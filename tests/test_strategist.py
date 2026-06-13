r"""tests/test_strategist.py — scripts/strategist.py + references/strategist.md 單元測試。

DoD 對應 `tasks.md` T3-1：
- 載入 references/strategist.md frontmatter 不 crash
- 10 個 questions 都在 strategist.md 內（regex 找 ## Q\d+）
- 範本 academic 產出的 lock 通過 validate_lock()
- 故意缺 1 個 required 欄位時 validate_lock() raise（或 StrategistIncompleteError）

設計：4 個 pytest cases（必要）+ 6 個補充 cases（強化覆蓋率）
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from scripts.report_lock import (
    REQUIRED_FIELDS,
    LockMissingFieldsError,
    validate_lock,
)
from scripts.strategist import (
    CONFIRMATION_QUESTIONS,
    SUPPORTED_TEMPLATES,
    StrategistError,
    StrategistIncompleteError,
    build_lock_template,
    build_report_spec,
    list_confirmations,
)


# ─── Fixtures ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRATEGIST_MD = PROJECT_ROOT / "references" / "strategist.md"


# ─── Test 1（必要）: 載入 references/strategist.md frontmatter 不 crash ─

def test_strategist_md_frontmatter_loads():
    """載入 references/strategist.md frontmatter 不 crash + 必要欄位齊備。"""
    content = STRATEGIST_MD.read_text(encoding="utf-8")
    assert content.startswith("---\n"), "strategist.md 應以 frontmatter 開頭"

    # 用正則抓 frontmatter
    m = re.match(r"\A---\s*\n(?P<yaml>.*?)\n---", content, re.DOTALL)
    assert m is not None, "frontmatter 區塊未正確閉合"

    fm = yaml.safe_load(m.group("yaml"))
    assert isinstance(fm, dict), "frontmatter 應為 mapping"

    # 必要欄位
    assert fm.get("name") == "strategist", "name 應為 'strategist'"
    assert fm.get("description"), "description 必填"
    assert len(fm.get("description", "")) >= 50, "description 太短"
    assert fm.get("version"), "version 必填"


# ─── Test 2（必要）: 10 個 questions 都在 strategist.md 內 ─────────────

def test_strategist_md_contains_10_questions():
    """references/strategist.md 內含 10 個 Q1~Q10 標題（regex `## Q\\d+`）。"""
    content = STRATEGIST_MD.read_text(encoding="utf-8")

    # 用 regex 找所有 ## Q\d+ 或 ### Q\d+ 標題（markdown H2/H3 皆可）
    pattern = re.compile(r"^#{2,3}\s+Q(\d+)\s*[\u2014\-\u2013:]?\s*", re.MULTILINE)
    matches = pattern.findall(content)
    question_numbers = sorted({int(m) for m in matches})

    # 至少 Q1 ~ Q10 都在
    expected = list(range(1, 11))
    assert question_numbers == expected, (
        f"strategist.md 應含 Q1~Q10 標題；找到：{question_numbers}，"
        f"缺：{set(expected) - set(question_numbers)}"
    )

    # 額外檢查：CONFIRMATION_QUESTIONS 與 markdown 對齊
    md_q_ids = {f"Q{n}" for n in question_numbers}
    py_q_ids = {q["id"] for q in CONFIRMATION_QUESTIONS}
    assert md_q_ids == py_q_ids, (
        f"Python CONFIRMATION_QUESTIONS 與 markdown Q 編號不一致："
        f"markdown={md_q_ids}, python={py_q_ids}"
    )


# ─── Test 3（必要）: 範本 academic 產出的 lock 通過 validate_lock() ───

def test_academic_template_passes_validate_lock():
    """範本 academic 產出的 lock 必須通過 validate_lock()（17 欄位齊備）。"""
    lock = build_lock_template("academic")

    # 結構檢查
    assert isinstance(lock, dict)
    assert lock["template"] == "academic"

    # 17 個 required 欄位都應可從 dot-key 取到
    for field in REQUIRED_FIELDS:
        parts = field.split(".")
        cur: Any = lock
        for p in parts:
            assert isinstance(cur, dict), f"{field} 路徑中斷"
            cur = cur.get(p)
        assert cur is not None, f"required 欄位 {field} 缺失"

    # 跑 validate_lock（不應 raise）
    validate_lock(lock)


# ─── Test 4（必要）: 故意缺 1 個 required 欄位時 raise ───────────────

def test_missing_required_field_raises():
    """故意缺 1 個 required 欄位時，validate_lock() 應 raise LockMissingFieldsError
    或 StrategistIncompleteError（前者為主，後者為 Strategist 層語意錯誤）。
    """
    # 從完整 academic lock 抽掉 citation_style
    lock = build_lock_template("academic")
    del lock["citation_style"]

    with pytest.raises((LockMissingFieldsError, StrategistIncompleteError)) as exc_info:
        validate_lock(lock)

    # 確認錯誤訊息有列出缺失欄位
    err_msg = str(exc_info.value)
    assert "citation_style" in err_msg or "BLOCKING" in err_msg

    # 另一個測試：故意缺字體
    lock2 = build_lock_template("academic")
    lock2["fonts"] = {"cjk": "標楷體"}  # 缺 latin
    with pytest.raises((LockMissingFieldsError, StrategistIncompleteError)):
        validate_lock(lock2)


# ─── Test 5（補充）: 5 種範本都產出合法 lock ────────────────────────

@pytest.mark.parametrize("template", SUPPORTED_TEMPLATES)
def test_all_templates_produce_valid_lock(template: str):
    """5 種範本（academic / business / spec / gov / custom）都應產出合法 lock。"""
    lock = build_lock_template(template)
    assert lock["template"] == template
    validate_lock(lock)  # 不應 raise


# ─── Test 6（補充）: sections 預設 ≥ 3 個 ────────────────────────────

@pytest.mark.parametrize("template", SUPPORTED_TEMPLATES)
def test_templates_have_at_least_3_sections(template: str):
    """每個範本的預設 sections 應 ≥ 3 個（Q6 BLOCKING 條件）。"""
    lock = build_lock_template(template)
    sections = lock.get("sections", [])
    assert len(sections) >= 3, (
        f"{template} 範本 sections={len(sections)}，應 ≥ 3"
    )
    for sec in sections:
        assert "path" in sec and "title" in sec, f"section 缺 path/title: {sec}"
        assert sec["title"], f"section title 為空: {sec}"


# ─── Test 7（補充）: 字體鎖死（CJK=標楷體, Latin=Times New Roman） ───

@pytest.mark.parametrize("template", SUPPORTED_TEMPLATES)
def test_templates_have_locked_fonts(template: str):
    """所有範本的 fonts.cjk=標楷體、fonts.latin=Times New Roman（不可覆寫）。"""
    lock = build_lock_template(template)
    assert lock["fonts"]["cjk"] == "標楷體", f"{template}: CJK 字體被改"
    assert lock["fonts"]["latin"] == "Times New Roman", f"{template}: Latin 字體被改"


# ─── Test 8（補充）: metadata overrides 生效 ────────────────────────

def test_metadata_overrides():
    """metadata_overrides 應正確套用到 title / author / date。"""
    lock = build_lock_template(
        "academic",
        metadata_overrides={
            "title": "我的研究論文",
            "author": "測試者",
            "date": "2026-06-13",
        },
    )
    assert lock["metadata"]["title"] == "我的研究論文"
    assert lock["metadata"]["author"] == "測試者"
    assert lock["metadata"]["date"] == "2026-06-13"


# ─── Test 9（補充）: 不支援的範本應 raise ───────────────────────────

def test_unsupported_template_raises():
    """不支援的範本名應 raise StrategistError。"""
    with pytest.raises(StrategistError):
        build_lock_template("unknown-type")


# ─── Test 10（補充）: build_report_spec 產出 Markdown ────────────────

def test_build_report_spec_produces_markdown():
    """build_report_spec 應產出含章節大綱的 Markdown。"""
    spec = build_report_spec("academic", title="測試報告")
    assert "# report_spec.md" in spec
    assert "測試報告" in spec
    assert "章節大綱" in spec
    assert "引用" in spec or "引用 / 參考文獻" in spec
    # 至少 3 個章節列點
    lines = spec.split("\n")
    section_lines = [ln for ln in lines if re.match(r"^\d+\.\s+\*\*", ln)]
    assert len(section_lines) >= 3, f"章節 < 3：{section_lines}"


# ─── Test 11（補充）: list_confirmations 與 Python 定義一致 ─────────

def test_list_confirmations_consistency():
    """list_confirmations() 回傳的 Q1~Q10 與 CONFIRMATION_QUESTIONS 一致。"""
    qs = list_confirmations()
    assert len(qs) == 10
    ids = [q["id"] for q in qs]
    assert ids == [f"Q{i}" for i in range(1, 11)]
    for q in qs:
        assert "key" in q and "text" in q
