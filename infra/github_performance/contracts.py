"""Immutable contracts shared by Aurora GitHub performance workflows."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
CodeSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]


class FrozenMapping(Mapping[str, Any]):
    """Small recursively immutable mapping used inside frozen contracts."""

    __slots__ = ("_data",)

    def __init__(self, value: Mapping[str, Any]) -> None:
        self._data = dict(value)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"FrozenMapping({self._data!r})"


def deep_freeze_json(value: Any) -> Any:
    """Recursively remove mutable JSON containers."""

    if isinstance(value, FrozenMapping):
        return value
    if isinstance(value, Mapping):
        return FrozenMapping({str(key): deep_freeze_json(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(deep_freeze_json(child) for child in value)
    return value


def deep_thaw_json(value: Any) -> Any:
    """Convert contracts and frozen containers to canonical JSON values."""

    if isinstance(value, BaseModel):
        return {
            name: deep_thaw_json(getattr(value, name))
            for name in type(value).model_fields
        }
    if isinstance(value, Mapping):
        return {str(key): deep_thaw_json(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [deep_thaw_json(child) for child in value]
    if isinstance(value, (set, frozenset)):
        return sorted(deep_thaw_json(child) for child in value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def canonical_sha256(value: BaseModel | Mapping[str, Any]) -> str:
    """Hash one contract using stable canonical JSON."""

    payload = json.dumps(
        deep_thaw_json(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class FrozenModel(BaseModel):
    """Base model that rejects extra fields and attribute mutation."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class TerminalState(str, Enum):
    COMPLETED = "completed"
    RIGHT_CENSORED = "right_censored"
    UNSUPPORTED = "unsupported"
    FAILED_TECHNICAL = "failed_technical"


class RunSpec(FrozenModel):
    schema_version: Literal["3.0"]
    identity: Mapping[str, Any]
    objective: Mapping[str, Any]
    policy: Mapping[str, Any]
    data: Mapping[str, Any]
    execution: Mapping[str, Any]
    resources: Mapping[str, Any]
    performance: Mapping[str, Any]
    retries: Mapping[str, Any]
    artifacts: Mapping[str, Any]
    security: Mapping[str, Any]
    statistics: Mapping[str, Any]
    metrics: Mapping[str, Any]
    reconciliation: Mapping[str, Any]
    gates: Mapping[str, Any]

    @field_validator(
        "identity",
        "objective",
        "policy",
        "data",
        "execution",
        "resources",
        "performance",
        "retries",
        "artifacts",
        "security",
        "statistics",
        "metrics",
        "reconciliation",
        "gates",
        mode="after",
    )
    @classmethod
    def _freeze_section(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return deep_freeze_json(value)


class RuntimeEvidence(FrozenModel):
    code_sha: CodeSha
    workflow_sha256: Sha256
    policy_hash: Sha256
    dependency_lock_sha256: Sha256
    capacity_profile_sha256: Sha256
    data_manifest_sha256: Sha256
    snapshot_hash: Sha256
    metric_contract_sha256: Sha256
    environment_sha256: Sha256


class CapacityProfile(FrozenModel):
    schema_version: str
    organization: str
    repository: str
    repository_visibility: Literal["public", "private", "internal"]
    plan: str
    standard_concurrency_ceiling: Annotated[int, Field(ge=1)]
    matrix_job_ceiling: Annotated[int, Field(ge=1, le=256)]
    runner_label: str
    reference_cpu: Annotated[int, Field(ge=1)]
    reference_memory_gb: Annotated[int, Field(ge=1)]
    reference_ssd_gb: Annotated[int, Field(ge=1)]
    larger_runners_allowed: bool
    confirmed_on: date
    confirmation_source: str


class PerformanceContract(FrozenModel):
    resolved_spec_sha256: Sha256
    code_sha: CodeSha
    workflow_sha256: Sha256
    policy_hash: Sha256
    snapshot_hash: Sha256
    data_manifest_sha256: Sha256
    metric_contract_sha256: Sha256
    dependency_lock_sha256: Sha256
    capacity_profile_sha256: Sha256
    environment_sha256: Sha256
    standard_runner_only: bool
    locked_opened: bool
    validation_used_for_selection: bool
    larger_runners_allowed: bool
    artifact_transport_mode: Literal[
        "auto",
        "actions_artifact",
        "snapshot_backend",
    ]
    planner_min_jobs: Annotated[int, Field(ge=1)]
    planner_max_jobs: Annotated[int, Field(ge=1, le=360)]
    planner_job_count_search: Literal["adaptive_exact"]
    planner_large_unit_threshold: Annotated[int, Field(ge=1)]
    planner_exact_lpt_candidates_max: Annotated[int, Field(ge=1, le=3)]
    matrix_job_ceiling: Annotated[int, Field(ge=1, le=256)]
    standard_concurrency_ceiling: Annotated[int, Field(ge=1, le=360)]
    runner_label: str
    max_memory_pct: Annotated[int, Field(ge=1, le=95)]
    min_free_disk_gb: NonNegativeFloat
    merge_fan_in: Annotated[int, Field(ge=2)]
    target_setup_fraction_max: Annotated[float, Field(ge=0, le=1)]
    target_checkpoint_fraction_max: Annotated[float, Field(ge=0, le=1)]

    @model_validator(mode="after")
    def _validate_job_bounds(self) -> PerformanceContract:
        if self.planner_min_jobs > self.planner_max_jobs:
            raise ValueError("planner_min_jobs must not exceed planner_max_jobs")
        return self


class ResourceSample(FrozenModel):
    rss_mb: NonNegativeFloat
    peak_memory_mb: NonNegativeFloat
    free_disk_mb: NonNegativeFloat
    cpu_seconds: NonNegativeFloat
    io_wait_seconds: NonNegativeFloat


class PreparedInputs(FrozenModel):
    manifest_path: str
    manifest_sha256: Sha256
    snapshot_hash: Sha256
    policy_hash: Sha256
    artifact_names: tuple[str, ...]


class SmokeResult(FrozenModel):
    passed: bool
    output_sha256: Sha256 | None
    reason_codes: tuple[str, ...]


class PilotResult(FrozenModel):
    queue_seconds: NonNegativeFloat
    setup_seconds: NonNegativeFloat
    transfer_fixed_seconds: NonNegativeFloat
    transfer_per_wave_seconds: NonNegativeFloat
    checkpoint_seconds: NonNegativeFloat
    merge_fixed_seconds: NonNegativeFloat
    merge_per_shard_seconds: NonNegativeFloat
    verify_seconds: NonNegativeFloat
    unit_seconds_p50: NonNegativeFloat
    unit_seconds_p95: NonNegativeFloat
    usable_parallelism: Annotated[int, Field(ge=1, le=360)]

    @model_validator(mode="after")
    def _validate_quantiles(self) -> PilotResult:
        if self.unit_seconds_p95 < self.unit_seconds_p50:
            raise ValueError("unit_seconds_p95 must be at least unit_seconds_p50")
        return self


class WorkUnit(FrozenModel):
    unit_key: str
    estimated_seconds: NonNegativeFloat
    payload_ref: str
    payload_sha256: Sha256


class WorkUnitManifest(FrozenModel):
    path: str
    sha256: Sha256
    schema_version: str
    unit_count: NonNegativeInt
    total_estimated_seconds: NonNegativeFloat


class ShardDefinition(FrozenModel):
    shard_id: str
    assignment_artifact: str
    assignment_member: str
    assignment_sha256: Sha256
    unit_count: Annotated[int, Field(ge=1)]
    estimated_seconds: NonNegativeFloat
    merge_group: str


class ShardPlan(FrozenModel):
    selected_jobs: Annotated[int, Field(ge=1, le=360)]
    work_unit_manifest_sha256: Sha256
    assignment_artifact: str
    assignment_manifest_sha256: Sha256
    shards: tuple[ShardDefinition, ...]
    plan_sha256: Sha256


class JobCountAlternative(FrozenModel):
    jobs: Annotated[int, Field(ge=1, le=360)]
    waves: Annotated[int, Field(ge=1)]
    slowest_shard_seconds: NonNegativeFloat
    predicted_seconds: NonNegativeFloat
    estimate_kind: Literal["analytical", "histogram", "exact_lpt"]


class JobCountDecision(FrozenModel):
    selected_jobs: Annotated[int, Field(ge=1, le=360)]
    predicted_seconds: NonNegativeFloat
    alternatives: tuple[JobCountAlternative, ...]


class MatrixSplit(FrozenModel):
    matrix_a: tuple[ShardDefinition, ...]
    matrix_b: tuple[ShardDefinition, ...]
    has_matrix_b: bool

    @model_validator(mode="after")
    def _validate_split(self) -> MatrixSplit:
        if len(self.matrix_a) > 256 or len(self.matrix_b) > 104:
            raise ValueError("matrix split exceeds GitHub limits")
        if self.has_matrix_b != bool(self.matrix_b):
            raise ValueError("has_matrix_b must match matrix_b contents")
        return self


class ExecutionPlan(FrozenModel):
    job_count: JobCountDecision
    shard_plan: ShardPlan
    matrix_split: MatrixSplit
    assignment_strategy: Literal[
        "weighted_lpt_hierarchical",
        "equal_count_flat",
    ]
    numeric_threads: Annotated[int, Field(ge=1)]
    checkpoint_interval_seconds: NonNegativeFloat
    artifact_compression_level: Annotated[int, Field(ge=0, le=9)]
    fallback_plan_sha256: Sha256


class MergeGroup(FrozenModel):
    group_id: str
    level: NonNegativeInt
    input_artifacts: tuple[str, ...]
    projected_input_bytes: NonNegativeInt
    projected_output_bytes: NonNegativeInt
    output_artifact: str


class MergePlan(FrozenModel):
    fan_in: Annotated[int, Field(ge=2)]
    groups: tuple[MergeGroup, ...]
    plan_sha256: Sha256


class AttemptManifest(FrozenModel):
    shard_id: str
    attempt_id: str
    state: TerminalState
    spec_hash: Sha256
    policy_hash: Sha256
    snapshot_hash: Sha256
    code_sha: CodeSha
    dependency_lock_sha256: Sha256
    capacity_profile_sha256: Sha256
    output_sha256: Sha256 | None
    reason_code: str | None
    artifact_name: str | None
    unit_attempts_path: str | None
    unit_attempts_sha256: Sha256 | None
    checkpoint_artifact: str | None
    completed_unit_count: NonNegativeInt
    output_rows: NonNegativeInt
    output_bytes: NonNegativeInt
    runtime_access_ledger_path: str | None = None
    runtime_access_ledger_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def _validate_terminal_evidence(self) -> AttemptManifest:
        if self.state is TerminalState.COMPLETED:
            required = (
                self.output_sha256,
                self.artifact_name,
                self.unit_attempts_path,
                self.unit_attempts_sha256,
            )
            if any(value is None for value in required):
                raise ValueError("completed attempt requires output and unit-attempt evidence")
        elif not self.reason_code:
            raise ValueError("non-completed attempt requires reason_code")
        return self


class UnitAttemptRecord(FrozenModel):
    unit_key: str
    shard_id: str
    attempt_id: str
    state: TerminalState
    output_sha256: Sha256 | None
    reason_code: str | None

    @model_validator(mode="after")
    def _validate_terminal_evidence(self) -> UnitAttemptRecord:
        if self.state is TerminalState.COMPLETED:
            if self.output_sha256 is None:
                raise ValueError("completed unit requires output_sha256")
        elif not self.reason_code:
            raise ValueError("non-completed unit requires reason_code")
        return self


class CheckpointManifest(FrozenModel):
    shard_id: str
    attempt_id: str
    artifact_name: str
    completed_unit_count: NonNegativeInt
    last_completed_unit_key: str | None
    payload_path: str
    payload_sha256: Sha256
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value


class RecoveryDecision(FrozenModel):
    shard_id: str
    prior_attempt_id: str
    action: Literal["retry", "replan", "do_not_retry"]
    failure_class: str
    next_attempt_id: str | None
    checkpoint_artifact: str | None
    reason_code: str


class CheckpointAuditRecord(FrozenModel):
    checkpoint_ref: str
    shard_id: str | None
    attempt_id: str | None
    artifact_name: str | None
    status: Literal["verified", "selected", "rejected"]
    completed_unit_count: NonNegativeInt | None
    payload_sha256: Sha256 | None
    reason_code: str | None


class RecoveryPlan(FrozenModel):
    decisions: tuple[RecoveryDecision, ...]
    checkpoint_audit: tuple[CheckpointAuditRecord, ...] = ()
    retry_matrix_a: tuple[Mapping[str, Any], ...]
    retry_matrix_b: tuple[Mapping[str, Any], ...]
    has_retry_matrix_a: bool
    has_retry_matrix_b: bool
    plan_sha256: Sha256

    @field_validator("retry_matrix_a", "retry_matrix_b", mode="after")
    @classmethod
    def _freeze_matrix(
        cls,
        value: tuple[Mapping[str, Any], ...],
    ) -> tuple[Mapping[str, Any], ...]:
        return tuple(deep_freeze_json(item) for item in value)


class UnitReconciliationRecord(FrozenModel):
    unit_key: str
    state: TerminalState
    selected_attempt_id: str
    output_sha256: Sha256 | None
    reason_code: str | None
    duplicate_attempt_ids: tuple[str, ...] = ()


class ReconciliationResult(FrozenModel):
    expected_units: NonNegativeInt
    completed: NonNegativeInt
    right_censored: NonNegativeInt
    unsupported: NonNegativeInt
    failed_technical: NonNegativeInt
    selected_attempt_ids: tuple[str, ...]
    identical_duplicate_attempt_ids: tuple[str, ...]
    conflicting_unit_keys: tuple[str, ...]
    missing_unit_keys: tuple[str, ...]
    partial: bool
    unit_records: tuple[UnitReconciliationRecord, ...] = ()

    @model_validator(mode="after")
    def _validate_totals(self) -> ReconciliationResult:
        terminal = self.completed + self.right_censored + self.unsupported
        terminal += self.failed_technical
        if terminal > self.expected_units:
            raise ValueError("terminal outcomes exceed expected_units")
        return self


class Violation(FrozenModel):
    code: str
    path: str
    message: str
    severity: Literal["error", "warning"]


class PreflightReport(FrozenModel):
    valid: bool
    spec_hash: Sha256 | None
    violations: tuple[Violation, ...]

    @property
    def violation_codes(self) -> frozenset[str]:
        return frozenset(item.code for item in self.violations)


class VerificationReport(FrozenModel):
    passed: bool
    partial: bool
    requirements_passed: bool
    locked_opened: bool
    validation_used_for_selection: bool
    standard_runner_only: bool
    matrix_job_ceiling_respected: bool
    evidence_paths: tuple[str, ...]
    terminal_counts: Mapping[str, int] = Field(default_factory=dict)
    evidence_sha256: Mapping[str, Sha256] = Field(default_factory=dict)
    failure_codes: tuple[str, ...] = ()

    @field_validator("terminal_counts", "evidence_sha256", mode="after")
    @classmethod
    def _freeze_evidence_mapping(
        cls,
        value: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return deep_freeze_json(value)


class BenchmarkReport(FrozenModel):
    passed: bool
    scientific_outputs_equal: bool
    reference_wall_seconds: NonNegativeFloat
    optimized_wall_seconds: NonNegativeFloat
    speedup: NonNegativeFloat
    reference_billable_minutes: NonNegativeFloat
    optimized_billable_minutes: NonNegativeFloat
    predicted_observed_error_pct: NonNegativeFloat
