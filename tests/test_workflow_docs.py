# test_workflow_docs.py — workflow 文件版本 / 引用合約測試
# 對應 tasks.md Phase 3 缺陷 #1（Section Blueprint）+ #2（Confirmation Loop）+ #3（Content Expansion）
# 涵蓋：
#   1. workflows/strategist.md v1.1 存在 + frontmatter 正確
#   2. workflows/strategist.md 含 Section Blueprint + 停等確認 字串
#   3. workflows/user-confirmation.md v1.0 存在 + 含 confirmation gate 設計
#   4. workflows/topic-research.md v1.1 含 Content Expansion 階段
#   5. 跨 workflow 引用：strategist ↔ user-confirmation ↔ topic-research
#   6. references/strategist.md v1.0 仍存在（沒破壞既有 schema）

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRATEGIST_WF = PROJECT_ROOT / "workflows" / "strategist.md"
USER_CONFIRMATION_WF = PROJECT_ROOT / "workflows" / "user-confirmation.md"
TOPIC_RESEARCH_WF = PROJECT_ROOT / "workflows" / "topic-research.md"
STRATEGIST_REF = PROJECT_ROOT / "references" / "strategist.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_fm(content: str) -> dict:
    m = re.match(r"\A---\s*\n(?P<yaml>.*?)\n---", content, re.DOTALL)
    assert m is not None, "frontmatter 區塊未正確閉合"
    return yaml.safe_load(m.group("yaml"))


# ─── Test 1: workflows/strategist.md v1.1 存在 + frontmatter 正確 ──

def test_strategist_workflow_v11_exists():
    """workflows/strategist.md v1.1 應存在（Problem 1 修）。"""
    assert STRATEGIST_WF.exists(), f"找不到 {STRATEGIST_WF}"
    content = _read(STRATEGIST_WF)
    fm = _load_fm(content)
    assert fm.get("name") == "strategist"
    assert fm.get("version", "").startswith("1.1"), (
        f"strategist.md version 應為 1.1.x，實際：{fm.get('version')}"
    )
    assert "Section Blueprint" in fm.get("description", "") or "Confirmation" in fm.get("description", ""), (
        "description 應提及 Section Blueprint 或 Confirmation"
    )


def test_strategist_workflow_contains_section_blueprint():
    """strategist.md 應含 Section Blueprint 章節（Problem 1 修）。"""
    content = _read(STRATEGIST_WF)
    assert "Section Blueprint" in content, "應含 Section Blueprint 階段"
    assert "0_outline.md" in content, "應提到 0_outline.md 產物"
    assert "目標" in content, "blueprint 應含『目標』欄位"
    assert "重點子節" in content, "blueprint 應含『重點子節』欄位"
    assert "預估頁數" in content, "blueprint 應含『預估頁數』欄位"


def test_strategist_workflow_contains_confirmation_pause():
    """strategist.md 應明確標示「停等使用者確認」階段（Problem 2 修）。"""
    content = _read(STRATEGIST_WF)
    # 必須有顯式的 confirmation gate
    assert "0_outline_for_review.md" in content, "應提到 0_outline_for_review.md"
    assert "0_confirmed.json" in content, "應提到 0_confirmed.json"
    assert "停等使用者確認" in content or "停等確認" in content, (
        "應有顯式的『停等確認』字串"
    )
    # 必須引用 user-confirmation workflow
    assert "workflows/user-confirmation.md" in content, (
        "應引用 workflows/user-confirmation.md"
    )


def test_strategist_workflow_references_executor_base():
    """strategist.md 應引用 references/executor-base.md（T3-2 銜接）。"""
    content = _read(STRATEGIST_WF)
    assert "references/executor-base.md" in content, (
        "應引用 references/executor-base.md"
    )


# ─── Test 2: workflows/user-confirmation.md v1.0 存在 + 完整 ──

def test_user_confirmation_workflow_v10_exists():
    """workflows/user-confirmation.md v1.0 應存在（Problem 2 修）。"""
    assert USER_CONFIRMATION_WF.exists(), f"找不到 {USER_CONFIRMATION_WF}"
    content = _read(USER_CONFIRMATION_WF)
    fm = _load_fm(content)
    assert fm.get("name") == "user-confirmation"
    assert fm.get("version", "").startswith("1.0"), (
        f"user-confirmation.md version 應為 1.0.x，實際：{fm.get('version')}"
    )
    # S 等級（小工具）
    assert "S 等級" in content or "S 等级" in content, "應標示為 S 等級"


def test_user_confirmation_workflow_defines_review_format():
    """user-confirmation.md 應定義 0_outline_for_review.md 的內容格式。"""
    content = _read(USER_CONFIRMATION_WF)
    assert "0_outline_for_review.md" in content
    assert "## 待確認項目" in content, "應含『待確認項目』區塊"
    assert "章節架構" in content, "應含章節架構確認項"
    assert "章節順序" in content, "應含章節順序確認項"


def test_user_confirmation_workflow_defines_confirmed_json():
    """user-confirmation.md 應定義 0_confirmed.json 的欄位。"""
    content = _read(USER_CONFIRMATION_WF)
    assert "0_confirmed.json" in content
    assert "executor_can_start" in content, (
        "應定義 executor_can_start 旗標"
    )
    assert "section_titles" in content, "應含 section_titles 欄位"


def test_user_confirmation_workflow_defines_executor_refusal():
    """user-confirmation.md 應定義 Executor 拒絕啟動保護。"""
    content = _read(USER_CONFIRMATION_WF)
    # 必須有「拒絕啟動」字串 + JSON 檢查 code
    assert "拒絕啟動" in content, "應有『拒絕啟動』說明"
    assert "_check_confirmation" in content or "executor_can_start" in content, (
        "應定義 Executor 啟動前檢查邏輯"
    )


# ─── Test 3: workflows/topic-research.md v1.1 含 Content Expansion ──

def test_topic_research_workflow_v11_has_content_expansion():
    """workflows/topic-research.md v1.1 應含 Content Expansion 階段（Problem 3 修）。"""
    content = _read(TOPIC_RESEARCH_WF)
    assert "Content Expansion" in content, "應含 Content Expansion 階段"
    assert "content_expansion" in content, "應含 content_expansion/ 目錄"
    assert "web_search" in content, "應提到 web_search tool"
    assert "scripts/web_research.py" in content, "應引用 scripts/web_research.py"


def test_topic_research_workflow_references_new_workflows():
    """topic-research.md 應引用 v1.1 新增的 workflow 與 scripts。"""
    content = _read(TOPIC_RESEARCH_WF)
    assert "workflows/strategist.md" in content, "應引用 workflows/strategist.md"
    assert "workflows/user-confirmation.md" in content, "應引用 workflows/user-confirmation.md"


# ─── Test 4: references/strategist.md v1.0 仍存在 ──

def test_references_strategist_v10_still_intact():
    """references/strategist.md v1.0 應仍存在（沒破壞既有 schema 檔）。"""
    assert STRATEGIST_REF.exists(), f"找不到 {STRATEGIST_REF}"
    content = _read(STRATEGIST_REF)
    fm = _load_fm(content)
    assert fm.get("name") == "strategist"
    assert fm.get("version", "").startswith("1.0"), (
        f"references/strategist.md version 應仍為 1.0.x，實際：{fm.get('version')}"
    )
    # 必須仍含 10 Confirmations
    assert "Q1" in content and "Q10" in content, (
        "10 Confirmations 應仍在 references/strategist.md"
    )
    # 必須 forward-ref 到新 workflow
    assert "workflows/strategist.md" in content, (
        "應 forward-ref 到 workflows/strategist.md v1.1"
    )


# ─── Test 5: 跨 workflow 引用合約 ──

def test_cross_workflow_reference_chain():
    """strategist → user-confirmation → executor base 引用鏈完整。"""
    strategist = _read(STRATEGIST_WF)
    user_conf = _read(USER_CONFIRMATION_WF)
    executor_ref = _read(PROJECT_ROOT / "references" / "executor-base.md")

    # strategist → user-confirmation
    assert "workflows/user-confirmation.md" in strategist
    # user-confirmation → strategist + executor
    assert "workflows/strategist.md" in user_conf
    assert "references/executor-base.md" in user_conf
    # executor → strategist（仍可吃 lock）
    assert "references/strategist.md" in executor_ref or "report_lock.md" in executor_ref


def test_topic_research_references_strategist_and_executor():
    """topic-research.md 應仍引用 strategist.md（向上游）與 executor-base.md（向下游）。"""
    content = _read(TOPIC_RESEARCH_WF)
    assert "references/strategist.md" in content
    assert "references/executor-base.md" in content
