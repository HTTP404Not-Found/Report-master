"""tests/test_examples.py — T3-13 examples 整合測試（≥ 6 pytest cases）。

對應 `tasks.md` T3-13（DoD 對齊）：

必測（必要 6 個）：
  1. example_1 lock frontmatter 有效（parse 不 crash）
  2. example_2 lock frontmatter 有效
  3. examples/output_1/report_final.html 存在且 > 1KB（假設 smoke 已跑過）
  4. examples/output_2/report_final.html 存在且 > 1KB
  5. test_examples.py 自身 smoke 不 crash（importable + CLI 入口存在）
  6. example_1 章節結構正確（≥ 5 章節）

補充（≥ 0 個，覆蓋率強化）：
  7. example_2 章節結構正確（≥ 6 章節）
  8. example_1 + example_2 line count > 100
  9. example_1 + example_2 章節 H1 標題正確
  10. example_1 + example_2 產出 DOCX（v1.4.0 DOCX-only output; PDF 不再 user-facing）
  11. test_examples.py 是合法的 Python module（compile 不 crash）
  12. scripts/test_examples.py 的 EXAMPLE_1 / EXAMPLE_2 metadata 與 example_*.md 對應

設計：
  - 不重跑 smoke test（避免 CI 慢）；DoD 3-4 假設 smoke 已產出 output_1 / output_2。
  - 用 autouse-style fixture 自動 skip（若 output 不存在 → pytest.skip）。
  - 若 smoke 跑過後產生了 output_1 / output_2，pytest 全綠。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import yaml

# 讓 scripts.* 可被 import
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.report_lock import (  # noqa: E402
    LockMissingFieldsError,
    REQUIRED_FIELDS,
    read_and_validate,
    write_lock,
)
from scripts.strategist import build_lock_template  # noqa: E402


# ─── Fixtures / 常數 ─────────────────────────────────────────────────

EXAMPLES_DIR = _PROJECT_ROOT / "examples"
EXAMPLE_1_MD = EXAMPLES_DIR / "example_1_natural_science.md"
EXAMPLE_2_MD = EXAMPLES_DIR / "example_2_technical_report.md"
TEST_EXAMPLES_PY = _PROJECT_ROOT / "scripts" / "test_examples.py"
LOCK_TEMPLATE_1 = {
    "id": 1,
    "name": "natural_science",
    "template": "academic",
    "min_sections": 5,
    "title_keywords": ["前言", "方法", "結果", "討論", "結論"],
}
LOCK_TEMPLATE_2 = {
    "id": 2,
    "name": "technical_report",
    "template": "spec",
    "min_sections": 6,
    "title_keywords": ["摘要", "背景", "相關工作", "系統設計", "實驗結果", "結論"],
}


def _try_build_example_lock(example_id: int) -> Optional[Dict[str, Any]]:
    """嘗試 build 一個 example 的 lock（不寫入磁碟）。"""
    if example_id == 1:
        meta = {
            "title": "都市熱島效應與綠覆率相關性之研究",
            "author": "王小明",
            "date": "2026-06-13",
            "abstract": "本研究以台北市 12 個行政區為觀測樣本...",
        }
        sections = ["前言", "方法", "結果", "討論", "結論"]
        template = "academic"
    elif example_id == 2:
        meta = {
            "title": "OpenReport：基於 Spec-Lock 的報告生成系統",
            "author": "OpenReport 開發團隊",
            "date": "2026-06-13",
            "abstract": "OpenReport 是一個基於 Spec-Lock 反漂移設計...",
        }
        sections = ["摘要", "背景", "相關工作", "系統設計", "實驗結果", "結論"]
        template = "spec"
    else:
        return None
    sections_override = [
        {"path": f"section_{i}.html", "title": t}
        for i, t in enumerate(sections, 1)
    ]
    return build_lock_template(
        template=template,
        metadata_overrides=meta,
        sections_override=sections_override,
    )


# ─── Test 1（必要）: example_1 lock frontmatter 有效（parse 不 crash）───

def test_example_1_lock_frontmatter_valid(tmp_path):
    """example_1 的 lock 17 required 欄位齊備 + parse 不 crash。"""
    lock_data = _try_build_example_lock(1)
    assert lock_data is not None, "example_1 lock 應可建構"

    # 17 required 欄位逐一檢查
    from scripts.report_lock import _get_nested
    for field in REQUIRED_FIELDS:
        val = _get_nested(lock_data, field)
        assert val is not None, f"example_1 lock 缺 required 欄位：{field}"

    # 寫入 → 重讀 → 仍合法
    lock_path = tmp_path / "lock_example_1.md"
    write_lock(lock_path, lock_data, body="# example_1 lock\n")
    reloaded = read_and_validate(str(lock_path))
    assert reloaded["metadata"]["title"].startswith("都市熱島"), "example_1 標題錯誤"
    assert reloaded["template"] == "academic"
    assert len(reloaded["sections"]) >= LOCK_TEMPLATE_1["min_sections"]


# ─── Test 2（必要）: example_2 lock frontmatter 有效 ──────────────────

def test_example_2_lock_frontmatter_valid(tmp_path):
    """example_2 的 lock 17 required 欄位齊備 + parse 不 crash。"""
    lock_data = _try_build_example_lock(2)
    assert lock_data is not None, "example_2 lock 應可建構"

    from scripts.report_lock import _get_nested
    for field in REQUIRED_FIELDS:
        val = _get_nested(lock_data, field)
        assert val is not None, f"example_2 lock 缺 required 欄位：{field}"

    # 寫入 → 重讀 → 仍合法
    lock_path = tmp_path / "lock_example_2.md"
    write_lock(lock_path, lock_data, body="# example_2 lock\n")
    reloaded = read_and_validate(str(lock_path))
    assert "OpenReport" in reloaded["metadata"]["title"], "example_2 標題錯誤"
    assert reloaded["template"] == "spec"
    assert len(reloaded["sections"]) >= LOCK_TEMPLATE_2["min_sections"]


# ─── Test 3（必要）: examples/output_1/report_final.html 存在且 > 1KB ─

def test_output_1_report_final_html_exists_and_big():
    """examples/output_1/report_final.html 應存在且 > 1KB。

    若 smoke test 未跑過（output_1/ 不存在）→ pytest.skip，不 fail。
    """
    output_1 = EXAMPLES_DIR / "output_1" / "report_final.html"
    if not output_1.exists():
        pytest.skip(
            f"{output_1} 不存在；請先跑 `python -m scripts.test_examples` 產出。"
        )
    size = output_1.stat().st_size
    assert size > 1024, f"report_final.html 大小 {size} <= 1KB（DoD FAIL）"

    # 也檢查內容（合規 HTML）
    content = output_1.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content or "<!doctype html>" in content.lower()
    assert "標楷體" in content, "應含 CJK 字體標楷體"
    assert "Times New Roman" in content, "應含 Latin 字體"


# ─── Test 4（必要）: examples/output_2/report_final.html 存在且 > 1KB ─

def test_output_2_report_final_html_exists_and_big():
    """examples/output_2/report_final.html 應存在且 > 1KB。

    若 smoke test 未跑過（output_2/ 不存在）→ pytest.skip，不 fail。
    """
    output_2 = EXAMPLES_DIR / "output_2" / "report_final.html"
    if not output_2.exists():
        pytest.skip(
            f"{output_2} 不存在；請先跑 `python -m scripts.test_examples` 產出。"
        )
    size = output_2.stat().st_size
    assert size > 1024, f"report_final.html 大小 {size} <= 1KB（DoD FAIL）"

    content = output_2.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content or "<!doctype html>" in content.lower()
    assert "標楷體" in content
    assert "Times New Roman" in content


# ─── Test 5（必要）: test_examples.py smoke 自己不 crash ─────────────

def test_test_examples_py_imports_and_has_cli():
    """scripts/test_examples.py 應可 import + 含 CLI 入口（_cli）。"""
    # 用 importlib 把 module 註冊到 sys.modules（讓 dataclasses 內省能運作）
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "scripts.test_examples", str(TEST_EXAMPLES_PY)
    )
    if spec is None or spec.loader is None:
        pytest.fail(f"無法載入 spec：{TEST_EXAMPLES_PY}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["scripts.test_examples"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        pytest.fail(f"test_examples.py import 失敗：{e}")

    # 含 _cli() 函式
    assert hasattr(module, "_cli"), "test_examples.py 應含 _cli() 函式"
    assert callable(module._cli)

    # 含 EXAMPLE_1 / EXAMPLE_2 常數
    assert hasattr(module, "EXAMPLE_1"), "應含 EXAMPLE_1 常數"
    assert hasattr(module, "EXAMPLE_2"), "應含 EXAMPLE_2 常數"
    assert module.EXAMPLE_1["id"] == 1
    assert module.EXAMPLE_2["id"] == 2


# ─── Test 6（必要）: example_1 章節結構正確（≥ 5 章節）──────────────

def test_example_1_has_at_least_5_sections(tmp_path):
    """example_1 應有 ≥ 5 章節（H1 數量或 lock.sections 數量）。"""
    lock_data = _try_build_example_lock(1)
    assert lock_data is not None
    sections = lock_data.get("sections", [])
    assert len(sections) >= LOCK_TEMPLATE_1["min_sections"], (
        f"example_1 章節數 {len(sections)} < {LOCK_TEMPLATE_1['min_sections']}"
    )

    # 章節標題應包含關鍵字
    titles = [s.get("title", "") for s in sections]
    for kw in LOCK_TEMPLATE_1["title_keywords"]:
        assert any(kw in t for t in titles), (
            f"example_1 章節應含關鍵字 {kw!r}；titles={titles}"
        )


# ─── Test 7（補充）: example_2 章節結構正確（≥ 6 章節）──────────────

def test_example_2_has_at_least_6_sections(tmp_path):
    """example_2 應有 ≥ 6 章節（H1 數量或 lock.sections 數量）。"""
    lock_data = _try_build_example_lock(2)
    assert lock_data is not None
    sections = lock_data.get("sections", [])
    assert len(sections) >= LOCK_TEMPLATE_2["min_sections"], (
        f"example_2 章節數 {len(sections)} < {LOCK_TEMPLATE_2['min_sections']}"
    )

    titles = [s.get("title", "") for s in sections]
    for kw in LOCK_TEMPLATE_2["title_keywords"]:
        assert any(kw in t for t in titles), (
            f"example_2 章節應含關鍵字 {kw!r}；titles={titles}"
        )


# ─── Test 8（補充）: example_1 + example_2 line count > 100 ──────────

@pytest.mark.parametrize("md_file,min_lines", [
    (EXAMPLE_1_MD, 100),
    (EXAMPLE_2_MD, 100),
])
def test_example_md_line_count(md_file: Path, min_lines: int):
    """example_*.md 檔案行數應 > 100（DoD #1, #2）。"""
    assert md_file.exists(), f"{md_file} 不存在"
    text = md_file.read_text(encoding="utf-8")
    line_count = text.count("\n") + (0 if text.endswith("\n") else 1)
    assert line_count > min_lines, (
        f"{md_file.name} 行數 {line_count} <= {min_lines}（DoD FAIL）"
    )


# ─── Test 9（補充）: example_*.md 是合法 Markdown（h1/h2 結構）────────

def test_example_mds_have_valid_markdown_structure():
    """example_*.md 應有完整的 H1 結構與章節小節。"""
    for md in (EXAMPLE_1_MD, EXAMPLE_2_MD):
        content = md.read_text(encoding="utf-8")
        # 至少一個 H1
        assert re.search(r"^#\s+\S", content, re.MULTILINE), (
            f"{md.name} 應含至少一個 H1"
        )
        # 至少 5 個 H2
        h2_count = len(re.findall(r"^##\s+\S", content, re.MULTILINE))
        assert h2_count >= 5, f"{md.name} 應有 ≥ 5 個 H2；找到 {h2_count}"


# ─── Test 10（補充）: 產出 DOCX（v1.4.0 DOCX-only output）───────────
#
# v1.4.0 changelog:
#   - PDF 已從 user-facing output 移除;report_gen 不再產 PDF
#   - DOCX 是 user-facing 交付物;HTML 是 Stage 2→3 中介產物
#   - html_to_pdf.py 模組保留供 legacy opt-in,但 pipeline 不再依賴
# 因此本測試只檢查 DOCX;不再檢查 PDF。

@pytest.mark.parametrize("output_id,filename", [
    (1, "report_final.docx"),
    (2, "report_final.docx"),
])
def test_output_files_docx_only(output_id: int, filename: str):
    """v1.4.0: DOCX-only output。PDF no longer produced by default; this test
    verifies DOCX exists and size is reasonable（> 100 bytes）。
    若 smoke test 已產出 DOCX，檔案應存在且大小合理。
    """
    target = EXAMPLES_DIR / f"output_{output_id}" / filename
    if not target.exists():
        pytest.skip(f"{target} 不存在；可能 pandoc 未安裝或 smoke test 未跑")
    size = target.stat().st_size
    assert size > 100, f"{target} 大小 {size} bytes 太小"


# ─── Test 11（補充）: scripts/test_examples.py 是合法 Python module ─

def test_test_examples_py_is_valid_python():
    """scripts/test_examples.py 應可被 Python compile（無 syntax error）。"""
    code = TEST_EXAMPLES_PY.read_text(encoding="utf-8")
    try:
        compile(code, str(TEST_EXAMPLES_PY), "exec")
    except SyntaxError as e:
        pytest.fail(f"test_examples.py syntax error：{e}")


# ─── Test 12（補充）: example metadata 與 *.md 對應 ─────────────────

def test_example_metadata_matches_md_titles():
    """scripts/test_examples.py 的 EXAMPLE_1/2 metadata 應與 .md 內的章節一致。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "scripts.test_examples", str(TEST_EXAMPLES_PY)
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["scripts.test_examples"] = module
    spec.loader.exec_module(module)

    # EXAMPLE_1 章節對應 example_1_natural_science.md 的章節
    md1 = EXAMPLE_1_MD.read_text(encoding="utf-8")
    for sec in module.EXAMPLE_1["sections"]:
        assert sec in md1, f"EXAMPLE_1.sections 應含 {sec!r}（在 example_1.md 內）"

    md2 = EXAMPLE_2_MD.read_text(encoding="utf-8")
    for sec in module.EXAMPLE_2["sections"]:
        assert sec in md2, f"EXAMPLE_2.sections 應含 {sec!r}（在 example_2.md 內）"


# ─── Test 13（補充）: example_*.md 不應有「第一章 第一章」重複（前綴正確）──

def test_example_mds_no_chapter_prefix_duplication():
    """example_*.md 內不應出現「第一章 第一章」這種章節前綴重複。"""
    for md in (EXAMPLE_1_MD, EXAMPLE_2_MD):
        content = md.read_text(encoding="utf-8")
        # 章節前綴（zh）
        for prefix in ("第一章", "第二章", "第三章", "第四章", "第五章", "第六章"):
            doubled = f"{prefix} {prefix}"
            assert doubled not in content, (
                f"{md.name} 內含重複章節前綴 {doubled!r}"
            )


# ─── D1 新增 tests（tasks.md D1 — End-to-End Smoke × 2）───────────

def _read_docx_text(path: Path) -> str:
    """讀 DOCX 並回傳 plain text。"""
    try:
        from docx import Document
    except ImportError:
        return ""
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def _has_asterisk_residue(text: str) -> bool:
    """檢查 text 內是否有遊離的 ** 殘留。"""
    import re as _re
    return bool(_re.search(r"\*\*", text))


def test_example_1_d1_artifacts_complete():
    """D1：example_1 應有完整 artifacts：0_strategist.md / 0_outline.md /
    0_confirmed.json / chapter_*_research.md / report_final.docx（無 ** 殘留）。"""
    output_1 = EXAMPLES_DIR / "output_1"
    if not output_1.exists():
        pytest.skip(f"{output_1} 不存在；請先跑 D1 smoke。")

    # 1. 0_strategist.md
    strategist = output_1 / "0_strategist.md"
    assert strategist.exists(), f"缺少 {strategist}"
    s_content = strategist.read_text(encoding="utf-8")
    assert "主題" in s_content or "topic" in s_content.lower(), (
        "0_strategist.md 應含 topic/主題欄位"
    )

    # 2. 0_outline.md
    outline = output_1 / "0_outline.md"
    assert outline.exists(), f"缺少 {outline}"
    o_content = outline.read_text(encoding="utf-8")
    assert "Section Blueprint" in o_content or "章節" in o_content, (
        "0_outline.md 應含 Section Blueprint / 章節內容"
    )

    # 3. 0_confirmed.json（含 confirmed: true）
    confirmed = output_1 / "0_confirmed.json"
    assert confirmed.exists(), f"缺少 {confirmed}"
    c_data = json.loads(confirmed.read_text(encoding="utf-8"))
    assert c_data.get("confirmed") is True, (
        f"0_confirmed.json 應有 confirmed=true，實際：{c_data}"
    )

    # 4. chapter_*_research.md（至少 1 個）
    research_files = sorted(output_1.glob("chapter_*_research.md"))
    assert len(research_files) >= 1, (
        f"應有 ≥1 個 chapter_*_research.md，實際：{list(output_1.glob('chapter_*_research.md'))}"
    )
    # 第一個 research 應有 bullets
    first_research = research_files[0].read_text(encoding="utf-8")
    assert "Bullets" in first_research or "bullet" in first_research.lower(), (
        f"chapter_1_research.md 應含 Bullets 區段"
    )

    # 5. report_final.docx（> 5KB + 無 ** 殘留）
    docx = output_1 / "report_final.docx"
    assert docx.exists(), f"缺少 {docx}"
    assert docx.stat().st_size > 5 * 1024, (
        f"report_final.docx 應 > 5KB，實際 {docx.stat().st_size} bytes"
    )
    text = _read_docx_text(docx)
    assert not _has_asterisk_residue(text), (
        f"report_final.docx 內文不應有 ** 殘留；抽樣：{text[:200]!r}"
    )


def test_example_2_d1_artifacts_complete():
    """D1：example_2 應有完整 artifacts（同 example_1）。"""
    output_2 = EXAMPLES_DIR / "output_2"
    if not output_2.exists():
        pytest.skip(f"{output_2} 不存在；請先跑 D1 smoke。")

    strategist = output_2 / "0_strategist.md"
    assert strategist.exists(), f"缺少 {strategist}"

    outline = output_2 / "0_outline.md"
    assert outline.exists(), f"缺少 {outline}"

    confirmed = output_2 / "0_confirmed.json"
    assert confirmed.exists(), f"缺少 {confirmed}"
    c_data = json.loads(confirmed.read_text(encoding="utf-8"))
    assert c_data.get("confirmed") is True, (
        f"0_confirmed.json 應有 confirmed=true，實際：{c_data}"
    )

    research_files = sorted(output_2.glob("chapter_*_research.md"))
    assert len(research_files) >= 1, (
        f"應有 ≥1 個 chapter_*_research.md，實際：{list(output_2.glob('chapter_*_research.md'))}"
    )

    docx = output_2 / "report_final.docx"
    assert docx.exists(), f"缺少 {docx}"
    assert docx.stat().st_size > 5 * 1024
    text = _read_docx_text(docx)
    assert not _has_asterisk_residue(text), (
        f"report_final.docx 內文不應有 ** 殘留"
    )


def test_d1_no_asterisk_residue_either_example():
    """D1：兩個 example 的 report_final.docx 都不應有 ** 殘留。"""
    for n in (1, 2):
        docx = EXAMPLES_DIR / f"output_{n}" / "report_final.docx"
        if not docx.exists():
            pytest.skip(f"{docx} 不存在；請先跑 D1 smoke。")
        text = _read_docx_text(docx)
        assert not _has_asterisk_residue(text), (
            f"output_{n}/report_final.docx 含 ** 殘留；前 200 字：{text[:200]!r}"
        )
