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

LEGACY_CACHED_COUNT = 18630
TOTAL_COUNT = 37258
FULLY_CACHED_COUNT = TOTAL_COUNT


def _workflow() -> dict:
    return load_github_yaml(WORKFLOW)


def _step(job: dict, *, step_id: str) -> dict:
    matches = [step for step in job["steps"] if step.get("id") == step_id]
    assert len(matches) == 1
    return matches[0]


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _checkpoint_binding(cached_count: int, total_count: int) -> dict[str, object]:
    return {
        "schema_version": "1",
        "profile_sha256": "a" * 64,
        "owner_proof_sha256": "b" * 64,
        "source_plan_receipt_sha256": "c" * 64,
        "science_sha256": "d" * 64,
        "catalog_manifest_sha256": "e" * 64,
        "cached_strategy_ids_sha256": "f" * 64,
        "cached_recipe_count": cached_count,
        "total_recipe_count": total_count,
    }


def _controller(binding: dict[str, object]) -> dict[str, object]:
    envelope = {"checkpoint_recovery": binding}
    controller: dict[str, object] = {"binding": envelope}
    controller["content_sha256"] = _canonical_sha256(controller)
    return controller


def _inline_script(*, job: str, step_id: str, marker: str) -> str:
    step = _step(_workflow()["jobs"][job], step_id=step_id)
    return textwrap.dedent(step["run"].split(marker, 1)[1].rsplit("\nPY", 1)[0])


def _checkpoint_gate_script() -> str:
    return _inline_script(
        job="engine_verify_sealed_plan",
        step_id="checkpoint_recovery",
        marker="python -S - <<'PY'\n",
    )


def _run_checkpoint_gate(
    tmp_path: Path,
    binding: dict[str, object],
    *,
    run_plan_cached_count: int,
    controller: dict[str, object] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    sealed_plan = tmp_path / "sealed-plan"
    sealed_plan.mkdir(parents=True)
    (sealed_plan / "controller_binding.json").write_text(
        json.dumps(controller if controller is not None else _controller(binding)),
        encoding="utf-8",
    )
    (sealed_plan / "run_plan.json").write_text(
        json.dumps({"cached_recipe_count": run_plan_cached_count}),
        encoding="utf-8",
    )
    output = tmp_path / "github-output"
    environment = os.environ.copy()
    environment.update(
        {
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_OUTPUT": str(output),
            "LEGACY_REDUCTION_ONLY": "false",
        }
    )
    result = subprocess.run(
        [sys.executable, "-S", "-c", _checkpoint_gate_script()],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    values = {}
    if output.exists():
        values = dict(
            line.split("=", 1)
            for line in output.read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
    return result, values


def _restore_result_script() -> str:
    return _inline_script(
        job="reduce",
        step_id="checkpoint_restore",
        marker='python -S - "$result" <<\'PY\'\n',
    )


def _restore_result_payload(
    tmp_path: Path,
    binding: dict[str, object],
    cached_count: int,
    total_count: int,
) -> dict[str, object]:
    return {
        "checkpoint_root": str((tmp_path / "checkpoint-root").resolve()),
        "source_plan_root": str((tmp_path / "source-plan-root").resolve()),
        "profile_sha256": binding["profile_sha256"],
        "owner_proof_sha256": binding["owner_proof_sha256"],
        "source_plan_receipt_sha256": binding["source_plan_receipt_sha256"],
        "resume_index_sha256": "1" * 64,
        "cached_strategy_ids_sha256": binding["cached_strategy_ids_sha256"],
        "cached_recipe_count": cached_count,
        "total_recipe_count": total_count,
    }


def _run_restore_result(
    tmp_path: Path,
    controller_binding: dict[str, object],
    payload: dict[str, object],
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    sealed_plan = tmp_path / "sealed-plan"
    sealed_plan.mkdir(parents=True)
    (sealed_plan / "controller_binding.json").write_text(
        json.dumps(_controller(controller_binding)), encoding="utf-8"
    )
    checkpoint_root = Path(str(payload["checkpoint_root"]))
    source_plan_root = Path(str(payload["source_plan_root"]))
    checkpoint_root.mkdir(parents=True)
    source_plan_root.mkdir(parents=True)
    result_path = tmp_path / "checkpoint-recovery-result.json"
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "github-output"
    environment = os.environ.copy()
    environment.update({"RUNNER_TEMP": str(tmp_path), "GITHUB_OUTPUT": str(output)})
    result = subprocess.run(
        [sys.executable, "-S", "-c", _restore_result_script(), str(result_path)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    values = {}
    if output.exists():
        values = dict(
            line.split("=", 1)
            for line in output.read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
    return result, values


@pytest.mark.parametrize("cached_count", [LEGACY_CACHED_COUNT, FULLY_CACHED_COUNT])
def test_checkpoint_gate_accepts_closed_counts_bound_to_run_plan(
    tmp_path: Path, cached_count: int
) -> None:
    binding = _checkpoint_binding(cached_count, TOTAL_COUNT)
    result, outputs = _run_checkpoint_gate(
        tmp_path,
        binding,
        run_plan_cached_count=cached_count,
    )

    assert result.returncode == 0, result.stderr
    assert outputs == {"enabled": "true"}


@pytest.mark.parametrize(
    ("cached_count", "total_count", "run_plan_cached_count"),
    [
        (LEGACY_CACHED_COUNT, TOTAL_COUNT, FULLY_CACHED_COUNT),
        (FULLY_CACHED_COUNT, TOTAL_COUNT, LEGACY_CACHED_COUNT),
        (LEGACY_CACHED_COUNT + 1, TOTAL_COUNT, LEGACY_CACHED_COUNT + 1),
    ],
)
def test_checkpoint_gate_rejects_count_mismatch_or_invalid_count(
    tmp_path: Path,
    cached_count: int,
    total_count: int,
    run_plan_cached_count: int,
) -> None:
    binding = _checkpoint_binding(cached_count, total_count)
    result, outputs = _run_checkpoint_gate(
        tmp_path,
        binding,
        run_plan_cached_count=run_plan_cached_count,
    )

    assert result.returncode != 0
    assert "CATALOG_CHECKPOINT_RECOVERY_BINDING_INVALID" in result.stderr
    assert outputs == {}


def test_checkpoint_gate_rejects_foreign_controller_sha(tmp_path: Path) -> None:
    binding = _checkpoint_binding(LEGACY_CACHED_COUNT, TOTAL_COUNT)
    controller = _controller(binding)
    controller["content_sha256"] = "0" * 64

    result, outputs = _run_checkpoint_gate(
        tmp_path,
        binding,
        run_plan_cached_count=LEGACY_CACHED_COUNT,
        controller=controller,
    )

    assert result.returncode != 0
    assert "CATALOG_CHECKPOINT_RECOVERY_BINDING_INVALID" in result.stderr
    assert outputs == {}


@pytest.mark.parametrize("cached_count", [LEGACY_CACHED_COUNT, FULLY_CACHED_COUNT])
def test_restore_result_accepts_closed_counts_matching_controller_binding(
    tmp_path: Path, cached_count: int
) -> None:
    binding = _checkpoint_binding(cached_count, TOTAL_COUNT)
    payload = _restore_result_payload(tmp_path, binding, cached_count, TOTAL_COUNT)
    result, outputs = _run_restore_result(tmp_path, binding, payload)

    assert result.returncode == 0, result.stderr
    assert outputs["cached_recipe_count"] == str(cached_count)
    assert outputs["total_recipe_count"] == str(TOTAL_COUNT)


@pytest.mark.parametrize(
    "foreign_field",
    [
        "profile_sha256",
        "owner_proof_sha256",
        "source_plan_receipt_sha256",
        "cached_strategy_ids_sha256",
    ],
)
def test_restore_result_rejects_foreign_common_sha(
    tmp_path: Path, foreign_field: str
) -> None:
    binding = _checkpoint_binding(LEGACY_CACHED_COUNT, TOTAL_COUNT)
    payload = _restore_result_payload(
        tmp_path, binding, LEGACY_CACHED_COUNT, TOTAL_COUNT
    )
    payload[foreign_field] = "0" * 64
    result, outputs = _run_restore_result(tmp_path, binding, payload)

    assert result.returncode != 0
    assert "CATALOG_CHECKPOINT_RECOVERY_RESULT_INVALID" in result.stderr
    assert outputs == {}


def test_restore_result_rejects_counts_that_do_not_match_controller_binding(
    tmp_path: Path,
) -> None:
    binding = _checkpoint_binding(FULLY_CACHED_COUNT, TOTAL_COUNT)
    payload = _restore_result_payload(
        tmp_path, binding, LEGACY_CACHED_COUNT, TOTAL_COUNT
    )
    result, outputs = _run_restore_result(tmp_path, binding, payload)

    assert result.returncode != 0
    assert "CATALOG_CHECKPOINT_RECOVERY_RESULT_INVALID" in result.stderr
    assert outputs == {}
