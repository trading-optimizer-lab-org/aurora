"""Failure classification and selective GitHub shard recovery."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from aurora.infra.github_performance.checkpoint import (
    CheckpointIntegrityError,
    load_checkpoint,
)
from aurora.infra.github_performance.contracts import (
    AttemptManifest,
    CheckpointAuditRecord,
    CheckpointManifest,
    RecoveryDecision,
    RecoveryPlan,
    ShardDefinition,
    ShardPlan,
    TerminalState,
    FrozenModel,
    canonical_sha256,
    deep_thaw_json,
)
from aurora.infra.github_performance.preflight import load_github_yaml


class FailureClass(str, Enum):
    TRANSIENT_NETWORK = "transient_network"
    GITHUB_5XX = "github_5xx"
    PROVIDER_429 = "provider_429"
    ARTIFACT_UPLOAD = "artifact_upload"
    RUNNER_LOST = "runner_lost"
    DETERMINISTIC_INPUT = "deterministic_input"
    SCHEMA = "schema"
    POLICY = "policy"
    CODE = "code"
    OUT_OF_MEMORY = "out_of_memory"
    DISK_EXHAUSTED = "disk_exhausted"

    def __str__(self) -> str:
        return self.value


class RecoveryLoopStatus(str, Enum):
    RETRY = "retry"
    REPLAN = "replan"
    COMPLETE = "complete"
    BLOCKED_HARD_FAILURE = "blocked_hard_failure"
    BUDGET_EXHAUSTED = "budget_exhausted"


class RecoveryLoopResult(FrozenModel):
    status: RecoveryLoopStatus
    current_wave: int
    next_wave: int | None
    retry_count: int
    terminal_shard_count: int
    replan_shard_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    plan: RecoveryPlan


TRANSIENT_CLASSES = frozenset(
    {
        FailureClass.TRANSIENT_NETWORK,
        FailureClass.GITHUB_5XX,
        FailureClass.PROVIDER_429,
        FailureClass.ARTIFACT_UPLOAD,
        FailureClass.RUNNER_LOST,
    }
)
REPLAN_CLASSES = frozenset(
    {
        FailureClass.OUT_OF_MEMORY,
        FailureClass.DISK_EXHAUSTED,
    }
)
REASON_CLASS = {
    "TRANSIENT_NETWORK": FailureClass.TRANSIENT_NETWORK,
    "NETWORK_TIMEOUT": FailureClass.TRANSIENT_NETWORK,
    "CONNECTION_RESET": FailureClass.TRANSIENT_NETWORK,
    "GITHUB_5XX": FailureClass.GITHUB_5XX,
    "PROVIDER_429": FailureClass.PROVIDER_429,
    "ARTIFACT_UPLOAD": FailureClass.ARTIFACT_UPLOAD,
    "ARTIFACT_UPLOAD_FAILED": FailureClass.ARTIFACT_UPLOAD,
    "RUNNER_LOST": FailureClass.RUNNER_LOST,
    "MISSING_ATTEMPT": FailureClass.RUNNER_LOST,
    "INPUT_HASH_MISMATCH": FailureClass.DETERMINISTIC_INPUT,
    "DETERMINISTIC_INPUT": FailureClass.DETERMINISTIC_INPUT,
    "SCHEMA_MISMATCH": FailureClass.SCHEMA,
    "POLICY_VIOLATION": FailureClass.POLICY,
    "DETERMINISTIC_CODE_ERROR": FailureClass.CODE,
    "CODE_ERROR": FailureClass.CODE,
    "OUT_OF_MEMORY": FailureClass.OUT_OF_MEMORY,
    "DISK_EXHAUSTED": FailureClass.DISK_EXHAUSTED,
}


class RecoveryMatrixTooLarge(RuntimeError):
    """Raised before recovery descriptors exceed GitHub output limits."""


def classify_failure(payload: Mapping[str, Any]) -> FailureClass:
    reason = str(
        payload.get("reason_code")
        or payload.get("reason")
        or payload.get("conclusion")
        or ""
    ).upper()
    return REASON_CLASS.get(reason, FailureClass.CODE)


def _attempt_number(attempt_id: str) -> tuple[int, str]:
    digits = "".join(character for character in attempt_id if character.isdigit())
    return (int(digits) if digits else -1, attempt_id)


def _new_attempt_id() -> str:
    return f"a-{uuid.uuid4()}"


def _best_checkpoint(
    shard_id: str,
    checkpoints: Sequence[CheckpointManifest],
) -> CheckpointManifest | None:
    eligible = [
        checkpoint
        for checkpoint in checkpoints
        if checkpoint.shard_id == shard_id
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (
            item.completed_unit_count,
            item.created_at,
            item.attempt_id,
        ),
    )


def _retry_descriptor(
    shard: ShardDefinition,
    attempt_id: str,
    checkpoint: CheckpointManifest | None,
) -> Mapping[str, Any]:
    return {
        "shard_id": shard.shard_id,
        "attempt_id": attempt_id,
        "merge_group": shard.merge_group,
        "checkpoint_artifact": (
            checkpoint.artifact_name if checkpoint is not None else ""
        ),
        "assignment_artifact": shard.assignment_artifact,
        "assignment_member": shard.assignment_member,
        "assignment_sha256": shard.assignment_sha256,
    }


def build_recovery_plan(
    shards: Iterable[ShardDefinition],
    attempts: Sequence[AttemptManifest],
    checkpoints: Sequence[CheckpointManifest],
    retry_policy: Mapping[str, int],
    checkpoint_audit: Sequence[CheckpointAuditRecord] = (),
) -> RecoveryPlan:
    """Retry only transient failures within their exact class budget."""

    ordered_shards = tuple(sorted(shards, key=lambda item: item.shard_id))
    if len({shard.shard_id for shard in ordered_shards}) != len(
        ordered_shards
    ):
        raise ValueError("duplicate shard_id in recovery input")
    attempts_by_shard: dict[str, list[AttemptManifest]] = defaultdict(list)
    for attempt in attempts:
        attempts_by_shard[attempt.shard_id].append(attempt)

    decisions: list[RecoveryDecision] = []
    retry_descriptors: list[Mapping[str, Any]] = []
    selected_checkpoint_artifacts: set[str] = set()
    for shard in ordered_shards:
        shard_attempts = sorted(
            attempts_by_shard.get(shard.shard_id, []),
            key=lambda item: _attempt_number(item.attempt_id),
        )
        if shard_attempts and any(
            item.state is TerminalState.COMPLETED
            for item in shard_attempts
        ):
            continue
        if shard_attempts:
            prior = shard_attempts[-1]
            reason = prior.reason_code or "DETERMINISTIC_CODE_ERROR"
            failure_class = classify_failure({"reason_code": reason})
            prior_attempt_id = prior.attempt_id
        else:
            reason = "MISSING_ATTEMPT"
            failure_class = FailureClass.RUNNER_LOST
            prior_attempt_id = "missing"
        checkpoint = _best_checkpoint(shard.shard_id, checkpoints)
        if failure_class in TRANSIENT_CLASSES:
            budget = int(retry_policy.get(failure_class.value, 0))
            same_class_failures = sum(
                classify_failure(
                    {"reason_code": attempt.reason_code or ""}
                )
                is failure_class
                for attempt in shard_attempts
                if attempt.state is TerminalState.FAILED_TECHNICAL
            )
            retries_used = max(0, same_class_failures - 1)
            if retries_used >= budget:
                decision = RecoveryDecision(
                    shard_id=shard.shard_id,
                    prior_attempt_id=prior_attempt_id,
                    action="do_not_retry",
                    failure_class=failure_class.value,
                    next_attempt_id=None,
                    checkpoint_artifact=None,
                    reason_code="RETRY_BUDGET_EXHAUSTED",
                )
            else:
                next_attempt = _new_attempt_id()
                decision = RecoveryDecision(
                    shard_id=shard.shard_id,
                    prior_attempt_id=prior_attempt_id,
                    action="retry",
                    failure_class=failure_class.value,
                    next_attempt_id=next_attempt,
                    checkpoint_artifact=(
                        checkpoint.artifact_name
                        if checkpoint is not None
                        else None
                    ),
                    reason_code=reason,
                )
                retry_descriptors.append(
                    _retry_descriptor(shard, next_attempt, checkpoint)
                )
                if checkpoint is not None:
                    selected_checkpoint_artifacts.add(
                        checkpoint.artifact_name
                    )
        elif failure_class in REPLAN_CLASSES:
            decision = RecoveryDecision(
                shard_id=shard.shard_id,
                prior_attempt_id=prior_attempt_id,
                action="replan",
                failure_class=failure_class.value,
                next_attempt_id=None,
                checkpoint_artifact=None,
                reason_code=reason,
            )
        else:
            decision = RecoveryDecision(
                shard_id=shard.shard_id,
                prior_attempt_id=prior_attempt_id,
                action="do_not_retry",
                failure_class=failure_class.value,
                next_attempt_id=None,
                checkpoint_artifact=None,
                reason_code=reason,
            )
        decisions.append(decision)

    matrix_a = tuple(retry_descriptors[:256])
    matrix_b = tuple(retry_descriptors[256:360])
    if len(retry_descriptors) > 360:
        raise ValueError("recovery plan exceeds standard concurrency ceiling")
    audit_by_artifact = {
        item.artifact_name: item
        for item in checkpoint_audit
        if item.artifact_name is not None
    }
    for checkpoint in checkpoints:
        status = (
            "selected"
            if checkpoint.artifact_name in selected_checkpoint_artifacts
            else "verified"
        )
        audit_by_artifact[checkpoint.artifact_name] = CheckpointAuditRecord(
            checkpoint_ref=checkpoint.artifact_name,
            shard_id=checkpoint.shard_id,
            attempt_id=checkpoint.attempt_id,
            artifact_name=checkpoint.artifact_name,
            status=status,
            completed_unit_count=checkpoint.completed_unit_count,
            payload_sha256=checkpoint.payload_sha256,
            reason_code=None,
        )
    audit_records = tuple(
        sorted(
            (
                *(
                    item
                    for item in checkpoint_audit
                    if item.artifact_name is None
                ),
                *audit_by_artifact.values(),
            ),
            key=lambda item: (
                item.checkpoint_ref,
                item.status,
            ),
        )
    )
    payload = {
        "decisions": [deep_thaw_json(item) for item in decisions],
        "checkpoint_audit": [
            deep_thaw_json(item) for item in audit_records
        ],
        "retry_matrix_a": [dict(item) for item in matrix_a],
        "retry_matrix_b": [dict(item) for item in matrix_b],
        "has_retry_matrix_a": bool(matrix_a),
        "has_retry_matrix_b": bool(matrix_b),
    }
    return RecoveryPlan(
        **payload,
        plan_sha256=canonical_sha256(payload),
    )


def build_recovery_loop(
    shards: Iterable[ShardDefinition],
    attempts: Sequence[AttemptManifest],
    checkpoints: Sequence[CheckpointManifest],
    retry_policy: Mapping[str, int],
    *,
    current_wave: int,
    max_waves: int,
    checkpoint_audit: Sequence[CheckpointAuditRecord] = (),
) -> RecoveryLoopResult:
    """Plan the next bounded recovery wave from all immutable evidence."""

    if current_wave < 0:
        raise ValueError("current_wave must be non-negative")
    if max_waves < 1:
        raise ValueError("max_waves must be positive")
    ordered_shards = tuple(sorted(shards, key=lambda item: item.shard_id))
    plan = build_recovery_plan(
        ordered_shards,
        attempts,
        checkpoints,
        retry_policy,
        checkpoint_audit,
    )
    terminal_states = {
        TerminalState.COMPLETED,
        TerminalState.RIGHT_CENSORED,
        TerminalState.UNSUPPORTED,
    }
    terminal_shards = {
        attempt.shard_id
        for attempt in attempts
        if attempt.state in terminal_states
    }
    retry_count = len(plan.retry_matrix_a) + len(plan.retry_matrix_b)
    replans = tuple(
        decision.shard_id
        for decision in plan.decisions
        if decision.action == "replan"
    )
    do_not_retry = tuple(
        decision
        for decision in plan.decisions
        if decision.action == "do_not_retry"
    )
    if len(terminal_shards) == len(ordered_shards):
        status = RecoveryLoopStatus.COMPLETE
        next_wave = None
        reasons: tuple[str, ...] = ()
    elif replans:
        status = RecoveryLoopStatus.REPLAN
        next_wave = None
        reasons = tuple(
            dict.fromkeys(
                decision.reason_code
                for decision in plan.decisions
                if decision.action == "replan"
            )
        )
    elif retry_count and current_wave + 1 < max_waves:
        status = RecoveryLoopStatus.RETRY
        next_wave = current_wave + 1
        reasons = ()
    elif retry_count:
        status = RecoveryLoopStatus.BUDGET_EXHAUSTED
        next_wave = None
        retry_count = 0
        reasons = ("RECOVERY_WAVE_BUDGET_EXHAUSTED",)
        payload = deep_thaw_json(plan)
        payload.pop("plan_sha256", None)
        payload["retry_matrix_a"] = []
        payload["retry_matrix_b"] = []
        payload["has_retry_matrix_a"] = False
        payload["has_retry_matrix_b"] = False
        plan = RecoveryPlan(
            **payload,
            plan_sha256=canonical_sha256(payload),
        )
    elif do_not_retry and all(
        decision.reason_code == "RETRY_BUDGET_EXHAUSTED"
        for decision in do_not_retry
    ):
        status = RecoveryLoopStatus.BUDGET_EXHAUSTED
        next_wave = None
        reasons = ("RETRY_BUDGET_EXHAUSTED",)
    elif do_not_retry:
        status = RecoveryLoopStatus.BLOCKED_HARD_FAILURE
        next_wave = None
        reasons = tuple(
            dict.fromkeys(
                decision.reason_code for decision in do_not_retry
            )
        )
    else:
        status = RecoveryLoopStatus.BLOCKED_HARD_FAILURE
        next_wave = None
        reasons = ("RECOVERY_EVIDENCE_INCOMPLETE",)
    return RecoveryLoopResult(
        status=status,
        current_wave=current_wave,
        next_wave=next_wave,
        retry_count=retry_count,
        terminal_shard_count=len(terminal_shards),
        replan_shard_ids=replans,
        reason_codes=reasons,
        plan=plan,
    )


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


def _atomic_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
    return path


def write_recovery_plan(
    plan: RecoveryPlan,
    output_dir: Path,
    *,
    max_output_bytes: int = 262_144,
) -> tuple[Path, Path, Path, Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    compact_a = json.dumps(
        {"include": deep_thaw_json(plan.retry_matrix_a)},
        separators=(",", ":"),
        sort_keys=True,
    )
    compact_b = json.dumps(
        {"include": deep_thaw_json(plan.retry_matrix_b)},
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(compact_a.encode()) + len(compact_b.encode()) >= max_output_bytes:
        raise RecoveryMatrixTooLarge(
            "recovery matrix outputs exceed 262144 bytes"
        )
    plan_path = _atomic_json(root / "recovery_plan.json", plan)
    matrix_a_path = _atomic_text(
        root / "retry_matrix_a.json",
        compact_a + "\n",
    )
    matrix_b_path = _atomic_text(
        root / "retry_matrix_b.json",
        compact_b + "\n",
    )
    audit_schema = pa.schema(
        [
            pa.field("record_type", pa.string(), nullable=False),
            pa.field("shard_id", pa.string(), nullable=False),
            pa.field("prior_attempt_id", pa.string(), nullable=False),
            pa.field("action", pa.string(), nullable=True),
            pa.field("failure_class", pa.string(), nullable=True),
            pa.field("checkpoint_artifact", pa.string(), nullable=True),
            pa.field("checkpoint_status", pa.string(), nullable=True),
            pa.field("completed_unit_count", pa.int64(), nullable=True),
            pa.field("payload_sha256", pa.string(), nullable=True),
            pa.field("reason_code", pa.string(), nullable=True),
        ],
        metadata={b"schema_version": b"1"},
    )
    rows = [
        {
            "record_type": "recovery_decision",
            "shard_id": item.shard_id,
            "prior_attempt_id": item.prior_attempt_id,
            "action": item.action,
            "failure_class": item.failure_class,
            "checkpoint_artifact": item.checkpoint_artifact,
            "checkpoint_status": None,
            "completed_unit_count": None,
            "payload_sha256": None,
            "reason_code": item.reason_code,
        }
        for item in plan.decisions
    ]
    rows.extend(
        {
            "record_type": "checkpoint",
            "shard_id": item.shard_id or "",
            "prior_attempt_id": item.attempt_id or "",
            "action": None,
            "failure_class": None,
            "checkpoint_artifact": (
                item.artifact_name or item.checkpoint_ref
            ),
            "checkpoint_status": item.status,
            "completed_unit_count": item.completed_unit_count,
            "payload_sha256": item.payload_sha256,
            "reason_code": item.reason_code,
        }
        for item in plan.checkpoint_audit
    )
    table = pa.Table.from_pylist(rows, schema=audit_schema)
    audit_path = root / "checkpoint_audit.parquet"
    temporary = audit_path.with_suffix(audit_path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", version="2.6")
    temporary.replace(audit_path)
    return plan_path, matrix_a_path, matrix_b_path, audit_path


def _load_attempt(path: Path) -> tuple[AttemptManifest, ...]:
    if path.suffix == ".parquet":
        return tuple(
            AttemptManifest.model_validate(row)
            for row in pq.read_table(path).to_pylist()
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return tuple(AttemptManifest.model_validate(item) for item in payload)
    return (AttemptManifest.model_validate(payload),)


def build_recovery_plan_from_paths(
    shard_plan_path: Path,
    attempt_paths: Sequence[Path],
    checkpoint_paths: Sequence[Path],
    spec_path: Path,
) -> RecoveryPlan:
    shard_plan = ShardPlan.model_validate_json(
        Path(shard_plan_path).read_text(encoding="utf-8")
    )
    attempts = tuple(
        attempt
        for path in attempt_paths
        for attempt in _load_attempt(Path(path))
    )
    checkpoints_list: list[CheckpointManifest] = []
    checkpoint_audit: list[CheckpointAuditRecord] = []
    for raw_path in checkpoint_paths:
        path = Path(raw_path)
        try:
            checkpoint = load_checkpoint(path)
        except CheckpointIntegrityError:
            checkpoint_audit.append(
                CheckpointAuditRecord(
                    checkpoint_ref=path.name,
                    shard_id=None,
                    attempt_id=None,
                    artifact_name=None,
                    status="rejected",
                    completed_unit_count=None,
                    payload_sha256=None,
                    reason_code="CHECKPOINT_INTEGRITY_ERROR",
                )
            )
        else:
            checkpoints_list.append(checkpoint)
    checkpoints = tuple(checkpoints_list)
    spec = load_github_yaml(Path(spec_path))
    retry_policy = spec.get("retries", {})
    if not isinstance(retry_policy, Mapping):
        raise ValueError("spec.retries must be a mapping")
    return build_recovery_plan(
        shard_plan.shards,
        attempts,
        checkpoints,
        retry_policy,
        checkpoint_audit,
    )


def build_recovery_loop_from_paths(
    shard_plan_path: Path,
    attempt_paths: Sequence[Path],
    checkpoint_paths: Sequence[Path],
    spec_path: Path,
    *,
    current_wave: int,
    max_waves: int,
) -> RecoveryLoopResult:
    shard_plan = ShardPlan.model_validate_json(
        Path(shard_plan_path).read_text(encoding="utf-8")
    )
    attempts = tuple(
        attempt
        for path in attempt_paths
        for attempt in _load_attempt(Path(path))
    )
    checkpoints_list: list[CheckpointManifest] = []
    checkpoint_audit: list[CheckpointAuditRecord] = []
    for raw_path in checkpoint_paths:
        path = Path(raw_path)
        try:
            checkpoint = load_checkpoint(path)
        except CheckpointIntegrityError:
            checkpoint_audit.append(
                CheckpointAuditRecord(
                    checkpoint_ref=path.name,
                    shard_id=None,
                    attempt_id=None,
                    artifact_name=None,
                    status="rejected",
                    completed_unit_count=None,
                    payload_sha256=None,
                    reason_code="CHECKPOINT_INTEGRITY_ERROR",
                )
            )
        else:
            checkpoints_list.append(checkpoint)
    spec = load_github_yaml(Path(spec_path))
    retry_policy = spec.get("retries", {})
    if not isinstance(retry_policy, Mapping):
        raise ValueError("spec.retries must be a mapping")
    return build_recovery_loop(
        shard_plan.shards,
        attempts,
        tuple(checkpoints_list),
        retry_policy,
        current_wave=current_wave,
        max_waves=max_waves,
        checkpoint_audit=tuple(checkpoint_audit),
    )


def write_recovery_loop(
    result: RecoveryLoopResult,
    output_dir: Path,
    *,
    max_output_bytes: int = 262_144,
) -> tuple[Path, ...]:
    paths = write_recovery_plan(
        result.plan,
        output_dir,
        max_output_bytes=max_output_bytes,
    )
    loop_path = _atomic_json(
        Path(output_dir) / "recovery_loop.json",
        result,
    )
    return (*paths, loop_path)
