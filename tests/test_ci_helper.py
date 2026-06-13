"""tests/test_ci_helper.py — T3-16 CI helper 整合測試（≥ 5 pytest cases）。

對應 tasks.md T3-16（CI 整合測試）：

必測（≥ 5 個）：
  1. ci_helper.py 可 import（不 crash）
  2. ci_helper.py --help 不 crash
  3. .github/workflows/ci.yml 是 valid YAML
  4. ci.yml 含有 `pytest tests/` step
  5. ci.yml 含 example output check step（> 1KB 驗證）

補充：
  6. ci.yml 是 GitHub Actions workflow（name + on + jobs 必要欄位）
  7. ci_helper.py 含 LINT_SCOPE_FILES 常數且至少指向自身 + test 檔
  8. ci_helper.py 內部 StepResult / CIReport dataclass 可序列化為 dict
  9. CI workflow on.push + on.pull_request 都觸發 main
 10. ci_helper.py run_examples 不跑 pytest（快速模式之一）

設計：
  - 完全本地、純檔案 I/O + subprocess；不依賴網路。
  - import 失敗 → 該 test 自身 fail（不 skip），方便定位環境問題。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# 讓 scripts.* 可被 import
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import scripts.ci_helper as ci_helper  # noqa: E402


CI_WORKFLOW_PATH = _PROJECT_ROOT / ".github" / "workflows" / "ci.yml"


# ─── 共用 fixtures / helpers ─────────────────────────────────────────


@pytest.fixture(scope="module")
def ci_workflow_yaml() -> dict:
    """載入並 parse ci.yml，整個 module 共用。"""
    assert CI_WORKFLOW_PATH.exists(), f"missing: {CI_WORKFLOW_PATH}"
    with CI_WORKFLOW_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def ci_workflow_text() -> str:
    return CI_WORKFLOW_PATH.read_text(encoding="utf-8")


def _all_step_texts(yaml_data: dict) -> list[str]:
    """把 workflow 內所有 step 的 run shell 命令攤平成 list[str]。"""
    jobs = (yaml_data or {}).get("jobs", {}) or {}
    texts: list[str] = []
    for job in jobs.values():
        for step in (job or {}).get("steps", []) or []:
            run = step.get("run")
            if isinstance(run, str):
                texts.append(run)
            elif isinstance(run, list):
                texts.append("\n".join(run))
    return texts


# ─── 必測 5 個 ────────────────────────────────────────────────────────


def test_ci_helper_imports_without_crash():
    """1. ci_helper.py 可 import（不 crash）。"""
    assert ci_helper is not None
    assert hasattr(ci_helper, "main"), "missing main() entry point"
    assert hasattr(ci_helper, "CIReport"), "missing CIReport dataclass"
    assert hasattr(ci_helper, "StepResult"), "missing StepResult dataclass"


def test_ci_helper_help_does_not_crash():
    """2. ci_helper.py --help 不 crash 且 exit 0。"""
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.ci_helper", "--help"],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"--help crashed: rc={proc.returncode}\n"
        f"stderr: {proc.stderr}\nstdout: {proc.stdout}"
    )
    assert "Report-master" in proc.stdout
    assert "--check-all" in proc.stdout
    assert "--fast" in proc.stdout
    assert "--examples" in proc.stdout


def test_ci_workflow_is_valid_yaml(ci_workflow_yaml: dict):
    """3. .github/workflows/ci.yml 是 valid YAML。"""
    assert ci_workflow_yaml is not None, "ci.yml parsed to None"
    assert isinstance(ci_workflow_yaml, dict), "ci.yml root must be a mapping"


def test_ci_workflow_has_pytest_tests_step(ci_workflow_yaml: dict):
    """4. ci.yml 含有 `pytest tests/` step。"""
    step_texts = _all_step_texts(ci_workflow_yaml)
    joined = "\n".join(step_texts)
    assert "pytest tests/" in joined, (
        "ci.yml is missing a `pytest tests/` step.\n"
        f"Found steps:\n{joined}"
    )
    # 對應 GitHub Actions step 1
    assert "pytest tests/test_examples.py" in joined, (
        "ci.yml is missing `pytest tests/test_examples.py` (step 2)."
    )


def test_ci_workflow_has_example_output_check(ci_workflow_yaml: dict):
    """5. ci.yml 含 example output check step（> 1KB 驗證）。"""
    step_texts = _all_step_texts(ci_workflow_yaml)
    joined = "\n".join(step_texts)
    assert "examples/output_1" in joined, (
        "ci.yml must check examples/output_1"
    )
    assert "examples/output_2" in joined, (
        "ci.yml must check examples/output_2"
    )
    assert "report_final.html" in joined, (
        "ci.yml must verify report_final.html"
    )
    assert "1024" in joined, (
        "ci.yml must enforce the > 1KB (1024 bytes) minimum"
    )


# ─── 補充 5 個 ────────────────────────────────────────────────────────


def test_ci_workflow_is_github_actions_shape(ci_workflow_yaml: dict):
    """6. ci.yml 是 GitHub Actions workflow（必要欄位齊全）。"""
    assert "name" in ci_workflow_yaml, "missing top-level 'name'"
    assert "on" in ci_workflow_yaml or True in ci_workflow_yaml, (
        "missing 'on' trigger (yaml 1.1 parses 'on' as True)"
    )
    assert "jobs" in ci_workflow_yaml, "missing 'jobs' section"
    assert isinstance(ci_workflow_yaml.get("jobs"), dict)
    assert len(ci_workflow_yaml["jobs"]) >= 1, "jobs must have ≥1 entry"

    # test job 必要欄位
    job = next(iter(ci_workflow_yaml["jobs"].values()))
    assert "runs-on" in job, "job missing 'runs-on'"
    assert "steps" in job, "job missing 'steps'"
    assert isinstance(job["steps"], list)
    assert len(job["steps"]) >= 4, "job must have ≥4 steps"


def test_ci_workflow_triggers_push_and_pr_on_main(ci_workflow_yaml: dict):
    """7. ci.yml on.push + on.pull_request 都觸發 main。"""
    on = ci_workflow_yaml.get("on") or ci_workflow_yaml.get(True)
    assert on is not None, "missing 'on' trigger section"
    push = on.get("push") or {}
    pr = on.get("pull_request") or {}
    assert "main" in (push.get("branches") or []), (
        "push trigger must include 'main'"
    )
    assert "main" in (pr.get("branches") or []), (
        "pull_request trigger must include 'main'"
    )


def test_ci_helper_lint_scope_targets_self():
    """8. ci_helper.LINT_SCOPE_FILES 至少含自身 + tests/test_ci_helper.py。"""
    paths = [Path(p).resolve() for p in ci_helper.LINT_SCOPE_FILES]
    self_path = (ci_helper._PROJECT_ROOT / "scripts" / "ci_helper.py").resolve()
    test_path = (ci_helper._PROJECT_ROOT / "tests" / "test_ci_helper.py").resolve()
    assert self_path in paths, f"LINT_SCOPE_FILES missing self: {self_path}"
    assert test_path in paths, f"LINT_SCOPE_FILES missing test: {test_path}"


def test_ci_helper_dataclasses_are_jsonable():
    """9. CIReport / StepResult 可序列化為 JSON（產出 ci_report.json 用）。"""
    step = ci_helper.StepResult(
        name="unit",
        status="pass",
        elapsed_ms=12.5,
        returncode=0,
        message="ok",
    )
    step_dict = step.to_dict()
    # round-trip 必須能 dump 成 JSON
    s = json.dumps(step_dict, ensure_ascii=False)
    assert "unit" in s and "pass" in s

    rpt = ci_helper.CIReport(mode="unit", started_at="2026-06-13T00:00:00")
    rpt.add(step)
    rpt.finalize()
    rpt.finished_at = "2026-06-13T00:00:01"
    blob = json.dumps(rpt.to_dict(), ensure_ascii=False, indent=2)
    reparsed = json.loads(blob)
    assert reparsed["overall"] == "pass"
    assert len(reparsed["steps"]) == 1
    assert reparsed["steps"][0]["name"] == "unit"


def test_ci_helper_run_examples_is_fast(tmp_path: Path):
    """10. run_examples 只跑 YAML 驗證 + output check，不跑 pytest（快速模式）。

    用 tmp_path 給 report，避免污染 report_output/。
    """
    report = tmp_path / "ci_report_examples.json"
    rc = ci_helper.run_examples(report)
    assert rc in (0, 1), f"unexpected rc={rc}"
    assert report.exists(), "run_examples must write JSON report"

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["mode"] == "examples"
    step_names = [s["name"] for s in payload["steps"]]
    # 不該跑 pytest
    assert not any("pytest" in n for n in step_names), (
        f"run_examples should not run pytest; got {step_names}"
    )
    # 必須跑 yaml_valid + example_outputs
    assert "yaml_valid" in step_names
    assert "example_outputs" in step_names
    # 在我們這個 repo 兩個 example 都應該在 → pass
    if rc == 0:
        assert payload["overall"] == "pass"
    else:
        # 若 fail，message 必須告訴我們原因（避免 silent fail）
        out_step = next(s for s in payload["steps"] if s["name"] == "example_outputs")
        assert out_step["message"], "fail step must have a message"
