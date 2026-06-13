# delta_checker.py — 報告版本 diff (report_v{n} vs v{n+1})
# 對應 SPEC.md §3.1 + REVIEW.md R4 + Stage 2.5 迭代迴圈
# 用途：用 difflib 對兩版 HTML 報告做 section-level diff
# 輸出：新增 / 刪除 / 修改清單

from __future__ import annotations

import re
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
    ap = argparse.ArgumentParser(description="Section-level diff between two HTML reports.")
    ap.add_argument("html_old", help="Old HTML path")
    ap.add_argument("html_new", help="New HTML path")
    ap.add_argument("--similarity-threshold", type=float, default=0.85)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show-diff", action="store_true", help="Show unified diff for modified sections")
    args = ap.parse_args()

    rep = delta_html(args.html_old, args.html_new,
                     similarity_threshold=args.similarity_threshold)

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