"""scripts/source_to_md/docx_to_md.py — DOCX → Markdown 轉換。

對應 `tasks.md` T1-4：
- 使用 mammoth（DOCX → HTML，再轉 Markdown）
- 保留 heading 層級、列表、表格、粗體、斜體
- 透過 md_normalizer 統一格式

公開 API：
  convert(source: Path, output_path: Path) -> Path
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Union

# 允許 CLI 直接執行
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    import mammoth
except ImportError as e:  # pragma: no cover
    raise ImportError("缺少 mammoth，請先 `pip install mammoth`") from e

try:
    import importlib.metadata as _metadata
    MAMMOTH_VERSION = _metadata.version("mammoth")
except Exception:
    MAMMOTH_VERSION = "unknown"

from scripts.source_to_md.md_normalizer import normalize


class _HTMLToMarkdown(HTMLParser):
    """極簡 HTML → Markdown 轉換器。

    mammoth 會把 DOCX 轉成簡化 HTML，本類別負責轉回 Markdown：
    - <h1>–<h6> → # ## ### ...
    - <p> → 段落
    - <strong>/<b> → **bold**
    - <em>/<i> → *italic*
    - <ul>/<ol>/<li> → 列表
    - <table>/<tr>/<th>/<td> → Markdown table
    - <br> → 換行
    """

    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []
        self.in_table = False
        self.current_row: List[str] = []
        self.current_cell: List[str] = []
        self.list_stack: List[str] = []  # "ul" or "ol"
        self.list_index_stack: List[int] = []
        self.skip_data = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        tag = tag.lower()
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
        elif tag == "ul":
            self.list_stack.append("ul")
            self.list_index_stack.append(0)
        elif tag == "ol":
            self.list_stack.append("ol")
            self.list_index_stack.append(0)
        elif tag == "li":
            depth = len(self.list_stack)
            indent = "  " * (depth - 1)
            self.list_index_stack[-1] += 1
            if self.list_stack[-1] == "ol":
                self.parts.append(f"\n{indent}{self.list_index_stack[-1]}. ")
            else:
                self.parts.append(f"\n{indent}- ")
        elif tag == "table":
            self.in_table = True
            self.parts.append("\n\n")
        elif tag == "tr":
            self.current_row = []
        elif tag in ("th", "td"):
            self.current_cell = []
        elif tag in ("img",):
            src = dict(attrs).get("src", "")
            alt = dict(attrs).get("alt", "")
            self.parts.append(f"\n![{alt}]({src})\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append("\n")
        elif tag == "p":
            self.parts.append("\n")
        elif tag in ("strong", "b"):
            self.parts.append("**")
        elif tag in ("em", "i"):
            self.parts.append("*")
        elif tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop()
                self.list_index_stack.pop()
            self.parts.append("\n")
        elif tag == "tr":
            # 結束一個 row → 加到 parts
            self.parts.append("| " + " | ".join(self.current_row) + " |\n")
        elif tag == "table":
            self.in_table = False
            # 加分隔行（需要先有一個 row 才能算欄數，簡化：加預設 --- 列）
            self.parts.append("\n")
        elif tag in ("th", "td"):
            self.current_row.append("".join(self.current_cell).strip())

    def handle_data(self, data: str) -> None:
        if self.in_table and (self.current_cell is not None or self.current_row is not None):
            # 表格 cell 收集
            if hasattr(self, "_current_cell_active"):
                self.current_cell.append(data)
            else:
                self.current_cell.append(data)
        else:
            self.parts.append(data)

    def get_markdown(self) -> str:
        text = "".join(self.parts)
        # 簡單清理：多空行合併
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _html_to_markdown(html: str) -> str:
    """HTML → Markdown。"""
    parser = _HTMLToMarkdown()
    parser.feed(html)
    return parser.get_markdown()


def convert(
    source: Union[str, Path],
    output_path: Union[str, Path],
) -> Path:
    """DOCX → Markdown。

    Args:
        source: DOCX 檔案路徑
        output_path: 輸出的 .md 檔案路徑

    Returns:
        輸出的 .md 路徑
    """
    src = Path(source)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        raise FileNotFoundError(f"找不到 DOCX：{src}")

    with open(src, "rb") as f:
        result = mammoth.convert_to_html(f)
        html = result.value
        messages = result.messages

    md = _html_to_markdown(html)

    # 加上 frontmatter + 警告註解
    warnings = "\n".join(
        f"<!-- mammoth: {m.type}: {m.message} -->"
        for m in messages
    )
    frontmatter = (
        "---\n"
        f"source_type: docx\n"
        f"source_file: {src.name}\n"
        f"converter: docx_to_md.py (mammoth {MAMMOTH_VERSION})\n"
        "---\n"
    )
    content = frontmatter + md
    if warnings:
        content += "\n\n" + warnings
    content = normalize(content)
    out.write_text(content, encoding="utf-8")

    return out


# ─── CLI ─────────────────────────────────────────────────────────────

def _cli() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="docx-to-md",
        description="DOCX → Markdown 轉換",
    )
    parser.add_argument("source", type=Path, help="DOCX 輸入檔")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="輸出 .md 檔（預設 <source>.md）",
    )
    args = parser.parse_args()

    output = args.output or args.source.with_suffix(".md")
    try:
        result = convert(args.source, output)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2
    print(f"✅ 已轉換：{result}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
