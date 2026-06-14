"""scripts/visual_review.py — Report-master 視覺自查 CLI helper.

對應 `workflows/visual-review.md` v1 + `tasks.md` T3-8。

> **⚠️ v1.4.0 deprecation 警告**:此工具從 v1.4.0 起為 **legacy opt-in**;
> 預設 `report_gen` pipeline 不再產 PDF(PDF 已從 user-facing output 移除,
> HTML 是 Stage 2→3 中介產物, DOCX 是 user-facing 交付物)。
> `html_to_pdf` 模組本身保留供 opt-in 重新啟用,所以本工具仍可運作,
> 但 **user-facing pipeline 不再依賴它**。
> 如要視覺 review DOCX, 推薦流程:
>   `soffice --headless --convert-to pdf report_final.docx --outdir /tmp/vr`
>   然後把 `/tmp/vr/report_final.pdf` 餵進本工具的 `--html` 位置
>   (heuristic 只看 HTML 結構; 若只要看 PDF 排版, 用任何 PDF viewer 更直接)。

用途：
- 在 Executor 產出 HTML 之後、使用者正式交付之前，做最後一輪視覺檢查
- 流程：auto-check (quality_checker) → render (html_to_pdf) → visual-inspection
  (heuristic + LLM stub) → report (visual_review.md) → verdict (exit code)

CLI：
  python -m scripts.visual_review --html <path>             # 單節
  python -m scripts.visual_review --dir <dir>               # 整批
  python -m scripts.visual_review --html <path> --verbose    # 顯示完整報告
  python -m scripts.visual_review --html <path> --json       # JSON 輸出
  python -m scripts.visual_review --html <path> --skip-render # 跳過 render

設計：
- VisualReviewer class：核心 API；可被 main agent / CI 整合呼叫
- _cli()：argparse wrapper，給終端機使用者用
- HeuristicInspector：stub visual-inspection（regex + BeautifulSoup）
- 整合 html_to_pdf + quality_checker（不重新發明）
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

# 允許 CLI 直接執行（`python scripts/visual_review.py`）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except ImportError:  # pragma: no cover
    BeautifulSoup = None  # type: ignore
    _HAS_BS4 = False

from scripts.html_to_pdf import (  # noqa: E402
    HTMLToPDFError,
    html_to_pdf,
)

logger = logging.getLogger(__name__)


# ─── 例外 ────────────────────────────────────────────────────────────

class VisualReviewError(Exception):
    """Visual review 基底例外。"""


class NoHTMLFoundError(VisualReviewError):
    """指定路徑下找不到任何 section_*.html。"""


# ─── Finding dataclass ───────────────────────────────────────────────

@dataclass
class Finding:
    """單一 visual finding。"""
    severity: str  # "HIGH" / "MEDIUM" / "LOW"
    rule: str
    line: int
    snippet: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── SectionResult dataclass ─────────────────────────────────────────

@dataclass
class SectionResult:
    """單節 visual review 結果。"""
    html_path: str
    pdf_path: Optional[str]
    quality_passed: bool
    quality_violations: List[Dict[str, Any]]
    render_bytes: int
    render_error: Optional[str]
    findings: List[Finding] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "html_path": self.html_path,
            "pdf_path": self.pdf_path,
            "quality_passed": self.quality_passed,
            "quality_violations": self.quality_violations,
            "render_bytes": self.render_bytes,
            "render_error": self.render_error,
            "findings": [f.to_dict() for f in self.findings],
            "timestamp": self.timestamp,
        }

    @property
    def passed(self) -> bool:
        """PASS = quality 過 + render 成功 + 0 findings。"""
        return (
            self.quality_passed
            and self.render_error is None
            and len(self.findings) == 0
        )


# ─── Heuristic Inspector ─────────────────────────────────────────────

class HeuristicInspector:
    """對 HTML + PDF metadata 做 heuristic visual inspection（stub）。

    不依賴 vision model；只用 regex + BeautifulSoup 對 HTML 結構做推斷。
    對應 `workflows/visual-review.md` §4.3.3 + §9。
    """

    # 章節標題編號 regex
    H1_NUMBERED = re.compile(r"^第[\d一二三四五六七八九十百零]+(章|篇)")
    H2_NUMBERED = re.compile(r"^\d+\.\d+\s")

    def __init__(self, html_text: str, html_path: Path) -> None:
        self.html_text = html_text
        self.html_path = html_path

    def inspect(self) -> List[Finding]:
        """執行所有 heuristic，回傳 finding list。"""
        findings: List[Finding] = []

        findings.extend(self._check_fonts())
        findings.extend(self._check_chapter_numbering())
        findings.extend(self._check_heading_hierarchy())
        findings.extend(self._check_images_and_tables())
        findings.extend(self._check_anchors())
        findings.extend(self._check_empty_section())

        return findings

    # ── 字體檢查 ──────────────────────────────────────────────────

    def _check_fonts(self) -> List[Finding]:
        """檢查字體是否鎖死、是否用了禁用字體。"""
        findings: List[Finding] = []
        for lineno, line in enumerate(self.html_text.splitlines(), start=1):
            stripped = re.sub(r"<!--.*?-->", "", line)
            # 禁用字體
            if re.search(
                r"font-family\s*:[^;]*[\"']?(?:Calibri|Arial|Helvetica|"
                r"Microsoft\s*YaHei|PingFang|Hiragino|微軟正黑體|新細明體)[\"']?",
                stripped,
                re.IGNORECASE,
            ):
                findings.append(Finding(
                    severity="HIGH",
                    rule="禁用字體 (應為 標楷體 / Times New Roman)",
                    line=lineno,
                    snippet=stripped.strip()[:120],
                ))
        return findings

    # ── 章節編號 ──────────────────────────────────────────────────

    def _check_chapter_numbering(self) -> List[Finding]:
        """檢查 H1 / H2 編號格式。"""
        findings: List[Finding] = []
        if not _HAS_BS4:
            return findings

        soup = BeautifulSoup(self.html_text, "lxml")

        for h in soup.find_all("h1"):
            text = h.get_text(strip=True)
            if not text:
                continue
            line_no = h.sourceline if hasattr(h, "sourceline") and h.sourceline else 0
            if not self.H1_NUMBERED.match(text):
                findings.append(Finding(
                    severity="LOW",
                    rule="H1 缺少「第N章/第N篇」編號",
                    line=line_no,
                    snippet=text[:120],
                ))

        for h in soup.find_all("h2"):
            text = h.get_text(strip=True)
            if not text:
                continue
            line_no = h.sourceline if hasattr(h, "sourceline") and h.sourceline else 0
            if not self.H2_NUMBERED.match(text):
                findings.append(Finding(
                    severity="LOW",
                    rule="H2 缺少「N.M」編號",
                    line=line_no,
                    snippet=text[:120],
                ))

        return findings

    # ── 標題層級斷裂 ──────────────────────────────────────────────

    def _check_heading_hierarchy(self) -> List[Finding]:
        """檢查 H1 → H3 跳過 H2 的層級斷裂。"""
        findings: List[Finding] = []
        if not _HAS_BS4:
            return findings

        soup = BeautifulSoup(self.html_text, "lxml")
        headings: List[tuple] = []
        for level in (1, 2, 3):
            for h in soup.find_all(f"h{level}"):
                line_no = h.sourceline if hasattr(h, "sourceline") and h.sourceline else 0
                text = h.get_text(strip=True)[:80]
                headings.append((level, line_no, text))

        # 檢查是否有跳級（H1 → H3, H2 → H4）
        prev_level = 0
        for level, line_no, text in headings:
            if prev_level > 0 and level > prev_level + 1:
                findings.append(Finding(
                    severity="MEDIUM",
                    rule=f"標題層級斷裂 (H{prev_level} → H{level})",
                    line=line_no,
                    snippet=text,
                ))
            prev_level = level

        return findings

    # ── 圖片 / 表格 ──────────────────────────────────────────────

    def _check_images_and_tables(self) -> List[Finding]:
        """檢查圖片 / 表格的 caption、overflow、alt 等。"""
        findings: List[Finding] = []
        if not _HAS_BS4:
            return findings

        soup = BeautifulSoup(self.html_text, "lxml")

        # 圖片檢查
        for img in soup.find_all("img"):
            line_no = img.sourceline if hasattr(img, "sourceline") and img.sourceline else 0
            # alt 缺失
            if not img.get("alt"):
                findings.append(Finding(
                    severity="LOW",
                    rule="<img> 缺少 alt 屬性",
                    line=line_no,
                    snippet=str(img)[:120],
                ))
            # width overflow
            width = img.get("width", "")
            style = img.get("style", "")
            width_match = re.search(r"width\s*:\s*(\d+)\s*px", style, re.IGNORECASE)
            w_val = 0
            try:
                w_val = int(str(width).rstrip("px")) if width else 0
            except ValueError:
                w_val = 0
            if width_match:
                w_val = max(w_val, int(width_match.group(1)))
            if w_val > 600:
                findings.append(Finding(
                    severity="MEDIUM",
                    rule=f"圖片 overflow (width={w_val}px)",
                    line=line_no,
                    snippet=str(img)[:120],
                ))

        # 表格檢查
        for table in soup.find_all("table"):
            line_no = table.sourceline if hasattr(table, "sourceline") and table.sourceline else 0
            # 缺 thead
            if not table.find("thead"):
                findings.append(Finding(
                    severity="MEDIUM",
                    rule="<table> 缺少 <thead>",
                    line=line_no,
                    snippet=str(table)[:120],
                ))
            # colspan 過寬 / 欄位 ≥ 6
            colspans = [int(td.get("colspan", 1)) for td in table.find_all("td")]
            max_colspan = max(colspans) if colspans else 1
            if max_colspan > 2:
                findings.append(Finding(
                    severity="LOW",
                    rule=f"表格 colspan={max_colspan}（過寬）",
                    line=line_no,
                    snippet=str(table)[:120],
                ))

        return findings

    # ── Anchor / 連結 ────────────────────────────────────────────

    def _check_anchors(self) -> List[Finding]:
        """檢查 anchor 是否有效。"""
        findings: List[Finding] = []
        if not _HAS_BS4:
            return findings

        soup = BeautifulSoup(self.html_text, "lxml")

        # 收集所有 id
        ids = {el.get("id") for el in soup.find_all(attrs={"id": True}) if el.get("id")}

        # 收集所有 anchor ref
        for a in soup.find_all("a", attrs={"href": True}):
            href = a.get("href", "")
            if href.startswith("#"):
                target = href[1:]
                if target and target not in ids:
                    line_no = a.sourceline if hasattr(a, "sourceline") and a.sourceline else 0
                    findings.append(Finding(
                        severity="MEDIUM",
                        rule=f"anchor 失效: {href}",
                        line=line_no,
                        snippet=str(a)[:120],
                    ))

        return findings

    # ── 空章節 ───────────────────────────────────────────────────

    def _check_empty_section(self) -> List[Finding]:
        """檢查 H1 / H2 後是否有實質內容。"""
        findings: List[Finding] = []
        if not _HAS_BS4:
            return findings

        soup = BeautifulSoup(self.html_text, "lxml")

        # 找所有 h1，看後面是否有 <p>
        for h in soup.find_all(["h1", "h2"]):
            text_len = 0
            sibling = h.find_next_sibling()
            count = 0
            while sibling and count < 10:
                if sibling.name in ("h1", "h2", "h3"):
                    break
                if sibling.name == "p":
                    text_len += len(sibling.get_text(strip=True))
                sibling = sibling.find_next_sibling()
                count += 1
            if text_len < 50:
                line_no = h.sourceline if hasattr(h, "sourceline") and h.sourceline else 0
                findings.append(Finding(
                    severity="LOW",
                    rule="章節內容過短（< 50 字）",
                    line=line_no,
                    snippet=h.get_text(strip=True)[:80],
                ))

        return findings


# ─── Visual Reviewer ─────────────────────────────────────────────────

class VisualReviewer:
    """Report-master 視覺自查核心。

    使用方式：
        >>> vr = VisualReviewer(html_path=Path("report_output/section_1.html"))
        >>> result = vr.review()
        >>> print(result.passed, result.findings)
    """

    def __init__(
        self,
        html_path: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None,
        *,
        fonts_dir: Optional[Union[str, Path]] = None,
        skip_render: bool = False,
        verbose: bool = False,
    ) -> None:
        self.html_path = Path(html_path).resolve()
        if not self.html_path.exists():
            raise FileNotFoundError(f"HTML 檔不存在: {self.html_path}")

        # output_dir：決定 PDF 寫哪裡、報告寫哪裡
        if output_dir is None:
            self.output_dir = self.html_path.parent
        else:
            self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.fonts_dir = Path(fonts_dir).resolve() if fonts_dir else None
        self.skip_render = bool(skip_render)
        self.verbose = bool(verbose)

    # ── 對外 API ────────────────────────────────────────────────────

    def review(self) -> SectionResult:
        """跑完整 visual review：auto-check + render + inspection。"""
        ts = datetime.now().isoformat(timespec="seconds")
        html_text = self.html_path.read_text(encoding="utf-8")

        # 1️⃣ Auto-check
        quality_passed = True
        quality_violations: List[Dict[str, Any]] = []
        try:
            from scripts.quality_checker import scan_html
            q_report = scan_html(html_text, source=str(self.html_path))
            quality_passed = q_report.passed
            quality_violations = q_report.violations
        except ImportError:
            logger.warning("quality_checker 不可用，跳過 auto-check")

        # 2️⃣ Render
        pdf_path = self.output_dir / (self.html_path.stem + ".pdf")
        render_error: Optional[str] = None
        render_bytes = 0
        if not self.skip_render:
            try:
                out = html_to_pdf(
                    html_source=self.html_path,
                    output_pdf=pdf_path,
                    fonts_dir=self.fonts_dir,
                )
                render_bytes = out.stat().st_size
                pdf_path = out
            except HTMLToPDFError as e:
                render_error = str(e)
                logger.error("render 失敗：%s", e)
        else:
            if pdf_path.exists():
                render_bytes = pdf_path.stat().st_size
            else:
                render_error = "skip-render 但 PDF 不存在"

        # 3️⃣ Visual-inspection（heuristic + LLM stub）
        inspector = HeuristicInspector(html_text, self.html_path)
        findings = inspector.inspect()

        # 把 quality violations 也轉成 findings（HIGH severity）
        for v in quality_violations:
            findings.append(Finding(
                severity="HIGH",
                rule=v.get("rule", "unknown"),
                line=v.get("line", 0),
                snippet=v.get("snippet", "")[:120],
            ))

        # 若 render 失敗，加一條 finding
        if render_error:
            findings.append(Finding(
                severity="HIGH",
                rule="render 失敗",
                line=0,
                snippet=render_error[:120],
            ))

        return SectionResult(
            html_path=str(self.html_path),
            pdf_path=str(pdf_path) if pdf_path.exists() else None,
            quality_passed=quality_passed,
            quality_violations=quality_violations,
            render_bytes=render_bytes,
            render_error=render_error,
            findings=findings,
            timestamp=ts,
        )


# ─── Report builder ─────────────────────────────────────────────────

def _format_finding(f: Finding) -> str:
    """格式化單一 finding 為 markdown 行。"""
    severity_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(f.severity, "⚪")
    return (
        f"- {severity_icon} **[{f.severity}]** line {f.line}: {f.rule}\n"
        f"  - snippet: `{f.snippet}`"
    )


def build_report(results: List[SectionResult], target_desc: str) -> str:
    """把多節結果彙整成 markdown 報告。"""
    ts = datetime.now().isoformat(timespec="seconds")
    total_findings = sum(len(r.findings) for r in results)
    all_passed = all(r.passed for r in results)
    verdict_icon = "✅" if all_passed else "❌"
    verdict_text = "PASS" if all_passed else "FAIL"

    lines: List[str] = []
    lines.append("# Visual Review Report")
    lines.append("")
    lines.append(f"> 產生時間: {ts}")
    lines.append(f"> 檢查範圍: {target_desc}")
    lines.append(f"> 整體判定: {verdict_icon} **{verdict_text}**（{total_findings} 個 findings）")
    lines.append("")
    lines.append("---")
    lines.append("")

    for r in results:
        name = Path(r.html_path).name
        lines.append(f"## {name}")
        lines.append("")
        qc_status = "✅ PASS" if r.quality_passed else "❌ FAIL"
        lines.append(f"- quality_checker: {qc_status}（{len(r.quality_violations)} violations）")
        if r.render_error:
            lines.append(f"- render: ❌ 失敗 — `{r.render_error}`")
        elif r.pdf_path:
            lines.append(f"- render: ✅ {Path(r.pdf_path).name}（{r.render_bytes} bytes）")
        else:
            lines.append("- render: ⏭ skipped")
        lines.append(f"- findings: {len(r.findings)}")
        if r.findings:
            for f in r.findings:
                lines.append("")
                lines.append(_format_finding(f))
        lines.append("")
        lines.append("---")
        lines.append("")

    if all_passed:
        lines.append("✅ 視覺自查通過 — 所有節均通過 quality_checker、render 成功、無 visual findings。")
    else:
        lines.append(f"❌ 視覺自查失敗 — 共 {total_findings} 個 findings，請參考上方各節列表修正。")
    lines.append("")
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────

def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="report-master visual-review",
        description=(
            "視覺自查：在 Executor 產出 HTML 之後、使用者交付之前做最後檢查。"
            "流程：auto-check (quality_checker) → render (html_to_pdf) → "
            "visual-inspection (heuristic) → report (visual_review.md)。\n\n"
            "⚠️ v1.4.0 起此工具為 legacy opt-in（預設 report_gen 不再產 PDF）。"
            "如要視覺 review DOCX，建議先用 `soffice --headless --convert-to pdf "
            "<docx> --outdir <tmp>` 轉成臨時 PDF，再用本工具 review；或直接用 PDF viewer。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--html", type=Path, default=None,
        help="單節 HTML 檔路徑（與 --dir 互斥）",
    )
    parser.add_argument(
        "--dir", type=Path, default=None,
        help="整批目錄路徑（掃描所有 section_*.html；與 --html 互斥）",
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=None,
        help="報告輸出路徑（預設：report_output/visual_review.md）",
    )
    parser.add_argument(
        "--skip-render", action="store_true",
        help="跳過 render 階段（PDF 已存在時用）",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="顯示完整報告到 stdout",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="以 JSON 格式輸出最終結果",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="安靜模式：只印最終 verdict",
    )
    parser.add_argument(
        "--fonts-dir", type=Path, default=None,
        help="覆蓋 fonts 目錄（給 html_to_pdf 用）",
    )
    return parser.parse_args(argv)


def _resolve_html_files(args: argparse.Namespace) -> List[Path]:
    """解析要 review 的 HTML 檔清單。"""
    if args.html:
        if not args.html.exists():
            raise NoHTMLFoundError(f"找不到 HTML: {args.html}")
        return [args.html.resolve()]

    if args.dir:
        if not args.dir.exists() or not args.dir.is_dir():
            raise NoHTMLFoundError(f"找不到目錄: {args.dir}")
        files = sorted(args.dir.glob("section_*.html"))
        if not files:
            raise NoHTMLFoundError(f"目錄 {args.dir} 下無 section_*.html")
        return [f.resolve() for f in files]

    raise NoHTMLFoundError("必須指定 --html 或 --dir")


def _print_header(args: argparse.Namespace, mode: str, count: int) -> None:
    """印 header。"""
    if args.quiet or args.json:
        return
    print(f"\n🔍 visual-review — {mode}")
    if args.html:
        print(f"   target: {args.html.resolve()}")
    else:
        print(f"   target: {args.dir.resolve()}")
    print(f"   files:  {count} 個 section HTML")
    print(f"   render: {'skip' if args.skip_render else 'on'}")
    print(f"   fonts:  {args.fonts_dir or '(default)'}")
    print()


def _cli(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # v1.4.0 deprecation banner（非 quiet / 非 json 模式才印，避免污染 machine-readable output）
    if not args.quiet and not args.json:
        print(
            "⚠️  v1.4.0 起此工具為 legacy opt-in；預設 report_gen pipeline "
            "不再產 PDF。如要視覺 review DOCX，建議先用 soffice 轉臨時 PDF，"
            "或直接用系統 PDF viewer。詳見模組 docstring。"
        )

    # 解析 HTML 檔清單
    try:
        html_files = _resolve_html_files(args)
    except NoHTMLFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2

    mode = "Single section mode" if args.html else "Directory mode"
    _print_header(args, mode, len(html_files))

    # 跑 review
    results: List[SectionResult] = []
    for i, html_path in enumerate(html_files, start=1):
        try:
            vr = VisualReviewer(
                html_path=html_path,
                fonts_dir=args.fonts_dir,
                skip_render=args.skip_render,
                verbose=args.verbose,
            )
            result = vr.review()
        except FileNotFoundError as e:
            print(f"❌ {e}", file=sys.stderr)
            return 2
        results.append(result)

        # 印單節結果
        if not args.quiet and not args.json:
            verdict_icon = "✅" if result.passed else "⚠️"
            print(
                f"{verdict_icon} [{i}/{len(html_files)}] {html_path.name} — "
                f"quality {'PASS' if result.quality_passed else 'FAIL'}, "
                f"render {'OK' if result.render_error is None else 'FAIL'}, "
                f"{len(result.findings)} findings"
            )
            if args.verbose and result.findings:
                for f in result.findings:
                    print(f"   - [{f.severity}] line {f.line}: {f.rule}")
                    print(f"     > {f.snippet}")

    # 彙整 verdict
    all_passed = all(r.passed for r in results)
    total_findings = sum(len(r.findings) for r in results)

    # 寫報告
    default_report_path = Path("report_output/visual_review.md")
    report_path = args.output.resolve() if args.output else default_report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)

    target_desc = (
        f"1 個 HTML 檔: {html_files[0].name}"
        if args.html
        else f"{len(html_files)} 個 HTML 檔（目錄：{args.dir.resolve()}）"
    )
    report_md = build_report(results, target_desc)
    report_path.write_text(report_md, encoding="utf-8")

    # 印 verdict
    if args.json:
        out = {
            "passed": all_passed,
            "total_findings": total_findings,
            "report_path": str(report_path),
            "sections": [r.to_dict() for r in results],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif not args.quiet:
        if all_passed:
            print(f"\n✅ 視覺自查通過")
        else:
            print(f"\n❌ 視覺自查失敗：{total_findings} 個 findings")
        print(f"📄 報告: {report_path}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(_cli())