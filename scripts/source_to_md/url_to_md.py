"""scripts/source_to_md/url_to_md.py — URL → Markdown 轉換。

對應 `tasks.md` T1-5：
- 使用 requests 抓 HTML
- 用 readability-like 啟發式萃取主要內容（title + 段落）
- 保留 heading 層級（依 h1-h6 標籤）
- 透過 md_normalizer 統一格式

公開 API：
  convert(url: str, output_path: Path) -> Path

注意：
- 不處理 JS 渲染（weasyprint 風格相同限制）
- 不下載外部圖片，僅記錄 img src
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional, Tuple, Union

# 允許 CLI 直接執行
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    import requests
except ImportError as e:  # pragma: no cover
    raise ImportError("缺少 requests，請先 `pip install requests`") from e

try:
    import importlib.metadata as _metadata
    REQUESTS_VERSION = _metadata.version("requests")
except Exception:
    REQUESTS_VERSION = "unknown"

from scripts.source_to_md.md_normalizer import normalize


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; ReportMaster/0.1; +https://github.com/HTTP404Not-Found/Report-master)"
)
DEFAULT_TIMEOUT = 30  # seconds


class _MainContentExtractor(HTMLParser):
    """啟發式 HTML → Markdown 轉換器。

    規則：
    - <title> → 收集到 self.title
    - <h1>–<h6> → # ## ### ...
    - <p> → 段落
    - <ul>/<ol>/<li> → 列表
    - <a href="..."> → [text](url)
    - <img src="..."> → ![alt](src)
    - <strong>/<b> → **bold**
    - <em>/<i> → *italic*
    - <code> → `code`
    - <pre> → ```code block```
    - <br> → 換行
    - <script>/<style>/<noscript> → 跳過
    """

    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []
        self.title: Optional[str] = None
        self.skip_depth = 0
        self.in_pre = False
        self.list_stack: List[str] = []
        self.list_index_stack: List[int] = []
        self._in_title = False
        self._pending_link: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        tag = tag.lower()
        attrs_dict = dict(attrs)
        if tag in ("script", "style", "noscript"):
            self.skip_depth += 1
            return
        if self.skip_depth > 0:
            return
        if tag == "title":
            self._in_title = True
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            self.parts.append(f"\n{'#' * level} ")
        elif tag == "p":
            self.parts.append("\n\n")
        elif tag == "br":
            self.parts.append("\n")
        elif tag in ("strong", "b"):
            self.parts.append("**")
        elif tag in ("em", "i"):
            self.parts.append("*")
        elif tag == "code" and not self.in_pre:
            self.parts.append("`")
        elif tag == "pre":
            self.in_pre = True
            self.parts.append("\n```\n")
        elif tag == "ul":
            self.list_stack.append("ul")
            self.list_index_stack.append(0)
            self.parts.append("\n")
        elif tag == "ol":
            self.list_stack.append("ol")
            self.list_index_stack.append(0)
            self.parts.append("\n")
        elif tag == "li":
            depth = len(self.list_stack)
            indent = "  " * (depth - 1)
            self.list_index_stack[-1] += 1
            if self.list_stack[-1] == "ol":
                self.parts.append(f"\n{indent}{self.list_index_stack[-1]}. ")
            else:
                self.parts.append(f"\n{indent}- ")
        elif tag == "a":
            href = attrs_dict.get("href", "")
            if href:
                self.parts.append("[")
                self._pending_link = href
            else:
                self._pending_link = None
        elif tag == "img":
            src = attrs_dict.get("src", "")
            alt = attrs_dict.get("alt", "")
            self.parts.append(f"![{alt}]({src})")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("script", "style", "noscript"):
            if self.skip_depth > 0:
                self.skip_depth -= 1
            return
        if self.skip_depth > 0:
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p"):
            self.parts.append("\n")
        elif tag in ("strong", "b"):
            self.parts.append("**")
        elif tag in ("em", "i"):
            self.parts.append("*")
        elif tag == "code" and not self.in_pre:
            self.parts.append("`")
        elif tag == "pre":
            self.in_pre = False
            self.parts.append("\n```\n")
        elif tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop()
                self.list_index_stack.pop()
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n")
        elif tag == "a":
            if self._pending_link:
                self.parts.append(f"]({self._pending_link})")
                self._pending_link = None

    def handle_data(self, data: str) -> None:
        if self.skip_depth > 0:
            return
        if self._in_title:
            self.title = (self.title or "") + data
            return
        self.parts.append(data)

    def get_markdown(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _fetch_html(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """抓 HTML（帶 User-Agent、timeout、編碼推斷）。"""
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    # 編碼推斷：先試 charset，最後 fallback utf-8
    if resp.encoding and resp.encoding.lower() not in ("iso-8859-1",):
        return resp.text
    # fallback 用 apparent_encoding
    resp.encoding = resp.apparent_encoding
    return resp.text


def convert(
    url: str,
    output_path: Union[str, Path],
    timeout: int = DEFAULT_TIMEOUT,
) -> Path:
    """URL → Markdown。

    Args:
        url: 來源 URL（http/https）
        output_path: 輸出的 .md 檔案路徑
        timeout: 抓取 timeout（秒）

    Returns:
        輸出的 .md 路徑
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    html = _fetch_html(url, timeout=timeout)

    parser = _MainContentExtractor()
    parser.feed(html)
    md_body = parser.get_markdown()
    title = (parser.title or url).strip()

    frontmatter = (
        "---\n"
        f"source_type: url\n"
        f"source_url: {url}\n"
        f"title: \"{title}\"\n"
        f"converter: url_to_md.py (requests {REQUESTS_VERSION})\n"
        "---\n"
    )
    content = frontmatter + "\n# " + title + "\n\n" + md_body
    content = normalize(content)
    out.write_text(content, encoding="utf-8")

    return out


# ─── CLI ─────────────────────────────────────────────────────────────

def _cli() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="url-to-md",
        description="URL → Markdown 轉換",
    )
    parser.add_argument("url", help="來源 URL")
    parser.add_argument(
        "-o", "--output", type=Path, required=True,
        help="輸出 .md 檔",
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT,
        help=f"timeout 秒數（預設 {DEFAULT_TIMEOUT}）",
    )
    args = parser.parse_args()

    try:
        result = convert(args.url, args.output, timeout=args.timeout)
    except requests.RequestException as e:
        print(f"[ERROR] 抓取失敗：{e}", file=sys.stderr)
        return 2
    print(f"✅ 已轉換：{result}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
