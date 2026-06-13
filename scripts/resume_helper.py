"""scripts/resume_helper.py — Report-master 斷點續傳 CLI helper.

對應 `workflows/resume-execute.md` v1 + `tasks.md` T3-5。

用途：
- 從 `lock.metadata.progress` 自動接續被中斷的 Executor pipeline
- 內部 import `Executor`（T3-2）並 wrap resume 邏輯
- 提供 state check / gap analysis / conflict resolution 的「先看再跑」介面

CLI：
  python -m scripts.resume_helper --lock <path>                  # 查詢 resume 狀態（無副作用）
  python -m scripts.resume_helper --lock <path> --dry-run       # 顯示接下來要做什麼
  python -m scripts.resume_helper --lock <path> --run           # 實際執行 resume
  python -m scripts.resume_helper --lock <path> --run --rebuild-changed
                                                               # lock 改過就重跑已存在的節

設計：
- ResumeHelper dataclass：pure function 風格，給 main agent / 測試呼叫
- _cli()：argparse wrapper，給終端機使用者用
- gap analysis：以 disk 為準、progress 為 hint（disk_trumps_progress=True）
- conflict detection：對比 lock signature 與 progress 殘留的 signature
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# 允許 CLI 直接執行（`python scripts/resume_helper.py`）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    import yaml  # noqa: F401  （給 lock_signature 用）
except ImportError as e:  # pragma: no cover
    raise ImportError("缺少 PyYAML，請先 `pip install pyyaml`") from e

from scripts.executor import Executor, ExecutorAbort  # noqa: E402
from scripts.report_lock import (  # noqa: E402
    LockError,
    LockFormatError,
    LockMissingFieldsError,
    read_and_validate,
    read_lock_with_body,
    write_lock,
)

logger = logging.getLogger(__name__)


# ─── 例外 ────────────────────────────────────────────────────────────

class ResumeHelperError(Exception):
    """Resume helper 基底例外。"""


class ResumeConflictError(ResumeHelperError):
    """Lock 改動造成衝突，需使用者決策。"""

    def __init__(self, message: str, *, old_sig: Optional[str], new_sig: str):
        self.old_sig = old_sig
        self.new_sig = new_sig
        super().__init__(message)


class ResumeNoopError(ResumeHelperError):
    """沒事可做（已完整 / 已完成）。"""


# ─── Lock signature（給 conflict detection 用） ─────────────────────

# 會影響 HTML 內容呈現的欄位（resume 時若這些欄位改了就 rebuild）
SIGNATURE_FIELDS: List[str] = (
    "fonts",
    "formatting",
    "page_size",
    "margins",
    "line_spacing",
    "language_variant",
    "citation_style",
)


def lock_signature(lock: Dict[str, Any]) -> str:
    """用「會影響內容」的欄位算 fingerprint（12 字 hex）。"""
    blob = yaml.safe_dump(
        {k: lock.get(k) for k in SIGNATURE_FIELDS},
        allow_unicode=True,
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


# ─── Result dataclasses ──────────────────────────────────────────────

@dataclass
class GapAnalysisResult:
    """比對 `lock.sections` 與 disk HTML 的結果。"""
    present: List[int] = field(default_factory=list)  # disk 上有的 section index
    missing: List[int] = field(default_factory=list)  # disk 上缺的 section index

    @property
    def total(self) -> int:
        return len(self.present) + len(self.missing)

    @property
    def all_present(self) -> bool:
        return bool(self.present) and not self.missing


@dataclass
class ConflictInfo:
    """Lock 衝突偵測結果。"""
    detected: bool
    old_signature: Optional[str]  # progress 紀錄的舊 sig；可能為 None
    new_signature: str            # 現 lock 算出的 sig
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResumePlan:
    """Resume 計畫（給 dry-run 印出 + 實際執行共用）。"""
    lock_path: str
    output_dir: str
    total_sections: int
    progress_current: int
    progress_completed: List[int]
    gap: GapAnalysisResult
    conflict: ConflictInfo
    next_start: int                # 從這節開始跑
    will_run: List[int]            # 實際要跑的 sections
    will_skip: List[int]           # 跳過的 sections
    rebuild_changed: bool          # 是否因 lock 改動而重跑
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lock_path": self.lock_path,
            "output_dir": self.output_dir,
            "total_sections": self.total_sections,
            "progress_current": self.progress_current,
            "progress_completed": self.progress_completed,
            "gap": asdict(self.gap),
            "conflict": self.conflict.to_dict(),
            "next_start": self.next_start,
            "will_run": self.will_run,
            "will_skip": self.will_skip,
            "rebuild_changed": self.rebuild_changed,
            "notes": self.notes,
        }


# ─── Core helper ─────────────────────────────────────────────────────

class ResumeHelper:
    """Report-master 斷點續傳 helper。

    使用方式：
        >>> helper = ResumeHelper(lock_path="report_lock.md",
        ...                       output_dir="report_output")
        >>> plan = helper.plan()
        >>> print(plan.will_run)
        [3, 4, 5]
        >>> result = helper.run(plan=plan)  # 實際執行
    """

    DEFAULT_OUTPUT_DIR = "report_output"

    def __init__(
        self,
        lock_path: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None,
        *,
        rebuild_changed: bool = False,
    ) -> None:
        self.lock_path = Path(lock_path)
        if not self.lock_path.exists():
            raise ResumeHelperError(f"lock 檔不存在：{self.lock_path}")
        # 讀 + 驗證（缺欄位 raise LockMissingFieldsError）
        self.lock_data = read_and_validate(str(self.lock_path))
        self.output_dir = Path(output_dir) if output_dir else Path(self.DEFAULT_OUTPUT_DIR)
        self.rebuild_changed = rebuild_changed

    # ── 對外 API ────────────────────────────────────────────────────

    def gap_analysis(self) -> GapAnalysisResult:
        """掃描 `output_dir` 找出哪些 section HTML 存在。"""
        present: List[int] = []
        missing: List[int] = []
        sections = self.lock_data.get("sections", [])
        if not sections:
            return GapAnalysisResult(present=[], missing=[])

        for i, sec in enumerate(sections, 1):
            sec_path = self._section_disk_path(sec, i)
            if sec_path.exists() and sec_path.stat().st_size > 0:
                present.append(i)
            else:
                missing.append(i)
        return GapAnalysisResult(present=present, missing=missing)

    def detect_conflict(self) -> ConflictInfo:
        """比對 progress.lock_signature 與現 lock signature。"""
        new_sig = lock_signature(self.lock_data)
        progress = self.lock_data.get("metadata", {}).get("progress", {})
        old_sig = progress.get("lock_signature")

        if not old_sig:
            # progress 沒記 signature → 不視為衝突（首次 resume 或 progress 被清）
            return ConflictInfo(
                detected=False,
                old_signature=None,
                new_signature=new_sig,
                reason="progress 沒記 lock_signature（首次 resume 或 progress 被清）",
            )

        if old_sig == new_sig:
            return ConflictInfo(
                detected=False,
                old_signature=old_sig,
                new_signature=new_sig,
                reason="signature 一致",
            )

        return ConflictInfo(
            detected=True,
            old_signature=old_sig,
            new_signature=new_sig,
            reason=f"signature 不一致：{old_sig} → {new_sig}",
        )

    def plan(self) -> ResumePlan:
        """計算 resume 計畫（不執行；給 dry-run + 實際 run 共用）。"""
        sections = self.lock_data.get("sections", [])
        total = len(sections)

        progress = self.lock_data.get("metadata", {}).get("progress", {})
        prog_current = int(progress.get("current_section", 0))
        prog_completed: List[int] = list(progress.get("completed_sections", []) or [])

        gap = self.gap_analysis()
        conflict = self.detect_conflict()

        notes: List[str] = []

        # 1. 已完成（progress.status == completed 且 disk 全在）
        if progress.get("status") == "completed" and gap.all_present:
            return ResumePlan(
                lock_path=str(self.lock_path),
                output_dir=str(self.output_dir),
                total_sections=total,
                progress_current=prog_current,
                progress_completed=prog_completed,
                gap=gap,
                conflict=conflict,
                next_start=total + 1,  # 沒事可做
                will_run=[],
                will_skip=gap.present,
                rebuild_changed=self.rebuild_changed,
                notes=["progress.status=completed 且 disk 全在；無需 resume"],
            )

        # 2. disk 為準、progress 為 hint
        disk_completed = gap.present

        # 3. 衝突 → rebuild_changed 決定
        if conflict.detected and self.rebuild_changed:
            # 全跑（含已存在的）
            will_run = list(range(1, total + 1))
            will_skip = []
            notes.append(
                f"⚠️  衝突偵測 + --rebuild-changed：重跑全部 {total} 節"
            )
            next_start = 1
        else:
            # 只補缺的（disk 沒有的）
            will_run = gap.missing
            will_skip = gap.present
            next_start = (min(will_run) if will_run else total + 1)

        # 校正 progress：disk 領先 progress（disk 比較準）
        if disk_completed and (not prog_completed or max(disk_completed) > max(prog_completed)):
            notes.append(
                f"📐 disk 顯示完成 {max(disk_completed)} 節 "
                f"（progress 說 {max(prog_completed) if prog_completed else 0}）"
                "→ 以 disk 為準"
            )
            self._calibrate_progress(disk_completed)

        # 校正 progress：progress 領先 disk（不該發生，但保險）
        if prog_completed and (not disk_completed or max(prog_completed) > max(disk_completed)):
            notes.append(
                f"⚠️  progress 說完成 {max(prog_completed)} 節 "
                f"但 disk 只有 {max(disk_completed) if disk_completed else 0} 節"
                "→ 把 progress 倒回 disk"
            )
            self._calibrate_progress(disk_completed)

        return ResumePlan(
            lock_path=str(self.lock_path),
            output_dir=str(self.output_dir),
            total_sections=total,
            progress_current=prog_current,
            progress_completed=prog_completed,
            gap=gap,
            conflict=conflict,
            next_start=next_start,
            will_run=will_run,
            will_skip=will_skip,
            rebuild_changed=self.rebuild_changed,
            notes=notes,
        )

    def run(
        self,
        plan: Optional[ResumePlan] = None,
        *,
        restart: bool = False,
    ) -> "ExecutorResult":
        """實際執行 resume（呼叫 Executor.run）。

        Args:
            plan: 預先算好的計畫；若 None 則內部呼叫 self.plan()。
            restart: 強制從頭（會覆蓋 rebuild_changed 與 plan）。

        Returns:
            ExecutorResult（from scripts.executor）

        Note:
            Executor 內部 _write_progress 只記錄「本 run 完成的節」，
            會覆蓋掉之前的 cumulative state。這裡在 run() 之後再做一次
            校正：以 disk 為準把 cumulative progress 寫回 lock。
        """
        if plan is None:
            plan = self.plan()

        exe = Executor(
            lock_path=self.lock_path,
            output_dir=self.output_dir,
        )
        if restart:
            return exe.run(restart=True)
        # 預期 plan.will_run = [3, 4, 5]；Executor 內部會讀 progress 並從 max+1 開始
        result = exe.run(restart=False)

        # 後處理：以 disk 為準，寫入 cumulative progress
        # （修補 Executor._write_progress 覆蓋掉 prior [1, 2] 的問題）
        self._write_cumulative_progress(result)

        return result

    def _write_cumulative_progress(self, result: "ExecutorResult") -> None:
        """以 disk 為準，把 cumulative completed_sections 寫回 lock。"""
        try:
            data, body = read_lock_with_body(str(self.lock_path))
        except (LockFormatError, LockMissingFieldsError) as e:
            logger.warning("讀 lock 失敗：%s", e)
            return

        sections = data.get("sections", [])
        total = len(sections)
        # 重新掃 disk（trust disk, not result.completed_sections）
        completed = []
        for i, sec in enumerate(sections, 1):
            sec_path = self._section_disk_path(sec, i)
            if sec_path.exists() and sec_path.stat().st_size > 0:
                completed.append(i)

        meta = data.setdefault("metadata", {})
        progress = meta.get("progress", {})
        progress["current_section"] = max(completed) if completed else 0
        progress["total_sections"] = total
        progress["completed_sections"] = completed
        progress["last_updated"] = result.timestamp or datetime.now().isoformat(timespec="seconds")
        progress["status"] = (
            "completed" if completed and total and len(completed) >= total
            else "in_progress"
        )
        # 把現 lock 的 signature 順手存起來（給下次 conflict detection 用）
        progress["lock_signature"] = lock_signature(data)
        meta["progress"] = progress
        try:
            write_lock(str(self.lock_path), data, body=body)
        except Exception as e:  # noqa: BLE001
            logger.warning("寫 cumulative progress 失敗：%s", e)

    # ── 內部輔助 ────────────────────────────────────────────────────

    def _section_disk_path(self, section: Dict[str, Any], section_index: int) -> Path:
        """從 section.path 解析；相對路徑掛在 output_dir 下。"""
        raw = section.get("path") or f"section_{section_index}.html"
        p = Path(raw)
        if not p.is_absolute():
            return self.output_dir / p.name
        return p

    def _calibrate_progress(self, disk_completed: List[int]) -> None:
        """把 progress 校正成 disk 的真實狀態。

        不丟 exception；只是「校正」給 disk 與 progress 一致。
        """
        try:
            data, body = read_lock_with_body(str(self.lock_path))
        except (LockFormatError, LockMissingFieldsError):
            return
        meta = data.setdefault("metadata", {})
        progress = meta.get("progress", {})
        progress["current_section"] = max(disk_completed) if disk_completed else 0
        progress["completed_sections"] = disk_completed
        progress["status"] = (
            "completed" if disk_completed and max(disk_completed) == len(self.lock_data.get("sections", []))
            else "in_progress"
        )
        progress["last_updated"] = datetime.now().isoformat(timespec="seconds")
        meta["progress"] = progress
        try:
            write_lock(str(self.lock_path), data, body=body)
        except Exception as e:  # noqa: BLE001
            logger.warning("校正 progress 失敗：%s", e)


# ─── 印出 helper ────────────────────────────────────────────────────

def format_status(helper: ResumeHelper, plan: ResumePlan, *, dry_run: bool) -> str:
    """把 plan 轉成可讀字串（給 CLI 印出用）。"""
    mode = "DRY RUN — 不會實際執行" if dry_run else "Resume — 即將執行"
    lines: List[str] = []
    lines.append(f"\n🔍 Resume Helper — {mode}")
    lines.append(f"   lock: {plan.lock_path}")
    lines.append(f"   output_dir: {plan.output_dir}")
    lines.append("")
    lines.append("📊 進度摘要：")
    lines.append(
        f"   lock.metadata.progress: current_section={plan.progress_current}, "
        f"completed_sections={plan.progress_completed}"
    )
    gap_summary = (
        f"present={plan.gap.present}, missing={plan.gap.missing}"
    )
    lines.append(f"   gap: {gap_summary}")
    lines.append("")
    lines.append("🚦 Conflict Detection：")
    if plan.conflict.detected:
        lines.append(
            f"   ⚠️  {plan.conflict.reason}"
        )
    else:
        lines.append(
            f"   ✓ {plan.conflict.reason} "
            f"(sig={plan.conflict.new_signature})"
        )
    lines.append("")
    lines.append("📋 計畫：")
    if plan.will_run:
        lines.append(
            f"   next start:  section {plan.next_start} "
            f"of {plan.total_sections}"
        )
        lines.append(
            f"   will run:    {plan.will_run}  ({len(plan.will_run)} 節)"
        )
    else:
        lines.append("   will run:    （無；已完整或已 completed）")
    if plan.will_skip:
        lines.append(
            f"   will skip:   {plan.will_skip}  ({len(plan.will_skip)} 節已存在)"
        )
    lines.append(f"   rebuild_changed: {plan.rebuild_changed}")
    if plan.notes:
        lines.append("")
        lines.append("📝 Notes：")
        for n in plan.notes:
            lines.append(f"   {n}")
    lines.append("")
    if dry_run:
        lines.append(
            "💡 取消 --dry-run 即可實際執行："
        )
        lines.append(
            "   python -m scripts.resume_helper --lock "
            f"{plan.lock_path} --run"
        )
    else:
        lines.append(
            "🚀 開始 resume（呼叫 Executor.run()）..."
        )
    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────

def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="report-master resume-helper",
        description=(
            "Stage 2 斷點續傳 CLI helper。"
            "從 lock.metadata.progress 自動接續被中斷的 Executor pipeline。"
        ),
    )
    parser.add_argument(
        "--lock", "-l",
        type=Path,
        required=True,
        help="report_lock.md 路徑",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("report_output"),
        help="section HTML 輸出目錄（預設 report_output/）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只顯示計畫，不實際執行",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="實際執行 resume（呼叫 Executor.run）",
    )
    parser.add_argument(
        "--rebuild-changed",
        action="store_true",
        help="lock signature 不一致時，重跑已存在的節",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="強制從頭（忽略 progress；會覆蓋 --rebuild-changed）",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="以 JSON 格式輸出計畫 / 結果",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="只印最終 summary 行",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # ── 計算 plan ──
    try:
        helper = ResumeHelper(
            lock_path=args.lock,
            output_dir=args.output,
            rebuild_changed=args.rebuild_changed,
        )
    except LockMissingFieldsError as e:
        print(str(e), file=sys.stderr)
        return 1
    except LockFormatError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    except ResumeHelperError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    try:
        plan = helper.plan()
    except ResumeNoopError as e:
        print(f"✅ {e}", file=sys.stderr)
        return 0

    # ── 衝突偵測 → 預設 raise（除非 --rebuild-changed 已加） ──
    if (
        plan.conflict.detected
        and not args.rebuild_changed
        and not args.restart
        and args.run
    ):
        msg = (
            f"\n⚠️  衝突偵測：{plan.conflict.reason}\n"
            "預設策略：保留已存在的 HTML，僅補缺的節。\n"
            "若要套用新 lock 設定重跑已存在的節，加 --rebuild-changed。\n"
            f"舊 sig: {plan.conflict.old_signature}\n"
            f"新 sig: {plan.conflict.new_signature}\n"
        )
        print(msg, file=sys.stderr)
        if args.json:
            print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(format_status(helper, plan, dry_run=True))
        return 2  # 衝突 → return code 2

    # ── dry-run ──
    if args.dry_run or not args.run:
        if args.json:
            print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
        elif args.quiet:
            print(json.dumps({
                "will_run": plan.will_run,
                "will_skip": plan.will_skip,
                "next_start": plan.next_start,
                "conflict": plan.conflict.detected,
            }))
        else:
            print(format_status(helper, plan, dry_run=True))
        return 0

    # ── 實際跑 ──
    if not args.quiet and not args.json:
        print(format_status(helper, plan, dry_run=False))

    try:
        result = helper.run(plan=plan, restart=args.restart)
    except (ExecutorAbort, LockMissingFieldsError) as e:
        print(f"❌ Executor 失敗：{e}", file=sys.stderr)
        return 3

    # ── 印結果 ──
    if args.json:
        print(json.dumps({
            "plan": plan.to_dict(),
            "result": result.to_dict(),
        }, ensure_ascii=False, indent=2))
    else:
        print(f"\n{'='*60}")
        print(f"Resume — 完成")
        print(f"{'='*60}")
        print(f"  passed: {result.passed}")
        print(f"  total_sections: {result.total_sections}")
        print(f"  completed (this run): {result.completed_sections}")
        if result.progress_written:
            print(f"  progress: 寫入 lock ✅")
        if result.stage3_stub_invoked:
            print(f"  stage3: {result.stage3_note}")
        if result.errors:
            print(f"  errors:")
            for e in result.errors:
                print(f"    • {e}")
        print(f"{'='*60}")
    return 0 if result.passed else 3


if __name__ == "__main__":
    sys.exit(_cli())
