"""Bounded physical merge helpers used by the reusable GitHub workflow."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from aurora.infra.github_performance.contracts import (
    AttemptManifest,
    MergeNodeManifest,
    MergePlan,
    PartitionedTransport,
    RunSpec,
    ShardPlan,
    TerminalState,
    TransportPart,
    WorkUnitManifest,
    canonical_sha256,
    deep_thaw_json,
)
from aurora.infra.github_performance.audits import (
    build_required_audits,
    combine_runtime_access_ledgers,
    write_required_audits,
    write_runtime_access_ledger,
)
from aurora.infra.github_performance.benchmark import (
    scientific_content_identity_from_output,
)
from aurora.infra.github_performance.merge_planner import (
    SHARD_ATTEMPT_SCHEMA,
    UNIT_ATTEMPT_SCHEMA,
    reconcile_attempt_files,
    write_shard_attempt_manifest,
)
from aurora.infra.github_performance.metric_verifier import (
    MetricInputRecord,
    read_metric_inputs,
    verify_metric_inputs,
    write_independent_metric_verification,
    write_metric_inputs,
)
from aurora.infra.github_performance.shard_planner import sha256_file
from aurora.infra.github_performance.workload import GithubWorkload


class PhysicalMergeError(RuntimeError):
    """Raised when attempt artifacts cannot be merged without ambiguity."""


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


def _logical_table_sha256(table: pa.Table) -> str:
    table = table.combine_chunks()
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()


def _key_text(
    table: pa.Table,
    row_index: int,
    key_columns: Sequence[str],
) -> str:
    values = [
        table.column(name)[row_index].as_py()
        for name in key_columns
    ]
    return json.dumps(
        values,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )


def write_partitioned_parquet_transport(
    source_path: Path,
    output_dir: Path,
    *,
    logical_name: str,
    key_columns: Sequence[str],
    target_bytes: int,
) -> PartitionedTransport:
    """Split one Parquet file deterministically under a strict byte target."""

    if target_bytes < 4096:
        raise ValueError("target_bytes must be at least 4096")
    source = Path(source_path)
    table = pq.read_table(source)
    keys = tuple(str(name) for name in key_columns)
    missing = tuple(name for name in keys if name not in table.column_names)
    if missing:
        raise PhysicalMergeError(
            "partition logical keys are missing: " + ", ".join(missing)
        )
    if table.num_rows:
        indices = pc.sort_indices(
            table,
            sort_keys=[(name, "ascending") for name in keys],
        )
        table = pc.take(table, indices)
    root = Path(output_dir)
    part_root = root / logical_name
    part_root.mkdir(parents=True, exist_ok=True)
    for stale in part_root.glob("part-*.parquet"):
        stale.unlink()
    (part_root / ".probe.parquet").unlink(missing_ok=True)
    parts: list[TransportPart] = []
    start = 0
    part_index = 0
    total_rows = table.num_rows
    if total_rows:
        estimated_row_bytes = max(1.0, table.nbytes / total_rows)
        metadata_reserve = min(8192, target_bytes // 4)
        rows_per_part = max(
            1,
            int(
                ((target_bytes - metadata_reserve) / estimated_row_bytes)
                * 0.90
            ),
        )
    else:
        rows_per_part = 0
    while start < total_rows or (total_rows == 0 and not parts):
        if total_rows == 0:
            best_end = 0
        else:
            current_rows = min(rows_per_part, total_rows - start)
            path = part_root / f"part-{part_index:05d}.parquet"
            while True:
                best_end = start + current_rows
                pq.write_table(
                    table.slice(start, current_rows),
                    path,
                    compression="zstd",
                    version="2.6",
                )
                if path.stat().st_size <= target_bytes:
                    rows_per_part = current_rows
                    break
                if current_rows == 1:
                    path.unlink(missing_ok=True)
                    raise PhysicalMergeError(
                        "PARTITION_TARGET_TOO_SMALL_FOR_ONE_LOGICAL_ROW"
                    )
                current_rows = max(1, current_rows // 2)
        path = part_root / f"part-{part_index:05d}.parquet"
        if total_rows == 0:
            pq.write_table(
                table,
                path,
                compression="zstd",
                version="2.6",
            )
        byte_count = path.stat().st_size
        if byte_count > target_bytes:
            raise PhysicalMergeError(
                "partition writer exceeded configured byte target"
            )
        row_count = best_end - start
        first_key = (
            _key_text(table, start, keys) if row_count else "[]"
        )
        last_key = (
            _key_text(table, best_end - 1, keys) if row_count else "[]"
        )
        parts.append(
            TransportPart(
                relative_path=str(path.relative_to(root)).replace("\\", "/"),
                sha256=sha256_file(path),
                byte_count=byte_count,
                row_count=row_count,
                first_key=first_key,
                last_key=last_key,
            )
        )
        start = best_end
        part_index += 1
        if total_rows == 0:
            break
    return PartitionedTransport(
        logical_name=logical_name,
        source_file_name=source.name,
        format="parquet",
        key_columns=keys,
        schema_sha256=hashlib.sha256(
            table.schema.serialize().to_pybytes()
        ).hexdigest(),
        logical_sha256=_logical_table_sha256(table),
        row_count=table.num_rows,
        target_bytes=target_bytes,
        parts=tuple(parts),
    )


def verify_partitioned_parquet_transport(
    root: Path,
    transport: PartitionedTransport,
) -> tuple[Path, ...]:
    """Verify every immutable part and its partition-independent hash."""

    paths: list[Path] = []
    tables: list[pa.Table] = []
    for part in transport.parts:
        path = Path(root) / part.relative_path
        if not path.is_file():
            raise PhysicalMergeError(
                f"transport part is missing: {part.relative_path}"
            )
        if path.stat().st_size != part.byte_count:
            raise PhysicalMergeError(
                f"transport byte count changed: {part.relative_path}"
            )
        if sha256_file(path) != part.sha256:
            raise PhysicalMergeError(
                f"transport hash mismatch: {part.relative_path}"
            )
        table = pq.read_table(path)
        if table.num_rows != part.row_count:
            raise PhysicalMergeError(
                f"transport row count changed: {part.relative_path}"
            )
        if table.num_rows:
            first = _key_text(table, 0, transport.key_columns)
            last = _key_text(
                table,
                table.num_rows - 1,
                transport.key_columns,
            )
            if first != part.first_key or last != part.last_key:
                raise PhysicalMergeError(
                    f"transport key bounds changed: {part.relative_path}"
                )
        paths.append(path)
        tables.append(table)
    combined = (
        pa.concat_tables(tables)
        if tables
        else pa.table({})
    )
    if combined.num_rows != transport.row_count:
        raise PhysicalMergeError("transport total row count changed")
    if hashlib.sha256(
        combined.schema.serialize().to_pybytes()
    ).hexdigest() != transport.schema_sha256:
        raise PhysicalMergeError("transport schema hash mismatch")
    if _logical_table_sha256(combined) != transport.logical_sha256:
        raise PhysicalMergeError("transport logical hash mismatch")
    return tuple(paths)


def _write_binary_transport(
    source_path: Path,
    output_dir: Path,
    *,
    logical_name: str,
    target_bytes: int,
) -> PartitionedTransport:
    source = Path(source_path)
    byte_count = source.stat().st_size
    if byte_count > target_bytes:
        raise PhysicalMergeError(
            "oversized non-Parquet output cannot be split by logical key"
        )
    root = Path(output_dir)
    target = (
        root
        / logical_name
        / f"part-00000{source.suffix or '.bin'}"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    digest = sha256_file(target)
    return PartitionedTransport(
        logical_name=logical_name,
        source_file_name=source.name,
        format="binary",
        key_columns=(),
        schema_sha256=hashlib.sha256(b"binary").hexdigest(),
        logical_sha256=digest,
        row_count=0,
        target_bytes=target_bytes,
        parts=(
            TransportPart(
                relative_path=str(target.relative_to(root)).replace(
                    "\\",
                    "/",
                ),
                sha256=digest,
                byte_count=byte_count,
                row_count=0,
                first_key="[]",
                last_key="[]",
            ),
        ),
    )


def _verify_transport(
    root: Path,
    transport: PartitionedTransport,
) -> tuple[Path, ...]:
    if transport.format == "parquet":
        return verify_partitioned_parquet_transport(root, transport)
    if len(transport.parts) != 1:
        raise PhysicalMergeError("binary transport must contain one part")
    part = transport.parts[0]
    path = Path(root) / part.relative_path
    if (
        not path.is_file()
        or path.stat().st_size != part.byte_count
        or sha256_file(path) != part.sha256
        or part.sha256 != transport.logical_sha256
    ):
        raise PhysicalMergeError("binary transport verification failed")
    return (path,)


def _attempt_directories(
    root: Path,
) -> tuple[tuple[AttemptManifest, Path], ...]:
    records: list[tuple[AttemptManifest, Path]] = []
    for path in sorted(Path(root).rglob("shard_attempt_manifest.json")):
        records.append(
            (
                AttemptManifest.model_validate_json(
                    path.read_text(encoding="utf-8")
                ),
                path.parent,
            )
        )
    return tuple(records)


def _select_attempt(
    candidates: Sequence[tuple[AttemptManifest, Path]],
) -> tuple[AttemptManifest, Path]:
    completed = tuple(
        item
        for item in candidates
        if item[0].state is TerminalState.COMPLETED
    )
    if completed:
        hashes = {item[0].output_sha256 for item in completed}
        if len(hashes) != 1:
            shard_id = completed[0][0].shard_id
            raise PhysicalMergeError(
                f"conflicting completed outputs for shard {shard_id}"
            )
        return min(completed, key=lambda item: item[0].attempt_id)
    return max(candidates, key=lambda item: item[0].attempt_id)


def select_group_attempts(
    inputs_root: Path,
    shard_plan: ShardPlan,
    merge_group: str,
) -> tuple[tuple[AttemptManifest, Path], ...]:
    expected = {
        shard.shard_id
        for shard in shard_plan.shards
        if shard.merge_group == merge_group
    }
    if not expected:
        raise PhysicalMergeError(f"unknown merge group: {merge_group}")
    by_shard: dict[str, list[tuple[AttemptManifest, Path]]] = defaultdict(list)
    for manifest, directory in _attempt_directories(inputs_root):
        if manifest.shard_id in expected:
            by_shard[manifest.shard_id].append((manifest, directory))
    selected: list[tuple[AttemptManifest, Path]] = []
    for shard_id in sorted(expected):
        candidates = by_shard.get(shard_id, ())
        if candidates:
            selected.append(_select_attempt(candidates))
    return tuple(selected)


def select_expected_attempts(
    inputs_root: Path,
    expected_shard_ids: Sequence[str],
) -> tuple[tuple[AttemptManifest, Path], ...]:
    """Select one deterministic terminal attempt for each expected shard."""

    expected = set(expected_shard_ids)
    by_shard: dict[str, list[tuple[AttemptManifest, Path]]] = defaultdict(list)
    for manifest, directory in _attempt_directories(inputs_root):
        if manifest.shard_id in expected:
            by_shard[manifest.shard_id].append((manifest, directory))
    selected = tuple(
        _select_attempt(by_shard[shard_id])
        for shard_id in sorted(expected)
        if by_shard.get(shard_id)
    )
    unexpected = {
        manifest.shard_id
        for manifest, _ in _attempt_directories(inputs_root)
        if manifest.shard_id not in expected
    }
    if unexpected:
        raise PhysicalMergeError(
            "unexpected shard attempts in merge group: "
            + ", ".join(sorted(unexpected))
        )
    return selected


def _verified_unit_attempt_path(
    manifest: AttemptManifest,
    directory: Path,
) -> Path | None:
    if (
        manifest.unit_attempts_path is None
        or manifest.unit_attempts_sha256 is None
    ):
        return None
    raw = Path(manifest.unit_attempts_path)
    candidates = (
        raw,
        directory / raw,
        directory / raw.name,
    )
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        raise PhysicalMergeError(
            f"unit attempts missing for {manifest.shard_id}"
        )
    if sha256_file(path) != manifest.unit_attempts_sha256:
        raise PhysicalMergeError(
            f"unit attempts hash mismatch for {manifest.shard_id}"
        )
    return path


def _verified_runtime_access_path(
    manifest: AttemptManifest,
    directory: Path,
) -> Path | None:
    if manifest.state is not TerminalState.COMPLETED:
        return None
    if (
        manifest.runtime_access_ledger_path is None
        or manifest.runtime_access_ledger_sha256 is None
    ):
        raise PhysicalMergeError(
            f"runtime access ledger missing for {manifest.shard_id}"
        )
    raw = Path(manifest.runtime_access_ledger_path)
    candidates = (raw, directory / raw, directory / raw.name)
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        raise PhysicalMergeError(
            f"runtime access ledger file missing for {manifest.shard_id}"
        )
    if sha256_file(path) != manifest.runtime_access_ledger_sha256:
        raise PhysicalMergeError(
            f"runtime access ledger hash mismatch for {manifest.shard_id}"
        )
    return path


def _verified_metric_inputs_path(
    manifest: AttemptManifest,
    directory: Path,
) -> Path:
    if (
        manifest.metric_inputs_path is None
        or manifest.metric_inputs_sha256 is None
    ):
        raise PhysicalMergeError(
            f"metric inputs missing for {manifest.shard_id}"
        )
    raw = Path(manifest.metric_inputs_path)
    candidates = (raw, directory / raw, directory / raw.name)
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        raise PhysicalMergeError(
            f"metric input file missing for {manifest.shard_id}"
        )
    if sha256_file(path) != manifest.metric_inputs_sha256:
        raise PhysicalMergeError(
            f"metric input hash mismatch for {manifest.shard_id}"
        )
    return path


def _combine_metric_inputs(paths: Sequence[Path]) -> tuple[
    MetricInputRecord,
    ...,
]:
    records: list[MetricInputRecord] = []
    for path in paths:
        records.extend(read_metric_inputs(path))
    identities = [(record.unit_key, record.split) for record in records]
    if len(identities) != len(set(identities)):
        raise PhysicalMergeError("duplicate metric input identity")
    return tuple(
        sorted(records, key=lambda item: (item.unit_key, item.split))
    )


def _write_sorted_parquet(
    source_paths: Sequence[Path],
    output_path: Path,
    schema: pa.Schema,
    sort_keys: Sequence[tuple[str, str]],
) -> Path:
    if source_paths:
        tables = [
            pq.read_table(path, columns=schema.names)
            for path in source_paths
        ]
        table = pa.concat_tables(tables)
        indices = pc.sort_indices(table, sort_keys=list(sort_keys))
        table = pc.take(table, indices)
    else:
        table = pa.Table.from_pylist([], schema=schema)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    pq.write_table(
        table,
        temporary,
        compression="zstd",
        version="2.6",
    )
    temporary.replace(output_path)
    return output_path


def merge_attempt_group(
    workload: GithubWorkload,
    shard_plan: ShardPlan,
    merge_group: str,
    inputs_root: Path,
    output_dir: Path,
) -> Path:
    """Merge one bounded shard group while preserving attempt evidence."""

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    selected = select_group_attempts(
        Path(inputs_root),
        shard_plan,
        merge_group,
    )
    completed_directories = tuple(
        directory
        for manifest, directory in selected
        if manifest.state is TerminalState.COMPLETED
    )
    if completed_directories:
        scientific_output = workload.merge_group(
            completed_directories,
            root,
        )
        scientific_output = Path(scientific_output).resolve()
        if not scientific_output.is_file():
            raise PhysicalMergeError(
                "workload partial merge did not produce a file"
            )
        if not scientific_output.is_relative_to(root.resolve()):
            raise PhysicalMergeError(
                "workload partial merge escaped its output directory"
            )
    else:
        scientific_output = _atomic_json(
            root / "scientific_empty.json",
            {"schema_version": "1", "reason": "no_completed_attempts"},
        )
    unit_paths = tuple(
        path
        for manifest, directory in selected
        if (path := _verified_unit_attempt_path(manifest, directory))
        is not None
    )
    unit_attempts = _write_sorted_parquet(
        unit_paths,
        root / "unit_attempts.parquet",
        UNIT_ATTEMPT_SCHEMA,
        (("unit_key", "ascending"), ("attempt_id", "ascending")),
    )
    shard_attempts = write_shard_attempt_manifest(
        (manifest for manifest, _ in selected),
        root / "shard_attempt_manifest.parquet",
    )
    access_paths = tuple(
        path
        for manifest, directory in selected
        if (path := _verified_runtime_access_path(manifest, directory))
        is not None
    )
    access_ledger = write_runtime_access_ledger(
        root / "runtime_access_ledger.parquet",
        combine_runtime_access_ledgers(access_paths),
    )
    metric_paths = tuple(
        _verified_metric_inputs_path(manifest, directory)
        for manifest, directory in selected
        if manifest.state is TerminalState.COMPLETED
    )
    metric_inputs = write_metric_inputs(
        root / "metric_verification_inputs.parquet",
        _combine_metric_inputs(metric_paths),
    )
    payload = {
        "schema_version": "1",
        "merge_group": merge_group,
        "expected_shards": sum(
            shard.merge_group == merge_group
            for shard in shard_plan.shards
        ),
        "selected_shards": len(selected),
        "completed_shards": sum(
            manifest.state is TerminalState.COMPLETED
            for manifest, _ in selected
        ),
        "scientific_output": scientific_output.name,
        "scientific_output_sha256": sha256_file(scientific_output),
        "unit_attempts": unit_attempts.name,
        "unit_attempts_sha256": sha256_file(unit_attempts),
        "shard_attempts": shard_attempts.name,
        "shard_attempts_sha256": sha256_file(shard_attempts),
        "runtime_access_ledger": access_ledger.name,
        "runtime_access_ledger_sha256": sha256_file(access_ledger),
        "metric_inputs": metric_inputs.name,
        "metric_inputs_sha256": sha256_file(metric_inputs),
    }
    return _atomic_json(root / "partial_merge_manifest.json", payload)


def _merge_group_from_plan(
    merge_plan: MergePlan,
    group_id: str,
):
    matches = tuple(
        group for group in merge_plan.groups
        if group.group_id == group_id
    )
    if len(matches) != 1:
        raise PhysicalMergeError(f"unknown merge plan group: {group_id}")
    return matches[0]


def _manifest_transport(
    manifest: MergeNodeManifest,
    logical_name: str,
) -> PartitionedTransport:
    matches = tuple(
        item for item in manifest.files
        if item.logical_name == logical_name
    )
    if len(matches) != 1:
        raise PhysicalMergeError(
            f"merge node has invalid {logical_name} transport"
        )
    return matches[0]


def _verified_merge_nodes(
    inputs_root: Path,
    expected_artifacts: Sequence[str],
    expected_level: int,
) -> tuple[
    tuple[
        str,
        MergeNodeManifest,
        Path,
        str,
        Mapping[str, tuple[Path, ...]],
    ],
    ...,
]:
    discovered: dict[
        str,
        tuple[MergeNodeManifest, Path, str, Mapping[str, tuple[Path, ...]]],
    ] = {}
    for path in sorted(Path(inputs_root).rglob("merge_node_manifest.json")):
        manifest = MergeNodeManifest.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if manifest.output_artifact in discovered:
            raise PhysicalMergeError(
                "duplicate merge node artifact: "
                f"{manifest.output_artifact}"
            )
        transports = {
            item.logical_name: _verify_transport(path.parent, item)
            for item in manifest.files
        }
        discovered[manifest.output_artifact] = (
            manifest,
            path.parent,
            sha256_file(path),
            transports,
        )
    expected = tuple(expected_artifacts)
    missing = tuple(name for name in expected if name not in discovered)
    unexpected = tuple(
        name for name in discovered if name not in set(expected)
    )
    if missing or unexpected:
        raise PhysicalMergeError(
            "merge child artifact mismatch: "
            f"missing={list(missing)}, unexpected={list(unexpected)}"
        )
    result = []
    for name in expected:
        manifest, directory, digest, transports = discovered[name]
        if manifest.level != expected_level:
            raise PhysicalMergeError(
                f"merge child level mismatch for {name}"
            )
        result.append(
            (name, manifest, directory, digest, transports)
        )
    return tuple(result)


def _scientific_views(
    sources: Sequence[tuple[Path, PartitionedTransport]],
    staging_root: Path,
) -> tuple[Path, ...]:
    views: list[Path] = []
    for source_index, (root, transport) in enumerate(sources):
        for part_index, part in enumerate(_verify_transport(root, transport)):
            directory = (
                Path(staging_root)
                / f"source-{source_index:05d}"
                / f"part-{part_index:05d}"
            )
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / transport.source_file_name
            try:
                os.link(part, target)
            except OSError:
                shutil.copy2(part, target)
            views.append(directory)
    return tuple(views)


def _scientific_key_columns(path: Path) -> tuple[str, ...]:
    if path.suffix.lower() != ".parquet":
        return ()
    names = tuple(pq.read_schema(path).names)
    for keys in (
        ("unit_key",),
        ("strategy_id",),
        ("candidate_id",),
        ("event_id",),
    ):
        if all(name in names for name in keys):
            return keys
    raise PhysicalMergeError(
        "oversized scientific Parquet requires a supported logical key"
    )


def _write_transport(
    source_path: Path,
    output_dir: Path,
    *,
    logical_name: str,
    key_columns: Sequence[str],
    target_bytes: int,
) -> PartitionedTransport:
    if Path(source_path).suffix.lower() == ".parquet":
        return write_partitioned_parquet_transport(
            source_path,
            output_dir,
            logical_name=logical_name,
            key_columns=key_columns,
            target_bytes=target_bytes,
        )
    return _write_binary_transport(
        source_path,
        output_dir,
        logical_name=logical_name,
        target_bytes=target_bytes,
    )


def merge_plan_group(
    workload: GithubWorkload,
    shard_plan: ShardPlan,
    merge_plan: MergePlan,
    group_id: str,
    inputs_root: Path,
    output_dir: Path,
) -> Path:
    """Execute one immutable merge-tree node and verify all direct children."""

    group = _merge_group_from_plan(merge_plan, group_id)
    root = Path(output_dir)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    staging = root / ".staging"
    staging.mkdir()
    child_hashes: dict[str, str] = {}
    source_shard_ids: tuple[str, ...]
    expected_inputs = len(group.input_artifacts)
    if group.level == 0:
        source_shard_ids = tuple(
            item.removeprefix("shard:")
            for item in group.input_artifacts
        )
        if any(
            not item.startswith("shard:")
            for item in group.input_artifacts
        ):
            raise PhysicalMergeError(
                "level-zero merge inputs must be logical shards"
            )
        selected = select_expected_attempts(
            Path(inputs_root),
            source_shard_ids,
        )
        scientific_inputs = tuple(
            directory
            for manifest, directory in selected
            if manifest.state is TerminalState.COMPLETED
        )
        unit_paths = tuple(
            path
            for manifest, directory in selected
            if (path := _verified_unit_attempt_path(manifest, directory))
            is not None
        )
        shard_source_paths: tuple[Path, ...] = ()
        access_paths = tuple(
            path
            for manifest, directory in selected
            if (
                path := _verified_runtime_access_path(
                    manifest,
                    directory,
                )
            )
            is not None
        )
        metric_paths = tuple(
            _verified_metric_inputs_path(manifest, directory)
            for manifest, directory in selected
            if manifest.state is TerminalState.COMPLETED
        )
        selected_inputs = len(selected)
        completed_shards = sum(
            manifest.state is TerminalState.COMPLETED
            for manifest, _ in selected
        )
        selected_manifests = tuple(
            manifest for manifest, _ in selected
        )
    else:
        children = _verified_merge_nodes(
            Path(inputs_root),
            group.input_artifacts,
            group.level - 1,
        )
        if any(
            manifest.merge_plan_sha256 != merge_plan.plan_sha256
            for _, manifest, _, _, _ in children
        ):
            raise PhysicalMergeError(
                "merge child was built from another immutable plan"
            )
        child_hashes = {
            name: digest
            for name, _, _, digest, _ in children
        }
        source_shard_ids = tuple(
            shard_id
            for _, manifest, _, _, _ in children
            for shard_id in manifest.source_shard_ids
        )
        if len(source_shard_ids) != len(set(source_shard_ids)):
            raise PhysicalMergeError(
                "merge tree contains duplicate source shards"
            )
        scientific_inputs = _scientific_views(
            tuple(
                (
                    directory,
                    _manifest_transport(manifest, "scientific_output"),
                )
                for _, manifest, directory, _, _ in children
            ),
            staging / "scientific-inputs",
        )
        unit_paths = tuple(
            path
            for _, _, _, _, transports in children
            for path in transports["unit_attempts"]
        )
        shard_source_paths = tuple(
            path
            for _, _, _, _, transports in children
            for path in transports["shard_attempts"]
        )
        access_paths = tuple(
            path
            for _, _, _, _, transports in children
            for path in transports["runtime_access_ledger"]
        )
        metric_paths = tuple(
            path
            for _, _, _, _, transports in children
            for path in transports["metric_inputs"]
        )
        selected_inputs = len(children)
        completed_shards = sum(
            manifest.completed_shards
            for _, manifest, _, _, _ in children
        )
        selected_manifests = ()
    scientific_root = staging / "scientific"
    scientific_root.mkdir(parents=True, exist_ok=True)
    scientific_output = Path(
        workload.merge_group(scientific_inputs, scientific_root)
    ).resolve()
    if (
        not scientific_output.is_file()
        or not scientific_output.is_relative_to(scientific_root.resolve())
    ):
        raise PhysicalMergeError("scientific merge output is invalid")
    unit_attempts = _write_sorted_parquet(
        unit_paths,
        staging / "unit_attempts.parquet",
        UNIT_ATTEMPT_SCHEMA,
        (("unit_key", "ascending"), ("attempt_id", "ascending")),
    )
    if group.level == 0:
        shard_attempts = write_shard_attempt_manifest(
            selected_manifests,
            staging / "shard_attempts.parquet",
        )
    else:
        shard_attempts = _write_sorted_parquet(
            shard_source_paths,
            staging / "shard_attempts.parquet",
            SHARD_ATTEMPT_SCHEMA,
            (("shard_id", "ascending"), ("attempt_id", "ascending")),
        )
    access_ledger = write_runtime_access_ledger(
        staging / "runtime_access_ledger.parquet",
        combine_runtime_access_ledgers(access_paths),
    )
    metric_inputs = write_metric_inputs(
        staging / "metric_inputs.parquet",
        _combine_metric_inputs(metric_paths),
    )
    target_bytes = merge_plan.partition_target_bytes
    transports = (
        _write_transport(
            scientific_output,
            root,
            logical_name="scientific_output",
            key_columns=_scientific_key_columns(scientific_output),
            target_bytes=target_bytes,
        ),
        _write_transport(
            unit_attempts,
            root,
            logical_name="unit_attempts",
            key_columns=("unit_key", "attempt_id"),
            target_bytes=target_bytes,
        ),
        _write_transport(
            shard_attempts,
            root,
            logical_name="shard_attempts",
            key_columns=("shard_id", "attempt_id"),
            target_bytes=target_bytes,
        ),
        _write_transport(
            access_ledger,
            root,
            logical_name="runtime_access_ledger",
            key_columns=(
                "shard_id",
                "attempt_id",
                "source",
                "partition",
                "purpose",
            ),
            target_bytes=target_bytes,
        ),
        _write_transport(
            metric_inputs,
            root,
            logical_name="metric_inputs",
            key_columns=("unit_key", "split"),
            target_bytes=target_bytes,
        ),
    )
    shutil.rmtree(staging)
    manifest = MergeNodeManifest(
        group_id=group.group_id,
        level=group.level,
        output_artifact=group.output_artifact,
        merge_plan_sha256=merge_plan.plan_sha256,
        input_artifacts=group.input_artifacts,
        child_manifest_sha256s=child_hashes,
        source_shard_ids=tuple(sorted(source_shard_ids)),
        expected_inputs=expected_inputs,
        selected_inputs=selected_inputs,
        completed_shards=completed_shards,
        files=transports,
    )
    return _atomic_json(root / "merge_node_manifest.json", manifest)


def _load_portable_work_units(path: Path) -> WorkUnitManifest:
    manifest = WorkUnitManifest.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    parquet_path = path.parent / Path(manifest.path).name
    if not parquet_path.is_file():
        raise PhysicalMergeError("work-unit Parquet is missing")
    return manifest.model_copy(update={"path": str(parquet_path.resolve())})


def _copy_contract_files(
    sources: Sequence[Path],
    output_dir: Path,
) -> None:
    names = (
        "resolved_run_spec.json",
        "performance_contract.json",
        "preflight_report.json",
        "environment_manifest.json",
        "metric_contract.json",
        "capacity_profile.json",
        "performance_pilot.json",
        "performance_plan.json",
        "execution_plan.json",
        "balanced_shard_plan.json",
        "work_unit_manifest.json",
        "work_units.parquet",
        "balanced_unit_assignments.parquet",
        "merge_plan.json",
        "recovery_plan.json",
        "checkpoint_audit.parquet",
        "budget_audit.json",
        "deadline_audit.json",
    )
    for name in names:
        matches = [
            root / name for root in sources if (root / name).is_file()
        ]
        if matches:
            shutil.copy2(matches[0], output_dir / name)


def final_merge(
    workload: GithubWorkload,
    spec: RunSpec,
    partials_root: Path,
    plan_root: Path,
    contract_root: Path,
    output_dir: Path,
    preflight_root: Path | None = None,
    recovery_root: Path | None = None,
) -> Path:
    """Promote one verified merge-tree root and seal the final artifact."""

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    merge_plan = MergePlan.model_validate_json(
        (Path(plan_root) / "merge_plan.json").read_text(encoding="utf-8")
    )
    node_paths = tuple(
        Path(partials_root).rglob("merge_node_manifest.json")
    )
    root_manifest: MergeNodeManifest | None
    if node_paths:
        root_nodes = _verified_merge_nodes(
            Path(partials_root),
            (merge_plan.root_artifact,),
            merge_plan.root_level,
        )
        _, root_manifest, root_directory, _, root_transports = (
            root_nodes[0]
        )
        if root_manifest.merge_plan_sha256 != merge_plan.plan_sha256:
            raise PhysicalMergeError("merge root was built from another plan")
        scientific_inputs = _scientific_views(
            (
                (
                    root_directory,
                    _manifest_transport(
                        root_manifest,
                        "scientific_output",
                    ),
                ),
            ),
            root / ".root-scientific-inputs",
        )
        unit_attempt_paths = root_transports["unit_attempts"]
        shard_paths = root_transports["shard_attempts"]
        partial_access_paths = root_transports[
            "runtime_access_ledger"
        ]
        partial_metric_paths = root_transports["metric_inputs"]
        legacy_partial_dirs: tuple[Path, ...] = ()
    else:
        root_manifest = None
        legacy_partial_dirs = tuple(
            path.parent
            for path in sorted(
                Path(partials_root).rglob("partial_merge_manifest.json")
            )
        )
        if not legacy_partial_dirs:
            raise PhysicalMergeError("no verified merge inputs found")
        scientific_inputs = legacy_partial_dirs
        unit_attempt_paths = tuple(
            path / "unit_attempts.parquet"
            for path in legacy_partial_dirs
            if (path / "unit_attempts.parquet").is_file()
        )
        shard_paths = tuple(
            path / "shard_attempt_manifest.parquet"
            for path in legacy_partial_dirs
            if (path / "shard_attempt_manifest.parquet").is_file()
        )
        partial_access_paths = tuple(
            path / "runtime_access_ledger.parquet"
            for path in legacy_partial_dirs
            if (path / "runtime_access_ledger.parquet").is_file()
        )
        partial_metric_paths = tuple(
            path / "metric_verification_inputs.parquet"
            for path in legacy_partial_dirs
            if (
                path / "metric_verification_inputs.parquet"
            ).is_file()
        )
        if len(partial_access_paths) != len(legacy_partial_dirs):
            raise PhysicalMergeError(
                "runtime access evidence is missing from a partial merge"
            )
        if len(partial_metric_paths) != len(legacy_partial_dirs):
            raise PhysicalMergeError(
                "metric inputs are missing from a partial merge"
            )
    scientific_output = Path(
        workload.merge_group(scientific_inputs, root)
    ).resolve()
    if not legacy_partial_dirs:
        shutil.rmtree(root / ".root-scientific-inputs")
    if (
        not scientific_output.is_file()
        or not scientific_output.is_relative_to(root.resolve())
    ):
        raise PhysicalMergeError("final scientific merge output is invalid")
    scientific_output_name = scientific_output.name
    scientific_output_sha256 = sha256_file(scientific_output)
    scientific_content_identity = (
        scientific_content_identity_from_output(scientific_output)
    )
    scientific_output_partitioned = False
    if scientific_output.stat().st_size > merge_plan.partition_target_bytes:
        scientific_transport = _write_transport(
            scientific_output,
            root,
            logical_name="scientific_output",
            key_columns=_scientific_key_columns(scientific_output),
            target_bytes=merge_plan.partition_target_bytes,
        )
        transport_path = _atomic_json(
            root / "scientific_output_transport.json",
            scientific_transport,
        )
        scientific_output.unlink()
        scientific_output_name = transport_path.name
        scientific_output_sha256 = scientific_transport.logical_sha256
        scientific_output_partitioned = True
    expected_manifest = _load_portable_work_units(
        Path(plan_root) / "work_unit_manifest.json"
    )
    _write_sorted_parquet(
        unit_attempt_paths,
        root / "unit_attempt_manifest.parquet",
        UNIT_ATTEMPT_SCHEMA,
        (("unit_key", "ascending"), ("attempt_id", "ascending")),
    )
    reconciliation = reconcile_attempt_files(
        expected_manifest,
        unit_attempt_paths,
        root / "unit_reconciliation.parquet",
    )
    _write_sorted_parquet(
        shard_paths,
        root / "shard_attempt_manifest.parquet",
        SHARD_ATTEMPT_SCHEMA,
        (("shard_id", "ascending"), ("attempt_id", "ascending")),
    )
    evidence_roots = [Path(contract_root), Path(plan_root)]
    if preflight_root is not None:
        evidence_roots.append(Path(preflight_root))
    if recovery_root is not None:
        evidence_roots.append(Path(recovery_root))
    _copy_contract_files(tuple(evidence_roots), root)
    access_ledger = combine_runtime_access_ledgers(partial_access_paths)
    metric_inputs_path = write_metric_inputs(
        root / "metric_verification_inputs.parquet",
        _combine_metric_inputs(partial_metric_paths),
    )
    metric_verification = verify_metric_inputs(
        read_metric_inputs(metric_inputs_path)
    )
    write_independent_metric_verification(
        metric_verification,
        metric_inputs_path,
        root / "independent_metric_verification.json",
    )
    environment_path = root / "environment_manifest.json"
    environment_manifest: Mapping[str, Any] = {}
    if environment_path.is_file():
        payload = json.loads(environment_path.read_text(encoding="utf-8"))
        if isinstance(payload, Mapping):
            environment_manifest = payload
    contract_path = root / "performance_contract.json"
    performance_contract: Mapping[str, Any] = {}
    if contract_path.is_file():
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
        if isinstance(payload, Mapping):
            performance_contract = payload
    audits = build_required_audits(
        spec,
        access_ledger,
        environment={
            "github_actions": os.environ.get("GITHUB_ACTIONS") == "true",
            "runner_label": str(spec.performance["runner_label"]),
            "larger_runner_used": bool(
                spec.performance["larger_runners_allowed"]
            ),
            "code_sha": performance_contract.get("code_sha", ""),
            "workflow_sha256": performance_contract.get(
                "workflow_sha256", ""
            ),
            "environment_sha256": environment_manifest.get(
                "environment_sha256", ""
            ),
        },
    )
    write_required_audits(root, audits)
    return _atomic_json(
        root / "final_merge_summary.json",
        {
            "schema_version": "1",
            "partial": reconciliation.partial,
            "expected_units": reconciliation.expected_units,
            "completed": reconciliation.completed,
            "right_censored": reconciliation.right_censored,
            "unsupported": reconciliation.unsupported,
            "failed_technical": reconciliation.failed_technical,
            "scientific_output": scientific_output_name,
            "scientific_output_sha256": scientific_output_sha256,
            "scientific_content_sha256": (
                scientific_content_identity[
                    "scientific_content_sha256"
                ]
            ),
            "scientific_content_rows": (
                scientific_content_identity["unit_count"]
            ),
            "scientific_output_partitioned": (
                scientific_output_partitioned
            ),
            "locked_opened": audits.policy.locked_opened,
            "locked_rows_accessed": audits.data.locked_rows_accessed,
            "validation_used_for_selection": (
                audits.policy.validation_used_for_selection
            ),
            "independent_metrics_equal": metric_verification.passed,
            "metric_records_verified": (
                metric_verification.records_verified
            ),
            "metric_fields_compared": metric_verification.fields_compared,
            "metric_mismatches": len(metric_verification.mismatches),
            "merge_plan_sha256": merge_plan.plan_sha256,
            "merge_root_artifact": merge_plan.root_artifact,
            "merge_root_level": merge_plan.root_level,
            "merge_levels_executed": merge_plan.root_level + 1,
            "merge_source_shards": (
                len(root_manifest.source_shard_ids)
                if root_manifest is not None
                else len(shard_paths)
            ),
            "multi_level_merge_verified": (
                root_manifest is not None
                and root_manifest.merge_plan_sha256
                == merge_plan.plan_sha256
            ),
        },
    )
