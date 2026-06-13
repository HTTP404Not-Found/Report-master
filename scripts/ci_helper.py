"""scripts/ci_helper.py — 本地 CI pre-check（local 版 GitHub Actions）。

對應 tasks.md T3-16（CI 整合測試）：

提供三種 CLI 模式：
  --check-all   全檢（pytest + lint + output files + YAML 驗證）
  --fast        只跑 pytest（跳過 lint + output check）
  --examples    只跑 example output 檢查

對應 GitHub Actions workflow（`.github/workflows/ci.yml`）：
  - step 1: pytest tests/
  - step 2: pytest tests/test_examples.py
  - step 3: python -m scripts.source_to_md.url_to_md --help
  - step 4: flake8 scripts/（--check-all 模式下 lint 本次新增/修改檔案）
  - step 5: 確認 examples/output_1 + examples/output_2/report_final.html 存在且 > 1KB

輸出：
  - JSON report 寫到 `report_output/ci_report.json`
  - 含每個 step 的 pass/fail + elapsed_ms + 訊息
  - 整體 exit code：0 = 全綠；1 = 任一 fail

設計：
  - pytest / flake8 / size check 都用 subprocess 跑（避免 import 汙染）。
  - lint 在 --check-all 模式下只針對「本次 T3-16 新增/修改檔案」
    （scripts/ci_helper.py + tests/test_ci_helper.py），避免被既有
    pre-existing lint issues 擋下；GitHub Actions 仍會跑全專案 lint。
  - 任一 step raise / non-zero exit → 該 step 標 fail，最後彙整。

CLI 範例：
  python -m scripts.ci_helper --check-all
  python -m scripts.ci_helper --fast
  python -m scripts.ci_helper --examples
  python -m scripts.ci_helper --help
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional


# ─── 常數 ─────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_OUTPUT_DIR = _PROJECT_ROOT / "report_output"
DEFAULT_REPORT_PATH = REPORT_OUTPUT_DIR / "ci_report.json"

# 本 helper 新增/修改的檔案（lint 在 --check-all 模式下只掃這些）
LINT_SCOPE_FILES = [
    str(_PROJECT_ROOT / "scripts" / "ci_helper.py"),
    str(_PROJECT_ROOT / "tests" / "test_ci_helper.py"),
]

# 兩個 example 的 output 必須存在且 > 1KB
EXAMPLE_OUTPUTS = [
    _PROJECT_ROOT / "examples" / "output_1" / "report_final.html",
    _PROJECT_ROOT / "examples" / "output_2" / "report_final.html",
]

MIN_OUTPUT_BYTES = 1024

CI_WORKFLOW_PATH = _PROJECT_ROOT / ".github" / "workflows" / "ci.yml"


# ─── 資料結構 ─────────────────────────────────────────────────────────


@dataclass
class StepResult:
    """單一 CI step 的結果。"""

    name: str
    status: str  # "pass" | "fail" | "skipped"
    elapsed_ms: float
    returncode: Optional[int] = None
    message: str = ""
    stdout_tail: str = ""
    stderr_tail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CIReport:
    """完整 CI 報告。"""

    mode: str
    started_at: str
    finished_at: str = ""
    total_elapsed_ms: float = 0.0
    overall: str = "pass"  # "pass" | "fail"
    steps: List[StepResult] = field(default_factory=list)

    def add(self, step: StepResult) -> None:
        self.steps.append(step)
        if step.status == "fail":
            self.overall = "fail"

    def finalize(self) -> None:
        self.total_elapsed_ms = round(
            sum(s.elapsed_ms for s in self.steps), 2
        )

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_elapsed_ms": self.total_elapsed_ms,
            "overall": self.overall,
            "steps": [s.to_dict() for s in self.steps],
        }


# ─── Step runner ───────────────────────────────────────────────────────


def _run_step(
    name: str,
    cmd: List[str],
    cwd: Optional[Path] = None,
    timeout: int = 600,
) -> StepResult:
    """執行單一 CLI 命令；不回 raise，回傳 StepResult。

    規則：
      - returncode 0 → pass
      - non-zero → fail（含 tail）
      - 例外（如 binary 找不到）→ fail（message 含原因）
    """
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = (time.monotonic() - started) * 1000
        status = "pass" if proc.returncode == 0 else "fail"
        return StepResult(
            name=name,
            status=status,
            elapsed_ms=round(elapsed, 2),
            returncode=proc.returncode,
            message=f"{'OK' if status == 'pass' else 'FAILED'} ({' '.join(cmd[:3])}...)",
            stdout_tail=_tail(proc.stdout),
            stderr_tail=_tail(proc.stderr),
        )
    except subprocess.TimeoutExpired as e:
        elapsed = (time.monotonic() - started) * 1000
        return StepResult(
            name=name,
            status="fail",
            elapsed_ms=round(elapsed, 2),
            message=f"TIMEOUT after {timeout}s",
            stderr_tail=_tail(e.stderr.decode("utf-8", errors="replace") if e.stderr else ""),
        )
    except FileNotFoundError as e:
        elapsed = (time.monotonic() - started) * 1000
        return StepResult(
            name=name,
            status="fail",
            elapsed_ms=round(elapsed, 2),
            message=f"command not found: {e}",
        )
    except Exception as e:  # pragma: no cover
        elapsed = (time.monotonic() - started) * 1000
        return StepResult(
            name=name,
            status="fail",
            elapsed_ms=round(elapsed, 2),
            message=f"exception: {type(e).__name__}: {e}",
        )


def _tail(s: str, n: int = 600) -> str:
    if not s:
        return ""
    s = s.rstrip()
    if len(s) <= n:
        return s
    return "..." + s[-n:]


# ─── 各 step 實作 ─────────────────────────────────────────────────────


def step_pytest_full() -> StepResult:
    """step 1: pytest tests/ -q --tb=short。"""
    return _run_step(
        "pytest_full",
        [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=short"],
        timeout=900,
    )


def step_pytest_examples() -> StepResult:
    """step 2: pytest tests/test_examples.py -q。"""
    return _run_step(
        "pytest_examples",
        [sys.executable, "-m", "pytest", "tests/test_examples.py", "-q"],
        timeout=600,
    )


def step_cli_smoke() -> StepResult:
    """step 3: python -m scripts.source_to_md.url_to_md --help。"""
    return _run_step(
        "cli_url_to_md_help",
        [sys.executable, "-m", "scripts.source_to_md.url_to_md", "--help"],
        timeout=60,
    )


def step_lint(scope_files: Optional[List[str]] = None) -> StepResult:
    """step 4: flake8 lint。

    若傳入 scope_files → 只掃該檔案清單（給 --check-all 用）。
    若 None → 掃整個 scripts/（對應 GitHub Actions 的全專案 lint）。
    """
    cmd = [sys.executable, "-m", "flake8", "--max-line-length=120", "--ignore=E501,W503"]
    if scope_files:
        cmd.extend(scope_files)
        name = "lint_scope"
        message_target = f"{len(scope_files)} file(s) in T3-16 scope"
    else:
        cmd.append("scripts/")
        name = "lint_full"
        message_target = "scripts/ (full)"
    step = _run_step(name, cmd, timeout=120)
    if step.status == "fail" and step.returncode == 1:
        step.message = f"flake8 found issues in {message_target}"
    elif step.status == "pass":
        step.message = f"flake8 clean ({message_target})"
    return step


def step_example_outputs() -> StepResult:
    """step 5: 兩個 example 的 report_final.html 都存在且 > 1KB。"""
    started = time.monotonic()
    issues: List[str] = []
    sizes: List[str] = []

    for path in EXAMPLE_OUTPUTS:
        if not path.exists():
            issues.append(f"missing: {path.relative_to(_PROJECT_ROOT)}")
            continue
        size = path.stat().st_size
        sizes.append(f"{path.parent.name}/report_final.html={size}B")
        if size <= MIN_OUTPUT_BYTES:
            issues.append(
                f"too small: {path.relative_to(_PROJECT_ROOT)} = {size} bytes "
                f"(need > {MIN_OUTPUT_BYTES})"
            )

    elapsed = (time.monotonic() - started) * 1000
    if issues:
        return StepResult(
            name="example_outputs",
            status="fail",
            elapsed_ms=round(elapsed, 2),
            message="; ".join(issues),
            stdout_tail=" / ".join(sizes),
        )
    return StepResult(
        name="example_outputs",
        status="pass",
        elapsed_ms=round(elapsed, 2),
        message="all example outputs present and > 1KB",
        stdout_tail=" / ".join(sizes),
    )


def step_yaml_valid() -> StepResult:
    """step 6（_check_all only）: .github/workflows/ci.yml 是 valid YAML。

    用 stdlib yaml 安全載入；fail 時附路徑錯誤訊息。
    """
    started = time.monotonic()
    try:
        import yaml  # PyYAML 已在 venv 內
    except ImportError as e:
        return StepResult(
            name="yaml_valid",
            status="fail",
            elapsed_ms=0.0,
            message=f"PyYAML not available: {e}",
        )
    if not CI_WORKFLOW_PATH.exists():
        return StepResult(
            name="yaml_valid",
            status="fail",
            elapsed_ms=0.0,
            message=f"missing: {CI_WORKFLOW_PATH.relative_to(_PROJECT_ROOT)}",
        )
    try:
        with CI_WORKFLOW_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        elapsed = (time.monotonic() - started) * 1000
        jobs = list((data or {}).get("jobs", {}).keys())
        return StepResult(
            name="yaml_valid",
            status="pass",
            elapsed_ms=round(elapsed, 2),
            message=f"ci.yml valid YAML (jobs={jobs})",
        )
    except Exception as e:
        elapsed = (time.monotonic() - started) * 1000
        return StepResult(
            name="yaml_valid",
            status="fail",
            elapsed_ms=round(elapsed, 2),
            message=f"yaml parse error: {type(e).__name__}: {e}",
        )


# ─── 主流程 ───────────────────────────────────────────────────────────


def _now_iso() -> str:
    import datetime as _dt

    return _dt.datetime.now().isoformat(timespec="seconds")


def _print_step(step: StepResult) -> None:
    icon = {"pass": "✓", "fail": "✗", "skipped": "○"}.get(step.status, "?")
    print(
        f"  [{icon}] {step.name:<22} {step.status:<7} "
        f"{step.elapsed_ms:>8.1f}ms  {step.message}"
    )
    if step.status == "fail" and step.stderr_tail:
        tail = step.stderr_tail
        if len(tail) > 400:
            tail = "..." + tail[-400:]
        print(f"        stderr tail: {tail}")


def run_check_all(report_path: Path) -> int:
    """全檢模式。"""
    rpt = CIReport(mode="check-all", started_at=_now_iso())

    print("▶ Report-master CI pre-check  [check-all]")
    print("=" * 60)

    rpt.add(step_yaml_valid())
    _print_step(rpt.steps[-1])

    rpt.add(step_pytest_full())
    _print_step(rpt.steps[-1])

    rpt.add(step_pytest_examples())
    _print_step(rpt.steps[-1])

    rpt.add(step_cli_smoke())
    _print_step(rpt.steps[-1])

    rpt.add(step_lint(scope_files=LINT_SCOPE_FILES))
    _print_step(rpt.steps[-1])

    rpt.add(step_example_outputs())
    _print_step(rpt.steps[-1])

    rpt.finished_at = _now_iso()
    rpt.finalize()
    _write_report(rpt, report_path)

    print("=" * 60)
    print(
        f"  overall: {rpt.overall.upper()}   "
        f"steps: {len(rpt.steps)}   "
        f"total: {rpt.total_elapsed_ms:.1f}ms"
    )
    print(f"  report → {_display_path(report_path)}")
    return 0 if rpt.overall == "pass" else 1


def run_fast(report_path: Path) -> int:
    """快速模式：只跑 pytest（跳過 lint + output check）。"""
    rpt = CIReport(mode="fast", started_at=_now_iso())

    print("▶ Report-master CI pre-check  [fast]")
    print("=" * 60)

    rpt.add(step_pytest_full())
    _print_step(rpt.steps[-1])

    rpt.finished_at = _now_iso()
    rpt.finalize()
    _write_report(rpt, report_path)

    print("=" * 60)
    print(
        f"  overall: {rpt.overall.upper()}   "
        f"steps: {len(rpt.steps)}   "
        f"total: {rpt.total_elapsed_ms:.1f}ms"
    )
    print(f"  report → {_display_path(report_path)}")
    return 0 if rpt.overall == "pass" else 1


def run_examples(report_path: Path) -> int:
    """example-only 模式：只跑 output 檢查。"""
    rpt = CIReport(mode="examples", started_at=_now_iso())

    print("▶ Report-master CI pre-check  [examples]")
    print("=" * 60)

    rpt.add(step_yaml_valid())
    _print_step(rpt.steps[-1])

    rpt.add(step_example_outputs())
    _print_step(rpt.steps[-1])

    rpt.finished_at = _now_iso()
    rpt.finalize()
    _write_report(rpt, report_path)

    print("=" * 60)
    print(
        f"  overall: {rpt.overall.upper()}   "
        f"steps: {len(rpt.steps)}   "
        f"total: {rpt.total_elapsed_ms:.1f}ms"
    )
    print(f"  report → {_display_path(report_path)}")
    return 0 if rpt.overall == "pass" else 1


def _write_report(rpt: CIReport, report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(rpt.to_dict(), f, ensure_ascii=False, indent=2)


def _display_path(p: Path) -> str:
    """回傳顯示用路徑：若 p 在 _PROJECT_ROOT 內 → 相對；否則 → 絕對。"""
    try:
        return str(p.relative_to(_PROJECT_ROOT))
    except ValueError:
        return str(p)


# ─── CLI ───────────────────────────────────────────────────────────────


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scripts.ci_helper",
        description=(
            "Report-master 本地 CI pre-check。對應 .github/workflows/ci.yml。"
        ),
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check-all",
        action="store_true",
        help="全檢：pytest + lint(本 PR scope) + output check + YAML 驗證",
    )
    mode.add_argument(
        "--fast",
        action="store_true",
        help="只跑 pytest tests/（跳過 lint / output check）",
    )
    mode.add_argument(
        "--examples",
        action="store_true",
        help="只跑 example output 檢查（output_1 + output_2）",
    )
    p.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help=f"JSON 報告輸出路徑（default: {_display_path(DEFAULT_REPORT_PATH)}）",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_argparser()
    args = parser.parse_args(argv)

    report_path = args.report
    if not report_path.is_absolute():
        report_path = _PROJECT_ROOT / report_path

    if args.check_all:
        return run_check_all(report_path)
    if args.fast:
        return run_fast(report_path)
    if args.examples:
        return run_examples(report_path)
    parser.error("specify one of --check-all / --fast / --examples")
    return 2  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
