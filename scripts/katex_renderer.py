# katex_renderer.py — KaTeX server-side 預渲染數學公式為 PNG
# 對應 SPEC.md §6.1 R5 + REVIEW.md R5 + shared-standards.md §7
# 用途：掃描 HTML 中的 $...$ 與 $$...$$ 公式，呼叫 katex CLI 預渲染為 PNG，
#       並將 inline / display math 替換為 <img src="...">。
#
# Track B 不自動安裝 katex CLI；遇到缺 CLI 時 raise 明確例外。
#
# 策略：
#   1. 優先用 `katex` CLI（Node.js 套件：katex-cli）
#   2. 備援：Python 的 `katex` 套件（如果有的話）
#   3. 都沒有 → MMDCNotFoundError analog: KaTeXNotFoundError

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Union, List, Tuple

logger = logging.getLogger(__name__)


class KaTeXRenderError(Exception):
    """Base for katex_renderer failures."""


class KaTeXNotFoundError(KaTeXRenderError):
    """katex CLI / package not available."""


# ────────────────────────────────────────────────────────────────────
# KaTeX discovery
# ────────────────────────────────────────────────────────────────────

def find_katex() -> str:
    """Locate katex CLI. Raises KaTeXNotFoundError if missing."""
    # Try the Node.js CLI binary first
    candidates = ["katex", "katex-cli"]
    for c in candidates:
        p = shutil.which(c)
        if p:
            return p
    raise KaTeXNotFoundError(
        "katex CLI 未安裝。請安裝後重跑：\n"
        "  npm install -g katex\n"
        "  # 或：pip install katex  (Python wrapper)\n"
        "（Track B 不自動安裝；fail-fast 提示。）\n"
        "替代方案：保留原始 LaTeX 公式字串，由 docx 編輯器後處理；"
        "或使用 pandoc --mathml（但 weasyprint 不渲染 MathML）。"
    )


# ────────────────────────────────────────────────────────────────────
# Pre-rendering pipeline
# ────────────────────────────────────────────────────────────────────

# Match $$...$$ (display math) first to avoid splitting on $...$
_DISPLAY_MATH_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
# Match $...$ (inline math) — exclude escaped \$
_INLINE_MATH_RE = re.compile(r"(?<!\\)\$([^\$\n]+?)\$(?![\d])")


def _extract_math(html: str) -> List[Tuple[int, int, str, str]]:
    """Return (start, end, kind, tex) tuples for math blocks.

    kind: 'display' ($$...$$) or 'inline' ($...$).
    """
    out: List[Tuple[int, int, str, str]] = []
    # Find display math first (longer match wins)
    display_spans = set()
    for m in _DISPLAY_MATH_RE.finditer(html):
        out.append((m.start(), m.end(), "display", m.group(1).strip()))
        display_spans.add((m.start(), m.end()))
    # Then inline, skipping spans overlapping with display
    for m in _INLINE_MATH_RE.finditer(html):
        ms, me = m.span()
        # Check overlap with any display span
        if any(not (me <= ds or ms >= de) for ds, de in display_spans):
            continue
        out.append((ms, me, "inline", m.group(1).strip()))
    return out


def render_katex_formula(
    tex: str,
    output_png: Union[str, Path],
    display_mode: bool = False,
    katex_path: Optional[str] = None,
) -> Path:
    """Render a single TeX formula to PNG via katex CLI.

    Args:
        tex: LaTeX source (without $ delimiters).
        output_png: path to write PNG.
        display_mode: True for block-level ($$...$$), False for inline ($...$).
        katex_path: override katex binary.

    Returns: Path to output_png.

    Raises:
        KaTeXNotFoundError, KaTeXRenderError.
    """
    katex = katex_path or find_katex()

    out = Path(output_png)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Try katex CLI; different versions have different arg shapes.
    # Strategy: try common flag patterns; if all fail, raise with guidance.
    patterns = [
        [katex, tex, "--output", str(out)],
        [katex, "--input", tex, "--output", str(out)],
        [katex, "-i", tex, "-o", str(out)],
    ]
    last_err = None
    for cmd in patterns:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except FileNotFoundError:
            continue
        if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return out
        last_err = proc.stderr.strip() or proc.stdout.strip()

    raise KaTeXRenderError(
        f"katex CLI 渲染失敗。請確認 CLI 版本與參數格式。\n"
        f"  最後一次錯誤: {last_err or '(no output)'}"
    )


def render_all_in_html(
    html_source: Union[str, Path],
    output_html: Union[str, Path],
    assets_dir: Union[str, Path],
    katex_path: Optional[str] = None,
) -> dict:
    """Render all $...$ and $$...$$ in HTML to PNGs; replace with <img>.

    Args:
        html_source: HTML string OR path.
        output_html: path to write HTML with replaced <img>.
        assets_dir: directory to write PNGs.
        katex_path: override katex binary.

    Returns: dict {rendered: N, replaced: N, paths: [...]}.
    """
    if isinstance(html_source, Path) or (
        isinstance(html_source, str) and Path(html_source).exists()
    ):
        html_text = Path(html_source).read_text(encoding="utf-8")
    else:
        html_text = str(html_source)

    assets_p = Path(assets_dir)
    assets_p.mkdir(parents=True, exist_ok=True)

    blocks = _extract_math(html_text)
    if not blocks:
        out_p = Path(output_html)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(html_text, encoding="utf-8")
        return {"rendered": 0, "replaced": 0, "paths": []}

    paths: List[str] = []
    new_html = html_text
    # Process in reverse to preserve offsets
    for idx in range(len(blocks) - 1, -1, -1):
        start, end, kind, tex = blocks[idx]
        png_name = f"katex_{idx + 1}.png"
        png_path = assets_p / png_name
        render_katex_formula(
            tex, png_path,
            display_mode=(kind == "display"),
            katex_path=katex_path,
        )
        rel_path = f"assets/{png_name}"
        if kind == "display":
            replacement = (
                f'<figure><img src="{rel_path}" alt="equation {idx + 1}" '
                f'style="display:block;margin:auto;max-width:100%;">'
                f'<figcaption class="caption">Equation {idx + 1}</figcaption>'
                f'</figure>'
            )
        else:
            replacement = f'<img src="{rel_path}" alt="inline equation {idx + 1}" style="vertical-align:middle;">'
        new_html = new_html[:start] + replacement + new_html[end:]
        paths.append(str(png_path))

    out_p = Path(output_html)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(new_html, encoding="utf-8")

    return {"rendered": len(paths), "replaced": len(paths), "paths": paths[::-1]}


# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────

def _main() -> int:
    import argparse
    import json
    import sys
    ap = argparse.ArgumentParser(description="Pre-render KaTeX formulas in HTML.")
    ap.add_argument("html", help="Input HTML path")
    ap.add_argument("-o", "--output", required=True, help="Output HTML path")
    ap.add_argument("--assets-dir", default="assets", help="Assets directory")
    args = ap.parse_args()

    try:
        result = render_all_in_html(
            html_source=args.html,
            output_html=args.output,
            assets_dir=args.assets_dir,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (KaTeXRenderError, KaTeXNotFoundError) as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())