# update_spec.py — SPEC.md 變更偵測 → 影響分析
# 對應 SPEC.md §6.1 R7 + REVIEW.md R7
# 用途：當 SPEC.md / architecture.md / report_lock_schema.md 變更時，
#       列出 affected tasks（從 tasks.md）與 affected scripts（從程式碼）。
#
# 簡單實作：git diff-based；command-line tool

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Optional


@dataclass
class AffectedTask:
    task_id: str
    title: str
    matched_keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class AffectedScript:
    path: str
    matched_keywords: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class UpdateSpecReport:
    spec_path: str
    added_lines: List[str] = field(default_factory=list)
    removed_lines: List[str] = field(default_factory=list)
    changed_keywords: List[str] = field(default_factory=list)
    affected_tasks: List[AffectedTask] = field(default_factory=list)
    affected_scripts: List[AffectedScript] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "spec_path": self.spec_path,
            "added_lines": self.added_lines[:20],
            "removed_lines": self.removed_lines[:20],
            "changed_keywords": self.changed_keywords,
            "affected_tasks": [t.to_dict() for t in self.affected_tasks],
            "affected_scripts": [s.to_dict() for s in self.affected_scripts],
        }


# ────────────────────────────────────────────────────────────────────
# Keyword map (heuristic)
# ────────────────────────────────────────────────────────────────────

# When a SPEC.md section changes, which tasks / scripts are likely affected?
_KEYWORD_MAP: Dict[str, Dict[str, List[str]]] = {
    "字體": {
        "tasks": ["T0-4", "T1-1", "T1-7"],
        "scripts": ["scripts/config.py", "scripts/html_to_pdf.py",
                    "scripts/html_to_docx.py", "fonts/README.md"],
    },
    "font": {
        "tasks": ["T0-4", "T1-1", "T1-7"],
        "scripts": ["scripts/config.py", "scripts/html_to_pdf.py",
                    "scripts/html_to_docx.py", "fonts/README.md"],
    },
    "PDF": {
        "tasks": ["T1-7", "T2-1", "T3-1"],
        "scripts": ["scripts/html_to_pdf.py", "scripts/export_checker.py"],
    },
    "DOCX": {
        "tasks": ["T2-2", "T3-2"],
        "scripts": ["scripts/html_to_docx.py", "scripts/docx_validator.py"],
    },
    "引用": {
        "tasks": ["T0-1", "T1-1"],
        "scripts": ["scripts/footnote_manager.py", "scripts/html_to_docx.py"],
    },
    "citation": {
        "tasks": ["T0-1", "T1-1"],
        "scripts": ["scripts/footnote_manager.py", "scripts/html_to_docx.py"],
    },
    "CSS": {
        "tasks": ["T0-2"],
        "scripts": ["scripts/quality_checker.py", "docs/shared-standards.md"],
    },
    "TOC": {
        "tasks": ["T2-3"],
        "scripts": ["scripts/toc_generator.py"],
    },
    "Confirmations": {
        "tasks": ["T1-2"],
        "scripts": ["scripts/project_manager.py", "docs/report_lock_schema.md"],
    },
    "Stage": {
        "tasks": ["T0-1", "T1-1", "T2-1"],
        "scripts": ["scripts/report_gen.py", "SKILL.md"],
    },
    "mermaid": {
        "tasks": ["T2-4"],
        "scripts": ["scripts/mermaid_renderer.py"],
    },
    "katex": {
        "tasks": ["T2-4"],
        "scripts": ["scripts/katex_renderer.py"],
    },
    "drift": {
        "tasks": ["T0-3"],
        "scripts": ["docs/glossary.md", "scripts/quality_checker.py"],
    },
}


def _detect_keywords(diff_lines: List[str]) -> List[str]:
    """Find which keywords (case-insensitive) appear in the diff."""
    text = "\n".join(diff_lines).lower()
    found = []
    for kw in _KEYWORD_MAP:
        if kw.lower() in text:
            found.append(kw)
    return found


def _match_tasks(tasks_md: str, keywords: List[str]) -> List[AffectedTask]:
    """Find task entries in tasks.md that match the keywords.

    tasks.md format: '- [ ] **T0-1 定義 ...**'
    """
    out = []
    task_re = re.compile(r"^\s*-\s*\[[ x]\]\s+\*\*(T\d+-\d+)\s+([^*]+)\*\*", re.MULTILINE)
    for m in task_re.finditer(tasks_md):
        tid = m.group(1)
        title = m.group(2).strip()
        # Find which keywords match the title
        title_lower = title.lower()
        matched = [kw for kw in keywords if kw.lower() in title_lower]
        if matched:
            out.append(AffectedTask(task_id=tid, title=title, matched_keywords=matched))
    return out


def _match_scripts(scripts_root: Path, keywords: List[str]) -> List[AffectedScript]:
    """Map keywords to known affected scripts (heuristic from KEYWORD_MAP)."""
    out = []
    seen = set()
    for kw in keywords:
        for script in _KEYWORD_MAP.get(kw, {}).get("scripts", []):
            if script in seen:
                continue
            seen.add(script)
            out.append(AffectedScript(path=script, matched_keywords=[kw]))
    return out


# ────────────────────────────────────────────────────────────────────
# Git diff integration
# ────────────────────────────────────────────────────────────────────

def git_diff(spec_path: str, base_ref: str = "HEAD", repo_root: Optional[Path] = None) -> str:
    """Run git diff <base_ref> -- <spec_path> and return the output."""
    repo = repo_root or Path.cwd()
    try:
        proc = subprocess.run(
            ["git", "diff", base_ref, "--", spec_path],
            cwd=str(repo),
            capture_output=True, text=True, check=False,
        )
        return proc.stdout
    except FileNotFoundError:
        return ""


def analyze_spec_change(
    spec_path: Union[str, Path],
    *,
    base_ref: str = "HEAD",
    tasks_md_path: Optional[Union[str, Path]] = None,
    scripts_root: Optional[Union[str, Path]] = None,
    diff_text: Optional[str] = None,
) -> UpdateSpecReport:
    """Analyze a SPEC.md change and list affected tasks / scripts.

    Args:
        spec_path: path to changed spec file.
        base_ref: git ref to diff against (default HEAD).
        tasks_md_path: optional path to tasks.md (default: projects/report-master/tasks.md).
        scripts_root: optional path to scripts/ directory.
        diff_text: optional pre-computed diff (skip git invocation).

    Returns: UpdateSpecReport.
    """
    spec_p = Path(spec_path)
    report = UpdateSpecReport(spec_path=str(spec_p))

    if diff_text is None:
        # Determine repo root: walk up to find .git
        cur = spec_p.resolve()
        repo_root = None
        for parent in [cur] + list(cur.parents):
            if (parent / ".git").exists():
                repo_root = parent
                break
        if repo_root is None:
            repo_root = cur.parent
        rel = str(spec_p.relative_to(repo_root)) if spec_p.is_relative_to(repo_root) else str(spec_p)
        diff_text = git_diff(rel, base_ref=base_ref, repo_root=repo_root)

    added = []
    removed = []
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:].strip())
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:].strip())

    report.added_lines = [l for l in added if l]
    report.removed_lines = [l for l in removed if l]

    keywords = _detect_keywords(report.added_lines + report.removed_lines)
    report.changed_keywords = keywords

    # Tasks
    if tasks_md_path is None:
        # Default heuristic: try ../tasks.md
        candidate = spec_p.parent / "tasks.md"
        if candidate.exists():
            tasks_md_path = candidate
    if tasks_md_path and Path(tasks_md_path).exists():
        tasks_md = Path(tasks_md_path).read_text(encoding="utf-8")
        report.affected_tasks = _match_tasks(tasks_md, keywords)

    # Scripts
    if scripts_root is None:
        candidate = spec_p.parent / "scripts"
        if candidate.exists():
            scripts_root = candidate
    if scripts_root:
        report.affected_scripts = _match_scripts(Path(scripts_root), keywords)

    return report


# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────

def _main() -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Analyze SPEC.md change impact.")
    ap.add_argument("spec_path", help="Path to spec file")
    ap.add_argument("--base-ref", default="HEAD", help="Git base ref (default HEAD)")
    ap.add_argument("--tasks-md", default=None, help="Path to tasks.md")
    ap.add_argument("--scripts-root", default=None, help="Path to scripts/")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rep = analyze_spec_change(
        args.spec_path,
        base_ref=args.base_ref,
        tasks_md_path=args.tasks_md,
        scripts_root=args.scripts_root,
    )

    if args.json:
        print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"📄 Changed: {rep.spec_path}")
        print(f"🔑 Keywords: {rep.changed_keywords or '(none)'}")
        print(f"\n📋 Affected tasks ({len(rep.affected_tasks)}):")
        for t in rep.affected_tasks:
            print(f"  • {t.task_id}: {t.title}  [{', '.join(t.matched_keywords)}]")
        print(f"\n🛠  Affected scripts ({len(rep.affected_scripts)}):")
        for s in rep.affected_scripts:
            print(f"  • {s.path}  [{', '.join(s.matched_keywords)}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())