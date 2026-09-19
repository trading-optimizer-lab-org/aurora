"""Closed reusable-workflow outcome for one catalog engine invocation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from .catalog_request_contract import FrozenModel, Sha256
from .catalog_sealed_plan import verify_sealed_global_reuse_execution_plan
from .catalog_worker_failure import CatalogWorkerFailureReceiptV1, TRANSIENT_CLASSES
from aurora.infra.github_performance.contracts import canonical_sha256


_RECOVERED_BINDINGS = (
    "request_sha256", "authority_id", "campaign_id", "science_sha256",
    "execution_plan_sha256", "execution_protocol_sha256", "protected_commit_sha",
    "engine_run_id", "engine_run_attempt",
)


@dataclass(frozen=True)
class RecoveredEvaluationEvidence:
    """Local verification result; transport provenance remains the caller's duty."""

    bindings: tuple[str, ...]
    stages: frozenset[str]
    science_index_sha256: str


def _recovery_document(path: Path) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate recovery evidence key")
            result[key] = value
        return result

    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("CATALOG_RECOVERED_EVIDENCE_FILE_INVALID")
    value = json.loads(path.read_text("utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
    if not isinstance(value, dict):
        raise ValueError("CATALOG_RECOVERED_EVIDENCE_DOCUMENT_INVALID")
    return value


def verify_recovered_evaluation_evidence(
    *, science_index: Path, sealed_plan: Path, failure_root: Path,
    expected: Mapping[str, Any],
) -> RecoveredEvaluationEvidence:
    """Verify same-run publications supplied by the protected workflow.

    Self hashes are integrity checks, not remote authentication. The CLI requires
    the current run/attempt; its caller must download these artifacts from that
    run's protected publishers, never from arbitrary user-selected runs.
    """
    invalid = "CATALOG_RECOVERED_EVALUATION_EVIDENCE_INVALID"
    bindings = {key: str(expected[key]) for key in _RECOVERED_BINDINGS[:7]}
    verify_sealed_global_reuse_execution_plan(sealed_plan, expected_bindings=bindings)
    index = _recovery_document(science_index)

    def check(document: Mapping[str, Any], hash_key: str) -> None:
        if (document.get(hash_key) != canonical_sha256({k: v for k, v in document.items() if k != hash_key})
                or any(str(document.get(k)) != v for k, v in bindings.items())
                or document.get("validation_opened") is not False
                or document.get("locked_opened") is not False):
            raise ValueError(invalid)

    check(index, "index_sha256")
    names = {"catalog_scientific_audit_receipt_v1.json", "catalog_equivalence_receipt_v1.json",
             "catalog_regression_receipt_v1.json"}
    files = index.get("files")
    if not isinstance(files, list) or len(files) != 3:
        raise ValueError(invalid)
    documents: dict[str, dict[str, Any]] = {}
    for row in files:
        if (not isinstance(row, dict) or set(row) != {"path", "size_bytes", "sha256"}
                or row["path"] not in names or row["path"] in documents):
            raise ValueError(invalid)
        path = science_index.parent / row["path"]
        document = _recovery_document(path)
        raw = path.read_bytes()
        if len(raw) != row["size_bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError(invalid)
        check(document, "receipt_sha256")
        documents[row["path"]] = document
    audit = documents["catalog_scientific_audit_receipt_v1.json"]
    equivalence = documents["catalog_equivalence_receipt_v1.json"]
    regression = documents["catalog_regression_receipt_v1.json"]
    logical = _recovery_document(sealed_plan / "logical_recipe_manifest.json")
    logical_payload = logical.get("payload", logical)
    ids = [row["strategy_id"] for row in logical_payload["recipes"]]
    count = len(ids)
    if (not count or len(set(ids)) != count or logical_payload["strategy_count"] != count
            or type(audit.get("strategy_count")) is not int or audit["strategy_count"] != count
            or audit.get("schemas_valid") is not True
            or equivalence.get("equivalent") is not True
            or equivalence.get("expected_count") != count or equivalence.get("observed_count") != count
            or equivalence.get("difference_count") != 0 or regression.get("no_regression") is not True
            or regression.get("equivalence_receipt_sha256") != equivalence["receipt_sha256"]):
        raise ValueError(invalid)
    policy = _recovery_document(sealed_plan / "checkpoint_policy.json")
    blocks = policy["recovery_blocks_v1"]["blocks"]
    expected_blocks = {row["block_id"] for row in blocks}
    metrics = audit.get("recovery_metrics")
    if not isinstance(metrics, dict) or metrics.get("schema_version") != "1":
        raise ValueError(invalid)
    verified, recovered = metrics.get("verified_block_ids"), metrics.get("recovered_block_ids")
    if (not isinstance(verified, list) or not isinstance(recovered, list)
            or any(not isinstance(item, str) for item in verified + recovered)
            or len(verified) != len(set(verified)) or len(recovered) != len(set(recovered))
            or set(verified) != expected_blocks or not recovered or not set(recovered) <= expected_blocks):
        raise ValueError(invalid)
    stages: set[str] = set()
    failed_workers: set[int] = set()
    if failure_root.is_symlink() or not failure_root.is_dir():
        raise ValueError(invalid)
    paths = sorted(failure_root.rglob("*.json"))
    if not paths or len(paths) > 360:
        raise ValueError(invalid)
    for path in paths:
        if any(parent.is_symlink() for parent in path.parents if parent != failure_root.parent):
            raise ValueError(invalid)
        failure = CatalogWorkerFailureReceiptV1.model_validate(_recovery_document(path))
        if (failure.failure_class not in TRANSIENT_CLASSES or failure.stage != "recipe_worker"
                or any(str(getattr(failure, key)) != bindings[key] for key in
                       ("authority_id", "campaign_id", "execution_plan_sha256", "protected_commit_sha"))
                or failure.attempt_id != f'{bindings["authority_id"]}:worker:{failure.worker_id:03d}:attempt:1'
                or failure.worker_id in failed_workers):
            raise ValueError(invalid)
        failed_workers.add(failure.worker_id)
        worker_blocks = {row["block_id"] for row in blocks if row["worker_id"] == failure.worker_id}
        if not worker_blocks or not worker_blocks <= set(recovered):
            raise ValueError(invalid)
        matched = []
        for suffix in "abc":
            matrix = _recovery_document(sealed_plan / f"recipe_matrix_{suffix}.json")
            if any(row["worker_id"] == failure.worker_id for row in matrix["include"]):
                matched.append(f"evaluate_{suffix}")
        if len(matched) != 1:
            raise ValueError(invalid)
        stages.add(matched[0])
    failed_stages = {key for key, value in expected["stage_results"].items()
                     if key in {"evaluate_a", "evaluate_b", "evaluate_c"} and value == "failure"}
    if stages != failed_stages:
        raise ValueError(invalid)
    return RecoveredEvaluationEvidence(tuple(str(expected[k]) for k in _RECOVERED_BINDINGS),
                                       frozenset(stages), index["index_sha256"])


SafeArtifactName = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,180}$"),
]
SafeReasonCode = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{2,95}$"),
]

_STAGE_RESULT = frozenset({"success", "failure", "cancelled", "skipped"})
_RECOVERY_STATUS = frozenset(
    {
        "retry",
        "replan",
        "complete",
        "blocked",
        "waiting_retry",
        "failed_scientific",
    }
)
_TERMINAL_STAGE_REASONS = (
    ("reduce", "CATALOG_REDUCTION_FAILED"),
    ("verify_terminal_science", "CATALOG_SCIENTIFIC_VERIFICATION_FAILED"),
    ("audit_runtime", "CATALOG_RUNTIME_AUDIT_FAILED"),
)
_CLOSED_SCIENTIFIC_FAILURES = frozenset(
    {
        "SCIENTIFIC_ENGINE_DETERMINISTIC_FAILURE",
        "SCIENTIFIC_INPUT_DOMAIN_EXHAUSTED",
    }
)


def _canonical_bytes(value: object) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        normalized = value.astimezone(UTC).isoformat()
        return normalized.replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


class CatalogEngineOutcomeState(str, Enum):
    TERMINAL_CANDIDATE = "TERMINAL_CANDIDATE"
    WAITING_RETRY = "WAITING_RETRY"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class CatalogEngineOutcomeV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    state: CatalogEngineOutcomeState
    reason_code: SafeReasonCode
    request_sha256: Sha256
    authority_id: UUID
    campaign_id: Sha256
    science_sha256: Sha256
    execution_plan_sha256: Sha256
    execution_protocol_sha256: Sha256
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    engine_run_id: int = Field(ge=1)
    engine_run_attempt: int = Field(ge=1)
    stage_results: Mapping[str, Literal["success", "failure", "cancelled", "skipped"]]
    recovery_statuses: tuple[
        Literal[
            "retry",
            "replan",
            "complete",
            "blocked",
            "waiting_retry",
            "failed_scientific",
        ],
        ...,
    ]
    final_evidence_artifact: SafeArtifactName | None
    runtime_audit_artifact: SafeArtifactName | None
    science_evidence_artifact: SafeArtifactName | None
    recovery_evidence_artifact: SafeArtifactName | None
    failure_fingerprint: Sha256 | None
    failure_occurrence_count: int = Field(ge=0, le=3)
    retry_not_before: datetime | None
    terminal_failure_code: SafeReasonCode | None
    created_at: datetime
    validation_opened: Literal[False] = False
    locked_opened: Literal[False] = False
    evidence_sha256: Sha256

    @field_validator("created_at", "retry_not_before")
    @classmethod
    def _normalize_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("CATALOG_ENGINE_OUTCOME_TIME_INVALID")
        return value.astimezone(UTC)

    @field_validator("stage_results")
    @classmethod
    def _validate_stage_results(
        cls,
        value: Mapping[str, str],
    ) -> Mapping[str, str]:
        if (
            not value
            or len(value) != len(set(value))
            or any(
                not key
                or len(key) > 96
                or not key.replace("_", "").isalnum()
                or result not in _STAGE_RESULT
                for key, result in value.items()
            )
        ):
            raise ValueError("CATALOG_ENGINE_STAGE_RESULTS_INVALID")
        return dict(value)

    @model_validator(mode="after")
    def _validate_shape_and_hash(self) -> "CatalogEngineOutcomeV1":
        if self.state is CatalogEngineOutcomeState.TERMINAL_CANDIDATE:
            if (
                self.reason_code != "CATALOG_ENGINE_TERMINAL_EVIDENCE_READY"
                or self.final_evidence_artifact is None
                or self.runtime_audit_artifact is None
                or self.science_evidence_artifact is None
                or self.failure_fingerprint is not None
                or self.failure_occurrence_count != 0
                or self.retry_not_before is not None
                or self.terminal_failure_code is not None
            ):
                raise ValueError("CATALOG_ENGINE_TERMINAL_OUTCOME_INVALID")
        elif self.state is CatalogEngineOutcomeState.WAITING_RETRY:
            if (
                self.recovery_evidence_artifact is None
                or self.final_evidence_artifact is not None
                or self.runtime_audit_artifact is not None
                or self.science_evidence_artifact is not None
                or self.failure_fingerprint is None
                or self.failure_occurrence_count not in {1, 2}
                or self.retry_not_before is None
                or self.retry_not_before <= self.created_at
                or self.terminal_failure_code is not None
            ):
                raise ValueError("CATALOG_ENGINE_WAITING_RETRY_INVALID")
        elif self.state is CatalogEngineOutcomeState.FAILED:
            if self.terminal_failure_code not in _CLOSED_SCIENTIFIC_FAILURES:
                raise ValueError("CATALOG_ENGINE_FAILED_OUTCOME_INVALID")
        elif self.terminal_failure_code is not None:
            raise ValueError("CATALOG_ENGINE_BLOCKED_OUTCOME_INVALID")
        payload = self.model_dump(mode="json", exclude={"evidence_sha256"})
        if hashlib.sha256(_canonical_bytes(payload)).hexdigest() != self.evidence_sha256:
            raise ValueError("CATALOG_ENGINE_OUTCOME_HASH_INVALID")
        return self


def _build_outcome(**values: object) -> CatalogEngineOutcomeV1:
    payload = {"schema_version": "1", **values}
    payload["evidence_sha256"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return CatalogEngineOutcomeV1.model_validate(payload)


def _utc_time(value: datetime | str | None, *, required: bool) -> datetime | None:
    if value is None:
        if required:
            raise ValueError("CATALOG_ENGINE_OUTCOME_TIME_INVALID")
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("CATALOG_ENGINE_OUTCOME_TIME_INVALID") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("CATALOG_ENGINE_OUTCOME_TIME_INVALID")
    return value.astimezone(UTC)


def select_catalog_engine_outcome(
    *,
    request_sha256: str,
    authority_id: UUID | str,
    campaign_id: str,
    science_sha256: str,
    execution_plan_sha256: str,
    execution_protocol_sha256: str,
    protected_commit_sha: str,
    engine_run_id: int,
    engine_run_attempt: int,
    stage_results: Mapping[str, str],
    recovery_statuses: Sequence[str],
    final_evidence_artifact: str | None,
    runtime_audit_artifact: str | None,
    science_evidence_artifact: str | None,
    recovery_evidence_artifact: str | None,
    failure_fingerprint: str | None,
    failure_occurrence_count: int,
    failure_reason_code: str | None,
    retry_not_before: datetime | str | None,
    terminal_failure_code: str | None,
    created_at: datetime | str,
    recovered_evaluation_evidence: RecoveredEvaluationEvidence | None = None,
) -> CatalogEngineOutcomeV1:
    """Select one explicit outcome; no failed workflow may yield blank outputs."""

    normalized_stages = dict(stage_results)
    if not normalized_stages or any(value not in _STAGE_RESULT for value in normalized_stages.values()):
        raise ValueError("CATALOG_ENGINE_STAGE_RESULTS_INVALID")
    statuses = tuple(str(item) for item in recovery_statuses)
    if any(item not in _RECOVERY_STATUS for item in statuses):
        raise ValueError("CATALOG_ENGINE_RECOVERY_STATUS_INVALID")
    normalized_created_at = _utc_time(created_at, required=True)
    normalized_retry_not_before = _utc_time(retry_not_before, required=False)
    common = {
        "request_sha256": request_sha256,
        "authority_id": authority_id,
        "campaign_id": campaign_id,
        "science_sha256": science_sha256,
        "execution_plan_sha256": execution_plan_sha256,
        "execution_protocol_sha256": execution_protocol_sha256,
        "protected_commit_sha": protected_commit_sha,
        "engine_run_id": engine_run_id,
        "engine_run_attempt": engine_run_attempt,
        "stage_results": normalized_stages,
        "recovery_statuses": statuses,
        "recovery_evidence_artifact": recovery_evidence_artifact,
        "created_at": normalized_created_at,
        "validation_opened": False,
        "locked_opened": False,
    }
    recovered_stages: frozenset[str] = frozenset()
    if recovered_evaluation_evidence is not None:
        if (not isinstance(recovered_evaluation_evidence, RecoveredEvaluationEvidence)
                or recovered_evaluation_evidence.bindings != tuple(str(common[k]) for k in _RECOVERED_BINDINGS)):
            raise ValueError("CATALOG_RECOVERED_EVALUATION_BINDING_INVALID")
        if (statuses and statuses[-1] == "complete" and "retry" in statuses
                and recovery_evidence_artifact and final_evidence_artifact
                and runtime_audit_artifact and science_evidence_artifact
                and all(normalized_stages.get(stage) == "success" for stage in (
                    "engine_verify_sealed_plan", "prepare_runtime_and_inputs", "publish_sealed_payload_artifacts",
                    "verify_component_store", "reconcile_wave_0", "ready_to_merge", "reduce_groups",
                    "reduce", "verify_terminal_science", "audit_runtime"))):
            recovered_stages = recovered_evaluation_evidence.stages
    if statuses and statuses[-1] == "waiting_retry":
        if failure_reason_code is None:
            raise ValueError("CATALOG_ENGINE_WAITING_RETRY_REASON_REQUIRED")
        return _build_outcome(
            **common,
            state=CatalogEngineOutcomeState.WAITING_RETRY,
            reason_code=failure_reason_code,
            final_evidence_artifact=None,
            runtime_audit_artifact=None,
            science_evidence_artifact=None,
            failure_fingerprint=failure_fingerprint,
            failure_occurrence_count=failure_occurrence_count,
            retry_not_before=normalized_retry_not_before,
            terminal_failure_code=None,
        )
    if statuses and statuses[-1] == "failed_scientific":
        if terminal_failure_code not in _CLOSED_SCIENTIFIC_FAILURES:
            raise ValueError("CATALOG_ENGINE_SCIENTIFIC_FAILURE_INVALID")
        return _build_outcome(
            **common,
            state=CatalogEngineOutcomeState.FAILED,
            reason_code=terminal_failure_code,
            final_evidence_artifact=None,
            runtime_audit_artifact=runtime_audit_artifact,
            science_evidence_artifact=None,
            failure_fingerprint=failure_fingerprint,
            failure_occurrence_count=failure_occurrence_count,
            retry_not_before=None,
            terminal_failure_code=terminal_failure_code,
        )
    if statuses and statuses[-1] == "blocked":
        reason = failure_reason_code or "CATALOG_RECOVERY_BLOCKED"
        return _build_outcome(
            **common,
            state=CatalogEngineOutcomeState.BLOCKED,
            reason_code=reason,
            final_evidence_artifact=None,
            runtime_audit_artifact=runtime_audit_artifact,
            science_evidence_artifact=None,
            failure_fingerprint=failure_fingerprint,
            failure_occurrence_count=failure_occurrence_count,
            retry_not_before=None,
            terminal_failure_code=None,
        )
    for stage, reason in _TERMINAL_STAGE_REASONS:
        if normalized_stages.get(stage) != "success":
            return _build_outcome(
                **common,
                state=CatalogEngineOutcomeState.BLOCKED,
                reason_code=reason,
                final_evidence_artifact=None,
                runtime_audit_artifact=(
                    runtime_audit_artifact
                    if normalized_stages.get("audit_runtime") == "success"
                    else None
                ),
                science_evidence_artifact=(
                    science_evidence_artifact
                    if normalized_stages.get("verify_terminal_science") == "success"
                    else None
                ),
                failure_fingerprint=failure_fingerprint,
                failure_occurrence_count=failure_occurrence_count,
                retry_not_before=None,
                terminal_failure_code=None,
            )
    if any(
        value in {"failure", "cancelled"}
        for key, value in normalized_stages.items()
        if key not in {"reduce", "verify_terminal_science", "audit_runtime"}
        and not (key in recovered_stages and value == "failure")
    ):
        return _build_outcome(
            **common,
            state=CatalogEngineOutcomeState.BLOCKED,
            reason_code=failure_reason_code or "CATALOG_ENGINE_STAGE_FAILED",
            final_evidence_artifact=None,
            runtime_audit_artifact=runtime_audit_artifact,
            science_evidence_artifact=science_evidence_artifact,
            failure_fingerprint=failure_fingerprint,
            failure_occurrence_count=failure_occurrence_count,
            retry_not_before=None,
            terminal_failure_code=None,
        )
    return _build_outcome(
        **common,
        state=CatalogEngineOutcomeState.TERMINAL_CANDIDATE,
        reason_code="CATALOG_ENGINE_TERMINAL_EVIDENCE_READY",
        final_evidence_artifact=final_evidence_artifact,
        runtime_audit_artifact=runtime_audit_artifact,
        science_evidence_artifact=science_evidence_artifact,
        failure_fingerprint=None,
        failure_occurrence_count=0,
        retry_not_before=None,
        terminal_failure_code=None,
    )


__all__ = [
    "CatalogEngineOutcomeState",
    "CatalogEngineOutcomeV1",
    "select_catalog_engine_outcome",
]
