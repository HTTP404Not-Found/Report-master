"""scripts/source_to_md/pdf_to_md.py — PDF → Markdown 轉換。

對應 `tasks.md` T1-3：
- 使用 PyMuPDF（fitz）
- 保留 heading 層級（依字體大小推斷）
- 圖片抽出到 <output_dir>/assets/
- 透過 md_normalizer 統一格式

公開 API：
  convert(source: Path, output_path: Path) -> Path
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional, Tuple, Union

# 允許 CLI 直接執行
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    import fitz  # PyMuPDF
except ImportError as e:  # pragma: no cover
    raise ImportError("缺少 PyMuPDF，請先 `pip install pymupdf`") from e

try:
    import importlib.metadata as _metadata
    FITZ_VERSION = _metadata.version("pymupdf")
except Exception:
    FITZ_VERSION = "unknown"

from scripts.source_to_md.md_normalizer import normalize


# Heading 層級判斷（依字體大小粗略分組）
# 中文 PDF 字體大小常見：
#   18pt+ → H1
#   16pt+ → H2
#   14pt+ → H3
HEADING_SIZE_THRESHOLDS = [
    (18.0, 1),
    (16.0, 2),
    (14.0, 3),
]
BODY_SIZE_THRESHOLD = 11.0


def convert(
    source: Union[str, Path],
    output_path: Union[str, Path],
    image_dir: Optional[Union[str, Path]] = None,
) -> Path:
    """PDF → Markdown。

    Args:
        source: PDF 檔案路徑
        output_path: 輸出的 .md 檔案路徑
        image_dir: 圖片輸出目錄（預設 <output_path.parent>/assets/）

    Returns:
        輸出的 .md 路徑
    """
    src = Path(source)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if image_dir is None:
        image_dir = out.parent / "assets"
    img_dir = Path(image_dir)
    img_dir.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        raise FileNotFoundError(f"找不到 PDF：{src}")

    doc = fitz.open(src)
    markdown_lines: List[str] = []
    image_index = 0

    try:
        for page_idx, page in enumerate(doc):
            # 頁面標題
            markdown_lines.append(f"\n<!-- Page {page_idx + 1} -->\n")

            # 取出頁面 blocks（含字體大小、座標）
            blocks = page.get_text("dict")["blocks"]

            for block in blocks:
                if block["type"] == 1:  # 圖片 block
                    # 圖片：抽出到 assets/
                    image_index += 1
                    img_path = img_dir / f"page{page_idx+1}_img{image_index}.png"
                    try:
                        xref = block.get("xref")
                        if xref:
                            pix = fitz.Pixmap(doc, xref)
                            if pix.n - pix.alpha >= 4:  # CMYK
                                pix = fitz.Pixmap(fitz.csRGB, pix)
                            pix.save(str(img_path))
                            markdown_lines.append(
                                f"![{img_path.name}]({img_path.relative_to(out.parent)})"
                            )
                    except Exception as e:
                        markdown_lines.append(
                            f"<!-- 圖片抽出失敗：{e} -->"
                        )
                    continue

                if block["type"] != 0:  # 非文字 block
                    continue

                # 處理文字 lines
                for line in block.get("lines", []):
                    text_parts: List[str] = []
                    max_size = 0.0
                    for span in line.get("spans", []):
                        text_parts.append(span["text"])
                        max_size = max(max_size, span["size"])
                    line_text = "".join(text_parts).strip()
                    if not line_text:
                        continue

                    # 判斷 heading
                    heading_level = _detect_heading_level(max_size)
                    if heading_level:
                        markdown_lines.append(
                            f"{'#' * heading_level} {line_text}"
                        )
                    else:
                        markdown_lines.append(line_text)
                    markdown_lines.append("")  # 段落分隔

        # 加上 frontmatter
        frontmatter = (
            "---\n"
            f"source_type: pdf\n"
            f"source_file: {src.name}\n"
            f"page_count: {len(doc)}\n"
            f"converter: pdf_to_md.py (PyMuPDF {FITZ_VERSION})\n"
            "---\n"
        )

        content = frontmatter + "\n".join(markdown_lines)
        content = normalize(content)
        out.write_text(content, encoding="utf-8")

    finally:
        doc.close()

    return out


def _detect_heading_level(font_size: float) -> Optional[int]:
    """依字體大小回傳 heading 層級（1/2/3）；否則 None。"""
    for threshold, level in HEADING_SIZE_THRESHOLDS:
        if font_size >= threshold:
            return level
    return None


# ─── CLI ─────────────────────────────────────────────────────────────

def _cli() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="pdf-to-md",
        description="PDF → Markdown 轉換",
    )
    parser.add_argument("source", type=Path, help="PDF 輸入檔")
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
