# Report-master SPEC.md — Architecture Review

**Reviewer:** Senior System Architect (subagent) · **Date:** 2026-06-13 · **Status:** DRAFT v0.1
**Verdict:** *Direction is sound and well-aligned with ppt-master's playbook. Ship MVP after addressing 6 specific gaps below.*

---

## ✅ Strengths

1. **Right positioning, well articulated.** "AI as Report Designer, not Finisher" is the correct framing — it matches ppt-master's philosophy and correctly identifies that reports (vs. slides) are *more* structured, not less. The constraint table in §1 is honest and useful.

2. **HTML as intermediate format is a defensible choice** — and the spec gives the *right* reason: **LLM generation reliability**, not aesthetics. This is the same logic that drove SVG in ppt-master (Section IV.1 of the reverse-engineer doc). Unlike SVG↔PPTX, the HTML world-view is genuinely close to PDF/DOCX (block flow, page model, footnotes, cross-refs) — so the conversion math is easier.

3. **Inheritance from ppt-master is explicit and disciplined.** Spec_lock anti-drift, Eight Confirmations as a *bundled* blocking gate, role-specialized references (Strategist ↔ Executor), `examples/` as golden tests, `docs/rules/` — all five top patterns from the reverse-engineer doc are adopted. This dramatically reduces design risk.

4. **Quality gate placement is correct** — between Stage 2 (HTML gen) and Stage 3 (conversion), checking HTML source, not the converted output. This mirrors ppt-master §4.6 exactly. Post-conversion checks would hide source-level violations.

5. **Output format choice (PDF + DOCX dual)** is the right call for a report system. Unlike slides, reports are often edited post-delivery; DOCX is the edit format, PDF is the delivery format.

---

## ⚠️ Risks / Gaps

### R1. **HTML → DOCX fidelity is much weaker than the spec implies.**
Pandoc's HTML→DOCX is lossy. CSS3 (`grid`, `flexbox`, `position`, `::before/::after`, custom counters) degrades to plain text or is dropped. A spec built on "any HTML works" will produce a beautiful PDF and a broken DOCX.
**Fix:** Define an HTML *subset* (`shared-standards.md`) that pandoc-docx preserves: simple `<table>`, `<img>`, `<h1-h6>`, `<sup>`, `<aside>`, lists, basic `<p>/<div>`. Prohibit CSS Grid/Flex/positioning. Use pandoc's `native_numbering` and `native_spans` extensions. Use `--reference-doc=custom.docx` for branding parity.

### R2. **"Eight Confirmations" don't cover the *hard* report decisions.**
Current 8 are *input* decisions (audience, language). Missing: page size (A4/Letter/Legal/JIS-B5), margins, single vs. double column, line spacing (APA=2.0, IEEE=1.0), header/footer content, language variant (zh-TW vs zh-CN), target page count, asset policy (DPI, fonts).
**Fix:** Promote to **10 Confirmations**; add a `report_lock.md` schema with required vs. optional keys. Make `line_spacing`, `page_size`, `margins`, `language_variant` **required**.

### R3. **No narrative-drift defense beyond `report_lock.md`.**
Reports can be 50+ pages. Re-reading `report_lock.md` per section catches *style* drift, not *narrative* drift (terminology, repeated arguments, broken cross-refs).
**Fix:** Add (a) `glossary.md` Executor reads first; (b) full `report_spec.md` re-read every 5 sections; (c) cross-reference validation in `quality_checker`; (d) per-section continuity prompt.

### R4. **The pipeline lacks an iteration loop.**
ppt-master is fire-and-export because slides are short. Reports need v1 → review → v2.
**Fix:** Add Stage 2.5 `revise` workflow that takes section IDs to regenerate, plus `delta_checker.py` for version diffs. Store `report_v{n}.html`, not overwrites.

### R5. **Mermaid + Chart.js is broken in this stack.**
Both render via browser JS; `weasyprint` has no JS engine, so Mermaid/Chart.js will appear as raw `class="mermaid"` source in the PDF. Silent failure.
**Fix:** Use `mermaid-cli` (`mmdc`) to pre-render to SVG at Stage 2; inline the SVG. For data charts, use server-side `matplotlib`/`pygal` → SVG, or hand-written SVG (ppt-master pattern). **Remove Chart.js.**

### R6. **No font / locale / CJK strategy.**
weasyprint needs fonts installed system-wide; pandoc needs `mainfont`/`CJKmainfont`. CJK + Latin is common in this domain.
**Fix:** Bundle a `fonts/` directory; document resolution order in `shared-standards.md`; have `config.py` fail-fast at project init.

### R7. **No versioning, change-propagation, or CI.**
ppt-master's `update_spec.py` (color/font → propagate to all SVGs) has no report equivalent. Changing citation style requires full reference-list regen.
**Fix:** Plan `update_report.py` from day 1. Commit early to `examples/` as integration tests (`compileall` + slim `quality_checker` over 3 examples).

### R8. **No post-conversion check.**
`quality_checker` runs on HTML. Pandoc and weasyprint silently degrade. The spec has no `export_checker.py`.
**Fix:** Add lightweight post-export check: PDF page count, image presence, font subsetting, DOCX opens cleanly, TOC links clickable. (Mirrors ppt-master's `verify-charts`.)

---

## 🔧 Tech Stack Validation

| Tool | Spec choice | Verdict | Alternative |
|---|---|---|---|
| PDF engine | **weasyprint** | ✅ Correct for CJK + CSS. Better than pdfkit (wkhtmltopdf is abandoned) and lighter than playwright (no headless browser). | Consider `weasyprint` ≥ 60 for CSS Grid partial support; `paged.js` for complex paged-media if needed |
| DOCX engine | **pandoc** | ✅ Correct primary. But add a `mammoth` **round-trip check** to validate DOCX→HTML→DOCX preserves structure. | `python-docx` only for post-processing (not generation) |
| Citation | pandoc-citeproc + CSL | ⚠️ **pandoc-citeproc is deprecated** since pandoc 2.11. Use built-in `--citeproc`. | `betterbib`, `Zotero` CSL files directly |
| Charts | Mermaid + Chart.js | ❌ **Both fail in weasyprint.** See R5. | `matplotlib` (server-side PNG/SVG) or hand-written SVG (matches ppt-master) |
| Math | not specified | ❌ Critical gap | `MathJax` (needs pre-render to SVG) or `KaTeX` server-side via `katex-cli` |
| TOC | tocgen / pandoc | ✅ Pandoc is sufficient with `--toc --toc-depth=N` |
| Footnotes | HTML `<sup><a>` + `<aside>` | ⚠️ Works for PDF; **pandoc HTML→DOCX does not preserve this pattern**. Use pandoc's native `^[note]` Markdown syntax or HTML `<sup>` with `data-footnote` attributes |

---

## 🔁 Pipeline Coherence

The serial pipeline is **right for reports**, but needs 3 tweaks:

1. **Add a "Format Probe" step at Stage 0** — inspect source material and infer report_type before Eight Confirmations. ppt-master does this implicitly; reports need it explicit because the choices (academic vs. business) radically change template behavior.

2. **Move `quality_checker` *inside* Stage 2 as a per-section gate**, not a post-stage gate.** Reports are long; waiting until all sections are generated to find a citation error is wasteful. Section-level blocking is the right granularity.

3. **Stage 3 should be a *batch* (PDF + DOCX in parallel)** — they're independent. The spec implies this implicitly; make it explicit so future implementers don't serialize them.

---

## ❓ What's NOT in the Spec But Should Be

1. **Error taxonomy & retry policy** — ppt-master has 446 lines of `error_helper.py`. The spec names `quality_checker` but not how the system *reacts* to errors.
2. **Asset management** — where do images live, what DPI, what's the licensing policy.
3. **Concurrency stance** — ppt-master explicitly **forbids** parallel sub-agents; the spec should say so for sections too.
4. **Diff/versioning capability** — "what changed between v1 and v2."
5. **Tagged PDF accessibility** (WCAG/Section 508).
6. **UI vs. content localization** — the spec currently mixes these.

---

## 🏗️ Priority Ordering — Top 5 to Build First

1. **`project_manager.py` + `config.py` + `report_lock.md` schema** — the contract for everything else. If this is wrong, nothing downstream works. (Maps to Phase 1 batch 1 items 1+2, but *lock the schema first*.)
2. **`source_to_md/` (PDF + DOCX + URL → Markdown)** — the universal intermediate. All later stages consume Markdown-derived content. Without this, no report can be built from source material.
3. **`html_to_pdf.py` with a *minimal, opinionated* CSS profile** — get one page working end-to-end. This proves the stack (weasyprint + fonts + CJK + footnote pattern) and exposes the "HTML subset" constraint that R1 depends on.
4. **`shared-standards.md` (the HTML/CSS subset) + `quality_checker.py`** — define what "valid report HTML" means *before* you let the LLM generate. This is the single highest-leverage doc in the project.
5. **One full example end-to-end** (e.g., a 5-page technical brief from a Markdown source) — exercises every pipeline stage, becomes the first golden test, and is the demo for wai. Skip Mermaid/math/citations for v1; add them as v1.1.

Everything else (templates, live-preview, citation manager, multiple format types) is v1.1+.

---

## Closing Note

The spec is a faithful port of ppt-master's playbook to a different output format. The biggest risk is **assuming HTML's expressive surface is uniformly available across PDF and DOCX** — it isn't. Bake the HTML subset constraint and per-section quality gates into the design *before* the LLM learns to produce rich HTML that pandoc will silently destroy.

*Note: Telegram ACK not sent — subagent env has no `OPENCLAW_TELEGRAM_BOT_TOKEN`. Main agent can forward the summary if needed.*
