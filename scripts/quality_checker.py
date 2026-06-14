# quality_checker.py — HTML/CSS 質量門禁
# 對應 SPEC.md §6.1 R1 + REVIEW.md R1 + docs/shared-standards.md
# 命中禁用清單 → BLOCKING (raise QualityCheckError)
#
# Usage:
#   from scripts.quality_checker import check_html, check_html_file, QualityCheckError
#   check_html(html_str)               # raises on FAIL
#   check_html_file(path)              # raises on FAIL
#   report = check_html_report(...)    # returns structured dict, never raises

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:  # pragma: no cover
    _HAS_BS4 = False


# ────────────────────────────────────────────────────────────────────
# 禁用清單（對應 docs/shared-standards.md §2）
# 任何命中 → BLOCKING
# ────────────────────────────────────────────────────────────────────

# CSS 屬性禁用（regex 在 <style> 區塊與內聯 style 中匹配）
# NOTE: float 規則獨立處理於 _check_float_on_non_img，會豁免 <img> 標準用法。
# NOTE（D1, 2026-06-14 TR-2）: position: absolute / fixed / sticky 是 canonical
#   禁用規則的唯一來源。任何後處理（_merge_html_docs / bundle.py /
#   html_to_docx / html_to_pdf 等）若曾用 regex 偷偷剝除這些 CSS，是「過渡解」——
#   應在 quality_checker 階段就 BLOCKING，不在後處理階段掩飾。v1.3.3 起確認
#   此清單為 single source of truth。
_FORBIDDEN_CSS_PROPS = [
    (r"display\s*:\s*(?:inline-)?flex\b", "display: flex / inline-flex"),
    (r"display\s*:\s*(?:inline-)?grid\b", "display: grid / inline-grid"),
    (r"position\s*:\s*absolute\b", "position: absolute"),
    (r"position\s*:\s*fixed\b", "position: fixed"),
    (r"position\s*:\s*sticky\b", "position: sticky"),
]

# 偽元素禁用
_FORBIDDEN_PSEUDO = [
    (r"::before\b", "::before 偽元素"),
    (r"::after\b", "::after 偽元素"),
    (r":before\b", ":before 偽元素 (CSS2)"),
    (r":after\b", ":after 偽元素 (CSS2)"),
]

# 禁用元素
_FORBIDDEN_ELEMENTS = [
    (r"<\s*script\b", "<script> 標籤（weasyprint 無 JS）"),
    (r"<\s*canvas\b", "<canvas> 元素（需 JS）"),
    (r"<\s*iframe\b", "<iframe> 沙箱"),
    (r"<\s*object\b", "<object> 沙箱"),
    (r"<\s*embed\b", "<embed> 沙箱"),
]

# 禁用屬性（內聯 JS handler）
_FORBIDDEN_ATTRS = [
    (r"\bon\w+\s*=", "on* JS event handler (onclick=, onload=)"),
]

# 外部 CSS / JS 引用
_EXTERNAL_REFS = [
    (r"<\s*link[^>]+rel\s*=\s*[\"']?stylesheet[\"']?", "<link rel=stylesheet> 外部 CSS"),
    (r"@import\s+url", "@import 外部 CSS"),
]

# 字體鎖死檢查：若 HTML 顯式指定非標楷體中文字體，BLOCKING
# （這個 check 是 soft：只在 <style> 中明確寫死非標楷體中文字體時才 BLOCK）
_FORBIDDEN_FONT_FAMILIES = [
    (r"font-family\s*:[^;]*[\"']?(?:Calibri|Arial|Helvetica|Microsoft\s*YaHei|PingFang|Hiragino|微軟正黑體|新細明體)[\"']?",
     "非鎖死字體 (應為 標楷體 / Times New Roman)"),
]


# ────────────────────────────────────────────────────────────────────
# Exception
# ────────────────────────────────────────────────────────────────────

class QualityCheckError(Exception):
    """Raised when HTML contains forbidden patterns. BLOCKING.

    Attributes:
        violations: list of dicts {rule, line, snippet}
        source: path or '<string>'
    """
    def __init__(self, violations: List[Dict[str, Any]], source: str = "<string>"):
        self.violations = violations
        self.source = source
        msgs = [f"  line {v['line']}: {v['rule']} — {v['snippet']}" for v in violations]
        super().__init__(
            f"[BLOCKING] {source} contains {len(violations)} forbidden pattern(s):\n"
            + "\n".join(msgs)
            + "\n請改寫為 docs/shared-standards.md 允許清單後重提。"
        )


# ────────────────────────────────────────────────────────────────────
# Result dataclass（for non-raising callers）
# ────────────────────────────────────────────────────────────────────

@dataclass
class QualityReport:
    passed: bool
    source: str
    violations: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ────────────────────────────────────────────────────────────────────
# Core scan
# ────────────────────────────────────────────────────────────────────

def _scan_patterns(html: str, patterns: List) -> List[Dict[str, Any]]:
    """Run a list of (regex, rule_name) over HTML lines; return violations."""
    violations = []
    # 逐行掃描以提供 line number
    for lineno, line in enumerate(html.splitlines(), start=1):
        # 移除該行的 HTML 註解以避免誤判（<!-- ... -->）
        stripped = re.sub(r"<!--.*?-->", "", line)
        for regex, rule in patterns:
            if re.search(regex, stripped, flags=re.IGNORECASE):
                violations.append({
                    "rule": rule,
                    "line": lineno,
                    "snippet": stripped.strip()[:120],
                })
    return violations


def _check_disallowed_elements(html: str) -> List[Dict[str, Any]]:
    """Use BeautifulSoup to count occurrences of disallowed tags.
    Falls back to regex if bs4 unavailable.
    """
    violations: List[Dict[str, Any]] = []

    # 先用 regex 找行號
    if _HAS_BS4:
        soup = BeautifulSoup(html, "lxml")
        for tag in ("script", "canvas", "iframe", "object", "embed"):
            for el in soup.find_all(tag):
                violations.append({
                    "rule": f"<{tag}> 元素",
                    "line": el.sourceline if hasattr(el, "sourceline") and el.sourceline else 0,
                    "snippet": str(el)[:120],
                })

    # regex fallback / cross-check
    violations.extend(_scan_patterns(html, _FORBIDDEN_ELEMENTS))

    return _dedupe(violations)


def _check_float_on_non_img(html: str) -> List[Dict[str, Any]]:
    """float: left/right 規則在非 <img> 元素上 BLOCKING.

    簡化策略：regex 抓 float: left/right；如果同區段有 <img> 則寬容。
    實務上若 LLM 對 img 用了 float 也算 OK，這裡以寬鬆策略為主。
    """
    violations = []
    for lineno, line in enumerate(html.splitlines(), start=1):
        stripped = re.sub(r"<!--.*?-->", "", line)
        if re.search(r"float\s*:\s*(?:left|right)\b", stripped, re.IGNORECASE):
            # 寬容：若該行含 <img 則放行
            if "<img" in stripped.lower():
                continue
            violations.append({
                "rule": "float: left / right (非 <img>)",
                "line": lineno,
                "snippet": stripped.strip()[:120],
            })
    return violations


def _check_external_css(html: str) -> List[Dict[str, Any]]:
    return _scan_patterns(html, _EXTERNAL_REFS)


def _check_css_props(html: str) -> List[Dict[str, Any]]:
    return _scan_patterns(html, _FORBIDDEN_CSS_PROPS)


def _check_pseudo(html: str) -> List[Dict[str, Any]]:
    return _scan_patterns(html, _FORBIDDEN_PSEUDO)


def _check_forbidden_attrs(html: str) -> List[Dict[str, Any]]:
    return _scan_patterns(html, _FORBIDDEN_ATTRS)


def _check_forbidden_fonts(html: str) -> List[Dict[str, Any]]:
    return _scan_patterns(html, _FORBIDDEN_FONT_FAMILIES)


def _check_chapter_numbering(html: str) -> List[Dict[str, Any]]:
    """Soft check (warning, not BLOCKING): H1/H2/H3 編號連續性.

    規則：
      - H1 應為「第N章 xxx」或「第N篇 xxx」格式
      - H2 應為「N.M xxx」格式
    不符僅警告，不 BLOCKING。
    """
    warnings: List[Dict[str, Any]] = []
    if not _HAS_BS4:
        return warnings

    soup = BeautifulSoup(html, "lxml")
    for level in (1, 2, 3):
        for h in soup.find_all(f"h{level}"):
            text = h.get_text(strip=True)
            if not text:
                continue
            if level == 1 and not re.match(r"^第[\d一二三四五六七八九十百]+", text):
                warnings.append({
                    "rule": f"h{level} 缺少「第N章」編號 (warning)",
                    "line": h.sourceline if hasattr(h, "sourceline") and h.sourceline else 0,
                    "snippet": text[:120],
                })
            elif level == 2 and not re.match(r"^\d+\.\d+\s", text):
                warnings.append({
                    "rule": f"h{level} 缺少「N.M」編號 (warning)",
                    "line": h.sourceline if hasattr(h, "sourceline") and h.sourceline else 0,
                    "snippet": text[:120],
                })
    return warnings


def _dedupe(violations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate by (rule, line, snippet)."""
    seen = set()
    out = []
    for v in violations:
        key = (v["rule"], v["line"], v["snippet"])
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


# ────────────────────────────────────────────────────────────────────
# Section Opener Rule（v1.1 新增 — D7 修復）
# 對應 references/executor-base.md §3.3.5
# 規則：每個 H2 / H3 後必須至少有 1 段 ≥ 2 句的引導 <p>
# 違規 = WARN 級（不 BLOCKING；寫入 lock.metadata.warnings）
# ────────────────────────────────────────────────────────────────────

# 句末標記（英文 + 全形中文）。至少 2 句才算合格引導段。
_SENTENCE_END_RE = re.compile(r"[.。!?!\uff1f\uff01]")

# 不可直接接在 heading 後的區塊元素（不算 opener）
_BLOCK_TAGS_AFTER_HEADING = {"ul", "ol", "table", "pre", "dl", "blockquote", "hr", "div", "section", "article", "figure"}


def check_section_opener(html: str, source: str = "<string>") -> List[Dict[str, Any]]:
    """Section Opener Rule 檢測（WARN 級）。

    對每個 H2 / H3，檢查其後第一個非空 sibling 是否為 <p>，且 <p> 內文字
    含 ≥ 2 個句末標記（`.` / `。` / `!` / `!` / `?` / `?`）。

    Args:
        html: HTML 字串
        source: 來源標籤（用於 violation 記錄）

    Returns:
        list of warning dict: {rule, line, snippet, severity="WARN", heading_text}

    Note:
        - H1 是章節標題，章節首段已隱含；不在檢測範圍。
        - 第一個 H2/H3（章節開頭）若無前置 H1 也不豁免——仍須有 opener。
        - WARN 級：呼叫端應寫入 lock.metadata.warnings，不應 BLOCKING。
    """
    warnings: List[Dict[str, Any]] = []

    if not _HAS_BS4:
        # 沒有 bs4 視為「無法檢測」；回傳空 list（不誤報）
        return warnings

    soup = BeautifulSoup(html, "lxml")
    body = soup.find("body") or soup

    headings = body.find_all(["h2", "h3"])

    for h in headings:
        level = h.name
        heading_text = h.get_text(strip=True)

        # 找 heading 的下一個非空 sibling
        nxt = h.find_next_sibling()
        while nxt is not None and getattr(nxt, "name", None) is None:
            nxt = nxt.find_next_sibling()

        if nxt is None:
            line_no = h.sourceline if hasattr(h, "sourceline") and h.sourceline else 0
            warnings.append({
                "rule": f"Section opener 缺失（{level} 後無內容）",
                "line": line_no,
                "snippet": heading_text[:80],
                "severity": "WARN",
                "heading_text": heading_text,
                "heading_level": level,
            })
            continue

        nxt_name = getattr(nxt, "name", None)

        if nxt_name and nxt_name.lower() in _BLOCK_TAGS_AFTER_HEADING:
            line_no = h.sourceline if hasattr(h, "sourceline") and h.sourceline else 0
            warnings.append({
                "rule": f"Section opener 缺失（{level} 直連 <{nxt_name}>）",
                "line": line_no,
                "snippet": heading_text[:80],
                "severity": "WARN",
                "heading_text": heading_text,
                "heading_level": level,
                "next_tag": nxt_name,
            })
            continue

        if nxt_name and nxt_name.lower() != "p":
            line_no = h.sourceline if hasattr(h, "sourceline") and h.sourceline else 0
            warnings.append({
                "rule": f"Section opener 缺失（{level} 後第一個元素為 <{nxt_name}>，應為 <p>）",
                "line": line_no,
                "snippet": heading_text[:80],
                "severity": "WARN",
                "heading_text": heading_text,
                "heading_level": level,
                "next_tag": nxt_name,
            })
            continue

        if nxt_name and nxt_name.lower() == "p":
            p_text = nxt.get_text(strip=True)
            p_classes = nxt.get("class", []) or []
            if "caption" in p_classes:
                line_no = h.sourceline if hasattr(h, "sourceline") and h.sourceline else 0
                warnings.append({
                    "rule": f"Section opener 缺失（{level} 後第一個元素為 caption）",
                    "line": line_no,
                    "snippet": heading_text[:80],
                    "severity": "WARN",
                    "heading_text": heading_text,
                    "heading_level": level,
                    "next_tag": "p.caption",
                })
                continue

            sentence_count = len(_SENTENCE_END_RE.findall(p_text))
            if sentence_count < 2:
                line_no = h.sourceline if hasattr(h, "sourceline") and h.sourceline else 0
                warnings.append({
                    "rule": f"Section opener 過短（{level} 後 <p> 僅 {sentence_count} 句，需 ≥ 2 句）",
                    "line": line_no,
                    "snippet": p_text[:80],
                    "severity": "WARN",
                    "heading_text": heading_text,
                    "heading_level": level,
                    "sentence_count": sentence_count,
                })
                continue

    return warnings


def write_warnings_to_lock(lock_path: Path, warnings: List[Dict[str, Any]]) -> int:
    """把 warnings 寫入 lock.metadata.warnings（idempotent）。

    lock.metadata.warnings 是非 schema 欄位（與 metadata.progress 同性質），
    用途：給下游 reviewer / 視覺檢查知道哪些小節需要補 opener。

    Args:
        lock_path: report_lock.md 路徑
        warnings: list of warning dict

    Returns:
        寫入的 warning 數量
    """
    try:
        from scripts.report_lock import read_lock_with_body, write_lock
    except ImportError:
        return 0

    if not lock_path.exists():
        return 0

    data, body = read_lock_with_body(lock_path)
    if not isinstance(data, dict):
        return 0
    metadata = data.setdefault("metadata", {})
    existing = metadata.get("warnings", []) or []

    existing_keys = {(w.get("rule", ""), w.get("heading_text", "")): w for w in existing if isinstance(w, dict)}
    added = 0
    for w in warnings:
        key = (w.get("rule", ""), w.get("heading_text", ""))
        if key in existing_keys:
            existing_keys[key].update({k: v for k, v in w.items() if k not in existing_keys[key]})
        else:
            existing.append(w)
            existing_keys[key] = w
            added += 1

    metadata["warnings"] = existing
    write_lock(lock_path, data, body=body)
    return added


# ────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────

def scan_html(html: str, source: str = "<string>") -> QualityReport:
    """Scan HTML; return QualityReport (does NOT raise).

    Use this when you want structured output (e.g. CLI / CI).
    """
    all_violations: List[Dict[str, Any]] = []
    all_violations.extend(_check_disallowed_elements(html))
    all_violations.extend(_check_external_css(html))
    all_violations.extend(_check_css_props(html))
    all_violations.extend(_check_pseudo(html))
    all_violations.extend(_check_float_on_non_img(html))
    all_violations.extend(_check_forbidden_attrs(html))
    all_violations.extend(_check_forbidden_fonts(html))

    all_violations = _dedupe(all_violations)

    stats = {
        "violations_total": len(all_violations),
        "forbidden_elements": sum(1 for v in all_violations if "<" in v["rule"]),
        "forbidden_css": sum(1 for v in all_violations if "display" in v["rule"] or "position" in v["rule"] or "float" in v["rule"]),
        "forbidden_pseudo": sum(1 for v in all_violations if "::" in v["rule"] or ":before" in v["rule"] or ":after" in v["rule"]),
        "external_refs": sum(1 for v in all_violations if "<link" in v["rule"] or "@import" in v["rule"]),
    }

    return QualityReport(
        passed=(len(all_violations) == 0),
        source=source,
        violations=all_violations,
        stats=stats,
    )


def check_html(html: str, source: str = "<string>") -> None:
    """Scan HTML; raise QualityCheckError on FAIL (BLOCKING)."""
    report = scan_html(html, source)
    if not report.passed:
        raise QualityCheckError(report.violations, source)


def check_html_file(path: str | Path) -> None:
    """Convenience: read file then check_html."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"HTML file not found: {p}")
    html = p.read_text(encoding="utf-8")
    check_html(html, source=str(p))


# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────

def _main() -> int:
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(
        description="Quality gate for report HTML (BLOCKING on forbidden patterns).",
    )
    ap.add_argument("html_path", help="Path to HTML file to check")
    ap.add_argument("--json", action="store_true", help="Output JSON report")
    ap.add_argument("--no-fail", action="store_true",
                    help="Do not exit non-zero on FAIL (useful for inspection)")
    args = ap.parse_args()

    p = Path(args.html_path)
    if not p.exists():
        print(f"ERROR: file not found: {p}", file=sys.stderr)
        return 2

    html = p.read_text(encoding="utf-8")
    report = scan_html(html, source=str(p))

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        if report.passed:
            print(f"✅ PASS — {p}")
            print(f"   stats: {report.stats}")
        else:
            print(f"❌ FAIL — {p} ({len(report.violations)} violation(s))")
            for v in report.violations:
                print(f"  line {v['line']}: {v['rule']}")
                print(f"    > {v['snippet']}")

    if not report.passed and not args.no_fail:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())