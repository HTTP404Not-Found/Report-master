"""scripts/bundle.py — Report-master D1 Stage 2.x Bundle。

對應 `tasks.md` D1 Step 6：把 `section_*.html` 合併成單一 `report_final.html`。

CLI：
  python -m scripts.bundle \\
      --input examples/output_1/ \\
      --output examples/output_1/report_final.html
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ─── 主要 API ───────────────────────────────────────────────────────

def bundle_sections(
    input_dir: Path,
    output_path: Path,
    *,
    title: str = "Report Bundle",
) -> Path:
    """把 input_dir 內 `section_*.html` 合併成單一 output_path。

    合併策略：
      1. 找所有 `section_N.html`（按 N 排序）
      2. 取第一個檔案的 `<head>...</head>` 與 CSS
      3. 抽每個檔案的 body 內容（去掉 <body>/</body> 標籤）
      4. 用 <hr> 分隔，串成單一 HTML

    Returns:
        output_path（已寫入）
    """
    if not input_dir.exists():
        raise FileNotFoundError(f"找不到輸入目錄：{input_dir}")
    input_dir = input_dir.resolve()

    section_files = sorted(
        input_dir.glob("section_*.html"),
        key=_section_sort_key,
    )
    if not section_files:
        raise FileNotFoundError(
            f"找不到 section_*.html 在 {input_dir}"
        )

    bodies: List[str] = []
    for f in section_files:
        text = f.read_text(encoding="utf-8")
        body = _extract_body(text)
        bodies.append(body)

    # head 用第一個檔案
    first_text = section_files[0].read_text(encoding="utf-8")
    head = _extract_head(first_text, title=title)

    html = head + "\n" + "\n<hr>\n".join(bodies) + "\n</body></html>\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


# ─── 內部 helper ───────────────────────────────────────────────────

def _section_sort_key(p: Path) -> int:
    """section_5.html → 5；其他給高序避免搶前面。"""
    m = re.match(r"section_(\d+)\.html$", p.name)
    if m:
        return int(m.group(1))
    return 9999


def _extract_body(text: str) -> str:
    """抽 body 內容（去掉 <body>...</body> 標籤）。"""
    start = text.find("<body>")
    end = text.rfind("</body>")
    if start == -1 or end == -1:
        return text
    return text[start + len("<body>"):end].strip()


def _extract_head(text: str, *, title: str) -> str:
    """抽 head 區（包含 <html lang=...> 到 </head> 標籤）+ 開新 body。"""
    head_end = text.find("</head>")
    if head_end == -1:
        return (
            '<!DOCTYPE html>\n<html lang="zh-TW">\n'
            '<head><meta charset="UTF-8">'
            f'<title>{title}</title></head>\n<body>\n'
        )
    head = text[: head_end + len("</head>")]
    # 把 <title>...</title> 換成指定 title
    head = re.sub(
        r"<title>.*?</title>",
        f"<title>{title}</title>",
        head,
        count=1,
        flags=re.DOTALL,
    )
    return head + "\n<body>\n"


# ─── CLI ────────────────────────────────────────────────────────────

def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="report-master bundle",
        description="D1 Stage 2.x Bundle：合併 section_*.html → report_final.html",
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        required=True,
        help="輸入目錄（含 section_*.html）",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        required=True,
        help="輸出 report_final.html 路徑",
    )
    parser.add_argument(
        "--title", "-t",
        default="Report Bundle",
        help="HTML <title>（預設 'Report Bundle'）",
    )
    args = parser.parse_args()

    try:
        out = bundle_sections(
            input_dir=args.input,
            output_path=args.output,
            title=args.title,
        )
    except FileNotFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    size = out.stat().st_size
    print(f"✅ bundle 已寫入：{out} ({size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
