# html_to_docx.py — HTML → DOCX (pandoc subprocess wrapper)
# 對應 SPEC.md §3.1 + architecture.md §介面定義
# 主路徑：pandoc --reference-doc=<custom.docx> -o output.docx input.html
# 支援 native_numbering / native_spans / citeproc 等 pandoc extensions

from __future__ import annotations

import os
import sys
import shutil
import logging
import subprocess
from pathlib import Path
from typing import Optional, List, Union

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Exceptions
# ────────────────────────────────────────────────────────────────────

class HTMLToDOCXError(Exception):
    """Base for html_to_docx failures."""


class PandocNotFoundError(HTMLToDOCXError):
    """pandoc binary not found in PATH."""


class HTMLSourceError(HTMLToDOCXError):
    """HTML source unreadable / empty."""


class PandocRenderError(HTMLToDOCXError):
    """pandoc returned non-zero exit."""


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

def find_pandoc() -> str:
    """Locate pandoc binary. Raises PandocNotFoundError if missing."""
    p = shutil.which("pandoc")
    if not p:
        raise PandocNotFoundError(
            "pandoc 未安裝。請安裝後重跑：\n"
            "  Ubuntu/Debian: sudo apt install pandoc\n"
            "  macOS:         brew install pandoc\n"
            "  或下載 binary：https://github.com/jgm/pandoc/releases\n"
            "（Track B 不自動安裝；fail-fast 提示。）"
        )
    return p


def default_reference_docx() -> Optional[Path]:
    """Return default reference docx path if it exists.

    Lookup order:
      1. $REPORT_MASTER_REFERENCE_DOCX
      2. <project>/templates/reference/report-master-template.docx
    Returns None if neither exists (pandoc will use its built-in default).
    """
    env = os.environ.get("REPORT_MASTER_REFERENCE_DOCX")
    if env:
        p = Path(env).expanduser()
        if p.exists():
            return p
    here = Path(__file__).resolve()
    candidate = here.parent.parent / "templates" / "reference" / "report-master-template.docx"
    return candidate if candidate.exists() else None


def pandoc_version() -> str:
    """Return pandoc version string (e.g. '3.1.13')."""
    p = find_pandoc()
    out = subprocess.run([p, "--version"], capture_output=True, text=True, check=False)
    if out.returncode != 0:
        return ""
    # First line is "pandoc 3.1.13\n..."
    return out.stdout.splitlines()[0].split()[-1] if out.stdout else ""


# ────────────────────────────────────────────────────────────────────
# Main API
# ────────────────────────────────────────────────────────────────────

def html_to_docx(
    html_source: Union[str, Path],
    output_docx: Union[str, Path],
    reference_docx: Optional[Union[str, Path]] = None,
    extra_args: Optional[List[str]] = None,
    pandoc_path: Optional[str] = None,
    toc: bool = False,
    toc_depth: int = 3,
    citeproc: bool = False,
    bibliography: Optional[Union[str, Path]] = None,
    csl: Optional[Union[str, Path]] = None,
    standalone: bool = True,
) -> Path:
    """Convert HTML → DOCX via pandoc.

    Args:
        html_source: HTML string OR path to HTML file.
        output_docx: path to write DOCX.
        reference_docx: optional reference docx (controls fonts / styles).
        extra_args: extra CLI args (advanced).
        pandoc_path: override pandoc binary path.
        toc: enable --toc.
        toc_depth: --toc-depth.
        citeproc: enable --citeproc (pandoc ≥ 2.11).
        bibliography: path to BibTeX (.bib).
        csl: path to CSL file.
        standalone: produce standalone DOCX with header.

    Returns: Path to output_docx.

    Raises:
        PandocNotFoundError, HTMLSourceError, PandocRenderError.
    """
    pandoc = pandoc_path or find_pandoc()
    out = Path(output_docx)
    out.parent.mkdir(parents=True, exist_ok=True)

    # ─── HTML source ───
    # Decide if input is a path. Must be non-empty AND (Path or exists on disk).
    is_path = False
    if isinstance(html_source, Path):
        is_path = True
    elif isinstance(html_source, str):
        # Heuristic: a string is treated as a path if it doesn't contain HTML markers
        # AND (it exists on disk OR it looks path-like and the path doesn't exist).
        if html_source and "\n" not in html_source and "<" not in html_source:
            is_path = True  # candidate; validate below

    if is_path:
        html_path = Path(html_source)
        if not html_path.exists():
            raise HTMLSourceError(f"HTML 檔不存在: {html_path}")
        if html_path.stat().st_size == 0:
            raise HTMLSourceError(f"HTML 檔為空: {html_path}")
        input_for_pandoc: Union[str, Path] = str(html_path)
    else:
        # Treat as inline string. Validate non-empty.
        if not html_source or not str(html_source).strip():
            raise HTMLSourceError("HTML 字串為空")
        import tempfile
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False, encoding="utf-8"
        )
        tmp.write(str(html_source))
        tmp.close()
        input_for_pandoc = tmp.name

    # ─── Build args ───
    args: List[str] = [pandoc]
    if standalone:
        args.append("-s")
    args += ["-f", "html", "-t", "docx"]
    args += ["-o", str(out)]

    if reference_docx:
        ref = Path(reference_docx)
        if not ref.exists():
            raise HTMLSourceError(f"reference docx 不存在: {ref}")
        args += ["--reference-doc", str(ref)]
    else:
        # Use Track B default if exists
        default_ref = default_reference_docx()
        if default_ref:
            args += ["--reference-doc", str(default_ref)]

    # Native extensions (REVIEW.md R1 fix).
    # NOTE: native_numbering + native_spans are markdown-only; for HTML input
    # we use raw_html + raw_tex which are html-compatible.
    args += ["--from", "html+raw_html+raw_tex+smart"]

    if toc:
        args += ["--toc", f"--toc-depth={toc_depth}"]

    if citeproc:
        args.append("--citeproc")
        if bibliography:
            bib = Path(bibliography)
            if not bib.exists():
                raise HTMLSourceError(f"bibliography 不存在: {bib}")
            args += ["--bibliography", str(bib)]
        if csl:
            csl_p = Path(csl)
            if not csl_p.exists():
                raise HTMLSourceError(f"CSL 不存在: {csl_p}")
            args += ["--csl", str(csl_p)]

    args.append(str(input_for_pandoc))

    if extra_args:
        args.extend(extra_args)

    logger.info("Running: %s", " ".join(args))

    # ─── Run pandoc ───
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise PandocRenderError(
            f"pandoc 失敗 (exit {proc.returncode}):\n"
            f"  STDERR: {proc.stderr.strip()}\n"
            f"  STDOUT: {proc.stdout.strip()}"
        )

    if not out.exists() or out.stat().st_size == 0:
        raise PandocRenderError(f"DOCX 寫入失敗或為空: {out}")

    # Clean up temp file if we made one
    if not is_path:
        try:
            os.unlink(input_for_pandoc)
        except OSError:
            pass

    logger.info("DOCX written: %s (%d bytes)", out, out.stat().st_size)
    return out


# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────

def _main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Convert HTML to DOCX (pandoc).")
    ap.add_argument("html", help="Input HTML file path")
    ap.add_argument("-o", "--output", required=True, help="Output DOCX path")
    ap.add_argument("--reference-docx", default=None,
                    help="Path to reference DOCX (controls fonts/styles)")
    ap.add_argument("--toc", action="store_true", help="Insert table of contents")
    ap.add_argument("--toc-depth", type=int, default=3, help="TOC depth (default 3)")
    ap.add_argument("--citeproc", action="store_true", help="Enable citeproc")
    ap.add_argument("--bibliography", default=None, help="BibTeX file")
    ap.add_argument("--csl", default=None, help="CSL file")
    args = ap.parse_args(argv)

    try:
        out = html_to_docx(
            html_source=args.html,
            output_docx=args.output,
            reference_docx=args.reference_docx,
            toc=args.toc,
            toc_depth=args.toc_depth,
            citeproc=args.citeproc,
            bibliography=args.bibliography,
            csl=args.csl,
        )
        print(f"✅ DOCX written: {out}")
        return 0
    except HTMLToDOCXError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())