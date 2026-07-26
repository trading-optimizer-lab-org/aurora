from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from aurora.core.execution_policy import require_github_execution
from aurora.infra.github_performance.contracts import (
    MergeNodeManifest,
    RunSpec,
    deep_thaw_json,
)
from aurora.infra.github_performance.merge_planner import (
    build_merge_plan,
    reconcile_attempt_files,
)
from aurora.infra.github_performance.merge_runtime import (
    PhysicalMergeError,
    merge_plan_group,
)
from aurora.infra.github_performance.metric_verifier import (
    read_metric_inputs,
    verify_metric_inputs,
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
from aurora.infra.github_performance.shard_planner import (
    sha256_file,
    weighted_lpt,
)
from aurora.infra.github_performance.telemetry import ResourceMonitor


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
        assert attempt.metric_inputs_path is not None
        assert attempt.metric_inputs_sha256 is not None
        metric_path = attempt_dir / attempt.metric_inputs_path
        assert sha256_file(metric_path) == attempt.metric_inputs_sha256
        metric_records = read_metric_inputs(metric_path)
        assert len(metric_records) == shard.unit_count * 2
        assert verify_metric_inputs(metric_records).passed is True
        pq.write_table(
            pa.Table.from_pylist(
                [
                    {
                        "observed_at": datetime(
                            2026,
                            7,
                            26,
                            12,
                            0,
                            index,
                            tzinfo=timezone.utc,
                        ),
                        "root_pid": 100 + index,
                        "process_count": 1,
                        "child_aware": True,
                        "rss_mb": 128.0 + index,
                        "peak_memory_mb": 256.0 + index,
                        "total_memory_mb": 16_384.0,
                        "free_disk_mb": 20_000.0,
                        "cpu_seconds": 1.0 + index,
                        "io_read_bytes": 1_024 + index,
                        "io_write_bytes": 2_048 + index,
                        "io_wait_seconds": 0.0,
                        "load_1m": 0.5,
                    }
                ],
                schema=ResourceMonitor.ARROW_SCHEMA,
            ),
            attempt_dir / "resource_samples.parquet",
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

    hierarchical_shards = tuple(
        shard.model_copy(
            update={"merge_group": f"g{index // 2:03d}"}
        )
        for index, shard in enumerate(plan.shards)
    )
    merge_plan = build_merge_plan(
        hierarchical_shards,
        fan_in=2,
        disk_budget_bytes=1_000_000_000,
        run_id="reference-real-tree",
        partition_target_bytes=32_768,
    )
    assert merge_plan.root_level == 1
    level_zero = tuple(
        group for group in merge_plan.groups if group.level == 0
    )
    assert len(level_zero) == 2
    attempt_by_shard = dict(zip(
        (shard.shard_id for shard in plan.shards),
        attempt_dirs,
        strict=True,
    ))
    child_root = tmp_path / "merge-tree-children"
    child_manifest_paths: dict[str, Path] = {}
    for group in level_zero:
        group_inputs = tmp_path / "merge-tree-inputs" / group.group_id
        for logical_input in group.input_artifacts:
            shard_id = logical_input.removeprefix("shard:")
            shutil.copytree(
                attempt_by_shard[shard_id],
                group_inputs / shard_id,
            )
        child_output = child_root / group.output_artifact
        child_manifest_paths[group.output_artifact] = merge_plan_group(
            WORKLOAD,
            plan,
            merge_plan,
            group.group_id,
            group_inputs,
            child_output,
        )

    root_group = next(
        group for group in merge_plan.groups
        if group.output_artifact == merge_plan.root_artifact
    )
    root_output = tmp_path / "merge-tree-root"
    root_manifest_path = merge_plan_group(
        WORKLOAD,
        plan,
        merge_plan,
        root_group.group_id,
        child_root,
        root_output,
    )
    root_manifest = MergeNodeManifest.model_validate_json(
        root_manifest_path.read_text(encoding="utf-8")
    )
    assert root_manifest.level == 1
    assert root_manifest.selected_inputs == 2
    assert root_manifest.completed_shards == 4
    assert root_manifest.source_shard_ids == tuple(
        sorted(shard.shard_id for shard in plan.shards)
    )
    assert root_manifest.child_manifest_sha256s == {
        artifact: sha256_file(path)
        for artifact, path in child_manifest_paths.items()
    }
    scientific_transport = next(
        item for item in root_manifest.files
        if item.logical_name == "scientific_output"
    )
    assert scientific_transport.row_count == 1_024
    assert len(scientific_transport.parts) > 1
    assert all(
        part.byte_count <= scientific_transport.target_bytes
        for part in scientific_transport.parts
    )
    locked_opened: list[bool] = []
    validation_selected: list[bool] = []
    for part in scientific_transport.parts:
        part_table = pq.read_table(
            root_output / part.relative_path,
            columns=[
                "locked_opened",
                "validation_used_for_selection",
            ],
        )
        locked_opened.extend(
            part_table.column("locked_opened").to_pylist()
        )
        validation_selected.extend(
            part_table.column(
                "validation_used_for_selection"
            ).to_pylist()
        )
    assert locked_opened == [False] * 1_024
    assert validation_selected == [False] * 1_024
    resource_transport = next(
        item for item in root_manifest.files
        if item.logical_name == "resource_samples"
    )
    assert resource_transport.row_count == 4
    resource_rows = pa.concat_tables(
        [
            pq.read_table(root_output / part.relative_path)
            for part in resource_transport.parts
        ]
    )
    assert resource_rows.column("child_aware").to_pylist() == [True] * 4
    assert set(resource_rows.column("shard_id").to_pylist()) == {
        shard.shard_id for shard in plan.shards
    }

    first_child = MergeNodeManifest.model_validate_json(
        next(iter(child_manifest_paths.values())).read_text(
            encoding="utf-8"
        )
    )
    first_transport = next(
        item for item in first_child.files
        if item.logical_name == "scientific_output"
    )
    corrupted_part = (
        next(iter(child_manifest_paths.values())).parent
        / first_transport.parts[0].relative_path
    )
    with corrupted_part.open("ab") as stream:
        stream.write(b"corrupt")
    with pytest.raises(PhysicalMergeError, match="transport"):
        merge_plan_group(
            WORKLOAD,
            plan,
            merge_plan,
            root_group.group_id,
            child_root,
            tmp_path / "merge-tree-corrupt-root",
        )
