from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from aurora.infra.github_performance.preflight import load_github_yaml
from aurora.infra.github_performance.recovery import (
    RecoveryEvidenceError,
    reconcile_expected_artifacts,
)

from tests.test_catalog_reduction_recovery_workflow import _inline_python


ROOT = Path(__file__).resolve().parents[1]
RECOVERY_WAVE = ROOT / ".github/workflows/catalog-recovery-wave.yml"
RECOVERY_ACTION = ROOT / ".github/actions/aurora-recovery-plan/action.yml"
AUTHORITY_ID = "da0924b3-e1cb-5876-bd61-1c672bf63836"
PLAN_PREFIX = "0123456789abcdef"
FOREIGN_PLAN_PREFIX = "fedcba9876543210"
BOUND_BUNDLE = f"catalog-checkpoint-recovery-prepared-{AUTHORITY_ID}"
FOREIGN_BUNDLE = "catalog-checkpoint-recovery-prepared-foreign"


def _step(path: Path, job: str, step_id: str) -> dict[str, object]:
    workflow = load_github_yaml(path)
    steps = (
        workflow["jobs"][job]["steps"]
        if "jobs" in workflow
        else workflow["runs"]["steps"]
    )
    return next(
        step
        for step in steps
        if step.get("id") == step_id
    )


def _worker_checkpoint(plan_prefix: str, worker: int, slot: int) -> str:
    return f"catalog-checkpoint-{plan_prefix}-g00-w{worker:03d}-s{slot:02d}"


def _inventory(names: tuple[str, ...]) -> list[dict[str, object]]:
    return [
        {
            "artifacts": [
                {"name": name, "expired": False} for name in names
            ]
        }
    ]


def _outputs(path: Path) -> dict[str, str]:
    return {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    }


def _run_recovery_inventory(
    tmp_path: Path, names: tuple[str, ...]
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    runner_temp = tmp_path / "runner-temp"
    (runner_temp / "sealed-plan").mkdir(parents=True)
    (runner_temp / "sealed-plan/checkpoint_policy.json").write_text(
        json.dumps(
            {
                "workers": [
                    {
                        "checkpoint_slot_count": 1,
                        "checkpoint_slot_artifacts": [
                            _worker_checkpoint(PLAN_PREFIX, worker, 1)
                        ],
                    }
                    for worker in range(2)
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "artifacts-1.json").write_text(
        json.dumps(_inventory(names)), encoding="utf-8"
    )
    (tmp_path / "artifacts-2.json").write_text(
        json.dumps(_inventory(names)), encoding="utf-8"
    )
    output = tmp_path / "github-output"
    output.write_text("", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_OUTPUT": str(output),
            "AUTHORITY_ID": AUTHORITY_ID,
            "RECONCILED_STATUS": "retry",
            "RETRY_A_RESULT": "skipped",
            "RETRY_B_RESULT": "skipped",
            "STATE_ARTIFACT": "catalog-campaign-state-wave-0",
        }
    )
    script = _inline_python(
        str(_step(RECOVERY_WAVE, "finalize_wave", "final")["run"])
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    return result, _outputs(output)


def _run_expected_checkpoint_selector(
    tmp_path: Path, expected: tuple[str, ...]
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    output = tmp_path / "github-output"
    output.write_text("", encoding="utf-8")
    runner_temp = tmp_path / "runner-temp"
    environment = os.environ.copy()
    environment.update(
        {
            "EXPECTED_ATTEMPTS": "[]",
            "EXPECTED_FAILURES": "[]",
            "EXPECTED_CHECKPOINTS": json.dumps(list(expected)),
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_OUTPUT": str(output),
        }
    )
    script = _inline_python(
        str(_step(RECOVERY_ACTION, "expected", "expected")["run"])
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    return result, _outputs(output)


def test_recovery_wave_inventory_excludes_only_bound_bundle(tmp_path: Path) -> None:
    workers = (
        _worker_checkpoint(PLAN_PREFIX, 0, 1),
        _worker_checkpoint(PLAN_PREFIX, 1, 1),
    )
    foreign_worker = _worker_checkpoint(FOREIGN_PLAN_PREFIX, 9, 1)
    names = (*workers, BOUND_BUNDLE, FOREIGN_BUNDLE, foreign_worker)

    result, outputs = _run_recovery_inventory(tmp_path, names)

    assert result.returncode == 0, result.stderr
    assert json.loads(outputs["checkpoint_manifest_artifacts"]) == sorted(
        (*workers, FOREIGN_BUNDLE, foreign_worker)
    )


def test_action_download_namespace_excludes_gate_bundle_and_keeps_worker_grammar(
    tmp_path: Path,
) -> None:
    workers = (
        _worker_checkpoint(PLAN_PREFIX, 0, 1),
        _worker_checkpoint(PLAN_PREFIX, 1, 1),
    )
    foreign_worker = _worker_checkpoint(FOREIGN_PLAN_PREFIX, 9, 1)
    expected = (*workers, foreign_worker)
    available = (*expected, BOUND_BUNDLE)

    result, outputs = _run_expected_checkpoint_selector(tmp_path, expected)

    assert result.returncode == 0, result.stderr
    assert outputs["expected_checkpoint_pattern"] == (
        "catalog-checkpoint-*-g*-w*-s*"
    )
    selected = tuple(
        name
        for name in available
        if fnmatch.fnmatchcase(name, outputs["expected_checkpoint_pattern"])
    )
    assert selected == expected
    assert BOUND_BUNDLE not in selected


def test_foreign_bundle_remains_expected_and_fails_closed_before_recovery(
    tmp_path: Path,
) -> None:
    workers = (
        _worker_checkpoint(PLAN_PREFIX, 0, 1),
        _worker_checkpoint(PLAN_PREFIX, 1, 1),
    )
    expected = (*workers, FOREIGN_BUNDLE)
    available = (*workers, FOREIGN_BUNDLE)
    result, outputs = _run_expected_checkpoint_selector(tmp_path, expected)

    assert result.returncode == 0, result.stderr
    selected = tuple(
        name
        for name in available
        if fnmatch.fnmatchcase(name, outputs["expected_checkpoint_pattern"])
    )
    with pytest.raises(RecoveryEvidenceError, match="RECOVERY_ARTIFACT_SET_MISMATCH"):
        reconcile_expected_artifacts(
            expected=expected,
            observed=selected,
            download_outcome="success",
        )
