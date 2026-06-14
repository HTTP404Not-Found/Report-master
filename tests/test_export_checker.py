"""Tests for scripts.export_checker (v1.4.0 DOCX-only, 5 項驗收).

v1.4.0 changes:
  - Removed 3 PDF checks (PDF openable / PDF font embedded / PDF page count > 0)
  - Kept/added 5 DOCX checks:
      1. DOCX openable (zip + word/document.xml parse)
      2. DOCX has [Content_Types].xml
      3. DOCX has word/document.xml
      4. DOCX has at least 1 paragraph
      5. TOC link (TOC field or bookmark) valid
  - Existing tests for `~$` lock-file warning preserved (WARN level).
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from scripts.export_checker import (
    ExportCheckReport,
    check_export,
    _check_docx,
    _check_office_lock_files,
)


# ────────────────────────────────────────────────────────────────────
# Helper: build a minimal valid DOCX in memory
# ────────────────────────────────────────────────────────────────────

def _make_docx_bytes(*, with_toc: bool = False, with_bookmark: bool = False) -> bytes:
    """Construct a minimal valid DOCX ZIP in memory.

    Includes:
      - [Content_Types].xml
      - word/document.xml (1 paragraph minimum)
    Optionally adds a TOC field instrText or a bookmark.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                   '</Types>')

        toc_field = ""
        bookmark = ""
        if with_toc:
            toc_field = (
                '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" </w:instrText></w:r>'
                '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                '<w:r><w:t>TOC content</w:t></w:r>'
                '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
            )
        if with_bookmark:
            bookmark = (
                '<w:p><w:bookmarkStart w:id="0" w:name="cover"/>'
                '<w:r><w:t>Cover</w:t></w:r>'
                '<w:bookmarkEnd w:id="0"/></w:p>'
            )

        body = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:body>'
            '<w:p><w:r><w:t>Hello World</w:t></w:r></w:p>'
            + toc_field + bookmark +
            '</w:body></w:document>'
        )
        z.writestr("word/document.xml", body)
    return buf.getvalue()


def _write_docx(tmp_path: Path, name: str, **kwargs) -> Path:
    p = tmp_path / name
    p.write_bytes(_make_docx_bytes(**kwargs))
    return p


# ────────────────────────────────────────────────────────────────────
# Tests for v1.4.0 5 項 DOCX 驗收
# ────────────────────────────────────────────────────────────────────

def test_check_docx_pass_with_toc(tmp_path: Path) -> None:
    """DOCX with TOC field → all 5 項 PASS."""
    docx = _write_docx(tmp_path, "ok_with_toc.docx", with_toc=True)
    rep = check_export(docx_path=docx, require_docx=True)
    assert rep.passed is True, f"expected PASS, issues={rep.issues}"
    assert rep.docx_report is not None
    # 5 checks present
    check_names = {c["name"] for c in rep.docx_report["checks"]}
    assert "zip_integrity" in check_names
    assert "has_[Content_Types].xml" in check_names
    assert "has_word/document.xml" in check_names
    assert "paragraph_count" in check_names
    assert "toc_link" in check_names
    # TOC detected
    toc_check = next(c for c in rep.docx_report["checks"] if c["name"] == "toc_link")
    assert toc_check["passed"] is True
    assert "TOC field" in toc_check["evidence"]


def test_check_docx_pass_with_bookmark(tmp_path: Path) -> None:
    """DOCX with bookmark (no TOC field) → all 5 項 PASS."""
    docx = _write_docx(tmp_path, "ok_with_bookmark.docx", with_bookmark=True)
    rep = check_export(docx_path=docx, require_docx=True)
    assert rep.passed is True, f"expected PASS, issues={rep.issues}"
    toc_check = next(c for c in rep.docx_report["checks"] if c["name"] == "toc_link")
    assert toc_check["passed"] is True
    assert "bookmark" in toc_check["evidence"]


def test_check_docx_fail_missing_content_types(tmp_path: Path) -> None:
    """DOCX missing [Content_Types].xml → FAIL."""
    docx = tmp_path / "bad_no_ct.docx"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # Intentionally omit [Content_Types].xml; include only document.xml
        z.writestr("word/document.xml",
                   '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   '<w:body><w:p/></w:body></w:document>')
    docx.write_bytes(buf.getvalue())

    rep = check_export(docx_path=docx, require_docx=True)
    assert rep.passed is False
    assert any("[Content_Types].xml" in i for i in rep.issues)


def test_check_docx_fail_missing_document_xml(tmp_path: Path) -> None:
    """DOCX missing word/document.xml → FAIL."""
    docx = tmp_path / "bad_no_doc.docx"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        # Intentionally omit word/document.xml
    docx.write_bytes(buf.getvalue())

    rep = check_export(docx_path=docx, require_docx=True)
    assert rep.passed is False
    assert any("word/document.xml" in i for i in rep.issues)


def test_check_docx_fail_no_paragraphs(tmp_path: Path) -> None:
    """DOCX with document.xml but zero paragraphs → FAIL."""
    docx = tmp_path / "bad_empty.docx"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?>'
                   '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   '<w:body></w:body></w:document>')
    docx.write_bytes(buf.getvalue())

    rep = check_export(docx_path=docx, require_docx=True)
    assert rep.passed is False
    assert any("沒有段落" in i or "paragraph" in i.lower() for i in rep.issues)
    assert rep.docx_report["paragraph_count"] == 0


# ────────────────────────────────────────────────────────────────────
# Backward-compat: require_docx=False allows missing DOCX
# ────────────────────────────────────────────────────────────────────

def test_check_export_require_docx_false() -> None:
    """require_docx=False with no path → PASS (no DOCX required)."""
    rep = check_export(docx_path=None, require_docx=False)
    assert rep.passed is True
    assert rep.docx_path is None


def test_check_export_missing_path_required() -> None:
    """require_docx=True with no path → FAIL."""
    rep = check_export(docx_path=None, require_docx=True)
    assert rep.passed is False
    assert any("缺少 DOCX" in i for i in rep.issues)


# ────────────────────────────────────────────────────────────────────
# Office 暫存檔 warning (D5 preserved)
# ────────────────────────────────────────────────────────────────────

def test_office_lock_file_warning(tmp_path: Path) -> None:
    """~$ lock file in same dir → WARN (non-blocking)."""
    docx = _write_docx(tmp_path, "good.docx", with_toc=True)
    # Create a fake Office lock file
    (tmp_path / "~$good.docx").write_text("lock")
    rep = check_export(docx_path=docx, require_docx=True)
    # PASS still (warning is non-blocking)
    assert rep.passed is True
    assert any("~$" in w for w in rep.warnings)
