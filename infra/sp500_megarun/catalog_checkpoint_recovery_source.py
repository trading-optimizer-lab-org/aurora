"""Fail-closed local validation for authenticated historical checkpoints.

The caller authenticates the source archive and its external provenance before
calling this module.  This module only reads the sealed plan and the already
published checkpoint bytes.  It never evaluates science, starts workers,
changes the source plan, or writes recovery results.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from pydantic import field_validator

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    canonical_sha256,
    deep_freeze_json,
)
from aurora.infra.github_performance.recovery import (
    CheckpointSlotEvidence,
    validate_checkpoint_slot_chain,
)
from aurora.infra.sp500_megarun.catalog_recovery_blocks import (
    verify_persisted_recovery_block,
)
from aurora.infra.sp500_megarun.catalog_resume import (
    CatalogResumeIndexV1,
    load_resume_index,
)
from aurora.infra.sp500_megarun.catalog_sealed_plan import (
    verify_sealed_global_reuse_execution_plan,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_WORKER_COUNT = 60
_RECOVERY_WORKER_COUNT = 30
_CHECKPOINT_SLOT_COUNT = 4
_SUPPORTED_CHECKPOINT_LAYOUTS = {4: _RECOVERY_WORKER_COUNT, 2: _SOURCE_WORKER_COUNT}
_REQUIRED_BINDINGS = frozenset(
    {
        "request_sha256",
        "decision_sha256",
        "protected_commit_sha",
        "authority_id",
        "campaign_id",
        "execution_plan_sha256",
    }
)
_RECIPE_MATRIX_NAMES = ("recipe_matrix_a", "recipe_matrix_b", "recipe_matrix_c")
_DESCRIPTOR_KEYS = frozenset(
    {
        "worker_id",
        "attempt_id",
        "assignment_artifact",
        "assignment_member",
        "assignment_sha256",
        "data_partition_artifacts",
        "data_partition_manifest_sha256",
        "component_bundle_artifacts",
        "component_bundle_manifest_sha256",
        "prior_checkpoint_chain_artifact",
        "checkpoint_slot_artifacts",
        "checkpoint_slot_manifest_sha256",
        "checkpoint_slot_count",
        "expected_strategy_count",
        "expected_strategy_manifest_sha256",
    }
)
_ASSIGNMENT_KEYS = frozenset(
    {"schema_version", "worker_id", "strategy_ids", "expected_strategy_manifest_sha256"}
)
_MATRIX_ROW_KEYS = frozenset(
    {"worker_id", "descriptor_bundle_artifact", "descriptor_member", "descriptor_sha256"}
)
_CHECKPOINT_REQUIRED_FILES = frozenset(
    {
        "receipt.json",
        "shard_attempt_manifest.json",
        "checkpoint_chain_manifest.json",
        "results.parquet",
    }
)
_CHECKPOINT_ALLOWED_FILES = _CHECKPOINT_REQUIRED_FILES | frozenset(
    {"unit_attempts.parquet", "resource_summary.json", "resource_telemetry.parquet"}
)
_SELECTED_RESULTS_FILE = "selected_results.jsonl"
_SELECTED_RESULTS_FIELDS = frozenset(
    {"configuration", "lane_id", "result", "source_strategy_key"}
)
_SELECTED_RESULTS_ROW_COUNT = 13
_MISSING = object()


class ValidatedCheckpointRecoverySource(FrozenModel):
    """Immutable evidence for the exact historical checkpoint source."""

    resume_index: CatalogResumeIndexV1
    plan_receipt: Mapping[str, object]
    science_identity_sha256: str
    catalog_manifest_sha256: str
    work_manifest_sha256: str
    worker_ids: tuple[int, ...]
    strategy_ids: tuple[str, ...]
    checkpoint_artifact_names: tuple[str, ...]
    checkpoint_receipt_sha256s: tuple[str, ...]
    checkpoint_chain_manifest_sha256s: tuple[str, ...]
    recovery_block_ids: tuple[str, ...]
    source_assignment_manifest_sha256s: tuple[str, ...]

    @field_validator("plan_receipt", mode="after")
    @classmethod
    def _freeze_plan_receipt(
        cls, value: Mapping[str, object]
    ) -> Mapping[str, object]:
        return cast(Mapping[str, object], deep_freeze_json(value))

    @property
    def checkpoint_count(self) -> int:
        return len(self.checkpoint_artifact_names)

    @property
    def worker_count(self) -> int:
        return len(self.worker_ids)

    @property
    def index_sha256(self) -> str:
        return self.resume_index.index_sha256

    @property
    def resume_index_sha256(self) -> str:
        return self.resume_index.index_sha256

    @property
    def plan_receipt_sha256(self) -> str:
        return str(self.plan_receipt["receipt_sha256"])

    @property
    def source_plan_receipt_sha256(self) -> str:
        return self.plan_receipt_sha256

    @property
    def checkpoint_artifacts(self) -> tuple[str, ...]:
        return self.checkpoint_artifact_names

    @property
    def checkpoint_chain_sha256s(self) -> tuple[str, ...]:
        return self.checkpoint_chain_manifest_sha256s

    @property
    def assignment_manifest_sha256s(self) -> tuple[str, ...]:
        return self.source_assignment_manifest_sha256s


def _read_json_object(path: Path, *, error_code: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(error_code)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(error_code) from exc
    if not isinstance(payload, dict):
        raise ValueError(error_code)
    return payload


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("duplicate JSON key")
        payload[key] = value
    return payload


def _reject_nonfinite_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _validate_finite_json(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    if isinstance(value, Mapping):
        for item in value.values():
            _validate_finite_json(item)
    elif isinstance(value, list):
        for item in value:
            _validate_finite_json(item)


def _validate_selected_results_sidecar(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID")
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID")
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID") from exc

    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        if not line.strip():
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID")
        try:
            row = json.loads(
                line,
                object_pairs_hook=_reject_duplicate_json_keys,
                parse_constant=_reject_nonfinite_json_constant,
            )
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID") from exc
        if not isinstance(row, dict):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID")
        try:
            _validate_finite_json(row)
        except ValueError as exc:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID") from exc
        rows.append(row)

    if len(rows) != _SELECTED_RESULTS_ROW_COUNT:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID")
    source_keys: set[str] = set()
    for row in rows:
        if set(row) != _SELECTED_RESULTS_FIELDS:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID")
        configuration = row["configuration"]
        lane_id = row["lane_id"]
        result = row["result"]
        source_strategy_key = row["source_strategy_key"]
        if (
            not isinstance(configuration, dict)
            or not isinstance(lane_id, str)
            or not lane_id.strip()
            or any(ord(character) < 0x20 for character in lane_id)
            or not isinstance(result, dict)
            or not isinstance(source_strategy_key, str)
            or not source_strategy_key.strip()
            or any(ord(character) < 0x20 for character in source_strategy_key)
            or source_strategy_key in source_keys
        ):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID")
        info = result.get("info")
        if (
            not isinstance(info, dict)
            or info.get("validation_opened") is not False
            or info.get("locked_opened") is not False
        ):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID")
        source_keys.add(source_strategy_key)


def _require_sha256(value: object, *, error_code: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(error_code)
    return value


def _validate_bindings(expected_bindings: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(expected_bindings, Mapping) or not expected_bindings:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_BINDINGS_INVALID")
    if any(
        not isinstance(key, str)
        or not key
        or not isinstance(value, str)
        or not value
        for key, value in expected_bindings.items()
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_BINDINGS_INVALID")
    missing = _REQUIRED_BINDINGS.difference(expected_bindings)
    if missing:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_BINDINGS_INCOMPLETE")
    return {str(key): str(value) for key, value in expected_bindings.items()}


def _validate_ids(
    values: Sequence[str], *, error_code: str
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(error_code)
    try:
        result = tuple(values)
    except TypeError as exc:
        raise ValueError(error_code) from exc
    if (
        not result
        or any(not isinstance(item, str) or not item for item in result)
        or len(result) != len(set(result))
    ):
        raise ValueError(error_code)
    return result


def _validate_checkpoint_slot_count(value: int) -> int:
    if type(value) is not int or value not in _SUPPORTED_CHECKPOINT_LAYOUTS:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SLOT_PLAN_INVALID")
    return value


def _validate_worker_ids(
    values: Sequence[int], *, checkpoint_slot_count: int = _CHECKPOINT_SLOT_COUNT
) -> tuple[int, ...]:
    slot_count = _validate_checkpoint_slot_count(checkpoint_slot_count)
    if isinstance(values, (str, bytes)):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_WORKERS_INVALID")
    try:
        worker_ids = tuple(values)
    except TypeError as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_WORKERS_INVALID") from exc
    if (
        len(worker_ids) != _SUPPORTED_CHECKPOINT_LAYOUTS[slot_count]
        or any(type(worker_id) is not int or not 0 <= worker_id < _SOURCE_WORKER_COUNT for worker_id in worker_ids)
        or len(set(worker_ids)) != len(worker_ids)
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_WORKERS_INVALID")
    return tuple(sorted(worker_ids))


def _safe_single_component(value: object, *, error_code: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "/" in value
        or "\\" in value
        or value in {".", ".."}
    ):
        raise ValueError(error_code)
    component = Path(value)
    if (
        component.is_absolute()
        or component.drive
        or component.root
        or len(component.parts) != 1
    ):
        raise ValueError(error_code)
    return value


def _safe_relative(root: Path, value: object, *, error_code: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(error_code)
    relative = Path(value)
    if (
        relative.is_absolute()
        or relative.drive
        or relative.root
        or ".." in relative.parts
        or relative.name in {".", ".."}
    ):
        raise ValueError(error_code)
    target = root.joinpath(relative)
    paths_to_check = (root, target)
    try:
        if any(
            candidate.is_symlink()
            for path in paths_to_check
            for candidate in (path, *path.parents)
        ):
            raise ValueError(error_code)
    except OSError as exc:
        raise ValueError(error_code) from exc
    return target


def _validate_closed_boundary(payload: Mapping[str, object], *, error_code: str) -> None:
    if payload.get("validation_opened") is not False or payload.get("locked_opened") is not False:
        raise ValueError(error_code)


def _validate_contract_science(
    sealed_plan: Path,
    *,
    expected_science: str,
    expected_catalog: str,
) -> None:
    contract = _read_json_object(
        sealed_plan / "resolved_contract.json",
        error_code="CATALOG_CHECKPOINT_RECOVERY_CONTRACT_INVALID",
    )
    science = contract.get("science")
    if not isinstance(science, Mapping):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SCIENCE_INVALID")
    _validate_closed_boundary(science, error_code="CATALOG_CHECKPOINT_RECOVERY_BOUNDARY_INVALID")
    if (
        canonical_sha256(science) != expected_science
        or science.get("catalog_manifest_sha256") != expected_catalog
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SCIENCE_BINDING_INVALID")


def _validate_run_plan_and_manifest(
    sealed_plan: Path,
    *,
    expected_science: str,
) -> tuple[dict[str, object], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    run_plan = _read_json_object(
        sealed_plan / "run_plan.json",
        error_code="CATALOG_CHECKPOINT_RECOVERY_RUN_PLAN_INVALID",
    )
    if (
        run_plan.get("schema_version") != "1"
        or run_plan.get("workers") != _SOURCE_WORKER_COUNT
        or run_plan.get("active_workers") != _SOURCE_WORKER_COUNT
        or run_plan.get("component_workers") != _SOURCE_WORKER_COUNT
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_WORKERS_INVALID")
    _validate_closed_boundary(run_plan, error_code="CATALOG_CHECKPOINT_RECOVERY_BOUNDARY_INVALID")
    matrices = run_plan.get("matrices")
    if not isinstance(matrices, list) or not matrices:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_WORKERS_INVALID")
    matrix_workers: list[int] = []
    for matrix in matrices:
        if not isinstance(matrix, list):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_WORKERS_INVALID")
        for worker_id in matrix:
            if type(worker_id) is not int:
                raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_WORKERS_INVALID")
            matrix_workers.append(worker_id)
    if tuple(sorted(matrix_workers)) != tuple(range(_SOURCE_WORKER_COUNT)):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_WORKERS_INVALID")

    manifest = _read_json_object(
        sealed_plan / "resume_work_manifest.json",
        error_code="CATALOG_CHECKPOINT_RECOVERY_WORK_MANIFEST_INVALID",
    )
    _validate_closed_boundary(
        manifest, error_code="CATALOG_CHECKPOINT_RECOVERY_BOUNDARY_INVALID"
    )
    if manifest.get("schema_version") != "1" or manifest.get("active_workers") != _SOURCE_WORKER_COUNT:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_WORK_MANIFEST_INVALID")
    manifest_hash = _require_sha256(
        manifest.get("manifest_sha256"),
        error_code="CATALOG_CHECKPOINT_RECOVERY_WORK_MANIFEST_HASH_INVALID",
    )
    manifest_identity = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if canonical_sha256(manifest_identity) != manifest_hash:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_WORK_MANIFEST_HASH_INVALID")

    all_ids = _validate_ids(
        cast(Sequence[str], manifest.get("all_strategy_ids")),
        error_code="CATALOG_CHECKPOINT_RECOVERY_SOURCE_IDS_INVALID",
    )
    pending_ids = _validate_ids(
        cast(Sequence[str], manifest.get("pending_strategy_ids")),
        error_code="CATALOG_CHECKPOINT_RECOVERY_SOURCE_IDS_INVALID",
    )
    cached_raw = manifest.get("cached_strategy_ids")
    if isinstance(cached_raw, (str, bytes)) or not isinstance(cached_raw, Sequence):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_IDS_INVALID")
    cached_ids = tuple(cached_raw)
    if any(not isinstance(item, str) or not item for item in cached_ids) or len(set(cached_ids)) != len(cached_ids):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_IDS_INVALID")
    if (
        set(cached_ids).intersection(pending_ids)
        or set(cached_ids).union(pending_ids) != set(all_ids)
        or run_plan.get("work_manifest_sha256") != manifest_hash
        or run_plan.get("pending_recipe_count") != len(pending_ids)
        or run_plan.get("cached_recipe_count") != len(cached_ids)
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_WORK_MANIFEST_BINDING_INVALID")
    if expected_science == "":  # pragma: no cover - validated by the caller
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SCIENCE_BINDING_INVALID")
    return run_plan, all_ids, pending_ids, cached_ids


def _read_recipe_source_assignments(
    sealed_plan: Path,
    *,
    all_strategy_ids: tuple[str, ...],
    pending_strategy_ids: tuple[str, ...],
    checkpoint_slot_count: int = _CHECKPOINT_SLOT_COUNT,
) -> dict[int, dict[str, object]]:
    slot_count = _validate_checkpoint_slot_count(checkpoint_slot_count)
    rows: list[dict[str, object]] = []
    for matrix_name in _RECIPE_MATRIX_NAMES:
        matrix = _read_json_object(
            sealed_plan / f"{matrix_name}.json",
            error_code="CATALOG_CHECKPOINT_RECOVERY_RECIPE_MATRIX_INVALID",
        )
        if set(matrix) != {"include"} or not isinstance(matrix.get("include"), list):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RECIPE_MATRIX_INVALID")
        for row in cast(list[object], matrix["include"]):
            if not isinstance(row, dict) or set(row) != _MATRIX_ROW_KEYS:
                raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RECIPE_MATRIX_INVALID")
            rows.append(cast(dict[str, object], row))
    if len(rows) != _SOURCE_WORKER_COUNT:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_WORKERS_INVALID")

    by_worker: dict[int, dict[str, object]] = {}
    routes: set[tuple[str, str]] = set()
    all_source_ids: list[str] = []
    for row in rows:
        worker_id = row.get("worker_id")
        if type(worker_id) is not int or not 0 <= worker_id < _SOURCE_WORKER_COUNT or worker_id in by_worker:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RECIPE_MATRIX_INVALID")
        descriptor_artifact = _safe_single_component(
            row.get("descriptor_bundle_artifact"),
            error_code="CATALOG_CHECKPOINT_RECOVERY_DESCRIPTOR_INVALID",
        )
        if not isinstance(row["descriptor_member"], str):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RECIPE_MATRIX_INVALID")
        descriptor_route = (descriptor_artifact, row["descriptor_member"])
        if descriptor_route in routes:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RECIPE_MATRIX_INVALID")
        routes.add(descriptor_route)
        descriptor_path = _safe_relative(
            sealed_plan / "payload_artifacts" / descriptor_artifact,
            descriptor_route[1],
            error_code="CATALOG_CHECKPOINT_RECOVERY_DESCRIPTOR_INVALID",
        )
        descriptor_sha = _require_sha256(
            row.get("descriptor_sha256"),
            error_code="CATALOG_CHECKPOINT_RECOVERY_DESCRIPTOR_HASH_INVALID",
        )
        try:
            if hashlib.sha256(descriptor_path.read_bytes()).hexdigest() != descriptor_sha:
                raise ValueError("CATALOG_CHECKPOINT_RECOVERY_DESCRIPTOR_HASH_INVALID")
        except OSError as exc:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_DESCRIPTOR_INVALID") from exc
        descriptor = _read_json_object(
            descriptor_path,
            error_code="CATALOG_CHECKPOINT_RECOVERY_DESCRIPTOR_INVALID",
        )
        if set(descriptor) != _DESCRIPTOR_KEYS or descriptor.get("worker_id") != worker_id:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_DESCRIPTOR_INVALID")
        if descriptor.get("checkpoint_slot_count") != slot_count:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SLOT_PLAN_INVALID")
        raw_artifacts = descriptor.get("checkpoint_slot_artifacts")
        if isinstance(raw_artifacts, (str, bytes)) or not isinstance(raw_artifacts, Sequence):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SLOT_PLAN_INVALID")
        checkpoint_artifacts = tuple(raw_artifacts)
        if (
            len(checkpoint_artifacts) < slot_count
            or any(
                not isinstance(artifact, str)
                or not artifact
                or "/" in artifact
                or "\\" in artifact
                for artifact in checkpoint_artifacts
            )
            or len(set(checkpoint_artifacts)) != len(checkpoint_artifacts)
        ):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SLOT_PLAN_INVALID")
        descriptor_slot_manifest = _require_sha256(
            descriptor.get("checkpoint_slot_manifest_sha256"),
            error_code="CATALOG_CHECKPOINT_RECOVERY_SLOT_PLAN_HASH_INVALID",
        )
        if canonical_sha256(
            {
                "schema_version": "1",
                "artifacts": checkpoint_artifacts,
                "slot_count": slot_count,
            }
        ) != descriptor_slot_manifest:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SLOT_PLAN_HASH_INVALID")

        assignment_artifact = descriptor.get("assignment_artifact")
        assignment_member = descriptor.get("assignment_member")
        assignment_artifact = _safe_single_component(
            assignment_artifact,
            error_code="CATALOG_CHECKPOINT_RECOVERY_ASSIGNMENT_INVALID",
        )
        if not isinstance(assignment_member, str):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ASSIGNMENT_INVALID")
        assignment_path = _safe_relative(
            sealed_plan / "payload_artifacts" / assignment_artifact,
            assignment_member,
            error_code="CATALOG_CHECKPOINT_RECOVERY_ASSIGNMENT_INVALID",
        )
        assignment_sha = _require_sha256(
            descriptor.get("assignment_sha256"),
            error_code="CATALOG_CHECKPOINT_RECOVERY_ASSIGNMENT_HASH_INVALID",
        )
        try:
            if hashlib.sha256(assignment_path.read_bytes()).hexdigest() != assignment_sha:
                raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ASSIGNMENT_HASH_INVALID")
        except OSError as exc:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ASSIGNMENT_INVALID") from exc
        assignment = _read_json_object(
            assignment_path,
            error_code="CATALOG_CHECKPOINT_RECOVERY_ASSIGNMENT_INVALID",
        )
        if set(assignment) != _ASSIGNMENT_KEYS or assignment.get("schema_version") != "1" or assignment.get("worker_id") != worker_id:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ASSIGNMENT_INVALID")
        strategy_ids = _validate_ids(
            cast(Sequence[str], assignment.get("strategy_ids")),
            error_code="CATALOG_CHECKPOINT_RECOVERY_SOURCE_IDS_INVALID",
        )
        strategy_manifest = _require_sha256(
            assignment.get("expected_strategy_manifest_sha256"),
            error_code="CATALOG_CHECKPOINT_RECOVERY_ASSIGNMENT_HASH_INVALID",
        )
        if (
            canonical_sha256(
                {"schema_version": "1", "worker_id": worker_id, "strategy_ids": strategy_ids}
            )
            != strategy_manifest
            or descriptor.get("expected_strategy_manifest_sha256") != strategy_manifest
            or descriptor.get("expected_strategy_count") != len(strategy_ids)
        ):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ASSIGNMENT_INVALID")
        by_worker[worker_id] = {
            "strategy_ids": strategy_ids,
            "strategy_manifest_sha256": strategy_manifest,
            "checkpoint_slot_artifacts": checkpoint_artifacts,
            "checkpoint_slot_manifest_sha256": descriptor_slot_manifest,
        }
        all_source_ids.extend(strategy_ids)

    if (
        set(by_worker) != set(range(_SOURCE_WORKER_COUNT))
        or len(all_source_ids) != len(set(all_source_ids))
        or not set(all_source_ids).issubset(all_strategy_ids)
        or set(all_source_ids) != set(pending_strategy_ids)
        or len(all_source_ids) != len(pending_strategy_ids)
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_IDS_INVALID")
    return by_worker


def _validate_checkpoint_policy(
    sealed_plan: Path,
    *,
    source_by_worker: dict[int, dict[str, object]],
    expected_bindings: Mapping[str, str],
    expected_science: str,
    checkpoint_slot_count: int = _CHECKPOINT_SLOT_COUNT,
) -> dict[str, object]:
    slot_count = _validate_checkpoint_slot_count(checkpoint_slot_count)
    policy = _read_json_object(
        sealed_plan / "checkpoint_policy.json",
        error_code="CATALOG_CHECKPOINT_RECOVERY_POLICY_INVALID",
    )
    policy_hash = _require_sha256(
        policy.get("content_sha256"),
        error_code="CATALOG_CHECKPOINT_RECOVERY_POLICY_HASH_INVALID",
    )
    if canonical_sha256({key: value for key, value in policy.items() if key != "content_sha256"}) != policy_hash:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_POLICY_HASH_INVALID")
    if (
        policy.get("schema_version") != "1"
        or policy.get("document_type") != "checkpoint_policy"
        or policy.get("science_sha256") != expected_science
        or policy.get("authority_id") != expected_bindings["authority_id"]
        or policy.get("campaign_id") != expected_bindings["campaign_id"]
        or policy.get("execution_plan_sha256") != expected_bindings["execution_plan_sha256"]
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_POLICY_BINDING_INVALID")
    workers = policy.get("workers")
    if not isinstance(workers, list) or len(workers) != _SOURCE_WORKER_COUNT:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_POLICY_INVALID")
    policy_by_worker: dict[int, dict[str, object]] = {}
    for row in workers:
        if not isinstance(row, dict):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_POLICY_INVALID")
        worker_id = row.get("worker_id")
        if type(worker_id) is not int or worker_id in policy_by_worker:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_POLICY_INVALID")
        artifacts = row.get("checkpoint_slot_artifacts")
        if isinstance(artifacts, (str, bytes)) or not isinstance(artifacts, Sequence):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_POLICY_INVALID")
        if (
            row.get("checkpoint_slot_count") != slot_count
            or tuple(artifacts) != source_by_worker.get(worker_id, {}).get("checkpoint_slot_artifacts")
            or row.get("checkpoint_slot_manifest_sha256")
            != source_by_worker.get(worker_id, {}).get("checkpoint_slot_manifest_sha256")
        ):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_POLICY_BINDING_INVALID")
        policy_by_worker[worker_id] = cast(dict[str, object], row)
    if set(policy_by_worker) != set(range(_SOURCE_WORKER_COUNT)):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_POLICY_INVALID")
    blocks = policy.get("recovery_blocks_v1")
    if not isinstance(blocks, dict) or not isinstance(blocks.get("blocks"), list):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_POLICY_INVALID")
    routes: set[tuple[int, int]] = set()
    block_ids: set[str] = set()
    for row in blocks["blocks"]:
        if not isinstance(row, dict):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_POLICY_INVALID")
        worker_id, slot_index = row.get("worker_id"), row.get("slot_index")
        block_id = _require_sha256(
            row.get("block_id"), error_code="CATALOG_CHECKPOINT_RECOVERY_POLICY_INVALID"
        )
        route = (worker_id, slot_index)
        if (
            type(worker_id) is not int
            or type(slot_index) is not int
            or worker_id not in policy_by_worker
            or not 1 <= slot_index <= slot_count
            or route in routes
            or block_id in block_ids
        ):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_POLICY_INVALID")
        routes.add((worker_id, slot_index))
        block_ids.add(block_id)
    if len(routes) != _SOURCE_WORKER_COUNT * slot_count:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_POLICY_INVALID")
    return policy


def _validate_checkpoint_inventory(
    checkpoint_root: Path,
    expected_artifacts: tuple[str, ...],
    *,
    checkpoint_slot_count: int = _CHECKPOINT_SLOT_COUNT,
    expected_worker_count: int = _RECOVERY_WORKER_COUNT,
    selected_artifact: str | None = None,
) -> None:
    slot_count = _validate_checkpoint_slot_count(checkpoint_slot_count)
    if checkpoint_root.is_symlink() or not checkpoint_root.is_dir():
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_SET_INVALID")
    try:
        entries = tuple(checkpoint_root.iterdir())
    except OSError as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_SET_INVALID") from exc
    expected = set(expected_artifacts)
    if (
        len(expected_artifacts) != expected_worker_count * slot_count
        or set(entry.name for entry in entries) != expected
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_SET_INVALID")
    allowed_files = _CHECKPOINT_ALLOWED_FILES
    if slot_count == 2:
        allowed_files = allowed_files | {_SELECTED_RESULTS_FILE}
    for entry in entries:
        if entry.is_symlink() or not entry.is_dir():
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_SET_INVALID")
        try:
            children = tuple(entry.iterdir())
        except OSError as exc:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_SET_INVALID") from exc
        if any(child.is_symlink() or child.is_dir() for child in children):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_SET_INVALID")
        names = {child.name for child in children}
        if not _CHECKPOINT_REQUIRED_FILES.issubset(names) or not names.issubset(allowed_files):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_SET_INVALID")
        if any(not child.is_file() for child in children):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_SET_INVALID")
        receipt = _read_checkpoint_json(
            entry / "receipt.json",
            error_code="CATALOG_CHECKPOINT_RECOVERY_RECEIPT_INVALID",
        )
        selected_count = receipt.get("selected_strategy_count", _MISSING)
        if selected_count is not _MISSING and (
            type(selected_count) is not int or selected_count < 0
        ):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID")
        has_selected_sidecar = _SELECTED_RESULTS_FILE in names
        if has_selected_sidecar and (
            slot_count != 2 or selected_artifact is None or entry.name != selected_artifact
        ):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID")
        if selected_count not in (_MISSING, 0):
            if slot_count != 2 or selected_artifact is None or entry.name != selected_artifact:
                raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID")
            if selected_count != _SELECTED_RESULTS_ROW_COUNT or not has_selected_sidecar:
                raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID")
        if has_selected_sidecar:
            if selected_count != _SELECTED_RESULTS_ROW_COUNT:
                raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID")
            _validate_selected_results_sidecar(entry / _SELECTED_RESULTS_FILE)
        elif (
            slot_count == 2
            and selected_artifact is not None
            and entry.name == selected_artifact
            and selected_count == _SELECTED_RESULTS_ROW_COUNT
        ):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SELECTED_RESULTS_INVALID")


def _read_checkpoint_json(path: Path, *, error_code: str) -> dict[str, object]:
    return _read_json_object(path, error_code=error_code)


def _validate_checkpoint_slots(
    checkpoint_root: Path,
    *,
    policy: Mapping[str, object],
    source_by_worker: Mapping[int, Mapping[str, object]],
    worker_ids: tuple[int, ...],
    expected_science: str,
    expected_catalog: str,
    work_manifest_sha256: str,
    checkpoint_slot_count: int = _CHECKPOINT_SLOT_COUNT,
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    slot_count = _validate_checkpoint_slot_count(checkpoint_slot_count)
    artifact_names: list[str] = []
    receipt_hashes: list[str] = []
    chain_hashes: list[str] = []
    recovery_block_ids: list[str] = []
    assignment_hashes: list[str] = []
    for worker_id in worker_ids:
        source = source_by_worker[worker_id]
        source_ids = cast(tuple[str, ...], source["strategy_ids"])
        source_artifacts = cast(tuple[str, ...], source["checkpoint_slot_artifacts"])
        source_assignment_hash = str(source["strategy_manifest_sha256"])
        evidence: list[CheckpointSlotEvidence] = []
        for slot_index in range(1, slot_count + 1):
            artifact_name = source_artifacts[slot_index - 1]
            artifact_root = checkpoint_root / artifact_name
            expected_ids = source_ids[
                len(source_ids) * (slot_index - 1) // slot_count : len(source_ids) * slot_index // slot_count
            ]
            receipt = _read_checkpoint_json(
                artifact_root / "receipt.json",
                error_code="CATALOG_CHECKPOINT_RECOVERY_RECEIPT_INVALID",
            )
            attempt = _read_checkpoint_json(
                artifact_root / "shard_attempt_manifest.json",
                error_code="CATALOG_CHECKPOINT_RECOVERY_ATTEMPT_INVALID",
            )
            chain = _read_checkpoint_json(
                artifact_root / "checkpoint_chain_manifest.json",
                error_code="CATALOG_CHECKPOINT_RECOVERY_CHAIN_INVALID",
            )
            for document, error_code in (
                (receipt, "CATALOG_CHECKPOINT_RECOVERY_RECEIPT_BOUNDARY_INVALID"),
                (attempt, "CATALOG_CHECKPOINT_RECOVERY_ATTEMPT_BOUNDARY_INVALID"),
                (chain, "CATALOG_CHECKPOINT_RECOVERY_CHAIN_BOUNDARY_INVALID"),
            ):
                _validate_closed_boundary(document, error_code=error_code)
            attempt_ids = attempt.get("strategy_ids")
            completed_ids = chain.get("completed_strategy_ids")
            if (
                receipt.get("science_identity_sha256") != expected_science
                or receipt.get("catalog_manifest_sha256") != expected_catalog
                or receipt.get("work_manifest_sha256") != work_manifest_sha256
                or receipt.get("shard_index") != worker_id
                or receipt.get("checkpoint_slot_index") != slot_index
                or receipt.get("checkpoint_slot_count") != slot_count
                or receipt.get("strategy_count") != len(expected_ids)
                or receipt.get("previous_checkpoint_receipt_sha256")
                != chain.get("previous_receipt_sha256")
                or attempt.get("worker_id") != worker_id
                or attempt.get("checkpoint_slot_index") != slot_index
                or attempt.get("checkpoint_slot_count") != slot_count
                or attempt.get("previous_checkpoint_receipt_sha256")
                != chain.get("previous_receipt_sha256")
                or not isinstance(attempt_ids, list)
                or tuple(attempt_ids) != expected_ids
                or chain.get("worker_id") != worker_id
                or chain.get("slot_index") != slot_index
                or chain.get("slot_count") != slot_count
                or not isinstance(completed_ids, list)
                or tuple(completed_ids) != expected_ids
            ):
                raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SLOT_ASSIGNMENT_INVALID")
            previous_hash = _require_sha256(
                chain.get("previous_receipt_sha256"),
                error_code="CATALOG_CHECKPOINT_RECOVERY_CHAIN_INVALID",
            )
            current_hash = _require_sha256(
                chain.get("current_receipt_sha256"),
                error_code="CATALOG_CHECKPOINT_RECOVERY_CHAIN_INVALID",
            )
            chain_hash = _require_sha256(
                chain.get("chain_sha256"),
                error_code="CATALOG_CHECKPOINT_RECOVERY_CHAIN_INVALID",
            )
            block_id = verify_persisted_recovery_block(
                artifact_root,
                policy=policy,
                science_sha256=expected_science,
                worker_id=worker_id,
                slot_index=slot_index,
            )
            if (
                receipt.get("recovery_block_id") != block_id
                or attempt.get("recovery_block_id") != block_id
                or chain.get("recovery_block_id") != block_id
            ):
                raise ValueError("CATALOG_CHECKPOINT_RECOVERY_BLOCK_BINDING_INVALID")
            evidence.append(
                CheckpointSlotEvidence(
                    logical_scope_id=f"worker:{worker_id}",
                    slot_index=slot_index,
                    slot_count=slot_count,
                    artifact_name=artifact_name,
                    previous_receipt_sha256=previous_hash,
                    receipt_sha256=current_hash,
                    artifact_uploaded=True,
                )
            )
            artifact_names.append(artifact_name)
            receipt_hashes.append(current_hash)
            chain_hashes.append(chain_hash)
            recovery_block_ids.append(block_id)
            assignment_hashes.append(source_assignment_hash)
        selection = validate_checkpoint_slot_chain(
            evidence,
            logical_scope_id=f"worker:{worker_id}",
            expected_slot_count=slot_count,
        )
        if (
            selection.completed_slot_count != slot_count
            or selection.next_slot_index is not None
            or selection.reused_artifacts != source_artifacts[:slot_count]
        ):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_CHAIN_INVALID")
    if len(set(artifact_names)) != len(artifact_names) or len(set(recovery_block_ids)) != len(recovery_block_ids):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_DUPLICATE_INVALID")
    return (
        tuple(artifact_names),
        tuple(receipt_hashes),
        tuple(chain_hashes),
        tuple(recovery_block_ids),
        tuple(assignment_hashes),
    )


def _validate_resume_index(
    resume_index: CatalogResumeIndexV1,
    *,
    expected_science: str,
    expected_catalog: str,
    expected_strategy_ids: tuple[str, ...],
) -> None:
    if (
        resume_index.schema_version != "1"
        or resume_index.science_identity_sha256 != expected_science
        or resume_index.catalog_manifest_sha256 != expected_catalog
        or resume_index.validation_opened is not False
        or resume_index.locked_opened is not False
        or resume_index.duplicate_result_count != 0
        or resume_index.physical_result_count != len(expected_strategy_ids)
        or set(resume_index.strategy_ids) != set(expected_strategy_ids)
        or len(resume_index.strategy_ids) != len(expected_strategy_ids)
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_STRATEGY_COVERAGE_INVALID")
    for item in resume_index.results:
        try:
            result = json.loads(item.result_json)
        except ValueError as exc:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RESULT_INVALID") from exc
        if not isinstance(result, dict) or result.get("partial") is True:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RESULT_INVALID")
        info = result.get("info")
        if not isinstance(info, dict):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RESULT_INVALID")
        if info.get("validation_opened") is not False or info.get("locked_opened") is not False:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_RESULT_BOUNDARY_INVALID")


def verify_checkpoint_recovery_source(
    sealed_plan: Path,
    checkpoint_root: Path,
    expected_bindings: Mapping[str, str],
    expected_science_identity_sha256: str,
    expected_catalog_manifest_sha256: str,
    expected_strategy_ids: Sequence[str],
    expected_worker_ids: Sequence[int],
    *,
    checkpoint_slot_count: int = _CHECKPOINT_SLOT_COUNT,
) -> ValidatedCheckpointRecoverySource:
    """Validate the exact authenticated checkpoint source for local recovery.

    The source plan remains immutable and the returned evidence is read-only.
    The caller is responsible for external authentication; no GitHub or other
    provenance is consulted here.  Closed source layouts accept thirty
    selected workers with four slots (the default), or all sixty source
    workers with two slots.
    """

    sealed_root = Path(sealed_plan)
    checkpoints_root = Path(checkpoint_root)
    expected_science = _require_sha256(
        expected_science_identity_sha256,
        error_code="CATALOG_CHECKPOINT_RECOVERY_SCIENCE_INVALID",
    )
    expected_catalog = _require_sha256(
        expected_catalog_manifest_sha256,
        error_code="CATALOG_CHECKPOINT_RECOVERY_CATALOG_INVALID",
    )
    bindings = _validate_bindings(expected_bindings)
    slot_count = _validate_checkpoint_slot_count(checkpoint_slot_count)
    worker_ids = _validate_worker_ids(
        expected_worker_ids, checkpoint_slot_count=slot_count
    )
    strategy_ids = _validate_ids(
        expected_strategy_ids,
        error_code="CATALOG_CHECKPOINT_RECOVERY_STRATEGY_SET_INVALID",
    )
    expected_strategy_set = set(strategy_ids)

    plan_receipt_raw = verify_sealed_global_reuse_execution_plan(
        sealed_root,
        expected_bindings=bindings,
    )
    if not isinstance(plan_receipt_raw, dict):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PLAN_RECEIPT_INVALID")
    _validate_closed_boundary(
        plan_receipt_raw, error_code="CATALOG_CHECKPOINT_RECOVERY_BOUNDARY_INVALID"
    )
    if (
        plan_receipt_raw.get("active_recipe_workers") != _SOURCE_WORKER_COUNT
        or plan_receipt_raw.get("science_sha256") != expected_science
        or plan_receipt_raw.get("authority_id") != bindings["authority_id"]
        or plan_receipt_raw.get("campaign_id") != bindings["campaign_id"]
        or plan_receipt_raw.get("execution_plan_sha256") != bindings["execution_plan_sha256"]
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PLAN_BINDING_INVALID")
    plan_receipt_sha256 = _require_sha256(
        plan_receipt_raw.get("receipt_sha256"),
        error_code="CATALOG_CHECKPOINT_RECOVERY_PLAN_RECEIPT_INVALID",
    )
    if canonical_sha256(
        {key: value for key, value in plan_receipt_raw.items() if key != "receipt_sha256"}
    ) != plan_receipt_sha256:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PLAN_RECEIPT_INVALID")

    _validate_contract_science(
        sealed_root,
        expected_science=expected_science,
        expected_catalog=expected_catalog,
    )
    run_plan, all_strategy_ids, pending_strategy_ids, _ = _validate_run_plan_and_manifest(
        sealed_root,
        expected_science=expected_science,
    )
    source_by_worker = _read_recipe_source_assignments(
        sealed_root,
        all_strategy_ids=all_strategy_ids,
        pending_strategy_ids=pending_strategy_ids,
        checkpoint_slot_count=slot_count,
    )
    selected_source_ids = tuple(
        strategy_id
        for worker_id in worker_ids
        for strategy_id in cast(tuple[str, ...], source_by_worker[worker_id]["strategy_ids"])
    )
    if set(selected_source_ids) != expected_strategy_set or len(selected_source_ids) != len(strategy_ids):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_STRATEGY_COVERAGE_INVALID")
    policy = _validate_checkpoint_policy(
        sealed_root,
        source_by_worker=source_by_worker,
        expected_bindings=bindings,
        expected_science=expected_science,
        checkpoint_slot_count=slot_count,
    )
    expected_artifacts = tuple(
        artifact
        for worker_id in worker_ids
        for artifact in cast(tuple[str, ...], source_by_worker[worker_id]["checkpoint_slot_artifacts"])[
            :slot_count
        ]
    )
    selected_artifact = None
    if slot_count == 2:
        selected_artifact = cast(
            tuple[str, ...], source_by_worker[0]["checkpoint_slot_artifacts"]
        )[0]
    _validate_checkpoint_inventory(
        checkpoints_root,
        expected_artifacts,
        checkpoint_slot_count=slot_count,
        expected_worker_count=len(worker_ids),
        selected_artifact=selected_artifact,
    )
    (
        checkpoint_artifacts,
        receipt_hashes,
        chain_hashes,
        recovery_block_ids,
        assignment_hashes,
    ) = _validate_checkpoint_slots(
        checkpoints_root,
        policy=policy,
        source_by_worker=source_by_worker,
        worker_ids=worker_ids,
        expected_science=expected_science,
        expected_catalog=expected_catalog,
        work_manifest_sha256=str(run_plan["work_manifest_sha256"]),
        checkpoint_slot_count=slot_count,
    )
    resume_index = load_resume_index(
        (checkpoints_root,),
        expected_science_identity_sha256=expected_science,
        expected_catalog_manifest_sha256=expected_catalog,
    )
    _validate_resume_index(
        resume_index,
        expected_science=expected_science,
        expected_catalog=expected_catalog,
        expected_strategy_ids=strategy_ids,
    )
    return ValidatedCheckpointRecoverySource(
        resume_index=resume_index,
        plan_receipt=plan_receipt_raw,
        science_identity_sha256=expected_science,
        catalog_manifest_sha256=expected_catalog,
        work_manifest_sha256=str(run_plan["work_manifest_sha256"]),
        worker_ids=worker_ids,
        strategy_ids=tuple(sorted(expected_strategy_set)),
        checkpoint_artifact_names=checkpoint_artifacts,
        checkpoint_receipt_sha256s=receipt_hashes,
        checkpoint_chain_manifest_sha256s=chain_hashes,
        recovery_block_ids=recovery_block_ids,
        source_assignment_manifest_sha256s=assignment_hashes,
    )


__all__ = [
    "ValidatedCheckpointRecoverySource",
    "verify_checkpoint_recovery_source",
]
