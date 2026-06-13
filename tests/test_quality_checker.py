# test_quality_checker.py — tests for HTML/CSS quality gate
# 對應 shared-standards.md §2 禁用清單
#
# Test cases:
#   OK: 合法 HTML — 應 PASS
#   FAIL: 多種禁用規則 — 應 BLOCKING

import sys
from pathlib import Path

import pytest

# Allow tests to import from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.quality_checker import (
    scan_html,
    check_html,
    check_html_file,
    QualityCheckError,
)


# ────────────────────────────────────────────────────────────────────
# OK cases
# ────────────────────────────────────────────────────────────────────

OK_HTML = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>範例報告</title>
<style>
  body { font-family: '標楷體', 'Times New Roman', serif; font-size: 12pt; line-height: 1.5; }
  h1 { font-family: '標楷體', 'Times New Roman', serif; font-size: 18pt; font-weight: bold; }
  h2 { font-family: '標楷體', 'Times New Roman', serif; font-size: 16pt; font-weight: bold; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid #ccc; padding: 0.5em; }
  .caption { text-align: center; font-size: 10pt; }
</style>
</head>
<body>
  <h1>第一章 緒論</h1>
  <p>本研究探討 <strong>標楷體</strong> 與 <em>Times New Roman</em> 的混排。</p>
  <h2>1.1 研究背景</h2>
  <p>參考文獻 <a href="#ref1">[1]</a> 指出...</p>
  <table>
    <thead><tr><th>項目</th><th>數值</th></tr></thead>
    <tbody><tr><td>字數</td><td>12,345</td></tr></tbody>
  </table>
  <p class="caption">Table 1: 範例表格</p>
</body>
</html>
"""


def test_ok_html_passes():
    rep = scan_html(OK_HTML, "OK")
    assert rep.passed is True
    assert len(rep.violations) == 0


def test_check_html_ok_does_not_raise():
    # Should NOT raise
    check_html(OK_HTML, "OK")


# ────────────────────────────────────────────────────────────────────
# FAIL cases — each forbidden rule
# ────────────────────────────────────────────────────────────────────

def test_fail_display_flex():
    html = '<html><body><div style="display: flex">x</div></body></html>'
    rep = scan_html(html)
    assert rep.passed is False
    rules = {v["rule"] for v in rep.violations}
    assert any("flex" in r for r in rules)


def test_fail_display_grid():
    html = '<html><body><div style="display: grid">x</div></body></html>'
    rep = scan_html(html)
    assert rep.passed is False
    assert any("grid" in v["rule"] for v in rep.violations)


def test_fail_position_absolute():
    html = '<html><body><div style="position: absolute">x</div></body></html>'
    rep = scan_html(html)
    assert rep.passed is False
    assert any("absolute" in v["rule"] for v in rep.violations)


def test_fail_position_fixed():
    html = '<html><body><div style="position: fixed">x</div></body></html>'
    rep = scan_html(html)
    assert rep.passed is False
    assert any("fixed" in v["rule"] for v in rep.violations)


def test_fail_pseudo_before():
    html = '<html><head><style>.q::before { content: "x"; }</style></head><body></body></html>'
    rep = scan_html(html)
    assert rep.passed is False
    assert any("::before" in v["rule"] or "before" in v["rule"].lower() for v in rep.violations)


def test_fail_pseudo_after():
    html = '<html><head><style>.q::after { content: "x"; }</style></head><body></body></html>'
    rep = scan_html(html)
    assert rep.passed is False
    assert any("::after" in v["rule"] or "after" in v["rule"].lower() for v in rep.violations)


def test_fail_external_css_link():
    html = '<html><head><link rel="stylesheet" href="foo.css"></head><body></body></html>'
    rep = scan_html(html)
    assert rep.passed is False
    assert any("stylesheet" in v["rule"] for v in rep.violations)


def test_fail_external_css_import():
    html = '<html><head><style>@import url("foo.css");</style></head><body></body></html>'
    rep = scan_html(html)
    assert rep.passed is False
    assert any("@import" in v["rule"] for v in rep.violations)


def test_fail_script_tag():
    html = '<html><body><script>alert(1)</script></body></html>'
    rep = scan_html(html)
    assert rep.passed is False
    assert any("<script>" in v["rule"] for v in rep.violations)


def test_fail_canvas_tag():
    html = '<html><body><canvas id="c"></canvas></body></html>'
    rep = scan_html(html)
    assert rep.passed is False
    assert any("<canvas>" in v["rule"] for v in rep.violations)


def test_fail_iframe_tag():
    html = '<html><body><iframe src="x"></iframe></body></html>'
    rep = scan_html(html)
    assert rep.passed is False
    assert any("<iframe>" in v["rule"] for v in rep.violations)


def test_fail_float_on_non_img():
    html = '<html><body><div style="float: left;">sidebar</div></body></html>'
    rep = scan_html(html)
    assert rep.passed is False
    assert any("float" in v["rule"] for v in rep.violations)


def test_float_on_img_is_ok():
    # The <img> with float is acceptable (standard caption wrapping pattern)
    html = '<html><body><img src="x.jpg" style="float: right;" alt="fig"></body></html>'
    rep = scan_html(html)
    # Should not produce float violation because of the <img> exemption
    float_violations = [v for v in rep.violations if "float" in v["rule"]]
    assert float_violations == []


def test_fail_onclick_handler():
    html = '<html><body><button onclick="alert(1)">x</button></body></html>'
    rep = scan_html(html)
    assert rep.passed is False
    assert any("onclick" in v["rule"] or "on*" in v["rule"] for v in rep.violations)


def test_fail_forbidden_font_calibri():
    html = '<html><head><style>body { font-family: "Calibri"; }</style></head><body></body></html>'
    rep = scan_html(html)
    assert rep.passed is False
    assert any("Calibri" in v["rule"] or "字體" in v["rule"] for v in rep.violations)


def test_raise_on_fail():
    html = '<html><body><div style="display: flex">x</div></body></html>'
    with pytest.raises(QualityCheckError) as exc_info:
        check_html(html, "test")
    assert "display" in str(exc_info.value).lower() or "flex" in str(exc_info.value).lower()


# ────────────────────────────────────────────────────────────────────
# File-based check
# ────────────────────────────────────────────────────────────────────

def test_check_html_file_ok(tmp_path):
    p = tmp_path / "ok.html"
    p.write_text(OK_HTML, encoding="utf-8")
    check_html_file(p)  # should not raise


def test_check_html_file_missing(tmp_path):
    p = tmp_path / "missing.html"
    with pytest.raises(FileNotFoundError):
        check_html_file(p)


def test_check_html_file_fails(tmp_path):
    p = tmp_path / "bad.html"
    p.write_text('<html><body><div style="display: flex"></div></body></html>', encoding="utf-8")
    with pytest.raises(QualityCheckError):
        check_html_file(p)


# ────────────────────────────────────────────────────────────────────
# Mixed: OK + FAIL combination
# ────────────────────────────────────────────────────────────────────

def test_multiple_violations():
    html = """<html><head>
<style>
.x { display: flex; position: absolute; }
.y::before { content: 'x'; }
</style>
<link rel="stylesheet" href="foo.css">
</head><body>
<script>alert(1)</script>
<canvas></canvas>
<iframe src="x"></iframe>
<div style="float: left;">x</div>
</body></html>
"""
    rep = scan_html(html)
    assert rep.passed is False
    # Should catch at least 7 distinct violations
    assert len(rep.violations) >= 7
    rules = {v["rule"] for v in rep.violations}
    assert any("flex" in r for r in rules)
    assert any("absolute" in r for r in rules)
    assert any("::before" in r or "before" in r.lower() for r in rules)
    assert any("stylesheet" in r for r in rules)
    assert any("<script>" in r for r in rules)
    assert any("<canvas>" in r for r in rules)
    assert any("<iframe>" in r for r in rules)
    assert any("float" in r for r in rules)