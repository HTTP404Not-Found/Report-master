# toc_generator.py — 目次自動產生 (pandoc --toc)
# 對應 SPEC.md §3.1 + architecture.md §介面定義
# 支援 --toc-depth=N；輸出可嵌入 HTML 或獨立 stub.html

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Union

from scripts.html_to_docx import find_pandoc, PandocNotFoundError, PandocRenderError, HTMLSourceError

logger = logging.getLogger(__name__)


class TOCGeneratorError(Exception):
    """Base for toc_generator failures."""


def generate_toc(
    html_source: Union[str, Path],
    output_html: Optional[Union[str, Path]] = None,
    *,
    toc_depth: int = 3,
    pandoc_path: Optional[str] = None,
) -> str:
    """Generate TOC from HTML using pandoc --toc.

    Strategy: pandoc needs an h1-h6 structure to extract. We pass the HTML through
    pandoc twice:
      1. html → markdown (extracts headings)
      2. markdown → html --toc (inserts TOC block)

    Args:
        html_source: HTML string OR path to HTML file.
        output_html: optional path to write TOC-embedded HTML.
        toc_depth: --toc-depth (1-6, default 3).
        pandoc_path: override pandoc binary path.

    Returns: HTML string with TOC embedded (between <nav id="TOC"> ... </nav>
             inserted right after <body>).

    Raises:
        PandocNotFoundError, PandocRenderError, HTMLSourceError, TOCGeneratorError.
    """
    if not (1 <= toc_depth <= 6):
        raise TOCGeneratorError(f"toc_depth 必須在 1-6 之間，得到 {toc_depth}")

    pandoc = pandoc_path or find_pandoc()

    # Load HTML
    is_path = False
    if isinstance(html_source, Path):
        is_path = True
    elif isinstance(html_source, str):
        if html_source and "\n" not in html_source and "<" not in html_source:
            is_path = True  # candidate; existence validated below

    if is_path:
        html_path = Path(html_source)
        if not html_path.exists():
            raise HTMLSourceError(f"HTML 檔不存在: {html_path}")
        if html_path.stat().st_size == 0:
            raise HTMLSourceError(f"HTML 檔為空: {html_path}")
        with open(str(html_path), encoding="utf-8") as f:
            html_text = f.read()
    else:
        html_text = str(html_source)
        if not html_text or not html_text.strip():
            raise HTMLSourceError("HTML 字串為空")

    # Step 1: HTML → Markdown
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as md_tmp:
        md_path = md_tmp.name

    try:
        proc1 = subprocess.run(
            [pandoc, "-f", "html+raw_html", "-t", "markdown",
             "--wrap=preserve", "-o", md_path],
            input=html_text, capture_output=True, text=True
        )
        if proc1.returncode != 0:
            raise PandocRenderError(f"HTML→Markdown 失敗: {proc1.stderr.strip()}")

        # Step 2: Markdown → HTML with TOC
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as toc_tmp:
            toc_path = toc_tmp.name

        try:
            proc2 = subprocess.run(
                [pandoc, "-f", "markdown", "-t", "html",
                 "--toc", f"--toc-depth={toc_depth}",
                 "--standalone",
                 "-o", toc_path, md_path],
                capture_output=True, text=True
            )
            if proc2.returncode != 0:
                raise PandocRenderError(f"Markdown→HTML --toc 失敗: {proc2.stderr.strip()}")

            with open(toc_path, encoding="utf-8") as f:
                out_html = f.read()

            # Strip <html><head>... wrapper if standalone produced full doc,
            # keep just <nav id="TOC"> block
            toc_block = _extract_toc_block(out_html)
            if not toc_block:
                # Fallback: keep the full standalone output
                toc_block = out_html

            # Inject into original HTML right after <body>
            result = _inject_toc(html_text, toc_block)

            if output_html:
                out_p = Path(output_html)
                out_p.parent.mkdir(parents=True, exist_ok=True)
                out_p.write_text(result, encoding="utf-8")
                logger.info("TOC-embedded HTML written: %s", out_p)

            return result
        finally:
            try:
                Path(toc_path).unlink()
            except OSError:
                pass
    finally:
        try:
            Path(md_path).unlink()
        except OSError:
            pass


def _extract_toc_block(html: str) -> Optional[str]:
    """Extract <nav id=\"TOC\"> ... </nav> block from pandoc's standalone HTML."""
    import re
    m = re.search(r"<nav[^>]*id=[\"']TOC[\"'][^>]*>.*?</nav>", html, re.DOTALL | re.IGNORECASE)
    return m.group(0) if m else None


def _inject_toc(html: str, toc_block: str) -> str:
    """Insert TOC block right after <body> tag.

    If a <nav id="TOC"> already exists, replace it.
    """
    import re
    # If already present, replace
    if re.search(r"<nav[^>]*id=[\"']TOC[\"']", html, re.IGNORECASE):
        return re.sub(
            r"<nav[^>]*id=[\"']TOC[\"'][^>]*>.*?</nav>",
            toc_block,
            html,
            count=1,
            flags=re.DOTALL | re.IGNORECASE,
        )
    # Insert after <body ...>
    m = re.search(r"<body[^>]*>", html, re.IGNORECASE)
    if m:
        idx = m.end()
        return html[:idx] + "\n" + toc_block + "\n" + html[idx:]
    # Fallback: prepend
    return toc_block + "\n" + html


# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────

def _main() -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="Generate TOC (pandoc --toc).")
    ap.add_argument("html", help="Input HTML path")
    ap.add_argument("-o", "--output", default=None, help="Output HTML path (optional)")
    ap.add_argument("--toc-depth", type=int, default=3, help="TOC depth (1-6, default 3)")
    args = ap.parse_args()

    try:
        result = generate_toc(args.html, args.output, toc_depth=args.toc_depth)
        if not args.output:
            print(result)
        else:
            print(f"✅ TOC written: {args.output}")
        return 0
    except (TOCGeneratorError, PandocNotFoundError, PandocRenderError, HTMLSourceError) as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())