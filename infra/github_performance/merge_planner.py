"""Bounded hierarchical merging and exact logical-unit reconciliation."""

from __future__ import annotations

import heapq
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from itertools import groupby
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from aurora.infra.github_performance.contracts import (
    AttemptManifest,
    MergeGroup,
    MergePlan,
    ReconciliationResult,
    ShardDefinition,
    TerminalState,
    UnitAttemptRecord,
    UnitReconciliationRecord,
    WorkUnitManifest,
    canonical_sha256,
    deep_thaw_json,
)
from aurora.infra.github_performance.shard_planner import sha256_file


UNIT_ATTEMPT_SCHEMA_VERSION = "1"
SHARD_ATTEMPT_SCHEMA_VERSION = "2"
RECONCILIATION_SCHEMA_VERSION = "1"
DEFAULT_PARTITION_TARGET_BYTES = 512 * 1024**2
MAX_GITHUB_MATRIX_JOBS = 256
MAX_WORKFLOW_MERGE_LEVELS = 4
UNIT_ATTEMPT_SCHEMA = pa.schema(
    [
        pa.field("unit_key", pa.string(), nullable=False),
        pa.field("shard_id", pa.string(), nullable=False),
        pa.field("attempt_id", pa.string(), nullable=False),
        pa.field("state", pa.string(), nullable=False),
        pa.field("output_sha256", pa.string(), nullable=True),
        pa.field("reason_code", pa.string(), nullable=True),
    ]
)
SHARD_ATTEMPT_SCHEMA = pa.schema(
    [
        pa.field("shard_id", pa.string(), nullable=False),
        pa.field("attempt_id", pa.string(), nullable=False),
        pa.field("state", pa.string(), nullable=False),
        pa.field("spec_hash", pa.string(), nullable=False),
        pa.field("policy_hash", pa.string(), nullable=False),
        pa.field("snapshot_hash", pa.string(), nullable=False),
        pa.field("code_sha", pa.string(), nullable=False),
        pa.field("dependency_lock_sha256", pa.string(), nullable=False),
        pa.field("capacity_profile_sha256", pa.string(), nullable=False),
        pa.field("output_sha256", pa.string(), nullable=True),
        pa.field("reason_code", pa.string(), nullable=True),
        pa.field("artifact_name", pa.string(), nullable=True),
        pa.field("unit_attempts_path", pa.string(), nullable=True),
        pa.field("unit_attempts_sha256", pa.string(), nullable=True),
        pa.field("checkpoint_artifact", pa.string(), nullable=True),
        pa.field("completed_unit_count", pa.int64(), nullable=False),
        pa.field("output_rows", pa.int64(), nullable=False),
        pa.field("output_bytes", pa.int64(), nullable=False),
        pa.field("runtime_access_ledger_path", pa.string(), nullable=True),
        pa.field("runtime_access_ledger_sha256", pa.string(), nullable=True),
        pa.field("metric_inputs_path", pa.string(), nullable=True),
        pa.field("metric_inputs_sha256", pa.string(), nullable=True),
    ]
)
RECONCILIATION_SCHEMA = pa.schema(
    [
        pa.field("unit_key", pa.string(), nullable=False),
        pa.field("state", pa.string(), nullable=False),
        pa.field("selected_attempt_id", pa.string(), nullable=False),
        pa.field("output_sha256", pa.string(), nullable=True),
        pa.field("reason_code", pa.string(), nullable=True),
        pa.field("duplicate_attempt_ids_json", pa.string(), nullable=False),
    ]
)


class MergePlanError(RuntimeError):
    """Raised when a merge group is unsafe for the configured disk budget."""


class ReconciliationError(RuntimeError):
    """Raised when logical results are missing, unexpected, or conflicting."""


def _atomic_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            deep_thaw_json(payload),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _projected_shard_bytes(shard: ShardDefinition) -> int:
    return max(4096, shard.unit_count * 512)


def build_merge_plan(
    shards: Iterable[ShardDefinition],
    fan_in: int,
    disk_budget_bytes: int,
    *,
    projected_bytes_by_shard: Mapping[str, int] | None = None,
    run_id: str = "run",
    source_artifact_prefix: str = "{run_label}",
    partition_target_bytes: int = DEFAULT_PARTITION_TARGET_BYTES,
    max_groups_per_level: int = MAX_GITHUB_MATRIX_JOBS,
    max_levels: int = MAX_WORKFLOW_MERGE_LEVELS,
) -> MergePlan:
    """Build all immutable merge levels while bounding local disk usage."""

    if fan_in < 2:
        raise ValueError("fan_in must be at least 2")
    if disk_budget_bytes <= 0:
        raise ValueError("disk_budget_bytes must be positive")
    if partition_target_bytes < 4096:
        raise ValueError("partition_target_bytes must be at least 4096")
    if not 1 <= max_groups_per_level <= MAX_GITHUB_MATRIX_JOBS:
        raise ValueError("max_groups_per_level exceeds GitHub limits")
    if max_levels < 1:
        raise ValueError("max_levels must be positive")
    ordered = tuple(
        sorted(shards, key=lambda item: (item.merge_group, item.shard_id))
    )
    if not ordered:
        raise ValueError("cannot merge an empty shard plan")
    if len({item.shard_id for item in ordered}) != len(ordered):
        raise ValueError("duplicate shard_id in merge inputs")
    byte_map = projected_bytes_by_shard or {}
    source_groups = tuple(
        (
            merge_group,
            tuple(group),
        )
        for merge_group, group in groupby(
            ordered,
            key=lambda item: item.merge_group,
        )
    )
    if any(len(group) > fan_in for _, group in source_groups):
        raise MergePlanError(
            "MERGE_SOURCE_GROUP_EXCEEDS_FAN_IN: shard merge group is "
            "larger than configured fan-in"
        )
    if len(source_groups) > max_groups_per_level:
        raise MergePlanError(
            "MERGE_MATRIX_LIMIT_EXCEEDED: first merge level requires "
            f"{len(source_groups)} groups"
        )
    seed = canonical_sha256(
        {
            "run_id": run_id,
            "fan_in": fan_in,
            "disk_budget_bytes": disk_budget_bytes,
            "partition_target_bytes": partition_target_bytes,
            "max_groups_per_level": max_groups_per_level,
            "max_levels": max_levels,
            "inputs": [
                (
                    shard.shard_id,
                    shard.merge_group,
                    int(
                        byte_map.get(
                            shard.shard_id,
                            _projected_shard_bytes(shard),
                        )
                    ),
                )
                for shard in ordered
            ],
        }
    )
    groups: list[MergeGroup] = []
    current: list[tuple[str, int]] = []
    for group_index, (source_group, members) in enumerate(source_groups):
        input_bytes = sum(
            int(
                byte_map.get(
                    shard.shard_id,
                    _projected_shard_bytes(shard),
                )
            )
            for shard in members
        )
        output_bytes = max(1024, math.ceil(input_bytes * 0.80))
        if input_bytes + output_bytes > int(disk_budget_bytes * 0.80):
            raise MergePlanError(
                "MERGE_DISK_BUDGET_EXCEEDED: projected group requires "
                f"{input_bytes + output_bytes} bytes"
            )
        group_id = f"l00-g{group_index:03d}"
        output = (
            f"{run_id}-merge-l00-p{group_index // fan_in:03d}-"
            f"g{group_index:03d}-{seed[:12]}"
        )
        groups.append(
            MergeGroup(
                group_id=group_id,
                level=0,
                input_artifacts=tuple(
                    f"shard:{shard.shard_id}" for shard in members
                ),
                input_artifact_pattern=(
                    f"{source_artifact_prefix}-shard-{source_group}-*"
                ),
                projected_input_bytes=input_bytes,
                projected_output_bytes=output_bytes,
                output_artifact=output,
            )
        )
        current.append((output, output_bytes))
    level = 1
    while len(current) > 1:
        if level >= max_levels:
            raise MergePlanError(
                "MERGE_LEVEL_LIMIT_EXCEEDED: immutable plan requires "
                f"more than {max_levels} levels"
            )
        next_level: list[tuple[str, int]] = []
        for group_index, start in enumerate(range(0, len(current), fan_in)):
            members = current[start : start + fan_in]
            input_bytes = sum(size for _, size in members)
            output_bytes = max(1024, math.ceil(input_bytes * 0.80))
            if input_bytes + output_bytes > int(disk_budget_bytes * 0.80):
                raise MergePlanError(
                    "MERGE_DISK_BUDGET_EXCEEDED: projected group requires "
                    f"{input_bytes + output_bytes} bytes"
                )
            group_id = f"l{level:02d}-g{group_index:03d}"
            output = (
                f"{run_id}-merge-l{level:02d}-"
                f"p{group_index // fan_in:03d}-"
                f"g{group_index:03d}-{seed[:12]}"
            )
            groups.append(
                MergeGroup(
                    group_id=group_id,
                    level=level,
                    input_artifacts=tuple(name for name, _ in members),
                    input_artifact_pattern=(
                        f"{run_id}-merge-l{level - 1:02d}-"
                        f"p{group_index:03d}-*"
                    ),
                    projected_input_bytes=input_bytes,
                    projected_output_bytes=output_bytes,
                    output_artifact=output,
                )
            )
            next_level.append((output, output_bytes))
        if len(next_level) == 1:
            current = next_level
            break
        current = next_level
        level += 1
        if len(current) > max_groups_per_level:
            raise MergePlanError(
                "MERGE_MATRIX_LIMIT_EXCEEDED: merge level requires "
                f"{len(current)} groups"
            )
    if not current:
        raise MergePlanError("merge plan did not produce a root")
    root_artifact = current[0][0]
    root_group = next(
        group for group in reversed(groups)
        if group.output_artifact == root_artifact
    )
    payload = {
        "fan_in": fan_in,
        "partition_target_bytes": partition_target_bytes,
        "max_groups_per_level": max_groups_per_level,
        "max_levels": max_levels,
        "groups": [deep_thaw_json(group) for group in groups],
        "root_artifact": root_artifact,
        "root_level": root_group.level,
    }
    return MergePlan(
        **payload,
        plan_sha256=canonical_sha256(payload),
    )


def build_merge_level_matrices(
    plan: MergePlan,
) -> Mapping[int, tuple[Mapping[str, Any], ...]]:
    """Encode every immutable merge level as compact matrix descriptors."""

    matrices: dict[int, tuple[Mapping[str, Any], ...]] = {}
    for level in range(plan.max_levels):
        groups = tuple(
            group for group in plan.groups if group.level == level
        )
        if len(groups) > plan.max_groups_per_level:
            raise MergePlanError(
                "MERGE_MATRIX_LIMIT_EXCEEDED: merge level requires "
                f"{len(groups)} groups"
            )
        matrices[level] = tuple(
            {
                "group_id": group.group_id,
                "level": group.level,
                "input_artifact_pattern": (
                    group.input_artifact_pattern
                ),
                "output_artifact": group.output_artifact,
                "projected_input_bytes": group.projected_input_bytes,
                "projected_output_bytes": group.projected_output_bytes,
            }
            for group in groups
        )
    return matrices


def write_merge_plan(plan: MergePlan, path: Path) -> Path:
    return _atomic_json(Path(path), plan)


def _select_unit_attempt(
    unit_key: str,
    attempts: Sequence[UnitAttemptRecord],
) -> tuple[UnitReconciliationRecord, tuple[str, ...]]:
    ordered = tuple(sorted(attempts, key=lambda item: item.attempt_id))
    completed = tuple(
        item for item in ordered if item.state is TerminalState.COMPLETED
    )
    if completed:
        digests = {item.output_sha256 for item in completed}
        if len(digests) != 1:
            raise ReconciliationError(
                f"conflicting output hashes for unit {unit_key}"
            )
        selected = completed[0]
        duplicates = tuple(item.attempt_id for item in completed[1:])
    else:
        selected = ordered[-1]
        duplicates = tuple(
            item.attempt_id
            for item in ordered[:-1]
            if (
                item.state,
                item.output_sha256,
                item.reason_code,
            )
            == (
                selected.state,
                selected.output_sha256,
                selected.reason_code,
            )
        )
    return (
        UnitReconciliationRecord(
            unit_key=unit_key,
            state=selected.state,
            selected_attempt_id=selected.attempt_id,
            output_sha256=selected.output_sha256,
            reason_code=selected.reason_code,
            duplicate_attempt_ids=duplicates,
        ),
        duplicates,
    )


def _result_from_records(
    expected_count: int,
    records: Sequence[UnitReconciliationRecord],
    *,
    duplicate_attempt_ids: Iterable[str] = (),
    missing_unit_keys: Iterable[str] = (),
) -> ReconciliationResult:
    counts = {state: 0 for state in TerminalState}
    for record in records:
        counts[record.state] += 1
    missing = tuple(sorted(missing_unit_keys))
    failed = counts[TerminalState.FAILED_TECHNICAL]
    return ReconciliationResult(
        expected_units=expected_count,
        completed=counts[TerminalState.COMPLETED],
        right_censored=counts[TerminalState.RIGHT_CENSORED],
        unsupported=counts[TerminalState.UNSUPPORTED],
        failed_technical=failed,
        selected_attempt_ids=tuple(
            record.selected_attempt_id for record in records
        ),
        identical_duplicate_attempt_ids=tuple(
            sorted(duplicate_attempt_ids)
        ),
        conflicting_unit_keys=(),
        missing_unit_keys=missing,
        partial=bool(missing or failed),
        unit_records=tuple(records),
    )


def reconcile_attempts(
    expected_units: Iterable[str],
    attempts: Sequence[UnitAttemptRecord],
) -> ReconciliationResult:
    """Reference reconciliation for bounded tests and small campaigns."""

    expected = tuple(sorted(expected_units))
    if len(expected) != len(set(expected)):
        raise ReconciliationError("expected unit keys contain duplicates")
    expected_set = set(expected)
    grouped: dict[str, list[UnitAttemptRecord]] = defaultdict(list)
    for attempt in attempts:
        if attempt.unit_key not in expected_set:
            raise ReconciliationError(
                f"unexpected unit attempt: {attempt.unit_key}"
            )
        grouped[attempt.unit_key].append(attempt)
    records: list[UnitReconciliationRecord] = []
    duplicates: list[str] = []
    missing: list[str] = []
    for unit_key in expected:
        candidates = grouped.get(unit_key, [])
        if not candidates:
            missing.append(unit_key)
            continue
        record, duplicate_ids = _select_unit_attempt(unit_key, candidates)
        records.append(record)
        duplicates.extend(duplicate_ids)
    return _result_from_records(
        len(expected),
        records,
        duplicate_attempt_ids=duplicates,
        missing_unit_keys=missing,
    )


def _reconciliation_rows(
    records: Iterable[UnitReconciliationRecord],
) -> Iterator[dict[str, Any]]:
    for record in records:
        yield {
            "unit_key": record.unit_key,
            "state": record.state.value,
            "selected_attempt_id": record.selected_attempt_id,
            "output_sha256": record.output_sha256,
            "reason_code": record.reason_code,
            "duplicate_attempt_ids_json": json.dumps(
                record.duplicate_attempt_ids,
                separators=(",", ":"),
            ),
        }


def _write_reconciliation_records(
    records: Iterable[UnitReconciliationRecord],
    path: Path,
    *,
    summary: ReconciliationResult | None = None,
    batch_size: int = 10_000,
) -> Path:
    metadata = {
        b"schema_version": RECONCILIATION_SCHEMA_VERSION.encode("ascii"),
    }
    if summary is not None:
        metadata[b"summary_json"] = json.dumps(
            {
                "expected_units": summary.expected_units,
                "completed": summary.completed,
                "right_censored": summary.right_censored,
                "unsupported": summary.unsupported,
                "failed_technical": summary.failed_technical,
                "missing_units": len(summary.missing_unit_keys),
                "partial": summary.partial,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    schema = RECONCILIATION_SCHEMA.with_metadata(metadata)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    writer = pq.ParquetWriter(
        temporary,
        schema,
        compression="zstd",
        version="2.6",
    )
    pending: list[dict[str, Any]] = []
    try:
        for row in _reconciliation_rows(records):
            pending.append(row)
            if len(pending) >= batch_size:
                writer.write_table(pa.Table.from_pylist(pending, schema=schema))
                pending.clear()
        if pending:
            writer.write_table(pa.Table.from_pylist(pending, schema=schema))
        elif temporary.stat().st_size == 0:
            writer.write_table(pa.Table.from_pylist([], schema=schema))
    finally:
        writer.close()
    temporary.replace(path)
    return path


def write_reconciliation(
    result: ReconciliationResult,
    path: Path,
) -> Path:
    return _write_reconciliation_records(
        result.unit_records,
        Path(path),
        summary=result,
    )


def write_unit_attempt_manifest(
    attempts: Iterable[UnitAttemptRecord],
    path: Path,
) -> Path:
    records = [
        {
            **deep_thaw_json(attempt),
            "state": attempt.state.value,
        }
        for attempt in sorted(
            attempts,
            key=lambda item: (item.unit_key, item.attempt_id),
        )
    ]
    schema = UNIT_ATTEMPT_SCHEMA.with_metadata(
        {b"schema_version": UNIT_ATTEMPT_SCHEMA_VERSION.encode("ascii")}
    )
    table = pa.Table.from_pylist(records, schema=schema)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", version="2.6")
    temporary.replace(path)
    return path


def write_shard_attempt_manifest(
    attempts: Iterable[AttemptManifest],
    path: Path,
) -> Path:
    records = [
        {
            **deep_thaw_json(attempt),
            "state": attempt.state.value,
        }
        for attempt in sorted(
            attempts,
            key=lambda item: (item.shard_id, item.attempt_id),
        )
    ]
    schema = SHARD_ATTEMPT_SCHEMA.with_metadata(
        {b"schema_version": SHARD_ATTEMPT_SCHEMA_VERSION.encode("ascii")}
    )
    table = pa.Table.from_pylist(records, schema=schema)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", version="2.6")
    temporary.replace(path)
    return path


def _attempt_rows(path: Path) -> Iterator[tuple[str, str, dict[str, Any]]]:
    parquet = pq.ParquetFile(path)
    previous: tuple[str, str] | None = None
    for batch in parquet.iter_batches(
        batch_size=8192,
        columns=UNIT_ATTEMPT_SCHEMA.names,
    ):
        for row in batch.to_pylist():
            current = (row["unit_key"], row["attempt_id"])
            if previous is not None and current < previous:
                raise ReconciliationError(
                    f"attempt file is not sorted: {path}"
                )
            previous = current
            yield current[0], current[1], row


def _expected_keys(manifest: WorkUnitManifest) -> Iterator[str]:
    parquet = pq.ParquetFile(manifest.path)
    for batch in parquet.iter_batches(
        batch_size=8192,
        columns=["unit_key"],
    ):
        yield from batch.column(0).to_pylist()


def reconcile_attempt_files(
    expected_manifest: WorkUnitManifest,
    attempt_paths: Sequence[Path],
    output_path: Path,
) -> ReconciliationResult:
    """Stream sorted Parquet attempts without global Python sets."""

    if sha256_file(Path(expected_manifest.path)) != expected_manifest.sha256:
        raise ReconciliationError("expected manifest hash mismatch")
    iterators = [_attempt_rows(Path(path)) for path in attempt_paths]
    merged = heapq.merge(*iterators, key=lambda row: (row[0], row[1]))
    grouped = groupby(merged, key=lambda row: row[0])
    current_group = next(grouped, None)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    schema = RECONCILIATION_SCHEMA.with_metadata(
        {b"schema_version": RECONCILIATION_SCHEMA_VERSION.encode("ascii")}
    )
    writer = pq.ParquetWriter(
        temporary,
        schema,
        compression="zstd",
        version="2.6",
    )
    pending: list[dict[str, Any]] = []
    counts = {state: 0 for state in TerminalState}
    missing_count = 0
    missing_sample: list[str] = []
    selected_count = 0
    duplicate_count = 0

    def flush() -> None:
        if pending:
            writer.write_table(pa.Table.from_pylist(pending, schema=schema))
            pending.clear()

    try:
        for expected_key in _expected_keys(expected_manifest):
            while (
                current_group is not None
                and current_group[0] < expected_key
            ):
                raise ReconciliationError(
                    f"unexpected unit attempt: {current_group[0]}"
                )
            if current_group is None or current_group[0] > expected_key:
                missing_count += 1
                if len(missing_sample) < 100:
                    missing_sample.append(expected_key)
                continue
            raw_attempts = [
                UnitAttemptRecord.model_validate(row[2])
                for row in current_group[1]
            ]
            record, duplicate_ids = _select_unit_attempt(
                expected_key,
                raw_attempts,
            )
            pending.append(next(_reconciliation_rows((record,))))
            counts[record.state] += 1
            selected_count += 1
            duplicate_count += len(duplicate_ids)
            if len(pending) >= 10_000:
                flush()
            current_group = next(grouped, None)
        if current_group is not None:
            raise ReconciliationError(
                f"unexpected unit attempt: {current_group[0]}"
            )
        flush()
        if selected_count == 0:
            writer.write_table(pa.Table.from_pylist([], schema=schema))
        summary_payload = {
            "expected_units": expected_manifest.unit_count,
            "completed": counts[TerminalState.COMPLETED],
            "right_censored": counts[TerminalState.RIGHT_CENSORED],
            "unsupported": counts[TerminalState.UNSUPPORTED],
            "failed_technical": counts[TerminalState.FAILED_TECHNICAL],
            "missing_units": missing_count,
            "selected_attempts": selected_count,
            "identical_duplicate_attempts": duplicate_count,
            "partial": bool(
                missing_count
                or counts[TerminalState.FAILED_TECHNICAL]
            ),
        }
        writer.add_key_value_metadata(
            {
                "summary_json": json.dumps(
                    summary_payload,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            }
        )
        writer.close()
        temporary.replace(output_path)
    except BaseException:
        writer.close()
        temporary.unlink(missing_ok=True)
        raise
    return ReconciliationResult(
        expected_units=expected_manifest.unit_count,
        completed=counts[TerminalState.COMPLETED],
        right_censored=counts[TerminalState.RIGHT_CENSORED],
        unsupported=counts[TerminalState.UNSUPPORTED],
        failed_technical=counts[TerminalState.FAILED_TECHNICAL],
        selected_attempt_ids=(),
        identical_duplicate_attempt_ids=(),
        conflicting_unit_keys=(),
        missing_unit_keys=tuple(missing_sample),
        partial=bool(
            missing_count or counts[TerminalState.FAILED_TECHNICAL]
        ),
        unit_records=(),
    )
