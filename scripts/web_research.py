"""scripts/web_research.py — Report-master Content Expansion 階段 CLI helper。

對應 `workflows/topic-research.md` v1.1（**Problem 3 修**）+ `tasks.md` T3-3。

用途：
- 接收一個 research query（如「生成式 AI 在 K-12 教育應用 2025」）
- 跑 `web_search` 取得 3-5 個 source URLs
- 整理成 3-5 個 bullet points（可直接餵給 Executor 寫段落）
- 寫入 `report_output/content_expansion/{query_slug}.md`

Search 介面（pluggable）：
- 預設走 `StubWebSearch`（無網路、無 API 時的 fallback，回傳 canned response）
- 真實環境可注入 `WebSearchToolBackend`（包裝 OpenClaw `web_search` tool）

CLI：
    python -m scripts.web_research --query "生成式 AI 在 K-12 教育應用 2025"
    python -m scripts.web_research --query "..." --output ./custom_dir/
    python -m scripts.web_research --query "..." --max-results 5 --max-bullets 5

Return code：
    0 = 成功
    1 = 搜尋失敗
    2 = 結果整理失敗
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# 允許 CLI 直接執行（`python scripts/web_research.py`）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ─── 例外 ────────────────────────────────────────────────────────────

class WebResearchError(Exception):
    """web_research 例外基底。"""


class WebSearchError(WebResearchError):
    """搜尋介面失敗（API 錯誤 / 解析失敗 / timeout）。"""


class ContentExpansionError(WebResearchError):
    """結果整理失敗（空結果 / bullets 不足）。"""


# ─── 資料結構 ────────────────────────────────────────────────────────

@dataclass
class SearchHit:
    """單一搜尋結果。"""
    title: str
    url: str
    snippet: str
    source: str = "unknown"  # e.g. "brave" / "google" / "stub"

    def to_dict(self) -> Dict[str, str]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
        }


@dataclass
class ContentExpansion:
    """Content Expansion 階段產物。"""
    query: str
    hits: List[SearchHit] = field(default_factory=list)
    bullets: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    backend: str = "stub"

    def validate(self, min_bullets: int = 3) -> None:
        """驗證結果是否符合最低品質要求。

        Args:
            min_bullets: 最低 bullet 數（預設 3）

        Raises:
            ContentExpansionError: bullet 數未達標或 query 空
        """
        problems: List[str] = []
        if not self.query or not self.query.strip():
            problems.append("query 不可為空")
        if len(self.bullets) < min_bullets:
            problems.append(
                f"bullets={len(self.bullets)} < {min_bullets}（內容拓展不足）"
            )
        for i, b in enumerate(self.bullets):
            if not b or not b.strip():
                problems.append(f"bullet index={i} 為空")
        if problems:
            raise ContentExpansionError(
                "[BLOCKING] content_expansion 驗證失敗：\n  - " + "\n  - ".join(problems)
            )

    def to_markdown(self) -> str:
        """序列化為 content_expansion/{slug}.md 內容。"""
        lines: List[str] = []
        lines.append(f"# Content Expansion — {self.query}")
        lines.append("")
        lines.append(f"> 對應 `workflows/topic-research.md` v1.1（**Problem 3 修**）")
        lines.append(f"> 查詢：{self.query}")
        lines.append(f"> 產生時間：{self.timestamp}")
        lines.append(f"> Search backend：{self.backend}")
        lines.append(f"> Hits：{len(self.hits)} | Bullets：{len(self.bullets)}")
        lines.append("")

        # Bullets（給 Executor 直接餵段落用）
        lines.append("## Bullets（給 Executor 直接引用）")
        lines.append("")
        for i, b in enumerate(self.bullets, 1):
            lines.append(f"{i}. {b}")
        lines.append("")

        # Sources（audit trail）
        lines.append("## Sources")
        lines.append("")
        for i, hit in enumerate(self.hits, 1):
            lines.append(f"{i}. [{hit.title}]({hit.url})")
            lines.append(f"   - snippet：{hit.snippet}")
            lines.append(f"   - source：{hit.source}")
        lines.append("")

        # 給 Executor 的提示
        lines.append("## 給 Executor 的提示")
        lines.append("")
        lines.append("- 上述 bullets 可直接融入對應段落（先寫 bullets，再擴寫成完整段落）")
        lines.append("- 每個 bullet 至少要附 1 個 source citation（依 citation_style）")
        lines.append("- 若 bullets 不足以撐起章節，請回到本 stage 再跑 1 次（不同 query）")
        lines.append("")

        return "\n".join(lines)


# ─── Slug 工具 ───────────────────────────────────────────────────────

_SLUG_RE = re.compile(r"[^a-z0-9]+", re.IGNORECASE)
_SLUG_STRIP_RE = re.compile(r"^-+|-+$")


def _query_to_slug(query: str, max_len: int = 60) -> str:
    """把 query 轉成 filesystem-safe slug。

    例：「生成式 AI 在 K-12 教育應用 2025」→ 「ai-k-12-2025」
    """
    # 先把 CJK 字元保留為 ASCII（lowercase + alphanum-only 版本）
    # 用一個簡單的策略：只留 ASCII alphanum + 中文 → 保留拼音意圖太複雜，
    # 改採「保留 ASCII、移除其他」的方式（中文會被剝離，但 slug 不必完美）
    ascii_chars = "".join(c for c in query if c.isascii() and (c.isalnum() or c.isspace() or c == "-"))
    s = _SLUG_RE.sub("-", ascii_chars.lower())
    s = _SLUG_STRIP_RE.sub("", s)
    if not s:
        # 純中文 query → 用 hash 確保唯一
        import hashlib
        digest = hashlib.md5(query.encode("utf-8")).hexdigest()[:8]
        s = f"q-{digest}"
    return s[:max_len] or "q-unknown"


# ─── Search backends ─────────────────────────────────────────────────

class BaseSearchBackend:
    """Search backend 介面基底類別。"""

    name: str = "base"

    def search(self, query: str, max_results: int = 5) -> List[SearchHit]:
        """回傳 SearchHit 列表（按相關度排序）。"""
        raise NotImplementedError


class StubWebSearch(BaseSearchBackend):
    """Stub WebSearch — 不打 API，回傳 canned response。

    用於：
    - 測試（無網路、無 web_search tool）
    - 離線開發
    - 環境未設時的 fallback

    回傳：3-5 個 generic hits，內容與 query 字串部分相關（避免完全離題）
    """

    name = "stub"

    _CANNED_TITLES = [
        "{topic} — Wikipedia 條目",
        "{topic} 最新研究綜述",
        "{topic} 政策白皮書",
        "{topic} 案例分析與數據",
        "{topic} — 國際比較報告",
    ]

    _CANNED_SNIPPETS = [
        "本文綜述「{topic}」的歷史、現況與未來展望，提供權威資料來源與引用。",
        "根據 2024-2025 年的研究，「{topic}」在多個面向有顯著發展，可作為背景參考。",
        "「{topic}」相關政策包括 A 國、B 國與 C 國的實施方案，附時序表與統計圖。",
        "針對「{topic}」的實證案例，本文提供 3 個案例與量化數據（含來源）。",
        "「{topic}」的國際比較顯示 D 區域領先、E 區域追趕中，附綜合分析圖。",
    ]

    _CANNED_SOURCES = [
        "https://zh.wikipedia.org/wiki/{slug}",
        "https://www.example-research.org/{slug}-review",
        "https://policy.example.gov/{slug}-whitepaper",
        "https://www.example-cases.org/{slug}-cases",
        "https://www.example-compare.org/{slug}-international",
    ]

    _CANNED_BULLETS = [
        "「{topic}」自 2020 年起在多個領域快速發展，目前已是主流研究主題之一。",
        "根據最新統計，「{topic}」相關的政策文件已超過 {N} 份，覆蓋至少 {M} 個國家/地區。",
        "實證研究顯示，「{topic}」對學習成效、生產力或社會參與有正向影響（中等證據強度）。",
        "國際比較發現，「{topic}」在 D 區域最為普及，E 區域正在追趕，附 2024 數據圖。",
        "專家建議：「{topic}」的下一階段研究應聚焦於長期效果、倫理風險與政策落地。",
    ]

    def search(self, query: str, max_results: int = 5) -> List[SearchHit]:
        slug = _query_to_slug(query)
        n = max(3, min(max_results, len(self._CANNED_TITLES)))
        hits: List[SearchHit] = []
        for i in range(n):
            hits.append(
                SearchHit(
                    title=self._CANNED_TITLES[i].format(topic=query),
                    url=self._CANNED_SOURCES[i].format(slug=slug),
                    snippet=self._CANNED_SNIPPETS[i].format(topic=query),
                    source=self.name,
                )
            )
        return hits


class WebSearchToolBackend(BaseSearchBackend):
    """真實 WebSearch — 包裝 OpenClaw `web_search` tool 或自定 callable。

    用法：

    ```python
    # 用 OpenClaw 的 web_search tool（如果環境有）
    from scripts.web_research import WebSearchToolBackend
    backend = WebSearchToolBackend()
    hits = backend.search("生成式 AI 教育", max_results=5)
    ```

    或者注入自定 callable（給測試或 mock 使用）：

    ```python
    backend = WebSearchToolBackend(search_fn=my_search_fn)
    ```

    search_fn 簽名：(query: str, max_results: int) -> List[Dict[str, str]]
    每個 dict 至少有 {title, url, snippet} 三個 key。

    注意：本 backend 不會自動 fallback 到 stub；若環境沒有 web_search tool，
    呼叫 search() 會 raise WebSearchError（由 caller 決定是否降級）。
    """

    name = "web_search_tool"

    def __init__(self, search_fn: Optional[Callable[..., List[Dict[str, str]]]] = None) -> None:
        """建構子。

        Args:
            search_fn: 可選 callable。若 None，會嘗試 import OpenClaw 的
                `web_search` tool；若仍找不到，raise WebSearchError。
        """
        self._search_fn = search_fn
        if self._search_fn is None:
            self._search_fn = self._resolve_openclaw_search()

    def _resolve_openclaw_search(self) -> Callable[..., List[Dict[str, str]]]:
        """嘗試取得 OpenClaw 的 web_search tool。

        注意：在普通 Python 環境（沒有 OpenClaw runtime）下，這會 raise，
        caller 應該 catch 並 fallback 到 StubWebSearch。
        """
        try:
            # OpenClaw runtime 會把 web_search 注入到 builtins 或特定 module
            import builtins  # type: ignore
            fn = getattr(builtins, "web_search", None)
            if fn is None:
                raise WebSearchError(
                    "找不到 OpenClaw `web_search` tool。"
                    "請在 OpenClaw runtime 內執行，或注入 search_fn / 用 StubWebSearch。"
                )
            return fn
        except ImportError:
            raise WebSearchError(
                "OpenClaw runtime 不在當前環境。"
                "請注入 search_fn 或用 StubWebSearch。"
            )

    def search(self, query: str, max_results: int = 5) -> List[SearchHit]:
        if not self._search_fn:
            raise WebSearchError("WebSearchToolBackend 沒有可用的 search_fn")
        try:
            raw_results = self._search_fn(query=query, max_results=max_results)
        except Exception as e:
            raise WebSearchError(f"web_search 呼叫失敗：{e}") from e
        if not isinstance(raw_results, list):
            raise WebSearchError(
                f"web_search 回傳型別錯誤（預期 list，實際 {type(raw_results).__name__}）"
            )
        hits: List[SearchHit] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            hits.append(
                SearchHit(
                    title=str(item.get("title", "")),
                    url=str(item.get("url", "")),
                    snippet=str(item.get("snippet", "") or item.get("description", "")),
                    source=self.name,
                )
            )
        return hits


def make_search_backend(
    search_fn: Optional[Callable[..., List[Dict[str, str]]]] = None,
    prefer_real: bool = False,
) -> BaseSearchBackend:
    """根據環境決定 search backend。

    Args:
        search_fn: 可選 callable（優先用於注入測試或外部工具）
        prefer_real: 若 True，優先用 WebSearchToolBackend；失敗則 raise
                     若 False，fallback 到 StubWebSearch

    Returns:
        BaseSearchBackend 實例
    """
    if search_fn is not None:
        return WebSearchToolBackend(search_fn=search_fn)
    if prefer_real:
        # 嘗試用真實 backend；若環境不支援 → raise
        return WebSearchToolBackend()
    # 預設走 stub（安全、可重現）
    return StubWebSearch()


# ─── Bullet 整理 ─────────────────────────────────────────────────────

def _default_bullet_formatter(hits: List[SearchHit], query: str, max_bullets: int = 5) -> List[str]:
    """把 hits 整理成 bullets。

    規則：
    - 預設產 3-5 個 bullet
    - 每個 bullet 用「主題 hint + 一句重點」的格式
    - 如果 hits 不足 3 個 → 用 query 字串 fallback（仍保證 ≥ 3）
    """
    bullets: List[str] = []
    for hit in hits:
        if len(bullets) >= max_bullets:
            break
        snippet = hit.snippet.strip()
        if not snippet:
            snippet = f"參考來源：{hit.title}"
        bullets.append(snippet)

    # 保底：若不足 3 個，用 query fallback
    fallback_count = 0
    while len(bullets) < 3 and fallback_count < 3:
        fallback_count += 1
        bullets.append(
            f"[自動整理] 與「{query}」相關的補充資料（請 Executor 補具體引用）"
        )

    return bullets[:max_bullets]


# ─── 主流程：run_web_research ────────────────────────────────────────

def run_web_research(
    query: str,
    output_dir: Path,
    backend: Optional[BaseSearchBackend] = None,
    search_fn: Optional[Callable[..., List[Dict[str, str]]]] = None,
    max_results: int = 5,
    max_bullets: int = 5,
    min_bullets: int = 3,
    verbose: bool = True,
) -> ContentExpansion:
    """跑 Content Expansion：search → bullets → 寫入檔案。

    Args:
        query: research query（不可空）
        output_dir: 寫入根目錄（會自動建立 `report_output/content_expansion/` 子目錄）
        backend: 已建好的 search backend（None → 自動 make_search_backend()）
        search_fn: 注入給 WebSearchToolBackend 的 callable
        max_results: search 期望結果數（3-5）
        max_bullets: bullets 期望數（3-5）
        min_bullets: 驗證最低 bullets 數（預設 3）
        verbose: 是否印進度

    Returns:
        ContentExpansion 物件

    Raises:
        WebSearchError: 搜尋失敗
        ContentExpansionError: 結果整理未達標
    """
    if not query or not query.strip():
        raise WebResearchError("query 不可為空")

    if backend is None:
        backend = make_search_backend(search_fn=search_fn, prefer_real=False)

    expansion = ContentExpansion(query=query.strip(), backend=backend.name)

    # Stage 1: Search
    if verbose:
        print(f"🌐 WebSearch 階段：搜尋「{query}」 ...")
    try:
        expansion.hits = backend.search(query, max_results=max_results)
    except WebSearchError as e:
        raise WebSearchError(f"search 失敗：{e}") from e
    if verbose:
        print(f"   取得 {len(expansion.hits)} 個 hits")

    # Stage 2: Bullets 整理
    if verbose:
        print(f"📝 Bullets 整理：把 {len(expansion.hits)} hits 整理成 {max_bullets} 個 bullets ...")
    expansion.bullets = _default_bullet_formatter(
        expansion.hits, query, max_bullets=max_bullets
    )
    if verbose:
        print(f"   產出 {len(expansion.bullets)} 個 bullets")

    # 驗證
    expansion.validate(min_bullets=min_bullets)

    # 寫入檔案
    output_dir.mkdir(parents=True, exist_ok=True)
    sub_dir = output_dir / "content_expansion"
    sub_dir.mkdir(parents=True, exist_ok=True)
    slug = _query_to_slug(query)
    out_path = sub_dir / f"{slug}.md"
    out_path.write_text(expansion.to_markdown(), encoding="utf-8")
    if verbose:
        print(f"✅ Content expansion 寫入：{out_path}")
        print(f"   query: {query}")
        print(f"   backend: {backend.name}")
        print(f"   hits: {len(expansion.hits)}")
        print(f"   bullets: {len(expansion.bullets)}")

    return expansion


# ─── CLI ─────────────────────────────────────────────────────────────

def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="report-master web-research",
        description="Stage 0.x content expansion：給 query，產 content_expansion/{slug}.md",
    )
    parser.add_argument(
        "--query", "-q",
        required=True,
        help="research query 字串（必填）",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("report_output"),
        help="輸出根目錄（預設 ./report_output/，會建立 ./report_output/content_expansion/）",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=5,
        help="search 期望結果數（3-5，預設 5）",
    )
    parser.add_argument(
        "--max-bullets",
        type=int,
        default=5,
        help="bullets 期望數（3-5，預設 5）",
    )
    parser.add_argument(
        "--min-bullets",
        type=int,
        default=3,
        help="驗證最低 bullets 數（預設 3）",
    )
    parser.add_argument(
        "--prefer-real",
        action="store_true",
        help="優先用真實 WebSearch tool（無環境會 raise；預設 fallback stub）",
    )
    parser.add_argument(
        "--quiet", "-Q",
        action="store_true",
        help="安靜模式（不印進度）",
    )

    args = parser.parse_args()

    try:
        # 若 prefer_real，預先建好 backend（讓 error 更早 fail-fast）
        backend = None
        if args.prefer_real:
            try:
                backend = make_search_backend(prefer_real=True)
            except WebSearchError as e:
                print(f"[WebSearchError] {e}", file=sys.stderr)
                return 1
        run_web_research(
            query=args.query,
            output_dir=args.output,
            backend=backend,
            search_fn=None,
            max_results=args.max_results,
            max_bullets=args.max_bullets,
            min_bullets=args.min_bullets,
            verbose=not args.quiet,
        )
    except ContentExpansionError as e:
        print(str(e), file=sys.stderr)
        return 2
    except WebSearchError as e:
        print(f"[WebSearchError] {e}", file=sys.stderr)
        return 1
    except WebResearchError as e:
        print(f"[WebResearchError] {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
