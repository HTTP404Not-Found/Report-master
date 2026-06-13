# mermaid_renderer.py — mermaid-cli (mmdc) 預渲染 SVG
# 對應 SPEC.md §6.1 R5 + REVIEW.md R5
# 用途：掃描 HTML 中的 <pre class="mermaid">...</pre>，呼叫 mmdc 預渲染為 SVG，
#       並將 <pre> 替換為 <img src="..."> 以嵌入 weasyprint 看得見的靜態 SVG。
#
# Track B 不自動安裝 mmdc；遇到缺 CLI 時 raise 明確例外。

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Union, List, Tuple

logger = logging.getLogger(__name__)


class MermaidRenderError(Exception):
    """Base for mermaid_renderer failures."""


class MMDCNotFoundError(MermaidRenderError):
    """mmdc (mermaid-cli) binary not found."""


# ────────────────────────────────────────────────────────────────────
# mmdc discovery
# ────────────────────────────────────────────────────────────────────

def find_mmdc() -> str:
    """Locate mmdc binary. Raises MMDCNotFoundError if missing."""
    p = shutil.which("mmdc") or shutil.which("mermaid")
    if not p:
        raise MMDCNotFoundError(
            "mermaid-cli (mmdc) 未安裝。請安裝後重跑：\n"
            "  npm install -g @mermaid-js/mermaid-cli\n"
            "或：\n"
            "  npx @mermaid-js/mermaid-cli\n"
            "（Track B 不自動安裝；fail-fast 提示。）"
        )
    return p


# ────────────────────────────────────────────────────────────────────
# Pre-rendering pipeline
# ────────────────────────────────────────────────────────────────────

# Match <pre class="mermaid"> ... </pre> blocks (multiline, dotall)
_MERMAID_BLOCK_RE = re.compile(
    r'<pre\s+class\s*=\s*["\']mermaid["\'][^>]*>(.*?)</pre>',
    re.DOTALL | re.IGNORECASE,
)


def _extract_mermaid_blocks(html: str) -> List[Tuple[int, int, str]]:
    """Return list of (start, end, mermaid_source) for each <pre class='mermaid'> block."""
    return [(m.start(), m.end(), m.group(1)) for m in _MERMAID_BLOCK_RE.finditer(html)]


def render_mermaid_block(
    mermaid_source: str,
    output_svg: Union[str, Path],
    mmdc_path: Optional[str] = None,
    puppeteer_config: Optional[Union[str, Path]] = None,
) -> Path:
    """Render a single mermaid source to SVG via mmdc.

    Args:
        mermaid_source: mermaid graph definition text.
        output_svg: path to write SVG.
        mmdc_path: override mmdc binary.
        puppeteer_config: optional path to puppeteer config (CI/headless setup).

    Returns: Path to output_svg.

    Raises:
        MMDCNotFoundError, MermaidRenderError.
    """
    mmdc = mmdc_path or find_mmdc()

    out = Path(output_svg)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Write mermaid source to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False, encoding="utf-8") as tmp:
        tmp.write(mermaid_source)
        mmd_path = tmp.name

    try:
        args = [mmdc, "-i", mmd_path, "-o", str(out), "-b", "transparent"]
        if puppeteer_config:
            args += ["-p", str(puppeteer_config)]

        proc = subprocess.run(args, capture_output=True, text=True)
        if proc.returncode != 0:
            raise MermaidRenderError(
                f"mmdc 失敗 (exit {proc.returncode}):\n"
                f"  STDERR: {proc.stderr.strip()[:500]}\n"
                f"  STDOUT: {proc.stdout.strip()[:500]}"
            )

        if not out.exists() or out.stat().st_size == 0:
            raise MermaidRenderError(f"SVG 寫入失敗或為空: {out}")

        return out
    finally:
        try:
            Path(mmd_path).unlink()
        except OSError:
            pass


def render_all_in_html(
    html_source: Union[str, Path],
    output_html: Union[str, Path],
    assets_dir: Union[str, Path],
    mmdc_path: Optional[str] = None,
    puppeteer_config: Optional[Union[str, Path]] = None,
) -> dict:
    """Render all <pre class="mermaid"> blocks in HTML to SVGs; replace with <img>.

    Args:
        html_source: HTML string OR path.
        output_html: path to write HTML with replaced <img>.
        assets_dir: directory to write SVGs (e.g. assets/).
        mmdc_path: override mmdc binary.
        puppeteer_config: optional path to puppeteer config.

    Returns: dict {rendered: N, replaced: N, paths: [...]}.

    Raises:
        MMDCNotFoundError, MermaidRenderError, FileNotFoundError.
    """
    if isinstance(html_source, Path) or (
        isinstance(html_source, str) and Path(html_source).exists()
    ):
        html_text = Path(html_source).read_text(encoding="utf-8")
    else:
        html_text = str(html_source)

    assets_p = Path(assets_dir)
    assets_p.mkdir(parents=True, exist_ok=True)

    blocks = _extract_mermaid_blocks(html_text)
    if not blocks:
        # Nothing to do — write through
        out_p = Path(output_html)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(html_text, encoding="utf-8")
        return {"rendered": 0, "replaced": 0, "paths": []}

    paths: List[str] = []
    # Process in reverse to preserve offsets
    new_html = html_text
    for idx in range(len(blocks) - 1, -1, -1):
        start, end, source = blocks[idx]
        svg_name = f"mermaid_{idx + 1}.svg"
        svg_path = assets_p / svg_name
        render_mermaid_block(source, svg_path, mmdc_path=mmdc_path,
                             puppeteer_config=puppeteer_config)
        rel_path = f"assets/{svg_name}"
        replacement = (
            f'<figure><img src="{rel_path}" alt="mermaid diagram {idx + 1}" '
            f'style="display:block;margin:auto;max-width:100%;">'
            f'<figcaption class="caption">Figure {idx + 1}: Mermaid diagram</figcaption>'
            f'</figure>'
        )
        new_html = new_html[:start] + replacement + new_html[end:]
        paths.append(str(svg_path))

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
    ap = argparse.ArgumentParser(description="Pre-render mermaid blocks in HTML.")
    ap.add_argument("html", help="Input HTML path")
    ap.add_argument("-o", "--output", required=True, help="Output HTML path")
    ap.add_argument("--assets-dir", default="assets", help="Assets directory (default 'assets')")
    ap.add_argument("--puppeteer-config", default=None, help="Puppeteer config JSON path")
    args = ap.parse_args()

    try:
        result = render_all_in_html(
            html_source=args.html,
            output_html=args.output,
            assets_dir=args.assets_dir,
            puppeteer_config=args.puppeteer_config,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (MermaidRenderError, MMDCNotFoundError) as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())