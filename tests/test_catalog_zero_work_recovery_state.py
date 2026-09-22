from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

import pytest

from aurora.infra.github_performance.campaign import (
    CampaignPhase,
    resume_campaign_state,
)
from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.github_performance.preflight import load_github_yaml
from tests.test_catalog_initial_reconcile_namespace import (
    AUTHORITY_ID,
    CAMPAIGN_ID,
    DECISION_SHA256,
    EXECUTION_PLAN_SHA256,
    EXECUTION_PROTOCOL_SHA256,
    PROTECTED_COMMIT_SHA,
    REQUEST_SHA256,
    SCIENCE_SHA256,
    _state_step_python,
)


ROOT = Path(__file__).resolve().parents[1]
ACTION = ROOT / ".github/actions/aurora-recovery-plan/action.yml"
WORK_MANIFEST_SHA256 = "b" * 64


def _exact_checkout_python(source: str) -> str:
    # A local editable install may point to another checkout; bind this one.
    return (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('aurora', {str(ROOT / '__init__.py')!r}, "
        f"submodule_search_locations=[{str(ROOT)!r}])\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "sys.modules['aurora'] = module\n"
        "spec.loader.exec_module(module)\n"
    ) + source


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _reconcile_step_python() -> str:
    action = load_github_yaml(ACTION)
    step = next(row for row in action["runs"]["steps"] if row.get("id") == "reconcile")
    run = step["run"]
    source = run.split("python - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    return textwrap.dedent(source)


def _descriptor_row(plan_root: Path, recovery_root: Path) -> dict[str, object]:
    bundle = "descriptor-000"
    member = "recipe/worker-000.json"
    descriptor = {
        "worker_id": 0,
        "checkpoint_slot_count": 1,
        "expected_strategy_count": 1,
        "expected_strategy_manifest_sha256": "c" * 64,
    }
    descriptor_path = recovery_root / "original-descriptors" / bundle / member
    _write_json(descriptor_path, descriptor)
    return {
        "worker_id": 0,
        "descriptor_bundle_artifact": bundle,
        "descriptor_member": member,
        "descriptor_sha256": __import__("hashlib").sha256(
            descriptor_path.read_bytes()
        ).hexdigest(),
    }


def _write_plan_and_wave0_inventory(
    tmp_path: Path,
    *,
    pending_recipe_count: int,
    include_worker: bool,
) -> tuple[Path, Path]:
    plan_root = tmp_path / "sealed-plan"
    plan_root.mkdir()
    recovery_root = tmp_path / "catalog-recovery"
    recovery_root.mkdir()

    row = _descriptor_row(plan_root, recovery_root) if include_worker else None
    includes = [row] if row is not None else []
    for name, rows in (
        ("recipe_matrix_a.json", includes),
        ("recipe_matrix_b.json", []),
        ("recipe_matrix_c.json", []),
    ):
        _write_json(plan_root / name, {"include": rows})
    _write_json(
        plan_root / "execution_plan_receipt.json",
        {
            "authority_id": AUTHORITY_ID,
            "campaign_id": CAMPAIGN_ID,
            "execution_plan_sha256": EXECUTION_PLAN_SHA256,
            "pending_recipe_count": pending_recipe_count,
        },
    )
    _write_json(
        plan_root / "resume_work_manifest.json",
        {"manifest_sha256": WORK_MANIFEST_SHA256},
    )
    _write_json(
        plan_root / "run_plan.json",
        {"processes_per_worker": 2, "block_size": 1},
    )
    _write_json(
        plan_root / "checkpoint_policy.json",
        {
            "schema_version": "1",
            "workers": (
                [
                    {
                        "worker_id": 0,
                        "checkpoint_slot_count": 1,
                        "checkpoint_slot_artifacts": [
                            f"catalog-checkpoint-{EXECUTION_PLAN_SHA256[:16]}-g00-w000-s01"
                        ],
                    }
                ]
                if include_worker
                else []
            ),
        },
    )
    component_seal = tmp_path / "component-store-seal" / "component-store-seal.json"
    component_seal.parent.mkdir()
    component_seal.write_bytes(b"component-store-seal-fixture")
    artifacts = []
    if not include_worker:
        artifacts.append(
            {
                "id": 1,
                "name": f"catalog-checkpoint-recovery-prepared-{AUTHORITY_ID}",
                "expired": False,
                "created_at": "2026-09-22T10:00:00Z",
                "size_in_bytes": 1,
            }
        )
    for snapshot in (1, 2):
        _write_json(
            tmp_path / f"artifacts-{snapshot}.json",
            [{"total_count": len(artifacts), "artifacts": artifacts}],
        )
    return plan_root, recovery_root


def _run_wave0(
    tmp_path: Path,
    *,
    pending_recipe_count: int,
    include_worker: bool,
) -> tuple[Path, Path, dict[str, str]]:
    plan_root, recovery_root = _write_plan_and_wave0_inventory(
        tmp_path,
        pending_recipe_count=pending_recipe_count,
        include_worker=include_worker,
    )
    wave0_output = tmp_path / "wave0-output.txt"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(ROOT),
            "RUNTIME_PYTHON": sys.executable,
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(wave0_output),
            "AUTHORITY_ID": AUTHORITY_ID,
            "CAMPAIGN_ID": CAMPAIGN_ID,
            "REQUEST_SHA256": REQUEST_SHA256,
            "SCIENCE_SHA256": SCIENCE_SHA256,
            "EXECUTION_PLAN_SHA256": EXECUTION_PLAN_SHA256,
            "EXECUTION_PROTOCOL_SHA256": EXECUTION_PROTOCOL_SHA256,
            "PROTECTED_COMMIT_SHA": PROTECTED_COMMIT_SHA,
            "DECISION_SHA256": DECISION_SHA256,
            "ACTIVE_RECIPE_WORKERS": "1" if include_worker else "0",
            "EVALUATE_A_RESULT": "failure" if include_worker else "skipped",
            "EVALUATE_B_RESULT": "skipped",
            "EVALUATE_C_RESULT": "skipped",
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", _exact_checkout_python(_state_step_python())],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    outputs = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in wave0_output.read_text(encoding="utf-8").splitlines()
        if "=" in line
    }
    shutil.copytree(tmp_path / "campaign-state", recovery_root / "state")
    for output_key, expected_name in (
        ("attempt_manifest_artifacts", "expected-attempts.json"),
        ("failure_manifest_artifacts", "expected-failures.json"),
        ("checkpoint_manifest_artifacts", "expected-checkpoints.json"),
    ):
        _write_json(
            recovery_root / expected_name,
            json.loads(outputs[output_key]),
        )
    return plan_root, recovery_root, outputs


def _add_terminal_attempt(
    recovery_root: Path,
    *,
    worker_id: int,
    expected_strategy_count: int,
) -> str:
    name = f"catalog-terminal-attempt-{EXECUTION_PLAN_SHA256[:16]}-{worker_id:03d}"
    _write_json(
        recovery_root / "expected-attempts.json",
        [name],
    )
    _write_json(
        recovery_root / "attempts" / name / "terminal-attempt-manifest.json",
        {
            "worker_id": worker_id,
            "attempt_id": f"{AUTHORITY_ID}:worker:{worker_id:03d}:attempt:1",
            "completed_checkpoint_slots": [{"slot": 1}],
            "expected_strategy_count": expected_strategy_count,
            "terminal_contains_result_rows": False,
            "validation_opened": False,
            "locked_opened": False,
        },
    )
    return name


def _run_reconcile(
    tmp_path: Path,
    *,
    pending_recipe_count: int,
    include_worker: bool,
    attempt_worker: int | None = None,
    attempt_strategy_count: int = 1,
) -> tuple[subprocess.CompletedProcess[str], dict[str, str], Path]:
    plan_root, recovery_root, _ = _run_wave0(
        tmp_path,
        pending_recipe_count=pending_recipe_count,
        include_worker=include_worker,
    )
    expected_attempt_outcome = "skipped"
    if attempt_worker is not None:
        _add_terminal_attempt(
            recovery_root,
            worker_id=attempt_worker,
            expected_strategy_count=attempt_strategy_count,
        )
        expected_attempt_outcome = "success"
    output = tmp_path / "reconcile-output.txt"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(ROOT),
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(output),
            "AUTHORITY_ID": AUTHORITY_ID,
            "CAMPAIGN_ID": CAMPAIGN_ID,
            "PROTECTED_COMMIT_SHA": PROTECTED_COMMIT_SHA,
            "EXECUTION_PROTOCOL_SHA256": EXECUTION_PROTOCOL_SHA256,
            "SEALED_PLAN_PATH": str(plan_root),
            "CURRENT_WAVE": "0",
            "ATTEMPT_DOWNLOAD_OUTCOME": expected_attempt_outcome,
            "FAILURE_DOWNLOAD_OUTCOME": "skipped",
            "CHECKPOINT_DOWNLOAD_OUTCOME": "skipped",
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", _exact_checkout_python(_reconcile_step_python())],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    outputs = {}
    if output.exists():
        outputs = {
            line.split("=", 1)[0]: line.split("=", 1)[1]
            for line in output.read_text(encoding="utf-8").splitlines()
            if "=" in line
        }
    return result, outputs, recovery_root


def test_full_cached_zero_work_reaches_ready_to_merge_with_empty_evidence_hash(
    tmp_path: Path,
) -> None:
    result, outputs, recovery_root = _run_reconcile(
        tmp_path,
        pending_recipe_count=0,
        include_worker=False,
    )

    assert result.returncode == 0, result.stderr
    assert outputs["status"] == "complete"
    latest = resume_campaign_state(
        recovery_root / "state", campaign_id=CAMPAIGN_ID
    )
    assert latest.phase is CampaignPhase.READY_TO_MERGE
    assert latest.logical_unit_count == 0
    assert latest.completed_unit_count == 0
    assert latest.pending_unit_count == 0
    assert latest.completed_unit_manifest_sha256 == canonical_sha256([])


@pytest.mark.parametrize(
    ("attempt_worker", "expected_error"),
    [
        (0, "RECOVERY_COMPLETED_EVIDENCE_EXCESS"),
        (7, "RECOVERY_TERMINAL_MANIFEST_CONFLICT"),
    ],
)
def test_zero_work_rejects_count_mismatch_and_unexpected_worker_evidence(
    tmp_path: Path,
    attempt_worker: int,
    expected_error: str,
) -> None:
    result, outputs, recovery_root = _run_reconcile(
        tmp_path,
        pending_recipe_count=0,
        include_worker=attempt_worker == 0,
        attempt_worker=attempt_worker,
    )

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert outputs == {}
    latest = resume_campaign_state(
        recovery_root / "state", campaign_id=CAMPAIGN_ID
    )
    assert latest.phase is CampaignPhase.EXECUTING


def test_positive_work_without_terminal_evidence_never_reaches_ready_to_merge(
    tmp_path: Path,
) -> None:
    result, outputs, recovery_root = _run_reconcile(
        tmp_path,
        pending_recipe_count=1,
        include_worker=True,
    )

    assert result.returncode == 0, result.stderr
    assert outputs["status"] == "blocked"
    latest = resume_campaign_state(
        recovery_root / "state", campaign_id=CAMPAIGN_ID
    )
    assert latest.phase is CampaignPhase.BLOCKED_HARD_FAILURE
    assert latest.logical_unit_count == 1
    assert latest.completed_unit_count == 0
    assert latest.pending_unit_count == 1
    assert latest.completed_unit_manifest_sha256 is None
