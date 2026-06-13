"""tests/test_executor.py — scripts/executor.py + references/executor-base.md 單元測試。

DoD 對應 `tasks.md` T3-2：
- 載入 references/executor-base.md frontmatter 不 crash
- 流程圖 / step 清單都在 executor.md 內（regex 找 `### Step` 或 `## 流程`）
- Executor class（或同名）能 init 並接受 lock path
- 故意給缺 1 個 required 欄位的 lock 時，Executor 拒絕啟動（raise）

設計：4 個必要 cases + 6 個補充 cases（覆蓋率強化）
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from scripts.executor import (
    Executor,
    ExecutorAbort,
    ExecutorError,
    ExecutorSectionError,
    SectionResult,
    _chapter_number_zh,
    _default_section_stub_html,
)
from scripts.quality_checker import check_html
from scripts.report_lock import (
    LockMissingFieldsError,
    REQUIRED_FIELDS,
    read_and_validate,
    read_lock,
    write_lock,
)
from scripts.strategist import build_lock_template


# ─── Fixtures ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXECUTOR_MD = PROJECT_ROOT / "references" / "executor-base.md"


@pytest.fixture
def tmp_project():
    """產生一個 tmp dir，內含合法 academic lock + 必要 stub 檔。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        lock = build_lock_template("academic", metadata_overrides={"title": "T3-2 Test"})
        # 限制到 3 個 section（task 描述的需求）
        lock["sections"] = lock["sections"][:3]
        lock_path = tmp_path / "report_lock.md"
        write_lock(lock_path, lock, body="# test lock\n")
        yield tmp_path


# ─── Test 1（必要）: 載入 references/executor-base.md frontmatter 不 crash ─

def test_executor_md_frontmatter_loads():
    """載入 references/executor-base.md frontmatter 不 crash + 必要欄位齊備。"""
    content = EXECUTOR_MD.read_text(encoding="utf-8")
    assert content.startswith("---\n"), "executor-base.md 應以 frontmatter 開頭"

    m = re.match(r"\A---\s*\n(?P<yaml>.*?)\n---", content, re.DOTALL)
    assert m is not None, "frontmatter 區塊未正確閉合"

    fm = yaml.safe_load(m.group("yaml"))
    assert isinstance(fm, dict), "frontmatter 應為 mapping"

    # 必要欄位
    assert fm.get("name") == "executor", "name 應為 'executor'"
    assert fm.get("description"), "description 必填"
    assert len(fm.get("description", "")) >= 50, "description 太短"
    assert str(fm.get("version")) in ("1.0", "1.1"), "version 應為 1.0 或 1.1"


# ─── Test 2（必要）: 流程圖 / step 清單都在 executor.md 內 ─────────────

def test_executor_md_has_flowchart_and_steps():
    """references/executor-base.md 內含 Mermaid 流程圖 + Step 清單。"""
    content = EXECUTOR_MD.read_text(encoding="utf-8")

    # Mermaid 區塊
    assert "```mermaid" in content, "executor.md 應含 Mermaid 流程圖"
    assert "flowchart" in content, "Mermaid 圖應為 flowchart 類型"

    # Step 標題（### Step N 或中文 Step 數字）
    # 對應 references §3.2 7-step 流程
    step_patterns = [
        r"###\s*3\.2",  # §3.2 Step 1: 載入 lock + spec + glossary
        r"###\s*3\.3",  # §3.3 Step 2
        r"###\s*3\.4",  # §3.4 Step 3
        r"###\s*3\.5",  # §3.5 Step 4
        r"###\s*3\.6",  # §3.6 Step 5
        r"###\s*3\.7",  # §3.7 Step 6
        r"###\s*3\.8",  # §3.8 Step 7
    ]
    found = sum(1 for p in step_patterns if re.search(p, content))
    assert found >= 5, f"executor.md 應含 ≥ 5 個 Step 段落；找到 {found}"

    # 額外：流程節標題（## 3. 逐節流程）
    assert re.search(r"^##\s*\d+\.\s*逐節流程", content, re.MULTILINE), (
        "應有「## N. 逐節流程」主章節"
    )


# ─── Test 3（必要）: Executor class 能 init 並接受 lock path ─────────

def test_executor_class_init_accepts_lock_path(tmp_project):
    """Executor(lock_path) 應成功 init 並讀取 lock。"""
    lock_path = tmp_project / "report_lock.md"
    exe = Executor(lock_path, output_dir=tmp_project / "report_output")
    assert exe.lock_path == lock_path
    assert exe.lock_data is not None
    assert "sections" in exe.lock_data
    assert len(exe.lock_data["sections"]) == 3  # fixture 限制到 3


# ─── Test 4（必要）: 缺 required 欄位時 Executor 拒絕啟動（raise） ────

def test_executor_rejects_lock_with_missing_required_field():
    """故意缺 1 個 required 欄位時，Executor(...) 應 raise LockMissingFieldsError。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        lock = build_lock_template("academic")
        # 故意缺 citation_style
        del lock["citation_style"]
        bad_lock = tmp_path / "bad_lock.md"
        write_lock(bad_lock, lock, body="# bad\n")

        with pytest.raises(LockMissingFieldsError) as exc_info:
            Executor(bad_lock)
        # 確認錯誤訊息有列出缺失欄位
        err_msg = str(exc_info.value)
        assert "citation_style" in err_msg

        # 另一個情境：lock 檔不存在 → ExecutorAbort
        with pytest.raises((ExecutorAbort, FileNotFoundError)):
            Executor(tmp_path / "nonexistent.md")


# ─── Test 5（補充）: 預設 stub HTML 通過 quality_checker ─────────────

def test_stub_html_passes_quality_gate():
    """_default_section_stub_html() 產出應通過 quality_checker。"""
    html = _default_section_stub_html(
        section_index=1,
        section_title="第一章 緒論",
        body_font_size=12,
        line_spacing=1.5,
    )
    # 不應 raise
    check_html(html, source="stub_1.html")

    # 多節都應通過
    for n in (2, 3, 5):
        h = _default_section_stub_html(
            section_index=n,
            section_title=f"第{_chapter_number_zh(n)}章 測試",
        )
        check_html(h, source=f"stub_{n}.html")


# ─── Test 6（補充）: 完整 pipeline 跑通（3 sections） ───────────────

def test_full_pipeline_3_sections(tmp_project):
    """Executor.run() 對 3 個 section 的 lock 跑完整 pipeline，應全部 PASS。"""
    lock_path = tmp_project / "report_lock.md"
    out_dir = tmp_project / "report_output"
    exe = Executor(lock_path, output_dir=out_dir)
    result = exe.run()

    assert result.passed, f"pipeline 應通過；errors={result.errors}"
    assert result.completed_sections == [1, 2, 3]
    assert len(result.section_results) == 3

    # 每節 HTML 應存在
    for n in (1, 2, 3):
        sec_html = out_dir / f"section_{n}.html"
        assert sec_html.exists(), f"section_{n}.html 應存在"
        # 內容應含 <!DOCTYPE html> 與章節編號
        text = sec_html.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in text
        assert "<h1>" in text
        assert f"第{_chapter_number_zh(n)}章" in text

    # progress 應寫入 lock
    persisted = read_lock(lock_path)
    progress = persisted["metadata"].get("progress", {})
    assert progress.get("status") == "completed"
    assert progress.get("completed_sections") == [1, 2, 3]


# ─── Test 7（補充）: 自動接續（auto-resume）──────────────────────

def test_auto_resume_from_progress(tmp_project):
    """若 lock 已有 progress.current_section=2，重啟時應從 section 3 接續。"""
    lock_path = tmp_project / "report_lock.md"
    out_dir = tmp_project / "report_output"

    # 注入 progress
    lock = read_lock(lock_path)
    lock["metadata"]["progress"] = {
        "current_section": 2,
        "total_sections": 3,
        "completed_sections": [1, 2],
        "status": "in_progress",
    }
    write_lock(lock_path, lock, body="# resume test\n")

    exe = Executor(lock_path, output_dir=out_dir)
    result = exe.run()
    assert result.passed
    # 應只跑 section 3（接續）
    assert result.completed_sections == [3]
    assert (out_dir / "section_3.html").exists()
    # section 1 / 2 不應重新生成（這次跑只生成 3）


# ─── Test 8（補充）: --section 跑單節 ──────────────────────────────

def test_run_section_single(tmp_project):
    """Executor.run_section(n) 跑單節，應正確生成該節 HTML。"""
    lock_path = tmp_project / "report_lock.md"
    out_dir = tmp_project / "report_output"
    exe = Executor(lock_path, output_dir=out_dir)
    sec_result = exe.run_section(2)

    assert isinstance(sec_result, SectionResult)
    assert sec_result.section_index == 2
    assert sec_result.quality_passed is True
    assert sec_result.html_path.endswith("section_2.html")
    assert sec_result.bytes > 100

    # 檔案實際存在
    out = Path(sec_result.html_path)
    assert out.exists()


# ─── Test 9（補充）: restart 從頭覆蓋 ──────────────────────────────

def test_restart_overrides_progress(tmp_project):
    """restart=True 時應忽略 progress，從 section 1 重跑。"""
    lock_path = tmp_project / "report_lock.md"
    out_dir = tmp_project / "report_output"

    # 注入 progress（已標記 completed）
    lock = read_lock(lock_path)
    lock["metadata"]["progress"] = {
        "current_section": 3,
        "total_sections": 3,
        "completed_sections": [1, 2, 3],
        "status": "completed",
    }
    write_lock(lock_path, lock, body="# restart test\n")

    exe = Executor(lock_path, output_dir=out_dir)
    result = exe.run(restart=True)
    assert result.passed
    # restart 從頭：應跑 1, 2, 3 全套
    assert result.completed_sections == [1, 2, 3]


# ─── Test 10（補充）: 章節中文編號 ───────────────────────────────

@pytest.mark.parametrize("n,expected", [
    (1, "一"), (2, "二"), (3, "三"), (10, "十"),
    (11, "十一"), (15, "十五"), (20, "二十"),
])
def test_chapter_number_zh(n, expected):
    """_chapter_number_zh 對 1~20 應正確轉中文。"""
    assert _chapter_number_zh(n) == expected


# ─── Test 11（補充）: lock 缺 fields 各種情境 ─────────────────────

@pytest.mark.parametrize("missing", [
    "fonts.cjk", "fonts.latin", "formatting.h1",
    "page_size", "citation_style", "output.docx_engine",
])
def test_executor_rejects_various_missing_fields(missing):
    """缺任何 required 欄位都應 raise LockMissingFieldsError。"""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        lock = build_lock_template("academic")
        # 移除指定欄位
        parts = missing.split(".")
        if len(parts) == 1:
            lock.pop(parts[0], None)
        elif len(parts) == 2:
            lock[parts[0]].pop(parts[1], None)
        bad = tmp_path / "bad.md"
        write_lock(bad, lock, body="# bad\n")
        with pytest.raises(LockMissingFieldsError):
            Executor(bad)
