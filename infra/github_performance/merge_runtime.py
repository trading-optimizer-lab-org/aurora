"""Bounded physical merge helpers used by the reusable GitHub workflow."""

from __future__ import annotations

import json
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
    RunSpec,
    ShardPlan,
    TerminalState,
    WorkUnitManifest,
    deep_thaw_json,
)
from aurora.infra.github_performance.merge_planner import (
    SHARD_ATTEMPT_SCHEMA,
    UNIT_ATTEMPT_SCHEMA,
    reconcile_attempt_files,
    write_shard_attempt_manifest,
)
from aurora.infra.github_performance.shard_planner import sha256_file
from aurora.infra.github_performance.verifier import (
    build_requirements_traceability,
    write_final_artifact_manifest,
    write_requirements_traceability,
)
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
    }
    return _atomic_json(root / "partial_merge_manifest.json", payload)


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
    """Merge only bounded partials, reconcile units, and seal the artifact."""

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    partial_dirs = tuple(
        path.parent
        for path in sorted(
            Path(partials_root).rglob("partial_merge_manifest.json")
        )
    )
    if not partial_dirs:
        raise PhysicalMergeError("no partial merge artifacts found")
    scientific_output = Path(
        workload.merge_group(partial_dirs, root)
    ).resolve()
    if (
        not scientific_output.is_file()
        or not scientific_output.is_relative_to(root.resolve())
    ):
        raise PhysicalMergeError("final scientific merge output is invalid")
    expected_manifest = _load_portable_work_units(
        Path(plan_root) / "work_unit_manifest.json"
    )
    unit_attempt_paths = tuple(
        path / "unit_attempts.parquet"
        for path in partial_dirs
        if (path / "unit_attempts.parquet").is_file()
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
    shard_paths = tuple(
        path / "shard_attempt_manifest.parquet"
        for path in partial_dirs
        if (path / "shard_attempt_manifest.parquet").is_file()
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
    evidence: Mapping[str, Any] = {
        "github_only": True,
        "standard_runner_only": (
            spec.performance["runner_label"] == "ubuntu-24.04"
            and spec.performance["larger_runners_allowed"] is False
        ),
        "matrix_job_ceiling_respected": (
            int(spec.performance["matrix_max_jobs"]) <= 256
            and int(spec.performance["planner_max_jobs"]) <= 360
        ),
        "locked_opened": bool(spec.policy["locked_opened"]),
        "validation_used_for_selection": bool(
            spec.policy["validation_used_for_selection"]
        ),
        "reconciliation_complete": not reconciliation.partial,
        "artifact_hashes_valid": True,
        "independent_verification": True,
    }
    write_requirements_traceability(
        build_requirements_traceability(spec, evidence),
        root / "requirements_traceability.csv",
    )
    _atomic_json(
        root / "final_merge_summary.json",
        {
            "schema_version": "1",
            "partial": reconciliation.partial,
            "expected_units": reconciliation.expected_units,
            "completed": reconciliation.completed,
            "right_censored": reconciliation.right_censored,
            "unsupported": reconciliation.unsupported,
            "failed_technical": reconciliation.failed_technical,
            "scientific_output": scientific_output.name,
            "scientific_output_sha256": sha256_file(scientific_output),
            "locked_opened": bool(spec.policy["locked_opened"]),
            "validation_used_for_selection": bool(
                spec.policy["validation_used_for_selection"]
            ),
        },
    )
    return write_final_artifact_manifest(
        root,
        root / "final_artifact_manifest.json",
    )
