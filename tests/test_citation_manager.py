"""tests/test_citation_manager.py — scripts/citation_manager.py + workflows/generate-citations.md 單元測試。

DoD 對應 `tasks.md` T3-6：
1. 載入 `workflows/generate-citations.md` frontmatter 不 crash
2. Mermaid flowchart 存在（regex ` ```mermaid `）
3. `citation_manager.py` CLI `--sources "..." --format apa` 不 crash
4. (補充) normalize_style 對已知/未知 style 正確行為
5. (補充) deduplicate_candidates 正確合併重複
6. (補充) format_citation 5 種 style 都能產字串
7. (補充) end-to-end 整合：2 URLs → 產 citations.yaml + references.md
8. (補充) workflow 引用既有資源（strategist / footnote_manager / source_to_md）
9. (補充) 不支援 citation_style 拋 UnsupportedCitationStyleError
10. (補充) 全部 sources 失敗拋 AllSourcesFailedError
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.citation_manager import (
    AllSourcesFailedError,
    CitationCandidate,
    CitationManagerError,
    CitationNotes,
    FormattedCitation,
    StubLLM,
    SUPPORTED_STYLES,
    UnsupportedCitationStyleError,
    deduplicate_candidates,
    format_citation,
    normalize_style,
    run_citations,
)


# ─── Fixtures ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_MD = PROJECT_ROOT / "workflows" / "generate-citations.md"
STRATEGIST_MD = PROJECT_ROOT / "references" / "strategist.md"
EXECUTOR_MD = PROJECT_ROOT / "references" / "executor-base.md"
FOOTNOTE_MGR_PY = PROJECT_ROOT / "scripts" / "footnote_manager.py"


# ─── Test 1（必要）: 載入 workflows/generate-citations.md frontmatter 不 crash ─

def test_workflow_md_frontmatter_loads():
    """載入 workflows/generate-citations.md frontmatter 不 crash + 必要欄位齊備。"""
    assert WORKFLOW_MD.exists(), f"找不到 {WORKFLOW_MD}"

    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert content.startswith("---\n"), "generate-citations.md 應以 frontmatter 開頭"

    # 用正則抓 frontmatter
    m = re.match(r"\A---\s*\n(?P<yaml>.*?)\n---", content, re.DOTALL)
    assert m is not None, "frontmatter 區塊未正確閉合"

    fm = yaml.safe_load(m.group("yaml"))
    assert isinstance(fm, dict), "frontmatter 應為 mapping"

    # 必要欄位
    assert fm.get("name") == "generate-citations", "name 應為 'generate-citations'"
    assert fm.get("description"), "description 必填"
    assert len(fm.get("description", "")) >= 50, "description 太短"
    assert fm.get("version") in ("1.0", 1.0), "version 應為 1.0"

    # 檔案行數 DoD 1
    line_count = len(content.splitlines())
    assert line_count > 100, f"workflow 應 > 100 行，目前 {line_count}"


# ─── Test 2（必要）: Mermaid flowchart 存在 ─────────────────────────

def test_workflow_md_contains_mermaid():
    """workflows/generate-citations.md 內含 Mermaid flowchart（regex `` ```mermaid ``）。"""
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


# ─── Test 3（必要）: citation_manager.py CLI 不 crash ───────────────

def test_citation_manager_cli_runs(tmp_path: Path):
    """`python -m scripts.citation_manager --sources "..." --format apa` 不 crash。"""
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.citation_manager",
            "--sources", "https://example.com",
            "--format", "apa",
            "--output", str(tmp_path),
            "--quiet",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"CLI 失敗（returncode={result.returncode}）\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # 應有 citations.yaml + references.md
    citations_path = tmp_path / "citations.yaml"
    references_path = tmp_path / "references.md"
    assert citations_path.exists(), f"沒產出 {citations_path}"
    assert references_path.exists(), f"沒產出 {references_path}"

    # YAML 載入
    data = yaml.safe_load(citations_path.read_text(encoding="utf-8"))
    assert data["metadata"]["citation_style"] == "apa"
    assert data["metadata"]["sources_input"] == 1
    assert len(data["candidates"]) >= 1

    # MD 內容
    md_content = references_path.read_text(encoding="utf-8")
    assert "# References" in md_content
    assert "引用格式：apa" in md_content


# ─── Test 4（補充）: normalize_style 對已知/未知 style 正確行為 ──────

def test_normalize_style_known_and_unknown():
    """normalize_style 應接受已知 style（大小寫、alias）；未知 → raise。"""
    # 已知
    assert normalize_style("APA") == "apa"
    assert normalize_style("apa") == "apa"
    assert normalize_style("MLA") == "mla"
    assert normalize_style("Chicago") == "chicago"
    assert normalize_style("IEEE") == "ieee"
    assert normalize_style("GB/T 7714") == "gb-t-7714"
    assert normalize_style("gbt7714") == "gb-t-7714"
    assert normalize_style("GBT-7714") == "gb-t-7714"
    assert normalize_style("chinese") == "gb-t-7714"

    # 未知
    with pytest.raises(UnsupportedCitationStyleError) as exc_info:
        normalize_style("vancouver")
    assert "vancouver" in str(exc_info.value) or "不支援" in str(exc_info.value)

    with pytest.raises(UnsupportedCitationStyleError):
        normalize_style("")

    # 5 種 style 全列
    assert len(SUPPORTED_STYLES) == 5
    assert "apa" in SUPPORTED_STYLES
    assert "mla" in SUPPORTED_STYLES
    assert "chicago" in SUPPORTED_STYLES
    assert "ieee" in SUPPORTED_STYLES
    assert "gb-t-7714" in SUPPORTED_STYLES


# ─── Test 5（補充）: deduplicate_candidates 正確合併 ────────────────

def test_deduplicate_candidates_merges_duplicates():
    """deduplicate_candidates 應合併 (title, year) 相同的 candidates。"""
    c1 = CitationCandidate(
        id="ref_001", type="article", author=["Lin, C."], year="2023",
        title="Deep learning for citation parsing", url="https://a.com",
    )
    c2 = CitationCandidate(
        id="ref_002", type="article", author=["Lin, C."], year="2023",
        title="Deep learning for citation parsing", url="https://b.com",
    )
    c3 = CitationCandidate(
        id="ref_003", type="article", author=["Wang, M."], year="2022",
        title="Other paper", url="https://c.com",
    )
    deduped, merged = deduplicate_candidates([c1, c2, c3])
    assert len(deduped) == 2, f"合併後應剩 2 筆，實際 {len(deduped)}"
    assert merged == 1, f"應合併 1 筆，實際 {merged}"
    ids = [c.id for c in deduped]
    assert "ref_001" in ids
    assert "ref_003" in ids

    # 空 list 應直接返回
    assert deduplicate_candidates([]) == ([], 0)


# ─── Test 6（補充）: format_citation 5 種 style 都能產字串 ──────────

def test_format_citation_all_styles():
    """format_citation 對 5 種 style 都應產非空字串。"""
    cand = CitationCandidate(
        id="ref_001", type="article",
        author=["Lin, C.-Y.", "Wang, M."],
        year="2023", title="Test paper",
        container="Journal of NLP", volume="12", issue="3", pages="45-67",
        url="https://example.com/article",
        doi="10.1234/jnlp.2023.012",
    )
    for style in SUPPORTED_STYLES:
        text = format_citation(cand, style)
        assert isinstance(text, str), f"{style}: 應為 str"
        assert len(text) > 0, f"{style}: 不應為空"
        # 任何 style 都應包含 author 與 year
        assert "Lin" in text, f"{style}: 應含 author 'Lin'"
        assert "2023" in text, f"{style}: 應含 year '2023'"


# ─── Test 7（補充）: end-to-end 整合測試 ────────────────────────────

def test_run_citations_end_to_end(tmp_path: Path):
    """給 1 URL + 1 本地 .md 檔 → 產 citations.yaml + references.md。

    用 example.com（穩定） + 本地 .md（確定性）作 sources，
    避免依賴外部 flaky 服務。
    """
    # 準備本地 Markdown 來源（取代易壞的外部 URL）
    local_md = tmp_path / "source.md"
    local_md.write_text(
        "---\n"
        "title: \"Test reference source\"\n"
        "---\n\n"
        "# Test Reference Source\n\n"
        "This document cites https://doi.org/10.1234/example.2023 and "
        "Brown, T. B. et al. (2020). 'Language models are few-shot learners', "
        "in Advances in Neural Information Processing Systems, vol. 33.\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "output"

    notes = run_citations(
        sources=[
            "https://example.com",
            str(local_md),
        ],
        output_dir=out_dir,
        citation_style="apa",
        verbose=False,
    )

    # CitationNotes 結構
    assert isinstance(notes, CitationNotes)
    assert notes.citation_style == "apa"
    assert notes.sources_input == 2
    assert len(notes.candidates) >= 2, (
        f"應 ≥ 2 個 candidates（1 URL + 1 local .md），實際 {len(notes.candidates)}"
    )
    assert len(notes.formatted) == len(notes.candidates)

    # 檔案寫入
    citations_path = out_dir / "citations.yaml"
    references_path = out_dir / "references.md"
    assert citations_path.exists()
    assert references_path.exists()

    # citations.yaml 內容
    data = yaml.safe_load(citations_path.read_text(encoding="utf-8"))
    assert data["metadata"]["citation_style"] == "apa"
    assert data["metadata"]["sources_input"] == 2
    assert len(data["candidates"]) >= 2
    assert len(data["formatted"]) >= 2

    # references.md 內容
    md = references_path.read_text(encoding="utf-8")
    assert "# References" in md
    assert "引用格式：apa" in md
    # 所有 ref_id 應被 references.md 引用到或 formatted 列表裡
    for c in notes.candidates:
        assert c.id in md or c.id in [f.ref_id for f in notes.formatted]


# ─── Test 8（補充）: workflow 引用既有資源 ──────────────────────────

def test_workflow_references_existing_assets():
    """workflow 應引用 references/strategist.md + scripts/footnote_manager.py + source_to_md。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    # 引用 references/strategist.md
    assert "references/strategist.md" in content, (
        "workflow 應引用 references/strategist.md"
    )
    # 引用既有 footnote_manager
    assert "footnote_manager" in content, (
        "workflow 應引用既有 footnote_manager 資源"
    )
    # 引用 source_to_md 系列
    assert "source_to_md" in content, (
        "workflow 應引用 source_to_md 系列"
    )


# ─── Test 9（補充）: 不支援 citation_style 拋 UnsupportedCitationStyleError ─

def test_run_citations_unsupported_style_raises(tmp_path: Path):
    """未知 citation_style 應 raise UnsupportedCitationStyleError。"""
    with pytest.raises(UnsupportedCitationStyleError):
        run_citations(
            sources=["https://example.com"],
            output_dir=tmp_path,
            citation_style="vancouver",
            verbose=False,
        )


# ─── Test 10（補充）: 全部 sources 失敗拋 AllSourcesFailedError ─────

def test_run_citations_all_sources_failed_raises(tmp_path: Path):
    """全部 sources 都抓不到時應 raise AllSourcesFailedError。"""
    with pytest.raises(AllSourcesFailedError):
        run_citations(
            sources=["/nonexistent/path/foo.pdf", "/nonexistent/path/bar.docx"],
            output_dir=tmp_path,
            citation_style="apa",
            verbose=False,
        )


# ─── Test 11（補充）: StubLLM 預設行為 ─────────────────────────────

def test_stub_llm_identify_returns_at_least_one():
    """StubLLM.identify_candidates 即使文字空也應回傳 ≥ 1 個 candidate。"""
    llm = StubLLM()
    # 即使空文字
    cands = llm.identify_candidates("", "")
    assert len(cands) >= 1, "空文字也應回傳至少 1 個 canned candidate"
    assert all(c.id == "" for c in cands), "StubLLM 不主動編號（由 caller 編）"
    # 有 metadata 文字
    cands2 = llm.identify_candidates(
        "This paper cites https://doi.org/10.1234/example. Published in 2023.",
        "https://example.com",
    )
    assert len(cands2) >= 1
    assert any(c.url for c in cands2), "應抓到 url"
