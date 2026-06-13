"""tests/test_resume_helper.py — scripts/resume_helper.py + workflows/resume-execute.md 測試。

DoD 對應 `tasks.md` T3-5：
1. 載入 `workflows/resume-execute.md` frontmatter 不 crash
2. Mermaid flowchart 存在（regex ` ```mermaid `）
3. `resume_helper.py` CLI `--lock <path> --dry-run` 不 crash
4. (補充) ResumeHelper gap analysis：模擬 2 節完成 + 2 節缺
5. (補充) ResumeHelper conflict detection：lock signature 一致/不一致
6. (補充) Resume plan：模擬「2 節 done + crash」→ 計畫從第 3 節開始
7. (bonus) 整合測試：模擬 crash after 2 sections, resume 從 section 3 開始 → 真的生成 section_3.html

設計：3 必要 + 4 補充 = 7 cases（含 bonus integration）
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from scripts.report_lock import read_lock, write_lock
from scripts.resume_helper import (
    ConflictInfo,
    GapAnalysisResult,
    ResumeHelper,
    ResumeHelperError,
    ResumePlan,
    lock_signature,
)
from scripts.executor import ExecutorResult  # type returned by helper.run()
from scripts.strategist import build_lock_template


# ─── Fixtures ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_MD = PROJECT_ROOT / "workflows" / "resume-execute.md"
EXECUTOR_MD = PROJECT_ROOT / "references" / "executor-base.md"


@pytest.fixture
def tmp_lock_with_progress(tmp_path: Path) -> Path:
    """產生一份 5 節 academic lock，注入 progress 標記完成到第 2 節。"""
    lock = build_lock_template(
        "academic",
        metadata_overrides={"title": "T3-5 Resume Test"},
    )
    # 5 個 sections（academic default）
    lock["sections"] = lock["sections"][:5]
    # 注入 progress：完成到第 2 節
    sig = lock_signature(lock)
    lock["metadata"]["progress"] = {
        "current_section": 2,
        "total_sections": 5,
        "completed_sections": [1, 2],
        "last_updated": "2026-06-13T13:30:00",
        "status": "in_progress",
        "lock_signature": sig,
    }
    lock_path = tmp_path / "report_lock.md"
    write_lock(lock_path, lock, body="# resume test lock\n")
    return lock_path


@pytest.fixture
def tmp_lock_with_partial_html(tmp_path: Path) -> Path:
    """產生 5 節 lock + 寫好 section_1.html / section_2.html（disk 完成 2 節）。"""
    lock = build_lock_template(
        "academic",
        metadata_overrides={"title": "T3-5 Partial HTML Test"},
    )
    lock["sections"] = lock["sections"][:5]
    sig = lock_signature(lock)
    lock["metadata"]["progress"] = {
        "current_section": 2,
        "total_sections": 5,
        "completed_sections": [1, 2],
        "last_updated": "2026-06-13T13:30:00",
        "status": "in_progress",
        "lock_signature": sig,
    }
    lock_path = tmp_path / "report_lock.md"
    write_lock(lock_path, lock, body="# resume test lock\n")

    output_dir = tmp_path / "report_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    # 寫 2 個 section HTML（disk 完成 2 節）
    for i in (1, 2):
        (output_dir / f"section_{i}.html").write_text(
            f"<!DOCTYPE html><html><body>section {i}</body></html>",
            encoding="utf-8",
        )
    return lock_path


# ─── Test 1（必要）: 載入 workflows/resume-execute.md frontmatter 不 crash ─

def test_workflow_md_frontmatter_loads():
    """載入 workflows/resume-execute.md frontmatter 不 crash + 必要欄位齊備。"""
    assert WORKFLOW_MD.exists(), f"找不到 {WORKFLOW_MD}"

    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert content.startswith("---\n"), "resume-execute.md 應以 frontmatter 開頭"

    m = re.match(r"\A---\s*\n(?P<yaml>.*?)\n---", content, re.DOTALL)
    assert m is not None, "frontmatter 區塊未正確閉合"

    fm = yaml.safe_load(m.group("yaml"))
    assert isinstance(fm, dict), "frontmatter 應為 mapping"

    # 必要欄位
    assert fm.get("name") == "resume-execute", "name 應為 'resume-execute'"
    assert fm.get("description"), "description 必填"
    assert len(fm.get("description", "")) >= 50, "description 太短"
    assert str(fm.get("version")) == "1.0", "version 應為 1.0"

    # DoD 1：行數 > 100
    line_count = len(content.splitlines())
    assert line_count > 100, f"workflow 應 > 100 行，目前 {line_count}"

    # 額外：應引用 executor-base.md
    assert "executor-base" in content, "resume-execute.md 應引用 references/executor-base.md"


# ─── Test 2（必要）: Mermaid flowchart 存在 ─────────────────────────

def test_workflow_md_contains_mermaid():
    """workflows/resume-execute.md 內含 Mermaid flowchart（regex `` ```mermaid ``）。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")

    pattern = re.compile(r"^```mermaid\s*$", re.MULTILINE)
    matches = pattern.findall(content)
    assert len(matches) >= 1, "workflow 應含至少 1 個 mermaid 區塊"

    m = re.search(r"```mermaid\s*\n(?P<body>.*?)\n```", content, re.DOTALL)
    assert m is not None, "應有完整 mermaid 區塊（``` 閉合）"
    mermaid_body = m.group("body")
    assert "flowchart" in mermaid_body or "graph" in mermaid_body, (
        "Mermaid 區塊應含 flowchart 或 graph 關鍵字"
    )
    # 額外：flowchart 應含「Resume」或「Conflict」或「State Check」關鍵字（resume 主題）
    keywords = ["State Check", "Gap Analysis", "Resume", "Conflict"]
    found = sum(1 for kw in keywords if kw in mermaid_body)
    assert found >= 2, f"Mermaid 應含 resume 主題關鍵字，找到 {found}/{len(keywords)}"


# ─── Test 3（必要）: resume_helper.py CLI --lock <path> --dry-run 不 crash ─

def test_resume_helper_cli_dry_run(tmp_lock_with_progress: Path):
    """`python -m scripts.resume_helper --lock <p> --dry-run` 不 crash + 印出計畫。"""
    lock_path = tmp_lock_with_progress
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.resume_helper",
            "--lock", str(lock_path),
            "--output", str(lock_path.parent / "report_output"),
            "--dry-run",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"CLI 失敗（returncode={result.returncode}）\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # 應有 plan 內容
    assert "Resume Helper" in result.stdout
    assert "計畫" in result.stdout or "will_run" in result.stdout or "will run" in result.stdout.lower()


# ─── Test 4（補充）: ResumeHelper gap analysis 找正確的 present / missing ──

def test_gap_analysis_detects_partial_completion(tmp_lock_with_partial_html: Path):
    """disk 上有 section_1 / section_2 → gap analysis 應回 present=[1,2], missing=[3,4,5]。"""
    lock_path = tmp_lock_with_partial_html
    output_dir = lock_path.parent / "report_output"
    helper = ResumeHelper(lock_path, output_dir=output_dir)

    gap = helper.gap_analysis()
    assert isinstance(gap, GapAnalysisResult)
    assert gap.present == [1, 2], f"present 應為 [1, 2]，實際 {gap.present}"
    assert gap.missing == [3, 4, 5], f"missing 應為 [3, 4, 5]，實際 {gap.missing}"
    assert gap.total == 5
    assert gap.all_present is False


# ─── Test 5（補充）: ResumeHelper conflict detection ───────────────

def test_conflict_detection_signature_match(tmp_lock_with_progress: Path):
    """lock signature 一致時 conflict.detected = False。"""
    helper = ResumeHelper(
        tmp_lock_with_progress,
        output_dir=tmp_lock_with_progress.parent / "report_output",
    )
    info = helper.detect_conflict()
    assert isinstance(info, ConflictInfo)
    assert info.detected is False
    assert info.new_signature is not None
    assert len(info.new_signature) == 12  # SHA256 prefix


def test_conflict_detection_signature_mismatch(tmp_path: Path):
    """progress 寫的 signature 跟現 lock 不符時 conflict.detected = True。"""
    lock = build_lock_template("academic", metadata_overrides={"title": "mismatch"})
    lock["sections"] = lock["sections"][:3]
    real_sig = lock_signature(lock)
    # 故意寫一個假的 sig 進 progress
    lock["metadata"]["progress"] = {
        "current_section": 2,
        "total_sections": 3,
        "completed_sections": [1, 2],
        "lock_signature": "deadbeef0000",  # 假的
    }
    lock_path = tmp_path / "lock.md"
    write_lock(lock_path, lock, body="# x\n")

    helper = ResumeHelper(lock_path, output_dir=tmp_path / "output")
    info = helper.detect_conflict()
    assert info.detected is True
    assert info.old_signature == "deadbeef0000"
    assert info.new_signature == real_sig


# ─── Test 6（補充）: Resume plan 從 N+1 開始 ──────────────────────

def test_plan_starts_from_next_section(tmp_lock_with_partial_html: Path):
    """disk 完成到第 2 節，plan.next_start 應為 3、will_run=[3,4,5]。"""
    lock_path = tmp_lock_with_partial_html
    output_dir = lock_path.parent / "report_output"
    helper = ResumeHelper(lock_path, output_dir=output_dir)

    plan = helper.plan()
    assert isinstance(plan, ResumePlan)
    assert plan.next_start == 3, f"next_start 應為 3，實際 {plan.next_start}"
    assert plan.will_run == [3, 4, 5], f"will_run 應為 [3,4,5]，實際 {plan.will_run}"
    assert plan.will_skip == [1, 2], f"will_skip 應為 [1,2]，實際 {plan.will_skip}"
    assert plan.gap.present == [1, 2]
    assert plan.gap.missing == [3, 4, 5]
    assert plan.conflict.detected is False
    assert plan.total_sections == 5


def test_plan_with_rebuild_changed_runs_all(tmp_lock_with_partial_html: Path):
    """rebuild_changed=True 時，即使 conflict 沒偵測到（此測資），也仍要尊重 flag 行為：
    衝突偵測需要 progress.lock_signature，但這裡 lock 沒改 → conflict.detected=False。
    因此 will_run 仍應為 missing 的節；rebuild_changed 在「無 conflict」時不應主動觸發。
    """
    lock_path = tmp_lock_with_partial_html
    output_dir = lock_path.parent / "report_output"
    helper = ResumeHelper(lock_path, output_dir=output_dir, rebuild_changed=True)

    plan = helper.plan()
    # 沒衝突時，rebuild_changed flag 對 plan 無影響（plan 只看 disk）
    assert plan.will_run == [3, 4, 5]
    assert plan.rebuild_changed is True


def test_plan_with_rebuild_changed_and_conflict_runs_all(tmp_path: Path):
    """衝突 + rebuild_changed → will_run 應為全 5 節。"""
    lock = build_lock_template("academic", metadata_overrides={"title": "rebuild test"})
    lock["sections"] = lock["sections"][:5]
    # progress 寫一個錯的 signature
    lock["metadata"]["progress"] = {
        "current_section": 2,
        "total_sections": 5,
        "completed_sections": [1, 2],
        "lock_signature": "old_old_old_",
    }
    lock_path = tmp_path / "lock.md"
    write_lock(lock_path, lock, body="# x\n")

    # 寫 2 個 section HTML
    output_dir = tmp_path / "report_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    for i in (1, 2):
        (output_dir / f"section_{i}.html").write_text(
            f"<!DOCTYPE html><html><body>section {i}</body></html>",
            encoding="utf-8",
        )

    helper = ResumeHelper(lock_path, output_dir=output_dir, rebuild_changed=True)
    plan = helper.plan()
    assert plan.conflict.detected is True
    assert plan.will_run == [1, 2, 3, 4, 5], f"重建時應全跑，實際 {plan.will_run}"
    assert plan.will_skip == []


# ─── Test 7（bonus integration）: 模擬 crash + resume ─────────────

def test_bonus_crash_after_2_sections_resume_from_3(tmp_path: Path):
    """Bonus integration：模擬 crash after 2 sections，resume_helper 真的從 section 3 開始執行。

    流程：
    1. 建立 5 節 lock
    2. 手動寫 section_1.html / section_2.html（模擬「跑完前 2 節」）
    3. 注入 progress 標記完成到 2
    4. 跑 helper.run()（resume_helper 內部呼叫 Executor.run()）
    5. 驗證 section_3.html / section_4.html / section_5.html 真的生成
    6. 驗證 progress 寫回 lock
    """
    lock = build_lock_template("academic", metadata_overrides={"title": "Crash + Resume Test"})
    lock["sections"] = lock["sections"][:5]
    sig = lock_signature(lock)
    lock["metadata"]["progress"] = {
        "current_section": 2,
        "total_sections": 5,
        "completed_sections": [1, 2],
        "lock_signature": sig,
    }
    lock_path = tmp_path / "report_lock.md"
    write_lock(lock_path, lock, body="# crash+resume test\n")

    output_dir = tmp_path / "report_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    # 寫 2 個 section HTML（disk 已有）
    for i in (1, 2):
        (output_dir / f"section_{i}.html").write_text(
            f"<!DOCTYPE html><html><body>section {i}</body></html>",
            encoding="utf-8",
        )

    # 跑 resume_helper（不 rebuild_changed，因為 lock 沒改）
    helper = ResumeHelper(lock_path, output_dir=output_dir, rebuild_changed=False)
    plan = helper.plan()
    assert plan.will_run == [3, 4, 5]
    assert plan.will_skip == [1, 2]

    # 實際執行
    result = helper.run(plan=plan)
    assert result.passed, f"resume 應通過；errors={result.errors}"
    # 這次 run 補完 3, 4, 5
    assert result.completed_sections == [3, 4, 5], (
        f"應補完 [3,4,5]，實際 {result.completed_sections}"
    )

    # section_3/4/5.html 應存在
    for n in (3, 4, 5):
        p = output_dir / f"section_{n}.html"
        assert p.exists(), f"resume 應生成 {p.name}"
        text = p.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in text
        assert "<h1>" in text

    # progress 應寫回 lock
    persisted = read_lock(lock_path)
    progress = persisted["metadata"].get("progress", {})
    assert progress.get("status") == "completed"
    assert progress.get("completed_sections") == [1, 2, 3, 4, 5]
    assert progress.get("current_section") == 5
