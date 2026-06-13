# html_to_docx_direct.py — HTML → DOCX via python-docx (平行路徑 / 控制力最高)
# 對應 SPEC.md §3.1 ADR "DOCX 平行路徑"
# 狀態：STUB（先寫函式簽名 + docstring，等基礎路徑通了再實作）
#
# 此路徑設計給政府公文 / 學術投稿對格式極敏感的場景：完全控制字體、段落、
# 編號與 styles.xml。開發量最大；目前僅保留接口與 NotImplementedError，
# 不阻擋基礎路徑 (pandoc) 上線。

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union


class HTMLToDOCXDirectError(Exception):
    """Base for html_to_docx_direct failures."""


def html_to_docx_direct(
    html_source: Union[str, Path],
    output_docx: Union[str, Path],
    *,
    cjk_font: str = "標楷體",
    latin_font: str = "Times New Roman",
    body_size_pt: int = 12,
    h1_size_pt: int = 18,
    h2_size_pt: int = 16,
    h3_size_pt: int = 14,
    line_spacing: float = 1.5,
    page_size: str = "A4",
    margins_cm: Optional[dict] = None,
) -> Path:
    """Convert HTML → DOCX using python-docx (high-control path).

    This function is currently NOT IMPLEMENTED. See TODO below.

    Args:
        html_source: HTML string OR path to HTML file.
        output_docx: path to write DOCX.
        cjk_font: CJK font name (locked: 標楷體).
        latin_font: Latin font name (locked: Times New Roman).
        body_size_pt: body text size in points.
        h1_size_pt / h2_size_pt / h3_size_pt: heading sizes.
        line_spacing: 1.0 / 1.5 / 2.0.
        page_size: A4 / Letter / Legal / JIS-B5.
        margins_cm: dict with top/bottom/left/right in cm.

    Returns: Path to output_docx.

    Raises:
        NotImplementedError: always (until this path is fully built).
    """
    raise NotImplementedError(
        "html_to_docx_direct 為平行路徑，目前僅保留接口。\n"
        "主路徑請用 scripts.html_to_docx.html_to_docx (pandoc)。\n"
        "若需啟用此路徑，請先實作以下 TODO：\n"
        "  TODO: 解析 HTML 子集（<h1-6> / <p> / <table> / <img> / <ul>/<ol>/<li> / <sup> / <a>）\n"
        "  TODO: 建立 python-docx Document 並設定 styles.xml 字體與大小\n"
        "  TODO: 處理章節編號（手動寫入；對齊 shared-standards.md §5）\n"
        "  TODO: 處理表格（border-collapse + cell padding）\n"
        "  TODO: 處理註腳（pandoc  ^[note] 語法無法直接轉；需解析 HTML <sup><aside>）\n"
        "  TODO: 處理交叉引用（<a href=\"#anchor\"> 對應 bookmark）\n"
        "  預估工作量：L（> 1 天）"
    )


# ────────────────────────────────────────────────────────────────────
# CLI (always exits non-zero with explanation)
# ────────────────────────────────────────────────────────────────────

def _main() -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(
        description="[STUB] Convert HTML to DOCX via python-docx (parallel path)."
    )
    ap.add_argument("html", help="Input HTML")
    ap.add_argument("-o", "--output", required=True, help="Output DOCX")
    args = ap.parse_args()

    try:
        html_to_docx_direct(args.html, args.output)
        return 0
    except NotImplementedError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())