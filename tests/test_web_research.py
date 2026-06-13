# test_web_research.py — scripts/web_research.py + workflows/topic-research.md (Content Expansion stage) 測試
# 對應 tasks.md Phase 3 缺陷 #3
# 涵蓋：
#   1. StubWebSearch 預設行為：3-5 hits / 3-5 bullets
#   2. CLI 不 crash + 寫入 report_output/content_expansion/{slug}.md
#   3. 自定 search_fn（mock）能注入 WebSearchToolBackend
#   4. 結果驗證：query 空 / bullets < 3 → BLOCKING
#   5. workflow 文件更新：topic-research.md v1.1 含 research_content 階段
#   6. workflow 文件更新：引用 web_research.py / web_search

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from scripts.web_research import (
    BaseSearchBackend,
    ContentExpansion,
    ContentExpansionError,
    SearchHit,
    StubWebSearch,
    WebResearchError,
    WebSearchError,
    WebSearchToolBackend,
    _default_bullet_formatter,
    _query_to_slug,
    make_search_backend,
    run_web_research,
)


# ─── Fixtures ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_MD = PROJECT_ROOT / "workflows" / "topic-research.md"


# ─── Test 1: StubWebSearch 預設行為 ────────────────────────────────

def test_stub_search_returns_3_to_5_hits():
    """StubWebSearch.search() 應回傳 3-5 個 hits（保證 ≥ 3）。"""
    backend = StubWebSearch()
    hits = backend.search("生成式 AI 在教育", max_results=5)
    assert 3 <= len(hits) <= 5, f"hits 應 3-5，實際 {len(hits)}"
    for hit in hits:
        assert isinstance(hit, SearchHit)
        assert hit.title, "title 不可空"
        assert hit.url, "url 不可空"
        assert hit.snippet, "snippet 不可空"
        assert hit.source == "stub"


def test_stub_search_clamps_to_min_3():
    """即使 max_results=1，StubWebSearch 也至少回傳 3 個（保底）。"""
    backend = StubWebSearch()
    hits = backend.search("test", max_results=1)
    assert len(hits) >= 3, f"hits 至少 3 個（保底），實際 {len(hits)}"


# ─── Test 2: bullet formatter ──────────────────────────────────────

def test_bullet_formatter_produces_3_to_5_bullets():
    """_default_bullet_formatter 應產 3-5 個 bullets（query 字串相關）。"""
    backend = StubWebSearch()
    hits = backend.search("AI 教育", max_results=5)
    bullets = _default_bullet_formatter(hits, "AI 教育", max_bullets=5)
    assert 3 <= len(bullets) <= 5
    # Bullets 應與 query 主題相關
    assert all(isinstance(b, str) and b.strip() for b in bullets)


def test_bullet_formatter_fallback_when_too_few_hits():
    """若 hits 不足 → fallback 用 query 補到 ≥ 3 個 bullets。"""
    hits = [SearchHit(title="x", url="http://x", snippet="single", source="stub")]
    bullets = _default_bullet_formatter(hits, "my topic", max_bullets=5)
    assert len(bullets) >= 3, f"保底 3 bullets，實際 {len(bullets)}"


# ─── Test 3: ContentExpansion 驗證 ─────────────────────────────────

def test_content_expansion_validation_raises_on_empty_query():
    """空 query 應 raise ContentExpansionError。"""
    ce = ContentExpansion(query="", bullets=["a", "b", "c"])
    with pytest.raises(ContentExpansionError):
        ce.validate()


def test_content_expansion_validation_raises_on_too_few_bullets():
    """bullets < 3 應 raise。"""
    ce = ContentExpansion(query="x", bullets=["only one"])
    with pytest.raises(ContentExpansionError) as exc:
        ce.validate()
    assert "BLOCKING" in str(exc.value)


def test_content_expansion_validation_passes_with_3_bullets():
    """3 個 bullets 應通過驗證。"""
    ce = ContentExpansion(query="x", bullets=["a", "b", "c"])
    ce.validate()  # 不 raise


def test_content_expansion_validation_raises_on_empty_bullet():
    """空字串 bullet 應 raise。"""
    ce = ContentExpansion(query="x", bullets=["a", "", "c"])
    with pytest.raises(ContentExpansionError):
        ce.validate()


# ─── Test 4: 序列化 ────────────────────────────────────────────────

def test_content_expansion_markdown_serialization():
    """ContentExpansion.to_markdown() 應含 bullets + sources + 給 Executor 的提示。"""
    ce = ContentExpansion(
        query="AI 教育",
        hits=[
            SearchHit(title="標題 1", url="https://x", snippet="snippet 1"),
            SearchHit(title="標題 2", url="https://y", snippet="snippet 2"),
        ],
        bullets=["重點 1", "重點 2", "重點 3"],
        backend="stub",
    )
    md = ce.to_markdown()
    assert "## Bullets（給 Executor 直接引用）" in md
    assert "## Sources" in md
    assert "## 給 Executor 的提示" in md
    assert "重點 1" in md
    assert "https://x" in md
    assert "AI 教育" in md


# ─── Test 5: slug 工具 ─────────────────────────────────────────────

def test_query_to_slug_for_ascii():
    """ASCII query → kebab-case slug。"""
    assert _query_to_slug("Hello World") == "hello-world"
    assert _query_to_slug("Foo Bar Baz 2025") == "foo-bar-baz-2025"
    assert _query_to_slug("  trim  me  ") == "trim-me"


def test_query_to_slug_for_pure_chinese_falls_back_to_hash():
    """純中文 query（無 ASCII）→ 用 hash fallback（保證唯一 + filesystem-safe）。"""
    slug = _query_to_slug("生成式人工智慧教育應用")
    # 完全無 ASCII → 走 hash fallback
    assert slug.startswith("q-"), f"純中文 query 應走 hash fallback，實際：{slug}"
    assert len(slug) >= 4


def test_query_to_slug_for_mixed_chinese_keeps_ascii():
    """中英混合 query → 保留 ASCII portion（中文被剝離、ASCII 變 kebab-case）。"""
    slug = _query_to_slug("生成式 AI 教育")
    # "AI" 是 ASCII → 保留
    assert "ai" in slug, f"中英混合 query 應保留 ASCII，實際：{slug}"


# ─── Test 6: 自定 search_fn 注入 ───────────────────────────────────

def test_web_search_tool_backend_with_injected_fn():
    """WebSearchToolBackend 接受注入的 search_fn（mock-friendly）。"""
    mock_results = [
        {"title": "Mock 1", "url": "https://mock1", "snippet": "mock snippet 1"},
        {"title": "Mock 2", "url": "https://mock2", "snippet": "mock snippet 2"},
        {"title": "Mock 3", "url": "https://mock3", "snippet": "mock snippet 3"},
    ]

    def mock_search_fn(query: str, max_results: int = 5) -> List[Dict[str, str]]:
        return mock_results[:max_results]

    backend = WebSearchToolBackend(search_fn=mock_search_fn)
    hits = backend.search("any query", max_results=3)
    assert len(hits) == 3
    assert hits[0].title == "Mock 1"
    assert hits[0].source == "web_search_tool"


def test_make_search_backend_default_returns_stub():
    """預設 make_search_backend() 應回傳 StubWebSearch（無 web_search tool 環境）。"""
    backend = make_search_backend()
    assert isinstance(backend, StubWebSearch)


def test_make_search_backend_with_search_fn_returns_real_backend():
    """注入 search_fn → 回傳 WebSearchToolBackend。"""
    backend = make_search_backend(search_fn=lambda q, m: [])
    assert isinstance(backend, WebSearchToolBackend)


# ─── Test 7: end-to-end run_web_research ───────────────────────────

def test_run_web_research_end_to_end(tmp_path: Path):
    """給 query → 產 content_expansion/{slug}.md，hits ≥ 3、bullets ≥ 3。"""
    ce = run_web_research(
        query="生成式 AI 在 K-12 教育應用 2025",
        output_dir=tmp_path,
        max_results=5,
        max_bullets=5,
        min_bullets=3,
        verbose=False,
    )

    assert isinstance(ce, ContentExpansion)
    assert len(ce.hits) >= 3
    assert len(ce.bullets) >= 3

    # 檔案寫入
    out_path = tmp_path / "content_expansion" / "ai-k-12-2025.md"
    assert out_path.exists(), f"沒產出 {out_path}"
    content = out_path.read_text(encoding="utf-8")
    assert "生成式 AI 在 K-12 教育應用 2025" in content
    assert "## Bullets（給 Executor 直接引用）" in content
    assert "## Sources" in content


def test_run_web_research_empty_query_raises(tmp_path: Path):
    """空 query 應 raise WebResearchError。"""
    with pytest.raises(WebResearchError):
        run_web_research(query="", output_dir=tmp_path, verbose=False)


# ─── Test 8: CLI smoke ─────────────────────────────────────────────

def test_web_research_cli_runs(tmp_path: Path):
    """`python -m scripts.web_research --query "test" --output <tmp>` 不 crash。"""
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.web_research",
            "--query", "test topic",
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

    # 應有 content_expansion/{slug}.md
    ce_dir = tmp_path / "content_expansion"
    assert ce_dir.exists()
    md_files = list(ce_dir.glob("*.md"))
    assert len(md_files) == 1
    content = md_files[0].read_text(encoding="utf-8")
    assert "test topic" in content
    assert "## Bullets" in content


# ─── Test 9: workflow topic-research.md v1.1 含 research_content 階段 ───

def test_workflow_md_version_updated_to_v11():
    """workflows/topic-research.md 應升級到 v1.1（含 Content Expansion 階段）。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    # v1.1 或以上
    m = re.match(r"\A---\s*\n(?P<yaml>.*?)\n---", content, re.DOTALL)
    assert m is not None
    fm = yaml.safe_load(m.group("yaml"))
    assert fm.get("version", "").startswith("1.1"), (
        f"workflow version 應為 1.1.x，實際：{fm.get('version')}"
    )


def test_workflow_md_references_web_research():
    """workflow 應引用 scripts/web_research.py + web_search。"""
    content = WORKFLOW_MD.read_text(encoding="utf-8")
    assert "scripts/web_research.py" in content or "scripts.web_research" in content, (
        "workflow 應引用 scripts/web_research.py"
    )
    assert "web_search" in content, "workflow 應提及 web_search 工具"
    assert "content_expansion" in content or "Content Expansion" in content, (
        "workflow 應含 Content Expansion 階段名稱"
    )
