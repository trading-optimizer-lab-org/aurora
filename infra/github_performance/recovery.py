"""Failure classification and selective GitHub shard recovery."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from aurora.infra.github_performance.checkpoint import (
    CheckpointIntegrityError,
    load_checkpoint,
)
from aurora.infra.github_performance.contracts import (
    AttemptManifest,
    CheckpointAuditRecord,
    CheckpointManifest,
    FrozenModel,
    RecoveryDecision,
    RecoveryPlan as RecoveryPlanContract,
    ShardDefinition,
    ShardPlan,
    TerminalState,
    UnitAttemptRecord,
    canonical_sha256,
    deep_thaw_json,
)
from aurora.infra.github_performance.shard_planner import sha256_file


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
    INTEGRITY = "integrity"
    UNKNOWN = "unknown"
    DETERMINISTIC_SCIENTIFIC_ENGINE_FAILURE = (
        "deterministic_scientific_engine_failure"
    )
    WORKFLOW_OR_JOB_CANCELLED = "workflow_or_job_cancelled"
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
    FAILED_SCIENTIFIC = "failed_scientific"
    WAITING_RETRY = "waiting_retry"


class RecoveryLoopResult(FrozenModel):
    status: RecoveryLoopStatus
    current_wave: int
    next_wave: int | None
    retry_count: int
    terminal_shard_count: int
    terminal_unit_count: int
    terminal_unit_manifest_sha256: str | None
    verified_source_artifacts: tuple[str, ...]
    replan_shard_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    plan: RecoveryPlan


class TerminalUnitEvidence(FrozenModel):
    unit_keys: tuple[str, ...]
    unit_count: int
    unit_manifest_sha256: str | None
    source_artifacts: tuple[str, ...]
    identical_duplicate_unit_keys: tuple[str, ...] = ()
    duplicate_attempt_ids: tuple[str, ...] = ()


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
    "INTEGRITY_ERROR": FailureClass.INTEGRITY,
    "CHECKPOINT_INTEGRITY_ERROR": FailureClass.INTEGRITY,
    "SCIENTIFIC_ENGINE_EXPECTED_FAILURE": (
        FailureClass.DETERMINISTIC_SCIENTIFIC_ENGINE_FAILURE
    ),
    "WORKFLOW_CANCELLED": FailureClass.WORKFLOW_OR_JOB_CANCELLED,
    "WORKFLOW_CANCELED": FailureClass.WORKFLOW_OR_JOB_CANCELLED,
    "JOB_CANCELLED": FailureClass.WORKFLOW_OR_JOB_CANCELLED,
    "JOB_CANCELED": FailureClass.WORKFLOW_OR_JOB_CANCELLED,
    "CANCELLED": FailureClass.WORKFLOW_OR_JOB_CANCELLED,
    "CANCELED": FailureClass.WORKFLOW_OR_JOB_CANCELLED,
}


class RecoveryMatrixTooLarge(RuntimeError):
    """Raised before recovery descriptors exceed GitHub output limits."""


class RecoveryEvidenceError(RuntimeError):
    """Raised when recovery evidence is missing, ambiguous, or inconsistent."""


def _load_recovery_spec(path: Path) -> Mapping[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("recovery spec must be a YAML mapping")
    return payload


class RecoveryPlan(RecoveryPlanContract):
    """Closed recovery plan with stable scoped-failure accounting."""

    failure_occurrence_count: int = 0
    failure_history_manifest_sha256: str = "0" * 64
    failure_fingerprints: tuple[str, ...] = ()
    identical_duplicate_success_count: int = 0


class CheckpointSlotEvidence(FrozenModel):
    logical_scope_id: str
    slot_index: int
    slot_count: int
    artifact_name: str
    previous_receipt_sha256: str
    receipt_sha256: str
    artifact_uploaded: bool


class CheckpointChainSelection(FrozenModel):
    logical_scope_id: str
    completed_slot_count: int
    next_slot_index: int | None
    latest_receipt_sha256: str
    reused_artifacts: tuple[str, ...]
    chain_manifest_sha256: str


class ArtifactInventoryReceipt(FrozenModel):
    expected: tuple[str, ...]
    observed: tuple[str, ...]
    download_outcome: str
    receipt_sha256: str


class RetryTimingDecision(FrozenModel):
    action: Literal["retry_now", "waiting_retry", "blocked"]
    retry_not_before: datetime | None
    delay_seconds: int
    reason_code: str


class AuthorityRecoverySnapshot(FrozenModel):
    authority_id: str
    request_issue_number: int
    state: Literal["reserved", "running", "recovering", "waiting_retry"]
    retry_not_before: datetime | None
    owner_run_state: Literal[
        "queued",
        "in_progress",
        "completed",
        "missing",
        "ambiguous",
        "cancelled",
    ]
    latest_failure_class: FailureClass
    engine_started: bool
    valid_checkpoint_count: int
    evidence_complete: bool
    current_protocol_sha256: str
    authority_protocol_sha256: str
    external_cancellation_proven_transient: bool


class WatchdogRecoveryDecision(FrozenModel):
    action: Literal["noop", "call_controller", "blocked"]
    issue_numbers: tuple[int, ...]
    authority_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NORMALIZED_TOKEN = re.compile(r"[^A-Za-z0-9]+")


def _normalized_token(value: object, *, uppercase: bool) -> str:
    normalized = _NORMALIZED_TOKEN.sub("_", str(value).strip()).strip("_")
    normalized = normalized or "UNKNOWN"
    return normalized.upper() if uppercase else normalized.lower()


def _normalized_repository_frame(value: object) -> str | None:
    if value is None:
        return None
    frame = str(value).strip().replace("\\", "/")
    lowered = frame.casefold()
    marker = "aurora/"
    offset = lowered.rfind(marker)
    if offset >= 0:
        frame = frame[offset:]
    return frame.casefold()


def failure_fingerprint(
    *,
    failure_class: FailureClass,
    reason_code: str,
    stage: str,
    logical_scope_id: str,
    exit_code: int | None = None,
    exception_type: str | None = None,
    normalized_frame: str | None = None,
    message: str | None = None,
) -> str:
    """Hash only stable scoped failure identity; dynamic message noise is ignored."""

    del message
    scope = str(logical_scope_id).strip()
    if not scope:
        raise ValueError("FAILURE_LOGICAL_SCOPE_ID_REQUIRED")
    payload = {
        "schema_version": "catalog-failure-fingerprint-v1",
        "failure_class": str(failure_class),
        "reason_code": _normalized_token(reason_code, uppercase=True),
        "stage": _normalized_token(stage, uppercase=False),
        "logical_scope_id": scope,
        "exit_code": int(exit_code) if exit_code is not None else None,
        "exception_type": (
            _normalized_token(exception_type, uppercase=False)
            if exception_type
            else None
        ),
        "normalized_frame": _normalized_repository_frame(normalized_frame),
    }
    return canonical_sha256(payload)


def validate_checkpoint_slot_chain(
    slots: Sequence[CheckpointSlotEvidence],
    *,
    logical_scope_id: str,
    expected_slot_count: int,
) -> CheckpointChainSelection:
    """Accept only one contiguous, uploaded, hash-linked checkpoint prefix."""

    if expected_slot_count not in {1, 2, 4, 8}:
        raise RecoveryEvidenceError("RECOVERY_CHECKPOINT_SLOT_COUNT_INVALID")
    ordered = tuple(sorted(slots, key=lambda item: item.slot_index))
    if not ordered:
        return CheckpointChainSelection(
            logical_scope_id=logical_scope_id,
            completed_slot_count=0,
            next_slot_index=1,
            latest_receipt_sha256="0" * 64,
            reused_artifacts=(),
            chain_manifest_sha256=canonical_sha256([]),
        )
    if len({item.slot_index for item in ordered}) != len(ordered):
        raise RecoveryEvidenceError("RECOVERY_CHECKPOINT_SLOT_DUPLICATE")
    previous = "0" * 64
    manifest: list[dict[str, object]] = []
    for expected_index, slot in enumerate(ordered, start=1):
        if (
            slot.logical_scope_id != logical_scope_id
            or slot.slot_count != expected_slot_count
            or slot.slot_index != expected_index
            or not slot.artifact_uploaded
            or not _SHA256.fullmatch(slot.previous_receipt_sha256)
            or not _SHA256.fullmatch(slot.receipt_sha256)
            or slot.previous_receipt_sha256 != previous
            or not slot.artifact_name
        ):
            raise RecoveryEvidenceError("RECOVERY_CHECKPOINT_CHAIN_INVALID")
        manifest.append(
            {
                "slot_index": slot.slot_index,
                "artifact_name": slot.artifact_name,
                "previous_receipt_sha256": slot.previous_receipt_sha256,
                "receipt_sha256": slot.receipt_sha256,
            }
        )
        previous = slot.receipt_sha256
    if len(ordered) > expected_slot_count:
        raise RecoveryEvidenceError("RECOVERY_CHECKPOINT_CHAIN_INVALID")
    return CheckpointChainSelection(
        logical_scope_id=logical_scope_id,
        completed_slot_count=len(ordered),
        next_slot_index=(
            len(ordered) + 1 if len(ordered) < expected_slot_count else None
        ),
        latest_receipt_sha256=previous,
        reused_artifacts=tuple(item.artifact_name for item in ordered),
        chain_manifest_sha256=canonical_sha256(manifest),
    )


def reconcile_expected_artifacts(
    *,
    expected: Sequence[str],
    observed: Sequence[str],
    download_outcome: str,
) -> ArtifactInventoryReceipt:
    """Prove an exact artifact set after every optional-pattern download."""

    expected_set = tuple(sorted(str(item) for item in expected))
    observed_set = tuple(sorted(str(item) for item in observed))
    if (
        len(expected_set) != len(set(expected_set))
        or len(observed_set) != len(set(observed_set))
        or any(not item or "/" in item or "\\" in item for item in expected_set)
        or any(not item or "/" in item or "\\" in item for item in observed_set)
    ):
        raise RecoveryEvidenceError("RECOVERY_ARTIFACT_SET_INVALID")
    normalized_outcome = str(download_outcome).casefold()
    if normalized_outcome not in {"success", "skipped"}:
        raise RecoveryEvidenceError("RECOVERY_ARTIFACT_DOWNLOAD_FAILED")
    if normalized_outcome == "skipped" and expected_set:
        raise RecoveryEvidenceError("RECOVERY_ARTIFACT_DOWNLOAD_SKIPPED")
    if expected_set != observed_set:
        raise RecoveryEvidenceError("RECOVERY_ARTIFACT_SET_MISMATCH")
    payload = {
        "schema_version": "catalog-recovery-artifact-inventory-v1",
        "expected": expected_set,
        "observed": observed_set,
        "download_outcome": normalized_outcome,
    }
    return ArtifactInventoryReceipt(
        expected=expected_set,
        observed=observed_set,
        download_outcome=normalized_outcome,
        receipt_sha256=canonical_sha256(payload),
    )


def plan_retry_timing(
    *,
    now: datetime,
    failure_occurrence_count: int,
    retry_after_seconds: int | None = None,
    rate_limit_reset: datetime | None = None,
) -> RetryTimingDecision:
    """Choose bounded immediate retry or durable waiting without runner sleep."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("RECOVERY_NOW_MUST_BE_TIMEZONE_AWARE")
    if failure_occurrence_count < 1:
        raise ValueError("RECOVERY_FAILURE_OCCURRENCE_INVALID")
    if failure_occurrence_count >= 3:
        return RetryTimingDecision(
            action="blocked",
            retry_not_before=None,
            delay_seconds=0,
            reason_code="SAME_FAILURE_OCCURRENCE_LIMIT",
        )
    fallback = 30 * (2 ** (failure_occurrence_count - 1))
    candidates = [fallback]
    if retry_after_seconds is not None:
        candidates.append(max(0, min(int(retry_after_seconds), 86_400)))
    if rate_limit_reset is not None:
        if rate_limit_reset.tzinfo is None or rate_limit_reset.utcoffset() is None:
            raise ValueError("RECOVERY_RATE_LIMIT_RESET_INVALID")
        candidates.append(
            max(0, min(int((rate_limit_reset - now).total_seconds()), 86_400))
        )
    delay = max(candidates)
    if delay > 60:
        return RetryTimingDecision(
            action="waiting_retry",
            retry_not_before=now.astimezone(UTC) + timedelta(seconds=delay),
            delay_seconds=delay,
            reason_code="RETRY_DELAY_REQUIRES_WATCHDOG",
        )
    return RetryTimingDecision(
        action="retry_now",
        retry_not_before=None,
        delay_seconds=delay,
        reason_code="BOUNDED_RETRY_ALLOWED",
    )


def decide_watchdog_reentry(
    authorities: Sequence[AuthorityRecoverySnapshot],
    *,
    now: datetime,
    claimed_authority_ids: Sequence[str] = (),
) -> WatchdogRecoveryDecision:
    """Select existing resumable authorities; never create or steal authority."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("CATALOG_WATCHDOG_NOW_INVALID")
    if not authorities:
        return WatchdogRecoveryDecision(
            action="noop", issue_numbers=(), authority_ids=(), reason_codes=()
        )
    claimed = set(claimed_authority_ids)
    selected: list[AuthorityRecoverySnapshot] = []
    for authority in sorted(authorities, key=lambda item: item.authority_id):
        if authority.authority_id in claimed:
            continue
        if not authority.evidence_complete or authority.owner_run_state in {
            "missing",
            "ambiguous",
        }:
            return WatchdogRecoveryDecision(
                action="blocked",
                issue_numbers=(),
                authority_ids=(authority.authority_id,),
                reason_codes=("CATALOG_WATCHDOG_EVIDENCE_AMBIGUOUS",),
            )
        if (
            authority.current_protocol_sha256
            != authority.authority_protocol_sha256
        ):
            return WatchdogRecoveryDecision(
                action="blocked",
                issue_numbers=(),
                authority_ids=(authority.authority_id,),
                reason_codes=("CATALOG_RECOVERY_PROTOCOL_MISMATCH",),
            )
        if authority.owner_run_state in {"queued", "in_progress"}:
            continue
        if authority.owner_run_state == "cancelled" and not (
            authority.external_cancellation_proven_transient
        ):
            return WatchdogRecoveryDecision(
                action="blocked",
                issue_numbers=(),
                authority_ids=(authority.authority_id,),
                reason_codes=("BLOCKED_EXTERNAL_INTERVENTION",),
            )
        if (
            authority.state == "waiting_retry"
            and authority.retry_not_before is not None
            and now < authority.retry_not_before
        ):
            continue
        resumable = (
            authority.state == "reserved" and not authority.engine_started
        ) or (
            authority.state in {"running", "recovering", "waiting_retry"}
            and authority.engine_started
            and authority.valid_checkpoint_count > 0
            and authority.latest_failure_class in TRANSIENT_CLASSES | REPLAN_CLASSES
        )
        if resumable:
            selected.append(authority)
    if not selected:
        return WatchdogRecoveryDecision(
            action="noop", issue_numbers=(), authority_ids=(), reason_codes=()
        )
    return WatchdogRecoveryDecision(
        action="call_controller",
        issue_numbers=tuple(item.request_issue_number for item in selected),
        authority_ids=tuple(item.authority_id for item in selected),
        reason_codes=(),
    )


def classify_failure(payload: Mapping[str, Any]) -> FailureClass:
    reason = str(
        payload.get("reason_code")
        or payload.get("reason")
        or payload.get("conclusion")
        or ""
    ).upper()
    return REASON_CLASS.get(reason, FailureClass.UNKNOWN)


def _attempt_number(attempt_id: str) -> tuple[int, str]:
    digits = "".join(character for character in attempt_id if character.isdigit())
    return (int(digits) if digits else -1, attempt_id)


def _new_attempt_id(fingerprint: str, occurrence: int) -> str:
    return f"recovery-{occurrence + 1}-{fingerprint[:20]}"


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
    *,
    fingerprint: str,
    occurrence: int,
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
        "failure_fingerprint": fingerprint,
        "failure_occurrence_count": occurrence,
        "resume_completed_unit_count": (
            checkpoint.completed_unit_count if checkpoint is not None else 0
        ),
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
    failure_history: list[dict[str, object]] = []
    maximum_occurrence = 0
    identical_duplicate_success_count = 0
    for shard in ordered_shards:
        shard_attempts = sorted(
            attempts_by_shard.get(shard.shard_id, []),
            key=lambda item: _attempt_number(item.attempt_id),
        )
        completed_attempts = tuple(
            item
            for item in shard_attempts
            if item.state is TerminalState.COMPLETED
        )
        if completed_attempts:
            output_hashes = {item.output_sha256 for item in completed_attempts}
            if len(output_hashes) != 1:
                raise RecoveryEvidenceError(
                    f"RECOVERY_CONFLICTING_SUCCESS:{shard.shard_id}"
                )
            identical_duplicate_success_count += max(
                0, len(completed_attempts) - 1
            )
            continue
        if shard_attempts:
            prior = shard_attempts[-1]
            reason = prior.reason_code or "DETERMINISTIC_CODE_ERROR"
            failure_class = classify_failure({"reason_code": reason})
            prior_attempt_id = prior.attempt_id
        else:
            reason = "RECOVERY_FAILURE_EVIDENCE_MISSING"
            failure_class = FailureClass.UNKNOWN
            prior_attempt_id = "missing"
        fingerprint = failure_fingerprint(
            failure_class=failure_class,
            reason_code=reason,
            stage="recipe_worker",
            logical_scope_id=shard.shard_id,
        )
        same_failure_occurrences = sum(
            failure_fingerprint(
                failure_class=classify_failure(
                    {"reason_code": attempt.reason_code or "UNKNOWN"}
                ),
                reason_code=attempt.reason_code or "UNKNOWN",
                stage="recipe_worker",
                logical_scope_id=shard.shard_id,
            )
            == fingerprint
            for attempt in shard_attempts
            if attempt.state is TerminalState.FAILED_TECHNICAL
        )
        maximum_occurrence = max(maximum_occurrence, same_failure_occurrences)
        failure_history.append(
            {
                "logical_scope_id": shard.shard_id,
                "failure_fingerprint": fingerprint,
                "occurrence_count": same_failure_occurrences,
            }
        )
        checkpoint = _best_checkpoint(shard.shard_id, checkpoints)
        if failure_class in TRANSIENT_CLASSES:
            budget = min(2, max(0, int(retry_policy.get(failure_class.value, 0))))
            if same_failure_occurrences >= 3:
                decision = RecoveryDecision(
                    shard_id=shard.shard_id,
                    prior_attempt_id=prior_attempt_id,
                    action="do_not_retry",
                    failure_class=failure_class.value,
                    next_attempt_id=None,
                    checkpoint_artifact=None,
                    reason_code="SAME_FAILURE_OCCURRENCE_LIMIT",
                )
            elif same_failure_occurrences > budget:
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
                next_attempt = _new_attempt_id(
                    fingerprint,
                    same_failure_occurrences,
                )
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
                    _retry_descriptor(
                        shard,
                        next_attempt,
                        checkpoint,
                        fingerprint=fingerprint,
                        occurrence=same_failure_occurrences,
                    )
                )
                if checkpoint is not None:
                    selected_checkpoint_artifacts.add(
                        checkpoint.artifact_name
                    )
        elif failure_class in REPLAN_CLASSES:
            if same_failure_occurrences >= 3:
                decision = RecoveryDecision(
                    shard_id=shard.shard_id,
                    prior_attempt_id=prior_attempt_id,
                    action="do_not_retry",
                    failure_class=failure_class.value,
                    next_attempt_id=None,
                    checkpoint_artifact=None,
                    reason_code="SAME_FAILURE_OCCURRENCE_LIMIT",
                )
            else:
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
            blocked_reason = (
                "BLOCKED_EXTERNAL_INTERVENTION"
                if failure_class is FailureClass.WORKFLOW_OR_JOB_CANCELLED
                else reason
            )
            decision = RecoveryDecision(
                shard_id=shard.shard_id,
                prior_attempt_id=prior_attempt_id,
                action="do_not_retry",
                failure_class=failure_class.value,
                next_attempt_id=None,
                checkpoint_artifact=None,
                reason_code=blocked_reason,
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
    history_sha256 = canonical_sha256(
        sorted(
            failure_history,
            key=lambda item: (
                str(item["logical_scope_id"]),
                str(item["failure_fingerprint"]),
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
        "failure_occurrence_count": maximum_occurrence,
        "failure_history_manifest_sha256": history_sha256,
        "failure_fingerprints": tuple(
            sorted(
                {
                    str(item["failure_fingerprint"])
                    for item in failure_history
                }
            )
        ),
        "identical_duplicate_success_count": (
            identical_duplicate_success_count
        ),
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
    shards_by_id = {shard.shard_id: shard for shard in ordered_shards}
    terminal_attempts_by_shard: dict[str, list[AttemptManifest]] = (
        defaultdict(list)
    )
    for attempt in attempts:
        if (
            attempt.state in terminal_states
            and attempt.shard_id in shards_by_id
            and attempt.artifact_name is not None
        ):
            terminal_attempts_by_shard[attempt.shard_id].append(attempt)
    selected_terminal_attempts = tuple(
        min(
            terminal_attempts_by_shard[shard_id],
            key=lambda item: (
                item.attempt_id,
                item.output_sha256 or "",
                item.artifact_name or "",
            ),
        )
        for shard_id in sorted(terminal_attempts_by_shard)
    )
    terminal_shards = {
        attempt.shard_id for attempt in selected_terminal_attempts
    }
    terminal_unit_count = sum(
        shards_by_id[shard_id].unit_count for shard_id in terminal_shards
    )
    terminal_evidence = [
        {
            "shard_id": attempt.shard_id,
            "attempt_id": attempt.attempt_id,
            "state": attempt.state.value,
            "artifact_name": attempt.artifact_name,
            "output_sha256": attempt.output_sha256,
            "unit_attempts_sha256": attempt.unit_attempts_sha256,
            "completed_unit_count": attempt.completed_unit_count,
        }
        for attempt in selected_terminal_attempts
    ]
    terminal_unit_manifest_sha256 = (
        canonical_sha256(terminal_evidence)
        if terminal_evidence
        else None
    )
    verified_source_artifacts = tuple(
        sorted(
            attempt.artifact_name
            for attempt in selected_terminal_attempts
            if attempt.artifact_name is not None
        )
    )
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
        status = RecoveryLoopStatus.BLOCKED_HARD_FAILURE
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
        decision.failure_class
        == FailureClass.DETERMINISTIC_SCIENTIFIC_ENGINE_FAILURE.value
        for decision in do_not_retry
    ):
        status = RecoveryLoopStatus.FAILED_SCIENTIFIC
        next_wave = None
        reasons = tuple(
            dict.fromkeys(decision.reason_code for decision in do_not_retry)
        )
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
        terminal_unit_count=terminal_unit_count,
        terminal_unit_manifest_sha256=terminal_unit_manifest_sha256,
        verified_source_artifacts=verified_source_artifacts,
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
    max_output_bytes: int = 524_288,
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
    matrix_output_bytes = len(compact_a.encode("utf-16-le")) + len(
        compact_b.encode("utf-16-le")
    )
    if matrix_output_bytes > max_output_bytes:
        raise RecoveryMatrixTooLarge(
            "recovery matrix UTF-16 outputs exceed 524288 bytes"
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


def build_terminal_unit_evidence_from_paths(
    attempt_paths: Sequence[Path],
    unit_attempt_paths: Sequence[Path],
    checkpoint_paths: Sequence[Path] = (),
) -> TerminalUnitEvidence:
    """Verify unit manifests and select one immutable terminal result per key."""

    attempts = tuple(
        attempt
        for path in attempt_paths
        for attempt in _load_attempt(Path(path))
    )
    attempts_by_identity = {
        (attempt.shard_id, attempt.attempt_id): attempt
        for attempt in attempts
    }
    if len(attempts_by_identity) != len(attempts):
        raise ValueError("duplicate shard attempt evidence")
    grouped: dict[str, list[UnitAttemptRecord]] = defaultdict(list)
    terminal_states = {
        TerminalState.COMPLETED,
        TerminalState.RIGHT_CENSORED,
        TerminalState.UNSUPPORTED,
    }
    loaded_files: list[
        tuple[Path, AttemptManifest, tuple[UnitAttemptRecord, ...]]
    ] = []
    for raw_path in unit_attempt_paths:
        path = Path(raw_path)
        observed_sha256 = sha256_file(path)
        carriers = tuple(
            attempt
            for attempt in attempts
            if attempt.unit_attempts_sha256 == observed_sha256
        )
        if len(carriers) != 1:
            raise ValueError("unit attempt manifest hash mismatch")
        rows = tuple(
            UnitAttemptRecord.model_validate(row)
            for row in pq.read_table(path).to_pylist()
        )
        loaded_files.append((path, carriers[0], rows))

    directly_bound_rows: dict[
        tuple[str, str],
        set[tuple[str, str, str | None, str | None]],
    ] = defaultdict(set)
    for _, carrier, rows in loaded_files:
        for row in rows:
            identity = (row.shard_id, row.attempt_id)
            if identity == (carrier.shard_id, carrier.attempt_id):
                directly_bound_rows[identity].add(
                    _unit_attempt_signature(row)
                )
    for raw_path in checkpoint_paths:
        path = Path(raw_path)
        try:
            checkpoint = load_checkpoint(path)
        except CheckpointIntegrityError:
            continue
        payload = pq.read_table(
            path.parent / checkpoint.payload_path,
            columns=[
                "unit_key",
                "source_attempt_id",
                "unit_output_sha256",
            ],
        )
        if payload.num_rows != checkpoint.completed_unit_count:
            raise ValueError("checkpoint completed-unit count mismatch")
        for item in payload.to_pylist():
            if item["source_attempt_id"] != checkpoint.attempt_id:
                continue
            directly_bound_rows[
                (checkpoint.shard_id, checkpoint.attempt_id)
            ].add(
                (
                    str(item["unit_key"]),
                    TerminalState.COMPLETED.value,
                    str(item["unit_output_sha256"]),
                    None,
                )
            )

    for path, carrier, rows in loaded_files:
        carrier_identity = (carrier.shard_id, carrier.attempt_id)
        for row in rows:
            identity = (row.shard_id, row.attempt_id)
            manifest = attempts_by_identity.get(identity)
            if manifest is None:
                raise ValueError(
                    "unit attempt evidence has no shard manifest: "
                    f"{identity[0]}/{identity[1]}"
                )
            if row.shard_id != carrier.shard_id:
                raise ValueError(
                    f"unit attempt file mixes shard identities: {path}"
                )
            if _attempt_scientific_identity(manifest) != (
                _attempt_scientific_identity(carrier)
            ):
                raise ValueError(
                    "resumed unit attempt crosses scientific identity"
                )
            if (
                identity != carrier_identity
                and _unit_attempt_signature(row)
                not in directly_bound_rows.get(identity, set())
            ):
                raise ValueError(
                    "resumed unit attempt row lacks independently bound "
                    f"source evidence: {row.unit_key}"
                )
            if row.state in terminal_states:
                grouped[row.unit_key].append(row)

    selected: list[UnitAttemptRecord] = []
    identical_duplicate_unit_keys: list[str] = []
    duplicate_attempt_ids: list[str] = []
    for unit_key in sorted(grouped):
        candidates = sorted(
            grouped[unit_key],
            key=lambda item: (item.attempt_id, item.shard_id),
        )
        completed = [
            item
            for item in candidates
            if item.state is TerminalState.COMPLETED
        ]
        if completed:
            digests = {item.output_sha256 for item in completed}
            if len(digests) != 1:
                raise ValueError(
                    f"conflicting completed output hashes for {unit_key}"
                )
            chosen = completed[0]
            if len(completed) > 1:
                identical_duplicate_unit_keys.append(unit_key)
                duplicate_attempt_ids.extend(
                    item.attempt_id for item in completed[1:]
                )
        else:
            chosen = candidates[-1]
        selected.append(chosen)

    payload = []
    source_artifacts: set[str] = set()
    for row in selected:
        manifest = attempts_by_identity[(row.shard_id, row.attempt_id)]
        if manifest.artifact_name is None:
            raise ValueError("terminal unit evidence has no source artifact")
        source_artifacts.add(manifest.artifact_name)
        payload.append(
            {
                "unit_key": row.unit_key,
                "shard_id": row.shard_id,
                "attempt_id": row.attempt_id,
                "state": row.state.value,
                "output_sha256": row.output_sha256,
                "reason_code": row.reason_code,
                "artifact_name": manifest.artifact_name,
                "unit_attempts_sha256": manifest.unit_attempts_sha256,
            }
        )
    return TerminalUnitEvidence(
        unit_keys=tuple(item["unit_key"] for item in payload),
        unit_count=len(payload),
        unit_manifest_sha256=(
            canonical_sha256(payload) if payload else None
        ),
        source_artifacts=tuple(sorted(source_artifacts)),
        identical_duplicate_unit_keys=tuple(identical_duplicate_unit_keys),
        duplicate_attempt_ids=tuple(sorted(duplicate_attempt_ids)),
    )


def _unit_attempt_signature(
    row: UnitAttemptRecord,
) -> tuple[str, str, str | None, str | None]:
    return (
        row.unit_key,
        row.state.value,
        row.output_sha256,
        row.reason_code,
    )


def _attempt_scientific_identity(
    attempt: AttemptManifest,
) -> tuple[str, str, str, str, str, str]:
    return (
        attempt.spec_hash,
        attempt.policy_hash,
        attempt.snapshot_hash,
        attempt.code_sha,
        attempt.dependency_lock_sha256,
        attempt.capacity_profile_sha256,
    )


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
    spec = _load_recovery_spec(Path(spec_path))
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
    unit_attempt_paths: Sequence[Path] = (),
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
    spec = _load_recovery_spec(Path(spec_path))
    retry_policy = spec.get("retries", {})
    if not isinstance(retry_policy, Mapping):
        raise ValueError("spec.retries must be a mapping")
    result = build_recovery_loop(
        shard_plan.shards,
        attempts,
        tuple(checkpoints_list),
        retry_policy,
        current_wave=current_wave,
        max_waves=max_waves,
        checkpoint_audit=tuple(checkpoint_audit),
    )
    if not unit_attempt_paths:
        return result
    evidence = build_terminal_unit_evidence_from_paths(
        attempt_paths,
        unit_attempt_paths,
        checkpoint_paths,
    )
    expected_units = sum(shard.unit_count for shard in shard_plan.shards)
    if (
        result.status is RecoveryLoopStatus.COMPLETE
        and evidence.unit_count != expected_units
    ):
        raise ValueError(
            "complete recovery lacks terminal evidence for every work unit"
        )
    return result.model_copy(
        update={
            "terminal_unit_count": evidence.unit_count,
            "terminal_unit_manifest_sha256": (
                evidence.unit_manifest_sha256
            ),
            "verified_source_artifacts": evidence.source_artifacts,
        }
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
