"""Deterministic work-unit manifests and balanced GitHub shard assignment."""

from __future__ import annotations

import hashlib
import heapq
import json
import math
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from aurora.infra.github_performance.contracts import (
    MatrixSplit,
    ShardDefinition,
    ShardPlan,
    WorkUnit,
    WorkUnitManifest,
    canonical_sha256,
    deep_thaw_json,
)


WORK_UNIT_SCHEMA_VERSION = "1"
ASSIGNMENT_SCHEMA_VERSION = "1"
ASSIGNMENT_ARTIFACT = "run-assignment-bundle-000"
WORK_UNIT_SCHEMA = pa.schema(
    [
        pa.field("unit_key", pa.string(), nullable=False),
        pa.field("estimated_seconds", pa.float64(), nullable=False),
        pa.field("payload_ref", pa.string(), nullable=False),
        pa.field("payload_sha256", pa.string(), nullable=False),
    ]
)
ASSIGNMENT_SCHEMA = pa.schema(
    [
        pa.field("shard_id", pa.string(), nullable=False),
        pa.field("unit_key", pa.string(), nullable=False),
        pa.field("estimated_seconds", pa.float64(), nullable=False),
        pa.field("payload_ref", pa.string(), nullable=False),
        pa.field("payload_sha256", pa.string(), nullable=False),
    ]
)


class MatrixOutputTooLarge(RuntimeError):
    """Raised before a dynamic matrix can exceed GitHub output limits."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_parquet(
    table: pa.Table,
    path: Path,
    *,
    compression: str = "zstd",
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(
        table,
        temporary,
        compression=compression,
        version="2.6",
        write_statistics=True,
    )
    temporary.replace(path)


def _unit_records(units: Iterable[WorkUnit]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in units:
        unit = raw if isinstance(raw, WorkUnit) else WorkUnit.model_validate(raw)
        if unit.unit_key in seen:
            raise ValueError(f"duplicate work unit: {unit.unit_key}")
        if not math.isfinite(unit.estimated_seconds):
            raise ValueError(f"non-finite estimated_seconds: {unit.unit_key}")
        seen.add(unit.unit_key)
        records.append(unit.model_dump(mode="python"))
    records.sort(key=lambda row: row["unit_key"])
    return records


def write_work_unit_manifest(
    units: Iterable[WorkUnit],
    path: Path,
) -> WorkUnitManifest:
    """Write the canonical, order-independent work-unit manifest."""

    records = _unit_records(units)
    metadata = {
        b"schema_version": WORK_UNIT_SCHEMA_VERSION.encode("ascii"),
        b"sorted_by": b"unit_key",
    }
    table = pa.Table.from_pylist(
        records,
        schema=WORK_UNIT_SCHEMA.with_metadata(metadata),
    )
    _atomic_write_parquet(table, Path(path))
    return WorkUnitManifest(
        path=str(Path(path)),
        sha256=sha256_file(Path(path)),
        schema_version=WORK_UNIT_SCHEMA_VERSION,
        unit_count=len(records),
        total_estimated_seconds=sum(
            float(record["estimated_seconds"]) for record in records
        ),
    )


def read_work_units(manifest: WorkUnitManifest) -> tuple[WorkUnit, ...]:
    """Read and verify only planner columns from one immutable manifest."""

    path = Path(manifest.path)
    if sha256_file(path) != manifest.sha256:
        raise ValueError("work-unit manifest hash mismatch")
    table = pq.read_table(path, columns=WORK_UNIT_SCHEMA.names)
    records = table.to_pylist()
    if len(records) != manifest.unit_count:
        raise ValueError("work-unit manifest count mismatch")
    units = tuple(WorkUnit.model_validate(record) for record in records)
    if len({unit.unit_key for unit in units}) != len(units):
        raise ValueError("work-unit manifest contains duplicate keys")
    measured_total = sum(unit.estimated_seconds for unit in units)
    if not math.isclose(
        measured_total,
        manifest.total_estimated_seconds,
        rel_tol=0,
        abs_tol=1e-9,
    ):
        raise ValueError("work-unit manifest estimated time mismatch")
    return units


def _assignment_table(
    shard_id: str,
    units: Iterable[WorkUnit],
) -> pa.Table:
    records = [
        {
            "shard_id": shard_id,
            **unit.model_dump(mode="python"),
        }
        for unit in sorted(units, key=lambda item: item.unit_key)
    ]
    metadata = {
        b"schema_version": ASSIGNMENT_SCHEMA_VERSION.encode("ascii"),
        b"sorted_by": b"shard_id,unit_key",
    }
    return pa.Table.from_pylist(
        records,
        schema=ASSIGNMENT_SCHEMA.with_metadata(metadata),
    )


def weighted_lpt(
    manifest: WorkUnitManifest,
    jobs: int,
    output_dir: Path,
) -> ShardPlan:
    """Assign longest units first to the currently lightest shard."""

    units = read_work_units(manifest)
    if not units:
        raise ValueError("cannot shard an empty work-unit manifest")
    if jobs < 1 or jobs > min(len(units), 360):
        raise ValueError("jobs must be between 1 and min(unit_count, 360)")

    shard_ids = tuple(f"s{index:03d}" for index in range(jobs))
    assignments: list[list[WorkUnit]] = [[] for _ in range(jobs)]
    heap: list[tuple[float, str, int]] = [
        (0.0, shard_id, index)
        for index, shard_id in enumerate(shard_ids)
    ]
    heapq.heapify(heap)
    for unit in sorted(
        units,
        key=lambda item: (-item.estimated_seconds, item.unit_key),
    ):
        current_seconds, shard_id, index = heapq.heappop(heap)
        assignments[index].append(unit)
        heapq.heappush(
            heap,
            (current_seconds + unit.estimated_seconds, shard_id, index),
        )

    root = Path(output_dir)
    all_tables: list[pa.Table] = []
    shards: list[ShardDefinition] = []
    for index, shard_id in enumerate(shard_ids):
        shard_units = assignments[index]
        if not shard_units:
            raise AssertionError("weighted LPT produced an empty shard")
        table = _assignment_table(shard_id, shard_units)
        member = Path("assignments") / f"{shard_id}.parquet"
        member_path = root / member
        _atomic_write_parquet(table, member_path)
        all_tables.append(table)
        shards.append(
            ShardDefinition(
                shard_id=shard_id,
                assignment_artifact=ASSIGNMENT_ARTIFACT,
                assignment_member=member.as_posix(),
                assignment_sha256=sha256_file(member_path),
                unit_count=len(shard_units),
                estimated_seconds=sum(
                    unit.estimated_seconds for unit in shard_units
                ),
                merge_group=f"g{index // 30:03d}",
            )
        )

    catalog = pa.concat_tables(all_tables)
    sort_indices = pc.sort_indices(
        catalog,
        sort_keys=[("shard_id", "ascending"), ("unit_key", "ascending")],
    )
    catalog = pc.take(catalog, sort_indices)
    catalog_path = root / "balanced_unit_assignments.parquet"
    _atomic_write_parquet(catalog, catalog_path)
    assignment_manifest_sha256 = sha256_file(catalog_path)
    plan_payload = {
        "selected_jobs": jobs,
        "work_unit_manifest_sha256": manifest.sha256,
        "assignment_artifact": ASSIGNMENT_ARTIFACT,
        "assignment_manifest_sha256": assignment_manifest_sha256,
        "shards": [deep_thaw_json(shard) for shard in shards],
    }
    return ShardPlan(
        **plan_payload,
        plan_sha256=canonical_sha256(plan_payload),
    )


def split_matrices(
    shards: Iterable[ShardDefinition],
    matrix_ceiling: int = 256,
) -> MatrixSplit:
    """Split at most 360 standard-runner shards into GitHub-safe matrices."""

    materialized = tuple(shards)
    if matrix_ceiling < 1 or matrix_ceiling > 256:
        raise ValueError("matrix_ceiling must be between 1 and 256")
    if len(materialized) > 360:
        raise ValueError("standard-runner plan cannot exceed 360 shards")
    matrix_a = materialized[:matrix_ceiling]
    matrix_b = materialized[matrix_ceiling:]
    if len(matrix_b) > 104:
        raise ValueError("second matrix cannot exceed 104 standard jobs")
    return MatrixSplit(
        matrix_a=matrix_a,
        matrix_b=matrix_b,
        has_matrix_b=bool(matrix_b),
    )


def encode_matrix_outputs(
    split: MatrixSplit,
    max_bytes: int = 262_144,
) -> Mapping[str, str]:
    """Encode compact shard descriptors, never logical unit lists."""

    payload = {
        "matrix_a_json": json.dumps(
            {"include": [deep_thaw_json(item) for item in split.matrix_a]},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ),
        "matrix_b_json": json.dumps(
            {"include": [deep_thaw_json(item) for item in split.matrix_b]},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ),
        "has_matrix_b": "true" if split.has_matrix_b else "false",
    }
    encoded_bytes = sum(
        len(value.encode("utf-8")) for value in payload.values()
    )
    if encoded_bytes >= max_bytes:
        raise MatrixOutputTooLarge(
            f"matrix outputs require {encoded_bytes} bytes; limit is {max_bytes}"
        )
    return payload
