"""tests/test_delta_checker.py — scripts/delta_checker.py 單元測試。

DoD 對應 `tasks.md` T3-9：
1. 字體差異 → BLOCKING（passed=False）
2. 章節結構差異 → warning
3. metadata 差異 → info
4. 無變化 → pass（passed=True, summary 全 0）

設計：4 個必要 cases + 4 個補充 cases（覆蓋率強化）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.delta_checker import (
    BLOCKING,
    INFO,
    WARNING,
    DeltaReport,
    LockDeltaReport,
    LockDiffEntry,
    SectionDiff,
    check_lock,
    delta_html,
    write_delta_report,
)


# ─── Fixtures ────────────────────────────────────────────────────────

def _ok_lock() -> dict:
    """一個完整、合規的 lock（17 個 required 欄位齊備）。"""
    return {
        "schema_version": 1,
        "fonts": {
            "cjk": "標楷體",
            "latin": "Times New Roman",
        },
        "formatting": {
            "cover": {"font_size": 22, "bold": True, "align": "center"},
            "toc": {"font_size": 20},
            "title": {"font_size": 22, "bold": True, "align": "center"},
            "h1": {"font_size": 18, "bold": True},
            "h2": {"font_size": 16, "bold": True},
            "h3": {"font_size": 14, "bold": True},
            "body": {"font_size": 12, "line_spacing": 1.5},
            "table": {"font_size": 12},
            "caption": {"font_size": 10, "align": "center"},
        },
        "page_size": "A4",
        "margins": {"top": "2.5cm", "bottom": "2.5cm", "left": "3cm", "right": "2cm"},
        "line_spacing": 1.5,
        "language_variant": "zh-TW",
        "citation_style": "APA",
        "output": {"docx_engine": "pandoc", "embed_fonts": True},
        "metadata": {"title": "範例", "author": "Zero", "date": "2026-06-13"},
    }


# ─── Test 1（必要）：字體差異 → BLOCKING（passed=False）──────────────

def test_font_change_is_blocking():
    """fonts.cjk 從 標楷體 改成其他中文字體 → BLOCKING，passed=False。"""
    old = _ok_lock()
    new = _ok_lock()
    new["fonts"]["cjk"] = "微軟正黑體"

    r = check_lock(old, new)

    assert r.passed is False, "字體變動必須 BLOCKING"
    assert r.summary[BLOCKING] == 1
    blocking_entries = [e for e in r.entries if e.severity == BLOCKING]
    assert len(blocking_entries) == 1
    e = blocking_entries[0]
    assert e.key == "fonts.cjk"
    assert e.old_value == "標楷體"
    assert e.new_value == "微軟正黑體"
    assert "字體固定不可覆寫" in e.reason


def test_latin_font_change_is_blocking():
    """fonts.latin 從 Times New Roman 改成 Calibri → BLOCKING。"""
    old = _ok_lock()
    new = _ok_lock()
    new["fonts"]["latin"] = "Calibri"

    r = check_lock(old, new)

    assert r.passed is False
    assert any(e.key == "fonts.latin" and e.severity == BLOCKING for e in r.entries)


# ─── Test 2（必要）：章節結構差異 → warning ───────────────────────────

def test_formatting_change_is_warning():
    """formatting.h1.font_size 改變 → warning（passed 仍 True）。"""
    old = _ok_lock()
    new = _ok_lock()
    new["formatting"]["h1"] = {"font_size": 20, "bold": True}

    r = check_lock(old, new)

    assert r.passed is True, "warning 不應該讓 passed=False"
    assert r.summary[WARNING] >= 1
    warning_entries = [e for e in r.entries if e.severity == WARNING]
    assert any(e.key.startswith("formatting.h1") for e in warning_entries)


def test_margins_change_is_warning():
    """margins 變動 → warning。"""
    old = _ok_lock()
    new = _ok_lock()
    new["margins"]["top"] = "3cm"

    r = check_lock(old, new)

    assert r.passed is True
    assert any(e.key == "margins.top" and e.severity == WARNING for e in r.entries)


# ─── Test 3（必要）：metadata 差異 → info ─────────────────────────────

def test_metadata_change_is_info():
    """metadata.title 改變 → info（passed True, summary['info']=1）。"""
    old = _ok_lock()
    new = _ok_lock()
    new["metadata"]["title"] = "新標題"

    r = check_lock(old, new)

    assert r.passed is True
    assert r.summary[INFO] >= 1
    info_entries = [e for e in r.entries if e.severity == INFO]
    assert any(e.key == "metadata.title" for e in info_entries)


# ─── Test 4（必要）：無變化 → pass（summary 全 0）─────────────────────

def test_no_change_passes():
    """old == new → passed=True, summary 全 0, entries 空。"""
    lock = _ok_lock()
    r = check_lock(lock, lock)

    assert r.passed is True
    assert r.summary == {BLOCKING: 0, WARNING: 0, INFO: 0}
    assert r.entries == []


# ─── 補充 tests：覆蓋率強化 ──────────────────────────────────────────

def test_multiple_severities_combined():
    """同時改字體 + formatting + metadata → BLOCKING + warning + info。"""
    old = _ok_lock()
    new = _ok_lock()
    new["fonts"]["cjk"] = "新細明體"          # BLOCKING
    new["formatting"]["body"]["font_size"] = 14  # warning
    new["metadata"]["author"] = "Someone"        # info

    r = check_lock(old, new)

    assert r.passed is False
    assert r.summary[BLOCKING] >= 1
    assert r.summary[WARNING] >= 1
    assert r.summary[INFO] >= 1


def test_page_size_change_is_blocking():
    """page_size 變動 → BLOCKING（影響排版重算）。"""
    old = _ok_lock()
    new = _ok_lock()
    new["page_size"] = "Letter"

    r = check_lock(old, new)
    assert r.passed is False
    assert any(e.key == "page_size" and e.severity == BLOCKING for e in r.entries)


def test_docx_engine_change_is_blocking():
    """output.docx_engine 變動 → BLOCKING。"""
    old = _ok_lock()
    new = _ok_lock()
    new["output"]["docx_engine"] = "python-docx"

    r = check_lock(old, new)
    assert r.passed is False
    assert any(e.key == "output.docx_engine" and e.severity == BLOCKING for e in r.entries)


def test_write_delta_report_creates_markdown(tmp_path):
    """write_delta_report 產出 markdown 報告。"""
    old = _ok_lock()
    new = _ok_lock()
    new["metadata"]["title"] = "新標題"
    report = check_lock(old, new)

    out = tmp_path / "delta.md"
    write_delta_report(report, out)

    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "# Delta Report" in content
    assert "metadata.title" in content
    assert "info" in content.lower()


def test_lock_delta_report_to_dict_is_jsonable():
    """LockDeltaReport.to_dict() 應可被 json.dumps 序列化。"""
    old = _ok_lock()
    new = _ok_lock()
    new["metadata"]["title"] = "X"
    r = check_lock(old, new)

    d = r.to_dict()
    s = json.dumps(d, ensure_ascii=False)
    assert "metadata.title" in s


def test_existing_delta_html_still_works():
    """回歸測試：原本的 delta_html 仍可用（不會被 lock 邏輯破壞）。

    確認對大幅不同的內容，能產出 DeltaReport 且有 modified section + unified_diff。
    """
    html_old = (
        "<html><body>"
        "<h1 id='a'>Chapter A</h1>"
        "<p>The quick brown fox jumps over the lazy dog in the morning sunlight.</p>"
        "</body></html>"
    )
    html_new = (
        "<html><body>"
        "<h1 id='a'>Chapter A</h1>"
        "<p>An entirely different sentence with completely unrelated words and content.</p>"
        "</body></html>"
    )

    r = delta_html(html_old, html_new, similarity_threshold=0.7)

    assert isinstance(r, DeltaReport)
    assert r.summary["modified"] >= 1, f"應至少有 1 個 modified section: {r.summary}"
    # 找到 modified section，unified_diff 應有內容
    mod = [s for s in r.sections if s.status == "modified"]
    assert len(mod) >= 1
    assert mod[0].unified_diff is not None


def test_lock_diff_entry_dataclass_shape():
    """LockDiffEntry 結構正確。"""
    e = LockDiffEntry(
        key="fonts.cjk",
        old_value="標楷體",
        new_value="微軟正黑體",
        severity=BLOCKING,
        reason="test",
    )
    d = e.to_dict()
    assert d["key"] == "fonts.cjk"
    assert d["severity"] == BLOCKING
