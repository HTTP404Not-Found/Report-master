# html_to_pdf.py — HTML → PDF (weasyprint wrapper)
# 對應 SPEC.md §3.1 + architecture.md §介面定義
# 自動偵測 fonts/ 字體並嵌入 PDF；失敗時 raise 明確例外。

from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from typing import List, Optional, Union

try:
    from weasyprint import HTML, CSS
    # weasyprint ≥ 60 moved FontConfiguration to weasyprint.text.fonts
    try:
        from weasyprint.text.fonts import FontConfiguration
    except ImportError:  # pragma: no cover — older versions
        from weasyprint import FontConfiguration
    _HAS_WEASYPRINT = True
except ImportError:  # pragma: no cover
    _HAS_WEASYPRINT = False


logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Exceptions
# ────────────────────────────────────────────────────────────────────

class HTMLToPDFError(Exception):
    """Base for html_to_pdf failures."""


class WeasyPrintNotInstalled(HTMLToPDFError):
    """weasyprint not installed in current Python env."""


class FontNotFoundError(HTMLToPDFError):
    """Required CJK / Latin font not present on disk."""


class HTMLSourceError(HTMLToPDFError):
    """HTML source unreadable / empty."""


class PDFRenderError(HTMLToPDFError):
    """weasyprint render failed."""


# ────────────────────────────────────────────────────────────────────
# Font discovery
# ────────────────────────────────────────────────────────────────────

def _resolve_fonts_dir() -> Path:
    """Return the project's fonts/ directory (or env override).

    Priority:
      1. $REPORT_MASTER_FONTS_DIR
      2. <project>/fonts (sibling of scripts/)
    """
    env = os.environ.get("REPORT_MASTER_FONTS_DIR")
    if env:
        p = Path(env).expanduser().resolve()
        return p
    # scripts/html_to_pdf.py → <project>/scripts/html_to_pdf.py
    here = Path(__file__).resolve()
    project_root = here.parent.parent  # scripts/../
    return project_root / "fonts"


def discover_fonts(fonts_dir: Optional[Union[str, Path]] = None) -> List[Path]:
    """Return all .ttf / .otf / .ttc files in fonts_dir (non-recursive)."""
    d = Path(fonts_dir) if fonts_dir else _resolve_fonts_dir()
    if not d.exists():
        return []
    out: List[Path] = []
    for ext in ("*.ttf", "*.otf", "*.ttc"):
        out.extend(sorted(d.glob(ext)))
    return out


def assert_required_fonts(fonts_dir: Optional[Union[str, Path]] = None,
                          cjk: str = "標楷體",
                          latin: str = "Times New Roman",
                          strict: bool = False) -> List[Path]:
    """Verify the fonts/ directory contains files matching the locked font names.

    By default this is a SOFT check: it returns the discovered fonts (may be empty)
    and only logs a warning. The strict mode (strict=True) raises FontNotFoundError
    when fonts_dir is missing/empty — used by config.py at project init time.

    Args:
        fonts_dir: directory to scan (defaults to project's fonts/).
        cjk: expected CJK font name (for messaging only).
        latin: expected Latin font name (for messaging only).
        strict: if True, raise FontNotFoundError when no fonts found.

    Returns: list of font paths discovered (may be empty in non-strict mode).

    Raises:
        FontNotFoundError: if fonts_dir is missing, OR (strict and empty).
    """
    d = Path(fonts_dir) if fonts_dir else _resolve_fonts_dir()
    if not d.exists():
        # In non-strict mode, just warn (system fonts will be used).
        if strict:
            raise FontNotFoundError(
                f"字體目錄不存在: {d}\n"
                f"請依 fonts/README.md 安裝 {cjk} (.ttf/.otf) 與 {latin}。"
            )
        logger.warning("字體目錄不存在: %s；weasyprint 將 fallback 至系統字體。", d)
        return []

    fonts = discover_fonts(d)
    if not fonts:
        if strict:
            raise FontNotFoundError(
                f"字體目錄 {d} 內無 .ttf/.otf/.ttc 檔案。\n"
                f"請放入 {cjk} 與 {latin} 字體後重跑。"
            )
        logger.warning("字體目錄 %s 內無字體檔；weasyprint 將 fallback 至系統字體。", d)
    else:
        logger.info("Found %d font file(s) in %s", len(fonts), d)
    return fonts


# ────────────────────────────────────────────────────────────────────
# Main API
# ────────────────────────────────────────────────────────────────────

def html_to_pdf(
    html_source: Union[str, Path],
    output_pdf: Union[str, Path],
    base_url: Optional[str] = None,
    fonts_dir: Optional[Union[str, Path]] = None,
    extra_css: Optional[str] = None,
    presentational_hints: bool = True,
) -> Path:
    """Convert HTML → PDF via weasyprint.

    Args:
        html_source: HTML string OR path to HTML file.
        output_pdf: path to write PDF.
        base_url: base URL for resolving relative <img src="..."> links.
        fonts_dir: directory containing .ttf/.otf/.ttc (defaults to project's fonts/).
        extra_css: optional extra CSS string appended after <style>.
        presentational_hints: pass to weasyprint.HTML.

    Returns: Path to output_pdf.

    Raises:
        WeasyPrintNotInstalled, HTMLSourceError, FontNotFoundError, PDFRenderError.
    """
    if not _HAS_WEASYPRINT:
        raise WeasyPrintNotInstalled(
            "weasyprint 未安裝。請在 venv 內執行：\n"
            "  .venv/bin/pip install weasyprint\n"
            "系統套件依賴（libpango / libcairo）若缺，請：\n"
            "  sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libcairo2\n"
            "（Track B 不自動安裝系統套件；fail-fast 提示。）"
        )

    out = Path(output_pdf)
    out.parent.mkdir(parents=True, exist_ok=True)

    # ─── HTML source ───
    if isinstance(html_source, Path) or (
        isinstance(html_source, str) and "\n" not in html_source and Path(html_source).exists()
    ):
        html_path = Path(html_source)
        if not html_path.exists():
            raise HTMLSourceError(f"HTML 檔不存在: {html_path}")
        html_text = html_path.read_text(encoding="utf-8")
        if not html_text.strip():
            raise HTMLSourceError(f"HTML 檔為空: {html_path}")
        if base_url is None:
            base_url = str(html_path.parent.resolve()) + "/"
    else:
        html_text = str(html_source)
        if not html_text.strip():
            raise HTMLSourceError("HTML 字串為空")

    # ─── Fonts ───
    # Use strict=False: missing fonts/ should not block; weasyprint falls back to system fonts.
    # For strict fail-fast (project init / CI), pass fonts_dir to a separate script
    # that calls assert_required_fonts(strict=True).
    fonts = assert_required_fonts(fonts_dir, strict=False)

    # ─── Build font config ───
    font_config = FontConfiguration()

    # ─── Render ───
    try:
        html_obj = HTML(string=html_text, base_url=base_url)

        stylesheets = []
        if fonts:
            stylesheets.extend(CSS(filename=str(f)) for f in fonts)

        if extra_css:
            stylesheets.append(CSS(string=extra_css))

        html_obj.write_pdf(
            target=str(out),
            stylesheets=stylesheets,
            font_config=font_config,
            presentational_hints=presentational_hints,
        )
    except Exception as e:  # weasyprint raises various subclasses
        # Re-raise with context, but don't swallow
        raise PDFRenderError(
            f"weasyprint 渲染失敗: {type(e).__name__}: {e}\n"
            f"請檢查 HTML 結構 / 字體路徑 / 系統套件（libpango）。"
        ) from e

    if not out.exists() or out.stat().st_size == 0:
        raise PDFRenderError(f"PDF 寫入失敗或為空: {out}")

    logger.info("PDF written: %s (%d bytes)", out, out.stat().st_size)
    return out


# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────

def _main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Convert HTML to PDF (weasyprint).")
    ap.add_argument("html", help="Input HTML file path")
    ap.add_argument("-o", "--output", required=True, help="Output PDF path")
    ap.add_argument("--base-url", default=None, help="Base URL for relative refs")
    ap.add_argument("--fonts-dir", default=None, help="Override fonts directory")
    ap.add_argument("--extra-css", default=None, help="Path to extra CSS file")
    args = ap.parse_args(argv)

    extra_css = None
    if args.extra_css:
        extra_css = Path(args.extra_css).read_text(encoding="utf-8")

    try:
        out = html_to_pdf(
            html_source=args.html,
            output_pdf=args.output,
            base_url=args.base_url,
            fonts_dir=args.fonts_dir,
            extra_css=extra_css,
        )
        print(f"✅ PDF written: {out}")
        return 0
    except HTMLToPDFError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())