# test_toc_generator.py — tests for toc_generator (pandoc --toc wrapper)
# 涵蓋：基本 OK、TOC 注入、depth 參數、邊界錯誤

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.toc_generator import (
    generate_toc,
    _inject_toc,
    _extract_toc_block,
    TOCGeneratorError,
)

from scripts.html_to_docx import find_pandoc

# Skip if pandoc missing
pytestmark = pytest.mark.skipif(
    shutil.which("pandoc") is None,
    reason="pandoc not installed"
)


HTML_WITH_HEADINGS = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>TOC Test</title>
<style>body{font-family:'標楷體',serif;}</style>
</head>
<body>
<h1>第一章 緒論</h1>
<p>內容 1</p>
<h2>1.1 背景</h2>
<p>內容 2</p>
<h1>第二章 方法</h1>
<p>內容 3</p>
<h2>2.1 流程</h2>
<p>內容 4</p>
<h2>2.2 工具</h2>
<p>內容 5</p>
<h1>第三章 結論</h1>
<p>內容 6</p>
</body>
</html>
"""


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

def test_inject_toc_after_body():
    html = "<html><body><h1>x</h1></body></html>"
    toc = '<nav id="TOC"><ul><li><a href="#x">x</a></li></ul></nav>'
    out = _inject_toc(html, toc)
    # TOC should appear after <body>, before <h1>
    assert '<nav id="TOC">' in out
    assert out.index('<nav id="TOC">') < out.index("<h1>x</h1>")


def test_inject_toc_replaces_existing():
    html = '<html><body><nav id="TOC">OLD</nav><h1>x</h1></body></html>'
    new_toc = '<nav id="TOC">NEW</nav>'
    out = _inject_toc(html, new_toc)
    assert "NEW" in out
    assert "OLD" not in out


def test_extract_toc_block():
    html = '<html><body><nav id="TOC"><ul><li>x</li></ul></nav></body></html>'
    block = _extract_toc_block(html)
    assert block is not None
    assert "<nav" in block
    assert "TOC" in block


def test_extract_toc_block_missing():
    html = "<html><body><h1>x</h1></body></html>"
    block = _extract_toc_block(html)
    assert block is None


# ────────────────────────────────────────────────────────────────────
# generate_toc — happy path
# ────────────────────────────────────────────────────────────────────

def test_generate_toc_string():
    result = generate_toc(HTML_WITH_HEADINGS, toc_depth=2)
    assert "<nav" in result
    assert 'id="TOC"' in result
    # Original content should still be present
    assert "第一章 緒論" in result
    assert "第二章 方法" in result


def test_generate_toc_file(tmp_path):
    in_html = tmp_path / "in.html"
    in_html.write_text(HTML_WITH_HEADINGS, encoding="utf-8")
    out_html = tmp_path / "out.html"
    result = generate_toc(in_html, out_html, toc_depth=2)
    assert out_html.exists()
    assert "<nav" in result


def test_generate_toc_depth_3():
    # Should include H3 if present (we use H2 in test, but depth=3 should still work)
    result = generate_toc(HTML_WITH_HEADINGS, toc_depth=3)
    assert "<nav" in result


def test_generate_toc_depth_1():
    result = generate_toc(HTML_WITH_HEADINGS, toc_depth=1)
    assert "<nav" in result


# ────────────────────────────────────────────────────────────────────
# Error cases
# ────────────────────────────────────────────────────────────────────

def test_invalid_toc_depth():
    with pytest.raises(TOCGeneratorError):
        generate_toc(HTML_WITH_HEADINGS, toc_depth=0)
    with pytest.raises(TOCGeneratorError):
        generate_toc(HTML_WITH_HEADINGS, toc_depth=7)


def test_empty_html_string():
    with pytest.raises(Exception):  # HTMLSourceError or PandocRenderError
        generate_toc("", toc_depth=2)


def test_missing_file(tmp_path):
    with pytest.raises(Exception):
        generate_toc(str(tmp_path / "nope.html"), toc_depth=2)


def test_empty_file(tmp_path):
    p = tmp_path / "empty.html"
    p.write_text("", encoding="utf-8")
    with pytest.raises(Exception):
        generate_toc(p, toc_depth=2)