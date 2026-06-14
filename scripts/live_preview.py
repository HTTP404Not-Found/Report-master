"""scripts/live_preview.py — Report-master HTML 即時預覽 CLI helper.

對應 `workflows/live-preview.md` v1 + `tasks.md` T3-7。

> **⚠️ v1.4.0 deprecation 警告**:此工具從 v1.4.0 起為 **legacy opt-in**;
> 預設 `report_gen` pipeline 不再產 PDF(PDF 已從 user-facing output 移除,
> DOCX 是 user-facing 交付物, HTML 是 Stage 2→3 中介產物)。
> `html_to_pdf` 模組本身保留供 opt-in 重新啟用,所以本工具仍可運作,
> 但 **user-facing pipeline 不再依賴它**。
> 如要即時預覽 DOCX 排版, 推薦在 Editor 端用 pandoc 預覽
> 或在瀏覽器裡直接 reload HTML(pipeline 仍會產 HTML 到 `report_output/`)。

用途：
- Watch `report_output/section_N.html` 的變動 → 自動重新渲染 PDF
- 單次渲染模式（`--once`）給 CI / 一次性檢查用
- 整合 `html_to_pdf.py` 作為 render 引擎（不重新發明）
- 可選整合 `quality_checker.py` 做 advisory 檢查
- 可選 `webbrowser` / `playwright` 開啟或刷新瀏覽器

CLI：
  python -m scripts.live_preview --html <path>             # watch 模式
  python -m scripts.live_preview --html <path> --once     # 單次渲染
  python -m scripts.live_preview --html <path> --open-browser --quality-check

設計：
- LivePreviewer class：核心 API；可被 main agent / IDE 整合呼叫
- _cli()：argparse wrapper，給終端機使用者用
- async loop：watchfiles.awatch（fallback 到 polling 同步 loop）
- debounce：合併短時間內多次 file change event
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

# 允許 CLI 直接執行（`python scripts/live_preview.py`）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from watchfiles import awatch  # type: ignore
    _HAS_WATCHFILES = True
except ImportError:  # pragma: no cover — fallback to polling
    awatch = None  # type: ignore
    _HAS_WATCHFILES = False

from scripts.html_to_pdf import (  # noqa: E402
    HTMLToPDFError,
    html_to_pdf,
)

logger = logging.getLogger(__name__)


# ─── 例外 ────────────────────────────────────────────────────────────

class LivePreviewError(Exception):
    """Live preview 基底例外。"""


class HTMLNotFoundError(LivePreviewError):
    """指定的 HTML 檔不存在。"""


class RenderFailedError(LivePreviewError):
    """PDF 渲染失敗。"""


# ─── Result dataclass ────────────────────────────────────────────────

@dataclass
class RenderResult:
    """單次 render 的結果。"""
    html_path: str
    pdf_path: str
    bytes: int
    duration_ms: float
    timestamp: str
    quality_violations: List[Dict[str, Any]] = field(default_factory=list)
    quality_passed: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "html_path": self.html_path,
            "pdf_path": self.pdf_path,
            "bytes": self.bytes,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
            "quality_violations": self.quality_violations,
            "quality_passed": self.quality_passed,
        }


# ─── Core helper ─────────────────────────────────────────────────────

class LivePreviewer:
    """Report-master HTML 即時預覽器。

    使用方式：
        >>> lp = LivePreviewer(html_path=Path("report_output/section_1.html"))
        >>> result = lp.render_once()
        >>> print(result.pdf_path)
        >>> lp.watch()  # 進入 watch loop（Ctrl+C 中斷）
    """

    DEFAULT_DEBOUNCE_MS = 200
    DEFAULT_POLL_INTERVAL_S = 0.5

    def __init__(
        self,
        html_path: Union[str, Path],
        output_pdf: Optional[Union[str, Path]] = None,
        *,
        fonts_dir: Optional[Union[str, Path]] = None,
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        quality_check: bool = False,
        open_browser: bool = False,
        on_render: Optional[Callable[[RenderResult], None]] = None,
        use_polling: bool = False,
    ) -> None:
        self.html_path = Path(html_path).resolve()
        if not self.html_path.exists():
            raise HTMLNotFoundError(f"HTML 檔不存在: {self.html_path}")

        # 預設輸出 PDF = HTML 同目錄 + .pdf 副檔名
        if output_pdf is None:
            self.output_pdf = self.html_path.with_suffix(".pdf")
        else:
            self.output_pdf = Path(output_pdf).resolve()

        self.fonts_dir = Path(fonts_dir).resolve() if fonts_dir else None
        self.debounce_ms = max(0, int(debounce_ms))
        self.poll_interval_s = max(0.05, float(poll_interval_s))
        self.quality_check = bool(quality_check)
        self.open_browser = bool(open_browser)
        self.on_render = on_render
        self.use_polling = bool(use_polling) or not _HAS_WATCHFILES

    # ── 對外 API ────────────────────────────────────────────────────

    def render_once(self) -> RenderResult:
        """單次渲染（不 watch）。"""
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        start = time.perf_counter()
        quality_violations: List[Dict[str, Any]] = []
        quality_passed = True

        # Quality advisory（若啟用）
        if self.quality_check:
            try:
                from scripts.quality_checker import scan_html
                html_text = self.html_path.read_text(encoding="utf-8")
                report = scan_html(html_text, source=str(self.html_path))
                if not report.passed:
                    quality_passed = False
                    quality_violations = report.violations
                    logger.warning(
                        "quality_check: %d violations（advisory，render 仍會進行）",
                        len(quality_violations),
                    )
            except ImportError:
                logger.warning("quality_checker 不可用，跳過 quality advisory")

        # Render
        try:
            out = html_to_pdf(
                html_source=self.html_path,
                output_pdf=self.output_pdf,
                fonts_dir=self.fonts_dir,
            )
        except HTMLToPDFError as e:
            raise RenderFailedError(str(e)) from e

        duration_ms = (time.perf_counter() - start) * 1000.0
        result = RenderResult(
            html_path=str(self.html_path),
            pdf_path=str(out),
            bytes=out.stat().st_size,
            duration_ms=round(duration_ms, 2),
            timestamp=ts,
            quality_violations=quality_violations,
            quality_passed=quality_passed,
        )

        # Notify
        if self.on_render:
            try:
                self.on_render(result)
            except Exception as e:  # noqa: BLE001
                logger.warning("on_render callback 失敗：%s", e)

        if self.open_browser:
            self._open_browser(out)

        return result

    def watch(self) -> List[RenderResult]:
        """Watch loop（同步版本；用 polling）。

        連續監聽 HTML 變動 → 自動 render → 累積結果。
        Ctrl+C 中斷後回傳所有 render 結果。

        Returns:
            每次 render 的 RenderResult list（Ctrl+C 時中斷）
        """
        results: List[RenderResult] = []
        last_mtime = self._safe_mtime(self.html_path)
        # 第一次 render（給使用者一個 baseline PDF）
        try:
            first = self.render_once()
            results.append(first)
        except RenderFailedError as e:
            logger.error("首次 render 失敗：%s", e)
            raise

        logger.info(
            "watch loop 啟動；debounce=%dms, poll=%.0fms, polling=%s",
            self.debounce_ms,
            self.poll_interval_s * 1000,
            self.use_polling,
        )

        try:
            while True:
                time.sleep(self.poll_interval_s)
                cur_mtime = self._safe_mtime(self.html_path)
                if cur_mtime is None:
                    # 檔案被刪除 → 等它回來
                    logger.warning("HTML 檔被刪除，等待重建...")
                    continue
                if last_mtime is None or cur_mtime > last_mtime:
                    # 偵測變動 → debounce → render
                    if self.debounce_ms > 0:
                        time.sleep(self.debounce_ms / 1000.0)
                        cur_mtime = self._safe_mtime(self.html_path)
                        if cur_mtime is None:
                            continue
                    last_mtime = cur_mtime
                    try:
                        result = self.render_once()
                        results.append(result)
                    except RenderFailedError as e:
                        logger.error("render 失敗：%s", e)
        except KeyboardInterrupt:
            logger.info("watch loop 中斷（KeyboardInterrupt）")
        return results

    async def awatch(self) -> List[RenderResult]:
        """Watch loop（async 版本；用 watchfiles.awatch）。

        Returns:
            每次 render 的 RenderResult list（Ctrl+C 時中斷）
        """
        if self.use_polling or not _HAS_WATCHFILES:
            # Fallback to sync polling
            return self.watch()

        results: List[RenderResult] = []
        target = str(self.html_path)
        # 首次 render（baseline）
        try:
            first = self.render_once()
            results.append(first)
        except RenderFailedError as e:
            logger.error("首次 render 失敗：%s", e)
            raise

        logger.info("async watch loop 啟動；debounce=%dms", self.debounce_ms)

        try:
            async for changes in awatch(self.html_path):  # type: ignore[misc]
                matched = any(
                    Path(changed).resolve() == self.html_path
                    for _change, changed in changes
                )
                if not matched:
                    continue
                # Debounce
                if self.debounce_ms > 0:
                    await asyncio.sleep(self.debounce_ms / 1000.0)
                try:
                    result = self.render_once()
                    results.append(result)
                except RenderFailedError as e:
                    logger.error("render 失敗：%s", e)
        except KeyboardInterrupt:
            logger.info("async watch loop 中斷（KeyboardInterrupt）")
        return results

    # ── 內部輔助 ────────────────────────────────────────────────────

    def _safe_mtime(self, path: Path) -> Optional[float]:
        """安全讀取 mtime；檔案不存在回傳 None。"""
        try:
            return path.stat().st_mtime
        except FileNotFoundError:
            return None

    def _open_browser(self, pdf_path: Path) -> None:
        """用 webbrowser 開啟 PDF。"""
        try:
            url = "file://" + str(pdf_path.resolve())
            webbrowser.open(url)
        except Exception as e:  # noqa: BLE001
            logger.warning("開啟瀏覽器失敗：%s", e)


# ─── Default on_render callback ──────────────────────────────────────

def default_on_render(result: RenderResult) -> None:
    """預設的 render 完成 callback：印一行 summary。"""
    print(
        f"✅ PDF written: {result.pdf_path} ({result.bytes} bytes, "
        f"{result.duration_ms:.1f}ms)",
        flush=True,
    )


# ─── CLI ─────────────────────────────────────────────────────────────

def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="report-master live-preview",
        description=(
            "HTML 即時預覽：watch HTML 變動 → 自動重新渲染 PDF。"
            "整合 html_to_pdf + watchfiles，支援單次渲染與 watch 模式。"
        ),
    )
    parser.add_argument(
        "--html", required=True, type=Path,
        help="要 watch 的 HTML 檔路徑（必填）",
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=None,
        help="輸出 PDF 路徑（預設：HTML 同目錄 + .pdf 副檔名）",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="單次渲染模式（不做 watch）",
    )
    parser.add_argument(
        "--open-browser", action="store_true",
        help="render 完成後用 webbrowser 開啟 PDF",
    )
    parser.add_argument(
        "--quality-check", action="store_true",
        help="render 前先跑 quality_checker.scan_html（advisory，不擋 render）",
    )
    parser.add_argument(
        "--debounce-ms", type=int, default=LivePreviewer.DEFAULT_DEBOUNCE_MS,
        help="debounce 時間（毫秒；預設 200）",
    )
    parser.add_argument(
        "--polling", action="store_true",
        help="強制使用 polling 模式（不依賴 watchfiles）",
    )
    parser.add_argument(
        "--poll-interval-s", type=float,
        default=LivePreviewer.DEFAULT_POLL_INTERVAL_S,
        help="polling 模式的檢查間隔（秒；預設 0.5）",
    )
    parser.add_argument(
        "--fonts-dir", type=Path, default=None,
        help="覆蓋 fonts 目錄（預設用 html_to_pdf 的預設）",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="以 JSON 格式輸出最終結果（單次模式可用）",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="安靜模式：只印最終 summary",
    )
    return parser.parse_args(argv)


def _print_header(args: argparse.Namespace, mode: str) -> None:
    """印 header。"""
    if args.quiet:
        return
    print(f"\n🔍 live-preview — {mode}")
    print(f"   watching: {args.html.resolve()}")
    out = args.output.resolve() if args.output else args.html.with_suffix(".pdf").resolve()
    print(f"   output:   {out}")
    print(f"   debounce: {args.debounce_ms}ms")
    print(f"   quality-check: {'on' if args.quality_check else 'off'}")
    print(f"   open-browser: {'on' if args.open_browser else 'off'}")
    print(f"   mode: {'polling' if (args.polling or not _HAS_WATCHFILES) else 'watchfiles'}")
    if mode.startswith("Watch"):
        print("\n⏳ 等待 HTML 變動...（Ctrl+C 結束）\n")


def _cli(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # ── 建 LivePreviewer ──
    on_render = None if args.quiet else default_on_render
    try:
        lp = LivePreviewer(
            html_path=args.html,
            output_pdf=args.output,
            fonts_dir=args.fonts_dir,
            debounce_ms=args.debounce_ms,
            poll_interval_s=args.poll_interval_s,
            quality_check=args.quality_check,
            open_browser=args.open_browser,
            on_render=on_render,
            use_polling=args.polling,
        )
    except HTMLNotFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    # ── 單次模式 ──
    if args.once:
        _print_header(args, "Single render mode")
        try:
            result = lp.render_once()
        except RenderFailedError as e:
            print(f"❌ render 失敗：{e}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        elif args.quiet:
            print(json.dumps({
                "pdf_path": result.pdf_path,
                "bytes": result.bytes,
                "quality_passed": result.quality_passed,
            }))
        # else: on_render 已印 summary
        return 0

    # ── Watch 模式 ──
    _print_header(args, "Watch mode")
    try:
        results = lp.watch()
    except RenderFailedError as e:
        print(f"❌ 首次 render 失敗：{e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        # watch() 內部已處理 KeyboardInterrupt；這裡只是保險
        pass

    if not args.quiet:
        print(f"\n🛑 Watch 結束；總共 render {len(results)} 次")

    if args.json:
        print(json.dumps(
            [r.to_dict() for r in results],
            ensure_ascii=False, indent=2,
        ))

    # 全部 PASS 才回 0（若有 quality FAIL 但 render 成功，仍視為 0）
    return 0


if __name__ == "__main__":
    sys.exit(_cli())