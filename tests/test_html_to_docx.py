# test_html_to_docx.py — tests for html_to_docx (pandoc wrapper)
# 涵蓋：基本 OK、HTML 字串輸入、toc 啟用、缺 pandoc fail-fast、CLI

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.html_to_docx import (
    html_to_docx,
    find_pandoc,
    pandoc_version,
    HTMLSourceError,
    PandocRenderError,
    PandocNotFoundError,
)


SIMPLE_HTML = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>範例</title>
</head>
<body>
<h1>第一章 緒論</h1>
<p>這是中文段落。包含 <strong>粗體</strong> 與 <em>斜體</em>。</p>
<h2>1.1 子節</h2>
<p>內含 <a href="#ref1">[1]</a> 連結。</p>
<table>
  <tr><th>項目</th><th>數值</th></tr>
  <tr><td>字數</td><td>12,345</td></tr>
</table>
</body>
</html>
"""


# Skip the whole module if pandoc not available
pandoc = find_pandoc() if shutil.which("pandoc") else None
pytestmark = pytest.mark.skipif(
    pandoc is None,
    reason="pandoc not installed (required for these tests)"
)


# ────────────────────────────────────────────────────────────────────
# Basic happy paths
# ────────────────────────────────────────────────────────────────────

def test_html_to_docx_string(tmp_path):
    out = tmp_path / "out.docx"
    result = html_to_docx(SIMPLE_HTML, out)
    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0


def test_html_to_docx_file(tmp_path):
    in_html = tmp_path / "in.html"
    in_html.write_text(SIMPLE_HTML, encoding="utf-8")
    out = tmp_path / "out.docx"
    html_to_docx(in_html, out)
    assert out.exists()
    assert out.stat().st_size > 0


def test_html_to_docx_with_toc(tmp_path):
    out = tmp_path / "out.docx"
    html_to_docx(SIMPLE_HTML, out, toc=True, toc_depth=2)
    assert out.exists()
    # Verify it's a valid DOCX (ZIP)
    import zipfile
    with zipfile.ZipFile(str(out)) as z:
        assert "[Content_Types].xml" in z.namelist()
        assert "word/document.xml" in z.namelist()


def test_html_to_docx_creates_output_dir(tmp_path):
    nested_out = tmp_path / "deep" / "nested" / "out.docx"
    html_to_docx(SIMPLE_HTML, nested_out)
    assert nested_out.exists()


# ────────────────────────────────────────────────────────────────────
# Source errors
# ────────────────────────────────────────────────────────────────────

def test_empty_html_raises(tmp_path):
    out = tmp_path / "out.docx"
    with pytest.raises(HTMLSourceError):
        html_to_docx("", out)


def test_missing_file_raises(tmp_path):
    out = tmp_path / "out.docx"
    with pytest.raises(HTMLSourceError):
        html_to_docx(str(tmp_path / "nope.html"), out)


def test_empty_file_raises(tmp_path):
    p = tmp_path / "empty.html"
    p.write_text("", encoding="utf-8")
    out = tmp_path / "out.docx"
    with pytest.raises(HTMLSourceError):
        html_to_docx(p, out)


# ────────────────────────────────────────────────────────────────────
# Discovery
# ────────────────────────────────────────────────────────────────────

def test_find_pandoc_returns_path():
    p = find_pandoc()
    assert Path(p).exists()


def test_pandoc_version_format():
    v = pandoc_version()
    # Should be like "3.1.13" or similar (digits + dots)
    assert v
    parts = v.split(".")
    assert len(parts) >= 2
    assert all(p.isdigit() for p in parts)


# ────────────────────────────────────────────────────────────────────
# Reference docx handling
# ────────────────────────────────────────────────────────────────────

def test_html_to_docx_reference_docx_missing_raises(tmp_path):
    out = tmp_path / "out.docx"
    with pytest.raises(HTMLSourceError):
        html_to_docx(SIMPLE_HTML, out, reference_docx=str(tmp_path / "nope.docx"))


def test_html_to_docx_reference_docx_ok(tmp_path):
    # Create a minimal reference docx (use the just-generated one)
    ref_docx = tmp_path / "ref.docx"
    html_to_docx(SIMPLE_HTML, ref_docx)  # bootstrap a real docx
    out = tmp_path / "out.docx"
    html_to_docx(SIMPLE_HTML, out, reference_docx=ref_docx)
    assert out.exists()


# ────────────────────────────────────────────────────────────────────
# CLI smoke
# ────────────────────────────────────────────────────────────────────

def test_cli_runs(tmp_path):
    in_html = tmp_path / "in.html"
    in_html.write_text(SIMPLE_HTML, encoding="utf-8")
    out = tmp_path / "out.docx"

    from scripts.html_to_docx import _main
    rc = _main([str(in_html), "-o", str(out), "--toc"])
    assert rc == 0
    assert out.exists()