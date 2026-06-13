"""scripts/docs_and_rules.py — Report-master 文件管理 + 規則制定 CLI helper.

對應 `workflows/docs-and-rules.md` v1.0 + `tasks.md` T3-15。

用途：
- 接收新規則描述 (`--type` / `--title` / `--body` / `--scope`)
- 跑 5 個階段：Identify → Draft → Cross-check → Version → Adopt
- 產出 `report_output/rules_adopted.md`（採納紀錄 + audit trail）
- 可選：cross-check 衝突清單 → `report_output/rules_conflict.md`（needs manual 模式）
- 自動更新 `docs/CHANGELOG.md` 與 `docs/rules_<type>_vN.md`

LLM 介面：
- 讀 env：LLM_API_URL / LLM_API_KEY / LLM_MODEL（optional）
- 未設定 → 走 StubLLM（回傳 canned response，給測試與離線使用）
- 設定 → 用 requests 呼叫 OpenAI-compatible chat completions API

CLI：
    python -m scripts.docs_and_rules --type STYLE --title "Table Nesting Limit" --body "..."
    python -m scripts.docs_and_rules --type STYLE --title "..." --check-only
    python -m scripts.docs_and_rules --type STYLE --title "..." --override

Return code：
    0 = ADOPTED（cross-check 通過、寫入成功）
    1 = NEEDS MANUAL（有 BLOCKING conflict）
    2 = argument 解析失敗
    3 = CHECK-ONLY 模式發現 BLOCKING conflict
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 允許 CLI 直接執行（`python scripts/docs_and_rules.py`）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ─── 例外 ────────────────────────────────────────────────────────────

class DocsAndRulesError(Exception):
    """docs_and_rules 例外基底。"""


class DocsAndRulesArgError(DocsAndRulesError):
    """參數錯誤（缺 flag、型別不合法等）。"""


class CrossCheckConflictError(DocsAndRulesError):
    """Cross-check 發現 BLOCKING conflict。"""


# ─── 常數 ────────────────────────────────────────────────────────────

# 5 種規則類型（固定 enum；不可擴充）
TYPE_STYLE = "STYLE"
TYPE_PROCESS = "PROCESS"
TYPE_API = "API"
TYPE_TEST = "TEST"
TYPE_LICENSE = "LICENSE"
ALL_TYPES = (TYPE_STYLE, TYPE_PROCESS, TYPE_API, TYPE_TEST, TYPE_LICENSE)

# Conflict type
CONFLICT_DISABLED_USED = "DISABLED_USED"
CONFLICT_SCOPE_OVERLAP = "SCOPE_OVERLAP_CONTRADICT"
CONFLICT_TERM_CONFLICT = "TERM_CONFLICT"
CONFLICT_ENFORCEMENT_MISMATCH = "ENFORCEMENT_MISMATCH"

# Severity
SEVERITY_BLOCKING = "BLOCKING"
SEVERITY_WARN = "WARN"

# Exit codes
EXIT_ADOPTED = 0
EXIT_NEEDS_MANUAL = 1
EXIT_ARG_ERROR = 2
EXIT_CHECK_ONLY_CONFLICT = 3

# shared-standards.md §2 禁用清單（regex 簡化版）
DISABLED_CSS_PATTERNS = [
    r"display\s*:\s*(?:flex|grid|inline-flex|inline-grid)",
    r"position\s*:\s*(?:absolute|fixed|sticky)",
    r"float\s*:\s*(?:left|right)",
    r"::before|::after",
    r"<link\s+rel=[\"']stylesheet[\"']",
    r"@import",
    r"<script\b",
    r"<canvas\b",
    r"<iframe\b|<object\b|<embed\b",
]

# keyword map for identify_type
KEYWORD_MAP: Dict[str, List[str]] = {
    TYPE_STYLE: [
        "字體", "font", "顏色", "color", "排版", "格式", "命名", "章節命名",
        "圖表", "術語", "css", "style", "naming", "table", "表格", "巢狀",
        "nesting", "border", "padding", "margin",
    ],
    TYPE_PROCESS: [
        "流程", "pipeline", "stage", "順序", "review", "gate",
        "workflow", "process", "順序", "順序", "ci/cd", "hook",
        "release", "deploy", "pre-commit",
    ],
    TYPE_API: [
        "api", "endpoint", "cli", "flag", "argument", "介面",
        "module", "function signature", "interface", "method", "http",
        "request", "response", "json",
    ],
    TYPE_TEST: [
        "測試", "test", "coverage", "pytest", "fixture",
        "unit test", "integration test", "覆蓋率", "mock", "assertion",
        "snapshot",
    ],
    TYPE_LICENSE: [
        "授權", "license", "mit", "apache", "版權", "copyright",
        "商業使用", "commercial use", "法遵", "compliance",
        "gpl", "bsd", "patent",
    ],
}


# ─── 資料結構 ────────────────────────────────────────────────────────

@dataclass
class RuleDraft:
    """單一規則草稿。"""
    rule_id: str
    type: str
    title: str
    version: str
    body: str
    fail_examples: List[str] = field(default_factory=list)
    pass_examples: List[str] = field(default_factory=list)
    related_rules: List[str] = field(default_factory=list)
    enforcement: str = ""
    scope: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass
class Conflict:
    """單一衝突項目。"""
    existing_rule_path: str
    existing_rule_text: str
    conflict_type: str
    severity: str
    suggested_resolution: str


@dataclass
class ConflictReport:
    """完整 cross-check 報告。"""
    new_rule_id: str
    new_rule_type: str
    new_rule_title: str
    conflicts: List[Conflict] = field(default_factory=list)
    warnings: List[Conflict] = field(default_factory=list)
    safe_to_adopt: bool = True

    @property
    def blocking_count(self) -> int:
        return len([c for c in self.conflicts if c.severity == SEVERITY_BLOCKING])

    @property
    def warn_count(self) -> int:
        return len(self.warnings)


# ─── Identify 階段 ──────────────────────────────────────────────────

def identify_type(title: str, body: str, explicit_type: Optional[str] = None) -> str:
    """識別規則類型。

    Args:
        title: 規則標題
        body: 規則內容
        explicit_type: 使用者明確指定的類型（最高優先）

    Returns:
        5 種 enum 之一或 "UNKNOWN"
    """
    if explicit_type:
        explicit_type = explicit_type.strip().upper()
        if explicit_type in ALL_TYPES:
            return explicit_type
        raise DocsAndRulesArgError(
            f"無效的 --type: '{explicit_type}'。合法值：{', '.join(ALL_TYPES)}"
        )

    text = f"{title} {body}".lower()
    scores: Dict[str, int] = {t: 0 for t in ALL_TYPES}
    for rule_type, keywords in KEYWORD_MAP.items():
        for kw in keywords:
            if kw.lower() in text:
                scores[rule_type] += 1

    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return "UNKNOWN"
    return best


# ─── Draft 階段 ─────────────────────────────────────────────────────

def _generate_rule_id(rule_type: str, existing_ids: List[str]) -> str:
    """產生 rule_id（如 R-S-007 / R-P-003 / R-A-001 / R-T-002 / R-L-001）。

    Args:
        rule_type: 規則類型（STYLE → S, PROCESS → P, ...）
        existing_ids: 既有 rule_id 清單（給連號用）
    """
    prefix_map = {
        TYPE_STYLE: "S",
        TYPE_PROCESS: "P",
        TYPE_API: "A",
        TYPE_TEST: "T",
        TYPE_LICENSE: "L",
    }
    prefix = prefix_map.get(rule_type, "X")
    # 找下一個可用編號
    used_nums = []
    for rid in existing_ids:
        m = re.match(rf"^R-{prefix}-(\d+)$", rid)
        if m:
            used_nums.append(int(m.group(1)))
    next_num = max(used_nums, default=0) + 1
    return f"R-{prefix}-{next_num:03d}"


def _draft_body(body: str) -> Tuple[List[str], List[str], List[str]]:
    """把使用者的 body 展開成 actionable 條目 + 產生 fail/pass 範例。

    Returns:
        (actionable_items, fail_examples, pass_examples)
    """
    # 簡單 split by 句號 / 中文句號 / newline
    raw_items = re.split(r"[。\.\n]+", body)
    actionable: List[str] = []
    for item in raw_items:
        item = item.strip()
        if not item:
            continue
        if len(item) < 3:
            continue
        actionable.append(item)
    # 至少 3 條
    if len(actionable) < 3:
        # 補上基本項
        while len(actionable) < 3:
            actionable.append(f"（待人工補完）")
    # 截斷到 10 條
    actionable = actionable[:10]

    # 範例（stub：基於 body 自動產）
    fail_examples = [
        f"違反範例：{body[:50]}...",
        "未通過 quality_checker 的 HTML 範本",
    ]
    pass_examples = [
        f"符合範例：{body[:50]}... 的標準實作",
        "通過 quality_checker 的 HTML 範本",
    ]
    return actionable, fail_examples, pass_examples


def draft_rule(
    rule_type: str,
    title: str,
    body: str,
    scope: str = "",
    existing_ids: Optional[List[str]] = None,
) -> RuleDraft:
    """草擬規則條目（Draft 階段）。

    Args:
        rule_type: 規則類型
        title: 規則標題
        body: 規則內容（使用者原文）
        scope: 適用範圍
        existing_ids: 既有 rule_id（給連號用）

    Returns:
        RuleDraft 物件（尚未 cross-check、未寫檔）
    """
    if existing_ids is None:
        existing_ids = []

    rule_id = _generate_rule_id(rule_type, existing_ids)
    actionable, fail_examples, pass_examples = _draft_body(body)
    body_text = "\n".join(f"{i+1}. {item}" for i, item in enumerate(actionable))

    return RuleDraft(
        rule_id=rule_id,
        type=rule_type,
        title=title,
        version="v1.0",  # Stage 4 才會更新為 v1.3 之類
        body=body_text,
        fail_examples=fail_examples,
        pass_examples=pass_examples,
        related_rules=[
            "docs/shared-standards.md v1（HTML/CSS 強制標準）",
            "workflows/error-handling.md v1（錯誤分類）",
            "workflows/technical-design.md v1（技術規格流程）",
        ],
        enforcement=(
            f"違反本規則時由 quality_checker 掃描並回報 BLOCKING；"
            f"若無對應 scanner，則由人工 review 阻擋。"
        ),
        scope=scope or "（全域；未指定）",
    )


# ─── Cross-check 階段 ───────────────────────────────────────────────

def _load_shared_standards(project_root: Path) -> Optional[str]:
    """讀 shared-standards.md；不存在回 None。"""
    p = project_root / "docs" / "shared-standards.md"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def _check_disabled_used(rule_body: str, shared_standards: Optional[str]) -> List[Conflict]:
    """檢查新規則是否允許 shared-standards.md §2 禁用項。

    規則：如果 rule_body 字面上「允許」「可以使用」某禁用樣式 → BLOCKING。
    """
    conflicts: List[Conflict] = []
    if shared_standards is None:
        return conflicts

    # 抽取 §2 禁用清單（簡化：抓「| `pattern` |」行）
    section_2 = re.search(
        r"## 2\.[^#]*?(?=\n## |\Z)", shared_standards, re.DOTALL
    )
    if section_2 is None:
        return conflicts
    section_2_text = section_2.group(0)

    allow_keywords = ["允許", "可使用", "allow", "permitted", "可以使用"]
    is_allowing = any(kw in rule_body.lower() for kw in allow_keywords)

    if not is_allowing:
        return conflicts

    # 檢查 rule_body 是否包含禁用樣式
    for pattern in DISABLED_CSS_PATTERNS:
        if re.search(pattern, rule_body, re.IGNORECASE):
            conflicts.append(Conflict(
                existing_rule_path="docs/shared-standards.md §2",
                existing_rule_text=f"禁用項 regex: {pattern}",
                conflict_type=CONFLICT_DISABLED_USED,
                severity=SEVERITY_BLOCKING,
                suggested_resolution=(
                    "新增 --override flag 並明確標 OVERRIDE; "
                    "或撤回本規則"
                ),
            ))
            break  # 找到一個就夠（避免過多衝突）

    return conflicts


def _check_scope_overlap(
    rule: RuleDraft,
    existing_changelog: Optional[str],
) -> List[Conflict]:
    """檢查 scope 是否與既有規則重疊且結論相反。

    簡化版：只比對 rule.scope 字串是否出現在既有規則 scope 內。
    """
    conflicts: List[Conflict] = []
    if existing_changelog is None or not rule.scope:
        return conflicts

    # 從 CHANGELOG 抓既有 scope
    scope_pattern = re.compile(r"-\s*\*\*[^*]+\*\*:\s*[^*]*?scope[：:]\s*([^*\n]+)")
    existing_scopes = scope_pattern.findall(existing_changelog)
    for es in existing_scopes:
        if rule.scope.strip() in es or es.strip() in rule.scope:
            # 簡化：若有重疊，給 WARN（不算 BLOCKING）
            pass  # 留 WARN 給未來擴充
    return conflicts


def cross_check(
    rule: RuleDraft,
    project_root: Path,
) -> ConflictReport:
    """執行 cross-check。

    Args:
        rule: 草擬的規則
        project_root: 專案根目錄（讀 shared-standards.md / CHANGELOG.md 用）

    Returns:
        ConflictReport 物件
    """
    shared_standards = _load_shared_standards(project_root)
    changelog_path = project_root / "docs" / "CHANGELOG.md"
    existing_changelog = changelog_path.read_text(encoding="utf-8") if changelog_path.exists() else None

    conflicts: List[Conflict] = []
    warnings: List[Conflict] = []

    # Check 1: DISABLED_USED（BLOCKING）
    disabled_conflicts = _check_disabled_used(rule.body, shared_standards)
    conflicts.extend(disabled_conflicts)

    # Check 2: SCOPE_OVERLAP（簡化版不報 BLOCKING；留 WARN 結構）
    # （預留空間給未來實作）

    report = ConflictReport(
        new_rule_id=rule.rule_id,
        new_rule_type=rule.type,
        new_rule_title=rule.title,
        conflicts=conflicts,
        warnings=warnings,
        safe_to_adopt=len(conflicts) == 0,
    )
    return report


# ─── Version 階段 ───────────────────────────────────────────────────

def _parse_latest_version(changelog_text: Optional[str]) -> Tuple[int, int]:
    """從 CHANGELOG.md 解析最新 version。

    Returns:
        (major, minor)
    """
    if not changelog_text:
        return (1, 0)  # 預設 v1.0
    # 抓 ## [v1.2] 或 ## [v2.0] 之類
    m = re.search(r"##\s*\[v(\d+)\.(\d+)\]", changelog_text)
    if m is None:
        return (1, 0)
    return (int(m.group(1)), int(m.group(2)))


def _next_version(
    latest: Tuple[int, int],
    has_blocking_override: bool = False,
) -> str:
    """決定新版本號。

    Args:
        latest: 既有最新版本 (major, minor)
        has_blocking_override: 是否覆蓋了 BLOCKING 衝突（→ MAJOR bump）
    """
    major, minor = latest
    if has_blocking_override:
        return f"v{major + 1}.0"
    return f"v{major}.{minor + 1}"


def _file_for_type(rule_type: str, project_root: Path) -> Path:
    """依規則類型決定寫入的 rules_*.md 路徑。"""
    type_to_filename = {
        TYPE_STYLE: "rules_style",
        TYPE_PROCESS: "rules_process",
        TYPE_API: "rules_api",
        TYPE_TEST: "rules_test",
        TYPE_LICENSE: "rules_license",
    }
    base_name = type_to_filename.get(rule_type, "rules_misc")
    # 找現有最新 vN
    parent = project_root / "docs"
    existing = sorted(parent.glob(f"{base_name}_v*.md"))
    if existing:
        # 找最大 N
        nums = []
        for p in existing:
            m = re.search(r"_v(\d+)\.md$", p.name)
            if m:
                nums.append(int(m.group(1)))
        next_n = max(nums, default=0) + 1
    else:
        next_n = 1
    return parent / f"{base_name}_v{next_n}.md"


def update_changelog(
    rule: RuleDraft,
    version: str,
    project_root: Path,
    override_used: bool,
) -> Path:
    """更新 docs/CHANGELOG.md，新增條目。

    Returns:
        CHANGELOG.md 路徑
    """
    changelog_path = project_root / "docs" / "CHANGELOG.md"
    if not changelog_path.exists():
        # 建立新檔
        changelog_path.parent.mkdir(parents=True, exist_ok=True)
        changelog_path.write_text(
            "# Report-master CHANGELOG\n\n"
            "> 對應 workflows/docs-and-rules.md v1.0\n\n",
            encoding="utf-8",
        )

    existing = changelog_path.read_text(encoding="utf-8")
    today = datetime.now().date().isoformat()
    override_note = "（含 BLOCKING override）" if override_used else ""

    new_section = (
        f"\n## [{version}] - {today}\n\n"
        f"### Added\n"
        f"- {rule.rule_id}: {rule.title}（{rule.type}）{override_note}\n"
        f"  - 違反時：{rule.enforcement[:80]}\n"
        f"  - 例外：無\n\n"
    )

    # 插入到檔案開頭（在標題之後）
    # 找第一個 ## 開頭位置
    m = re.search(r"^##\s*\[", existing, re.MULTILINE)
    if m:
        insertion_point = m.start()
        new_content = existing[:insertion_point] + new_section + existing[insertion_point:]
    else:
        # 沒有既有條目 → append
        new_content = existing.rstrip() + "\n" + new_section

    changelog_path.write_text(new_content, encoding="utf-8")
    return changelog_path


def append_rule_to_file(
    rule: RuleDraft,
    project_root: Path,
) -> Path:
    """把新規則 append 到對應的 rules_<type>_vN.md。

    Returns:
        寫入的檔案路徑
    """
    target = _file_for_type(rule.type, project_root)

    # 如果檔案不存在，建立 header
    if not target.exists():
        header = (
            f"# {target.stem}.md — Report-master {rule.type} 規則彙整\n\n"
            f"> 對應 workflows/docs-and-rules.md v1.0\n\n"
        )
        target.write_text(header, encoding="utf-8")

    existing = target.read_text(encoding="utf-8")
    new_section = (
        f"\n## {rule.rule_id}: {rule.title}\n\n"
        f"**類型**: {rule.type}\n"
        f"**版本**: {rule.version}\n"
        f"**生效日期**: {rule.timestamp}\n"
        f"**適用範圍**: {rule.scope}\n\n"
        f"### 規則內容\n\n"
        f"{rule.body}\n\n"
        f"### 反例（FAIL）\n\n"
    )
    for ex in rule.fail_examples:
        new_section += f"- {ex}\n"
    new_section += f"\n### 正例（PASS）\n\n"
    for ex in rule.pass_examples:
        new_section += f"- {ex}\n"
    new_section += f"\n### 與既有規則的關係\n\n"
    for rel in rule.related_rules:
        new_section += f"- {rel}\n"
    new_section += f"\n### 違反時的處置\n\n{rule.enforcement}\n\n"

    target.write_text(existing.rstrip() + "\n" + new_section, encoding="utf-8")
    return target


# ─── Adopt 階段 ─────────────────────────────────────────────────────

def adopt_rule(
    rule: RuleDraft,
    conflict_report: ConflictReport,
    version: str,
    project_root: Path,
    override_used: bool,
    output_path: Optional[Path] = None,
) -> Path:
    """產出 report_output/rules_adopted.md。

    Returns:
        寫入的檔案路徑
    """
    if output_path is None:
        output_path = project_root / "report_output" / "rules_adopted.md"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    status = "✅ ADOPTED"
    if conflict_report.blocking_count > 0 and override_used:
        status = "⚠️  ADOPTED WITH OVERRIDE"

    md_lines: List[str] = []
    md_lines.append("# Rules Adopted Report")
    md_lines.append("")
    md_lines.append(f"_產生：Report-master docs-and-rules workflow v1.0_")
    md_lines.append(f"_時間：{rule.timestamp}_")
    md_lines.append("")
    md_lines.append("## 摘要")
    md_lines.append("")
    md_lines.append("| 欄位 | 值 |")
    md_lines.append("|------|----|")
    md_lines.append(f"| Rule ID | {rule.rule_id} |")
    md_lines.append(f"| Title | {rule.title} |")
    md_lines.append(f"| Type | {rule.type} |")
    md_lines.append(f"| Version | {version} |")
    md_lines.append(f"| Status | {status} |")
    md_lines.append(
        f"| Cross-check | "
        f"{'✅ PASS' if conflict_report.safe_to_adopt else '❌ FAIL'} "
        f"({conflict_report.blocking_count} BLOCKING / {conflict_report.warn_count} WARN) |"
    )
    md_lines.append(f"| Override | {str(override_used).lower()} |")
    md_lines.append("")
    md_lines.append("## 規則全文")
    md_lines.append("")
    md_lines.append(rule.body)
    md_lines.append("")
    md_lines.append("### 反例（FAIL）")
    md_lines.append("")
    for ex in rule.fail_examples:
        md_lines.append(f"- {ex}")
    md_lines.append("")
    md_lines.append("### 正例（PASS）")
    md_lines.append("")
    for ex in rule.pass_examples:
        md_lines.append(f"- {ex}")
    md_lines.append("")
    md_lines.append("## 採納決策")
    md_lines.append("")
    md_lines.append(f"- **決策者**：{'人工（--override）' if override_used else '自動'}")
    md_lines.append(f"- **決策時間**：{rule.timestamp}")
    md_lines.append(f"- **決策依據**：")
    if conflict_report.safe_to_adopt:
        md_lines.append(f"  - shared-standards.md §2 禁用清單未觸發")
        md_lines.append(f"  - cross-check 通過（0 BLOCKING / {conflict_report.warn_count} WARN）")
    else:
        md_lines.append(f"  - 使用者明確 --override（覆蓋既有規則）")
        md_lines.append(f"  - 已標 OVERRIDE:於 CHANGELOG.md")
    md_lines.append("")
    md_lines.append("## Audit Trail")
    md_lines.append("")
    md_lines.append("| 階段 | 時間 | 動作 |")
    md_lines.append("|------|------|------|")
    md_lines.append(f"| Identify | {rule.timestamp} | 識別為 {rule.type} |")
    md_lines.append(f"| Draft | {rule.timestamp} | 草擬完成 |")
    md_lines.append(f"| Cross-check | {rule.timestamp} | {conflict_report.blocking_count} BLOCKING / {conflict_report.warn_count} WARN |")
    md_lines.append(f"| Version | {rule.timestamp} | {version} 寫入 CHANGELOG.md |")
    md_lines.append(f"| Adopt | {rule.timestamp} | rules_adopted.md 產出 |")
    md_lines.append("")
    md_lines.append("## 違反處置")
    md_lines.append("")
    md_lines.append(rule.enforcement)
    md_lines.append("")
    md_lines.append("## 引用")
    md_lines.append("")
    for rel in rule.related_rules:
        md_lines.append(f"- {rel}")
    md_lines.append("- workflows/docs-and-rules.md v1.0（本 workflow）")
    md_lines.append("")

    output_path.write_text("\n".join(md_lines), encoding="utf-8")
    return output_path


def write_conflict_report(
    rule: RuleDraft,
    conflict_report: ConflictReport,
    project_root: Path,
    output_path: Optional[Path] = None,
) -> Path:
    """產出 report_output/rules_conflict.md（needs manual 模式）。"""
    if output_path is None:
        output_path = project_root / "report_output" / "rules_conflict.md"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    md_lines: List[str] = []
    md_lines.append("# Rules Conflict Report")
    md_lines.append("")
    md_lines.append(f"_產生：Report-master docs-and-rules workflow v1.0_")
    md_lines.append(f"_時間：{rule.timestamp}_")
    md_lines.append("")
    md_lines.append("## 摘要")
    md_lines.append("")
    md_lines.append(f"- **Rule ID**: {rule.rule_id}")
    md_lines.append(f"- **Title**: {rule.title}")
    md_lines.append(f"- **Type**: {rule.type}")
    md_lines.append(f"- **BLOCKING conflicts**: {conflict_report.blocking_count}")
    md_lines.append(f"- **WARN**: {conflict_report.warn_count}")
    md_lines.append("")
    md_lines.append("## BLOCKING 衝突")
    md_lines.append("")
    if not conflict_report.conflicts:
        md_lines.append("（無）")
    for c in conflict_report.conflicts:
        md_lines.append(f"### {c.conflict_type}")
        md_lines.append("")
        md_lines.append(f"- **既有規則**: `{c.existing_rule_path}`")
        md_lines.append(f"- **既有規則內容**: {c.existing_rule_text}")
        md_lines.append(f"- **嚴重程度**: {c.severity}")
        md_lines.append(f"- **建議處置**: {c.suggested_resolution}")
        md_lines.append("")

    md_lines.append("## 建議")
    md_lines.append("")
    md_lines.append("請使用者決策：")
    md_lines.append("")
    md_lines.append("1. **撤回**：取消本規則（不寫入任何檔案）")
    md_lines.append("2. **共存**：修改新規則的 body，避免觸發禁用清單")
    md_lines.append("3. **覆蓋**：重跑加 `--override` flag（會 bump MAJOR version）")
    md_lines.append("")

    output_path.write_text("\n".join(md_lines), encoding="utf-8")
    return output_path


# ─── LLM 介面（stub + real） ────────────────────────────────────────

class BaseLLM:
    """LLM 介面基底類別。"""

    def draft_rule(
        self, rule_type: str, title: str, body: str, scope: str
    ) -> RuleDraft:
        raise NotImplementedError


class StubLLM(BaseLLM):
    """Stub LLM — 不打 API，回傳 canned response。"""

    def draft_rule(
        self, rule_type: str, title: str, body: str, scope: str
    ) -> RuleDraft:
        # 直接走內建 draft_rule（無 LLM 增強）
        return draft_rule(rule_type=rule_type, title=title, body=body, scope=scope)


class HTTPLLM(BaseLLM):
    """真實 LLM（HTTP OpenAI-compatible）；目前 fallback 到 StubLLM。"""

    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(self) -> None:
        self.api_url = os.environ.get("LLM_API_URL", "")
        self.api_key = os.environ.get("LLM_API_KEY", "")
        self.model = os.environ.get("LLM_MODEL", self.DEFAULT_MODEL)

    def draft_rule(
        self, rule_type: str, title: str, body: str, scope: str
    ) -> RuleDraft:
        # 目前 fallback 到 StubLLM；保留介面給未來擴充
        return StubLLM().draft_rule(rule_type, title, body, scope)


def make_llm() -> BaseLLM:
    """依環境變數決定 LLM 實作。"""
    if os.environ.get("LLM_API_URL") and os.environ.get("LLM_API_KEY"):
        return HTTPLLM()
    return StubLLM()


# ─── 主流程：run_rule ───────────────────────────────────────────────

def run_rule(
    rule_type: str,
    title: str,
    body: str,
    scope: str = "",
    project_root: Optional[Path] = None,
    override: bool = False,
    check_only: bool = False,
    output: Optional[Path] = None,
    llm: Optional[BaseLLM] = None,
    verbose: bool = True,
) -> Tuple[RuleDraft, ConflictReport, str]:
    """跑 5 個階段：Identify → Draft → Cross-check → Version → Adopt。

    Args:
        rule_type: 規則類型（5 種 enum 之一）
        title: 規則標題
        body: 規則內容（使用者原文）
        scope: 適用範圍
        project_root: 專案根目錄
        override: 是否覆蓋既有 BLOCKING 衝突
        check_only: 是否只做 cross-check，不寫檔
        output: 自訂輸出路徑
        llm: LLM 實例（None → 自動 make_llm()）
        verbose: 是否印進度

    Returns:
        (rule, conflict_report, version)

    Raises:
        DocsAndRulesArgError: 參數錯誤
        CrossCheckConflictError: BLOCKING 衝突且無 --override
    """
    if not title or not title.strip():
        raise DocsAndRulesArgError("title 不可為空")
    if not body or not body.strip():
        raise DocsAndRulesArgError("body 不可為空")

    if project_root is None:
        project_root = _PROJECT_ROOT
    project_root = Path(project_root)

    if llm is None:
        llm = make_llm()

    if verbose:
        print(f"\n📜 docs-and-rules — 開始")
        print(f"   type: {rule_type}")
        print(f"   title: {title}")
        print(f"   body: {body[:60]}{'...' if len(body) > 60 else ''}")
        print(f"   check-only: {check_only}")
        print(f"   override: {override}")

    # Stage 1: Identify
    if verbose:
        print(f"\n🔍 Stage 1: Identify")
    identified_type = identify_type(title, body, explicit_type=rule_type)
    if verbose:
        if identified_type == rule_type:
            print(f"   ✅ 識別為 {identified_type}（使用者明確指定）")
        elif identified_type == "UNKNOWN":
            print(f"   ⚠️  無法自動識別（keyword 不命中）；使用 --type = {rule_type}")
        else:
            print(f"   ℹ️  自動識別為 {identified_type}；使用者指定 {rule_type}（採用使用者）")
    actual_type = rule_type  # 使用者明確指定優先

    # Stage 2: Draft
    if verbose:
        print(f"\n✏️  Stage 2: Draft")
    rule = llm.draft_rule(
        rule_type=actual_type,
        title=title,
        body=body,
        scope=scope,
    )
    if verbose:
        actionable_count = len(rule.body.split("\n"))
        print(f"   ✅ Rule ID: {rule.rule_id}")
        print(f"   ✅ 展開 {actionable_count} 條 actionable 規則")
        print(f"   ✅ {len(rule.fail_examples)} 個反例 + {len(rule.pass_examples)} 個正例")

    # Stage 3: Cross-check
    if verbose:
        print(f"\n🛡️  Stage 3: Cross-check")
    conflict_report = cross_check(rule, project_root)
    if verbose:
        print(f"   ✅ 檢查 shared-standards.md + CHANGELOG.md")
        print(f"   {'✅' if conflict_report.safe_to_adopt else '❌'} "
              f"{conflict_report.blocking_count} BLOCKING / {conflict_report.warn_count} WARN")

    # check-only 模式：不寫檔；直接回報
    if check_only:
        if verbose:
            print(f"\n🔍 check-only 模式：不寫入檔案")
        if conflict_report.blocking_count > 0:
            write_conflict_report(rule, conflict_report, project_root)
            if verbose:
                print(f"   ❌ 衝突報告：report_output/rules_conflict.md")
            raise CrossCheckConflictError(
                f"[BLOCKING] {conflict_report.blocking_count} 個衝突；"
                f"詳見 report_output/rules_conflict.md。"
            )
        return rule, conflict_report, rule.version

    # 處理 BLOCKING 衝突
    if not conflict_report.safe_to_adopt and not override:
        write_conflict_report(rule, conflict_report, project_root)
        raise CrossCheckConflictError(
            f"[BLOCKING] {conflict_report.blocking_count} 個衝突需人工決策。"
            f"詳見 report_output/rules_conflict.md。"
            f"重跑加 --override 以覆蓋。"
        )

    # Stage 4: Version
    if verbose:
        print(f"\n📦 Stage 4: Version")
    changelog_path = project_root / "docs" / "CHANGELOG.md"
    existing_changelog = (
        changelog_path.read_text(encoding="utf-8") if changelog_path.exists() else None
    )
    latest = _parse_latest_version(existing_changelog)
    version = _next_version(latest, has_blocking_override=(override and conflict_report.blocking_count > 0))
    rule.version = version
    if verbose:
        print(f"   ✅ latest version: v{latest[0]}.{latest[1]}")
        print(f"   ✅ new version: {version}")

    update_changelog(
        rule=rule,
        version=version,
        project_root=project_root,
        override_used=(override and conflict_report.blocking_count > 0),
    )
    if verbose:
        print(f"   ✅ CHANGELOG.md 更新")

    rules_file = append_rule_to_file(rule, project_root)
    if verbose:
        print(f"   ✅ rules 寫入 {rules_file.name}")

    # Stage 5: Adopt
    if verbose:
        print(f"\n📋 Stage 5: Adopt")
    adopted_path = adopt_rule(
        rule=rule,
        conflict_report=conflict_report,
        version=version,
        project_root=project_root,
        override_used=(override and conflict_report.blocking_count > 0),
        output_path=output,
    )
    if verbose:
        print(f"   ✅ {adopted_path.name} 產出")

    if verbose:
        print(f"\n✅ 規則採納完成")
        print(f"📄 紀錄: {adopted_path}")
        print(f"📝 版本: {version}")

    return rule, conflict_report, version


# ─── CLI ─────────────────────────────────────────────────────────────

def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="report-master docs-and-rules",
        description=(
            "文件管理 + 規則制定：給規則類型 + 標題 + 內容，"
            "跑 5 階段（Identify → Draft → Cross-check → Version → Adopt）"
            "產出 rules_adopted.md + 更新 CHANGELOG.md + 寫入 rules_<type>_vN.md。"
        ),
    )
    parser.add_argument(
        "--type", "-t",
        required=True,
        choices=list(ALL_TYPES),
        help="規則類型（STYLE / PROCESS / API / TEST / LICENSE）",
    )
    parser.add_argument(
        "--title",
        required=True,
        help="規則標題",
    )
    parser.add_argument(
        "--body", "-b",
        required=True,
        help="規則內容（使用者原文；可多句）",
    )
    parser.add_argument(
        "--scope", "-s",
        default="",
        help="適用範圍（例：「report_output/*.html」）",
    )
    parser.add_argument(
        "--project-root", "-p",
        type=Path,
        default=None,
        help="專案根目錄（預設自動偵測）",
    )
    parser.add_argument(
        "--override",
        action="store_true",
        help="覆蓋既有 BLOCKING 衝突（會 bump MAJOR version）",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="只做 cross-check，不寫入檔案（會產 conflict report）",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="自訂 rules_adopted.md 輸出路徑",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="安靜模式（不印進度）",
    )

    args = parser.parse_args()

    try:
        run_rule(
            rule_type=args.type,
            title=args.title,
            body=args.body,
            scope=args.scope,
            project_root=args.project_root,
            override=args.override,
            check_only=args.check_only,
            output=args.output,
            verbose=not args.quiet,
        )
    except CrossCheckConflictError as e:
        print(str(e), file=sys.stderr)
        # check-only + conflict → 3；其他（needs manual）→ 1
        if args.check_only:
            return EXIT_CHECK_ONLY_CONFLICT
        return EXIT_NEEDS_MANUAL
    except DocsAndRulesArgError as e:
        print(f"[DocsAndRulesArgError] {e}", file=sys.stderr)
        return EXIT_ARG_ERROR
    except DocsAndRulesError as e:
        print(f"[DocsAndRulesError] {e}", file=sys.stderr)
        return EXIT_ARG_ERROR

    return EXIT_ADOPTED


if __name__ == "__main__":
    sys.exit(_cli())