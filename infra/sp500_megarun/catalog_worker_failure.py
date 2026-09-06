"""Sealed worker-failure evidence and closed recovery decisions."""

from __future__ import annotations

import errno
import hashlib
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    canonical_sha256,
)
from aurora.infra.github_performance.recovery import (
    FailureClass,
    REPLAN_CLASSES,
    TRANSIENT_CLASSES,
    classify_failure,
    failure_fingerprint,
    plan_retry_timing,
)


_ALLOWED_REASON_CODES = frozenset(
    {
        "ARTIFACT_UPLOAD_FAILED",
        "CONNECTION_RESET",
        "DETERMINISTIC_CODE_ERROR",
        "DISK_EXHAUSTED",
        "GITHUB_5XX",
        "INPUT_HASH_MISMATCH",
        "INTEGRITY_ERROR",
        "NETWORK_TIMEOUT",
        "OUT_OF_MEMORY",
        "POLICY_VIOLATION",
        "PROVIDER_429",
        "RUNNER_LOST",
        "SCHEMA_MISMATCH",
        "SCIENTIFIC_ENGINE_EXPECTED_FAILURE",
        "UNKNOWN_WORKER_FAILURE",
        "WORKFLOW_CANCELLED",
    }
)
_ALLOWED_STAGES = frozenset(
    {
        "checkpoint_upload",
        "input_download",
        "recipe_worker",
        "runtime_assembly",
        "setup",
        "terminal_manifest",
    }
)


def worker_failure_artifact_name(
    *,
    execution_plan_sha256: str,
    worker_id: int,
    attempt_id: str,
) -> str:
    """Return a unique immutable artifact name for one failed attempt."""

    attempt_sha256 = hashlib.sha256(attempt_id.encode("utf-8")).hexdigest()
    return (
        f"catalog-failure-attempt-{execution_plan_sha256[:16]}-"
        f"{worker_id:03d}-{attempt_sha256[:16]}"
    )


class CatalogWorkerFailureReceiptV1(FrozenModel):
    schema_version: Literal["catalog-worker-failure-v1"] = (
        "catalog-worker-failure-v1"
    )
    authority_id: str = Field(min_length=1, max_length=96)
    campaign_id: str = Field(min_length=1, max_length=96)
    execution_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    worker_id: int = Field(ge=0, le=359)
    attempt_id: str = Field(min_length=1, max_length=220)
    stage: str = Field(min_length=1, max_length=40)
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,95}$")
    failure_class: FailureClass
    failure_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    exit_code: int | None = Field(default=None, ge=0, le=255)
    exception_type: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z_][A-Za-z0-9_.]{0,127}$",
    )
    normalized_frame: str | None = Field(default=None, max_length=240)
    source_error_code: str | None = Field(
        default=None,
        pattern=r"^[A-Z][A-Z0-9_]{2,127}$",
    )
    retry_after_seconds: int | None = Field(default=None, ge=0, le=86_400)
    rate_limit_reset: datetime | None = None
    created_at: datetime
    validation_opened: Literal[False] = False
    locked_opened: Literal[False] = False
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("stage")
    @classmethod
    def _validate_stage(cls, value: str) -> str:
        if value not in _ALLOWED_STAGES:
            raise ValueError("CATALOG_WORKER_FAILURE_STAGE_INVALID")
        return value

    @field_validator("reason_code")
    @classmethod
    def _validate_reason_code(cls, value: str) -> str:
        if value not in _ALLOWED_REASON_CODES:
            raise ValueError("CATALOG_WORKER_FAILURE_REASON_INVALID")
        return value

    @field_validator("created_at", "rate_limit_reset")
    @classmethod
    def _validate_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("CATALOG_WORKER_FAILURE_TIME_INVALID")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _validate_identity(self) -> "CatalogWorkerFailureReceiptV1":
        if not self.attempt_id.startswith(
            f"{self.authority_id}:worker:{self.worker_id:03d}:"
        ):
            raise ValueError("CATALOG_WORKER_FAILURE_ATTEMPT_INVALID")
        expected_class = classify_failure({"reason_code": self.reason_code})
        if self.failure_class is not expected_class:
            raise ValueError("CATALOG_WORKER_FAILURE_CLASS_INVALID")
        expected_fingerprint = failure_fingerprint(
            failure_class=self.failure_class,
            reason_code=self.reason_code,
            stage=self.stage,
            logical_scope_id=f"worker:{self.worker_id}",
            exit_code=self.exit_code,
            exception_type=self.exception_type,
            normalized_frame=self.normalized_frame,
        )
        if self.failure_fingerprint != expected_fingerprint:
            raise ValueError("CATALOG_WORKER_FAILURE_FINGERPRINT_INVALID")
        payload = self.model_dump(mode="python", exclude={"receipt_sha256"})
        if canonical_sha256(payload) != self.receipt_sha256:
            raise ValueError("CATALOG_WORKER_FAILURE_HASH_INVALID")
        return self


class CatalogWorkerRecoveryDecisionV1(FrozenModel):
    worker_id: int = Field(ge=0, le=359)
    action: Literal[
        "complete",
        "retry",
        "replan",
        "waiting_retry",
        "failed_scientific",
        "blocked",
    ]
    reason_code: str
    failure_class: FailureClass | None
    failure_fingerprint: str | None
    failure_occurrence_count: int = Field(ge=0, le=3)
    retry_not_before: datetime | None


class CatalogWorkerRecoveryPlanV1(FrozenModel):
    status: Literal[
        "complete",
        "retry",
        "replan",
        "waiting_retry",
        "failed_scientific",
        "blocked",
    ]
    decisions: tuple[CatalogWorkerRecoveryDecisionV1, ...]
    failure_fingerprint: str | None
    failure_occurrence_count: int = Field(ge=0, le=3)
    failure_reason_code: str | None
    retry_not_before: datetime | None
    failure_history_manifest_sha256: str


def build_catalog_worker_failure_receipt(
    *,
    authority_id: str,
    campaign_id: str,
    execution_plan_sha256: str,
    protected_commit_sha: str,
    worker_id: int,
    attempt_id: str,
    stage: str,
    reason_code: str,
    exit_code: int | None = None,
    exception_type: str | None = None,
    normalized_frame: str | None = None,
    source_error_code: str | None = None,
    retry_after_seconds: int | None = None,
    rate_limit_reset: datetime | None = None,
    created_at: datetime | None = None,
) -> CatalogWorkerFailureReceiptV1:
    failure_class = classify_failure({"reason_code": reason_code})
    fingerprint = failure_fingerprint(
        failure_class=failure_class,
        reason_code=reason_code,
        stage=stage,
        logical_scope_id=f"worker:{worker_id}",
        exit_code=exit_code,
        exception_type=exception_type,
        normalized_frame=normalized_frame,
    )
    payload = {
        "schema_version": "catalog-worker-failure-v1",
        "authority_id": authority_id,
        "campaign_id": campaign_id,
        "execution_plan_sha256": execution_plan_sha256,
        "protected_commit_sha": protected_commit_sha,
        "worker_id": worker_id,
        "attempt_id": attempt_id,
        "stage": stage,
        "reason_code": reason_code,
        "failure_class": failure_class,
        "failure_fingerprint": fingerprint,
        "exit_code": exit_code,
        "exception_type": exception_type,
        "normalized_frame": normalized_frame,
        "source_error_code": source_error_code,
        "retry_after_seconds": retry_after_seconds,
        "rate_limit_reset": rate_limit_reset,
        "created_at": (created_at or datetime.now(UTC)).astimezone(UTC),
        "validation_opened": False,
        "locked_opened": False,
    }
    payload["receipt_sha256"] = canonical_sha256(payload)
    return CatalogWorkerFailureReceiptV1.model_validate(payload)


def _source_code(exc: BaseException) -> str | None:
    if not isinstance(exc, SystemExit) or not isinstance(exc.code, str):
        return None
    normalized = exc.code.strip().upper()
    if not normalized or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
        for character in normalized
    ):
        return None
    return normalized[:128]


def classify_worker_exception(exc: BaseException) -> tuple[str, int, str]:
    """Map a caught in-process failure to the protected closed reason set."""

    exception_type = type(exc).__name__
    if isinstance(exc, MemoryError):
        return "OUT_OF_MEMORY", 1, exception_type
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return "DISK_EXHAUSTED", 1, exception_type
    if isinstance(exc, ConnectionResetError):
        return "CONNECTION_RESET", 1, exception_type
    if isinstance(exc, TimeoutError):
        return "NETWORK_TIMEOUT", 1, exception_type
    source = _source_code(exc)
    if source is not None:
        if "POLICY" in source:
            return "POLICY_VIOLATION", 1, exception_type
        if "SCHEMA" in source:
            return "SCHEMA_MISMATCH", 1, exception_type
        if any(
            token in source
            for token in (
                "BINDING",
                "CHAIN",
                "HASH",
                "INTEGRITY",
                "MANIFEST",
            )
        ):
            return "INTEGRITY_ERROR", 1, exception_type
        if any(token in source for token in ("INCOMPLETE", "MISSING", "UNKNOWN")):
            return "INPUT_HASH_MISMATCH", 1, exception_type
    code = exc.code if isinstance(exc, SystemExit) else 1
    exit_code = code if isinstance(code, int) and 0 <= code <= 255 else 1
    return "DETERMINISTIC_CODE_ERROR", exit_code, exception_type


def normalized_exception_frame(exc: BaseException) -> str | None:
    traceback = exc.__traceback__
    if traceback is None:
        return None
    while traceback.tb_next is not None:
        traceback = traceback.tb_next
    frame = traceback.tb_frame
    path = Path(frame.f_code.co_filename).as_posix()
    lowered = path.casefold()
    for marker in ("/aurora/", "/infra/", "/scripts/"):
        if marker in lowered:
            offset = lowered.rfind(marker) + 1
            path = path[offset:]
            break
    else:
        path = Path(path).name
    return f"{path}:{frame.f_code.co_name}"[:240]


def decide_catalog_worker_recovery(
    *,
    expected_worker_ids: Sequence[int],
    completed_worker_ids: Sequence[int],
    failure_receipts: Iterable[CatalogWorkerFailureReceiptV1],
    current_wave: int,
    max_waves: int,
    now: datetime,
) -> CatalogWorkerRecoveryPlanV1:
    """Fail closed unless every pending worker has exact classified evidence."""

    expected = tuple(sorted(set(expected_worker_ids)))
    completed = set(completed_worker_ids)
    if expected != tuple(expected_worker_ids) or not completed.issubset(expected):
        raise ValueError("CATALOG_WORKER_RECOVERY_SCOPE_INVALID")
    if current_wave < 0 or max_waves < 1:
        raise ValueError("CATALOG_WORKER_RECOVERY_WAVE_INVALID")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("CATALOG_WORKER_RECOVERY_TIME_INVALID")
    grouped: dict[int, list[CatalogWorkerFailureReceiptV1]] = defaultdict(list)
    attempt_ids: set[str] = set()
    history: list[dict[str, object]] = []
    for receipt in failure_receipts:
        if (
            receipt.worker_id not in expected
            or receipt.attempt_id in attempt_ids
            or receipt.created_at > now.astimezone(UTC) + timedelta(seconds=30)
        ):
            raise ValueError("CATALOG_WORKER_FAILURE_HISTORY_INVALID")
        attempt_ids.add(receipt.attempt_id)
        grouped[receipt.worker_id].append(receipt)
        history.append(
            {
                "worker_id": receipt.worker_id,
                "attempt_id": receipt.attempt_id,
                "failure_fingerprint": receipt.failure_fingerprint,
                "reason_code": receipt.reason_code,
                "created_at": receipt.created_at,
            }
        )

    decisions: list[CatalogWorkerRecoveryDecisionV1] = []
    for worker_id in expected:
        if worker_id in completed:
            decisions.append(
                CatalogWorkerRecoveryDecisionV1(
                    worker_id=worker_id,
                    action="complete",
                    reason_code="WORKER_COMPLETED",
                    failure_class=None,
                    failure_fingerprint=None,
                    failure_occurrence_count=0,
                    retry_not_before=None,
                )
            )
            continue
        receipts = sorted(
            grouped.get(worker_id, ()),
            key=lambda item: (item.created_at, item.attempt_id),
        )
        if not receipts:
            decisions.append(
                CatalogWorkerRecoveryDecisionV1(
                    worker_id=worker_id,
                    action="blocked",
                    reason_code="RECOVERY_FAILURE_EVIDENCE_MISSING",
                    failure_class=FailureClass.UNKNOWN,
                    failure_fingerprint=None,
                    failure_occurrence_count=0,
                    retry_not_before=None,
                )
            )
            continue
        latest = receipts[-1]
        occurrence = sum(
            item.failure_fingerprint == latest.failure_fingerprint
            for item in receipts
        )
        occurrence = min(occurrence, 3)
        action: str
        reason = latest.reason_code
        retry_not_before = None
        if occurrence >= 3:
            action = "blocked"
            reason = "SAME_FAILURE_OCCURRENCE_LIMIT"
        elif len(receipts) >= 3:
            action = "blocked"
            reason = "WORKER_ATTEMPT_BUDGET_EXHAUSTED"
        elif current_wave >= max_waves:
            action = "blocked"
            reason = "RECOVERY_WAVE_BUDGET_EXHAUSTED"
        elif latest.failure_class in TRANSIENT_CLASSES:
            timing = plan_retry_timing(
                now=now,
                failure_occurrence_count=occurrence,
                retry_after_seconds=latest.retry_after_seconds,
                rate_limit_reset=latest.rate_limit_reset,
            )
            action = (
                "waiting_retry"
                if timing.action == "waiting_retry"
                else "retry"
            )
            reason = (
                timing.reason_code
                if action == "waiting_retry"
                else latest.reason_code
            )
            retry_not_before = timing.retry_not_before
        elif latest.failure_class in REPLAN_CLASSES:
            action = "replan"
        elif latest.failure_class is FailureClass.DETERMINISTIC_SCIENTIFIC_ENGINE_FAILURE:
            action = "failed_scientific"
        else:
            action = "blocked"
            if latest.failure_class is FailureClass.WORKFLOW_OR_JOB_CANCELLED:
                reason = "BLOCKED_EXTERNAL_INTERVENTION"
        decisions.append(
            CatalogWorkerRecoveryDecisionV1(
                worker_id=worker_id,
                action=action,
                reason_code=reason,
                failure_class=latest.failure_class,
                failure_fingerprint=latest.failure_fingerprint,
                failure_occurrence_count=occurrence,
                retry_not_before=retry_not_before,
            )
        )

    noncomplete = tuple(item for item in decisions if item.action != "complete")
    actions = {item.action for item in noncomplete}
    if not noncomplete:
        status = "complete"
    elif "blocked" in actions:
        status = "blocked"
    elif "failed_scientific" in actions:
        status = (
            "failed_scientific"
            if actions == {"failed_scientific"}
            else "blocked"
        )
    elif "waiting_retry" in actions:
        status = "waiting_retry"
    elif "replan" in actions:
        status = "replan"
    else:
        status = "retry"
    representative = max(
        noncomplete,
        key=lambda item: (
            item.failure_occurrence_count,
            item.worker_id,
        ),
        default=None,
    )
    retry_times = tuple(
        item.retry_not_before
        for item in noncomplete
        if item.retry_not_before is not None
    )
    reason = representative.reason_code if representative is not None else None
    if status == "blocked" and "failed_scientific" in actions and len(actions) > 1:
        reason = "MIXED_SCIENTIFIC_AND_TECHNICAL_FAILURES"
    return CatalogWorkerRecoveryPlanV1(
        status=status,
        decisions=tuple(decisions),
        failure_fingerprint=(
            representative.failure_fingerprint
            if representative is not None
            else None
        ),
        failure_occurrence_count=(
            representative.failure_occurrence_count
            if representative is not None
            else 0
        ),
        failure_reason_code=reason,
        retry_not_before=max(retry_times) if retry_times else None,
        failure_history_manifest_sha256=canonical_sha256(
            {
                "schema_version": "1",
                "failures": sorted(
                    history,
                    key=lambda item: (
                        int(item["worker_id"]),
                        item["created_at"],
                        str(item["attempt_id"]),
                    ),
                ),
            }
        ),
    )


__all__ = [
    "CatalogWorkerFailureReceiptV1",
    "CatalogWorkerRecoveryDecisionV1",
    "CatalogWorkerRecoveryPlanV1",
    "build_catalog_worker_failure_receipt",
    "classify_worker_exception",
    "decide_catalog_worker_recovery",
    "normalized_exception_frame",
    "worker_failure_artifact_name",
]
