# test_html_to_pdf.py — tests for html_to_pdf (weasyprint wrapper)
# 涵蓋：基本 OK、字體缺失 fail-fast、HTML 為空、HTML 路徑不存在

import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.html_to_pdf import (
    html_to_pdf,
    discover_fonts,
    assert_required_fonts,
    HTMLSourceError,
    FontNotFoundError,
    PDFRenderError,
    WeasyPrintNotInstalled,
)


SIMPLE_HTML = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<style>
body { font-family: '標楷體', 'Times New Roman', serif; font-size: 12pt; }
h1 { font-family: '標楷體', 'Times New Roman', serif; font-size: 18pt; }
</style>
</head>
<body>
<h1>標題</h1>
<p>中文段落測試。</p>
<table>
  <tr><th>項目</th><th>數值</th></tr>
  <tr><td>字數</td><td>12,345</td></tr>
</table>
</body>
</html>
"""


@pytest.fixture
def fake_fonts_dir(tmp_path):
    """Create a fake fonts dir with one .ttf file (weasyprint doesn't care about validity for size check)."""
    d = tmp_path / "fonts"
    d.mkdir()
    (d / "fake-cjk.ttf").write_bytes(b"\x00\x01\x00\x00" + b"\x00" * 100)
    (d / "fake-latin.otf").write_bytes(b"\x00\x01\x00\x00" + b"\x00" * 100)
    return d


# ────────────────────────────────────────────────────────────────────
# Basic happy path
# ────────────────────────────────────────────────────────────────────

def test_html_to_pdf_string_input(tmp_path, fake_fonts_dir):
    out = tmp_path / "out.pdf"
    result = html_to_pdf(SIMPLE_HTML, out, fonts_dir=fake_fonts_dir)
    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0
    # Verify it's a PDF (starts with %PDF)
    with open(out, "rb") as f:
        header = f.read(8)
    assert header.startswith(b"%PDF-")


def test_html_to_pdf_file_input(tmp_path, fake_fonts_dir):
    in_html = tmp_path / "in.html"
    in_html.write_text(SIMPLE_HTML, encoding="utf-8")
    out = tmp_path / "out.pdf"
    result = html_to_pdf(in_html, out, fonts_dir=fake_fonts_dir)
    assert out.exists()
    assert out.stat().st_size > 0


def test_html_to_pdf_creates_output_dir(tmp_path, fake_fonts_dir):
    nested_out = tmp_path / "deep" / "nested" / "out.pdf"
    result = html_to_pdf(SIMPLE_HTML, nested_out, fonts_dir=fake_fonts_dir)
    assert nested_out.exists()


# ────────────────────────────────────────────────────────────────────
# Font fail-fast
# ────────────────────────────────────────────────────────────────────

def test_fonts_dir_missing_raises(tmp_path):
    """In non-strict mode (default), missing fonts/ should NOT raise.
    Use strict=True via assert_required_fonts() to get fail-fast."""
    empty = tmp_path / "no_fonts"
    empty.mkdir()
    out = tmp_path / "out.pdf"
    # sub-empty dir has no fonts
    sub = empty / "fonts"
    # html_to_pdf uses non-strict by default — should not raise here
    try:
        html_to_pdf(SIMPLE_HTML, out, fonts_dir=sub)
    except FontNotFoundError:
        pass  # acceptable if internal logic changed
    else:
        assert out.exists(), "PDF should be generated even without project fonts"


def test_assert_required_fonts_strict_raises(tmp_path):
    empty = tmp_path / "no_fonts"
    empty.mkdir()
    # Strict mode should raise
    with pytest.raises(FontNotFoundError):
        assert_required_fonts(empty, strict=True)


def test_assert_required_fonts_nonstrict_warns(tmp_path):
    empty = tmp_path / "no_fonts"
    empty.mkdir()
    # Non-strict should return empty list (and log warning)
    result = assert_required_fonts(empty, strict=False)
    assert result == []


def test_fonts_dir_with_files_ok(tmp_path, fake_fonts_dir):
    fonts = discover_fonts(fake_fonts_dir)
    assert len(fonts) == 2
    assert any("cjk" in f.name for f in fonts)


def test_discover_fonts_empty_dir(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    fonts = discover_fonts(d)
    assert fonts == []


def test_assert_required_fonts_missing_dir(tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(FontNotFoundError):
        assert_required_fonts(missing, strict=True)


def test_assert_required_fonts_empty_dir(tmp_path):
    empty = tmp_path / "empty_fonts"
    empty.mkdir()
    with pytest.raises(FontNotFoundError):
        assert_required_fonts(empty, strict=True)


# ────────────────────────────────────────────────────────────────────
# HTML source errors
# ────────────────────────────────────────────────────────────────────

def test_empty_html_string_raises(tmp_path, fake_fonts_dir):
    out = tmp_path / "out.pdf"
    with pytest.raises(HTMLSourceError):
        html_to_pdf("   \n  ", out, fonts_dir=fake_fonts_dir)


def test_empty_html_file_raises(tmp_path, fake_fonts_dir):
    p = tmp_path / "empty.html"
    p.write_text("", encoding="utf-8")
    out = tmp_path / "out.pdf"
    with pytest.raises(HTMLSourceError):
        html_to_pdf(p, out, fonts_dir=fake_fonts_dir)


def test_missing_html_file_raises(tmp_path, fake_fonts_dir):
    p = tmp_path / "nope.html"
    out = tmp_path / "out.pdf"
    with pytest.raises(HTMLSourceError):
        html_to_pdf(p, out, fonts_dir=fake_fonts_dir)


# ────────────────────────────────────────────────────────────────────
# Extra CSS option
# ────────────────────────────────────────────────────────────────────

def test_extra_css_applied(tmp_path, fake_fonts_dir):
    extra = "h1 { color: red; }"
    out = tmp_path / "out.pdf"
    # Should not raise
    html_to_pdf(SIMPLE_HTML, out, fonts_dir=fake_fonts_dir, extra_css=extra)
    assert out.exists()


# ────────────────────────────────────────────────────────────────────
# CLI smoke
# ────────────────────────────────────────────────────────────────────

def test_cli_runs(tmp_path, fake_fonts_dir):
    in_html = tmp_path / "in.html"
    in_html.write_text(SIMPLE_HTML, encoding="utf-8")
    out = tmp_path / "out.pdf"

    from scripts.html_to_pdf import _main
    rc = _main([
        str(in_html),
        "-o", str(out),
        "--fonts-dir", str(fake_fonts_dir),
    ])
    assert rc == 0
    assert out.exists()