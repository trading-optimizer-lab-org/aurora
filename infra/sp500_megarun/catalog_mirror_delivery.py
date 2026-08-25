"""Pure mirror-first delivery reconciliation for catalog authority writes."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import Field, field_validator, model_validator

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    Sha256,
    canonical_sha256,
)

from .catalog_authority_ledger import CatalogAuthorityRecordV1
from .catalog_request_receipt import CatalogRequestReceiptV1


_REPOSITORY = "trading-optimizer-lab-org/aurora"
_CONTROLLER_WRITER_WORKFLOWS = frozenset(
    {
        ".github/workflows/catalog-run-controller.yml",
        ".github/workflows/catalog-request-reconciler.yml",
        ".github/workflows/catalog-run-watchdog.yml",
    }
)
_REPAIRABLE_POST_CONCLUSIONS = frozenset({"failure", "skipped"})
_MAX_REPAIR_ATTEMPTS = 3
_MAX_FUTURE_SKEW = timedelta(seconds=30)


def _utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _payload_sha256(
    payload: CatalogAuthorityRecordV1 | CatalogRequestReceiptV1,
) -> str:
    if isinstance(payload, CatalogAuthorityRecordV1):
        return payload.record_sha256
    return payload.receipt_sha256


def catalog_mirror_repair_claim_artifact_name(
    target_payload_sha256: str,
    repair_sequence: int,
) -> str:
    if (
        len(target_payload_sha256) != 64
        or any(character not in "0123456789abcdef" for character in target_payload_sha256)
        or isinstance(repair_sequence, bool)
        or not 0 <= repair_sequence < _MAX_REPAIR_ATTEMPTS
    ):
        raise ValueError("CATALOG_MIRROR_REPAIR_CLAIM_IDENTITY_INVALID")
    return f"catalog-mirror-repair-{target_payload_sha256}-{repair_sequence:03d}"


class CatalogMirrorArtifactV1(FrozenModel):
    """One downloaded immutable artifact and its parsed canonical payload."""

    schema_version: Literal["1"] = "1"
    artifact_id: int = Field(ge=1)
    artifact_name: str = Field(min_length=1)
    expired: bool
    created_at: datetime
    expires_at: datetime
    payload: CatalogAuthorityRecordV1 | CatalogRequestReceiptV1
    payload_sha256: Sha256

    @field_validator("created_at", "expires_at")
    @classmethod
    def _validate_time(cls, value: datetime) -> datetime:
        return _utc(value, field="mirror artifact timestamp")

    @model_validator(mode="after")
    def _validate_mirror(self) -> "CatalogMirrorArtifactV1":
        if self.expires_at <= self.created_at:
            raise ValueError("CATALOG_MIRROR_EXPIRY_INVALID")
        if self.artifact_name != self.payload.artifact_name:
            raise ValueError("CATALOG_MIRROR_SLOT_CONFLICT")
        if self.payload_sha256 != _payload_sha256(self.payload):
            raise ValueError("CATALOG_MIRROR_PAYLOAD_HASH_INVALID")
        return self

    @classmethod
    def create(
        cls,
        *,
        artifact_id: int,
        artifact_name: str,
        expired: bool,
        created_at: datetime,
        expires_at: datetime,
        payload: object,
    ) -> "CatalogMirrorArtifactV1":
        parsed: CatalogAuthorityRecordV1 | CatalogRequestReceiptV1
        if isinstance(payload, CatalogAuthorityRecordV1):
            parsed = CatalogAuthorityRecordV1.model_validate(
                payload.model_dump(mode="json")
            )
        elif isinstance(payload, CatalogRequestReceiptV1):
            parsed = CatalogRequestReceiptV1.model_validate(
                payload.model_dump(mode="json")
            )
        else:
            raise ValueError("CATALOG_MIRROR_PAYLOAD_TYPE_INVALID")
        values = {
            "schema_version": "1",
            "artifact_id": artifact_id,
            "artifact_name": artifact_name,
            "expired": expired,
            "created_at": _utc(created_at, field="created_at"),
            "expires_at": _utc(expires_at, field="expires_at"),
            "payload": parsed,
            "payload_sha256": _payload_sha256(parsed),
        }
        return cls(**values)


class CatalogMirrorWriterEvidenceV1(FrozenModel):
    """Complete Actions evidence for the writer that created one mirror."""

    schema_version: Literal["1"] = "1"
    complete: bool
    stable: bool
    authenticated: bool
    repository: Literal["trading-optimizer-lab-org/aurora"]
    workflow_path: Literal[
        ".github/workflows/catalog-run-controller.yml",
        ".github/workflows/catalog-request-reconciler.yml",
        ".github/workflows/catalog-run-watchdog.yml",
    ]
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    run_id: int = Field(ge=1)
    run_attempt: int = Field(ge=1)
    run_status: str = Field(min_length=1)
    writer_job_id: Literal[
        "report_nonexecuting_decision",
        "repair_request_receipt_orphan",
        "reserve",
        "record_running",
        "record_nonterminal_wait",
        "finalize",
    ]
    writer_job_database_id: int = Field(ge=1)
    job_status: str = Field(min_length=1)
    upload_step_conclusion: str | None
    post_step_conclusion: str | None


class CatalogMirrorRepairWriterContextV1(FrozenModel):
    """Historical or current protected job recorded with a repair claim."""

    schema_version: Literal["1"] = "1"
    run_id: int = Field(ge=1)
    run_attempt: int = Field(ge=1)
    writer_job_id: Literal[
        "report_nonexecuting_decision",
        "repair_request_receipt_orphan",
        "reserve",
        "record_running",
        "record_nonterminal_wait",
        "finalize",
    ]
    writer_job_database_id: int = Field(ge=1)
    workflow_path: Literal[
        ".github/workflows/catalog-run-controller.yml",
        ".github/workflows/catalog-request-reconciler.yml",
        ".github/workflows/catalog-run-watchdog.yml",
    ]
    repository: Literal["trading-optimizer-lab-org/aurora"]
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _validate_observed_at(cls, value: datetime) -> datetime:
        return _utc(value, field="repair writer timestamp")


class CatalogMirrorCurrentRepairWriterContextV1(FrozenModel):
    """Current protected job that may create one bounded comment-repair claim."""

    schema_version: Literal["1"] = "1"
    run_id: int = Field(ge=1)
    run_attempt: int = Field(ge=1)
    writer_job_id: Literal[
        "report_nonexecuting_decision",
        "reserve",
        "record_running",
        "record_nonterminal_wait",
        "finalize",
    ]
    writer_job_database_id: int = Field(ge=1)
    workflow_path: Literal[
        ".github/workflows/catalog-run-controller.yml",
        ".github/workflows/catalog-request-reconciler.yml",
        ".github/workflows/catalog-run-watchdog.yml",
    ]
    repository: Literal["trading-optimizer-lab-org/aurora"]
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _validate_observed_at(cls, value: datetime) -> datetime:
        return _utc(value, field="repair writer timestamp")


class CatalogMirrorRepairClaimV1(FrozenModel):
    """Immutable intent recorded before one otherwise non-idempotent POST."""

    schema_version: Literal["1"] = "1"
    target_kind: Literal["authority", "request"]
    target_artifact_name: str = Field(pattern=r"^[A-Za-z0-9._-]{1,255}$")
    target_artifact_id: int = Field(ge=1)
    target_payload_sha256: Sha256
    repair_sequence: int = Field(ge=0, lt=_MAX_REPAIR_ATTEMPTS)
    previous_claim_sha256: Sha256 | None
    writer: CatalogMirrorRepairWriterContextV1
    claim_sha256: Sha256

    @property
    def artifact_name(self) -> str:
        return catalog_mirror_repair_claim_artifact_name(
            self.target_payload_sha256,
            self.repair_sequence,
        )

    @model_validator(mode="after")
    def _validate_claim(self) -> "CatalogMirrorRepairClaimV1":
        identity = self.model_dump(mode="json", exclude={"claim_sha256"})
        if canonical_sha256(identity) != self.claim_sha256:
            raise ValueError("CATALOG_MIRROR_REPAIR_CLAIM_HASH_INVALID")
        if (self.repair_sequence == 0) is not (
            self.previous_claim_sha256 is None
        ):
            raise ValueError("CATALOG_MIRROR_REPAIR_CLAIM_CHAIN_INVALID")
        return self

    @classmethod
    def create(
        cls,
        *,
        target_kind: Literal["authority", "request"],
        target_artifact_name: str,
        target_artifact_id: int,
        target_payload_sha256: str,
        repair_sequence: int,
        previous_claim_sha256: str | None,
        writer: CatalogMirrorRepairWriterContextV1,
    ) -> "CatalogMirrorRepairClaimV1":
        if writer.writer_job_id == "repair_request_receipt_orphan":
            raise ValueError("CATALOG_MIRROR_REPAIR_CURRENT_WRITER_INVALID")
        identity = {
            "schema_version": "1",
            "target_kind": target_kind,
            "target_artifact_name": target_artifact_name,
            "target_artifact_id": target_artifact_id,
            "target_payload_sha256": target_payload_sha256,
            "repair_sequence": repair_sequence,
            "previous_claim_sha256": previous_claim_sha256,
            "writer": writer.model_dump(mode="json"),
        }
        return cls(**identity, claim_sha256=canonical_sha256(identity))


class CatalogMirrorDeliveryDecisionV1(FrozenModel):
    """One bounded action for an immutable delivery slot."""

    schema_version: Literal["1"] = "1"
    delivery_kind: Literal["authority", "request"]
    action: Literal["upload_new", "repair_comment", "idempotent"]
    artifact_name: str = Field(min_length=1)
    artifact_id: int | None = Field(default=None, ge=1)
    payload_sha256: Sha256
    stop_after_repair: bool

    @model_validator(mode="after")
    def _validate_shape(self) -> "CatalogMirrorDeliveryDecisionV1":
        existing = self.action in {"repair_comment", "idempotent"}
        if (self.artifact_id is not None) is not existing:
            raise ValueError("CATALOG_MIRROR_DECISION_SHAPE_INVALID")
        if self.stop_after_repair is not existing:
            raise ValueError("CATALOG_MIRROR_DECISION_SHAPE_INVALID")
        return self


def _authority_delivery_identity(record: CatalogAuthorityRecordV1) -> str:
    return canonical_sha256(
        record.model_dump(
            mode="json",
            exclude={
                "record_sha256",
                "run_id",
                "run_attempt",
                "writer_job_database_id",
                "created_at",
            },
        )
    )


def _writer_evidence_for(
    payload: CatalogAuthorityRecordV1 | CatalogRequestReceiptV1,
    evidence: Sequence[CatalogMirrorWriterEvidenceV1],
) -> CatalogMirrorWriterEvidenceV1:
    run_id = payload.run_id if isinstance(payload, CatalogAuthorityRecordV1) else payload.writer_run_id
    run_attempt = (
        payload.run_attempt
        if isinstance(payload, CatalogAuthorityRecordV1)
        else payload.writer_run_attempt
    )
    writer_job_id = payload.writer_job_id
    database_id = (
        payload.writer_job_database_id
        if isinstance(payload, CatalogAuthorityRecordV1)
        else payload.writer_job_database_id
    )
    protected_commit_sha = payload.protected_commit_sha
    matches = tuple(
        row
        for row in evidence
        if row.run_id == run_id
        and row.run_attempt == run_attempt
        and row.writer_job_id == writer_job_id
        and row.writer_job_database_id == database_id
        and row.protected_commit_sha == protected_commit_sha
    )
    if len(matches) != 1:
        raise ValueError("CATALOG_MIRROR_WRITER_EVIDENCE_INVALID")
    row = matches[0]
    if (
        not row.complete
        or not row.stable
        or not row.authenticated
        or row.repository != _REPOSITORY
        or row.workflow_path not in _CONTROLLER_WRITER_WORKFLOWS
        or row.run_status != "completed"
        or row.job_status != "completed"
        or row.upload_step_conclusion != "success"
    ):
        raise ValueError("CATALOG_MIRROR_WRITER_EVIDENCE_INVALID")
    return row


def _select_live_artifact(
    *,
    artifact_name: str,
    artifacts: Sequence[CatalogMirrorArtifactV1],
    now: datetime,
) -> CatalogMirrorArtifactV1 | None:
    now = _utc(now, field="now")
    if any(row.artifact_name != artifact_name for row in artifacts):
        raise ValueError("CATALOG_MIRROR_SLOT_CONFLICT")
    live = tuple(
        row
        for row in artifacts
        if not row.expired and row.expires_at > now
    )
    if any(row.created_at > now + _MAX_FUTURE_SKEW for row in live):
        raise ValueError("CATALOG_MIRROR_TIMESTAMP_INVALID")
    if len(live) > 1:
        raise ValueError("CATALOG_MIRROR_SLOT_CONFLICT")
    return live[0] if live else None


def _decision(
    *,
    delivery_kind: Literal["authority", "request"],
    action: Literal["upload_new", "repair_comment", "idempotent"],
    artifact_name: str,
    payload_sha256: str,
    artifact_id: int | None = None,
) -> CatalogMirrorDeliveryDecisionV1:
    return CatalogMirrorDeliveryDecisionV1(
        delivery_kind=delivery_kind,
        action=action,
        artifact_name=artifact_name,
        artifact_id=artifact_id,
        payload_sha256=payload_sha256,
        stop_after_repair=action != "upload_new",
    )


def _require_repairable_post(
    payload: CatalogAuthorityRecordV1 | CatalogRequestReceiptV1,
    evidence: Sequence[CatalogMirrorWriterEvidenceV1],
) -> None:
    writer = _writer_evidence_for(payload, evidence)
    if writer.post_step_conclusion not in _REPAIRABLE_POST_CONCLUSIONS:
        raise ValueError("CATALOG_MIRROR_POST_OUTCOME_AMBIGUOUS")


def decide_request_receipt_mirror_delivery(
    *,
    candidate: CatalogRequestReceiptV1,
    artifacts: Sequence[CatalogMirrorArtifactV1],
    comment_receipts: Sequence[CatalogRequestReceiptV1],
    writer_evidence: Sequence[CatalogMirrorWriterEvidenceV1],
    now: datetime,
) -> CatalogMirrorDeliveryDecisionV1:
    """Upload, repair, or no-op one request-receipt delivery slot."""

    candidate = CatalogRequestReceiptV1.model_validate(
        candidate.model_dump(mode="json")
    )
    mirror = _select_live_artifact(
        artifact_name=candidate.artifact_name,
        artifacts=artifacts,
        now=now,
    )
    relevant_comments = tuple(
        row
        for row in comment_receipts
        if row.mirror_identity_sha256 == candidate.mirror_identity_sha256
    )
    if len(relevant_comments) > 1:
        raise ValueError("CATALOG_MIRROR_COMMENT_CONFLICT")
    if mirror is None:
        if relevant_comments:
            raise ValueError("CATALOG_MIRROR_REQUIRED")
        return _decision(
            delivery_kind="request",
            action="upload_new",
            artifact_name=candidate.artifact_name,
            payload_sha256=candidate.receipt_sha256,
        )
    if not isinstance(mirror.payload, CatalogRequestReceiptV1):
        raise ValueError("CATALOG_MIRROR_SLOT_CONFLICT")
    stored = mirror.payload
    if stored.mirror_identity_sha256 != candidate.mirror_identity_sha256:
        raise ValueError("CATALOG_MIRROR_SLOT_CONFLICT")
    if relevant_comments:
        if relevant_comments[0].receipt_sha256 != stored.receipt_sha256:
            raise ValueError("CATALOG_MIRROR_COMMENT_CONFLICT")
        return _decision(
            delivery_kind="request",
            action="idempotent",
            artifact_name=stored.artifact_name,
            artifact_id=mirror.artifact_id,
            payload_sha256=stored.receipt_sha256,
        )
    _require_repairable_post(stored, writer_evidence)
    return _decision(
        delivery_kind="request",
        action="repair_comment",
        artifact_name=stored.artifact_name,
        artifact_id=mirror.artifact_id,
        payload_sha256=stored.receipt_sha256,
    )


def decide_authority_mirror_delivery(
    *,
    candidate: CatalogAuthorityRecordV1,
    artifacts: Sequence[CatalogMirrorArtifactV1],
    comment_records: Sequence[CatalogAuthorityRecordV1],
    writer_evidence: Sequence[CatalogMirrorWriterEvidenceV1],
    now: datetime,
) -> CatalogMirrorDeliveryDecisionV1:
    """Upload, repair, or no-op one authority-ledger delivery slot."""

    candidate = CatalogAuthorityRecordV1.model_validate(
        candidate.model_dump(mode="json")
    )
    mirror = _select_live_artifact(
        artifact_name=candidate.artifact_name,
        artifacts=artifacts,
        now=now,
    )
    relevant_comments = tuple(
        row
        for row in comment_records
        if row.authority_id == candidate.authority_id
        and row.sequence == candidate.sequence
    )
    if len(relevant_comments) > 1:
        raise ValueError("CATALOG_MIRROR_COMMENT_CONFLICT")
    if mirror is None:
        if relevant_comments:
            raise ValueError("CATALOG_MIRROR_REQUIRED")
        return _decision(
            delivery_kind="authority",
            action="upload_new",
            artifact_name=candidate.artifact_name,
            payload_sha256=candidate.record_sha256,
        )
    if not isinstance(mirror.payload, CatalogAuthorityRecordV1):
        raise ValueError("CATALOG_MIRROR_SLOT_CONFLICT")
    stored = mirror.payload
    if _authority_delivery_identity(stored) != _authority_delivery_identity(candidate):
        raise ValueError("CATALOG_MIRROR_SLOT_CONFLICT")
    if relevant_comments:
        if relevant_comments[0].record_sha256 != stored.record_sha256:
            raise ValueError("CATALOG_MIRROR_COMMENT_CONFLICT")
        return _decision(
            delivery_kind="authority",
            action="idempotent",
            artifact_name=stored.artifact_name,
            artifact_id=mirror.artifact_id,
            payload_sha256=stored.record_sha256,
        )
    _require_repairable_post(stored, writer_evidence)
    return _decision(
        delivery_kind="authority",
        action="repair_comment",
        artifact_name=stored.artifact_name,
        artifact_id=mirror.artifact_id,
        payload_sha256=stored.record_sha256,
    )


def _repair_claim_writer_evidence_for(
    claim: CatalogMirrorRepairClaimV1,
    evidence: Sequence[CatalogMirrorWriterEvidenceV1],
) -> CatalogMirrorWriterEvidenceV1:
    writer = claim.writer
    matches = tuple(
        row
        for row in evidence
        if row.run_id == writer.run_id
        and row.run_attempt == writer.run_attempt
        and row.writer_job_id == writer.writer_job_id
        and row.writer_job_database_id == writer.writer_job_database_id
        and row.protected_commit_sha == writer.protected_commit_sha
    )
    if len(matches) != 1:
        raise ValueError("CATALOG_MIRROR_REPAIR_WRITER_EVIDENCE_INVALID")
    row = matches[0]
    if (
        not row.complete
        or not row.stable
        or not row.authenticated
        or row.repository != writer.repository
        or row.workflow_path != writer.workflow_path
        or row.run_status != "completed"
        or row.job_status != "completed"
        or row.upload_step_conclusion != "success"
    ):
        raise ValueError("CATALOG_MIRROR_REPAIR_WRITER_EVIDENCE_INVALID")
    return row


def prepare_catalog_mirror_repair_claim(
    *,
    decision: CatalogMirrorDeliveryDecisionV1,
    prior_claims: Sequence[CatalogMirrorRepairClaimV1],
    prior_writer_evidence: Sequence[CatalogMirrorWriterEvidenceV1],
    current_writer: CatalogMirrorCurrentRepairWriterContextV1,
) -> CatalogMirrorRepairClaimV1:
    """Claim one repair before POST, retrying only proven failed attempts."""

    decision = CatalogMirrorDeliveryDecisionV1.model_validate(
        decision.model_dump(mode="json")
    )
    try:
        current_writer = CatalogMirrorCurrentRepairWriterContextV1.model_validate(
            current_writer.model_dump(mode="json")
        )
    except ValueError:
        raise ValueError("CATALOG_MIRROR_REPAIR_CURRENT_WRITER_INVALID") from None
    claims = tuple(
        CatalogMirrorRepairClaimV1.model_validate(row.model_dump(mode="json"))
        for row in prior_claims
    )
    evidence = tuple(
        CatalogMirrorWriterEvidenceV1.model_validate(row.model_dump(mode="json"))
        for row in prior_writer_evidence
    )
    if (
        decision.action != "repair_comment"
        or decision.artifact_id is None
        or decision.stop_after_repair is not True
    ):
        raise ValueError("CATALOG_MIRROR_REPAIR_NOT_REQUIRED")
    if len(claims) >= _MAX_REPAIR_ATTEMPTS:
        raise ValueError("CATALOG_MIRROR_REPAIR_LIMIT_REACHED")
    if tuple(row.repair_sequence for row in claims) != tuple(range(len(claims))):
        raise ValueError("CATALOG_MIRROR_REPAIR_CLAIM_CHAIN_INVALID")
    previous_hash: str | None = None
    writer_identities: set[tuple[int, int, int]] = set()
    for claim in claims:
        if (
            claim.target_kind != decision.delivery_kind
            or claim.target_artifact_name != decision.artifact_name
            or claim.target_artifact_id != decision.artifact_id
            or claim.target_payload_sha256 != decision.payload_sha256
            or claim.previous_claim_sha256 != previous_hash
        ):
            raise ValueError("CATALOG_MIRROR_REPAIR_CLAIM_CHAIN_INVALID")
        row = _repair_claim_writer_evidence_for(claim, evidence)
        if row.post_step_conclusion not in _REPAIRABLE_POST_CONCLUSIONS:
            raise ValueError("CATALOG_MIRROR_REPAIR_POST_OUTCOME_AMBIGUOUS")
        identity = (
            claim.writer.run_id,
            claim.writer.run_attempt,
            claim.writer.writer_job_database_id,
        )
        if identity in writer_identities:
            raise ValueError("CATALOG_MIRROR_REPAIR_CLAIM_CHAIN_INVALID")
        writer_identities.add(identity)
        previous_hash = claim.claim_sha256
    current_identity = (
        current_writer.run_id,
        current_writer.run_attempt,
        current_writer.writer_job_database_id,
    )
    if current_identity in writer_identities:
        raise ValueError("CATALOG_MIRROR_REPAIR_CLAIM_CHAIN_INVALID")
    return CatalogMirrorRepairClaimV1.create(
        target_kind=decision.delivery_kind,
        target_artifact_name=decision.artifact_name,
        target_artifact_id=decision.artifact_id,
        target_payload_sha256=decision.payload_sha256,
        repair_sequence=len(claims),
        previous_claim_sha256=previous_hash,
        writer=current_writer,
    )


__all__ = [
    "CatalogMirrorArtifactV1",
    "CatalogMirrorDeliveryDecisionV1",
    "CatalogMirrorRepairClaimV1",
    "CatalogMirrorCurrentRepairWriterContextV1",
    "CatalogMirrorRepairWriterContextV1",
    "CatalogMirrorWriterEvidenceV1",
    "catalog_mirror_repair_claim_artifact_name",
    "decide_authority_mirror_delivery",
    "decide_request_receipt_mirror_delivery",
    "prepare_catalog_mirror_repair_claim",
]
