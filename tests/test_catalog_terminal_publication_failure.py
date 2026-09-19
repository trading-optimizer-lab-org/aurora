from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap

import yaml

from aurora.infra.sp500_megarun.catalog_worker_failure import (
    CatalogWorkerFailureReceiptV1,
    decide_catalog_worker_recovery,
)


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/catalog-optimized-worker.yml"
PLAN = "1" * 64
COMMIT = "2" * 40


def _steps() -> list[dict[str, object]]:
    workflow = yaml.safe_load(WORKFLOW.read_text("utf-8"))
    return workflow["jobs"]["evaluate"]["steps"]


def _step(step_id: str) -> dict[str, object]:
    return next(step for step in _steps() if step.get("id") == step_id)


def _condition_matches(condition: str, outcomes: dict[str, str]) -> bool:
    expression = condition.removeprefix("${{").removesuffix("}}").strip()
    expression = expression.replace("always()", "True")
    expression = expression.replace("&&", " and ").replace("||", " or ")
    expression = re.sub(
        r"steps\.([a-z_]+)\.outcome",
        lambda match: repr(outcomes[match.group(1)]),
        expression,
    )
    return bool(eval(expression, {"__builtins__": {}}, {}))


def _bash() -> str:
    path = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    assert path and Path(path).is_file(), "bash is required to exercise the workflow"
    return path


def _run_shell(
    *,
    command: str,
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(environment)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [_bash(), "--noprofile", "--norc", "-c", command],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _prepare_descriptor(tmp_path: Path, *, missing_slot: int | None = None) -> dict[str, object]:
    runner_temp = tmp_path / "runner-temp"
    (runner_temp / "descriptor-bundle").mkdir(parents=True)
    descriptor = {
        "worker_id": 7,
        "attempt_id": "authority:worker:007:attempt:1",
        "prior_checkpoint_chain_artifact": "catalog-checkpoint-s1",
        "checkpoint_slot_count": 2,
        "expected_strategy_count": 3,
    }
    (runner_temp / "descriptor-bundle/recipe-descriptor.json").write_text(
        json.dumps(descriptor), encoding="utf-8"
    )
    for slot in (1, 2):
        checkpoint = runner_temp / f"checkpoint-{slot}"
        checkpoint.mkdir()
        if slot != missing_slot:
            (checkpoint / "receipt.json").write_text(
                f"checkpoint-{slot}\n", encoding="utf-8"
            )
    return descriptor


def _run_terminal_writer(
    tmp_path: Path, *, missing_slot: int | None = None
) -> subprocess.CompletedProcess[str]:
    _prepare_descriptor(tmp_path, missing_slot=missing_slot)
    run = textwrap.dedent(str(_step("terminal")["run"]))
    return _run_shell(
        command=f'python() {{ "$TEST_PYTHON" "$@"; }};\n{run}',
        cwd=tmp_path,
        environment={
            "RUNNER_TEMP": (tmp_path / "runner-temp").as_posix(),
            "TEST_PYTHON": Path(sys.executable).as_posix(),
        },
    )


def _run_failure_reporter(
    tmp_path: Path,
    *,
    terminal_outcome: str,
    terminal_upload_outcome: str,
    compute_outcome: str = "skipped",
    upload_outcome: str = "skipped",
) -> CatalogWorkerFailureReceiptV1:
    output = tmp_path / "runner-temp/catalog-worker-failure-final.json"
    github_output = tmp_path / "github-output"
    environment = {
        "AUTHORITY_ID": "authority",
        "CAMPAIGN_ID": "campaign",
        "EXECUTION_PLAN_SHA256": PLAN,
        "PROTECTED_COMMIT_SHA": COMMIT,
        "WORKER_ID": "7",
        "VERIFIED_ATTEMPT_ID": "authority:worker:007:attempt:1",
        "RUNTIME_OUTCOME": "success",
        "TERMINAL_OUTCOME": terminal_outcome,
        "TERMINAL_UPLOAD_OUTCOME": terminal_upload_outcome,
        "GITHUB_RUN_ID": "299",
        "GITHUB_RUN_ATTEMPT": "1",
        "RUNNER_TEMP": (tmp_path / "runner-temp").as_posix(),
        "GITHUB_OUTPUT": github_output.as_posix(),
        "TEST_PYTHON": Path(sys.executable).as_posix(),
    }
    for kind in ("COMPUTE", "UPLOAD"):
        for slot in range(1, 9):
            environment[f"{kind}_{slot}"] = (
                upload_outcome if kind == "UPLOAD" else compute_outcome
            )
    step = _step("failure")
    result = _run_shell(
        command=f'python() {{ "$TEST_PYTHON" "$@"; }};\n{step["run"]}',
        cwd=ROOT,
        environment=environment,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return CatalogWorkerFailureReceiptV1.model_validate_json(output.read_text("utf-8"))


def test_terminal_upload_failure_is_reported_after_terminal_publication_and_retries(
    tmp_path: Path,
) -> None:
    steps = _steps()
    ids = [step.get("id") for step in steps]
    terminal_index = ids.index("terminal")
    terminal_upload_index = ids.index("terminal_upload")
    failure_index = ids.index("failure")
    assert terminal_index < terminal_upload_index < failure_index

    failure = _step("failure")
    condition = str(failure["if"])
    assert "steps.durable_chain.outcome != 'success'" in condition
    assert "steps.terminal.outcome != 'success'" in condition
    assert "steps.terminal_upload.outcome != 'success'" in condition
    outcomes = {
        "durable_chain": "success",
        "terminal": "success",
        "terminal_upload": "failure",
    }
    assert _condition_matches(condition, outcomes)

    terminal_result = _run_terminal_writer(tmp_path)
    assert terminal_result.returncode == 0, terminal_result.stdout + terminal_result.stderr
    manifest = json.loads((tmp_path / "terminal-attempt-manifest.json").read_text("utf-8"))
    assert manifest["attempt_id"] == "authority:worker:007:attempt:1"
    assert manifest["completed_checkpoint_slots"][0]["cumulative_prior_chain"] is True

    receipt = _run_failure_reporter(
        tmp_path,
        terminal_outcome="success",
        terminal_upload_outcome="failure",
        compute_outcome="success",
        upload_outcome="success",
    )
    assert receipt.reason_code == "ARTIFACT_UPLOAD_FAILED"
    assert receipt.stage == "terminal_manifest"
    recovery = decide_catalog_worker_recovery(
        expected_worker_ids=(7,),
        completed_worker_ids=(),
        failure_receipts=(receipt,),
        current_wave=0,
        max_waves=3,
        now=receipt.created_at,
    )
    assert recovery.status == "retry"


def test_terminal_manifest_construction_failure_is_fail_closed(tmp_path: Path) -> None:
    terminal_result = _run_terminal_writer(tmp_path, missing_slot=2)
    assert terminal_result.returncode != 0
    assert "CHECKPOINT_RECEIPT_MISSING" in terminal_result.stdout + terminal_result.stderr
    assert not (tmp_path / "terminal-attempt-manifest.json").exists()

    receipt = _run_failure_reporter(
        tmp_path,
        terminal_outcome="failure",
        terminal_upload_outcome="skipped",
    )
    assert receipt.reason_code == "INTEGRITY_ERROR"
    assert receipt.stage == "terminal_manifest"


def test_successful_terminal_publication_does_not_schedule_failure_reporter(
    tmp_path: Path,
) -> None:
    steps = _steps()
    terminal_upload = _step("terminal_upload")
    assert terminal_upload["if"] == "${{ always() && steps.terminal.outcome == 'success' }}"
    condition = str(_step("failure")["if"])
    assert not _condition_matches(
        condition,
        {
            "durable_chain": "success",
            "terminal": "success",
            "terminal_upload": "success",
        },
    )
    result = _run_terminal_writer(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "terminal-attempt-manifest.json").is_file()
    assert not (tmp_path / "runner-temp/catalog-worker-failure-final.json").exists()
