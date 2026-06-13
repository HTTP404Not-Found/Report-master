"""scripts/error_helper.py — Report-master error-handling CLI helper.

對應 `workflows/error-handling.md` v1 + `tasks.md` T3-12。

用途：
- 接收失敗的 error log / traceback / ErrorContext
- 規則引擎分類成 6 種 error type 之一：
  LOCK_MISMATCH / FONT_MISSING / SECTION_MISSING / API_ERROR / PARSE_ERROR / UNKNOWN
- 自動修復（API_ERROR retry、SECTION_MISSING 補跑、LOCK_MISMATCH 校驗）
- 產出 `report_output/error_report.md`（審計痕跡）
- append 到 `report_lock.metadata.errors[]`（給 Stage 2 之後 retry 用）

CLI：
  python -m scripts.error_helper --error-file <path>          # 分析 error log
  python -m scripts.error_helper --traceback "..."           # 直接給字串
  python -m scripts.error_helper --retry-count 5             # 設定 retry 次數
  python -m scripts.error_helper --json                       # JSON 輸出
  python -m scripts.error_helper --report <path>              # 自訂 error_report 路徑
  python -m scripts.error_helper --no-auto-fix                # 跳過自動修復
  python -m scripts.error_helper --lock <report_lock.md>     # 自動 append errors[]

Exit codes：
  0 = resolved（自動修復成功）
  1 = needs_manual（已寫 error_report；escalate 給人工）
  2 = argument error（缺 flag / 檔案不存在 / 路徑無效）

設計：
- ErrorClassifier：純 regex 規則引擎，無 LLM 依賴
- ErrorResolver：對每種 type 給自動修復策略
- ErrorReporter：產出 markdown 報告 + 寫 lock
- ErrorHelper：facade，串接 classify → resolve → report
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import traceback as tb_mod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# 允許 CLI 直接執行（`python scripts/error_helper.py`）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    import yaml
except ImportError as e:  # pragma: no cover
    raise ImportError("缺少 PyYAML，請先 `pip install pyyaml`") from e

from scripts.report_lock import (  # noqa: E402
    LockError,
    LockFormatError,
    LockMissingFieldsError,
    read_lock_with_body,
    write_lock,
)

logger = logging.getLogger(__name__)


# ─── 常數 ────────────────────────────────────────────────────────────

# 6 種 error type
ERROR_LOCK_MISMATCH = "LOCK_MISMATCH"
ERROR_FONT_MISSING = "FONT_MISSING"
ERROR_SECTION_MISSING = "SECTION_MISSING"
ERROR_API_ERROR = "API_ERROR"
ERROR_PARSE_ERROR = "PARSE_ERROR"
ERROR_UNKNOWN = "UNKNOWN"

ALL_ERROR_TYPES = (
    ERROR_LOCK_MISMATCH,
    ERROR_FONT_MISSING,
    ERROR_SECTION_MISSING,
    ERROR_API_ERROR,
    ERROR_PARSE_ERROR,
    ERROR_UNKNOWN,
)

SEVERITY_BLOCKING = "BLOCKING"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

EXIT_RESOLVED = 0
EXIT_NEEDS_MANUAL = 1
EXIT_ARG_ERROR = 2


# ─── 例外 ────────────────────────────────────────────────────────────

class ErrorHelperError(Exception):
    """error_helper 基底例外。"""


class ErrorHelperArgError(ErrorHelperError):
    """參數錯誤（缺 flag、檔案不存在等）。"""


# ─── Data classes ────────────────────────────────────────────────────

@dataclass
class ErrorContext:
    """標準化錯誤上下文（給 classifier / resolver 共用）。"""
    source: str = ""                              # "executor" / "quality_checker" / ...
    error_type_raw: str = ""                      # exception class name
    message: str = ""                             # str(exception)
    traceback: str = ""                           # traceback.format_exc()
    section_index: Optional[int] = None
    section_path: Optional[str] = None
    lock_path: Optional[str] = None
    html_excerpt: Optional[str] = None            # 失敗的 HTML 前 1KB
    exit_code: Optional[int] = None
    stderr: Optional[str] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    @classmethod
    def from_error_file(
        cls, error_file: Union[str, Path], *, section_index: Optional[int] = None
    ) -> "ErrorContext":
        """從 error log 檔讀取並建構 context。"""
        path = Path(error_file)
        if not path.exists():
            raise ErrorHelperArgError(f"error_file 不存在：{path}")
        text = path.read_text(encoding="utf-8", errors="replace")
        return cls.from_text(text, section_index=section_index)

    @classmethod
    def from_text(
        cls, text: str, *, section_index: Optional[int] = None
    ) -> "ErrorContext":
        """從 raw text（stderr / traceback / log）建構 context。"""
        ctx = cls(
            traceback=text,
            message=text.strip().splitlines()[-1] if text.strip() else "",
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            section_index=section_index,
        )
        # 嘗試從 traceback 推斷 exception class
        m = re.search(r"^([A-Z][A-Za-z0-9_.]*Error)\s*:", text, re.MULTILINE)
        if m:
            ctx.error_type_raw = m.group(1)
        # 嘗試從 message 推斷 section path
        m2 = re.search(r"(section_\d+\.html)", text)
        if m2:
            ctx.section_path = m2.group(1)
        # 嘗試推斷 exit code（若出現 "exit code" / "returncode"）
        m3 = re.search(r"(?:exit code|returncode)\s*[:=]?\s*(-?\d+)", text, re.IGNORECASE)
        if m3:
            try:
                ctx.exit_code = int(m3.group(1))
            except ValueError:
                pass
        return ctx

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ClassificationResult:
    """分類結果。"""
    error_type: str             # 6 種之一
    severity: str               # BLOCKING / warning / info
    matched_rule: str           # 命中的規則描述
    confidence: float           # 0.0 ~ 1.0
    needs_manual: bool          # 是否需要人工介入

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResolutionAttempt:
    """單次自動修復嘗試。"""
    action: str
    result: str                 # "success" / "fail" / "skipped"
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResolutionResult:
    """完整自動修復結果。"""
    resolved: bool
    attempts: List[ResolutionAttempt] = field(default_factory=list)
    needs_manual: bool = False
    next_action: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resolved": self.resolved,
            "attempts": [a.to_dict() for a in self.attempts],
            "needs_manual": self.needs_manual,
            "next_action": self.next_action,
        }


@dataclass
class ErrorReport:
    """完整處理結果（給 CLI / JSON / markdown 共用）。"""
    context: ErrorContext
    classification: ClassificationResult
    resolution: ResolutionResult
    report_markdown: str = ""
    report_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context": self.context.to_dict(),
            "classification": self.classification.to_dict(),
            "resolution": self.resolution.to_dict(),
            "report_path": self.report_path,
        }


# ─── Classifier（規則引擎） ─────────────────────────────────────────

# 規則定義：(error_type, severity, compiled_pattern, rule_description)
# 順序：先匹配先贏
_CLASSIFICATION_RULES: List[tuple] = [
    # LOCK_MISMATCH
    (
        ERROR_LOCK_MISMATCH, SEVERITY_BLOCKING,
        re.compile(
            r"(?:lock mismatch|lock_signature|signature 不一致"
            r"|signature mismatch|check_lock.*BLOCKING|lock drift)",
            re.IGNORECASE,
        ),
        "matched keyword: lock mismatch / signature 不一致",
    ),
    # FONT_MISSING
    (
        ERROR_FONT_MISSING, SEVERITY_BLOCKING,
        re.compile(
            r"(?:font-family.*not found|WeasyPrintError.*font"
            r"|failed to load font|missing font|font not found"
            r"|標楷體.*not found|Times New Roman.*not found)",
            re.IGNORECASE,
        ),
        "matched keyword: font not found / WeasyPrint font error",
    ),
    # API_ERROR
    (
        ERROR_API_ERROR, SEVERITY_BLOCKING,
        re.compile(
            r"(?:RateLimitError|APIError|APIConnectionError"
            r"|APITimeoutError|rate limit exceeded|quota exceeded"
            r"|API key|invalid api key|status code (?:401|429|503))",
            re.IGNORECASE,
        ),
        "matched keyword: API rate limit / quota / 401/429/503",
    ),
    # SECTION_MISSING
    (
        ERROR_SECTION_MISSING, SEVERITY_WARNING,
        re.compile(
            r"(?:FileNotFoundError.*section_\d+\.html"
            r"|section missing|section_\d+\.html.*not found"
            r"|missing section|disk.*section.*missing)",
            re.IGNORECASE,
        ),
        "matched keyword: section_*.html FileNotFoundError",
    ),
    # PARSE_ERROR
    (
        ERROR_PARSE_ERROR, SEVERITY_WARNING,
        re.compile(
            r"(?:JSONDecodeError|YAMLError|missing <!DOCTYPE"
            r"|missing </html>|HTML 結構不完整|parse error"
            r"|failed to parse|yaml.*scanner error)",
            re.IGNORECASE,
        ),
        "matched keyword: JSON/YAML/HTML parse error",
    ),
]


# 類別名稱 fallback 規則
_CLASS_NAME_FALLBACK: List[tuple] = [
    (re.compile(r"Lock|Signature|Drift", re.IGNORECASE), ERROR_LOCK_MISMATCH, SEVERITY_BLOCKING),
    (re.compile(r"WeasyPrint|Font", re.IGNORECASE), ERROR_FONT_MISSING, SEVERITY_BLOCKING),
    (re.compile(r"RateLimit|API|Connection|Timeout", re.IGNORECASE), ERROR_API_ERROR, SEVERITY_BLOCKING),
    (re.compile(r"FileNotFound.*section|FileNotFoundError.*\.html", re.IGNORECASE), ERROR_SECTION_MISSING, SEVERITY_WARNING),
    (re.compile(r"JSON|YAML|Parse|YAMLError", re.IGNORECASE), ERROR_PARSE_ERROR, SEVERITY_WARNING),
]


class ErrorClassifier:
    """規則引擎分類器。純 regex，無 LLM 依賴。"""

    def classify(self, ctx: ErrorContext) -> ClassificationResult:
        # 把 message + traceback + stderr 拼起來給 regex 掃
        haystack_parts = [ctx.message or "", ctx.traceback or "", ctx.stderr or ""]
        haystack = "\n".join(haystack_parts)

        # 1. 主規則（順序匹配）
        for err_type, severity, pattern, rule_desc in _CLASSIFICATION_RULES:
            if pattern.search(haystack):
                return ClassificationResult(
                    error_type=err_type,
                    severity=severity,
                    matched_rule=rule_desc,
                    confidence=0.95,
                    needs_manual=(severity == SEVERITY_BLOCKING),
                )

        # 2. 類別名稱 fallback
        if ctx.error_type_raw:
            for pattern, err_type, severity in _CLASS_NAME_FALLBACK:
                if pattern.search(ctx.error_type_raw):
                    return ClassificationResult(
                        error_type=err_type,
                        severity=severity,
                        matched_rule=f"matched exception class: {ctx.error_type_raw}",
                        confidence=0.7,
                        needs_manual=(severity == SEVERITY_BLOCKING),
                    )

        # 3. UNKNOWN
        return ClassificationResult(
            error_type=ERROR_UNKNOWN,
            severity=SEVERITY_BLOCKING,
            matched_rule="no rule matched",
            confidence=0.0,
            needs_manual=True,
        )


# ─── Resolver（自動修復） ───────────────────────────────────────────

class ErrorResolver:
    """對 6 種 error type 給自動修復策略。"""

    DEFAULT_RETRY_COUNT = 3

    def __init__(self, *, retry_count: int = DEFAULT_RETRY_COUNT, no_auto_fix: bool = False):
        self.retry_count = max(0, retry_count)
        self.no_auto_fix = no_auto_fix

    def resolve(
        self, ctx: ErrorContext, classification: ClassificationResult
    ) -> ResolutionResult:
        """根據 classification 跑對應的自動修復。"""
        if self.no_auto_fix:
            return ResolutionResult(
                resolved=False,
                attempts=[ResolutionAttempt(
                    action="skip auto-fix (--no-auto-fix)",
                    result="skipped",
                    note="user requested manual handling",
                )],
                needs_manual=True,
                next_action=self._next_action_for(classification.error_type, ctx),
            )

        method_name = f"_resolve_{classification.error_type.lower()}"
        method = getattr(self, method_name, self._resolve_unknown)
        return method(ctx, classification)

    # ── 各類型處置 ────────────────────────────────────────────────

    def _resolve_lock_mismatch(
        self, ctx: ErrorContext, cls: ClassificationResult
    ) -> ResolutionResult:
        attempts: List[ResolutionAttempt] = []
        # 1. 若有 lock_path → 嘗試重新校驗（檢查 schema + 重新計算 signature）
        if ctx.lock_path:
            lock_p = Path(ctx.lock_path)
            if lock_p.exists():
                try:
                    data, body = read_lock_with_body(str(lock_p))
                    attempts.append(ResolutionAttempt(
                        action="reload lock + validate schema",
                        result="success",
                        note=f"lock valid: {len(data.get('sections', []))} sections",
                    ))
                    # 把現 lock 算 signature 寫入 progress（如缺）
                    from scripts.resume_helper import lock_signature
                    sig = lock_signature(data)
                    meta = data.setdefault("metadata", {})
                    progress = meta.get("progress", {})
                    old_sig = progress.get("lock_signature")
                    progress["lock_signature"] = sig
                    progress["last_updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    meta["progress"] = progress
                    try:
                        write_lock(str(lock_p), data, body=body)
                        attempts.append(ResolutionAttempt(
                            action=f"update lock.metadata.progress.lock_signature",
                            result="success",
                            note=f"old={old_sig} new={sig}",
                        ))
                    except Exception as e:  # noqa: BLE001
                        attempts.append(ResolutionAttempt(
                            action="update lock signature",
                            result="fail",
                            note=str(e),
                        ))
                except LockMissingFieldsError as e:
                    attempts.append(ResolutionAttempt(
                        action="reload lock",
                        result="fail",
                        note=f"missing fields: {e.missing}",
                    ))
            else:
                attempts.append(ResolutionAttempt(
                    action="reload lock",
                    result="fail",
                    note=f"lock_path not found: {lock_p}",
                ))
        else:
            attempts.append(ResolutionAttempt(
                action="reload lock",
                result="skipped",
                note="no lock_path provided",
            ))

        # LOCK_MISMATCH 的最終決定權在 user：是否要 revise / 重跑 Stage 1
        return ResolutionResult(
            resolved=False,
            attempts=attempts,
            needs_manual=True,
            next_action=(
                "lock 已重新校驗；請決定：\n"
                "  (a) 跑 revise 修補受影響的 section：\n"
                "      python -m scripts.revise_helper --section <N> --instruction '...' --write\n"
                "  (b) 重跑 Stage 1 (Strategist) 重新產 lock：\n"
                "      python -m scripts.strategist --project-dir <dir>\n"
                "  (c) 保留現狀，使用 resume_helper 接續：\n"
                "      python -m scripts.resume_helper --lock <lock.md> --run"
            ),
        )

    def _resolve_font_missing(
        self, ctx: ErrorContext, cls: ClassificationResult
    ) -> ResolutionResult:
        attempts: List[ResolutionAttempt] = []
        # 1. 檢查 fonts/ 目錄缺哪個字體
        fonts_dir = _PROJECT_ROOT / "fonts"
        missing: List[str] = []
        present: List[str] = []
        for f in ("標楷體.ttf", "Times New Roman.ttf", "NotoSansCJK-Regular.ttc"):
            p = fonts_dir / f
            if p.exists():
                present.append(f)
            else:
                missing.append(f)
        if missing:
            attempts.append(ResolutionAttempt(
                action="check fonts/ directory",
                result="fail",
                note=f"missing: {missing}, present: {present}",
            ))
        else:
            attempts.append(ResolutionAttempt(
                action="check fonts/ directory",
                result="success",
                note=f"all required fonts present: {present}",
            ))

        return ResolutionResult(
            resolved=not bool(missing),
            attempts=attempts,
            needs_manual=bool(missing),
            next_action=(
                "字體缺失，請執行：\n"
                "  (a) macOS：cp /System/Library/Fonts/Supplemental/Kaiti.ttc fonts/標楷體.ttf\n"
                "  (b) Linux (Debian/Ubuntu)：sudo apt install fonts-noto-cjk\n"
                "      然後 ln -s /usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc fonts/標楷體.ttf\n"
                "  (c) Windows：從 C:\\Windows\\Fonts\\kaiu.ttf 複製到 fonts/標楷體.ttf\n"
                "  下載 Times New Roman：https://fonts.google.com/specimen/Tinos\n"
                "  然後重跑 Stage 3：python -m scripts.report_gen render"
            ),
        )

    def _resolve_section_missing(
        self, ctx: ErrorContext, cls: ClassificationResult
    ) -> ResolutionResult:
        attempts: List[ResolutionAttempt] = []
        # 嘗試用 resume_helper 算 plan
        if ctx.lock_path:
            try:
                from scripts.resume_helper import ResumeHelper
                helper = ResumeHelper(lock_path=ctx.lock_path)
                plan = helper.plan()
                attempts.append(ResolutionAttempt(
                    action="resume_helper.plan()",
                    result="success" if plan.will_run else "noop",
                    note=f"will_run={plan.will_run}, will_skip={plan.will_skip}",
                ))
                if plan.will_run:
                    return ResolutionResult(
                        resolved=False,  # 仍需使用者 --run 確認
                        attempts=attempts,
                        needs_manual=False,
                        next_action=(
                            f"建議補跑缺的節：\n"
                            f"  python -m scripts.resume_helper --lock {ctx.lock_path} --run\n"
                            f"  （將跑 sections {plan.will_run}）"
                        ),
                    )
            except Exception as e:  # noqa: BLE001
                attempts.append(ResolutionAttempt(
                    action="resume_helper.plan()",
                    result="fail",
                    note=str(e),
                ))
        else:
            attempts.append(ResolutionAttempt(
                action="resume_helper.plan()",
                result="skipped",
                note="no lock_path provided",
            ))

        return ResolutionResult(
            resolved=False,
            attempts=attempts,
            needs_manual=True,
            next_action=(
                "請提供 lock_path 或手動跑：\n"
                "  python -m scripts.resume_helper --lock <report_lock.md> --run"
            ),
        )

    def _resolve_api_error(
        self, ctx: ErrorContext, cls: ClassificationResult
    ) -> ResolutionResult:
        attempts: List[ResolutionAttempt] = []
        # 1. retry with exponential backoff（模擬；不真的呼叫 LLM）
        for i in range(self.retry_count):
            attempts.append(ResolutionAttempt(
                action=f"retry #{i + 1}/{self.retry_count} (exponential backoff)",
                result="fail",  # 預設假設失敗；實際由外層決定
                note="retry strategy stubbed; check actual API response",
            ))
        # 2. 切換 model（建議）
        attempts.append(ResolutionAttempt(
            action="switch model gpt-4 → gpt-3.5-turbo",
            result="skipped",
            note="manual decision required",
        ))

        return ResolutionResult(
            resolved=False,
            attempts=attempts,
            needs_manual=True,
            next_action=(
                "LLM API 錯誤，建議：\n"
                "  1. 確認 API key 環境變數有效：\n"
                "     echo $OPENAI_API_KEY  # 或 $ANTHROPIC_API_KEY\n"
                "  2. 等 quota 重置（OpenAI: https://platform.openai.com/account/limits）\n"
                "  3. 或換 provider：\n"
                "     export LLM_PROVIDER=anthropic\n"
                "     export ANTHROPIC_API_KEY=sk-ant-...\n"
                "  4. 然後重跑：\n"
                "     python -m scripts.resume_helper --lock <report_lock.md> --run"
            ),
        )

    def _resolve_parse_error(
        self, ctx: ErrorContext, cls: ClassificationResult
    ) -> ResolutionResult:
        attempts: List[ResolutionAttempt] = []
        # 1. retry with stricter prompt（stub）
        attempts.append(ResolutionAttempt(
            action="retry with stricter prompt template (force DOCTYPE/structure)",
            result="skipped",
            note="LLM-dependent; requires user re-run",
        ))

        return ResolutionResult(
            resolved=False,
            attempts=attempts,
            needs_manual=True,
            next_action=(
                "解析錯誤，建議：\n"
                "  1. 檢查 LLM 是否回傳完整 HTML（<!DOCTYPE> ... </html>）\n"
                "  2. 加 retry + 換更嚴的 prompt 範本重跑：\n"
                "     python -m scripts.resecutor --lock <lock.md> --section <N> --retry\n"
                "  3. 或手動修 HTML 後用 revise 寫回：\n"
                "     python -m scripts.revise_helper --section <N> --instruction 'fix DOCTYPE' --write"
            ),
        )

    def _resolve_unknown(
        self, ctx: ErrorContext, cls: ClassificationResult
    ) -> ResolutionResult:
        return ResolutionResult(
            resolved=False,
            attempts=[ResolutionAttempt(
                action="classify + escalate",
                result="skipped",
                note="UNKNOWN error type; cannot auto-fix",
            )],
            needs_manual=True,
            next_action=(
                "未知錯誤，請人工檢查：\n"
                "  1. 檢視 traceback（在 error_report.md）\n"
                "  2. 若是新錯誤類型，請在 workflows/error-handling.md §3.3 新增規則\n"
                "  3. 或在 GitHub issue 回報：https://github.com/HTTP404Not-Found/Report-master/issues"
            ),
        )

    def _next_action_for(self, err_type: str, ctx: ErrorContext) -> str:
        """給 ErrorReport 用；fallback 文字。"""
        return f"請人工處理 {err_type} 類型錯誤（見 error_report.md）"


# ─── Reporter ────────────────────────────────────────────────────────

class ErrorReporter:
    """產出 markdown 報告 + 寫 lock。"""

    DEFAULT_REPORT_PATH = "report_output/error_report.md"

    def __init__(self, report_path: Union[str, Path] = DEFAULT_REPORT_PATH):
        self.report_path = Path(report_path)

    def build_markdown(
        self,
        ctx: ErrorContext,
        cls: ClassificationResult,
        res: ResolutionResult,
    ) -> str:
        lines: List[str] = []
        lines.append("# Error Report")
        lines.append("")
        lines.append(f"_產生：Report-master error-handling workflow_")
        lines.append(f"_時間：{ctx.timestamp}_")
        lines.append("")
        # 摘要
        lines.append("## 摘要")
        lines.append("")
        lines.append(f"**Error Type:** `{cls.error_type}`")
        lines.append(f"**Severity:** {cls.severity}")
        lines.append(f"**Source:** `{ctx.source or '(unknown)'}`")
        lines.append(f"**Resolved:** {res.resolved}")
        lines.append(f"**Needs Manual:** {res.needs_manual}")
        lines.append(f"**Matched Rule:** {cls.matched_rule}")
        lines.append(f"**Confidence:** {cls.confidence:.2f}")
        lines.append("")
        # 上下文
        lines.append("## 上下文")
        lines.append("")
        if ctx.section_index is not None:
            lines.append(f"- Section: {ctx.section_index}")
        if ctx.section_path:
            lines.append(f"- Section path: `{ctx.section_path}`")
        if ctx.lock_path:
            lines.append(f"- Lock: `{ctx.lock_path}`")
        if ctx.exit_code is not None:
            lines.append(f"- Exit code: {ctx.exit_code}")
        if ctx.message:
            lines.append("")
            lines.append("**Message:**")
            lines.append("```")
            # 截斷過長的 message
            msg = ctx.message if len(ctx.message) < 600 else ctx.message[:600] + "...(truncated)"
            lines.append(msg)
            lines.append("```")
        lines.append("")
        # 自動修復嘗試
        lines.append("## 自動修復嘗試")
        lines.append("")
        if not res.attempts:
            lines.append("_（無 — 因 UNKNOWN 或 no-auto-fix）_")
        else:
            lines.append("| # | 動作 | 結果 | 備註 |")
            lines.append("|---|------|------|------|")
            for i, a in enumerate(res.attempts, 1):
                lines.append(f"| {i} | {a.action} | {a.result} | {a.note} |")
        lines.append("")
        # next action
        lines.append("## 建議 next action")
        lines.append("")
        if res.next_action:
            lines.append("```")
            lines.append(res.next_action)
            lines.append("```")
        else:
            lines.append("_（無）_")
        lines.append("")
        # traceback（可選）
        if ctx.traceback:
            lines.append("## Traceback（前 2KB）")
            lines.append("")
            lines.append("```")
            tb_text = ctx.traceback if len(ctx.traceback) < 2000 else ctx.traceback[:2000] + "...(truncated)"
            lines.append(tb_text)
            lines.append("```")
            lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("_本檔由 `scripts.error_helper` 自動產生；不要手動編輯後重跑（會被覆蓋）。_")
        return "\n".join(lines)

    def write(
        self,
        ctx: ErrorContext,
        cls: ClassificationResult,
        res: ResolutionResult,
    ) -> str:
        """寫 markdown 到磁碟。回傳寫入路徑。"""
        md = self.build_markdown(ctx, cls, res)
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(md, encoding="utf-8")
        return str(self.report_path)

    def append_to_lock(
        self,
        cls: ClassificationResult,
        ctx: ErrorContext,
        lock_path: Optional[Union[str, Path]] = None,
    ) -> bool:
        """把本次錯誤 append 到 lock.metadata.errors[]。回傳是否成功。"""
        target = lock_path or ctx.lock_path
        if not target:
            return False
        p = Path(target)
        if not p.exists():
            return False
        try:
            data, body = read_lock_with_body(str(p))
        except (LockFormatError, LockMissingFieldsError):
            return False
        meta = data.setdefault("metadata", {})
        errors = meta.get("errors", [])
        if not isinstance(errors, list):
            errors = []
        errors.append({
            "timestamp": ctx.timestamp,
            "error_type": cls.error_type,
            "severity": cls.severity,
            "source": ctx.source,
            "message": ctx.message[:500] if ctx.message else "",
            "resolved": False,
        })
        meta["errors"] = errors
        data["metadata"] = meta
        try:
            write_lock(str(p), data, body=body)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("寫 lock errors 失敗：%s", e)
            return False


# ─── Facade ──────────────────────────────────────────────────────────

class ErrorHelper:
    """Report-master error-handling helper。

    使用方式：
        >>> helper = ErrorHelper()
        >>> report = helper.handle_error_file("/tmp/stderr.log")
        >>> print(report.classification.error_type)  # "API_ERROR"
        >>> print(report.report_path)  # "report_output/error_report.md"
    """

    DEFAULT_REPORT_PATH = "report_output/error_report.md"
    DEFAULT_RETRY_COUNT = 3

    def __init__(
        self,
        *,
        retry_count: int = DEFAULT_RETRY_COUNT,
        no_auto_fix: bool = False,
        report_path: Union[str, Path] = DEFAULT_REPORT_PATH,
    ):
        self.classifier = ErrorClassifier()
        self.resolver = ErrorResolver(retry_count=retry_count, no_auto_fix=no_auto_fix)
        self.reporter = ErrorReporter(report_path=report_path)
        self.retry_count = retry_count
        self.no_auto_fix = no_auto_fix

    # ── 對外 API ────────────────────────────────────────────────────

    def handle_error_file(
        self,
        error_file: Union[str, Path],
        *,
        source: str = "",
        section_index: Optional[int] = None,
        lock_path: Optional[Union[str, Path]] = None,
    ) -> ErrorReport:
        ctx = ErrorContext.from_error_file(error_file, section_index=section_index)
        ctx.source = source or ctx.source or Path(error_file).name
        if lock_path:
            ctx.lock_path = str(lock_path)
        return self._run(ctx)

    def handle_traceback(
        self,
        traceback_text: str,
        *,
        source: str = "traceback",
        section_index: Optional[int] = None,
        lock_path: Optional[Union[str, Path]] = None,
        message: str = "",
    ) -> ErrorReport:
        ctx = ErrorContext.from_text(traceback_text, section_index=section_index)
        ctx.source = source
        if message:
            ctx.message = message
        if lock_path:
            ctx.lock_path = str(lock_path)
        return self._run(ctx)

    def _run(self, ctx: ErrorContext) -> ErrorReport:
        # 1. 分類
        cls = self.classifier.classify(ctx)
        # 2. 自動修復
        res = self.resolver.resolve(ctx, cls)
        # 3. 產出 markdown
        md = self.reporter.build_markdown(ctx, cls, res)
        # 4. 寫磁碟
        written_path = self.reporter.write(ctx, cls, res)
        # 5. append 到 lock（如有）
        self.reporter.append_to_lock(cls, ctx)
        return ErrorReport(
            context=ctx,
            classification=cls,
            resolution=res,
            report_markdown=md,
            report_path=written_path,
        )


# ─── CLI 印出 helper ────────────────────────────────────────────────

def format_report_for_cli(report: ErrorReport) -> str:
    """給 CLI 印出的人類可讀字串。"""
    cls = report.classification
    res = report.resolution
    ctx = report.context
    lines: List[str] = []
    lines.append(f"\n🔍 Error Helper — 分析 {'成功' if res.resolved else '完成（需人工）'}")
    lines.append(f"   source: {ctx.source or '(unknown)'}")
    if ctx.section_index is not None:
        lines.append(f"   section: {ctx.section_index}")
    if ctx.lock_path:
        lines.append(f"   lock: {ctx.lock_path}")
    lines.append("")
    severity_emoji = {
        "BLOCKING": "❌", "warning": "⚠️", "info": "ℹ️",
    }.get(cls.severity, "❓")
    lines.append(
        f"{severity_emoji} [{cls.error_type}] {cls.severity} — {cls.matched_rule}"
    )
    if ctx.message:
        msg_short = ctx.message if len(ctx.message) < 200 else ctx.message[:200] + "..."
        lines.append(f"   message: {msg_short}")
    lines.append("")
    # 自動修復
    if res.attempts:
        lines.append("🔧 自動修復嘗試:")
        for i, a in enumerate(res.attempts, 1):
            symbol = {"success": "✓", "fail": "✗", "skipped": "⊘"}.get(a.result, "?")
            lines.append(f"   [{symbol} {i}/{len(res.attempts)}] {a.action}: {a.result}")
            if a.note:
                lines.append(f"        {a.note}")
        lines.append("")
    # next action
    lines.append("💡 建議 next action:")
    for line in res.next_action.splitlines():
        lines.append(f"   {line}")
    lines.append("")
    lines.append(f"📄 error_report: {report.report_path}")
    lines.append("")
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────

def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="report-master error-helper",
        description=(
            "錯誤分類 + 自動修復 + 報告產出 CLI helper。"
            "接收 error log / traceback，分類成 6 種 error type 之一並嘗試自動修復。"
        ),
    )
    parser.add_argument(
        "--error-file", "-e",
        type=Path,
        default=None,
        help="error log 檔路徑",
    )
    parser.add_argument(
        "--traceback", "-t",
        type=str,
        default=None,
        help="直接給 traceback 字串",
    )
    parser.add_argument(
        "--retry-count", "-r",
        type=int,
        default=ErrorHelper.DEFAULT_RETRY_COUNT,
        help=f"API_ERROR 自動修復的 retry 次數（預設 {ErrorHelper.DEFAULT_RETRY_COUNT}）",
    )
    parser.add_argument(
        "--no-auto-fix",
        action="store_true",
        help="跳過自動修復，僅分類與報告",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(ErrorHelper.DEFAULT_REPORT_PATH),
        help=f"error_report 輸出路徑（預設 {ErrorHelper.DEFAULT_REPORT_PATH}）",
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=None,
        help="lock 檔路徑（會自動 append metadata.errors[]）",
    )
    parser.add_argument(
        "--source", "-s",
        type=str,
        default="",
        help="錯誤來源描述（給 ErrorContext.source）",
    )
    parser.add_argument(
        "--section",
        type=int,
        default=None,
        help="對應的 section 編號（1-based）",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="以 JSON 格式輸出",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="只印最終 summary 行",
    )
    return parser


def _cli() -> int:
    parser = _build_argparser()
    args = parser.parse_args()

    # 檢查：--error-file 與 --traceback 至少要有一個
    if not args.error_file and not args.traceback:
        parser.error("必須指定 --error-file 或 --traceback 其中之一")

    # 檢查 --error_file 是否存在（若提供）
    if args.error_file and not args.error_file.exists():
        print(f"❌ error_file 不存在：{args.error_file}", file=sys.stderr)
        return EXIT_ARG_ERROR

    helper = ErrorHelper(
        retry_count=args.retry_count,
        no_auto_fix=args.no_auto_fix,
        report_path=args.report,
    )

    try:
        if args.error_file:
            report = helper.handle_error_file(
                args.error_file,
                source=args.source,
                section_index=args.section,
                lock_path=args.lock,
            )
        else:
            assert args.traceback is not None
            report = helper.handle_traceback(
                args.traceback,
                source=args.source or "traceback",
                section_index=args.section,
                lock_path=args.lock,
            )
    except ErrorHelperArgError as e:
        print(f"❌ {e}", file=sys.stderr)
        return EXIT_ARG_ERROR
    except (LockFormatError, LockMissingFieldsError) as e:
        print(f"❌ lock 錯誤：{e}", file=sys.stderr)
        return EXIT_ARG_ERROR

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    elif args.quiet:
        print(json.dumps({
            "error_type": report.classification.error_type,
            "severity": report.classification.severity,
            "resolved": report.resolution.resolved,
            "needs_manual": report.resolution.needs_manual,
            "report_path": report.report_path,
        }, ensure_ascii=False))
    else:
        print(format_report_for_cli(report))

    return EXIT_RESOLVED if report.resolution.resolved else EXIT_NEEDS_MANUAL


if __name__ == "__main__":
    sys.exit(_cli())