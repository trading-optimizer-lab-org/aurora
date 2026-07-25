from __future__ import annotations

import json
import os
from pathlib import Path

import pyarrow.parquet as pq

from aurora.core.execution_policy import require_github_execution
from aurora.infra.github_performance.contracts import (
    RunSpec,
    deep_thaw_json,
)
from aurora.infra.github_performance.merge_planner import (
    reconcile_attempt_files,
)
from aurora.infra.github_performance.preflight import (
    load_github_yaml,
    validate_run_spec,
    validate_workflow_policy,
)
from aurora.infra.github_performance.reference_workload import (
    REFERENCE_SEED,
    TRAIN_OBSERVATIONS,
    VALIDATION_OBSERVATIONS,
    WORKLOAD,
    _evaluate,
    _generate_prices,
)
from aurora.infra.github_performance.shard_planner import weighted_lpt


ROOT = Path(__file__).parents[1]
SPEC_PATH = ROOT / "config" / "github_performance_reference.yaml"
WORKFLOW_PATH = (
    ROOT / ".github/workflows/github-performance-reference.yml"
)


def _resolved_spec(snapshot_hash: str, manifest_hash: str) -> RunSpec:
    payload = load_github_yaml(SPEC_PATH)
    payload["identity"]["code_sha"] = "a" * 40
    payload["identity"]["workflow_sha256"] = "b" * 64
    payload["policy"]["policy_hash"] = "c" * 64
    payload["data"]["manifest_sha256"] = manifest_hash
    payload["data"]["snapshot_hash"] = snapshot_hash
    payload["execution"]["dependency_lock_sha256"] = "d" * 64
    payload["execution"]["environment_sha256"] = "e" * 64
    payload["performance"]["capacity_profile_sha256"] = "f" * 64
    payload["metrics"]["contract_sha256"] = "1" * 64
    return RunSpec.model_validate(payload)


def test_reference_fixture_is_deterministic_and_never_crosses_locked() -> None:
    frame_a = _generate_prices()
    frame_b = _generate_prices()
    assert REFERENCE_SEED == 20_260_725
    assert frame_a.equals(frame_b)
    assert len(frame_a.loc[frame_a["period"] == "train"]) == (
        TRAIN_OBSERVATIONS
    )
    assert len(frame_a.loc[frame_a["period"] == "validation"]) == (
        VALIDATION_OBSERVATIONS
    )
    assert str(frame_a["date"].max().date()) == "2020-12-31"


def test_same_reference_unit_has_same_scientific_hash() -> None:
    require_github_execution("reference unit determinism")
    frame = _generate_prices()
    first = _evaluate(frame, "unit", 10, 100, "attempt-a")
    second = _evaluate(frame, "unit", 10, 100, "attempt-b")
    assert first["unit_output_sha256"] == second["unit_output_sha256"]
    assert first["source_attempt_id"] != second["source_attempt_id"]
    comparable_first = {
        key: value
        for key, value in first.items()
        if key != "source_attempt_id"
    }
    comparable_second = {
        key: value
        for key, value in second.items()
        if key != "source_attempt_id"
    }
    assert comparable_first == comparable_second


def test_reference_spec_and_manual_caller_pass_static_policy() -> None:
    report = validate_run_spec(SPEC_PATH)
    assert report.valid, report.violation_codes
    assert validate_workflow_policy(WORKFLOW_PATH, ROOT) == []
    workflow = load_github_yaml(WORKFLOW_PATH)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {
        "contents": "read",
        "actions": "read",
    }


def test_four_shard_reference_smoke_reconciles_exactly(
    tmp_path: Path,
) -> None:
    require_github_execution("four-shard reference smoke")
    requested = RunSpec.model_validate(load_github_yaml(SPEC_PATH))
    prepared = WORKLOAD.prepare(requested.model_copy(
        update={
            "policy": {
                **deep_thaw_json(requested.policy),
                "policy_hash": "c" * 64,
            }
        }
    ), tmp_path / "prepared")
    spec = _resolved_spec(
        prepared.snapshot_hash,
        prepared.manifest_sha256,
    )
    smoke = WORKLOAD.smoke(spec, prepared)
    assert smoke.passed is True
    manifest = WORKLOAD.enumerate_units(
        spec,
        prepared,
        tmp_path / "plan" / "work_units.parquet",
    )
    assert manifest.unit_count == 1_024
    plan = weighted_lpt(manifest, 4, tmp_path / "plan")
    attempt_dirs: list[Path] = []
    unit_attempt_paths: list[Path] = []
    os.environ["AURORA_PREPARED_ROOT"] = str(tmp_path / "prepared")
    for index, original_shard in enumerate(plan.shards):
        shard = original_shard.model_copy(
            update={
                "assignment_member": str(
                    tmp_path / "plan" / original_shard.assignment_member
                )
            }
        )
        attempt_id = f"a{index:03d}"
        artifact_name = (
            f"reference-shard-{shard.merge_group}-"
            f"{shard.shard_id}-{attempt_id}"
        )
        os.environ["AURORA_ATTEMPT_ID"] = attempt_id
        os.environ["AURORA_ARTIFACT_NAME"] = artifact_name
        attempt_dir = tmp_path / "attempts" / shard.shard_id / attempt_id
        attempt = WORKLOAD.run_shard(
            spec,
            shard,
            attempt_dir,
            None,
        )
        (attempt_dir / "shard_attempt_manifest.json").write_text(
            attempt.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        attempt_dirs.append(attempt_dir)
        unit_attempt_paths.append(attempt_dir / "unit_attempts.parquet")
    reconciliation = reconcile_attempt_files(
        manifest,
        unit_attempt_paths,
        tmp_path / "unit_reconciliation.parquet",
    )
    assert reconciliation.partial is False
    assert reconciliation.completed == 1_024
    merged = WORKLOAD.merge_group(attempt_dirs, tmp_path / "merged")
    table = pq.read_table(merged)
    assert table.num_rows == 1_024
    assert table.column("locked_opened").to_pylist() == [False] * 1_024
    assert table.column(
        "validation_used_for_selection"
    ).to_pylist() == [False] * 1_024
    summary = json.loads(
        (tmp_path / "merged/reference_results_summary.json").read_text()
    )
    assert summary["rows"] == 1_024
