r"""tests/test_topic_research.py — scripts/topic_research.py + workflows/topic-research.md 單元測試。

DoD 對應 `tasks.md` T3-3：
1. 載入 `workflows/topic-research.md` frontmatter 不 crash
2. Mermaid flowchart 存在（regex ` ```mermaid `）
3. `topic_research.py` CLI `--topic "test"` 不 crash
4. (補充) ResearchNotes 驗證：sub-questions < 3 → raise
5. (補充) ResearchNotes 序列化：含 Sub-questions + Outline 章節
6. (補充) StubLLM 預設行為：3 sub-questions + 5 章 outline
7. (補充) end-to-end 整合：給 topic → 產 3 sub-questions + 5-section outline
8. (補充) 對 reference 引用：strategist.md / executor-base.md 都在文內
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.topic_research import (
    OutlineSection,
    ResearchNotes,
    ResearchValidationError,
    StubLLM,
    SubQuestion,
    TopicResearchError,
    run_research,
)


# ─── Fixtures ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_MD = PROJECT_ROOT / "workflows" / "topic-research.md"
STRATEGIST_MD = PROJECT_ROOT / "references" / "strategist.md"
EXECUTOR_MD = PROJECT_ROOT / "references" / "executor-base.md"


# ─── Test 1（必要）: 載入 workflows/topic-research.md frontmatter 不 crash ─

def test_workflow_md_frontmatter_loads():
    """載入 workflows/topic-research.md frontmatter 不 crash + 必要欄位齊備。"""
    assert WORKFLOW_MD.exists(), f"找不到 {WORKFLOW_MD}"

    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert content.startswith("---\n"), "topic-research.md 應以 frontmatter 開頭"

    # 用正則抓 frontmatter
    m = re.match(r"\A---\s*\n(?P<yaml>.*?)\n---", content, re.DOTALL)
    assert m is not None, "frontmatter 區塊未正確閉合"

    fm = yaml.safe_load(m.group("yaml"))
    assert isinstance(fm, dict), "frontmatter 應為 mapping"

    # 必要欄位
    assert fm.get("name") == "topic-research", "name 應為 'topic-research'"
    assert fm.get("description"), "description 必填"
    assert len(fm.get("description", "")) >= 50, "description 太短"
    assert fm.get("version"), "version 必填"

    # 檔案行數 DoD 1
    line_count = len(content.splitlines())
    assert line_count > 100, f"workflow 應 > 100 行，目前 {line_count}"


# ─── Test 2（必要）: Mermaid flowchart 存在 ─────────────────────────

def test_workflow_md_contains_mermaid():
    """workflows/topic-research.md 內含 Mermaid flowchart（regex `` ```mermaid ``）。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")

    # 找 ```mermaid 開頭的區塊
    pattern = re.compile(r"^```mermaid\s*$", re.MULTILINE)
    matches = pattern.findall(content)
    assert len(matches) >= 1, "workflow 應含至少 1 個 ```mermaid 區塊"

    # 額外檢查：Mermaid 內含 flowchart 關鍵字
    m = re.search(r"```mermaid\s*\n(?P<body>.*?)\n```", content, re.DOTALL)
    assert m is not None, "應有完整 mermaid 區塊（``` 閉合）"
    mermaid_body = m.group("body")
    assert "flowchart" in mermaid_body or "graph" in mermaid_body, (
        "Mermaid 區塊應含 flowchart 或 graph 關鍵字"
    )


# ─── Test 3（必要）: topic_research.py CLI --topic "test" 不 crash ────

def test_topic_research_cli_runs(tmp_path: Path):
    """`python -m scripts.topic_research --topic "test" --output <tmp>` 不 crash。"""
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.topic_research",
            "--topic", "test topic",
            "--output", str(tmp_path),
            "--quiet",
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

    # 應有 research_notes.md
    notes_path = tmp_path / "research_notes.md"
    assert notes_path.exists(), f"沒產出 {notes_path}"
    content = notes_path.read_text(encoding="utf-8")
    assert "test topic" in content
    assert "## Sub-questions" in content
    assert "## Outline" in content


# ─── Test 4（補充）: ResearchNotes 驗證：sub-questions < 3 → raise ───

def test_research_notes_validation_raises_on_too_few_sub_questions():
    """sub-questions < 3 時 ResearchNotes.validate() 應 raise ResearchValidationError。"""
    notes = ResearchNotes(topic="x")
    notes.sub_questions = [SubQuestion(id="q1", question="?", angle="理論")]
    notes.outline = [
        OutlineSection(index=1, title="第一章", path="report_output/section_1.html"),
        OutlineSection(index=2, title="第二章", path="report_output/section_2.html"),
        OutlineSection(index=3, title="第三章", path="report_output/section_3.html"),
    ]
    with pytest.raises(ResearchValidationError) as exc_info:
        notes.validate()
    assert "sub-questions" in str(exc_info.value).lower() or "BLOCKING" in str(exc_info.value)


def test_research_notes_validation_raises_on_too_few_sections():
    """outline < 3 章時 ResearchNotes.validate() 應 raise。"""
    notes = ResearchNotes(topic="x")
    notes.sub_questions = [
        SubQuestion(id="q1", question="?", angle="理論"),
        SubQuestion(id="q2", question="?", angle="實務"),
        SubQuestion(id="q3", question="?", angle="影響"),
    ]
    notes.outline = [
        OutlineSection(index=1, title="第一章", path="report_output/section_1.html"),
    ]
    with pytest.raises(ResearchValidationError):
        notes.validate()


# ─── Test 5（補充）: ResearchNotes 序列化含必要區塊 ──────────────────

def test_research_notes_markdown_serialization():
    """ResearchNotes.to_markdown() 應含 Sub-questions + Outline + 給 Strategist 的提示。"""
    notes = ResearchNotes(topic="AI 對教育的影響")
    notes.sub_questions = [
        SubQuestion(id="q1", question="趨勢是什麼？", angle="實務"),
        SubQuestion(id="q2", question="成效如何？", angle="影響"),
        SubQuestion(id="q3", question="未來展望？", angle="未來"),
    ]
    notes.outline = [
        OutlineSection(index=1, title="第一章 緒論", path="report_output/section_1.html"),
        OutlineSection(index=2, title="第二章 趨勢", path="report_output/section_2.html", sub_question_id="q1"),
        OutlineSection(index=3, title="第三章 成效", path="report_output/section_3.html", sub_question_id="q2"),
        OutlineSection(index=4, title="第四章 未來", path="report_output/section_4.html", sub_question_id="q3"),
        OutlineSection(index=5, title="第五章 結論", path="report_output/section_5.html"),
    ]

    md = notes.to_markdown()
    assert "## Sub-questions" in md
    assert "## Outline" in md
    assert "## 給 Strategist 的提示" in md
    assert "趨勢是什麼？" in md
    assert "第一章 緒論" in md
    assert "q1" in md  # sub-question 對應


# ─── Test 6（補充）: StubLLM 預設行為 ──────────────────────────────

def test_stub_llm_default_behavior():
    """StubLLM 預設產出 3 個 sub-questions（保底） + 5 章 outline。"""
    llm = StubLLM()
    sqs = llm.generate_sub_questions("test", n=5)
    assert len(sqs) >= 3, f"sub-questions 至少 3 個，實際 {len(sqs)}"
    assert all(sq.id for sq in sqs), "每個 sub-question 應有 id"
    assert all(sq.question for sq in sqs), "每個 sub-question 應有 question"

    outline = llm.generate_outline("test", sqs, n_sections=5)
    assert len(outline) == 5, f"outline 應 5 章，實際 {len(outline)}"
    assert outline[0].title == "第一章 緒論", "首章應為緒論"
    assert "結論" in outline[-1].title, f"末章標題應含『結論』，實際：{outline[-1].title}"
    # 至少一個章節有對應 sub-question
    has_sq = any(sec.sub_question_id for sec in outline)
    assert has_sq, "中間章節應有 sub_question_id"


# ─── Test 7（補充）: end-to-end 整合測試 ────────────────────────────

def test_run_research_end_to_end(tmp_path: Path):
    """給 topic → 產 3 sub-questions + 5-section outline + 寫入檔案。"""
    notes = run_research(
        topic="機器學習在醫療的應用",
        output_dir=tmp_path,
        n_sub_questions=5,
        n_sections=5,
        min_sub_questions=3,
        min_outline=3,
        verbose=False,
    )

    # ResearchNotes 結構
    assert isinstance(notes, ResearchNotes)
    assert len(notes.sub_questions) >= 3
    assert len(notes.outline) >= 5

    # 檔案寫入
    notes_path = tmp_path / "research_notes.md"
    assert notes_path.exists()
    content = notes_path.read_text(encoding="utf-8")
    assert "機器學習在醫療的應用" in content
    assert "## Sub-questions" in content
    assert "## Outline" in content


# ─── Test 8（補充）: workflow 引用 strategist + executor ─────────────

def test_workflow_references_strategist_and_executor():
    """workflow 應引用 references/strategist.md 與 references/executor-base.md。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    # 引用 references/strategist.md
    assert "references/strategist.md" in content, (
        "workflow 應引用 references/strategist.md"
    )
    # 引用 references/executor-base.md
    assert "references/executor-base.md" in content, (
        "workflow 應引用 references/executor-base.md"
    )


# ─── Test 9（補充）: empty topic 應 raise ───────────────────────────

def test_run_research_empty_topic_raises(tmp_path: Path):
    """空 topic 應 raise TopicResearchError。"""
    with pytest.raises(TopicResearchError):
        run_research(
            topic="",
            output_dir=tmp_path,
            verbose=False,
        )

    with pytest.raises(TopicResearchError):
        run_research(
            topic="   ",
            output_dir=tmp_path,
            verbose=False,
        )
