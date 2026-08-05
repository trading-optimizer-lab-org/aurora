from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from aurora.infra.github_performance import merge_runtime
from aurora.infra.github_performance.contracts import (
    ShardDefinition,
    TerminalState,
    UnitAttemptRecord,
)
from aurora.infra.github_performance.merge_planner import (
    MergePlanError,
    ReconciliationError,
    build_merge_plan,
    reconcile_attempt_files,
    reconcile_attempts,
    write_reconciliation,
    write_unit_attempt_manifest,
)
from aurora.infra.github_performance.shard_planner import (
    write_work_unit_manifest,
)
from github_performance_helpers import (
    completed_unit,
    make_shard,
    make_unit,
    unsupported_unit,
)


def test_conflicting_successful_attempts_block_merge() -> None:
    attempts = [
        completed_unit("u1", "a1", digest="1" * 64),
        completed_unit("u1", "a2", digest="2" * 64),
    ]
    with pytest.raises(ReconciliationError, match="conflicting output"):
        reconcile_attempts({"u1"}, attempts)


def test_identical_duplicate_attempt_is_not_double_counted() -> None:
    result = reconcile_attempts(
        {"u1"},
        [
            completed_unit("u1", "a1", "1" * 64),
            completed_unit("u1", "a2", "1" * 64),
        ],
    )
    assert result.completed == 1
    assert result.identical_duplicate_attempt_ids == ("a2",)
    assert result.partial is False


def test_missing_and_technical_units_make_result_partial() -> None:
    failed = UnitAttemptRecord(
        unit_key="u1",
        shard_id="s000",
        attempt_id="a1",
        state=TerminalState.FAILED_TECHNICAL,
        output_sha256=None,
        reason_code="RUNNER_LOST",
    )
    result = reconcile_attempts({"u1", "u2"}, [failed])
    assert result.failed_technical == 1
    assert result.missing_unit_keys == ("u2",)
    assert result.partial is True


def test_unsupported_and_right_censored_are_terminal() -> None:
    censored = UnitAttemptRecord(
        unit_key="u2",
        shard_id="s000",
        attempt_id="a1",
        state=TerminalState.RIGHT_CENSORED,
        output_sha256=None,
        reason_code="DEADLINE",
    )
    result = reconcile_attempts(
        {"u1", "u2"},
        [unsupported_unit("u1", "NO_DATA"), censored],
    )
    assert result.unsupported == 1
    assert result.right_censored == 1
    assert result.partial is False


def test_reconciliation_table_accounts_for_every_unit(
    tmp_path: Path,
) -> None:
    result = reconcile_attempts(
        {"u1", "u2"},
        [
            completed_unit("u1", "a1", "1" * 64),
            unsupported_unit("u2", "NO_DATA"),
        ],
    )
    path = write_reconciliation(
        result,
        tmp_path / "unit_reconciliation.parquet",
    )
    table = pq.read_table(path)
    assert table.num_rows == 2
    assert set(table.column("unit_key").to_pylist()) == {"u1", "u2"}


def test_streaming_reconciliation_reads_multiple_attempt_files(
    tmp_path: Path,
) -> None:
    expected = write_work_unit_manifest(
        (make_unit(index) for index in range(4)),
        tmp_path / "work_units.parquet",
    )
    first = write_unit_attempt_manifest(
        [
            completed_unit("u0000", "a1", "1" * 64),
            completed_unit("u0002", "a1", "2" * 64),
        ],
        tmp_path / "a.parquet",
    )
    second = write_unit_attempt_manifest(
        [
            unsupported_unit("u0001", "NO_DATA"),
            completed_unit("u0003", "a1", "3" * 64),
        ],
        tmp_path / "b.parquet",
    )
    result = reconcile_attempt_files(
        expected,
        [first, second],
        tmp_path / "unit_reconciliation.parquet",
    )
    assert result.expected_units == 4
    assert result.completed == 3
    assert result.unsupported == 1
    assert result.partial is False
    assert result.unit_records == ()


def test_merge_plan_is_hierarchical_and_bounded() -> None:
    plan = build_merge_plan(
        (make_shard(index) for index in range(360)),
        fan_in=30,
        disk_budget_bytes=10 * 1024**3,
        run_id="test",
    )
    assert max(len(group.input_artifacts) for group in plan.groups) <= 30
    assert max(group.level for group in plan.groups) == 1
    assert len([group for group in plan.groups if group.level == 0]) == 12


def test_merge_plan_covers_7200_shards_across_every_required_level() -> None:
    shards = tuple(
        ShardDefinition.model_construct(
            shard_id=f"s{index:04d}",
            assignment_artifact="run-assignment-bundle-000",
            assignment_member=f"assignments/s{index:04d}.parquet",
            assignment_sha256="8" * 64,
            unit_count=1,
            estimated_seconds=1.0,
            merge_group=f"g{index // 30:03d}",
        )
        for index in range(7200)
    )
    plan = build_merge_plan(
        shards,
        fan_in=30,
        disk_budget_bytes=10 * 1024**4,
        run_id="large",
    )
    by_level = {
        level: tuple(group for group in plan.groups if group.level == level)
        for level in {group.level for group in plan.groups}
    }
    assert {level: len(groups) for level, groups in by_level.items()} == {
        0: 240,
        1: 8,
        2: 1,
    }
    assert all(
        len(group.input_artifacts) <= 30
        for group in plan.groups
    )
    source_inputs = tuple(
        artifact
        for group in by_level[0]
        for artifact in group.input_artifacts
    )
    assert len(source_inputs) == 7200
    assert len(set(source_inputs)) == 7200
    assert set(source_inputs) == {
        f"shard:{shard.shard_id}" for shard in shards
    }
    consumed_children = tuple(
        artifact
        for level in (1, 2)
        for group in by_level[level]
        for artifact in group.input_artifacts
    )
    non_root_outputs = tuple(
        group.output_artifact
        for level in (0, 1)
        for group in by_level[level]
    )
    assert sorted(consumed_children) == sorted(non_root_outputs)
    assert len(consumed_children) == len(set(consumed_children))
    assert all(group.input_artifact_pattern for group in plan.groups)


def test_partitioned_transport_is_deterministic_bounded_and_lossless(
    tmp_path: Path,
) -> None:
    rows = [
        {
            "unit_key": f"u{index:05d}",
            "payload": f"{index:05d}-" + format(index * 982_451_653, "064x"),
        }
        for index in reversed(range(1200))
    ]
    source = tmp_path / "source.parquet"
    pq.write_table(pa.Table.from_pylist(rows), source, compression="zstd")
    writer = getattr(
        merge_runtime,
        "write_partitioned_parquet_transport",
    )
    first = writer(
        source,
        tmp_path / "first",
        logical_name="scientific_output",
        key_columns=("unit_key",),
        target_bytes=12 * 1024,
    )
    second = writer(
        source,
        tmp_path / "second",
        logical_name="scientific_output",
        key_columns=("unit_key",),
        target_bytes=12 * 1024,
    )
    assert len(first.parts) > 1
    assert all(part.byte_count <= 12 * 1024 for part in first.parts)
    assert sum(part.row_count for part in first.parts) == 1200
    assert first.logical_sha256 == second.logical_sha256
    assert [
        (part.row_count, part.first_key, part.last_key)
        for part in first.parts
    ] == [
        (part.row_count, part.first_key, part.last_key)
        for part in second.parts
    ]
    recovered = pa.concat_tables(
        [
            pq.read_table(tmp_path / "first" / part.relative_path)
            for part in first.parts
        ]
    )
    keys = recovered.column("unit_key").to_pylist()
    assert keys == sorted(row["unit_key"] for row in rows)
    assert len(keys) == len(set(keys)) == 1200


def test_partitioned_transport_hashes_persisted_nan_representation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "nan-source.parquet"
    pq.write_table(
        pa.table(
            {
                "unit_key": ["u2", "u1"],
                "metric": [float("nan"), 1.0],
            }
        ),
        source,
        compression="zstd",
    )
    transport = merge_runtime.write_partitioned_parquet_transport(
        source,
        tmp_path / "transport",
        logical_name="scientific_output",
        key_columns=("unit_key",),
        target_bytes=4096,
    )

    paths = merge_runtime.verify_partitioned_parquet_transport(
        tmp_path / "transport",
        transport,
    )

    assert len(paths) == 1
    assert pq.read_table(paths[0]).column("unit_key").to_pylist() == [
        "u1",
        "u2",
    ]


def test_merge_plan_rejects_unsafe_disk_projection() -> None:
    with pytest.raises(MergePlanError, match="MERGE_DISK_BUDGET_EXCEEDED"):
        build_merge_plan(
            (make_shard(index) for index in range(2)),
            fan_in=2,
            disk_budget_bytes=1024,
        )
