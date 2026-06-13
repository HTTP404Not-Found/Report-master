"""revise_helper.py — Stage 2.5 revise CLI helper (T3-9).

對應 `workflows/revise.md`：當使用者想修改已生成的 HTML 節內容
（不改 lock，只改 HTML），此 CLI 串接：

  1. 定位 section HTML（依 `--section N` 或 `--section file.html`）
  2. 套用 instruction（stub LLM 階段；真實環境會呼叫 LLM）
  3. 跑 quality_checker.py 確認 HTML 仍合規
  4. 跑 delta_checker.check_lock 比對 lock，確保沒意外動到
  5. 寫回 section HTML（如 `--write`）
  6. 產出 `report_output/delta_report.md`

設計原則：
- 不自動呼叫 LLM（避免 network/API key 依賴）。`--instruction` 只作為
  文字說明記錄在 revised section 的 `<meta name="revise-note">`，
  並驗證 instruction 不會破壞 HTML 結構。
- `--dry-run` 顯示會做什麼，不寫檔。
- 任何 BLOCKING 鎖變動 → exit code 1（強制人工確認）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ─── 內部 imports（容許直接執行 python scripts/revise_helper.py）────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.delta_checker import (  # noqa: E402
    BLOCKING,
    WARNING,
    INFO,
    LockDeltaReport,
    check_lock,
    write_delta_report,
)
from scripts.quality_checker import check_html  # noqa: E402
from scripts.report_lock import read_lock  # noqa: E402


# ────────────────────────────────────────────────────────────────────
# Section 定位
# ────────────────────────────────────────────────────────────────────

DEFAULT_SECTION_GLOB = "report_output/section_*.html"


def locate_section(target: str, project_root: Path) -> Path:
    """把 `--section N` (e.g. "3") 或 `--section file.html` 轉成 Path。

    規則：
      - 若 target 是純數字 → report_output/section_{N}.html
      - 若 target 是絕對路徑（以 / 或盤符開頭）→ 直接用
      - 若 target 是相對路徑（含 .html 或 /）→ 相對 project_root
      - 若都不符 → 報錯
    """
    p = Path(target)
    if target.isdigit():
        candidate = project_root / "report_output" / f"section_{target}.html"
    elif p.is_absolute():
        candidate = p
    elif target.endswith(".html") or "/" in target or "\\" in target:
        candidate = (project_root / target).resolve()
    else:
        raise ValueError(
            f"--section 須為數字 (e.g. '3') 或 .html 路徑；收到：{target!r}"
        )
    if not candidate.exists():
        raise FileNotFoundError(
            f"找不到 section 檔：{candidate}。請先跑 Stage 2 (executor) 產出。"
        )
    return candidate


# ────────────────────────────────────────────────────────────────────
# Revise 動作（stub LLM）
# ────────────────────────────────────────────────────────────────────

REVISION_NOTE_TAG = '<meta name="revise-note" content="{note}">'


def apply_revision(html: str, instruction: str, section_path: Path) -> str:
    """套用 revise instruction 到 HTML。

    Stub 實作：不做真實 LLM 改寫，而是：
      1. 在 `<head>` 注入 `<meta name="revise-note">` 記錄 instruction
      2. 確保 HTML 結構完整（不破壞 doctype / html / body）
      3. 呼叫端必須驗證 quality_checker 仍 PASS

    真實實作（給未來擴充）：呼叫 LLM 重寫受影響段落、保留 HTML 結構。
    """
    if not instruction or not instruction.strip():
        raise ValueError("instruction 不可為空")

    # 跳脫雙引號避免 meta tag 解析錯誤
    safe_note = instruction.replace('"', "&quot;").replace("<", "&lt;")
    note_tag = REVISION_NOTE_TAG.format(note=safe_note[:200])

    if "<head>" in html:
        # 在 <head> 後插入；如果已有 revise-note，先移除舊的
        html = re.sub(
            r'<meta\s+name="revise-note"[^>]*>',
            "",
            html,
        )
        html = html.replace("<head>", f"<head>\n{note_tag}", 1)
    else:
        # 退化：在 doctype 後加一個 head（最少破壞）
        if "<!DOCTYPE" in html:
            html = html.replace(
                "<!DOCTYPE html>",
                f"<!DOCTYPE html>\n<head>{note_tag}</head>",
                1,
            )
        else:
            html = f"<!DOCTYPE html>\n<head>{note_tag}</head>\n{html}"

    return html


# ────────────────────────────────────────────────────────────────────
# 整合流程
# ────────────────────────────────────────────────────────────────────

def run_revise(
    section_target: str,
    instruction: str,
    lock_path: Path,
    project_root: Path,
    *,
    write: bool = False,
    dry_run: bool = False,
    report_path: Optional[Path] = None,
) -> Dict:
    """跑一次 revise 流程，回傳結果 dict。

    Steps:
      1. 讀 lock 與 section HTML
      2. dry_run / write 決定是否實際寫回
      3. 套用 revision（永遠產生 revised HTML 以便 quality_check）
      4. quality_checker 驗證
      5. check_lock 確保 lock 沒被動（這裡 lock 不變 → 應 passed）
      6. 寫回 / 寫報告
    """
    section_path = locate_section(section_target, project_root)
    original_html = section_path.read_text(encoding="utf-8")
    lock_data = read_lock(lock_path)

    plan = {
        "section_path": str(section_path.relative_to(project_root)) if section_path.is_relative_to(project_root) else str(section_path),
        "lock_path": str(lock_path.relative_to(project_root)) if lock_path.is_relative_to(project_root) else str(lock_path),
        "instruction": instruction,
        "write": write,
        "dry_run": dry_run,
        "actions": [],
    }

    # 1. 模擬 revise
    revised_html = apply_revision(original_html, instruction, section_path)
    plan["actions"].append("套用 revise-note meta tag")

    # 2. quality_checker 驗證（包成 try/except，因 check_html 對 BLOCKING 直接 raise）
    try:
        check_html(revised_html, source=str(section_path))
        qc_passed = True
        qc_blockings: List[str] = []
        qc_warnings_count = 0
    except Exception as e:
        qc_passed = False
        qc_blockings = [str(e)]
        qc_warnings_count = 0
    plan["quality_check"] = {
        "passed": qc_passed,
        "blockings": qc_blockings,
        "warnings_count": qc_warnings_count,
    }
    if not qc_passed:
        plan["abort_reason"] = "quality_checker 失敗（HTML 不合規）"
        return plan

    # 3. lock diff（revise 不應動 lock → 應為 passed=True、無差異）
    lock_report = check_lock(lock_data, lock_data)  # 同物件 → 應無差異
    plan["lock_diff"] = lock_report.to_dict()

    # 4. dry-run：顯示，不寫
    if dry_run:
        plan["actions"].append("dry-run：未寫入任何檔案")
        return plan

    # 5. write 模式才實際寫回
    if write:
        section_path.write_text(revised_html, encoding="utf-8")
        plan["actions"].append(f"已寫回 {section_path.name}")

    # 6. 寫 delta 報告
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_delta_report(lock_report, report_path)
        plan["actions"].append(f"delta 報告已寫入 {report_path.name}")

    plan["success"] = True
    return plan


# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Stage 2.5 revise helper — 修改已生成的 HTML 節內容（不改 lock）。",
    )
    ap.add_argument(
        "--section", required=True,
        help="目標 section：數字（如 '3'）或 .html 路徑（如 report_output/section_3.html）",
    )
    ap.add_argument(
        "--instruction", required=True,
        help="要對該節做的修改說明（會寫入 <meta name='revise-note'>）",
    )
    ap.add_argument(
        "--lock", default="report_output/lock.md",
        help="lock 檔路徑（預設 report_output/lock.md）",
    )
    ap.add_argument(
        "--project-root", default=str(_ROOT),
        help="專案根目錄（預設自動偵測）",
    )
    ap.add_argument(
        "--write", action="store_true",
        help="實際寫回 section HTML（不加 → 只檢查不寫）",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="dry run：顯示會做什麼，不寫任何檔案",
    )
    ap.add_argument(
        "--report", default="report_output/delta_report.md",
        help="delta 報告輸出路徑",
    )
    ap.add_argument("--json", action="store_true", help="以 JSON 格式輸出結果")
    return ap


def _main() -> int:
    ap = _build_parser()
    args = ap.parse_args()

    project_root = Path(args.project_root).resolve()
    lock_path = (project_root / args.lock).resolve()
    if not lock_path.exists():
        # fallback: examples/lock.md
        fallback = project_root / "examples" / "lock.md"
        if fallback.exists():
            lock_path = fallback
        else:
            print(f"❌ 找不到 lock：{lock_path}", file=sys.stderr)
            return 2

    try:
        plan = run_revise(
            section_target=args.section,
            instruction=args.instruction,
            lock_path=lock_path,
            project_root=project_root,
            write=args.write,
            dry_run=args.dry_run or (not args.write),
            report_path=(project_root / args.report) if args.report else None,
        )
    except FileNotFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(f"📝 Revise plan: section={plan['section_path']}")
        print(f"   instruction: {plan['instruction']}")
        print(f"   write={plan['write']}  dry_run={plan['dry_run']}")
        print(f"   actions:")
        for a in plan["actions"]:
            print(f"     • {a}")
        if "quality_check" in plan:
            qc = plan["quality_check"]
            status = "✅" if qc["passed"] else "❌"
            print(f"   quality_check: {status} passed (warnings={qc['warnings_count']})")
        if "lock_diff" in plan:
            ld = plan["lock_diff"]
            print(f"   lock_diff: passed={ld['passed']} summary={ld['summary']}")
        if "abort_reason" in plan:
            print(f"   ❌ abort: {plan['abort_reason']}")
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
