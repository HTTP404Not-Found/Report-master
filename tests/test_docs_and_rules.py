"""tests/test_docs_and_rules.py — scripts/docs_and_rules.py + workflows/docs-and-rules.md 單元測試.

DoD 對應 `tasks.md` T3-15：
1. 載入 `workflows/docs-and-rules.md` frontmatter 不 crash
2. Mermaid flowchart 存在
3. CLI `--type STYLE` 不 crash
4. `identify_type()` 正確分類（STYLE / PROCESS / API / TEST / LICENSE）

補充測試：
- RuleDraft / Conflict / ConflictReport 結構
- cross_check() BLOCKING 衝突偵測（display: grid）
- end-to-end run_rule 整合測試（產 rules_adopted.md + CHANGELOG.md + rules_style_vN.md）
- `--check-only` 模式：BLOCKING 時 exit code = 3
- `--override` 模式：覆蓋後正常 ADOPTED
- CLI argument 解析錯誤
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.docs_and_rules import (
    ALL_TYPES,
    CONFLICT_DISABLED_USED,
    Conflict,
    ConflictReport,
    CrossCheckConflictError,
    DocsAndRulesArgError,
    DocsAndRulesError,
    EXIT_ADOPTED,
    EXIT_CHECK_ONLY_CONFLICT,
    EXIT_NEEDS_MANUAL,
    RuleDraft,
    SEVERITY_BLOCKING,
    TYPE_API,
    TYPE_LICENSE,
    TYPE_PROCESS,
    TYPE_STYLE,
    TYPE_TEST,
    _draft_body,
    _file_for_type,
    _generate_rule_id,
    _next_version,
    _parse_latest_version,
    adopt_rule,
    append_rule_to_file,
    cross_check,
    draft_rule,
    identify_type,
    run_rule,
    update_changelog,
    write_conflict_report,
)


# ─── Fixtures ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_MD = PROJECT_ROOT / "workflows" / "docs-and-rules.md"
SHARED_STANDARDS_MD = PROJECT_ROOT / "docs" / "shared-standards.md"


@pytest.fixture
def isolated_project(tmp_path: Path):
    """建立隔離的測試專案目錄（複製必要的 docs/）。

    避免測試污染主專案的 CHANGELOG.md / rules_*.md。
    """
    # 複製 docs/shared-standards.md（cross-check 需要）
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    src = PROJECT_ROOT / "docs" / "shared-standards.md"
    if src.exists():
        (docs_dir / "shared-standards.md").write_text(
            src.read_text(encoding="utf-8"), encoding="utf-8"
        )
    # 建立 report_output/
    (tmp_path / "report_output").mkdir(parents=True, exist_ok=True)
    return tmp_path


# ─── Test 1（必要）: 載入 workflows/docs-and-rules.md frontmatter 不 crash ─

def test_workflow_md_frontmatter_loads():
    """載入 workflows/docs-and-rules.md frontmatter 不 crash + 必要欄位齊備。"""
    assert WORKFLOW_MD.exists(), f"找不到 {WORKFLOW_MD}"

    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert content.startswith("---\n"), "docs-and-rules.md 應以 frontmatter 開頭"

    # 用正則抓 frontmatter
    m = re.match(r"\A---\s*\n(?P<yaml>.*?)\n---", content, re.DOTALL)
    assert m is not None, "frontmatter 區塊未正確閉合"

    fm = yaml.safe_load(m.group("yaml"))
    assert isinstance(fm, dict), "frontmatter 應為 mapping"

    # 必要欄位
    assert fm.get("name") == "docs-and-rules", "name 應為 'docs-and-rules'"
    assert fm.get("description"), "description 必填"
    assert len(fm.get("description", "")) >= 50, "description 太短"
    assert str(fm.get("version", "")) == "1.0", "version 應為 '1.0'"

    # 檔案行數 DoD 1
    line_count = len(content.splitlines())
    assert line_count > 100, f"workflow 應 > 100 行，目前 {line_count}"


# ─── Test 2（必要）: Mermaid flowchart 存在 ─────────────────────────

def test_workflow_md_contains_mermaid():
    """workflows/docs-and-rules.md 內含 Mermaid flowchart（regex `` ```mermaid ``）。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")

    # 找 ```mermaid 開頭的區塊
    pattern = re.compile(r"^```mermaid\s*$", re.MULTILINE)
    matches = pattern.findall(content)
    assert len(matches) >= 1, "workflow 應含至少 1 個 ```mermaid 區塊"

    # 額外檢查：Mermaid 內含 flowchart 關鍵字
    m = re.search(r"```mermaid\s*\n(?P<body>.*?)\n```", content, re.DOTALL)
    assert m is not None, "應有完整 mermaid 區塊（``` 閉合）"
    mermaid_body = m.group("body")
    assert "flowchart" in mermaid_body or "graph" in mermaid_body, (
        "Mermaid 區塊應含 flowchart 或 graph 關鍵字"
    )


# ─── Test 3（必要）: CLI --type STYLE 不 crash ─────────────────────

def test_cli_type_style_runs(tmp_path: Path):
    """`python -m scripts.docs_and_rules --type STYLE --title "..." --body "..."` 不 crash。

    整合測試：跑完整 5 階段流程，產 rules_adopted.md + CHANGELOG.md + rules_style_vN.md。
    """
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.docs_and_rules",
            "--type", "STYLE",
            "--title", "Test Style Rule",
            "--body", "Test rule body content for unit testing purposes.",
            "--output", str(tmp_path / "rules_adopted.md"),
            "--quiet",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"CLI 失敗（returncode={result.returncode}）\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # 應有 rules_adopted.md
    adopted_path = tmp_path / "rules_adopted.md"
    assert adopted_path.exists(), f"沒產出 {adopted_path}"
    content = adopted_path.read_text(encoding="utf-8")
    assert "Test Style Rule" in content
    assert "ADOPTED" in content


# ─── Test 4（必要）: identify_type() 正確分類 ──────────────────────

def test_identify_type_classification():
    """identify_type() 應正確分類 5 種類型。"""
    # STYLE: 字體 / 排版 / 表格
    assert identify_type("Font Family", "字體與排版") == TYPE_STYLE
    assert identify_type("Table Nesting", "表格巢狀") == TYPE_STYLE
    assert identify_type("Color Rule", "顏色規範") == TYPE_STYLE

    # PROCESS: pipeline / workflow / stage
    assert identify_type("CI Pipeline", "stage 順序與 review gate") == TYPE_PROCESS
    assert identify_type("Release Flow", "deploy 流程") == TYPE_PROCESS

    # API: endpoint / cli / flag
    assert identify_type("REST API", "endpoint 與 http request") == TYPE_API
    assert identify_type("CLI Flag", "argument 與 module") == TYPE_API

    # TEST: pytest / coverage / fixture
    assert identify_type("Unit Test", "pytest 覆蓋率要求") == TYPE_TEST
    assert identify_type("Fixture Standard", "mock 與 assertion") == TYPE_TEST

    # LICENSE: mit / copyright / 商業使用
    assert identify_type("MIT License", "版權與商業使用限制") == TYPE_LICENSE
    assert identify_type("GPL", "compliance 條款") == TYPE_LICENSE

    # UNKNOWN: keyword 不命中
    assert identify_type("Random Title", "xyzqwerty asdf") == "UNKNOWN"

    # 明確指定時優先
    assert identify_type("Random Title", "xyzqwerty", explicit_type=TYPE_API) == TYPE_API

    # 無效 explicit_type
    with pytest.raises(DocsAndRulesArgError):
        identify_type("X", "Y", explicit_type="INVALID_TYPE")


# ─── Test 5（補充）: RuleDraft / Conflict / ConflictReport 結構 ──

def test_dataclass_structures():
    """RuleDraft / Conflict / ConflictReport 結構正確。"""
    # RuleDraft
    rule = RuleDraft(
        rule_id="R-S-007",
        type=TYPE_STYLE,
        title="Test",
        version="v1.3",
        body="1. foo\n2. bar",
        fail_examples=["bad"],
        pass_examples=["good"],
        related_rules=["shared-standards"],
        enforcement="BLOCKING",
        scope="report_output/*.html",
        timestamp="2026-06-13T15:30:00",
    )
    assert rule.rule_id == "R-S-007"
    assert rule.type == TYPE_STYLE

    # Conflict
    conflict = Conflict(
        existing_rule_path="docs/shared-standards.md §2",
        existing_rule_text="display: flex",
        conflict_type=CONFLICT_DISABLED_USED,
        severity=SEVERITY_BLOCKING,
        suggested_resolution="撤回或 override",
    )
    assert conflict.severity == SEVERITY_BLOCKING

    # ConflictReport
    report = ConflictReport(
        new_rule_id="R-S-007",
        new_rule_type=TYPE_STYLE,
        new_rule_title="Test",
        conflicts=[conflict],
        warnings=[],
    )
    assert report.blocking_count == 1
    assert report.warn_count == 0
    # safe_to_adopt 由 cross_check() 設定；直接構造時為 True（預設）
    # 測試透過 cross_check() 驗證（見 test_cross_check_blocks_disabled_css）
    assert report.safe_to_adopt is True  # default


# ─── Test 6（補充）: cross_check() BLOCKING 衝突偵測 ──────────────

def test_cross_check_blocks_disabled_css(isolated_project: Path):
    """cross_check() 應偵測到「允許 display: grid」的 BLOCKING 衝突。"""
    rule = RuleDraft(
        rule_id="R-S-TEST",
        type=TYPE_STYLE,
        title="Allow CSS Grid",
        version="v1.0",
        body="允許使用 display: grid; display: flex 等 layout",
        fail_examples=[],
        pass_examples=[],
        enforcement="BLOCKING",
        scope="*",
    )

    report = cross_check(rule, isolated_project)
    assert report.blocking_count >= 1, (
        f"應偵測到 BLOCKING 衝突，got: {report.blocking_count}"
    )
    assert report.safe_to_adopt is False
    assert any(c.conflict_type == CONFLICT_DISABLED_USED for c in report.conflicts)


def test_cross_check_passes_safe_rule(isolated_project: Path):
    """cross_check() 對「不觸發禁用清單」的規則應 safe_to_adopt=True。"""
    rule = RuleDraft(
        rule_id="R-S-SAFE",
        type=TYPE_STYLE,
        title="Safe Style Rule",
        version="v1.0",
        body="字體使用 '標楷體'，章節命名為「第 X 章」",
        enforcement="BLOCKING",
        scope="*",
    )

    report = cross_check(rule, isolated_project)
    assert report.blocking_count == 0, (
        f"安全規則不應有 BLOCKING，got: {report.blocking_count}"
    )
    assert report.safe_to_adopt is True


# ─── Test 7（補充）: end-to-end run_rule 整合測試 ────────────────

def test_run_rule_end_to_end(isolated_project: Path):
    """run_rule 完整跑 5 階段，產 rules_adopted.md + CHANGELOG.md + rules_style_vN.md。"""
    output_path = isolated_project / "report_output" / "rules_adopted.md"

    rule, conflict_report, version = run_rule(
        rule_type=TYPE_STYLE,
        title="Table Nesting Limit",
        body="HTML 表格巢狀層數不得超過 3 層。違反時 quality_checker 報 BLOCKING。",
        scope="report_output/*.html",
        project_root=isolated_project,
        output=output_path,
        verbose=False,
    )

    assert isinstance(rule, RuleDraft)
    assert rule.type == TYPE_STYLE
    assert rule.title == "Table Nesting Limit"
    assert conflict_report.safe_to_adopt is True

    # 產出檔案
    assert output_path.exists(), f"沒產出 {output_path}"
    assert (isolated_project / "docs" / "CHANGELOG.md").exists(), "沒產出 CHANGELOG.md"
    rules_files = list((isolated_project / "docs").glob("rules_style_v*.md"))
    assert len(rules_files) >= 1, f"沒產出 rules_style_vN.md；found: {rules_files}"

    # 驗證 CHANGELOG.md 內容
    changelog = (isolated_project / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert rule.rule_id in changelog, f"CHANGELOG.md 應含 {rule.rule_id}"
    assert version in changelog, f"CHANGELOG.md 應含 {version}"


# ─── Test 8（補充）: --check-only 模式 BLOCKING 時 exit 3 ─────────

def test_cli_check_only_returns_3_on_blocking():
    """CLI --check-only 模式遇到 BLOCKING 衝突時應 exit code = 3。"""
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.docs_and_rules",
            "--type", "STYLE",
            "--title", "Allow CSS Grid",
            "--body", "允許使用 display: grid;",
            "--check-only",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    # 允許的副作用：會在 PROJECT_ROOT/report_output 寫 rules_conflict.md
    # 測試結束後清理
    try:
        assert result.returncode == EXIT_CHECK_ONLY_CONFLICT, (
            f"--check-only 遇 BLOCKING 應 exit 3，got {result.returncode};"
            f" stdout: {result.stdout}; stderr: {result.stderr}"
        )
    finally:
        # 清理副作用
        for f in [
            PROJECT_ROOT / "report_output" / "rules_conflict.md",
            PROJECT_ROOT / "docs" / "rules_style_v1.md",
            PROJECT_ROOT / "docs" / "CHANGELOG.md",
        ]:
            if f.exists():
                f.unlink()


def test_cli_check_only_returns_0_when_safe(tmp_path: Path):
    """CLI --check-only 模式無 BLOCKING 時應 exit code = 0。"""
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.docs_and_rules",
            "--type", "STYLE",
            "--title", "Safe Rule",
            "--body", "字體與排版規範",
            "--check-only",
            "--quiet",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == EXIT_ADOPTED, (
        f"--check-only 無衝突應 exit 0，got {result.returncode};"
        f" stderr: {result.stderr}"
    )


# ─── Test 9（補充）: --override 模式覆蓋 BLOCKING 衝突 ───────────

def test_cli_override_blocks_blocking():
    """CLI --override 模式遇到 BLOCKING 衝突時應正常 ADOPTED（不報 conflict）。"""
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.docs_and_rules",
            "--type", "STYLE",
            "--title", "Override Test",
            "--body", "允許使用 display: grid;",
            "--override",
            "--quiet",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        assert result.returncode == EXIT_ADOPTED, (
            f"--override 應正常 ADOPTED，got {result.returncode};"
            f" stderr: {result.stderr}"
        )
    finally:
        # 清理副作用
        for f in [
            PROJECT_ROOT / "report_output" / "rules_adopted.md",
            PROJECT_ROOT / "docs" / "rules_style_v1.md",
            PROJECT_ROOT / "docs" / "CHANGELOG.md",
        ]:
            if f.exists():
                f.unlink()


# ─── Test 10（補充）: CLI argument 解析錯誤 ────────────────────────

def test_cli_missing_required_args():
    """CLI 缺必要 flag 應 exit code = 2。"""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.docs_and_rules"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2, (
        f"缺 flag 應 exit 2，got {result.returncode};"
        f" stderr: {result.stderr}"
    )


def test_cli_invalid_type():
    """CLI --type 值不合法應 exit code = 2。"""
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.docs_and_rules",
            "--type", "INVALID_TYPE",
            "--title", "x",
            "--body", "y",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2, (
        f"無效 --type 應 exit 2，got {result.returncode};"
        f" stderr: {result.stderr}"
    )


# ─── Test 11（補充）: _generate_rule_id 連號邏輯 ──────────────────

def test_generate_rule_id_increments():
    """_generate_rule_id 應依既有 IDs 自動遞增。"""
    # 無既有 IDs → 從 001 起
    rid1 = _generate_rule_id(TYPE_STYLE, [])
    assert rid1 == "R-S-001"

    # 已有 R-S-001 → 002
    rid2 = _generate_rule_id(TYPE_STYLE, ["R-S-001"])
    assert rid2 == "R-S-002"

    # 已有 R-S-001 / R-S-003（跳號）→ 004（不補洞）
    rid3 = _generate_rule_id(TYPE_STYLE, ["R-S-001", "R-S-003"])
    assert rid3 == "R-S-004"

    # 不同類型各自連號
    rid4 = _generate_rule_id(TYPE_API, ["R-A-001"])
    assert rid4 == "R-A-002"


# ─── Test 12（補充）: _parse_latest_version / _next_version ──────

def test_version_parsing_and_bump():
    """_parse_latest_version 與 _next_version 對 CHANGELOG 解析正確。"""
    # 無 CHANGELOG → 預設 v1.0
    assert _parse_latest_version(None) == (1, 0)
    assert _parse_latest_version("") == (1, 0)

    # 有 v1.2
    text = "# CHANGELOG\n\n## [v1.2] - 2026-06-01\n\n- old\n"
    assert _parse_latest_version(text) == (1, 2)

    # _next_version: 預設增量
    assert _next_version((1, 2)) == "v1.3"
    assert _next_version((1, 2), has_blocking_override=True) == "v2.0"
    assert _next_version((2, 5), has_blocking_override=True) == "v3.0"


# ─── Test 13（補充）: _draft_body 展開成 actionable 條目 ──────────

def test_draft_body_expands_actionable():
    """_draft_body 應把使用者 body 展開成至少 3 條 actionable。"""
    items, fails, passes = _draft_body(
        "字體用標楷體。表格巢狀 ≤ 3 層。顏色用 #000000。"
    )
    assert len(items) >= 3, f"應至少 3 條，got {len(items)}"
    assert len(fails) >= 1
    assert len(passes) >= 1


# ─── Test 14（補充）: append_rule_to_file / update_changelog 寫檔正確 ──

def test_append_and_changelog_writes_files(isolated_project: Path):
    """append_rule_to_file + update_changelog 應正確寫入檔案。"""
    rule = RuleDraft(
        rule_id="R-S-100",
        type=TYPE_STYLE,
        title="Append Test",
        version="v1.5",
        body="1. test\n2. rule\n3. body",
        fail_examples=["bad"],
        pass_examples=["good"],
        enforcement="BLOCKING",
        scope="*",
    )

    rules_file = append_rule_to_file(rule, isolated_project)
    assert rules_file.exists()
    content = rules_file.read_text(encoding="utf-8")
    assert "R-S-100" in content
    assert "Append Test" in content

    update_changelog(
        rule=rule,
        version="v1.5",
        project_root=isolated_project,
        override_used=False,
    )
    changelog = (isolated_project / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "R-S-100" in changelog
    assert "v1.5" in changelog


# ─── Test 15（補充）: write_conflict_report 產出衝突檔 ──────────

def test_write_conflict_report(isolated_project: Path):
    """write_conflict_report 應產出 rules_conflict.md 含衝突細節。"""
    rule = RuleDraft(
        rule_id="R-S-999",
        type=TYPE_STYLE,
        title="Conflict Test",
        version="v1.0",
        body="x",
        enforcement="BLOCKING",
    )
    conflict = Conflict(
        existing_rule_path="docs/shared-standards.md §2",
        existing_rule_text="display: grid",
        conflict_type=CONFLICT_DISABLED_USED,
        severity=SEVERITY_BLOCKING,
        suggested_resolution="撤回",
    )
    report = ConflictReport(
        new_rule_id=rule.rule_id,
        new_rule_type=rule.type,
        new_rule_title=rule.title,
        conflicts=[conflict],
        warnings=[],
    )

    out = write_conflict_report(rule, report, isolated_project)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "Conflict Test" in content
    assert "BLOCKING" in content
    assert "DISABLED_USED" in content


# ─── Test 16（補充）: workflow 引用必備檔案 ────────────────────────

def test_workflow_references_required_files():
    """workflow 應引用 shared-standards / error-handling / technical-design。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert "docs/shared-standards.md" in content, (
        "workflow 應引用 docs/shared-standards.md"
    )
    assert "workflows/error-handling.md" in content, (
        "workflow 應引用 workflows/error-handling.md"
    )
    assert "workflows/technical-design.md" in content, (
        "workflow 應引用 workflows/technical-design.md"
    )


# ─── Test 17（補充）: workflow 含 5 種規則類型 enum ──────────────

def test_workflow_lists_5_rule_types():
    """workflow 應列 5 種規則類型（STYLE / PROCESS / API / TEST / LICENSE）。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    for t in ALL_TYPES:
        assert t in content, f"workflow 應含 {t} 規則類型"


# ─── Test 18（補充）: workflow 5 階段流程名稱 ─────────────────────

def test_workflow_lists_5_stages():
    """workflow 應列 5 個階段（Identify / Draft / Cross-check / Version / Adopt）。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert "Identify" in content, "workflow 應含 Identify 階段"
    assert "Draft" in content, "workflow 應含 Draft 階段"
    assert "Cross-check" in content or "cross-check" in content, (
        "workflow 應含 Cross-check 階段"
    )
    assert "Version" in content, "workflow 應含 Version 階段"
    assert "Adopt" in content, "workflow 應含 Adopt 階段"


# ─── Test 19（補充）: adopt_rule 產出含 audit trail ──────────────

def test_adopt_rule_contains_audit_trail(isolated_project: Path):
    """adopt_rule 產出的 rules_adopted.md 應含 audit trail 段落。"""
    rule = RuleDraft(
        rule_id="R-S-AUDIT",
        type=TYPE_STYLE,
        title="Audit Trail Test",
        version="v1.0",
        body="1. item one\n2. item two",
        enforcement="BLOCKING",
    )
    report = ConflictReport(
        new_rule_id=rule.rule_id,
        new_rule_type=rule.type,
        new_rule_title=rule.title,
    )

    out = adopt_rule(
        rule=rule,
        conflict_report=report,
        version="v1.0",
        project_root=isolated_project,
        override_used=False,
    )
    content = out.read_text(encoding="utf-8")
    assert "Audit Trail" in content, "應含 Audit Trail 區塊"
    assert "Identify" in content, "Audit Trail 應含 Identify 階段"
    assert "Draft" in content, "Audit Trail 應含 Draft 階段"
    assert "Cross-check" in content, "Audit Trail 應含 Cross-check 階段"
    assert "Version" in content, "Audit Trail 應含 Version 階段"
    assert "Adopt" in content, "Audit Trail 應含 Adopt 階段"


# ─── Test 20（補充）: draft_rule 結構正確 ────────────────────────

def test_draft_rule_structure():
    """draft_rule 應產出符合結構的 RuleDraft。"""
    rule = draft_rule(
        rule_type=TYPE_STYLE,
        title="Test Draft",
        body="字體規範. 排版規範. 顏色規範.",
        scope="*",
        existing_ids=["R-S-001"],
    )
    assert rule.rule_id == "R-S-002"
    assert rule.type == TYPE_STYLE
    assert rule.title == "Test Draft"
    assert rule.body  # 非空
    assert rule.fail_examples
    assert rule.pass_examples
    assert rule.enforcement
    assert rule.scope == "*"