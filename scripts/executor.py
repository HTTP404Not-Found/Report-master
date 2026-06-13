"""scripts/executor.py — Report-master Stage 2 Executor CLI helper.

對應 `references/executor-base.md` v1 + `tasks.md` T3-2。

用途：
- 逐節生成 HTML（每節都跑 quality_checker）
- 自動接續 `metadata.progress`（auto-resume / 斷點續傳）
- 寫入 `report_output/section_N.html`
- 觸發 Stage 3 stub（html_to_pdf + html_to_docx）於最後

CLI：
  python -m scripts.executor --lock <path> --output <dir>             # 跑全部
  python -m scripts.executor --lock <path> --output <dir> --section N  # 跑單節
  python -m scripts.executor --lock <path> --output <dir> --restart    # 強制從頭

本檔提供：
  1. Executor class（核心 API；吃 lock path，跑 pipeline）
  2. _generate_section_html_stub()：當 LLM 不可用時，產出合規 HTML 當 placeholder
     （仍可過 quality gate；給 integration test / 開發期 demo 用）
  3. CLI parser
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# 允許 CLI 直接執行（`python scripts/executor.py`）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.report_lock import (  # noqa: E402
    LockFormatError,
    LockMissingFieldsError,
    read_and_validate,
    read_lock_with_body,
    write_lock,
)
from scripts.quality_checker import (  # noqa: E402
    QualityCheckError,
    check_html,
    scan_html,
)

logger = logging.getLogger(__name__)


# ─── 例外 ────────────────────────────────────────────────────────────

class ExecutorError(Exception):
    """Executor 基底例外。"""


class ExecutorSectionError(ExecutorError):
    """單節生成 / 校驗失敗。"""


class ExecutorAbort(ExecutorError):
    """整個 pipeline 中止（recoverable，由 caller 決定是否重試）。"""


# ─── 預設 HTML 模板（stub 給 LLM 不可用情境） ───────────────────────

def _default_section_stub_html(
    section_index: int,
    section_title: str,
    *,
    body_font_size: int = 12,
    line_spacing: float = 1.5,
    extra_paragraphs: int = 2,
) -> str:
    """產生符合 shared-standards.md 的 section HTML stub。

    注意：
    - 不使用 display: flex / grid / position: absolute / ::before / ::after
    - 字體鎖死：'標楷體', 'Times New Roman', serif
    - 章節編號手寫（「第N章 xxx」/「N.M xxx」）

    Returns:
        完整 <!DOCTYPE html>...</html> 字串
    """
    chapter_num = _chapter_number_zh(section_index)
    sub_heading_nums = [
        f"{section_index}.{i}" for i in range(1, extra_paragraphs + 1)
    ]
    sub_titles = ["研究背景", "研究方法", "結果分析", "討論", "小結"][
        : extra_paragraphs
    ]

    sub_blocks = []
    for n, t in zip(sub_heading_nums, sub_titles):
        sub_blocks.append(
            f"""
<h2>{n} {t}</h2>
<p>本節為 <strong>Report-master Executor</strong> 自動產生的 placeholder 內容，"
"對應 <em>{section_title}</em> 的子節 {n}。正式版將由 LLM 根據 report_spec.md 與 "
"glossary.md 生成。</p>
<p>本 stub 通過 <code>quality_checker.check()</code> 校驗（符合 shared-standards.md "
"允許清單），可作為 Stage 3 渲染測試輸入。</p>
"""
        )

    body = (
        f"""
<h1>第{chapter_num}章 {section_title}</h1>

<p>本文件由 <strong>Report-master Executor</strong>（Stage 2）逐節生成，"
"對應 <code>report_lock.md</code> 中 <code>sections[{section_index - 1}]</code>。</p>
<p>本節為 stub 內容：當 LLM 不可用或開發期 demo 時，Executor 會呼叫 <code>_default_section_stub_html()</code>"
"產生符合 <code>docs/shared-standards.md</code> 的 placeholder HTML，"
"供 <code>quality_checker.py</code> 過門 + Stage 3 工程轉換測試用。</p>
"""
        + "".join(sub_blocks)
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>第{chapter_num}章 {section_title}</title>
<style>
  body {{ font-family: '標楷體', 'Times New Roman', serif; font-size: {body_font_size}pt; line-height: {line_spacing}; margin: 2.5cm; }}
  h1 {{ font-family: '標楷體', 'Times New Roman', serif; font-size: 18pt; font-weight: bold; margin-top: 1em; }}
  h2 {{ font-family: '標楷體', 'Times New Roman', serif; font-size: 16pt; font-weight: bold; margin-top: 0.8em; }}
  h3 {{ font-family: '標楷體', 'Times New Roman', serif; font-size: 14pt; font-weight: bold; margin-top: 0.6em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #999; padding: 0.5em; text-align: left; }}
  th {{ background-color: #f0f0f0; font-weight: bold; }}
  .caption {{ text-align: center; font-size: 10pt; margin-top: 0.3em; }}
  a {{ color: #1a73e8; text-decoration: underline; }}
  code {{ font-family: 'Times New Roman', monospace; background-color: #f5f5f5; padding: 0.1em 0.3em; }}
</style>
</head>
<body>
{body.strip()}
</body>
</html>
"""
    return html


def _chapter_number_zh(n: int) -> str:
    """1 -> 一, 2 -> 二, ..., 10 -> 十。簡單中文數字轉換（支援 1~20）。"""
    mapping = {
        1: "一", 2: "二", 3: "三", 4: "四", 5: "五",
        6: "六", 7: "七", 8: "八", 9: "九", 10: "十",
        11: "十一", 12: "十二", 13: "十三", 14: "十四", 15: "十五",
        16: "十六", 17: "十七", 18: "十八", 19: "十九", 20: "二十",
    }
    if n in mapping:
        return mapping[n]
    return str(n)


# ─── Executor class ──────────────────────────────────────────────────

@dataclass
class SectionResult:
    """單節執行結果。"""
    section_index: int  # 1-based
    section_title: str
    html_path: str
    bytes: int
    quality_passed: bool
    quality_violations: List[Dict[str, Any]] = field(default_factory=list)
    retries: int = 0
    error: Optional[str] = None


@dataclass
class ExecutorResult:
    """整個 pipeline 結果。"""
    passed: bool
    lock_path: str
    output_dir: str
    total_sections: int
    completed_sections: List[int] = field(default_factory=list)
    section_results: List[Dict[str, Any]] = field(default_factory=list)
    progress_written: bool = False
    stage3_stub_invoked: bool = False
    stage3_note: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Executor:
    """Report-master Stage 2 Executor.

    吃一份 `report_lock.md` 路徑，跑逐節 HTML 生成 + per-section quality gate。
    自動讀 `metadata.progress` 接續；`run()` 完成後把新的 progress 寫回 lock。

    Usage:
        >>> exe = Executor("path/to/report_lock.md", output_dir="report_output")
        >>> result = exe.run()
        >>> result.passed
        True
    """

    DEFAULT_OUTPUT_DIR = "report_output"
    DEFAULT_GLOSSARY_PATH = "glossary.md"
    DEFAULT_SPEC_PATH = "report_spec.md"

    def __init__(
        self,
        lock_path: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None,
        spec_path: Optional[Union[str, Path]] = None,
        glossary_path: Optional[Union[str, Path]] = None,
        *,
        max_retries: int = 2,
        skip_quality_gate: bool = False,
    ) -> None:
        self.lock_path = Path(lock_path)
        if not self.lock_path.exists():
            raise ExecutorAbort(f"lock 檔不存在：{self.lock_path}")
        # 讀 + 驗證（缺欄位 raise LockMissingFieldsError）
        self.lock_data = read_and_validate(str(self.lock_path))
        self.output_dir = Path(output_dir) if output_dir else Path(self.DEFAULT_OUTPUT_DIR)
        self.spec_path = Path(spec_path) if spec_path else Path(self.DEFAULT_SPEC_PATH)
        self.glossary_path = Path(glossary_path) if glossary_path else Path(self.DEFAULT_GLOSSARY_PATH)
        self.max_retries = max_retries
        self.skip_quality_gate = skip_quality_gate

    # ── 主要 API ────────────────────────────────────────────────────

    def run(self, restart: bool = False) -> ExecutorResult:
        """跑完整 pipeline（從 `metadata.progress` 自動接續，或從頭）。

        Args:
            restart: 若 True，忽略 progress，從 section 1 開始。

        Returns:
            ExecutorResult
        """
        ts = datetime.now().isoformat(timespec="seconds")
        result = ExecutorResult(
            passed=True,
            lock_path=str(self.lock_path),
            output_dir=str(self.output_dir),
            total_sections=len(self.lock_data.get("sections", [])),
            timestamp=ts,
        )

        sections = self.lock_data.get("sections", [])
        if not sections:
            result.passed = False
            result.errors.append("lock 內 sections 為空，無可生成內容。")
            return result

        # 決定起點
        start_from = self._start_section(restart=restart)

        # 逐節跑
        for idx, sec in enumerate(sections, 1):
            if idx < start_from:
                # 已完成，跳過
                continue
            try:
                sec_result = self.run_section(idx)
            except ExecutorSectionError as e:
                result.passed = False
                result.errors.append(f"[section {idx}] {e}")
                # 寫進 lock metadata.errors[] 供 debug
                self._record_error(idx, str(e))
                # 中止 pipeline（不再嘗試後續節）
                return result
            else:
                result.completed_sections.append(idx)
                result.section_results.append(asdict(sec_result))
                if not sec_result.quality_passed:
                    result.passed = False
                    result.errors.append(
                        f"[section {idx}] quality gate FAIL "
                        f"（{len(sec_result.quality_violations)} violations）"
                    )

        # 寫入 progress
        self._write_progress(result)
        result.progress_written = True

        # Stage 3 stub
        if result.passed:
            note = self._invoke_stage3_stub()
            result.stage3_stub_invoked = True
            result.stage3_note = note

        return result

    def run_section(self, section_index: int) -> SectionResult:
        """跑單節（section_index 是 1-based）。"""
        sections = self.lock_data.get("sections", [])
        if section_index < 1 or section_index > len(sections):
            raise ExecutorSectionError(
                f"section_index={section_index} 超出範圍 1..{len(sections)}"
            )
        section = sections[section_index - 1]
        title = section.get("title", f"section_{section_index}")
        # 決定輸出路徑
        section_path = self._section_output_path(section, section_index)

        body = self._load_context()
        prev_htmls = self._load_previous_htmls(section_index - 1)

        # 生成 + 校驗 + 重試
        html = None
        violations: List[Dict[str, Any]] = []
        retries = 0
        last_error: Optional[str] = None

        for attempt in range(self.max_retries + 1):
            try:
                html = self._generate_section_html(
                    section_index=section_index,
                    section_title=title,
                    lock=self.lock_data,
                    body=body,
                    prev_htmls=prev_htmls,
                    prior_violations=violations if attempt > 0 else None,
                )
            except Exception as e:  # LLM 失敗等
                last_error = f"generation failed: {e}"
                retries = attempt
                continue

            if self.skip_quality_gate:
                break

            report = scan_html(html, source=f"section_{section_index}.html")
            if report.passed:
                violations = []
                break
            else:
                violations = report.violations
                retries = attempt
                last_error = f"quality check failed: {len(violations)} violation(s)"

        if html is None:
            raise ExecutorSectionError(
                f"section {section_index} ({title}) 生成失敗：{last_error}"
            )

        if violations:
            # 重試上限仍 FAIL
            raise ExecutorSectionError(
                f"section {section_index} ({title}) quality BLOCKING after "
                f"{self.max_retries} retries: {len(violations)} violation(s)"
            )

        # 寫入
        section_path.parent.mkdir(parents=True, exist_ok=True)
        section_path.write_text(html, encoding="utf-8")

        return SectionResult(
            section_index=section_index,
            section_title=title,
            html_path=str(section_path),
            bytes=len(html.encode("utf-8")),
            quality_passed=True,
            quality_violations=[],
            retries=retries,
        )

    # ── 內部輔助 ────────────────────────────────────────────────────

    def _start_section(self, restart: bool) -> int:
        """決定從第幾節開始（auto-resume）。"""
        if restart:
            return 1
        progress = self.lock_data.get("metadata", {}).get("progress", {})
        if not progress:
            return 1
        if progress.get("status") == "completed":
            # 已跑完，預設從頭（除非 restart=False 但要重跑，這裡不支援）
            return 1
        completed = progress.get("completed_sections", [])
        if completed:
            return max(completed) + 1
        return progress.get("current_section", 0) + 1

    def _section_output_path(
        self, section: Dict[str, Any], section_index: int
    ) -> Path:
        """從 section.path 解析；若是相對路徑，掛在 output_dir 下。"""
        raw = section.get("path") or f"section_{section_index}.html"
        p = Path(raw)
        if not p.is_absolute():
            # 預設：output_dir / 檔名
            return self.output_dir / p.name
        return p

    def _load_context(self) -> Dict[str, Any]:
        """載入 spec + glossary（不存在的話回空字串）。"""
        spec = ""
        if self.spec_path.exists():
            spec = self.spec_path.read_text(encoding="utf-8")
        glossary = ""
        if self.glossary_path.exists():
            glossary = self.glossary_path.read_text(encoding="utf-8")
        return {"spec": spec, "glossary": glossary}

    def _load_previous_htmls(self, before_index: int) -> List[str]:
        """載入 < before_index 的所有 section HTML。"""
        out = []
        for i in range(1, before_index + 1):
            # 優先用 _section_output_path 的一致路徑
            sections = self.lock_data.get("sections", [])
            if i > len(sections):
                break
            section = sections[i - 1]
            p = self._section_output_path(section, i)
            if p.exists():
                out.append(p.read_text(encoding="utf-8"))
        return out

    def _generate_section_html(
        self,
        *,
        section_index: int,
        section_title: str,
        lock: Dict[str, Any],
        body: Dict[str, Any],
        prev_htmls: List[str],
        prior_violations: Optional[List[Dict[str, Any]]],
    ) -> str:
        """生成單節 HTML。

        在本 CLI helper 中，我們使用 stub 產生器（_default_section_stub_html）
        來確保 integration test / 開發期 demo 可以跑通。

        正式的 LLM 呼叫會在 production Executor 注入；本介面保持簡單以方便測試。
        """
        body_fmt = lock.get("formatting", {}).get("body", {})
        font_size = int(body_fmt.get("font_size", 12))
        line_spacing = float(lock.get("line_spacing", 1.5))

        # stub 產出
        html = _default_section_stub_html(
            section_index=section_index,
            section_title=section_title,
            body_font_size=font_size,
            line_spacing=line_spacing,
            extra_paragraphs=2,
        )

        # 若有 prior violations，記錄到 log（不修改 HTML——stub 本身已合規）
        if prior_violations:
            logger.warning(
                "section %d 重試：%d 違規，stub 不重生成 HTML 內容",
                section_index, len(prior_violations),
            )
        return html

    def _write_progress(self, result: ExecutorResult) -> None:
        """把 progress 寫回 lock。"""
        try:
            data, body_text = read_lock_with_body(str(self.lock_path))
        except (LockFormatError, LockMissingFieldsError) as e:
            logger.warning("讀 lock 失敗，progress 未寫入：%s", e)
            return

        meta = data.setdefault("metadata", {})
        progress = {
            "current_section": max(result.completed_sections) if result.completed_sections else 0,
            "total_sections": result.total_sections,
            "completed_sections": result.completed_sections,
            "last_updated": result.timestamp,
            "status": "completed" if result.passed and len(result.completed_sections) == result.total_sections else "in_progress",
        }
        meta["progress"] = progress
        try:
            write_lock(str(self.lock_path), data, body=body_text)
        except Exception as e:
            logger.warning("寫入 lock 失敗：%s", e)

    def _record_error(self, section_index: int, message: str) -> None:
        """把錯誤訊息寫進 lock.metadata.errors[]。"""
        try:
            data, body_text = read_lock_with_body(str(self.lock_path))
        except (LockFormatError, LockMissingFieldsError):
            return
        meta = data.setdefault("metadata", {})
        errors = meta.setdefault("errors", [])
        errors.append({
            "section": section_index,
            "message": message,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })
        try:
            write_lock(str(self.lock_path), data, body=body_text)
        except Exception:
            pass

    def _invoke_stage3_stub(self) -> str:
        """Stage 3 stub：呼叫 html_to_pdf + html_to_docx（若有安裝）。

        本 helper 僅 stub 觸發；不在本任務的核心範圍。
        """
        try:
            from scripts.html_to_pdf import html_to_pdf
            from scripts.html_to_docx import html_to_docx
            return "Stage 3 stub：html_to_pdf + html_to_docx 介面可用，呼叫見 report_gen.py"
        except ImportError as e:
            return f"Stage 3 stub 載入失敗：{e}"


# ─── CLI ─────────────────────────────────────────────────────────────

def _parse_sections(arg: str, total: int) -> List[int]:
    """解析 --section 參數（單一數字或 comma-separated）。"""
    parts = [p.strip() for p in arg.split(",") if p.strip()]
    out: List[int] = []
    for p in parts:
        try:
            n = int(p)
        except ValueError:
            raise ValueError(f"--section 解析失敗：{p!r}（需為整數）")
        if n < 1 or n > total:
            raise ValueError(f"--section 超出範圍：{n}（1..{total}）")
        out.append(n)
    return out


def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="report-master executor",
        description="Stage 2 Executor CLI helper（逐節 HTML + per-section quality gate）",
    )
    parser.add_argument(
        "--lock", "-l",
        type=Path,
        required=True,
        help="report_lock.md 路徑",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("report_output"),
        help="section HTML 輸出目錄（預設 report_output/）",
    )
    parser.add_argument(
        "--section", "-s",
        type=str,
        default=None,
        help="只跑指定節（1-based；可 comma-separated 跑多節）",
    )
    parser.add_argument(
        "--spec",
        type=Path,
        default=None,
        help="report_spec.md 路徑（預設 ./report_spec.md）",
    )
    parser.add_argument(
        "--glossary",
        type=Path,
        default=None,
        help="glossary.md 路徑（預設 ./glossary.md）",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="忽略 metadata.progress，從 section 1 開始",
    )
    parser.add_argument(
        "--skip-quality-gate",
        action="store_true",
        help="略過 quality_checker（危險，僅 debug）",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="quality 失敗時的最大重試次數（預設 2）",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="以 JSON 格式輸出結果",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        exe = Executor(
            lock_path=args.lock,
            output_dir=args.output,
            spec_path=args.spec,
            glossary_path=args.glossary,
            max_retries=args.max_retries,
            skip_quality_gate=args.skip_quality_gate,
        )
    except LockMissingFieldsError as e:
        print(str(e), file=sys.stderr)
        return 2
    except ExecutorAbort as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    # 跑單節 vs 跑全部
    if args.section:
        try:
            indices = _parse_sections(args.section, len(exe.lock_data.get("sections", [])))
        except ValueError as e:
            print(f"❌ {e}", file=sys.stderr)
            return 1
        results: List[SectionResult] = []
        all_ok = True
        for idx in indices:
            try:
                sr = exe.run_section(idx)
            except ExecutorSectionError as e:
                print(f"❌ section {idx}: {e}", file=sys.stderr)
                all_ok = False
                break
            results.append(sr)
            print(f"✅ [{idx}] {sr.section_title} — {sr.bytes} bytes, "
                  f"quality PASS (retries={sr.retries})")
        # 寫入 progress
        exe._write_progress(ExecutorResult(
            passed=all_ok,
            lock_path=str(args.lock),
            output_dir=str(args.output),
            total_sections=len(exe.lock_data.get("sections", [])),
            completed_sections=[r.section_index for r in results],
            timestamp=datetime.now().isoformat(timespec="seconds"),
        ))
        if args.json:
            print(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2))
        return 0 if all_ok else 3
    else:
        result = exe.run(restart=args.restart)
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"\n{'='*60}")
            print(f"Executor — {result.timestamp}")
            print(f"{'='*60}")
            print(f"  passed: {result.passed}")
            print(f"  total_sections: {result.total_sections}")
            print(f"  completed: {result.completed_sections}")
            if result.progress_written:
                print(f"  progress: 寫入 lock ✅")
            if result.stage3_stub_invoked:
                print(f"  stage3: {result.stage3_note}")
            if result.errors:
                print(f"  errors:")
                for e in result.errors:
                    print(f"    • {e}")
            print(f"{'='*60}")
        return 0 if result.passed else 3


if __name__ == "__main__":
    sys.exit(_cli())
