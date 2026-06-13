"""tests/test_technical_design.py — scripts/technical_design.py + workflows/technical-design.md 單元測試.

DoD 對應 `tasks.md` T3-14：
1. 載入 `workflows/technical-design.md` frontmatter 不 crash
2. Mermaid flowchart 存在（regex ` ```mermaid `）
3. `technical_design.py` CLI `--name "test"` 不 crash
4. 產出目錄包含 `design.md`

補充測試：
- DesignDocument 結構與 Final Gate 校驗
- StubLLM 預設行為（7 scope questions + ≥3 API + ≥2 entities + ≥3 milestones）
- ScopeQuestion / APISpec / Entity / Milestone 序列化
- end-to-end run_design 整合測試
- 對 references/strategist.md + workflows/topic-research.md 引用
- workflow 含 audience 範本清單（engineers / pm / executives）
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.technical_design import (
    APISpec,
    ArchitectureNode,
    DesignDocument,
    Entity,
    FinalGateError,
    LLMError,
    Milestone,
    ScopeQuestion,
    StubLLM,
    TechnicalDesignError,
    _next_version_dir,
    _select_template,
    run_design,
)


# ─── Fixtures ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_MD = PROJECT_ROOT / "workflows" / "technical-design.md"
STRATEGIST_MD = PROJECT_ROOT / "references" / "strategist.md"
TOPIC_RESEARCH_MD = PROJECT_ROOT / "workflows" / "topic-research.md"


# ─── Test 1（必要）: 載入 workflows/technical-design.md frontmatter 不 crash ─

def test_workflow_md_frontmatter_loads():
    """載入 workflows/technical-design.md frontmatter 不 crash + 必要欄位齊備。"""
    assert WORKFLOW_MD.exists(), f"找不到 {WORKFLOW_MD}"

    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert content.startswith("---\n"), "technical-design.md 應以 frontmatter 開頭"

    # 用正則抓 frontmatter
    m = re.match(r"\A---\s*\n(?P<yaml>.*?)\n---", content, re.DOTALL)
    assert m is not None, "frontmatter 區塊未正確閉合"

    fm = yaml.safe_load(m.group("yaml"))
    assert isinstance(fm, dict), "frontmatter 應為 mapping"

    # 必要欄位
    assert fm.get("name") == "technical-design", "name 應為 'technical-design'"
    assert fm.get("description"), "description 必填"
    assert len(fm.get("description", "")) >= 50, "description 太短"
    assert str(fm.get("version", "")) == "1.0", "version 應為 '1.0'"

    # 檔案行數 DoD 1
    line_count = len(content.splitlines())
    assert line_count > 100, f"workflow 應 > 100 行，目前 {line_count}"


# ─── Test 2（必要）: Mermaid flowchart 存在 ─────────────────────────

def test_workflow_md_contains_mermaid():
    """workflows/technical-design.md 內含 Mermaid flowchart（regex `` ```mermaid ``）。"""
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


# ─── Test 3（必要）: technical_design.py CLI --name "test" 不 crash ──

def test_technical_design_cli_runs(tmp_path: Path):
    """`python -m scripts.technical_design --name "test" --scope "..."` 不 crash。

    整合測試：跑完整 7 階段流程，產 design.md + scope.md。
    exit code 應為 0（Final Gate PASS）。
    """
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.technical_design",
            "--name", "test-feature",
            "--scope", "smoke test scope description",
            "--output-dir", str(tmp_path),
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

    # 應有 design.md
    target_dir = tmp_path / "test-feature"
    assert target_dir.exists(), f"沒產出 {target_dir}"
    design_path = target_dir / "design.md"
    assert design_path.exists(), f"沒產出 {design_path}"
    content = design_path.read_text(encoding="utf-8")
    assert "test-feature" in content
    assert "## 1. Overview" in content
    assert "## 2. Architecture" in content
    assert "## 3. API Design" in content
    assert "## 4. Data Model" in content
    assert "## 5. Implementation Plan" in content
    assert "## 6. Risks & Open Questions" in content


# ─── Test 4（必要）: 產出目錄包含 design.md ────────────────────────

def test_output_dir_contains_design_md(tmp_path: Path):
    """執行 run_design 後 technical_design_output/<name>/ 應含 design.md + scope.md。"""
    output_root = tmp_path / "designs"
    doc = run_design(
        name="md-output-check",
        audience="engineers",
        scope="驗證產出目錄結構",
        output_dir=output_root,
        verbose=False,
    )

    assert isinstance(doc, DesignDocument)
    target_dir = output_root / "md-output-check"
    assert target_dir.is_dir(), f"應產出 {target_dir} 目錄"

    design_path = target_dir / "design.md"
    assert design_path.exists(), f"沒產出 {design_path}"
    assert design_path.stat().st_size > 0, "design.md 應非空"

    scope_path = target_dir / "scope.md"
    assert scope_path.exists(), f"沒產出 {scope_path}"
    assert scope_path.stat().st_size > 0, "scope.md 應非空"

    # 驗證 design.md 內容含 6 章節
    design_text = design_path.read_text(encoding="utf-8")
    for sec in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "## 6."):
        assert sec in design_text, f"design.md 應含 {sec} 章節"


# ─── Test 5（補充）: DesignDocument.check_final_gate ─────────────────

def test_final_gate_validation_pass_and_fail():
    """DesignDocument.check_final_gate：完整 doc → 空 list；缺章節 → 列出缺失。"""
    # PASS case
    doc = DesignDocument(
        name="x",
        audience="engineers",
        scope="y",
    )
    doc.scope_questions = [ScopeQuestion(id=f"q{i}", topic="t", question="?", answer="a") for i in range(1, 8)]
    doc.architecture_overview = "overview"
    doc.architecture_diagram = "flowchart LR\nA --> B"
    doc.architecture_nodes = [
        ArchitectureNode(id="a", name="A", description="A node"),
        ArchitectureNode(id="b", name="B", description="B node"),
        ArchitectureNode(id="c", name="C", description="C node"),
    ]
    doc.apis = [
        APISpec(name="a1", endpoint="/x", input_desc="in", output_desc="out", error_desc="err"),
        APISpec(name="a2", endpoint="/y", input_desc="in", output_desc="out", error_desc="err"),
        APISpec(name="a3", endpoint="/z", input_desc="in", output_desc="out", error_desc="err"),
    ]
    doc.entities = [
        Entity(name="E1", fields=[{"name": "id", "type": "int", "nullable": "NO", "description": "id"}]),
        Entity(name="E2", fields=[{"name": "id", "type": "int", "nullable": "NO", "description": "id"}]),
    ]
    doc.milestones = [
        Milestone(name="M1", days=1, deliverables=["d1"], acceptance=["a1"]),
        Milestone(name="M2", days=1, deliverables=["d2"], acceptance=["a2"]),
        Milestone(name="M3", days=1, deliverables=["d3"], acceptance=["a3"]),
    ]
    doc.risks = ["risk1"]
    doc.open_questions = ["q1"]

    missing = doc.check_final_gate()
    assert missing == [], f"PASS case 應無缺失，got: {missing}"

    # FAIL case: 缺 architecture diagram
    bad_doc = DesignDocument(name="x", audience="engineers", scope="y")
    bad_doc.apis = doc.apis
    bad_doc.entities = doc.entities
    bad_doc.milestones = doc.milestones
    bad_doc.risks = ["risk"]
    # 故意不設 architecture_diagram / nodes
    missing_bad = bad_doc.check_final_gate()
    assert len(missing_bad) >= 1, "FAIL case 應有缺失"
    assert any("Architecture" in m for m in missing_bad), (
        f"應報 Architecture 缺失，got: {missing_bad}"
    )


# ─── Test 6（補充）: StubLLM 預設行為 ──────────────────────────────

def test_stub_llm_default_behavior():
    """StubLLM 預設產出 7 scope questions + ≥3 API + ≥2 entities + ≥3 milestones。"""
    llm = StubLLM()

    # Scope questions
    sqs = llm.generate_scope_questions("test", "engineers", "test scope")
    assert len(sqs) >= 5, f"scope questions 至少 5 個，實際 {len(sqs)}"
    assert all(sq.id for sq in sqs), "每個 question 應有 id"
    assert all(sq.question for sq in sqs), "每個 question 應有 question text"

    # Architecture
    overview, diagram, nodes, data_flow = llm.generate_architecture("test", "scope", sqs)
    assert "mermaid" in diagram.lower() or "flowchart" in diagram.lower(), (
        "architecture 應含 mermaid flowchart"
    )
    assert "flowchart" in diagram or "graph" in diagram, "diagram 應含 flowchart/graph"
    assert len(nodes) >= 3, f"architecture nodes 至少 3 個，實際 {len(nodes)}"

    # APIs
    apis = llm.generate_apis("test", "scope")
    assert len(apis) >= 3, f"APIs 至少 3 個，實際 {len(apis)}"
    for api in apis:
        assert api.endpoint, f"API {api.name} 缺 endpoint"
        assert api.input_desc, f"API {api.name} 缺 input_desc"
        assert api.output_desc, f"API {api.name} 缺 output_desc"
        assert api.error_desc, f"API {api.name} 缺 error_desc"

    # Data Model
    entities, er_diagram = llm.generate_data_model("test", "scope")
    assert len(entities) >= 2, f"entities 至少 2 個，實際 {len(entities)}"
    assert er_diagram.strip(), "ER diagram 不應為空"
    assert "erDiagram" in er_diagram, "ER diagram 應為 Mermaid erDiagram"

    # Milestones
    ms = llm.generate_milestones("test", "scope")
    assert len(ms) >= 3, f"milestones 至少 3 個，實際 {len(ms)}"
    for m in ms:
        assert m.deliverables, f"milestone {m.name} 缺 deliverables"
        assert m.acceptance, f"milestone {m.name} 缺 acceptance"

    # Risks
    risks, open_questions = llm.generate_risks("test", "scope")
    assert len(risks) >= 1, "risks 至少 1 條"
    assert len(open_questions) >= 1, "open questions 至少 1 條"


# ─── Test 7（補充）: ScopeQuestion / APISpec / Entity / Milestone 序列化 ─

def test_dataclass_serialization():
    """ScopeQuestion / APISpec / Entity / Milestone.to_markdown() 應含必要區塊。"""
    # ScopeQuestion
    sq = ScopeQuestion(id="q1", topic="功能邊界", question="包含哪些？", answer="A 和 B")
    sq_md = sq.to_markdown()
    assert "Q1" in sq_md
    assert "功能邊界" in sq_md
    assert "包含哪些？" in sq_md
    assert "A 和 B" in sq_md

    # APISpec
    api = APISpec(
        name="test_api",
        endpoint="POST /x",
        input_desc="in",
        output_desc="out",
        error_desc="err",
    )
    api_md = api.to_markdown()
    assert "test_api" in api_md
    assert "POST /x" in api_md

    # Entity
    ent = Entity(
        name="User",
        fields=[
            {"name": "id", "type": "int", "nullable": "NO", "description": "primary key"},
            {"name": "name", "type": "string", "nullable": "YES", "description": "name"},
        ],
        relations="User has many Order",
    )
    ent_md = ent.to_markdown()
    assert "User" in ent_md
    assert "| `id` |" in ent_md
    assert "User has many Order" in ent_md

    # Milestone
    ms = Milestone(
        name="M1",
        days=3,
        deliverables=["d1", "d2"],
        acceptance=["a1"],
    )
    ms_md = ms.to_markdown()
    assert "M1" in ms_md
    assert "3 天" in ms_md
    assert "d1" in ms_md
    assert "a1" in ms_md


# ─── Test 8（補充）: run_design end-to-end 整合 ─────────────────────

def test_run_design_end_to_end(tmp_path: Path):
    """run_design 完整跑 7 階段，產 DesignDocument + 寫入 design.md / scope.md。"""
    doc = run_design(
        name="e2e-test-feature",
        audience="engineers",
        scope="end-to-end 整合測試",
        output_dir=tmp_path,
        verbose=False,
    )

    assert isinstance(doc, DesignDocument)
    assert doc.name == "e2e-test-feature"
    assert doc.audience == "engineers"
    assert doc.scope == "end-to-end 整合測試"
    assert len(doc.scope_questions) >= 5
    assert len(doc.architecture_nodes) >= 3
    assert len(doc.apis) >= 3
    assert len(doc.entities) >= 2
    assert len(doc.milestones) >= 3
    assert len(doc.risks) >= 1
    assert len(doc.open_questions) >= 1

    # Final Gate 應 PASS
    missing = doc.check_final_gate()
    assert missing == [], f"Final Gate 應 PASS，got: {missing}"

    # 檔案寫入
    target_dir = tmp_path / "e2e-test-feature"
    assert target_dir.exists()
    assert (target_dir / "design.md").exists()
    assert (target_dir / "scope.md").exists()


# ─── Test 9（補充）: run_design 可選旗標 (--with-api / --with-data-model) ─

def test_run_design_optional_outputs(tmp_path: Path):
    """run_design with with_api=True 與 with_data_model=True 應產對應副檔。"""
    run_design(
        name="with-extras",
        audience="pm",
        scope="產出 api.md + data_model.md",
        output_dir=tmp_path,
        with_api=True,
        with_data_model=True,
        verbose=False,
    )

    target_dir = tmp_path / "with-extras"
    assert (target_dir / "design.md").exists()
    assert (target_dir / "api.md").exists()
    assert (target_dir / "data_model.md").exists()

    # 驗證 api.md 內容
    api_text = (target_dir / "api.md").read_text(encoding="utf-8")
    assert "API Design" in api_text
    assert "## " in api_text  # 至少一個 API section

    # 驗證 data_model.md 內容
    dm_text = (target_dir / "data_model.md").read_text(encoding="utf-8")
    assert "Data Model" in dm_text
    assert "Entity:" in dm_text


# ─── Test 10（補充）: _select_template 對 audience 對應正確 ─────────

def test_select_template_audience_mapping():
    """_select_template 應依 audience 回傳正確範本。"""
    assert _select_template("engineers") == "eng-v1"
    assert _select_template("engineer") == "eng-v1"
    assert _select_template("pm") == "pm-v1"
    assert _select_template("executives") == "exec-v1"
    assert _select_template("ceo") == "exec-v1"
    assert _select_template("mixed") == "mixed-v1"
    # 預設：engineers
    assert _select_template("unknown-audience") == "eng-v1"
    assert _select_template("") == "eng-v1"


# ─── Test 11（補充）: _next_version_dir 處理衝突 ───────────────────

def test_next_version_dir_handles_conflicts(tmp_path: Path):
    """_next_version_dir：name 不存在 → 直接用；存在 → name_v1 / name_v2。"""
    # 不存在
    d1 = _next_version_dir(tmp_path, "fresh")
    assert d1 == tmp_path / "fresh"

    # 已存在 → v1
    (tmp_path / "fresh").mkdir()
    d2 = _next_version_dir(tmp_path, "fresh")
    assert d2 == tmp_path / "fresh_v1"

    # 連 v1 也存在 → v2
    (tmp_path / "fresh_v1").mkdir()
    d3 = _next_version_dir(tmp_path, "fresh")
    assert d3 == tmp_path / "fresh_v2"


# ─── Test 12（補充）: run_design empty name/scope 應 raise ───────────

def test_run_design_empty_inputs_raise(tmp_path: Path):
    """run_design 對空 name / scope 應 raise TechnicalDesignError。"""
    with pytest.raises(TechnicalDesignError):
        run_design(
            name="",
            audience="engineers",
            scope="x",
            output_dir=tmp_path,
            verbose=False,
        )

    with pytest.raises(TechnicalDesignError):
        run_design(
            name="valid",
            audience="engineers",
            scope="",
            output_dir=tmp_path,
            verbose=False,
        )

    with pytest.raises(TechnicalDesignError):
        run_design(
            name="   ",
            audience="engineers",
            scope="  ",
            output_dir=tmp_path,
            verbose=False,
        )


# ─── Test 13（補充）: workflow 引用 strategist + topic-research ────

def test_workflow_references_strategist_and_topic_research():
    """workflow 應引用 references/strategist.md 與 workflows/topic-research.md。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert "references/strategist.md" in content, (
        "workflow 應引用 references/strategist.md"
    )
    assert "workflows/topic-research.md" in content, (
        "workflow 應引用 workflows/topic-research.md"
    )


# ─── Test 14（補充）: workflow 含 audience 範本清單 ─────────────────

def test_workflow_contains_audience_templates():
    """workflow §10 應列 audience 範本（engineers / pm / executives / mixed）。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert "engineers" in content, "workflow 應含 engineers audience"
    assert "pm" in content, "workflow 應含 pm audience"
    assert "executives" in content, "workflow 應含 executives audience"
    assert "mixed" in content, "workflow 應含 mixed audience"


# ─── Test 15（補充）: workflow 7 階段流程名稱 ──────────────────────

def test_workflow_lists_7_stages():
    """workflow 應列 7 個階段（Scope / Architecture / API Design / Data Model / Implementation Plan / Review / Output）。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    # 階段關鍵字
    assert "Scope" in content, "workflow 應含 Scope 階段"
    assert "Architecture" in content, "workflow 應含 Architecture 階段"
    assert "API Design" in content, "workflow 應含 API Design 階段"
    assert "Data Model" in content, "workflow 應含 Data Model 階段"
    assert "Implementation Plan" in content, "workflow 應含 Implementation Plan 階段"
    assert "Review" in content, "workflow 應含 Review 階段"
    # 階段編號 4.1 ~ 4.7 應存在
    for stage in ("4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.7"):
        assert stage in content, f"workflow 應有 §{stage} 階段詳述"


# ─── Test 16（補充）: DesignDocument.to_markdown 含 Final Gate checklist ─

def test_design_md_contains_final_gate_checklist(tmp_path: Path):
    """DesignDocument.to_markdown() 應含 Final Gate Checklist 區塊。"""
    doc = run_design(
        name="final-gate-check",
        audience="engineers",
        scope="驗證 final gate checklist",
        output_dir=tmp_path,
        verbose=False,
    )

    md = doc.to_markdown()
    assert "## Final Gate Checklist" in md, "應含 Final Gate Checklist 章節"
    assert "✅" in md or "PASS" in md, "應標示 Final Gate 結果"
    assert "## 1. Overview" in md
    assert "## 6. Risks & Open Questions" in md


# ─── Test 17（補充）: workflow §3 Mermaid 含全部 7 階段節點 ──────

def test_workflow_mermaid_includes_7_stages():
    """workflow §3 的 Mermaid 流程圖應含 7 個主要節點。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    # 抓 §3 的 mermaid 區塊
    m = re.search(r"## 3\. 流程總覽.*?```mermaid\s*\n(?P<body>.*?)\n```", content, re.DOTALL)
    if m is None:
        # fallback: 抓第一個 mermaid 區塊
        m = re.search(r"```mermaid\s*\n(?P<body>.*?)\n```", content, re.DOTALL)
    assert m is not None, "應有 Mermaid 區塊"
    mermaid_body = m.group("body")
    # 應含 7 個階段的關鍵字
    for keyword in ("Scope", "Architecture", "API", "Data Model", "Implementation", "Review", "Output"):
        assert keyword in mermaid_body, f"Mermaid 應含 {keyword} 節點"
