# export_checker.py — post-export 檢查
# 對應 SPEC.md §6.1 R8 + REVIEW.md R8
# 用途：驗收 PDF + DOCX 雙交付物（頁數 / 字體 / 圖片 / 連結）
# 報告：PASS / FAIL + 詳細 reason
#
# 雙輸入：同時檢查 PDF + DOCX；任何一項失敗 → 整份報告 PASS=false

from __future__ import annotations

import logging
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

logger = logging.getLogger(__name__)


class ExportCheckError(Exception):
    """Raised when export check fails (BLOCKING)."""


@dataclass
class ExportCheckReport:
    passed: bool
    pdf_path: Optional[str]
    docx_path: Optional[str]
    pdf_report: Dict[str, Any] = field(default_factory=dict)
    docx_report: Dict[str, Any] = field(default_factory=dict)
    issues: List[str] = field(default_factory=list)
    # v1.3.3 新增 — D5: Office 暫存檔 (~$) 警告 (WARN 級,不 BLOCKING)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ────────────────────────────────────────────────────────────────────
# PDF checks
# ────────────────────────────────────────────────────────────────────

def _has_pymupdf() -> bool:
    try:
        import pymupdf  # noqa: F401
        return True
    except ImportError:
        try:
            import fitz  # noqa: F401
            return True
        except ImportError:
            return False


def _check_pdf(pdf_path: Path) -> Dict[str, Any]:
    """PyMuPDF-based PDF inspection."""
    out: Dict[str, Any] = {"path": str(pdf_path), "checks": []}

    if not pdf_path.exists():
        out["passed"] = False
        out["issues"] = [f"PDF 檔不存在: {pdf_path}"]
        return out

    if pdf_path.stat().st_size == 0:
        out["passed"] = False
        out["issues"] = [f"PDF 檔為空: {pdf_path}"]
        return out

    if not _has_pymupdf():
        out["skipped"] = True
        out["skipped_reason"] = "PyMuPDF 未安裝"
        # Fallback: just check file size > 1KB
        out["passed"] = pdf_path.stat().st_size > 1024
        out["checks"].append({"name": "file_size", "size": pdf_path.stat().st_size})
        return out

    try:
        # Try new package name first
        try:
            import pymupdf as fitz  # type: ignore
        except ImportError:
            import fitz  # type: ignore

        doc = fitz.open(str(pdf_path))
        page_count = doc.page_count

        out["page_count"] = page_count
        out["checks"].append({"name": "page_count", "value": page_count,
                              "passed": page_count > 0})
        if page_count == 0:
            out["passed"] = False
            out.setdefault("issues", []).append("PDF 頁數為 0")

        # Font subsetting
        fonts_seen = set()
        for i in range(page_count):
            page = doc[i]
            for f in page.get_fonts(full=True):
                # f = (xref, ext, type, basefont, name, encoding)
                if len(f) >= 4:
                    fonts_seen.add(f[3])
        out["fonts"] = sorted(fonts_seen)
        out["checks"].append({"name": "fonts_found", "value": sorted(fonts_seen),
                              "count": len(fonts_seen)})

        # Image count
        images = 0
        for i in range(page_count):
            images += len(doc[i].get_images(full=True))
        out["image_count"] = images
        out["checks"].append({"name": "image_count", "value": images})

        # Link count
        links = 0
        for i in range(page_count):
            links += len(doc[i].get_links())
        out["link_count"] = links

        doc.close()
        out["passed"] = out.get("passed", True) and page_count > 0
    except Exception as e:
        out["passed"] = False
        out.setdefault("issues", []).append(f"PyMuPDF 解析失敗: {e}")

    return out


# ────────────────────────────────────────────────────────────────────
# DOCX checks (lightweight — deep check in docx_validator)
# ────────────────────────────────────────────────────────────────────

def _check_docx(docx_path: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {"path": str(docx_path), "checks": []}

    if not docx_path.exists():
        out["passed"] = False
        out["issues"] = [f"DOCX 檔不存在: {docx_path}"]
        return out
    if docx_path.stat().st_size == 0:
        out["passed"] = False
        out["issues"] = [f"DOCX 檔為空: {docx_path}"]
        return out

    try:
        with zipfile.ZipFile(str(docx_path)) as z:
            names = z.namelist()
            bad = z.testzip()
            out["checks"].append({"name": "zip_integrity",
                                  "passed": bad is None,
                                  "bad_member": bad})
            if bad:
                out["passed"] = False
                out.setdefault("issues", []).append(f"ZIP 損壞: {bad}")

            required = ["[Content_Types].xml", "word/document.xml"]
            for r in required:
                present = r in names
                out["checks"].append({"name": f"has_{r}", "passed": present})
                if not present:
                    out["passed"] = False
                    out.setdefault("issues", []).append(f"缺 {r}")

            # word/document.xml must have at least one paragraph
            if "word/document.xml" in names:
                doc_xml = z.read("word/document.xml").decode("utf-8", errors="replace")
                p_count = doc_xml.count("<w:p ") + doc_xml.count("<w:p>")
                out["paragraph_count"] = p_count
                out["checks"].append({"name": "paragraph_count", "value": p_count,
                                      "passed": p_count > 0})
                if p_count == 0:
                    out["passed"] = False
                    out.setdefault("issues", []).append("DOCX 沒有段落")

        out.setdefault("passed", True)
    except zipfile.BadZipFile as e:
        out["passed"] = False
        out["issues"] = [f"DOCX 不是有效 ZIP: {e}"]

    return out


# ────────────────────────────────────────────────────────────────────
# Main API
# ────────────────────────────────────────────────────────────────────

def _check_office_lock_files(pdf_path: Optional[Path], docx_path: Optional[Path]) -> List[str]:
    """v1.3.3 新增 — D5: 掃 Office 暫存檔 (~$)。

    Office Word / Excel / PowerPoint 在檔案被開啟時會產生以 `~$` 開頭的
    lock file (例: `~$report_final.docx`)。如果 exports/ 目錄裡還有這類
    檔案，代表上次的 Office session 未正常關閉，可能導致：
      - 匯出期間被寫入不完全的 DOCX 覆蓋
      - CI / 交付時帶著假的「交付物」

    這是 **WARN 級** 檢查（不 BLOCKING），僅提示使用者手動清理。
    """
    warnings: List[str] = []
    scanned_dirs: set = set()

    for p in (pdf_path, docx_path):
        if p is None:
            continue
        parent = p.parent.resolve()
        if parent in scanned_dirs:
            continue
        scanned_dirs.add(parent)
        try:
            for entry in parent.iterdir():
                if entry.name.startswith("~$"):
                    warnings.append(
                        f"Office 暫存檔未清理: {entry.name} "
                        f"({parent}) — 可能是上次 Office session 未正常關閉"
                    )
        except OSError as e:
            warnings.append(f"掃描目錄失敗: {parent} — {e}")

    return warnings


def check_export(
    pdf_path: Optional[Union[str, Path]] = None,
    docx_path: Optional[Union[str, Path]] = None,
    *,
    require_pdf: bool = True,
    require_docx: bool = True,
) -> ExportCheckReport:
    """Check post-export deliverables.

    Args:
        pdf_path: optional PDF path.
        docx_path: optional DOCX path.
        require_pdf: if True and pdf_path is None, fail.
        require_docx: if True and docx_path is None, fail.

    Returns: ExportCheckReport (passed=False on any failure).
    """
    pdf_p = Path(pdf_path) if pdf_path else None
    docx_p = Path(docx_path) if docx_path else None

    report = ExportCheckReport(
        passed=True,
        pdf_path=str(pdf_p) if pdf_p else None,
        docx_path=str(docx_p) if docx_p else None,
    )

    if require_pdf and not pdf_p:
        report.passed = False
        report.issues.append("缺少 PDF 路徑")

    if require_docx and not docx_p:
        report.passed = False
        report.issues.append("缺少 DOCX 路徑")

    if pdf_p:
        pdf_rep = _check_pdf(pdf_p)
        report.pdf_report = pdf_rep
        if not pdf_rep.get("passed", True):
            report.passed = False
            for issue in pdf_rep.get("issues", []):
                report.issues.append(f"[PDF] {issue}")

    if docx_p:
        docx_rep = _check_docx(docx_p)
        report.docx_report = docx_rep
        if not docx_rep.get("passed", True):
            report.passed = False
            for issue in docx_rep.get("issues", []):
                report.issues.append(f"[DOCX] {issue}")

    # v1.3.3 新增 — D5: Office 暫存檔警告 (WARN 級)
    lock_warnings = _check_office_lock_files(pdf_p, docx_p)
    report.warnings.extend(lock_warnings)

    return report


# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────

def _main() -> int:
    import argparse
    import json
    import sys
    ap = argparse.ArgumentParser(description="Post-export check (BLOCKING on failure).")
    ap.add_argument("--pdf", default=None, help="PDF path")
    ap.add_argument("--docx", default=None, help="DOCX path")
    ap.add_argument("--require-pdf", action="store_true", default=True)
    ap.add_argument("--require-docx", action="store_true", default=True)
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    rep = check_export(
        pdf_path=args.pdf,
        docx_path=args.docx,
        require_pdf=args.require_pdf,
        require_docx=args.require_docx,
    )

    if args.json:
        print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
    else:
        if rep.passed:
            print(f"✅ EXPORT PASS")
            if rep.pdf_report:
                print(f"  PDF: pages={rep.pdf_report.get('page_count','?')}, "
                      f"fonts={len(rep.pdf_report.get('fonts',[]))}, "
                      f"images={rep.pdf_report.get('image_count','?')}")
            if rep.docx_report:
                print(f"  DOCX: paragraphs={rep.docx_report.get('paragraph_count','?')}")
        else:
            print(f"❌ EXPORT FAIL")
            for issue in rep.issues:
                print(f"  • {issue}")

        # v1.3.3 新增 — D5: Office 暫存檔警告 (WARN 級)
        if rep.warnings:
            print(f"\n⚠️  WARN ({len(rep.warnings)}):")
            for w in rep.warnings:
                print(f"  ⚠ {w}")

    return 0 if rep.passed else 1


if __name__ == "__main__":
    raise SystemExit(_main())