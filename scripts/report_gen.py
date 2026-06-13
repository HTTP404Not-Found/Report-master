# report_gen.py — Report-master 主 pipeline orchestrator
# 對應 SPEC.md §2.3 Pipeline + SKILL.md §3 呼叫協議
# 串接：load lock → Stage 2 逐節 HTML 生成 → quality_checker 過門 → Stage 3 平行轉換 → export_checker 驗收
#
# 三種 CLI 模式：
#   1. 全自動（Stage 2 + 3）：  python -m scripts.report_gen --source X --output Y --lock Z
#   2. 只跑 Stage 3（已生成 HTML）：report_gen render --html X --output Y [--format pdf,docx]
#   3. 只跑 Stage 2（生成 HTML）：  report_gen generate --lock X --output Y

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Optional, Union

from scripts.quality_checker import check_html, scan_html, QualityCheckError
from scripts.html_to_pdf import html_to_pdf, HTMLToPDFError
from scripts.html_to_docx import html_to_docx, HTMLToDOCXError
from scripts.export_checker import check_export
from scripts.docx_validator import validate_docx, DOCXValidationError

# Try to use Track A's report_lock.py (preferred). Fall back to local parser.
try:
    from scripts.report_lock import (
        read_and_validate,
        LockError as _RALockError,
        LockMissingFieldsError as _RAMissingError,
    )
    _HAS_REPORT_LOCK = True
except ImportError:
    _HAS_REPORT_LOCK = False

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# Lock parsing (lightweight — Track A owns the full schema validator)
# ────────────────────────────────────────────────────────────────────

class LockParseError(Exception):
    """report_lock.md parsing failed."""


class LockMissingFieldsError(LockParseError):
    """One or more required fields are missing from report_lock.md."""


REQUIRED_FIELDS = [
    "fonts", "formatting", "page_size", "margins",
    "line_spacing", "language_variant", "citation_style",
]

# Required subkeys inside `fonts` and `formatting`
REQUIRED_FONT_KEYS = ["cjk", "latin"]
REQUIRED_FORMATTING_KEYS = [
    "cover", "toc", "title", "h1", "h2", "h3", "body", "table", "caption",
]


def _read_lock_minimal(lock_path: Path) -> dict:
    """Parse + validate report_lock.md.

    Prefers Track A's scripts.report_lock (full schema validator).
    Falls back to local minimal parser if Track A module is unavailable.

    Raises:
        LockParseError: file missing / malformed / no YAML.
        LockMissingFieldsError: required fields absent.
    """
    if _HAS_REPORT_LOCK:
        # Delegate to Track A's full validator
        try:
            data = read_and_validate(str(lock_path))
            return data
        except _RAMissingError:
            raise  # propagate as-is (subclass of LockError)
        except _RALockError as e:
            raise LockParseError(str(e)) from e

    # Fallback: local minimal parser
    if not lock_path.exists():
        raise LockParseError(f"report_lock.md 不存在: {lock_path}")

    text = lock_path.read_text(encoding="utf-8")

    # Find YAML frontmatter between --- ... ---
    if not text.startswith("---"):
        raise LockParseError(f"report_lock.md 缺 YAML frontmatter (起始不是 ---): {lock_path}")
    end = text.find("\n---", 3)
    if end == -1:
        raise LockParseError(f"report_lock.md 缺 YAML 結束 (---): {lock_path}")
    yaml_text = text[3:end].strip()

    # Parse YAML
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(yaml_text)
    except ImportError:
        raise LockParseError("PyYAML 未安裝；請在 venv 內安裝 pyyaml")
    except Exception as e:
        raise LockParseError(f"YAML 解析失敗: {e}")

    if not isinstance(data, dict):
        raise LockParseError("YAML frontmatter 不是 mapping 結構")

    # Validate required
    missing = []
    for field_name in REQUIRED_FIELDS:
        if field_name not in data:
            missing.append(field_name)

    if "fonts" in data and isinstance(data["fonts"], dict):
        for k in REQUIRED_FONT_KEYS:
            if k not in data["fonts"]:
                missing.append(f"fonts.{k}")
    if "formatting" in data and isinstance(data["formatting"], dict):
        for k in REQUIRED_FORMATTING_KEYS:
            if k not in data["formatting"]:
                missing.append(f"formatting.{k}")

    if missing:
        raise LockMissingFieldsError(
            f"report_lock.md 缺少 required 欄位: {', '.join(missing)}\n"
            f"請見 docs/report_lock_schema.md §2 補齊。"
        )

    return data


# ────────────────────────────────────────────────────────────────────
# Stage 2 — Section HTML generation (stub for AI agent integration)
# ────────────────────────────────────────────────────────────────────

def _load_existing_html(source: Path) -> List[Path]:
    """Load pre-generated section HTML files from source dir.

    Convention: source_dir contains *.html files (one per section).
    The pipeline does NOT re-generate; it assumes an AI agent (Executor) has
    already produced these. If no HTML files exist, raise.
    """
    if not source.exists():
        raise FileNotFoundError(f"source 目錄不存在: {source}")
    if source.is_file() and source.suffix.lower() == ".html":
        return [source]
    htmls = sorted(source.glob("**/*.html"))
    if not htmls:
        raise FileNotFoundError(
            f"source 目錄內無 .html 檔: {source}\n"
            f"請先由 Executor 生成逐節 HTML（或傳入單一 .html 檔）。"
        )
    return htmls


def _bundle_html(html_paths: List[Path], output_path: Path) -> Path:
    """Concatenate multiple section HTMLs into a single bundle.html.

    Strategy: extract <body>...</body> from each, wrap in a fresh <html>.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    body_parts: List[str] = []
    title = "Report Bundle"
    for p in html_paths:
        text = p.read_text(encoding="utf-8")
        # Naive extraction
        import re
        m_title = re.search(r"<title>([^<]*)</title>", text, re.IGNORECASE)
        if m_title and m_title.group(1).strip():
            title = m_title.group(1).strip()
        m_body = re.search(r"<body[^>]*>(.*?)</body>", text, re.IGNORECASE | re.DOTALL)
        if m_body:
            body_parts.append(f"<!-- from {p.name} -->\n{m_body.group(1)}")
        else:
            body_parts.append(f"<!-- from {p.name} -->\n{text}")

    bundle = (
        "<!DOCTYPE html>\n"
        '<html lang="zh-TW">\n'
        "<head>\n"
        '<meta charset="UTF-8">\n'
        f"<title>{title}</title>\n"
        "<style>\n"
        "  body { font-family: '標楷體', 'Times New Roman', serif; font-size: 12pt; line-height: 1.5; }\n"
        "  h1 { font-family: '標楷體', 'Times New Roman', serif; font-size: 18pt; font-weight: bold; }\n"
        "  h2 { font-family: '標楷體', 'Times New Roman', serif; font-size: 16pt; font-weight: bold; }\n"
        "  h3 { font-family: '標楷體', 'Times New Roman', serif; font-size: 14pt; font-weight: bold; }\n"
        "  table { border-collapse: collapse; width: 100%; }\n"
        "  th, td { border: 1px solid #ccc; padding: 0.5em; }\n"
        "  .caption { text-align: center; font-size: 10pt; }\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        + "\n<hr>\n".join(body_parts)
        + "\n</body>\n</html>\n"
    )
    output_path.write_text(bundle, encoding="utf-8")
    return output_path


def _stage2_generate(source: Path, lock: dict) -> Path:
    """Stage 2: load HTML files from source, bundle them.

    The actual AI generation (Executor prompts) is OUT OF SCOPE for this script;
    this stub assumes the source dir already contains per-section HTML produced
    by an upstream Executor run.

    Returns: path to bundle.html.
    """
    htmls = _load_existing_html(source)
    logger.info("Stage 2: loaded %d HTML file(s) from %s", len(htmls), source)

    bundle_path = source / "_bundle.html" if source.is_dir() else source.parent / "_bundle.html"
    return _bundle_html(htmls, bundle_path)


def _stage2_quality_gate(html_paths: List[Path]) -> Dict[str, dict]:
    """Per-section quality gate (BLOCKING).

    Returns dict {html_path: scan_report_dict}. Raises on first failure.
    """
    results = {}
    for hp in html_paths:
        try:
            text = hp.read_text(encoding="utf-8")
            check_html(text, source=str(hp))
            rep = scan_html(text, source=str(hp))
            results[str(hp)] = rep.to_dict()
            logger.info("✅ quality_checker PASS: %s", hp)
        except QualityCheckError as e:
            logger.error("❌ quality_checker FAIL: %s", hp)
            raise
    return results


# ────────────────────────────────────────────────────────────────────
# Stage 3 — Parallel render
# ────────────────────────────────────────────────────────────────────

@dataclass
class Stage3Result:
    pdf: Optional[Path] = None
    docx: Optional[Path] = None
    pdf_error: Optional[str] = None
    docx_error: Optional[str] = None


def _stage3_render(
    bundle_html: Path,
    output_dir: Path,
    formats: List[str],
    lock: dict,
) -> Stage3Result:
    """Stage 3: render PDF + DOCX in parallel-ish (sequential here for simplicity).

    Returns Stage3Result with paths and any per-format errors.
    """
    result = Stage3Result()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    pdf_path = output_dir / f"report_{timestamp}.pdf"
    docx_path = output_dir / f"report_{timestamp}.docx"

    if "pdf" in formats:
        try:
            html_to_pdf(bundle_html, pdf_path)
            result.pdf = pdf_path
            logger.info("✅ PDF: %s", pdf_path)
        except HTMLToPDFError as e:
            result.pdf_error = str(e)
            logger.error("❌ PDF failed: %s", e)

    if "docx" in formats:
        try:
            html_to_docx(bundle_html, docx_path)
            result.docx = docx_path
            logger.info("✅ DOCX: %s", docx_path)
        except HTMLToDOCXError as e:
            result.docx_error = str(e)
            logger.error("❌ DOCX failed: %s", e)

    return result


# ────────────────────────────────────────────────────────────────────
# Main entry: generate_report()
# ────────────────────────────────────────────────────────────────────

@dataclass
class GenerateReportResult:
    passed: bool
    lock_path: str
    source_dir: str
    output_dir: str
    bundle_html: Optional[str] = None
    stage2_quality: Dict[str, dict] = field(default_factory=dict)
    pdf: Optional[str] = None
    docx: Optional[str] = None
    export_check: Dict = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


def generate_report(
    source_dir: Union[str, Path],
    output_dir: Union[str, Path],
    lock_path: Union[str, Path],
    formats: Optional[List[str]] = None,
    skip_quality_gate: bool = False,
    run_docx_validation: bool = True,
) -> GenerateReportResult:
    """Main pipeline: Stage 2 + 3 with quality gates.

    Args:
        source_dir: directory containing per-section *.html (or single .html file).
        output_dir: where to write report_{ts}.pdf / report_{ts}.docx.
        lock_path: path to report_lock.md.
        formats: subset of ['pdf', 'docx']; default both.
        skip_quality_gate: DANGEROUS — skip HTML quality check (debug only).
        run_docx_validation: also run docx_validator after DOCX render.

    Returns: GenerateReportResult.
    """
    formats = formats or ["pdf", "docx"]
    src = Path(source_dir)
    out = Path(output_dir)
    lock_p = Path(lock_path)

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    result = GenerateReportResult(
        passed=True, lock_path=str(lock_p), source_dir=str(src),
        output_dir=str(out), timestamp=ts,
    )

    # ── Load lock ──
    try:
        lock = _read_lock_minimal(lock_p)
    except (LockParseError, LockMissingFieldsError) as e:
        result.passed = False
        result.errors.append(f"[LOCK] {e}")
        return result

    # ── Stage 2: load + quality gate ──
    try:
        htmls = _load_existing_html(src)
    except FileNotFoundError as e:
        result.passed = False
        result.errors.append(f"[STAGE2] {e}")
        return result

    if not skip_quality_gate:
        try:
            result.stage2_quality = _stage2_quality_gate(htmls)
        except QualityCheckError as e:
            result.passed = False
            result.errors.append(f"[QUALITY] {e}")
            return result

    # ── Bundle ──
    try:
        bundle_path = _stage2_generate(src, lock)
        result.bundle_html = str(bundle_path)
    except Exception as e:
        result.passed = False
        result.errors.append(f"[BUNDLE] {e}")
        return result

    # ── Stage 3: render ──
    stage3 = _stage3_render(bundle_path, out, formats, lock)
    if stage3.pdf:
        result.pdf = str(stage3.pdf)
    else:
        result.passed = False
        if stage3.pdf_error:
            result.errors.append(f"[PDF] {stage3.pdf_error}")
    if stage3.docx:
        result.docx = str(stage3.docx)
    else:
        result.passed = False
        if stage3.docx_error:
            result.errors.append(f"[DOCX] {stage3.docx_error}")

    # ── DOCX validation (optional) ──
    if run_docx_validation and stage3.docx and formats and "docx" in formats:
        try:
            docx_rep = validate_docx(stage3.docx)
            if not docx_rep.passed:
                result.passed = False
                for issue in docx_rep.issues:
                    result.errors.append(f"[DOCX_VALIDATE] {issue}")
        except Exception as e:
            result.errors.append(f"[DOCX_VALIDATE] (non-fatal): {e}")

    # ── Export check ──
    pdf_p = Path(stage3.pdf) if stage3.pdf else None
    docx_p = Path(stage3.docx) if stage3.docx else None
    export_rep = check_export(pdf_p, docx_p, require_pdf=("pdf" in formats), require_docx=("docx" in formats))
    result.export_check = export_rep.to_dict()
    if not export_rep.passed:
        result.passed = False
        for issue in export_rep.issues:
            result.errors.append(f"[EXPORT] {issue}")

    return result


# ────────────────────────────────────────────────────────────────────
# CLI sub-commands
# ────────────────────────────────────────────────────────────────────

def _cmd_generate(args) -> int:
    """Stage 2 only: load HTML, quality gate, bundle."""
    src = Path(args.source)
    out = Path(args.output)
    lock_p = Path(args.lock)

    try:
        lock = _read_lock_minimal(lock_p)
    except (LockParseError, LockMissingFieldsError) as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2

    try:
        htmls = _load_existing_html(src)
    except FileNotFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2

    try:
        _stage2_quality_gate(htmls)
    except QualityCheckError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 3

    bundle = _stage2_generate(src, lock)
    print(f"✅ bundle: {bundle}")
    return 0


def _cmd_render(args) -> int:
    """Stage 3 only: bundle → PDF/DOCX."""
    html_p = Path(args.html)
    out = Path(args.output)
    lock_p = Path(args.lock) if args.lock else None
    lock = {}
    if lock_p:
        try:
            lock = _read_lock_minimal(lock_p)
        except (LockParseError, LockMissingFieldsError) as e:
            print(f"❌ {e}", file=sys.stderr)
            return 2

    formats = [f.strip() for f in args.format.split(",")] if args.format else ["pdf", "docx"]
    stage3 = _stage3_render(html_p, out, formats, lock)

    exit_code = 0
    if "pdf" in formats:
        if stage3.pdf:
            print(f"✅ PDF: {stage3.pdf}")
        else:
            print(f"❌ PDF: {stage3.pdf_error}", file=sys.stderr)
            exit_code = 1
    if "docx" in formats:
        if stage3.docx:
            print(f"✅ DOCX: {stage3.docx}")
        else:
            print(f"❌ DOCX: {stage3.docx_error}", file=sys.stderr)
            exit_code = 1
    return exit_code


def _cmd_full(args) -> int:
    """Full pipeline: Stage 2 + 3 + export check."""
    result = generate_report(
        source_dir=args.source,
        output_dir=args.output,
        lock_path=args.lock,
        formats=[f.strip() for f in args.format.split(",")] if args.format else None,
        skip_quality_gate=args.skip_quality_gate,
        run_docx_validation=not args.no_docx_validation,
    )
    print(f"\n{'='*60}")
    print(f"Generate Report — {result.timestamp}")
    print(f"{'='*60}")
    print(f"  passed: {result.passed}")
    if result.bundle_html:
        print(f"  bundle: {result.bundle_html}")
    if result.pdf:
        print(f"  PDF:    {result.pdf}")
    if result.docx:
        print(f"  DOCX:   {result.docx}")
    if result.errors:
        print(f"  errors:")
        for e in result.errors:
            print(f"    • {e}")
    print(f"{'='*60}")
    return 0 if result.passed else 1


def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="report-master",
        description="Report-master pipeline (Stage 2 + 3)",
    )
    sub = ap.add_subparsers(dest="subcommand")

    # Full (default)
    p_full = sub.add_parser("full", help="Full pipeline (Stage 2 + 3 + export check)")
    p_full.add_argument("--source", required=True, help="Source HTML dir or file")
    p_full.add_argument("--output", required=True, help="Output directory")
    p_full.add_argument("--lock", required=True, help="report_lock.md path")
    p_full.add_argument("--format", default="pdf,docx", help="Comma-separated: pdf,docx")
    p_full.add_argument("--skip-quality-gate", action="store_true")
    p_full.add_argument("--no-docx-validation", action="store_true")
    p_full.set_defaults(func=_cmd_full)

    # Generate
    p_gen = sub.add_parser("generate", help="Stage 2 only (load HTML + quality gate + bundle)")
    p_gen.add_argument("--source", required=True)
    p_gen.add_argument("--output", required=True)
    p_gen.add_argument("--lock", required=True)
    p_gen.set_defaults(func=_cmd_generate)

    # Render
    p_ren = sub.add_parser("render", help="Stage 3 only (bundle → PDF/DOCX)")
    p_ren.add_argument("--html", required=True)
    p_ren.add_argument("--output", required=True)
    p_ren.add_argument("--lock", default=None)
    p_ren.add_argument("--format", default="pdf,docx")
    p_ren.set_defaults(func=_cmd_render)

    # Default (no subcommand) — full mode
    ap.add_argument("--source", help="Source HTML dir or file")
    ap.add_argument("--output", help="Output directory")
    ap.add_argument("--lock", help="report_lock.md path")
    ap.add_argument("--format", default="pdf,docx")
    ap.add_argument("--skip-quality-gate", action="store_true")
    ap.add_argument("--no-docx-validation", action="store_true")

    return ap


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    ap = _build_arg_parser()
    args = ap.parse_args(argv)

    # Default mode: full pipeline (legacy python -m scripts.report_gen)
    if args.subcommand is None:
        if not (args.source and args.output and args.lock):
            ap.print_help()
            return 2
        # Reuse _cmd_full
        return _cmd_full(args)

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())