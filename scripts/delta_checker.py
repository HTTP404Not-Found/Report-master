# delta_checker.py — 報告版本 diff (report_v{n} vs v{n+1})
# 對應 SPEC.md §3.1 + REVIEW.md R4 + Stage 2.5 迭代迴圈
# 用途：用 difflib 對兩版 HTML 報告做 section-level diff
# 輸出：新增 / 刪除 / 修改清單

from __future__ import annotations

import re
import json
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher, unified_diff
from pathlib import Path
from typing import List, Dict, Optional, Union


# ────────────────────────────────────────────────────────────────────
# Section parsing
# ────────────────────────────────────────────────────────────────────

def _extract_sections(html: str) -> List[Dict[str, str]]:
    """Split HTML into sections by <h1>...</h1> markers.

    Returns: list of {level, title, content, anchor}.
    """
    # Match <h1 id="...">TITLE</h1> ... up to next <h1> or EOF
    pattern = re.compile(
        r'<h([1-6])(\s+id\s*=\s*["\']([^"\']+)["\'])?[^>]*>(.*?)</h\1>',
        re.IGNORECASE | re.DOTALL,
    )
    sections = []
    matches = list(pattern.finditer(html))

    if not matches:
        # Treat the whole document as one anonymous section
        return [{"level": 0, "title": "(untitled)", "content": html, "anchor": ""}]

    # Pre-section content (before first h1)
    if matches[0].start() > 0:
        sections.append({
            "level": 0,
            "title": "(preamble)",
            "content": html[:matches[0].start()],
            "anchor": "",
        })

    for i, m in enumerate(matches):
        level = int(m.group(1))
        anchor = m.group(3) or ""
        # Strip inner tags from title
        title = re.sub(r"<[^>]+>", "", m.group(4)).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(html)
        sections.append({
            "level": level,
            "title": title,
            "content": html[start:end],
            "anchor": anchor,
        })

    return sections


# ────────────────────────────────────────────────────────────────────
# Diff
# ────────────────────────────────────────────────────────────────────

@dataclass
class SectionDiff:
    anchor: str
    title: str
    status: str  # "unchanged" | "added" | "removed" | "modified"
    similarity: float  # 0..1
    unified_diff: Optional[str] = None  # for modified

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class DeltaReport:
    passed: bool = True
    v_old: str = ""
    v_new: str = ""
    sections: List[SectionDiff] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "passed": self.passed,
            "v_old": self.v_old,
            "v_new": self.v_new,
            "sections": [s.to_dict() for s in self.sections],
            "summary": self.summary,
        }


def _title_key(s: Dict[str, str]) -> str:
    """Stable key for matching sections across versions."""
    return s["anchor"] or s["title"]


# ────────────────────────────────────────────────────────────────────
# Lock diff (Stage 2.5 revise — 對應 T3-9)
# ────────────────────────────────────────────────────────────────────

# 17 個 required 欄位（與 scripts/report_lock.py REQUIRED_FIELDS 對齊）
LOCK_REQUIRED_KEYS = [
    "fonts.cjk", "fonts.latin",
    "formatting.cover", "formatting.toc", "formatting.title",
    "formatting.h1", "formatting.h2", "formatting.h3",
    "formatting.body", "formatting.table", "formatting.caption",
    "page_size", "margins", "line_spacing", "language_variant",
    "citation_style", "output.docx_engine",
]

# BLOCKING（紅燈）：一旦變動會破壞下游 (html_to_pdf / html_to_docx 行為）。
BLOCKING_KEYS = {
    "fonts.cjk",        # 不可改：固定 標楷體
    "fonts.latin",      # 不可改：固定 Times New Roman
    "formatting.cover",
    "formatting.title",
    "page_size",
    "language_variant",
    "output.docx_engine",
}

# warning（黃燈）：次要 formatting / 視覺顯著變動。
# 用前綴匹配：任何 `formatting.h1.*` 子欄位變動也視為 warning（與 h1 同等級）。
WARNING_KEYS = {
    "formatting.h1", "formatting.h2", "formatting.h3",
    "formatting.body", "formatting.table", "formatting.caption", "formatting.toc",
    "margins", "line_spacing",
}
WARNING_PREFIXES = ("formatting.h1.", "formatting.h2.", "formatting.h3.",
                    "formatting.body.", "formatting.table.", "formatting.caption.",
                    "formatting.toc.", "margins.", "line_spacing.")

# info（綠燈）：中繼資料變動，幾乎不影響排版。
# （不在 BLOCKING/WARNING 中的 dotted key）

# 嚴重性常數
BLOCKING = "BLOCKING"
WARNING = "warning"
INFO = "info"
SEVERITY_RANK = {BLOCKING: 3, WARNING: 2, INFO: 1}


@dataclass
class LockDiffEntry:
    """單一 lock 欄位差異。"""
    key: str
    old_value: object
    new_value: object
    severity: str
    reason: str

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class LockDeltaReport:
    """lock diff 整體報告。"""
    passed: bool = True
    entries: List[LockDiffEntry] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "passed": self.passed,
            "entries": [e.to_dict() for e in self.entries],
            "summary": self.summary,
        }


def _severity_for(key: str) -> str:
    if key in BLOCKING_KEYS:
        return BLOCKING
    if key in WARNING_KEYS:
        return WARNING
    for p in WARNING_PREFIXES:
        if key.startswith(p):
            return WARNING
    return INFO


def _reason_for(key: str, severity: str) -> str:
    if key in {"fonts.cjk", "fonts.latin"}:
        return "字體固定不可覆寫（SPEC §3.4.1 / docs/report_lock_schema.md §2）"
    if key == "output.docx_engine":
        return "DOCX 引擎切換會走不同 exporter，需重新驗證"
    if key == "language_variant":
        return "語言變體影響 CSL 與字體對應"
    if key == "page_size":
        return "紙張尺寸變動 → 排版重算、頁碼重編"
    if key.startswith("formatting."):
        return "formatting 變動 → 全節重排版，建議重跑 quality_checker"
    if key in {"margins", "line_spacing"}:
        return "版面幾何變動 → 重跑 quality_checker + PDF/DOCX 預覽"
    return "中繼資料變動，不影響排版"


def check_lock(old_lock: Dict, new_lock: Dict) -> LockDeltaReport:
    """比對兩個 lock 結構差異，回傳含 severity 的報告。

    規則：
      - BLOCKING（紅燈）：fonts / 關鍵 formatting / 結構 → 任一出現 → passed=False
      - warning（黃燈）：h1~h3 / margins / line_spacing 等次要 formatting
      - info（綠燈）：metadata 等非排版欄位

    用於 Stage 2.5 revise：revise 修改 HTML 內容時不應意外動到 lock；
    若動到，依嚴重性決定是否 rollback 或只 warn。
    """
    old_lock = old_lock or {}
    new_lock = new_lock or {}

    flat_old: Dict[str, object] = {}
    flat_new: Dict[str, object] = {}

    def _flatten(d: Dict, prefix: str, out: Dict[str, object]) -> None:
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                _flatten(v, key, out)
            else:
                out[key] = v

    _flatten(old_lock, "", flat_old)
    _flatten(new_lock, "", flat_new)

    keys = sorted(set(list(flat_old.keys()) + list(flat_new.keys())))
    entries: List[LockDiffEntry] = []
    summary = {BLOCKING: 0, WARNING: 0, INFO: 0}
    blocking_found = False

    for k in keys:
        ov = flat_old.get(k)
        nv = flat_new.get(k)
        if ov == nv:
            continue
        sev = _severity_for(k)
        entries.append(LockDiffEntry(
            key=k, old_value=ov, new_value=nv,
            severity=sev, reason=_reason_for(k, sev),
        ))
        summary[sev] = summary.get(sev, 0) + 1
        if sev == BLOCKING:
            blocking_found = True

    return LockDeltaReport(
        passed=not blocking_found,
        entries=entries,
        summary=summary,
    )


def write_delta_report(report, path) -> Path:
    """將 LockDeltaReport 或 DeltaReport 序列化為 markdown 到 path。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    lines: List[str] = []
    lines.append("# Delta Report\n\n")
    lines.append("_產生：Report-master Stage 2.5 (revise workflow)_\n\n")

    if isinstance(report, LockDeltaReport):
        lines.append("## Lock diff\n\n")
        lines.append(f"**Passed:** {'✅' if report.passed else '❌'}\n\n")
        lines.append(f"**Summary:** `{report.summary}`\n\n")
        if not report.entries:
            lines.append("無差異。\n")
        else:
            lines.append("| Severity | Key | Old | New | Reason |\n")
            lines.append("|---|---|---|---|---|\n")
            for e in report.entries:
                ov = json.dumps(e.old_value, ensure_ascii=False) if e.old_value is not None else "—"
                nv = json.dumps(e.new_value, ensure_ascii=False) if e.new_value is not None else "—"
                if len(ov) > 60:
                    ov = ov[:57] + "..."
                if len(nv) > 60:
                    nv = nv[:57] + "..."
                lines.append(f"| {e.severity} | `{e.key}` | `{ov}` | `{nv}` | {e.reason} |\n")
    elif isinstance(report, DeltaReport):
        lines.append("## HTML diff\n\n")
        lines.append(f"**Summary:** `{report.summary}`\n\n")
        for s in report.sections:
            line = f"- [{s.status}] sim={s.similarity:.3f} {s.title}"
            if s.anchor:
                line += f" (#{s.anchor})"
            lines.append(line + "\n")
        modified = [s for s in report.sections if s.status == "modified" and s.unified_diff]
        if modified:
            lines.append("\n## Unified Diffs (modified sections)\n\n")
            for s in modified:
                lines.append(f"### {s.title}\n\n```diff\n{s.unified_diff}\n```\n")
    else:
        lines.append("## Unknown report type\n")

    p.write_text("".join(lines), encoding="utf-8")
    return p


def delta_html(
    html_old: Union[str, Path],
    html_new: Union[str, Path],
    *,
    similarity_threshold: float = 0.85,
) -> DeltaReport:
    """Compute section-level diff between two HTML reports.

    Strategy:
      1. Extract sections from both HTMLs by <h1> (and h2/h3 for nested).
      2. Match sections by anchor (id) if present, else by title.
      3. For each matched pair, compute SequenceMatcher.ratio().
      4. Status:
           - ratio == 1.0           → unchanged
           - threshold < ratio < 1  → modified
           - only in new            → added
           - only in old            → removed

    Args:
        html_old / html_new: HTML strings OR file paths.
        similarity_threshold: below this → modified (default 0.85).

    Returns: DeltaReport.
    """
    if isinstance(html_old, Path) or (isinstance(html_old, str) and Path(html_old).exists()):
        old_text = Path(html_old).read_text(encoding="utf-8")
    else:
        old_text = str(html_old)
    if isinstance(html_new, Path) or (isinstance(html_new, str) and Path(html_new).exists()):
        new_text = Path(html_new).read_text(encoding="utf-8")
    else:
        new_text = str(html_new)

    old_secs = _extract_sections(old_text)
    new_secs = _extract_sections(new_text)

    old_keys = {_title_key(s): s for s in old_secs}
    new_keys = {_title_key(s): s for s in new_secs}

    all_keys = list(dict.fromkeys(list(old_keys.keys()) + list(new_keys.keys())))

    report = DeltaReport(
        v_old=f"<{len(old_text)} chars>" if not Path(html_old).__str__().startswith("<") else "<inline>",
        v_new=f"<{len(new_text)} chars>" if not Path(html_new).__str__().startswith("<") else "<inline>",
    )

    summary = {"added": 0, "removed": 0, "modified": 0, "unchanged": 0}

    for key in all_keys:
        in_old = key in old_keys
        in_new = key in new_keys

        if in_old and not in_new:
            sec = old_keys[key]
            report.sections.append(SectionDiff(
                anchor=sec["anchor"], title=sec["title"],
                status="removed", similarity=0.0,
            ))
            summary["removed"] += 1
        elif in_new and not in_old:
            sec = new_keys[key]
            report.sections.append(SectionDiff(
                anchor=sec["anchor"], title=sec["title"],
                status="added", similarity=0.0,
            ))
            summary["added"] += 1
        else:
            o = old_keys[key]
            n = new_keys[key]
            ratio = SequenceMatcher(None, o["content"], n["content"]).ratio()
            if ratio >= 0.999:
                status = "unchanged"
                summary["unchanged"] += 1
                udiff = None
            elif ratio >= similarity_threshold:
                # small drift
                status = "unchanged"  # consider unchanged for high sim
                summary["unchanged"] += 1
                udiff = None
            else:
                status = "modified"
                summary["modified"] += 1
                udiff = "\n".join(unified_diff(
                    o["content"].splitlines(keepends=True),
                    n["content"].splitlines(keepends=True),
                    fromfile=f"old:{o['title']}", tofile=f"new:{n['title']}",
                    n=2,
                ))
            report.sections.append(SectionDiff(
                anchor=n["anchor"] or o["anchor"], title=n["title"] or o["title"],
                status=status, similarity=round(ratio, 3), unified_diff=udiff,
            ))

    report.summary = summary
    return report


# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────

def _main() -> int:
    import argparse
    import json
    import sys
    ap = argparse.ArgumentParser(description="Section-level diff between two HTML reports (or lock diff for *.lock.md).")
    ap.add_argument("html_old", help="Old HTML path (or *.lock.md for lock diff)")
    ap.add_argument("html_new", help="New HTML path (or *.lock.md for lock diff)")
    ap.add_argument("--similarity-threshold", type=float, default=0.85)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show-diff", action="store_true", help="Show unified diff for modified sections")
    ap.add_argument("--report", help="Write markdown report to this path")
    args = ap.parse_args()

    # 判斷輸入：lock 走 check_lock；HTML 走 delta_html
    old_is_lock = args.html_old.endswith((".lock.md", ".lock.yaml", ".lock.yml"))
    new_is_lock = args.html_new.endswith((".lock.md", ".lock.yaml", ".lock.yml"))

    if old_is_lock and new_is_lock:
        try:
            from scripts.report_lock import read_lock
            old_lock = read_lock(args.html_old)
            new_lock = read_lock(args.html_new)
        except Exception as e:
            print(f"❌ 讀取 lock 失敗: {e}", file=sys.stderr)
            return 2
        rep = check_lock(old_lock, new_lock)
        if args.report:
            write_delta_report(rep, args.report)
            print(f"📝 報告已寫入 {args.report}")
        if args.json:
            print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"Lock diff — passed={rep.passed} summary={rep.summary}")
            for e in rep.entries:
                print(f"  [{e.severity:8}] {e.key}: {e.reason}")
        return 0 if rep.passed else 1

    rep = delta_html(args.html_old, args.html_new,
                     similarity_threshold=args.similarity_threshold)
    if args.report:
        write_delta_report(rep, args.report)
        print(f"📝 報告已寫入 {args.report}")

    if args.json:
        # Truncate large unified_diffs in JSON output
        d = rep.to_dict()
        for s in d["sections"]:
            if s.get("unified_diff"):
                s["unified_diff"] = s["unified_diff"][:500] + "..."
        print(json.dumps(d, ensure_ascii=False, indent=2))
    else:
        print(f"Summary: {rep.summary}")
        for s in rep.sections:
            line = f"  [{s.status:9}] sim={s.similarity:.3f} {s.title}"
            if s.anchor:
                line += f"  (#{s.anchor})"
            print(line)
            if args.show_diff and s.status == "modified" and s.unified_diff:
                print("    " + s.unified_diff.replace("\n", "\n    "))

    return 0


if __name__ == "__main__":
    raise SystemExit(_main())