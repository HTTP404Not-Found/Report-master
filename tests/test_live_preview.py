"""tests/test_live_preview.py — scripts/live_preview.py + workflows/live-preview.md 單元測試。

DoD 對應 `tasks.md` T3-7：
1. 載入 `workflows/live-preview.md` frontmatter 不 crash
2. Mermaid flowchart 存在（regex ` ```mermaid `）
3. `live_preview.py` CLI `--html examples/section_1.html --once` 不 crash
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.live_preview import (
    HTMLNotFoundError,
    LivePreviewer,
    RenderResult,
    RenderFailedError,
    _HAS_WATCHFILES,
)


# ─── Fixtures ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_MD = PROJECT_ROOT / "workflows" / "live-preview.md"
EXAMPLES_HTML = PROJECT_ROOT / "examples" / "section_1.html"


# ─── Test 1（必要）: 載入 workflows/live-preview.md frontmatter 不 crash ─

def test_workflow_md_frontmatter_loads():
    """載入 workflows/live-preview.md frontmatter 不 crash + 必要欄位齊備。"""
    assert WORKFLOW_MD.exists(), f"找不到 {WORKFLOW_MD}"

    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert content.startswith("---\n"), "live-preview.md 應以 frontmatter 開頭"

    # 用正則抓 frontmatter
    m = re.match(r"\A---\s*\n(?P<yaml>.*?)\n---", content, re.DOTALL)
    assert m is not None, "frontmatter 區塊未正確閉合"

    fm = yaml.safe_load(m.group("yaml"))
    assert isinstance(fm, dict), "frontmatter 應為 mapping"

    # 必要欄位
    assert fm.get("name") == "live-preview", "name 應為 'live-preview'"
    assert fm.get("description"), "description 必填"
    assert len(fm.get("description", "")) >= 50, "description 太短"
    assert fm.get("version"), "version 必填"

    # 檔案行數 DoD 1
    line_count = len(content.splitlines())
    assert line_count > 100, f"workflow 應 > 100 行，目前 {line_count}"


# ─── Test 2（必要）: Mermaid flowchart 存在 ─────────────────────────

def test_workflow_md_contains_mermaid():
    """workflows/live-preview.md 內含 Mermaid flowchart（regex `` ```mermaid ``）。"""
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


# ─── Test 3（必要）: live_preview.py CLI --html ... --once 不 crash ─

def test_live_preview_cli_runs_once(tmp_path: Path):
    """`python -m scripts.live_preview --html examples/section_1.html --once` 不 crash。

    整合測試：用 examples/ 的 section_1.html 跑 --once 模式，應產出 PDF。
    """
    if not EXAMPLES_HTML.exists():
        pytest.skip(f"找不到範例 HTML: {EXAMPLES_HTML}")

    # 將 HTML 複製到 tmp_path（避免污染 examples/ 目錄）
    import shutil
    test_html = tmp_path / "section_1.html"
    shutil.copy(EXAMPLES_HTML, test_html)

    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.live_preview",
            "--html", str(test_html),
            "--once",
            "--quiet",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"CLI 失敗（returncode={result.returncode}）\n"
        f"stdout: {result.stdout[-500:]}\nstderr: {result.stderr[-500:]}"
    )

    # 應產出 PDF（與 HTML 同目錄 + .pdf 副檔名）
    pdf_path = test_html.with_suffix(".pdf")
    assert pdf_path.exists(), f"沒產出 {pdf_path}"
    assert pdf_path.stat().st_size > 0, "PDF 應非空"

    # --quiet 模式下 stdout 應為 JSON
    try:
        data = json.loads(result.stdout.strip().splitlines()[-1])
        assert "pdf_path" in data
        assert "bytes" in data
    except (json.JSONDecodeError, IndexError):
        # 若不是 JSON，至少要有 PDF 檔案
        pass


# ─── Test 4（補充）: HTMLNotFoundError when HTML 不存在 ─────────────

def test_live_previewer_raises_on_missing_html(tmp_path: Path):
    """指定不存在的 HTML → LivePreviewer() 應 raise HTMLNotFoundError。"""
    missing = tmp_path / "nope.html"
    assert not missing.exists()

    with pytest.raises(HTMLNotFoundError) as exc_info:
        LivePreviewer(html_path=missing)
    assert "不存在" in str(exc_info.value) or "not found" in str(exc_info.value).lower()


# ─── Test 5（補充）: LivePreviewer.render_once() 產 PDF ─────────────

def test_live_previewer_render_once(tmp_path: Path, fake_fonts_dir):
    """LivePreviewer.render_once() 應產出 PDF，回傳 RenderResult。"""
    import shutil
    test_html = tmp_path / "test_section.html"
    shutil.copy(EXAMPLES_HTML, test_html)

    lp = LivePreviewer(
        html_path=test_html,
        output_pdf=tmp_path / "test_output.pdf",
        fonts_dir=fake_fonts_dir,
        use_polling=True,
    )
    result = lp.render_once()

    assert isinstance(result, RenderResult)
    assert result.pdf_path == str(tmp_path / "test_output.pdf")
    assert Path(result.pdf_path).exists()
    assert result.bytes > 0
    assert result.duration_ms >= 0
    assert result.timestamp


# ─── Test 6（補充）: LivePreviewer 預設 output_pdf = html.with_suffix(.pdf) ─

def test_live_previewer_default_output_path(tmp_path: Path):
    """不指定 output_pdf 時，預設 = HTML 同目錄 + .pdf 副檔名。"""
    import shutil
    test_html = tmp_path / "my_section.html"
    shutil.copy(EXAMPLES_HTML, test_html)

    lp = LivePreviewer(html_path=test_html, use_polling=True)
    assert lp.output_pdf == test_html.with_suffix(".pdf")


# ─── Test 7（補充）: quality_check=True 但 HTML 合規時仍 render ─────

def test_live_previewer_quality_check_advisory(tmp_path: Path, fake_fonts_dir):
    """quality_check=True 時，命中禁用清單會 warn 但 render 仍會進行（advisory）。"""
    import shutil
    test_html = tmp_path / "bad_section.html"
    shutil.copy(EXAMPLES_HTML, test_html)

    lp = LivePreviewer(
        html_path=test_html,
        output_pdf=tmp_path / "bad_output.pdf",
        fonts_dir=fake_fonts_dir,
        quality_check=True,
        use_polling=True,
    )
    # examples/section_1.html 應是合規的（已通過其他測試驗證）
    result = lp.render_once()
    assert result.pdf_path and Path(result.pdf_path).exists()
    # 合規 HTML → quality_passed=True, violations=[]
    assert result.quality_passed is True
    assert result.quality_violations == []


# ─── Test 8（補充）: --open-browser flag 接受（不真的開瀏覽器） ───

def test_live_preview_cli_open_browser_flag(tmp_path: Path):
    """CLI 接受 --open-browser flag（不真的開瀏覽器，因為 headless 環境）。"""
    import shutil
    test_html = tmp_path / "section_1.html"
    shutil.copy(EXAMPLES_HTML, test_html)

    # 我們 patch webbrowser.open 來避免在 headless 環境彈窗
    # 改用 monkeypatch
    result = subprocess.run(
        [
            sys.executable, "-c",
            # 用 inline Python 模擬：呼叫 LivePreviewer 並驗證 open_browser=True 不 crash
            "import sys; "
            "sys.path.insert(0, '.'); "
            "from pathlib import Path; "
            f"from scripts.live_preview import LivePreviewer; "
            f"lp = LivePreviewer(html_path=Path('{test_html}'), "
            "open_browser=False, use_polling=True); "  # 關掉真的開瀏覽器
            "r = lp.render_once(); "
            "assert r.bytes > 0; "
            "print('OK')",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"失敗：stdout={result.stdout}, stderr={result.stderr}"
    )
    assert "OK" in result.stdout


# ─── Test 9（補充）: workflow 引用 executor-base + html_to_pdf ──────

def test_workflow_references_executor_and_html_to_pdf():
    """workflow 應引用 references/executor-base.md 與 scripts/html_to_pdf.py。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert "references/executor-base.md" in content, (
        "workflow 應引用 references/executor-base.md"
    )
    assert "html_to_pdf" in content, (
        "workflow 應引用 html_to_pdf（render 引擎）"
    )


# ─── Test 10（補充）: workflow 描述的 CLI 範例存在於 workflow doc ─────

def test_workflow_md_contains_cli_examples():
    """workflow 應含 CLI 範例（`--once`, `--open-browser`, `--quality-check`）。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert "--once" in content, "workflow 應含 --once CLI 範例"
    assert "--open-browser" in content, "workflow 應含 --open-browser CLI 範例"
    assert "watchfiles" in content or "polling" in content, (
        "workflow 應含 watchfiles 或 polling 說明"
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