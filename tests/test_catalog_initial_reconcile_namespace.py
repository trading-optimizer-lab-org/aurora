from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from aurora.infra.github_performance.preflight import load_github_yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/catalog-optimized-run.yml"
STEP_NAME = "Seal initial executing state and exact recovery inventory"
AUTHORITY_ID = "da0924b3-e1cb-5876-bd61-1c672bf63836"
CAMPAIGN_ID = "catalog-campaign-test"
EXECUTION_PLAN_SHA256 = "a" * 64
WORK_MANIFEST_SHA256 = "b" * 64
SCIENCE_SHA256 = "c" * 64
EXECUTION_PROTOCOL_SHA256 = "d" * 64
REQUEST_SHA256 = "e" * 64
DECISION_SHA256 = "f" * 64
PROTECTED_COMMIT_SHA = "1" * 40
WORKER_COUNT = 60
CHECKPOINTS_PER_WORKER = 2
PLAN_PREFIX = EXECUTION_PLAN_SHA256[:16]


def _state_step_python() -> str:
    workflow = load_github_yaml(WORKFLOW)
    steps = workflow["jobs"]["reconcile_wave_0"]["steps"]
    matches = [step for step in steps if step.get("name") == STEP_NAME]
    assert len(matches) == 1
    run = matches[0]["run"]
    marker = "<<'PY'\n"
    assert run.count(marker) == 1
    return textwrap.dedent(run.split(marker, 1)[1].rsplit("\nPY", 1)[0])


def _checkpoint_names() -> tuple[str, ...]:
    return tuple(
        f"catalog-checkpoint-{PLAN_PREFIX}-g{worker // 24:02d}-"
        f"w{worker:03d}-s{slot:02d}"
        for worker in range(WORKER_COUNT)
        for slot in range(1, CHECKPOINTS_PER_WORKER + 1)
    )


def _write_fixtures(tmp_path: Path, defect: str | None) -> tuple[list[str], Path]:
    plan_root = tmp_path / "sealed-plan"
    plan_root.mkdir()
    checkpoint_names = list(_checkpoint_names())
    policy_workers = [
        {
            "worker_id": worker,
            "checkpoint_slot_count": CHECKPOINTS_PER_WORKER,
            "checkpoint_slot_artifacts": [
                f"catalog-checkpoint-{PLAN_PREFIX}-g{worker // 24:02d}-"
                f"w{worker:03d}-s{slot:02d}"
                for slot in range(1, CHECKPOINTS_PER_WORKER + 1)
            ],
        }
        for worker in range(WORKER_COUNT)
    ]
    (plan_root / "execution_plan_receipt.json").write_text(
        json.dumps(
            {
                "authority_id": AUTHORITY_ID,
                "campaign_id": CAMPAIGN_ID,
                "execution_plan_sha256": EXECUTION_PLAN_SHA256,
                "pending_recipe_count": 37258,
            }
        ),
        encoding="utf-8",
    )
    (plan_root / "resume_work_manifest.json").write_text(
        json.dumps({"manifest_sha256": WORK_MANIFEST_SHA256}),
        encoding="utf-8",
    )
    (plan_root / "checkpoint_policy.json").write_text(
        json.dumps({"schema_version": "1", "workers": policy_workers}),
        encoding="utf-8",
    )
    component_seal = tmp_path / "component-store-seal" / "component-store-seal.json"
    component_seal.parent.mkdir()
    component_seal.write_bytes(b"component-store-seal-fixture")

    attempts = [
        f"catalog-terminal-attempt-{PLAN_PREFIX}-{worker:03d}"
        for worker in range(WORKER_COUNT)
    ]
    bound_recovery_bundle = f"catalog-checkpoint-recovery-prepared-{AUTHORITY_ID}"
    artifact_names = attempts + checkpoint_names + [bound_recovery_bundle]
    if defect == "missing":
        artifact_names.remove(checkpoint_names[0])
    elif defect == "duplicate":
        artifact_names.append(checkpoint_names[0])
    elif defect == "unexpected":
        artifact_names.append(f"catalog-checkpoint-{PLAN_PREFIX}-g02-w060-s01")
    elif defect == "foreign_bundle":
        artifact_names.append("catalog-checkpoint-recovery-prepared-foreign-authority")
    elif defect == "foreign_checkpoint":
        artifact_names.append("catalog-checkpoint-0000000000000000-g00-w009-s01")

    artifacts = [
        {
            "id": index,
            "name": name,
            "expired": False,
            "created_at": "2026-09-22T10:00:00Z",
            "size_in_bytes": 1,
        }
        for index, name in enumerate(artifact_names, start=1)
    ]
    for snapshot in (1, 2):
        (tmp_path / f"artifacts-{snapshot}.json").write_text(
            json.dumps([{"total_count": len(artifacts), "artifacts": artifacts}]),
            encoding="utf-8",
        )
    return attempts, plan_root


def _run_state_step(tmp_path: Path, defect: str | None) -> tuple[
    subprocess.CompletedProcess[str], dict[str, str], Path
]:
    attempts, _ = _write_fixtures(tmp_path, defect)
    output = tmp_path / "github-output.txt"
    state_root = tmp_path / "campaign-state"
    environment = os.environ.copy()
    environment.update(
        {
            "RUNTIME_PYTHON": sys.executable,
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(output),
            "AUTHORITY_ID": AUTHORITY_ID,
            "CAMPAIGN_ID": CAMPAIGN_ID,
            "REQUEST_SHA256": REQUEST_SHA256,
            "SCIENCE_SHA256": SCIENCE_SHA256,
            "EXECUTION_PLAN_SHA256": EXECUTION_PLAN_SHA256,
            "EXECUTION_PROTOCOL_SHA256": EXECUTION_PROTOCOL_SHA256,
            "PROTECTED_COMMIT_SHA": PROTECTED_COMMIT_SHA,
            "DECISION_SHA256": DECISION_SHA256,
            "ACTIVE_RECIPE_WORKERS": str(WORKER_COUNT),
            "EVALUATE_A_RESULT": "success",
            "EVALUATE_B_RESULT": "success",
            "EVALUATE_C_RESULT": "success",
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", _state_step_python()],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    outputs = {}
    if output.exists():
        outputs = dict(
            line.split("=", 1)
            for line in output.read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
    assert attempts == [
        f"catalog-terminal-attempt-{PLAN_PREFIX}-{worker:03d}"
        for worker in range(WORKER_COUNT)
    ]
    return result, outputs, state_root


def test_initial_reconcile_ignores_only_bound_recovery_bundle_and_seals_state(
    tmp_path: Path,
) -> None:
    result, outputs, state_root = _run_state_step(tmp_path, None)

    assert result.returncode == 0, result.stderr
    assert outputs["status"] == "retry"
    assert outputs["campaign_state_artifact"] == (
        f"catalog-campaign-state-{AUTHORITY_ID}-wave-0"
    )
    assert json.loads(outputs["attempt_manifest_artifacts"]) == [
        f"catalog-terminal-attempt-{PLAN_PREFIX}-{worker:03d}"
        for worker in range(WORKER_COUNT)
    ]
    assert outputs["failure_manifest_artifacts"] == "[]"
    checkpoint_manifest = json.loads(outputs["checkpoint_manifest_artifacts"])
    assert checkpoint_manifest == list(_checkpoint_names())
    assert f"catalog-checkpoint-recovery-prepared-{AUTHORITY_ID}" not in checkpoint_manifest

    initial = json.loads((state_root / "campaign_state_v000000.json").read_text())
    executing = json.loads((state_root / "campaign_state_v000001.json").read_text())
    latest = json.loads((state_root / "campaign_state_latest.json").read_text())
    assert initial["phase"] == "planned"
    assert executing["phase"] == "executing"
    assert executing["authority_id"] == AUTHORITY_ID
    assert executing["campaign_id"] == CAMPAIGN_ID
    assert executing["logical_unit_count"] == 37258
    assert executing["active_plan_sha256"] == EXECUTION_PLAN_SHA256
    assert executing["component_store_manifest_sha256"] == hashlib.sha256(
        b"component-store-seal-fixture"
    ).hexdigest()
    assert latest["state_file"] == "campaign_state_v000001.json"
    assert latest["version"] == 1


@pytest.mark.parametrize(
    "defect", ["missing", "duplicate", "unexpected", "foreign_bundle", "foreign_checkpoint"]
)
def test_initial_reconcile_rejects_unbound_or_nonexact_checkpoint_inventory(
    tmp_path: Path, defect: str,
) -> None:
    result, outputs, state_root = _run_state_step(tmp_path, defect)

    assert result.returncode != 0
    assert "CATALOG_GREEN_WAVE_ARTIFACT_AMBIGUITY" in result.stderr
    assert outputs == {}
    assert not state_root.exists()
