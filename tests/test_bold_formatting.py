# test_bold_formatting.py — Problem 4: DOCX bold formatting tests
# 對應 tasks.md Phase 3 缺陷 #4
# 場景：
#   1. <strong> → Word run with bold=True
#   2. **text** literal → 經 sanitize 轉成 <strong> → bold run
#   3. 最終 DOCX 內文不含 literal `**` 殘留
#
# 同時也守住：
#   - __text__ (alt markdown bold) → bold
#   - tag 屬性（href="..."）內的 ** 不被 sanitize 破壞
#   - 巢狀 <strong><strong> 仍 bold（idempotent）

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

import pytest

# 把 project root 加到 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.html_to_docx_direct import (
    _sanitize_markdown_emphasis,
    html_to_docx_direct,
    HTMLToDOCXDirectError,
    HTMLToDOCXDirectImportError,
    _require_deps,
)


# ────────────────────────────────────────────────────────────────────
# Skip if required deps missing
# ────────────────────────────────────────────────────────────────────

def _has_deps() -> bool:
    try:
        _require_deps()
        return True
    except HTMLToDOCXDirectImportError:
        return False


pytestmark = pytest.mark.skipif(
    not _has_deps(),
    reason="python-docx / beautifulsoup4 / lxml not installed",
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCK = PROJECT_ROOT / "examples" / "lock.md"


def _read_docx_xml(docx_path: Path, member: str = "word/document.xml") -> str:
    """讀 DOCX 內的 XML 成員（document.xml / styles.xml）。"""
    with zipfile.ZipFile(str(docx_path)) as z:
        return z.read(member).decode("utf-8")


def _runs_containing(document_xml: str, needle: str) -> list[str]:
    """找出所有包含 needle 字串的 <w:r> 元素（內部 XML 片段）。"""
    pattern = re.compile(r"<w:r(?:\s[^>]*)?>(.*?)</w:r>", re.DOTALL)
    runs = pattern.findall(document_xml)
    return [r for r in runs if needle in r]


def _has_bold_run(document_xml: str, needle: str) -> bool:
    """檢查 needle 出現在至少一個帶 <w:b/> 旗標的 run 中。"""
    for r in _runs_containing(document_xml, needle):
        if "<w:b/>" in r or "<w:b " in r:
            return True
    return False


# ────────────────────────────────────────────────────────────────────
# Test 1: <strong> → DOCX run with bold=True (clean path)
# ────────────────────────────────────────────────────────────────────

def test_strong_tag_produces_bold_run(tmp_path: Path):
    """<strong>text</strong> 應被轉成 Word 粗體 run（含 <w:b/>）。"""
    html = (
        "<html><body>"
        "<p>這是 <strong>粗體內容</strong> 結尾</p>"
        "</body></html>"
    )
    out = tmp_path / "bold_clean.docx"
    html_to_docx_direct(html, out, lock_file=DEFAULT_LOCK)

    doc_xml = _read_docx_xml(out)
    assert _has_bold_run(doc_xml, "粗體內容"), (
        "<strong> 文字應出現在至少一個帶 <w:b/> 旗標的 run 中。"
        f"\n實際 document.xml 片段：\n{doc_xml[:600]}"
    )
    # Also confirm no literal ** remains
    assert "**粗體內容**" not in doc_xml, (
        "DOCX 內文不應含 literal `**粗體內容**` 字串"
    )


# ────────────────────────────────────────────────────────────────────
# Test 2: **text** literal → sanitizer → <strong> → bold run
# ────────────────────────────────────────────────────────────────────

def test_markdown_bold_double_star_becomes_bold(tmp_path: Path):
    """literal `**text**` Markdown 粗體應被 sanitize 轉成 <strong>，
    並在 DOCX 內以 bold run 呈現（不再保留 literal `**`）。
    """
    html = (
        "<html><body>"
        "<p>報告 <strong>重點摘要</strong> 以及 **待加粗詞** 與結尾。</p>"
        "</body></html>"
    )
    out = tmp_path / "bold_dirty.docx"
    html_to_docx_direct(html, out, lock_file=DEFAULT_LOCK)

    doc_xml = _read_docx_xml(out)
    # Both <strong> and **...** → must end up as bold runs
    assert _has_bold_run(doc_xml, "重點摘要"), (
        "<strong> 重點摘要 應是 bold run"
    )
    assert _has_bold_run(doc_xml, "待加粗詞"), (
        "literal `**待加粗詞**` 應被 sanitize 並轉成 bold run"
    )
    # Sanity: no literal ** should remain anywhere in document.xml
    assert "**" not in doc_xml, (
        f"DOCX 內文不應含 literal `**`。實際片段：{doc_xml[:400]}"
    )
    # Verify the sanitized text content is preserved
    runs = _runs_containing(doc_xml, "待加粗詞")
    assert len(runs) >= 1, "應有 run 包含『待加粗詞』"


# ────────────────────────────────────────────────────────────────────
# Test 3: __text__ alt syntax + 內文不含 ** 殘留
# ────────────────────────────────────────────────────────────────────

def test_no_literal_double_star_in_docx_output(tmp_path: Path):
    """任何輸入（即使混合 literal `**`、`<b>`、巢狀 `<strong>`），
    最終 DOCX 內文不應出現 literal `**` 殘留，且所有粗體 marker 都轉成
    真正的 Word bold run。
    """
    html = (
        "<html><body>"
        "<h1>標題含 **殘留字串** 測試</h1>"
        "<p>段落 1：<b>粗體 b</b> 與 <strong>粗體 strong</strong>。</p>"
        "<p>段落 2：__雙底線粗體__ 與 <em>斜體</em> 混排。</p>"
        "<p>段落 3：<strong><strong>巢狀雙 strong</strong></strong>。</p>"
        "<p>屬性保護：<a href='https://example.com/**keep**'>連結</a>。</p>"
        "</body></html>"
    )
    out = tmp_path / "bold_mixed.docx"
    html_to_docx_direct(html, out, lock_file=DEFAULT_LOCK)

    doc_xml = _read_docx_xml(out)

    # ── 條件 1：DOCX 內文不應含 literal ** ──
    assert "**" not in doc_xml, (
        f"DOCX 內文不應含 literal `**`。\n實際片段：\n{doc_xml[:800]}"
    )

    # ── 條件 2：所有粗體 marker 都有對應 bold run ──
    expected_bold_strings = [
        "粗體 b",
        "粗體 strong",
        "雙底線粗體",
        "巢狀雙 strong",
    ]
    for needle in expected_bold_strings:
        assert _has_bold_run(doc_xml, needle), (
            f"『{needle}』 應出現在至少一個帶 <w:b/> 旗標的 run 中。"
        )

    # ── 條件 3：斜體仍 italic（非 bold） ──
    italic_runs = [
        r for r in _runs_containing(doc_xml, "斜體")
        if ("<w:i/>" in r or "<w:i " in r)
    ]
    assert len(italic_runs) >= 1, (
        "<em>斜體</em> 應被轉成 italic run"
    )

    # ── 條件 4：屬性中的 `**` 不被誤轉 ──
    # 連結文字「連結」應在 run 中出現
    assert "連結" in doc_xml, "連結文字應保留"


# ────────────────────────────────────────────────────────────────────
# Test 4（補充）: sanitizer 單元測試 — 確認輸入字串處理正確
# ────────────────────────────────────────────────────────────────────

def test_sanitizer_handles_basic_markdown_bold():
    """_sanitize_markdown_emphasis 應正確處理基本 Markdown 粗體 / 斜體。"""
    cases = [
        # (input, expected_substring_check)
        ("**粗體**", "<strong>粗體</strong>"),
        ("__底線__", "<strong>底線</strong>"),
        ("*斜體*", "<em>斜體</em>"),
        ("_底線斜_", "<em>底線斜</em>"),
        ("前 **中** 後", "前 <strong>中</strong> 後"),
        ("empty **  **", "empty **  **"),  # 空白內部不轉
        ("attr-only <a href=\"**keep**\">x</a>", "<a href=\"**keep**\">"),  # 屬性保護
    ]
    for src, must_contain in cases:
        out = _sanitize_markdown_emphasis(src)
        assert must_contain in out, (
            f"sanitize({src!r}) 應含 {must_contain!r}，實際：{out!r}"
        )


def test_sanitizer_idempotent_on_clean_html():
    """已含 <strong> 的 HTML 經 sanitizer 應保持不變（idempotent）。"""
    clean = "<html><body><p><strong>已粗體</strong></p></body></html>"
    out = _sanitize_markdown_emphasis(clean)
    # No stray ** or __ or *italic* syntax in this clean HTML.
    assert "**" not in out, f"clean HTML 不應產生 `**`，實際：{out!r}"
    assert "<strong>已粗體</strong>" in out


# ────────────────────────────────────────────────────────────────────
# Test 5（補充）: examples/output_1 既有 DOCX 不含 literal **
# ────────────────────────────────────────────────────────────────────

def test_existing_output_docx_no_literal_double_star():
    """examples/output_1/report_final.docx 內文不應含 literal `**` 殘留
    （回歸保護：之前可能因 upstream LLM 注入而存在）。
    """
    docx_path = PROJECT_ROOT / "examples" / "output_1" / "report_final.docx"
    if not docx_path.exists():
        pytest.skip(f"範例 DOCX 不存在：{docx_path}")
    doc_xml = _read_docx_xml(docx_path)
    assert "**" not in doc_xml, (
        f"既有 examples/output_1/report_final.docx 內文不應含 literal `**`。"
        f"\n實際片段（前 800 字）：\n{doc_xml[:800]}"
    )
