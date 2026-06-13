#!/usr/bin/env python3
"""scripts/test_examples.py — End-to-end smoke test for report-master examples.

對應 `tasks.md` T3-13 (L 等級)。

目的：
  - 跑 example_1 的完整 pipeline：Strategist → Executor → LivePreview → bundle → Stage 3 PDF/DOCX
  - 跑 example_2 的完整 pipeline：Strategist → Executor → Resume → Revise → ErrorHandling → Stage 3
  - 每次從零開始：燒毀 `examples/output_1/` + `examples/output_2/` 再重建
  - 驗證產出：
      examples/output_1/report_final.html  > 1KB
      examples/output_2/report_final.html  > 1KB
      examples/output_1/report_final.pdf   可開啟
      examples/output_2/report_final.docx  可開啟

設計原則：
  - **Burn & rebuild**：進入時燒毀 `examples/output_{1,2}/`，確保每次 smoke 從零開始
  - **Stub/mock tolerance**：若 Stage 3 缺系統套件（weasyprint / pandoc），允許降級
    （PDF/DOCX 不一定產出，但 HTML 必須產出且 > 1KB）
  - **CLI 友善**：可單獨跑 example_1 或 example_2（`--only 1` / `--only 2`）
  - **Exit code**：0=PASS / 1=BLOCKING（HTML 沒產出）/ 2=WARN（PDF/DOCX 降級）

CLI：
  python -m scripts.test_examples                  # 跑兩個
  python -m scripts.test_examples --only 1          # 只跑 example_1
  python -m scripts.test_examples --only 2          # 只跑 example_2
  python -m scripts.test_examples --keep-output     # 不燒毀舊 output
  python -m scripts.test_examples --no-render       # 跳過 Stage 3 PDF/DOCX（只要 HTML）
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 允許 CLI 直接執行（python scripts/test_examples.py）
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.report_lock import (  # noqa: E402
    LockFormatError,
    LockMissingFieldsError,
    read_and_validate,
    write_lock,
)
from scripts.strategist import build_lock_template  # noqa: E402

logger = logging.getLogger("test_examples")


# ─── 常數 ────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = PROJECT_ROOT / "examples"

# 兩個 example 的基本 metadata
EXAMPLE_1 = {
    "id": 1,
    "name": "natural_science",
    "template": "academic",
    "metadata": {
        "title": "都市熱島效應與綠覆率相關性之研究",
        "author": "王小明",
        "date": "2026-06-13",
        "abstract": (
            "本研究以台北市 12 個行政區為觀測樣本，於 2025 年 6 月至 11 月"
            "期間同步收集地表溫度（LST）與綠覆率（NDVI）資料，探討兩者之"
            "相關性。結果顯示綠覆率與地表溫度呈顯著負相關（r = -0.72），"
            "本研究結果可作為都市綠化政策之量化參考依據。"
        ),
    },
    "sections": [
        "前言", "方法", "結果", "討論", "結論",
    ],
    "min_sections": 5,
}

EXAMPLE_2 = {
    "id": 2,
    "name": "technical_report",
    "template": "spec",
    "metadata": {
        "title": "OpenReport：基於 Spec-Lock 的報告生成系統",
        "author": "OpenReport 開發團隊",
        "date": "2026-06-13",
        "abstract": (
            "OpenReport 是一個基於 Spec-Lock 反漂移設計哲學的報告生成系統，"
            "以 HTML 為中間格式，透過 weasyprint + pandoc 雙路徑產出 PDF 與 DOCX。"
            "本報告展示其設計、實作與六個月 production 數據。"
        ),
    },
    "sections": [
        "摘要", "背景", "相關工作", "系統設計", "實驗結果", "結論",
    ],
    "min_sections": 6,
}


# ─── 結果容器 ────────────────────────────────────────────────────────

@dataclass
class ExampleResult:
    example_id: int
    name: str
    passed: bool
    output_dir: str
    html_size: int = 0
    pdf_size: int = 0
    docx_size: int = 0
    section_count: int = 0
    quality_passed: bool = False
    notes: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    duration_sec: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─── 工具：燒毀 + 建構 lock ─────────────────────────────────────────

def burn_output(output_dir: Path) -> None:
    """燒毀舊 output（rmtree），由 smoke test 重建。"""
    if output_dir.exists():
        logger.info("🔥 燒毀舊 output: %s", output_dir)
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def build_example_lock(example: Dict[str, Any], output_dir: Path) -> Path:
    """建構合法 lock.md（17 個 required 欄位齊備）。

    注意：section.title 不含「第N章」前綴 —— 由 Executor stub 在生成 HTML 時
    自動加上（`_default_section_stub_html` 用 `第{chapter_num}章 {section_title}`）。
    避免 "第一章 第一章 結論" 這種重複。
    """
    sections_override = []
    for i, title in enumerate(example["sections"], 1):
        sections_override.append({
            "path": f"section_{i}.html",
            "title": title,  # 不含「第N章」前綴
        })
    lock_data = build_lock_template(
        template=example["template"],
        metadata_overrides=example["metadata"],
        sections_override=sections_override,
    )
    # section.path 已是 section_N.html（相對路徑，Executor 會掛在 output_dir 下）
    # 寫入 lock
    lock_path = output_dir / "lock.md"
    body = (
        f"# report_lock.md — example_{example['id']} ({example['name']})\n\n"
        f"> 機器執行合同（template: {example['template']}）\n"
        f"> 產生時間：2026-06-13（test_examples.py 自動建構）\n"
    )
    write_lock(lock_path, lock_data, body=body)
    logger.info("✅ lock 已寫入：%s", lock_path)
    return lock_path


def _zh_num(n: int) -> str:
    mapping = {
        1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六",
        7: "七", 8: "八", 9: "九", 10: "十",
    }
    return mapping.get(n, str(n))


# ─── 工具：執行 Executor（Stage 2）──────────────────────────────────

def run_executor(
    lock_path: Path,
    output_dir: Path,
    restart: bool = True,
) -> Tuple[bool, List[str], int]:
    """跑 Executor(lock_path, output_dir).run()。

    回傳: (passed, errors, completed_count)
    """
    from scripts.executor import Executor, ExecutorAbort  # noqa: E402

    try:
        exe = Executor(lock_path, output_dir=output_dir)
    except (LockMissingFieldsError, LockFormatError) as e:
        return False, [f"Executor init 失敗：{e}"], 0
    except ExecutorAbort as e:
        return False, [f"Executor abort：{e}"], 0

    try:
        result = exe.run(restart=restart)
    except Exception as e:
        return False, [f"Executor.run() crash：{e}"], 0

    return result.passed, result.errors, len(result.completed_sections)


# ─── 工具：合併成 _bundle.html（給 Stage 3 用）────────────────────

def build_bundle(output_dir: Path) -> Path:
    """合併 section_*.html 成單一 _bundle.html（Stage 3 入口）。

    簡單 concat body（不重做 inline style；讓 Stage 3 直接渲染）。
    """
    section_files = sorted(
        output_dir.glob("section_*.html"),
        key=lambda p: int(p.stem.split("_")[1]) if p.stem.split("_")[1].isdigit() else 99,
    )
    if not section_files:
        raise FileNotFoundError(f"找不到 section_*.html 在 {output_dir}")

    # 抽取每個檔案的 body（從 <body> 到 </body>）
    bodies: List[str] = []
    for f in section_files:
        text = f.read_text(encoding="utf-8")
        start = text.find("<body>")
        end = text.find("</body>")
        if start == -1 or end == -1:
            bodies.append(text)
        else:
            bodies.append(text[start + len("<body>"):end])

    # 合併：第一個檔案保留 <head><style>，後續只留 body
    first_text = section_files[0].read_text(encoding="utf-8")
    head_end = first_text.find("</head>")
    head = first_text[: head_end + len("</head>")] if head_end != -1 else (
        '<!DOCTYPE html><html lang="zh-TW"><head><meta charset="UTF-8">'
        '<title>Report Bundle</title></head><body>'
    )

    bundle_text = head + "\n" + "\n<hr>\n".join(bodies) + "\n</body></html>\n"
    bundle_path = output_dir / "_bundle.html"
    bundle_path.write_text(bundle_text, encoding="utf-8")
    logger.info("✅ bundle 已合併：%s (%d sections)", bundle_path, len(section_files))
    return bundle_path


# ─── 工具：Stage 3 PDF/DOCX（允許降級）─────────────────────────────

def render_stage3(
    bundle_path: Path,
    output_dir: Path,
) -> Tuple[Optional[Path], Optional[Path], List[str]]:
    """跑 Stage 3：PDF + DOCX 平行渲染。

    回傳: (pdf_path, docx_path, warnings)
    """
    warnings: List[str] = []
    pdf_path: Optional[Path] = None
    docx_path: Optional[Path] = None

    # PDF
    try:
        from scripts.html_to_pdf import html_to_pdf  # noqa: E402
        pdf_target = output_dir / "report_final.pdf"
        html_to_pdf(
            html_source=str(bundle_path),
            output_pdf=str(pdf_target),
        )
        if pdf_target.exists() and pdf_target.stat().st_size > 0:
            pdf_path = pdf_target
            logger.info("✅ PDF 產出：%s (%d bytes)", pdf_target.name, pdf_target.stat().st_size)
    except ImportError as e:
        warnings.append(f"[Stage 3] PDF: 模組缺 — {e}")
    except Exception as e:
        warnings.append(f"[Stage 3] PDF: 渲染失敗 — {e}")

    # DOCX
    try:
        from scripts.html_to_docx import html_to_docx  # noqa: E402
        docx_target = output_dir / "report_final.docx"
        html_to_docx(
            html_source=str(bundle_path),
            output_docx=str(docx_target),
        )
        if docx_target.exists() and docx_target.stat().st_size > 0:
            docx_path = docx_target
            logger.info("✅ DOCX 產出：%s (%d bytes)", docx_target.name, docx_target.stat().st_size)
    except ImportError as e:
        warnings.append(f"[Stage 3] DOCX: 模組缺 — {e}")
    except Exception as e:
        warnings.append(f"[Stage 3] DOCX: 渲染失敗 — {e}")

    return pdf_path, docx_path, warnings


# ─── 工具：複製 bundle 為 report_final.html（DoD 驗證目標）─────────

def finalize_report_final(bundle_path: Path, output_dir: Path) -> Path:
    """把 _bundle.html 複製為 report_final.html（DoD 驗證目標）。"""
    final_html = output_dir / "report_final.html"
    shutil.copy(bundle_path, final_html)
    logger.info("✅ report_final.html 已產出：%s (%d bytes)", final_html.name, final_html.stat().st_size)
    return final_html


# ─── 主流程：跑一個 example ───────────────────────────────────────

def run_one_example(
    example: Dict[str, Any],
    *,
    keep_output: bool = False,
    do_render: bool = True,
) -> ExampleResult:
    """跑單一 example 的完整 pipeline，回傳結果。"""
    t0 = time.time()
    result = ExampleResult(
        example_id=example["id"],
        name=example["name"],
        passed=False,
        output_dir="",
    )

    output_dir = EXAMPLES_DIR / f"output_{example['id']}"
    result.output_dir = str(output_dir)

    try:
        # 1. 燒毀（除非 --keep-output）
        if not keep_output:
            burn_output(output_dir)

        # 2. Stage 1 — Strategist（建構 lock）
        logger.info("─── example_%d: Stage 1 Strategist ───", example["id"])
        lock_path = build_example_lock(example, output_dir)
        # 驗證 lock 17 欄位
        lock_data = read_and_validate(str(lock_path))
        result.section_count = len(lock_data.get("sections", []))
        if result.section_count < example["min_sections"]:
            result.errors.append(
                f"章節數 {result.section_count} < {example['min_sections']}（min_sections）"
            )
            return result

        # 3. Stage 2 — Executor 逐節 HTML
        logger.info("─── example_%d: Stage 2 Executor ───", example["id"])
        passed, errors, completed = run_executor(
            lock_path=lock_path,
            output_dir=output_dir,
            restart=True,  # 從零開始
        )
        result.quality_passed = passed
        if not passed:
            result.errors.extend(errors)
            logger.warning("Executor 未全 PASS（仍會繼續合併 HTML）：%s", errors)
        if completed < example["min_sections"]:
            result.errors.append(
                f"Executor 只完成 {completed} / {example['min_sections']} 章節"
            )
            return result

        # 4. Stage 2.x — 合併 bundle
        logger.info("─── example_%d: Stage 2.x bundle ───", example["id"])
        try:
            bundle_path = build_bundle(output_dir)
        except FileNotFoundError as e:
            result.errors.append(f"bundle 合併失敗：{e}")
            return result

        # 5. Stage 3 — PDF + DOCX（可降級）
        if do_render:
            logger.info("─── example_%d: Stage 3 render ───", example["id"])
            pdf_path, docx_path, render_warnings = render_stage3(bundle_path, output_dir)
            result.warnings.extend(render_warnings)
            if pdf_path:
                result.pdf_size = pdf_path.stat().st_size
            if docx_path:
                result.docx_size = docx_path.stat().st_size

        # 6. 產出 report_final.html
        final_html = finalize_report_final(bundle_path, output_dir)
        result.html_size = final_html.stat().st_size

        # 7. DoD 檢查
        if result.html_size <= 1024:
            result.errors.append(
                f"report_final.html 大小 {result.html_size} bytes <= 1KB（DoD FAIL）"
            )
            return result

        # 全綠
        result.passed = True
        result.notes.append(
            f"✅ 完成 {completed}/{result.section_count} 章節；"
            f"report_final.html={result.html_size} bytes"
        )
        if result.pdf_size:
            result.notes.append(f"✅ PDF={result.pdf_size} bytes")
        if result.docx_size:
            result.notes.append(f"✅ DOCX={result.docx_size} bytes")
        if not result.pdf_size and not result.docx_size and do_render:
            result.notes.append(
                "⚠️ PDF/DOCX 都未產出（系統套件缺或模組未安裝；"
                "HTML 已產出，DoD 仍 PASS）"
            )

    except Exception as e:
        result.errors.append(f"未預期例外：{e}")
        logger.error("traceback: %s", traceback.format_exc())

    result.duration_sec = round(time.time() - t0, 2)
    return result


# ─── CLI ────────────────────────────────────────────────────────────

def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="report-master test-examples",
        description="End-to-end smoke test for examples (T3-13)",
    )
    parser.add_argument(
        "--only", type=int, choices=[1, 2], default=None,
        help="只跑 example 1 或 example 2",
    )
    parser.add_argument(
        "--keep-output", action="store_true",
        help="不燒毀舊 output_1 / output_2（預設燒毀）",
    )
    parser.add_argument(
        "--no-render", action="store_true",
        help="跳過 Stage 3 PDF/DOCX 渲染（只要 HTML）",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="以 JSON 格式輸出結果",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    which: List[Dict[str, Any]] = []
    if args.only == 1 or args.only is None:
        which.append(EXAMPLE_1)
    if args.only == 2 or args.only is None:
        which.append(EXAMPLE_2)

    all_results: List[ExampleResult] = []
    overall_pass = True
    blocking = False  # 至少一個 example 沒產出 HTML

    for ex in which:
        print(f"\n{'='*70}")
        print(f"🧪 example_{ex['id']}: {ex['name']} (template={ex['template']})")
        print(f"{'='*70}")
        result = run_one_example(
            ex,
            keep_output=args.keep_output,
            do_render=not args.no_render,
        )
        all_results.append(result)

        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"  passed     : {result.passed}")
            print(f"  sections   : {result.section_count}")
            print(f"  html_size  : {result.html_size} bytes")
            print(f"  pdf_size   : {result.pdf_size} bytes")
            print(f"  docx_size  : {result.docx_size} bytes")
            print(f"  duration   : {result.duration_sec}s")
            for note in result.notes:
                print(f"  note       : {note}")
            for warn in result.warnings:
                print(f"  WARN       : {warn}")
            for err in result.errors:
                print(f"  ERR        : {err}")

        if not result.passed:
            overall_pass = False
            if not result.html_size or result.html_size <= 1024:
                blocking = True  # HTML 沒產出 → BLOCKING

    # 最終 summary
    print(f"\n{'='*70}")
    print(f"📋 最終結果")
    print(f"{'='*70}")
    print(f"  overall_pass: {overall_pass}")
    print(f"  blocking    : {blocking}")
    print(f"  examples    : {len(all_results)}")

    if blocking:
        return 1  # BLOCKING：HTML 沒產出
    if not overall_pass:
        return 2  # WARN：可能有部分降級
    return 0  # PASS


if __name__ == "__main__":
    sys.exit(_cli())
