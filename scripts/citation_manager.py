"""scripts/citation_manager.py — Report-master 引用管理 workflow CLI helper.

對應 `workflows/generate-citations.md` v1.0 + `tasks.md` T3-6。

用途：
- 接收 source materials list（URLs / PDF / DOCX paths，逗號分隔）
- 接收 citation_style（apa / mla / chicago / ieee / gb-t-7714）
- 跑 5 階段：Extract → Identify → Format → Conflict → Write
- 寫入 `report_output/citations.yaml`（結構化）+ `report_output/references.md`（人類可讀）

LLM 介面：
- 讀 env：LLM_API_URL / LLM_API_KEY / LLM_MODEL（optional）
- 未設定 → 走 StubLLM（回傳 canned citations，給測試與離線使用）
- 設定 → 用 requests 呼叫 OpenAI-compatible chat completions API

CLI：
    python -m scripts.citation_manager --sources "url1,url2" --format apa
    python -m scripts.citation_manager --sources "url1,paper.pdf" --format mla --output ./out/

Return code：
    0 = 成功
    1 = LLM 失敗 / 解析失敗
    2 = 全部 sources 抓取失敗（沒產出任何 candidate）
    3 = 不支援的 citation_style
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# 允許 CLI 直接執行（`python scripts/citation_manager.py`）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ─── 例外 ────────────────────────────────────────────────────────────

class CitationManagerError(Exception):
    """citation_manager 例外基底。"""


class UnsupportedCitationStyleError(CitationManagerError):
    """不支援的 citation_style。"""


class AllSourcesFailedError(CitationManagerError):
    """全部 sources 抓取失敗。"""


class LLMError(CitationManagerError):
    """LLM 呼叫 / 解析失敗。"""


# ─── Citation style 註冊表 ───────────────────────────────────────────

SUPPORTED_STYLES = ("apa", "mla", "chicago", "ieee", "gb-t-7714")


def normalize_style(style: str) -> str:
    """正規化 citation_style 字串（接受大小寫變體、別名）。

    Args:
        style: 使用者輸入（如 "APA" / "apa" / "gb-t-7714" / "gbt7714"）

    Returns:
        正規化後的 style（如 "apa" / "gb-t-7714"）

    Raises:
        UnsupportedCitationStyleError: 未知 style
    """
    s = (style or "").strip().lower()
    s = s.replace("_", "-").replace(" ", "-").replace("/", "-")

    # 別名對映
    aliases = {
        "gbt7714": "gb-t-7714",
        "gbt-7714": "gb-t-7714",
        "gb7714": "gb-t-7714",
        "gb-t-7714": "gb-t-7714",
        "chinese": "gb-t-7714",
        "academic-chinese": "gb-t-7714",
        "ieee": "ieee",
    }
    s = aliases.get(s, s)

    if s not in SUPPORTED_STYLES:
        raise UnsupportedCitationStyleError(
            f"不支援 citation_style='{style}'；支援：{', '.join(SUPPORTED_STYLES)}"
        )
    return s


# ─── 資料結構 ────────────────────────────────────────────────────────

@dataclass
class CitationCandidate:
    """單一 citation candidate（Identify 階段產出）。"""
    id: str
    type: str  # book | article | web | report | misc
    author: List[str] = field(default_factory=list)
    year: str = ""
    title: str = ""
    container: str = ""
    publisher: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    url: str = ""
    doi: str = ""
    accessed: str = ""
    raw_text_excerpt: str = ""
    incomplete: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FormattedCitation:
    """單一 formatted citation（Format 階段產出）。"""
    ref_id: str
    style: str
    text: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CitationNotes:
    """generate-citations 完整產出（聚合結構）。"""
    citation_style: str
    sources_input: int
    candidates_found: int = 0
    candidates: List[CitationCandidate] = field(default_factory=list)
    formatted: List[FormattedCitation] = field(default_factory=list)
    merged_count: int = 0
    errors: List[Dict[str, str]] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def after_merge(self) -> int:
        return len(self.candidates)

    # ─── 序列化 ─────────────────────────────────────────────────────

    def to_yaml_dict(self) -> Dict[str, Any]:
        """序列化為 citations.yaml 結構（會被 PyYAML 序列化）。"""
        return {
            "metadata": {
                "citation_style": self.citation_style,
                "sources_input": self.sources_input,
                "candidates_found": self.candidates_found,
                "after_merge": self.after_merge,
                "merged_count": self.merged_count,
                "errors": self.errors,
                "generated_at": self.timestamp,
                "generator": "scripts/citation_manager.py",
            },
            "candidates": [c.to_dict() for c in self.candidates],
            "formatted": [f.to_dict() for f in self.formatted],
        }

    def to_references_md(self) -> str:
        """序列化為 references.md 內容。"""
        lines: List[str] = []
        lines.append("# References")
        lines.append("")
        lines.append(f"> 對應 `workflows/generate-citations.md` v1.0")
        lines.append(f"> 引用格式：{self.citation_style}")
        lines.append(f"> 產生時間：{self.timestamp}")
        lines.append(f"> 來源筆數：{self.sources_input}（合併後 {self.after_merge}）")
        lines.append("")

        # 依 style 排序
        sorted_formatted = self._sort_formatted()

        lines.append("---")
        lines.append("")
        for i, fc in enumerate(sorted_formatted, 1):
            # APA / MLA / Chicago / GBT 7714：作者姓字母序（已由 _sort 處理）
            # IEEE：依出現順序
            prefix = f"[{i}] " if self.citation_style == "ieee" else ""
            lines.append(f"{prefix}{fc.text}")
            lines.append("")

        # 給 Executor 的指引
        lines.append("---")
        lines.append("")
        lines.append("## 給 Executor 的指引")
        lines.append("")
        lines.append("- 在每節 HTML 內文需引用時，用 pandoc-native 腳註語法 `^[ref_id]`（如 `^[ref_001]`）")
        lines.append("- `ref_001` 對應到本檔第一條")
        lines.append(f"- 完整 metadata 在 `citations.yaml`（給 Stage 3 pandoc --citeproc 用）")
        lines.append("- 若 `^[ref_001]` 在 pandoc 轉檔時解析失敗，檢查 ref_id 是否在 `citations.yaml` 的 `candidates[].id` 中")
        lines.append("")

        # 錯誤區塊（若有）
        if self.errors:
            lines.append("---")
            lines.append("")
            lines.append("## 抓取/解析錯誤")
            lines.append("")
            for err in self.errors:
                lines.append(f"- **{err.get('source', '?')}**: {err.get('reason', '?')}")
            lines.append("")

        return "\n".join(lines)

    def _sort_formatted(self) -> List[FormattedCitation]:
        """依 citation_style 排序。

        - IEEE：保持原序（出現順序）
        - 其他：依作者姓字母序（中文用 ref_id 當 tie-breaker）
        """
        if self.citation_style == "ieee":
            return list(self.formatted)

        # 建立 ref_id → candidate 對映
        cand_map = {c.id: c for c in self.candidates}

        def sort_key(fc: FormattedCitation) -> Tuple[str, str]:
            cand = cand_map.get(fc.ref_id)
            if not cand or not cand.author:
                return ("zzzzz", fc.ref_id)
            first_author = cand.author[0]
            return (first_author.lower(), fc.ref_id)

        return sorted(self.formatted, key=sort_key)


# ─── LLM 介面（stub + real） ────────────────────────────────────────

class BaseLLM:
    """LLM 介面基底類別。"""

    def identify_candidates(self, normalized_md: str, source_url: str) -> List[CitationCandidate]:
        """從 normalized.md 找出 citation candidates。"""
        raise NotImplementedError


class StubLLM(BaseLLM):
    """Stub LLM — 不打 API，回傳 canned response。

    用於：
    - 測試（無網路）
    - 離線開發
    - 環境未設 LLM_API_URL / LLM_API_KEY 時的 fallback

    Stub 行為：
    - 從 normalized.md 抓 1-3 個 URL（若有）
    - 從 normalized.md 抓年份（4 位數 19xx/20xx）
    - 從 normalized.md 抓 DOI
    - 用 1 筆 canned reference（"Brown et al. 2020"）作 fallback
    - 保證至少回傳 1 個 candidate
    """

    _CANNED_AUTHORS = ["Brown, T. B.", "Mann, B.", "Ryder, N.", "Subbiah, M."]
    _CANNED_TITLE = "Language models are few-shot learners"
    _CANNED_CONTAINER = "Advances in Neural Information Processing Systems"
    _CANNED_YEAR = "2020"

    def identify_candidates(self, normalized_md: str, source_url: str) -> List[CitationCandidate]:
        candidates: List[CitationCandidate] = []

        # 1. 從文字抓 URL
        urls = re.findall(r"https?://[^\s\)\]\"\'<>]+", normalized_md)
        unique_urls: List[str] = []
        for u in urls:
            u = u.rstrip(".,;:!?")
            if u not in unique_urls and u != source_url:
                unique_urls.append(u)

        # 2. 從文字抓年份
        years = re.findall(r"\b(19|20)\d{2}\b", normalized_md)
        unique_years = sorted(set(years))[:2]  # 最多 2 個不同年份

        # 3. 從文字抓 DOI
        dois = re.findall(r"10\.\d{4,}/\S+", normalized_md)
        unique_dois = [d.rstrip(".,;") for d in dois][:2]

        # 4. 用找到的 metadata 拼 candidate；若都沒有，用 canned
        if unique_urls or unique_years or unique_dois:
            for i in range(min(3, max(1, len(unique_urls) + len(unique_dois)))):
                cand = CitationCandidate(
                    id="",  # 由 caller 重新編號（run_citations 會用 global counter）
                    type="article",
                    author=list(self._CANNED_AUTHORS[:2]) if i == 0 else [f"Author{i+1}, A."],
                    year=unique_years[0] if unique_years else self._CANNED_YEAR,
                    title=f"[STUB] Citation {i+1} extracted from {source_url[:60]}",
                    container=self._CANNED_CONTAINER,
                    volume=str(30 + i),
                    issue="",
                    pages="1877-1901" if i == 0 else "",
                    url=unique_urls[i] if i < len(unique_urls) else source_url,
                    doi=unique_dois[i] if i < len(unique_dois) else "",
                    accessed=datetime.now().strftime("%Y-%m-%d"),
                    raw_text_excerpt=normalized_md[:200].replace("\n", " "),
                    incomplete=False,
                )
                candidates.append(cand)
        else:
            # 全 canned（保證 ≥ 1 個）
            candidates.append(
                CitationCandidate(
                    id="",  # 由 caller 重新編號
                    type="article",
                    author=list(self._CANNED_AUTHORS),
                    year=self._CANNED_YEAR,
                    title=self._CANNED_TITLE,
                    container=self._CANNED_CONTAINER,
                    volume="33",
                    issue="",
                    pages="1877-1901",
                    url=source_url or "https://example.com",
                    doi="",
                    accessed=datetime.now().strftime("%Y-%m-%d"),
                    raw_text_excerpt="[STUB canned] GPT-3 paper (Brown et al. 2020)",
                    incomplete=False,
                )
            )

        return candidates


class HTTPLLM(BaseLLM):
    """真實 LLM — 透過 HTTP 呼叫 OpenAI-compatible chat completions API。

    環境變數：
        LLM_API_URL   — e.g. https://api.openai.com/v1/chat/completions
        LLM_API_KEY   — e.g. sk-xxxxx
        LLM_MODEL     — e.g. gpt-4o-mini（optional，預設 gpt-4o-mini）
        LLM_TIMEOUT   — 逾時秒數（optional，預設 30）

    注意：若環境無 `requests` 套件 → raise LLMError
    """

    DEFAULT_MODEL = "gpt-4o-mini"
    DEFAULT_TIMEOUT = 30

    def __init__(self) -> None:
        self.api_url = os.environ.get("LLM_API_URL", "")
        self.api_key = os.environ.get("LLM_API_KEY", "")
        self.model = os.environ.get("LLM_MODEL", self.DEFAULT_MODEL)
        try:
            self.timeout = int(os.environ.get("LLM_TIMEOUT", str(self.DEFAULT_TIMEOUT)))
        except ValueError:
            self.timeout = self.DEFAULT_TIMEOUT

    def _call(self, prompt: str) -> str:
        try:
            import requests  # type: ignore
        except ImportError as e:
            raise LLMError(
                "需要 `requests` 套件才能呼叫 HTTP LLM；請 `pip install requests`"
            ) from e

        if not self.api_url or not self.api_key:
            raise LLMError(
                "LLM_API_URL / LLM_API_KEY 未設定；請設定環境變數或走 StubLLM"
            )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是一個引用識別助理。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = requests.post(
                self.api_url, json=payload, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
        except Exception as e:
            raise LLMError(f"HTTP 呼叫失敗：{e}") from e

        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except (KeyError, ValueError, IndexError) as e:
            raise LLMError(f"回應解析失敗：{e}") from e

    def identify_candidates(self, normalized_md: str, source_url: str) -> List[CitationCandidate]:
        prompt = (
            f"你是引用識別助理。給定以下文件內容，找出所有「被引用的文獻」。\n\n"
            f"來源 URL：{source_url}\n\n"
            f"文件內容（前 2000 字）：\n{normalized_md[:2000]}\n\n"
            f"輸出格式（YAML）：\n```yaml\ncandidates:\n"
            f"  - id: ref_001\n"
            f"    type: article\n"
            f"    author: [\"Lin, C.-Y.\"]\n"
            f"    year: \"2023\"\n"
            f"    title: \"...\"\n"
            f"```\n"
        )
        raw = self._call(prompt)
        return self._parse_yaml(raw)

    def _parse_yaml(self, raw: str) -> List[CitationCandidate]:
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise LLMError("需要 PyYAML 才能解析 LLM 輸出") from e

        m = re.search(r"```yaml\s*\n(.*?)```", raw, re.DOTALL)
        if not m:
            raise LLMError(f"LLM 輸出找不到 YAML 區塊：{raw[:200]}")
        try:
            data = yaml.safe_load(m.group(1))
        except Exception as e:
            raise LLMError(f"YAML 解析失敗：{e}") from e

        out: List[CitationCandidate] = []
        for i, item in enumerate(data.get("candidates", []), 1):
            out.append(
                CitationCandidate(
                    id=str(item.get("id", f"ref_{i:03d}")),
                    type=str(item.get("type", "misc")),
                    author=list(item.get("author", []) or []),
                    year=str(item.get("year", "")),
                    title=str(item.get("title", "")),
                    container=str(item.get("container", "")),
                    publisher=str(item.get("publisher", "")),
                    volume=str(item.get("volume", "")),
                    issue=str(item.get("issue", "")),
                    pages=str(item.get("pages", "")),
                    url=str(item.get("url", "")),
                    doi=str(item.get("doi", "")),
                    accessed=str(item.get("accessed", "")),
                    raw_text_excerpt=str(item.get("raw_text_excerpt", ""))[:200],
                    incomplete=bool(item.get("incomplete", False)),
                )
            )
        return out


def make_llm() -> BaseLLM:
    """根據環境變數決定 LLM 實作。"""
    api_url = os.environ.get("LLM_API_URL", "")
    api_key = os.environ.get("LLM_API_KEY", "")
    if api_url and api_key:
        return HTTPLLM()
    return StubLLM()


# ─── Extract 階段 ───────────────────────────────────────────────────

def extract_source(
    source: str,
    output_dir: Path,
    llm: BaseLLM,
    verbose: bool = True,
) -> Tuple[Optional[str], List[CitationCandidate], Optional[Dict[str, str]]]:
    """Extract + Identify 一個 source：抓文字 + 找 candidates。

    Args:
        source: URL 或檔案路徑
        output_dir: 寫入 _sources/ 子目錄
        llm: LLM 實例
        verbose: 是否印進度

    Returns:
        (normalized_md, candidates, error)
        - normalized_md: 抓下來的 Markdown 文字（None 若失敗）
        - candidates: 識別出的 citation candidates（失敗時為空 list）
        - error: 錯誤資訊 dict（成功時為 None）
    """
    sources_dir = output_dir / "_sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    source_id = f"source_{abs(hash(source)) % 10000:04d}"
    source_path = sources_dir / f"{source_id}.md"

    # 1. 判斷 source 類型
    if source.startswith("http://") or source.startswith("https://"):
        # URL
        try:
            from scripts.source_to_md.url_to_md import convert as url_convert
            url_convert(source, source_path)
        except ImportError:
            error = {"source": source, "reason": "url_to_md 不可用（缺 requests）"}
            return None, [], error
        except Exception as e:
            error = {"source": source, "reason": f"URL 抓取失敗：{type(e).__name__}: {e}"}
            if verbose:
                print(f"   ❌ {source[:60]}: {error['reason']}")
            return None, [], error
    else:
        # 檔案
        p = Path(source)
        if not p.exists():
            error = {"source": source, "reason": "檔案不存在"}
            if verbose:
                print(f"   ❌ {source}: 檔案不存在")
            return None, [], error

        try:
            if p.suffix.lower() == ".pdf":
                from scripts.source_to_md.pdf_to_md import convert as pdf_convert
                pdf_convert(p, source_path)
            elif p.suffix.lower() in (".docx", ".doc"):
                from scripts.source_to_md.docx_to_md import convert as docx_convert
                docx_convert(p, source_path)
            elif p.suffix.lower() in (".md", ".markdown", ".txt"):
                # 直接複製
                source_path.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                error = {"source": source, "reason": f"不支援的副檔名：{p.suffix}"}
                if verbose:
                    print(f"   ❌ {source}: {error['reason']}")
                return None, [], error
        except Exception as e:
            error = {"source": source, "reason": f"轉檔失敗：{type(e).__name__}: {e}"}
            if verbose:
                print(f"   ❌ {source}: {error['reason']}")
            return None, [], error

    # 2. 讀 normalized.md
    if not source_path.exists():
        error = {"source": source, "reason": "轉檔後檔案不存在"}
        return None, [], error

    try:
        normalized_md = source_path.read_text(encoding="utf-8")
    except Exception as e:
        error = {"source": source, "reason": f"讀檔失敗：{e}"}
        return None, [], error

    # 3. 呼叫 LLM 找 candidates
    try:
        candidates = llm.identify_candidates(normalized_md, source)
    except LLMError as e:
        error = {"source": source, "reason": f"LLM 失敗：{e}"}
        if verbose:
            print(f"   ⚠️  {source}: LLM 失敗 → {e}")
        return normalized_md, [], error

    if verbose:
        print(f"   ✅ {source[:60]} → {len(candidates)} candidates")

    return normalized_md, candidates, None


# ─── Format 階段 ───────────────────────────────────────────────────

def _join_authors_apa(authors: List[str]) -> str:
    """APA: 'Last, F.', 'Last, F.', & 'Last, F.'"""
    if not authors:
        return ""
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]}, & {authors[1]}"
    return ", ".join(authors[:-1]) + f", & {authors[-1]}"


def _join_authors_mla(authors: List[str]) -> str:
    """MLA: 'Last, First' and 'First Last'"""
    if not authors:
        return ""
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]}, and {authors[1]}"
    return f"{authors[0]}, et al."


def _format_apa(c: CitationCandidate) -> str:
    """APA 7th: Author, A. A. (Year). Title. Container, Vol(Issue), pages. URL"""
    parts: List[str] = []
    auth_str = _join_authors_apa(c.author)
    if auth_str:
        parts.append(f"{auth_str} ")
    if c.year:
        parts.append(f"({c.year}). ")
    if c.title:
        title = c.title
        if c.type in ("article", "web"):
            parts.append(f"{title}. ")
        else:
            parts.append(f"*{title}*. ")
    if c.container:
        parts.append(f"*{c.container}*")
        if c.volume:
            parts.append(f", *{c.volume}*")
            if c.issue:
                parts.append(f"({c.issue})")
        if c.pages:
            parts.append(f", {c.pages}")
        parts.append(". ")
    if c.publisher and c.type == "book":
        parts.append(f"{c.publisher}. ")
    if c.doi:
        parts.append(f"https://doi.org/{c.doi}")
    elif c.url:
        parts.append(c.url)
    return "".join(parts).strip()


def _format_mla(c: CitationCandidate) -> str:
    """MLA 9th: Author. 'Title.' Container, vol. X, no. Y, Year, pp. ZZ-ZZ."""
    parts: List[str] = []
    auth_str = _join_authors_mla(c.author)
    if auth_str:
        parts.append(f"{auth_str}. ")
    if c.title:
        if c.type in ("article", "web"):
            parts.append(f'"{c.title}." ')
        else:
            parts.append(f"*{c.title}*. ")
    if c.container:
        parts.append(f"*{c.container}*")
        if c.volume:
            parts.append(f", vol. {c.volume}")
        if c.issue:
            parts.append(f", no. {c.issue}")
        if c.year:
            parts.append(f", {c.year}")
        if c.pages:
            parts.append(f", pp. {c.pages}")
        parts.append(". ")
    elif c.year:
        parts.append(f"{c.year}. ")
    if c.publisher and c.type == "book":
        parts.append(f"{c.publisher}. ")
    if c.url:
        parts.append(c.url)
    return "".join(parts).strip()


def _format_chicago(c: CitationCandidate) -> str:
    """Chicago 17th (notes-bibliography): Author. 'Title.' Container Vol, no. Issue (Year): pages."""
    parts: List[str] = []
    auth_str = _join_authors_mla(c.author)  # Chicago 同 MLA
    if auth_str:
        parts.append(f"{auth_str}. ")
    if c.title:
        if c.type in ("article", "web"):
            parts.append(f'"{c.title}." ')
        else:
            parts.append(f"*{c.title}*. ")
    if c.container:
        parts.append(f"*{c.container}*")
        if c.volume:
            parts.append(f" {c.volume}")
        if c.issue:
            parts.append(f", no. {c.issue}")
        if c.year:
            parts.append(f" ({c.year})")
        if c.pages:
            parts.append(f": {c.pages}")
        parts.append(". ")
    if c.publisher and c.type == "book":
        parts.append(f"{c.publisher}. ")
    if c.url:
        parts.append(c.url)
    return "".join(parts).strip()


def _format_ieee(c: CitationCandidate) -> str:
    """IEEE: [N] F. Last, 'Title,' Container, vol. X, no. Y, pp. ZZ, Year. URL"""
    # IEEE 由 CitationNotes 統一加 [N] 編號，這裡只產本文
    parts: List[str] = []
    if c.author:
        # IEEE: "F. Last"
        initials_last: List[str] = []
        for a in c.author:
            # "Last, F." → "F. Last"
            if "," in a:
                last, _, first = a.partition(",")
                first = first.strip().rstrip(".")
                initials_last.append(f"{first}. {last.strip()}")
            else:
                initials_last.append(a)
        if len(initials_last) > 2:
            auth_str = f"{initials_last[0]} et al."
        else:
            auth_str = " and ".join(initials_last)
        parts.append(f"{auth_str}, ")
    if c.title:
        if c.type in ("article", "web"):
            parts.append(f'"{c.title}," ')
        else:
            parts.append(f"*{c.title}*, ")
    if c.container:
        parts.append(f"*{c.container}*")
        if c.volume:
            parts.append(f", vol. {c.volume}")
        if c.issue:
            parts.append(f", no. {c.issue}")
        if c.pages:
            parts.append(f", pp. {c.pages}")
        if c.year:
            parts.append(f", {c.year}")
        parts.append(". ")
    if c.url:
        parts.append(c.url)
    return "".join(parts).strip()


def _format_gbt7714(c: CitationCandidate) -> str:
    """學術中文 GB/T 7714: 作者. 題名[J/M/N]. 刊名, 年, 卷(期): 頁碼."""
    type_map = {"article": "J", "book": "M", "web": "N", "report": "R", "misc": "Z"}
    parts: List[str] = []
    if c.author:
        parts.append(", ".join(c.author))
        parts.append(". ")
    if c.title:
        parts.append(c.title)
        t = type_map.get(c.type, "Z")
        parts.append(f"[{t}]. ")
    if c.container:
        parts.append(f"{c.container}")
        if c.year:
            parts.append(f", {c.year}")
        if c.volume:
            parts.append(f", {c.volume}")
            if c.issue:
                parts.append(f"({c.issue})")
        if c.pages:
            parts.append(f": {c.pages}")
        parts.append(". ")
    if c.url:
        parts.append(c.url)
    return "".join(parts).strip()


_FORMATTERS = {
    "apa": _format_apa,
    "mla": _format_mla,
    "chicago": _format_chicago,
    "ieee": _format_ieee,
    "gb-t-7714": _format_gbt7714,
}


def format_citation(c: CitationCandidate, style: str) -> str:
    """依指定 style 格式化 candidate。"""
    fmt_fn = _FORMATTERS.get(style)
    if fmt_fn is None:
        raise UnsupportedCitationStyleError(f"不支援 style: {style}")
    return fmt_fn(c)


# ─── Conflict 階段 ─────────────────────────────────────────────────

def _normalize_for_dedup(s: str) -> str:
    """正規化字串用於去重比對（小寫、移除標點、合併空白）。"""
    s = s.lower()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def deduplicate_candidates(
    candidates: List[CitationCandidate],
) -> Tuple[List[CitationCandidate], int]:
    """合併重複的 candidates。

    Args:
        candidates: 候選清單

    Returns:
        (deduplicated, merged_count)
        - deduplicated: 合併後的清單（保持原順序）
        - merged_count: 被合併掉的數量
    """
    if not candidates:
        return candidates, 0

    seen: Dict[Tuple[str, str], CitationCandidate] = {}
    out: List[CitationCandidate] = []
    merged = 0

    for c in candidates:
        # 用 (title, year) 當 dedup key
        key = (
            _normalize_for_dedup(c.title),
            _normalize_for_dedup(c.year),
        )
        # 若 title 為空，退到 (author, year)
        if not key[0]:
            key = (
                _normalize_for_dedup(c.author[0] if c.author else ""),
                _normalize_for_dedup(c.year),
            )

        if key in seen:
            # 合併：保留 metadata 最完整者（欄位最多非空）
            existing = seen[key]
            existing_score = sum(1 for v in asdict(existing).values() if v and v not in ([], ""))
            new_score = sum(1 for v in asdict(c).values() if v and v not in ([], ""))
            if new_score > existing_score:
                # 採用新 candidate（保留舊 id 避免破壞引用）
                c.id = existing.id
                seen[key] = c
                # 替換 out 中的對應 entry
                for i, e in enumerate(out):
                    if e.id == existing.id:
                        out[i] = c
                        break
            merged += 1
        else:
            seen[key] = c
            out.append(c)

    return out, merged


# ─── 主流程：run ────────────────────────────────────────────────────

def run_citations(
    sources: List[str],
    output_dir: Path,
    citation_style: str = "apa",
    llm: Optional[BaseLLM] = None,
    verbose: bool = True,
) -> CitationNotes:
    """跑 5 階段，產 CitationNotes 並寫入 citations.yaml + references.md。

    Args:
        sources: source list（URLs 或檔案路徑）
        output_dir: 寫入目錄（會自動建立 report_output/ 子目錄）
        citation_style: apa / mla / chicago / ieee / gb-t-7714
        llm: LLM 實例（None → 自動 make_llm()）
        verbose: 是否印進度

    Returns:
        CitationNotes 物件

    Raises:
        UnsupportedCitationStyleError: 不支援的 style
        AllSourcesFailedError: 全部 sources 抓取失敗
        LLMError: LLM 失敗
    """
    if not sources:
        raise CitationManagerError("sources 不可為空")

    style = normalize_style(citation_style)

    if llm is None:
        llm = make_llm()

    notes = CitationNotes(
        citation_style=style,
        sources_input=len(sources),
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    # Stage 1: Extract + Identify
    if verbose:
        print(f"🔍 Extract + Identify 階段：{len(sources)} 個 sources")
    all_candidates: List[CitationCandidate] = []
    success_count = 0
    next_id = [0]  # global counter (list for closure mutability)

    for src in sources:
        _, cands, err = extract_source(src, output_dir, llm, verbose=verbose)
        if err is None:
            success_count += 1
            # 重新編號（避免 StubLLM 撞 id）
            for c in cands:
                next_id[0] += 1
                c.id = f"ref_{next_id[0]:03d}"
                all_candidates.append(c)
        else:
            notes.errors.append(err)

    if verbose:
        print(f"   抓取成功：{success_count}/{len(sources)}")
        print(f"   候選總數：{len(all_candidates)}")

    if success_count == 0:
        raise AllSourcesFailedError(
            f"全部 {len(sources)} 個 sources 抓取失敗；錯誤詳見 citations.yaml.errors"
        )

    notes.candidates_found = len(all_candidates)

    # Stage 2: Conflict (dedup)
    if verbose:
        print(f"🔀 Conflict 階段：偵測重複 ...")
    deduped, merged = deduplicate_candidates(all_candidates)
    notes.merged_count = merged
    notes.candidates = deduped
    if verbose:
        print(f"   合併後：{len(deduped)} 個 references（移除 {merged} 筆重複）")

    # Stage 3: Format
    if verbose:
        print(f"🎨 Format 階段：套用 {style} 格式 ...")
    formatted: List[FormattedCitation] = []
    for cand in deduped:
        try:
            text = format_citation(cand, style)
            formatted.append(FormattedCitation(ref_id=cand.id, style=style, text=text))
        except UnsupportedCitationStyleError:
            raise
        except Exception as e:
            # 個別 candidate 失敗不 BLOCKING；記 log
            formatted.append(FormattedCitation(
                ref_id=cand.id, style=style,
                text=f"[FORMAT ERROR: {e}] {cand.title}"
            ))
    notes.formatted = formatted
    if verbose:
        print(f"   {len(formatted)} formatted strings")

    # Stage 4: Write
    if verbose:
        print(f"📝 Write 階段：寫入 citations.yaml + references.md ...")

    citations_path = output_dir / "citations.yaml"
    references_path = output_dir / "references.md"

    # 寫 citations.yaml
    try:
        import yaml  # type: ignore
        with citations_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                notes.to_yaml_dict(),
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            )
    except ImportError:
        # 沒有 PyYAML → 寫成 JSON 變體（仍可讀）
        import json
        citations_path.write_text(
            json.dumps(notes.to_yaml_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # 寫 references.md
    references_path.write_text(notes.to_references_md(), encoding="utf-8")

    if verbose:
        print(f"✅ Citations 寫入：{citations_path}")
        print(f"   來源筆數：{notes.sources_input}")
        print(f"   候選數：{notes.candidates_found}")
        print(f"   合併後：{notes.after_merge}")
        print(f"   引用格式：{notes.citation_style}")
        print()
        print(f"✅ References 寫入：{references_path}")
        print(f"   條目數：{len(notes.formatted)}")

    return notes


# ─── CLI ─────────────────────────────────────────────────────────────

def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="report-master citation-manager",
        description="Stage 1 引用管理：給 sources + format，產 citations.yaml + references.md",
    )
    parser.add_argument(
        "--sources", "-s",
        required=True,
        help="source list（URLs 或檔案路徑，逗號分隔；必填）",
    )
    parser.add_argument(
        "--format", "-f",
        default="apa",
        help="引用格式：apa / mla / chicago / ieee / gb-t-7714（預設 apa）",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("report_output"),
        help="輸出目錄（預設 ./report_output/）",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="安靜模式（不印進度）",
    )

    args = parser.parse_args()

    # 解析 sources（逗號分隔）
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]

    try:
        run_citations(
            sources=sources,
            output_dir=args.output,
            citation_style=args.format,
            verbose=not args.quiet,
        )
    except UnsupportedCitationStyleError as e:
        print(f"[UnsupportedCitationStyleError] {e}", file=sys.stderr)
        return 3
    except AllSourcesFailedError as e:
        print(f"[AllSourcesFailedError] {e}", file=sys.stderr)
        return 2
    except LLMError as e:
        print(f"[LLMError] {e}", file=sys.stderr)
        return 1
    except CitationManagerError as e:
        print(f"[CitationManagerError] {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
