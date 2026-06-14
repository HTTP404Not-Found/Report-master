"""tests/test_quality_checker_section_opener.py — check_section_opener 整合測試

對應 references/executor-base.md §3.3.5「Section Opener Rule」（v1.1 新增 — D7）。

測試範圍：
  1. check_section_opener() 獨立函式行為
  2. revise_helper.ensure_section_openers() 修補流程
  3. examples/ 3 份範例端到端通過

設計：6 個必要 cases + 7 個補充 cases
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.quality_checker import check_section_opener  # noqa: E402
from scripts.revise_helper import (  # noqa: E402
    build_opener_paragraph,
    ensure_section_openers,
)


# ─── Fixtures：3 種情境的 HTML 樣本 ─────────────────────────────────

HTML_PASS = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>Section Opener PASS</title>
</head>
<body>
<h1>第一章 緒論</h1>
<p>本章說明研究動機與方法。這是第一段的第二句。</p>

<h2>1.1 研究背景</h2>
<p>近年 AI 快速發展。本節將回顧相關文獻。</p>

<h3>1.1.1 子主題</h3>
<p>子主題說明在此。文末句號。</p>
</body>
</html>
"""

HTML_FAIL_H2_LIST = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>Section Opener FAIL H2-list</title>
</head>
<body>
<h1>第一章 緒論</h1>
<p>本章探討主題。第一段第二句收尾。</p>

<h2>2.1 章節結構</h2>
<ul>
  <li>第一項</li>
  <li>第二項</li>
</ul>
</body>
</html>
"""

HTML_FAIL_H3_TABLE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>Section Opener FAIL H3-table</title>
</head>
<body>
<h1>第三章 結果</h1>
<p>本章呈現實驗結果。資料以表格整理如下。</p>

<h3>3.1.1 統計數據</h3>
<table>
  <tr><th>項目</th><th>數值</th></tr>
  <tr><td>A</td><td>1</td></tr>
</table>
</body>
</html>
"""

HTML_FAIL_SHORT_P = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>FAIL — opener 過短</title>
</head>
<body>
<h1>第一章 緒論</h1>
<p>本章是緒論。內含背景說明。</p>

<h2>1.1 動機</h2>
<p>動機說明只有一句。</p>
</body>
</html>
"""

HTML_FAIL_CAPTION = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>FAIL — caption 不算 opener</title>
</head>
<body>
<h1>第一章 緒論</h1>
<p>本章是緒論。內含圖表。</p>

<h2>1.1 圖表</h2>
<p class="caption">Table 1: 範例</p>
<table><tr><td>x</td></tr></table>
</body>
</html>
"""

HTML_EDGE_BARE = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>邊界 — 章節首段</title>
</head>
<body>
<h2>1.1 邊界</h2>
<p>這是合格 opener。有兩個句號在內。</p>
</body>
</html>
"""


# ─── Test 1（必要）：PASS case ───────────────────────────────────────

def test_check_section_opener_pass():
    warnings = check_section_opener(HTML_PASS, source="PASS")
    assert warnings == []


# ─── Test 2（必要）：FAIL — H2 直連 <ul> ────────────────────────────

def test_check_section_opener_fail_h2_list():
    warnings = check_section_opener(HTML_FAIL_H2_LIST, source="H2-LIST")
    assert len(warnings) == 1
    w = warnings[0]
    assert w["heading_level"] == "h2"
    assert w["heading_text"] == "2.1 章節結構"
    assert "<ul>" in w["rule"]
    assert w["severity"] == "WARN"


# ─── Test 3（必要）：FAIL — H3 直連 <table> ─────────────────────────

def test_check_section_opener_fail_h3_table():
    warnings = check_section_opener(HTML_FAIL_H3_TABLE, source="H3-TABLE")
    assert len(warnings) == 1
    w = warnings[0]
    assert w["heading_level"] == "h3"
    assert w["heading_text"] == "3.1.1 統計數據"
    assert "<table>" in w["rule"]
    assert w["severity"] == "WARN"


# ─── Test 4（補充）：FAIL — opener 過短 ─────────────────────────────

def test_check_section_opener_fail_short_p():
    warnings = check_section_opener(HTML_FAIL_SHORT_P, source="SHORT-P")
    assert len(warnings) == 1
    w = warnings[0]
    assert "過短" in w["rule"]
    assert "僅 1 句" in w["rule"]
    assert w["severity"] == "WARN"


# ─── Test 5（補充）：FAIL — caption 不算 opener ─────────────────────

def test_check_section_opener_fail_caption():
    warnings = check_section_opener(HTML_FAIL_CAPTION, source="CAPTION")
    assert len(warnings) == 1
    w = warnings[0]
    assert "caption" in w["rule"].lower() or "<p>" in w["rule"]
    assert w["severity"] == "WARN"


# ─── Test 6（補充）：邊界 — 第一個 H2 也要 opener ──────────────────

def test_check_section_opener_edge_bare():
    warnings = check_section_opener(HTML_EDGE_BARE, source="EDGE")
    assert warnings == []


# ─── Test 7（補充）：revise_helper.ensure_section_openers() 修補流程 ────

def test_ensure_section_openers_patches_h2_list():
    patched, warnings = ensure_section_openers(HTML_FAIL_H2_LIST)
    assert len(warnings) == 1
    assert "<p" in patched
    recheck = check_section_opener(patched, source="AFTER-PATCH")
    assert recheck == []


def test_ensure_section_openers_patches_h3_table():
    patched, warnings = ensure_section_openers(HTML_FAIL_H3_TABLE)
    assert len(warnings) == 1
    assert "<p" in patched
    recheck = check_section_opener(patched, source="AFTER-PATCH")
    assert recheck == []


def test_ensure_section_openers_noop_when_ok():
    patched, warnings = ensure_section_openers(HTML_PASS)
    assert warnings == []
    assert patched.count("<p") == HTML_PASS.count("<p")


# ─── Test 8（補充）：build_opener_paragraph 產生合法 opener ─────────

def test_build_opener_paragraph_contains_2_sentences():
    opener = build_opener_paragraph("1.1 研究背景")
    assert opener.startswith("<p>")
    assert opener.endswith("</p>")
    import re
    sent_end = re.findall(r"[.。!?！?？]", opener)
    assert len(sent_end) >= 2, f"opener 句數 {len(sent_end)} < 2: {opener}"


# ─── Test 9（補充）：examples/ 3 份範例端到端通過 ───────────────────

EXAMPLES_FILES = [
    PROJECT_ROOT / "examples" / "section_1.html",
    PROJECT_ROOT / "examples" / "output_1" / "section_1.html",
    PROJECT_ROOT / "examples" / "output_2" / "section_1.html",
]


@pytest.mark.parametrize("example_path", EXAMPLES_FILES, ids=lambda p: p.name)
def test_examples_pass_section_opener(example_path: Path):
    if not example_path.exists():
        pytest.skip(f"example not found: {example_path}")
    html = example_path.read_text(encoding="utf-8")
    warnings = check_section_opener(html, source=str(example_path.relative_to(PROJECT_ROOT)))
    assert warnings == [], (
        f"{example_path.name} 有 {len(warnings)} 條 opener 違規：\n"
        + "\n".join(
            f"  - [{w.get('heading_level', '?')}] {w.get('heading_text', '')[:50]} → {w.get('rule', '')}"
            for w in warnings
        )
    )