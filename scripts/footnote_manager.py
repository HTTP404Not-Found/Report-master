# footnote_manager.py — 註腳 / 引用管理 (pandoc  ^[note] 語法)
# 對應 SPEC.md §3.1 + architecture.md §介面定義
# 用途：解析 / 收集 / 重新編號 pandoc-native  ^[note] 註腳
#
# 兩種模式：
#   1. parse_footnotes(md) — 解析 Markdown 內 ^[note] 與 [^id] 編號引用
#   2. renumber(md, mode)   — 重新編號為 1, 2, 3...  (per-document 或 per-section)

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Literal


@dataclass
class Footnote:
    """Single footnote record."""
    raw: str            # original text inside ^[...]
    order: int          # assigned order in output
    original_id: Optional[str] = None  # if [^id] named ref

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class FootnoteReport:
    count: int
    footnotes: List[Footnote] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {"count": self.count, "footnotes": [f.to_dict() for f in self.footnotes]}


# ────────────────────────────────────────────────────────────────────
# Parsing
# ────────────────────────────────────────────────────────────────────

# pandoc  ^[note]  — inline anonymous
_INLINE_FN_RE = re.compile(r"\^\[([^\]]+)\]")

# pandoc  [^id]  — reference to named footnote
_NAMED_REF_RE = re.compile(r"\[\^([\w\-]+)\]")

# pandoc  [^id]: note  — definition block (rare in HTML stage; for completeness)
_NAMED_DEF_RE = re.compile(r"^\[\^([\w\-]+)\]:\s*(.+)$", re.MULTILINE)


def parse_footnotes(markdown: str) -> FootnoteReport:
    """Parse all pandoc-native footnotes from markdown text.

    Captures:
      - ^[inline note]  — anonymous inline footnotes (most common in our pipeline)
      - [^named]        — reference to a named footnote (definition elsewhere)

    Returns: FootnoteReport (ordered by appearance).
    """
    footnotes: List[Footnote] = []
    seen_named_ids = set()

    # Anonymous inline
    for i, m in enumerate(_INLINE_FN_RE.finditer(markdown), start=1):
        footnotes.append(Footnote(raw=m.group(1).strip(), order=i))

    # Named references (if a [^id] appears without a corresponding [^id]: def,
    # it's still counted for cross-ref tracking)
    for m in _NAMED_REF_RE.finditer(markdown):
        fid = m.group(1)
        if fid not in seen_named_ids:
            seen_named_ids.add(fid)
            # Check if there's a definition
            def_match = _NAMED_DEF_RE.search(markdown)
            raw_text = ""
            # find any matching definition
            for dm in _NAMED_DEF_RE.finditer(markdown):
                if dm.group(1) == fid:
                    raw_text = dm.group(2).strip()
                    break
            footnotes.append(Footnote(
                raw=raw_text or f"[named: {fid}]",
                order=len(footnotes) + 1,
                original_id=fid,
            ))

    # Definitions without references (orphan named footnotes)
    for dm in _NAMED_DEF_RE.finditer(markdown):
        fid = dm.group(1)
        if fid not in seen_named_ids:
            footnotes.append(Footnote(
                raw=dm.group(2).strip(),
                order=len(footnotes) + 1,
                original_id=fid,
            ))

    return FootnoteReport(count=len(footnotes), footnotes=footnotes)


# ────────────────────────────────────────────────────────────────────
# Renumbering
# ────────────────────────────────────────────────────────────────────

def renumber_footnotes(
    markdown: str,
    mode: Literal["sequential", "per-section"] = "sequential",
) -> str:
    """Re-number footnote references and definitions.

    Modes:
      - sequential:    1, 2, 3, ... across the whole document (default).
      - per-section:   reset at each H1 boundary.

    Strategy: replace `^[...]` in order; for named `[^id]`, strip the id and
    replace with sequential `^[...]` (pandoc can resolve them by position).

    Note: this is a *normalization* helper. Final numbering is typically
    applied by pandoc during DOCX/PDF conversion; this function is for
    pre-validation / preview.
    """
    counter = [0]

    def next_id():
        counter[0] += 1
        return counter[0]

    if mode == "sequential":
        # Replace [^id] → ^[text content of that named fn]
        # First, build id→raw map
        id_to_raw: Dict[str, str] = {}
        for dm in _NAMED_DEF_RE.finditer(markdown):
            id_to_raw[dm.group(1)] = dm.group(2).strip()

        def repl_named(m):
            fid = m.group(1)
            text = id_to_raw.get(fid, f"[named:{fid}]")
            return f"^[{text}]"

        md = _NAMED_REF_RE.sub(repl_named, markdown)
        # Remove [^id]: definitions (they're inline now)
        md = _NAMED_DEF_RE.sub("", md)
        return md

    elif mode == "per-section":
        # Split by H1, renumber within each section
        sections = re.split(r"(?=^#\s)", markdown, flags=re.MULTILINE)
        out_parts = []
        for sec in sections:
            counter[0] = 0
            id_to_raw = {
                dm.group(1): dm.group(2).strip()
                for dm in _NAMED_DEF_RE.finditer(sec)
            }

            def repl_named(m, _id_map=id_to_raw):
                fid = m.group(1)
                text = _id_map.get(fid, f"[named:{fid}]")
                return f"^[{text}]"

            new_sec = _NAMED_REF_RE.sub(repl_named, sec)
            new_sec = _NAMED_DEF_RE.sub("", new_sec)
            out_parts.append(new_sec)
        return "\n\n".join(out_parts)

    else:
        raise ValueError(f"未知 mode: {mode}")


# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────

def _main() -> int:
    import argparse
    import json
    import sys
    ap = argparse.ArgumentParser(description="Pandoc footnote parser/renumber.")
    ap.add_argument("md", help="Markdown file path")
    ap.add_argument("--mode", choices=["parse", "renumber-sequential", "renumber-per-section"],
                    default="parse")
    args = ap.parse_args()

    text = Path(args.md).read_text(encoding="utf-8")

    if args.mode == "parse":
        rep = parse_footnotes(text)
        print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2))
        return 0
    else:
        mode = "sequential" if args.mode == "renumber-sequential" else "per-section"
        out = renumber_footnotes(text, mode=mode)
        print(out)
        return 0


# Need Path here
from pathlib import Path  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(_main())