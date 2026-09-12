from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

from aurora.infra.github_performance.recovery import FailureClass
from aurora.infra.sp500_megarun.catalog_worker_failure import (
    CatalogWorkerFailureReceiptV1,
    build_catalog_worker_failure_receipt,
    decide_catalog_worker_recovery,
    worker_failure_artifact_name,
)


ROOT = Path(__file__).resolve().parents[1]
PLAN = "1" * 64
COMMIT = "2" * 40


@pytest.mark.parametrize(
    "worker_id,runtime_outcome,verified_attempt,upload_outcome,existing_failure",
    [(0, "skipped", "", "skipped", False),
     (7, "failure", "authority:worker:007:attempt:1", "skipped", False),
     (359, "skipped", "", "skipped", False),
     (7, "success", "authority:worker:007:attempt:1", "failure", False),
     (7, "success", "authority:worker:007:attempt:1", "failure", True)],
)
def test_workflow_seals_failure_before_or_after_runtime_activation(
    tmp_path: Path, worker_id: int, runtime_outcome: str, verified_attempt: str,
    upload_outcome: str, existing_failure: bool,
) -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/catalog-optimized-worker.yml").read_text("utf-8")
    )
    step = next(s for s in workflow["jobs"]["evaluate"]["steps"]
                if s.get("id") == "failure")
    bash = ("C:/Program Files/Git/bin/bash.exe" if os.name == "nt"
            else shutil.which("bash"))
    assert bash and Path(bash).is_file(), "bash is required to exercise the worker"
    environment = dict(os.environ, AUTHORITY_ID="authority", CAMPAIGN_ID="campaign",
                       EXECUTION_PLAN_SHA256=PLAN, PROTECTED_COMMIT_SHA=COMMIT,
                       WORKER_ID=str(worker_id), VERIFIED_ATTEMPT_ID=verified_attempt,
                       RUNTIME_OUTCOME=runtime_outcome, GITHUB_RUN_ID="299",
                       GITHUB_RUN_ATTEMPT="1", RUNNER_TEMP=tmp_path.as_posix(),
                       GITHUB_OUTPUT=(tmp_path / "outputs").as_posix(),
                       TEST_PYTHON=Path(sys.executable).as_posix())
    environment.update({f"{kind}_{slot}": "skipped"
                        for kind in ("COMPUTE", "UPLOAD") for slot in range(1, 9)})
    environment["UPLOAD_1"] = upload_outcome
    original = None
    if existing_failure:
        original = build_catalog_worker_failure_receipt(
            authority_id="authority", campaign_id="campaign",
            execution_plan_sha256=PLAN, protected_commit_sha=COMMIT,
            worker_id=worker_id, attempt_id=verified_attempt,
            stage="recipe_worker", reason_code="CONNECTION_RESET", exit_code=1,
            exception_type="ConnectionResetError",
        ).model_dump_json() + "\n"
        (tmp_path / "catalog-worker-failure.json").write_text(original, encoding="utf-8")
    python_flags = "" if runtime_outcome == "success" else "-S"
    result = subprocess.run(
        [bash, "--noprofile", "--norc", "-c",
         f'python() {{ "$TEST_PYTHON" {python_flags} "$@"; }};\n' + step["run"]],
        cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = CatalogWorkerFailureReceiptV1.model_validate_json(
        (tmp_path / "catalog-worker-failure-final.json").read_text("utf-8")
    )
    assert receipt.worker_id == worker_id
    assert receipt.attempt_id == (verified_attempt or
                                  f"authority:worker:{worker_id:03d}:unverified:299:1")
    if existing_failure:
        assert receipt.stage == "recipe_worker"
        assert receipt.failure_class is FailureClass.TRANSIENT_NETWORK
        assert receipt.reason_code == "CONNECTION_RESET"
        assert (tmp_path / "catalog-worker-failure-final.json").read_text("utf-8") == original
    elif upload_outcome == "failure":
        assert receipt.stage == "checkpoint_upload"
        assert receipt.failure_class is FailureClass.ARTIFACT_UPLOAD
        assert receipt.reason_code == "ARTIFACT_UPLOAD_FAILED"
    else:
        assert receipt.stage == "setup"
        assert receipt.failure_class is FailureClass.UNKNOWN
        assert receipt.reason_code == "UNKNOWN_WORKER_FAILURE"
    assert receipt.validation_opened is False and receipt.locked_opened is False
    outputs = dict(line.split("=", 1) for line in
                   (tmp_path / "outputs").read_text("utf-8").splitlines())
    assert outputs["failure_artifact"] == worker_failure_artifact_name(
        execution_plan_sha256=PLAN, worker_id=worker_id, attempt_id=receipt.attempt_id,
    )
    assert outputs["failure_fingerprint"] == receipt.failure_fingerprint
    recovery = decide_catalog_worker_recovery(
        expected_worker_ids=(worker_id,), completed_worker_ids=(),
        failure_receipts=(receipt,), current_wave=0, max_waves=3,
        now=receipt.created_at,
    )
    assert recovery.status == ("retry" if upload_outcome == "failure" else "blocked")


@pytest.mark.parametrize("option,value", [
    ("--worker-id", "-1"), ("--worker-id", "360"),
    ("--authority-id", ""), ("--campaign-id", "x" * 97),
    ("--execution-plan-sha256", "bad"), ("--protected-commit-sha", "f" * 39),
    ("--attempt-id", "authority:worker:7:unverified:299:1"),
    ("--attempt-id", "other:worker:007:unverified:299:1"),
    ("--attempt-id", "authority:worker:007:" + "x" * 221),
    ("--reason-code", "CONNECTION_RESET"), ("--existing", "receipt.json"),
])
def test_bootstrap_reporter_rejects_invalid_binding_or_classification_override(
    tmp_path: Path, option: str, value: str,
) -> None:
    output = tmp_path / "receipt.json"
    github_output = tmp_path / "outputs"
    args = {
        "--authority-id": "authority", "--campaign-id": "campaign",
        "--execution-plan-sha256": PLAN, "--protected-commit-sha": COMMIT,
        "--worker-id": "7", "--attempt-id": "authority:worker:007:unverified:299:1",
        "--output": str(output), "--github-output": str(github_output),
    }
    args[option] = value
    result = subprocess.run(
        [sys.executable, "-S", "scripts/prepare_catalog_worker_bootstrap_failure.py",
         *(item for pair in args.items() for item in pair)],
        cwd=ROOT, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    assert not output.exists()
    assert not github_output.exists()
