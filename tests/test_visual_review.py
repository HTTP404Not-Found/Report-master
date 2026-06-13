"""tests/test_visual_review.py — scripts/visual_review.py + workflows/visual-review.md 單元測試。

DoD 對應 `tasks.md` T3-8：
1. 載入 `workflows/visual-review.md` frontmatter 不 crash
2. Mermaid flowchart 存在（regex ` ```mermaid `）
3. `visual_review.py` CLI `--html examples/section_1.html` 不 crash

補充測試：
- SectionResult / Finding dataclass 結構
- HeuristicInspector 各項 rule
- VisualReviewer 整合測試
- --json / --skip-render flag
- workflow 引用 executor-base + html_to_pdf + quality_checker
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.visual_review import (
    Finding,
    HeuristicInspector,
    NoHTMLFoundError,
    SectionResult,
    VisualReviewer,
    VisualReviewError,
    build_report,
)


# ─── Fixtures ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_MD = PROJECT_ROOT / "workflows" / "visual-review.md"
EXAMPLES_HTML = PROJECT_ROOT / "examples" / "section_1.html"


# ─── Test 1（必要）: 載入 workflows/visual-review.md frontmatter 不 crash ─

def test_workflow_md_frontmatter_loads():
    """載入 workflows/visual-review.md frontmatter 不 crash + 必要欄位齊備。"""
    assert WORKFLOW_MD.exists(), f"找不到 {WORKFLOW_MD}"

    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert content.startswith("---\n"), "visual-review.md 應以 frontmatter 開頭"

    # 用正則抓 frontmatter
    m = re.match(r"\A---\s*\n(?P<yaml>.*?)\n---", content, re.DOTALL)
    assert m is not None, "frontmatter 區塊未正確閉合"

    fm = yaml.safe_load(m.group("yaml"))
    assert isinstance(fm, dict), "frontmatter 應為 mapping"

    # 必要欄位
    assert fm.get("name") == "visual-review", "name 應為 'visual-review'"
    assert fm.get("description"), "description 必填"
    assert len(fm.get("description", "")) >= 50, "description 太短"
    assert str(fm.get("version", "")) == "1.0", "version 應為 '1.0'"

    # 檔案行數 DoD 1
    line_count = len(content.splitlines())
    assert line_count > 100, f"workflow 應 > 100 行，目前 {line_count}"


# ─── Test 2（必要）: Mermaid flowchart 存在 ─────────────────────────

def test_workflow_md_contains_mermaid():
    """workflows/visual-review.md 內含 Mermaid flowchart（regex `` ```mermaid ``）。"""
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


# ─── Test 3（必要）: visual_review.py CLI --html ... 不 crash ──────

def test_visual_review_cli_runs(tmp_path: Path):
    """`python -m scripts.visual_review --html examples/section_1.html` 不 crash。

    整合測試：用 examples/ 的 section_1.html 跑視覺自查。
    exit code 可能 0（pass）或 1（有 finding），兩者都算正常。
    """
    if not EXAMPLES_HTML.exists():
        pytest.skip(f"找不到範例 HTML: {EXAMPLES_HTML}")

    # 將 HTML 複製到 tmp_path（避免污染 examples/）
    import shutil
    test_html = tmp_path / "section_1.html"
    shutil.copy(EXAMPLES_HTML, test_html)

    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.visual_review",
            "--html", str(test_html),
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )

    # exit code 應為 0 或 1（pass 或有 finding）；不應是 2（argument error）
    assert result.returncode in (0, 1), (
        f"CLI 失敗（returncode={result.returncode}，預期 0 或 1）\n"
        f"stdout: {result.stdout[-500:]}\nstderr: {result.stderr[-500:]}"
    )

    # 應產出 PDF
    pdf_path = test_html.with_suffix(".pdf")
    assert pdf_path.exists(), f"沒產出 {pdf_path}"
    assert pdf_path.stat().st_size > 0, "PDF 應非空"

    # 應產出 visual_review.md
    report_path = PROJECT_ROOT / "report_output" / "visual_review.md"
    assert report_path.exists(), f"沒產出 {report_path}"


# ─── Test 4（補充）: Finding dataclass 結構 ─────────────────────────

def test_finding_dataclass():
    """Finding dataclass 可正確建立 + to_dict()。"""
    f = Finding(severity="HIGH", rule="test rule", line=10, snippet="snippet text")
    assert f.severity == "HIGH"
    assert f.rule == "test rule"
    assert f.line == 10
    assert f.snippet == "snippet text"

    d = f.to_dict()
    assert d == {
        "severity": "HIGH",
        "rule": "test rule",
        "line": 10,
        "snippet": "snippet text",
    }


# ─── Test 5（補充）: SectionResult.passed 屬性 ──────────────────────

def test_section_result_passed_property():
    """SectionResult.passed：quality 過 + render OK + 0 findings = True。"""
    # PASS case
    r_pass = SectionResult(
        html_path="x.html",
        pdf_path="x.pdf",
        quality_passed=True,
        quality_violations=[],
        render_bytes=100,
        render_error=None,
        findings=[],
    )
    assert r_pass.passed is True

    # FAIL: 有 finding
    r_fail = SectionResult(
        html_path="x.html",
        pdf_path="x.pdf",
        quality_passed=True,
        quality_violations=[],
        render_bytes=100,
        render_error=None,
        findings=[Finding("LOW", "test", 1, "x")],
    )
    assert r_fail.passed is False

    # FAIL: render 失敗
    r_render_fail = SectionResult(
        html_path="x.html",
        pdf_path=None,
        quality_passed=True,
        quality_violations=[],
        render_bytes=0,
        render_error="render failed",
        findings=[],
    )
    assert r_render_fail.passed is False

    # FAIL: quality 不過
    r_qc_fail = SectionResult(
        html_path="x.html",
        pdf_path="x.pdf",
        quality_passed=False,
        quality_violations=[{"rule": "test", "line": 1, "snippet": "x"}],
        render_bytes=100,
        render_error=None,
        findings=[],
    )
    assert r_qc_fail.passed is False


# ─── Test 6（補充）: HeuristicInspector 字體檢查 ─────────────────────

def test_heuristic_forbidden_font():
    """HeuristicInspector 應抓到禁用字體 (Calibri)。"""
    html = """<!DOCTYPE html>
<html><head><style>
body { font-family: Calibri, sans-serif; }
</style></head><body><h1>第一章 test</h1><p>content</p></body></html>
"""
    p = PROJECT_ROOT / "tmp_test_font.html"
    p.write_text(html, encoding="utf-8")
    try:
        insp = HeuristicInspector(html, p)
        findings = insp.inspect()
        # 應抓到 "禁用字體"
        font_findings = [f for f in findings if "禁用字體" in f.rule]
        assert len(font_findings) >= 1, f"應抓到 Calibri 禁用字體，got: {findings}"
        assert font_findings[0].severity == "HIGH"
    finally:
        if p.exists():
            p.unlink()


def test_heuristic_safe_font_passes():
    """HeuristicInspector 對鎖死字體不報錯。"""
    html = """<!DOCTYPE html>
<html><head><style>
body { font-family: '標楷體', 'Times New Roman', serif; }
</style></head><body><h1>第一章 test</h1><p>long enough content here to pass the empty section check</p></body></html>
"""
    p = PROJECT_ROOT / "tmp_test_safe_font.html"
    p.write_text(html, encoding="utf-8")
    try:
        insp = HeuristicInspector(html, p)
        findings = insp.inspect()
        font_findings = [f for f in findings if "禁用字體" in f.rule]
        assert len(font_findings) == 0, f"標楷體不應誤報，got: {font_findings}"
    finally:
        if p.exists():
            p.unlink()


# ─── Test 7（補充）: HeuristicInspector 章節編號 ─────────────────────

def test_heuristic_chapter_numbering():
    """HeuristicInspector 應檢查 H1 / H2 編號格式。"""
    # 缺少「第N章」的 H1
    html_no_num = """<!DOCTYPE html>
<html><head><style>body{font-family:'標楷體'}</style></head><body>
<h1>Introduction</h1>
<p>some content here that is more than fifty characters long to pass the empty check</p>
<h2>1.1 Section</h2>
<p>some content here that is more than fifty characters long to pass the empty check</p>
</body></html>
"""
    p = PROJECT_ROOT / "tmp_test_chap.html"
    p.write_text(html_no_num, encoding="utf-8")
    try:
        insp = HeuristicInspector(html_no_num, p)
        findings = insp.inspect()
        h1_findings = [f for f in findings if "H1 缺少" in f.rule]
        assert len(h1_findings) >= 1, "應抓到 H1 缺少「第N章」編號"
    finally:
        if p.exists():
            p.unlink()


# ─── Test 8（補充）: HeuristicInspector 圖片 overflow ───────────────

def test_heuristic_image_overflow():
    """HeuristicInspector 應抓到 width > 600px 的圖片。"""
    html = """<!DOCTYPE html>
<html><head><style>body{font-family:'標楷體'}</style></head><body>
<h1>第一章 test</h1>
<p>some content here that is more than fifty characters long to pass the empty check</p>
<img src="big.png" alt="big" width="800">
<p>some content here that is more than fifty characters long to pass the empty check</p>
</body></html>
"""
    p = PROJECT_ROOT / "tmp_test_img.html"
    p.write_text(html, encoding="utf-8")
    try:
        insp = HeuristicInspector(html, p)
        findings = insp.inspect()
        overflow = [f for f in findings if "overflow" in f.rule]
        assert len(overflow) >= 1, f"應抓到 800px overflow，got: {findings}"
        assert "800" in overflow[0].snippet or "800" in overflow[0].rule
    finally:
        if p.exists():
            p.unlink()


# ─── Test 9（補充）: VisualReviewer 整合測試 ─────────────────────────

def test_visual_reviewer_runs(tmp_path: Path, fake_fonts_dir):
    """VisualReviewer.review() 應回傳 SectionResult，含 findings。"""
    import shutil
    test_html = tmp_path / "test_section.html"
    shutil.copy(EXAMPLES_HTML, test_html)

    vr = VisualReviewer(
        html_path=test_html,
        fonts_dir=fake_fonts_dir,
    )
    result = vr.review()

    assert isinstance(result, SectionResult)
    assert result.html_path == str(test_html)
    assert result.render_error is None
    assert result.render_bytes > 0
    # examples/section_1.html 已知有 3 個 finding（2 anchor + 1 empty section）
    assert isinstance(result.findings, list)
    # 至少有 anchor 失效的 finding
    anchor_findings = [f for f in result.findings if "anchor" in f.rule]
    assert len(anchor_findings) >= 1


def test_visual_reviewer_skip_render(tmp_path: Path, fake_fonts_dir):
    """VisualReviewer --skip-render：若 PDF 已存在則不重新 render。"""
    import shutil
    test_html = tmp_path / "test_section.html"
    shutil.copy(EXAMPLES_HTML, test_html)

    # 先產 PDF
    from scripts.html_to_pdf import html_to_pdf
    pdf_path = tmp_path / "test_section.pdf"
    html_to_pdf(html_source=test_html, output_pdf=pdf_path, fonts_dir=fake_fonts_dir)
    original_mtime = pdf_path.stat().st_mtime

    # 跑 review with skip_render
    vr = VisualReviewer(
        html_path=test_html,
        fonts_dir=fake_fonts_dir,
        skip_render=True,
    )
    result = vr.review()

    assert result.render_error is None
    assert result.render_bytes == pdf_path.stat().st_size
    # PDF 應未被重新 render（mtime 相同）
    assert pdf_path.stat().st_mtime == original_mtime


# ─── Test 10（補充）: build_report() 輸出 markdown ──────────────────

def test_build_report_pass_and_fail():
    """build_report() 應根據 results 產出 PASS 或 FAIL 報告。"""
    # PASS case
    pass_result = SectionResult(
        html_path="/x/section_1.html",
        pdf_path="/x/section_1.pdf",
        quality_passed=True,
        quality_violations=[],
        render_bytes=100,
        render_error=None,
        findings=[],
        timestamp="2026-06-13T15:00:00",
    )
    md_pass = build_report([pass_result], "1 個 HTML 檔")
    assert "# Visual Review Report" in md_pass
    assert "✅" in md_pass
    assert "視覺自查通過" in md_pass

    # FAIL case
    fail_result = SectionResult(
        html_path="/x/section_1.html",
        pdf_path="/x/section_1.pdf",
        quality_passed=True,
        quality_violations=[],
        render_bytes=100,
        render_error=None,
        findings=[Finding("HIGH", "test rule", 10, "test snippet")],
        timestamp="2026-06-13T15:00:00",
    )
    md_fail = build_report([fail_result], "1 個 HTML 檔")
    assert "❌" in md_fail
    assert "FAIL" in md_fail
    assert "test rule" in md_fail
    assert "視覺自查失敗" in md_fail


# ─── Test 11（補充）: CLI --json 輸出有效 JSON ─────────────────────

def test_visual_review_cli_json(tmp_path: Path):
    """CLI `--json` 應產出可解析的 JSON。"""
    import shutil
    test_html = tmp_path / "section_1.html"
    shutil.copy(EXAMPLES_HTML, test_html)

    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.visual_review",
            "--html", str(test_html),
            "--json",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode in (0, 1), f"CLI 失敗（returncode={result.returncode}）"

    # 解析 JSON
    data = json.loads(result.stdout)
    assert "passed" in data
    assert "total_findings" in data
    assert "report_path" in data
    assert "sections" in data
    assert isinstance(data["sections"], list)
    assert len(data["sections"]) == 1

    section = data["sections"][0]
    assert "html_path" in section
    assert "pdf_path" in section
    assert "findings" in section
    assert isinstance(section["findings"], list)


# ─── Test 12（補充）: NoHTMLFoundError 觸發 ─────────────────────────

def test_no_html_found_error():
    """_resolve_html_files 對不存在的路徑 raise NoHTMLFoundError。"""
    from scripts.visual_review import _resolve_html_files

    class FakeArgs:
        html = None
        dir = Path("/nonexistent/path/xyz")

    with pytest.raises(NoHTMLFoundError):
        _resolve_html_files(FakeArgs)


def test_no_html_found_error_no_args():
    """_resolve_html_files 對 --html/--dir 都沒給時 raise NoHTMLFoundError。"""
    from scripts.visual_review import _resolve_html_files

    class FakeArgs:
        html = None
        dir = None

    with pytest.raises(NoHTMLFoundError):
        _resolve_html_files(FakeArgs)


# ─── Test 13（補充）: workflow 引用必要檔案 ─────────────────────────

def test_workflow_references_required_files():
    """workflow 應引用 executor-base + html_to_pdf + quality_checker。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert "references/executor-base.md" in content, (
        "workflow 應引用 references/executor-base.md"
    )
    assert "html_to_pdf" in content, (
        "workflow 應引用 html_to_pdf"
    )
    assert "quality_checker" in content, (
        "workflow 應引用 quality_checker"
    )


# ─── Test 14（補充）: workflow 含 CLI 範例 ───────────────────────────

def test_workflow_md_contains_cli_examples():
    """workflow 應含 CLI 範例（`--html`, `--dir`, `--verbose`, `--json`）。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert "--html" in content, "workflow 應含 --html CLI 範例"
    assert "--dir" in content, "workflow 應含 --dir CLI 範例"
    assert "--verbose" in content or "-v" in content, (
        "workflow 應含 --verbose CLI 範例"
    )
    assert "--json" in content, "workflow 應含 --json CLI 範例"


# ─── Test 15（補充）: workflow 含 heuristic 規則清單 ─────────────────

def test_workflow_md_contains_heuristic_list():
    """workflow §9 應含 heuristic 規則清單。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    # §9 標題
    assert "9." in content, "workflow 應有 §9 標題"
    assert "Heuristic" in content or "heuristic" in content, (
        "workflow §9 應含 heuristic 關鍵字"
    )


# ─── Fixture: fake fonts dir ─────────────────────────────────────────

@pytest.fixture
def fake_fonts_dir(tmp_path):
    """建立假字體目錄（含 .ttf 檔）給 html_to_pdf 用。"""
    d = tmp_path / "fonts"
    d.mkdir()
    (d / "fake-cjk.ttf").write_bytes(b"\x00\x01\x00\x00" + b"\x00" * 100)
    (d / "fake-latin.otf").write_bytes(b"\x00\x01\x00\x00" + b"\x00" * 100)
    return d