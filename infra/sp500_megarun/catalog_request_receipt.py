"""Closed mirror-first receipts for controller-authored catalog request comments."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from .catalog_authority_ledger import AuthorityState, CatalogAuthorityRecordV1
from .catalog_authority_writer import (
    CatalogAuthorityTransitionCandidateV1,
    CatalogAuthorityWriterContextV1,
)
from .catalog_controller_reporting import CatalogTerminalDecisionV1
from .catalog_engine_outcome import CatalogEngineOutcomeState, CatalogEngineOutcomeV1
from .catalog_request_contract import FrozenModel, Sha256


REQUEST_RECEIPT_MARKER = "AURORA_CATALOG_REQUEST_RECEIPT_V1"
MAX_REQUEST_RECEIPT_SEQUENCE = 9_999_999_999
_ALLOWED_WRITER_WORKFLOWS = frozenset(
    {
        ".github/workflows/catalog-run-controller.yml",
        ".github/workflows/catalog-request-reconciler.yml",
        ".github/workflows/catalog-run-watchdog.yml",
    }
)
_ALLOWED_WRITER_EVENTS = frozenset(
    {"issues", "issue_comment", "workflow_call", "workflow_run", "schedule"}
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
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def request_receipt_artifact_name(*, issue_number: int, sequence: int) -> str:
    if issue_number < 1 or not 0 <= sequence <= MAX_REQUEST_RECEIPT_SEQUENCE:
        raise ValueError("CATALOG_REQUEST_RECEIPT_SEQUENCE_INVALID")
    return f"catalog-request-receipt-{issue_number}-{sequence:010d}"


def next_request_receipt_sequence(
    receipts: Sequence["CatalogRequestReceiptV1"],
    *,
    issue_number: int,
    request_sha256: str,
) -> int:
    """Validate one contiguous append-only receipt chain and return its next slot."""

    checked = tuple(
        CatalogRequestReceiptV1.model_validate(item.model_dump(mode="json"))
        for item in receipts
    )
    if any(
        item.issue_number != issue_number
        or item.request_sha256 != request_sha256
        for item in checked
    ):
        raise ValueError("CATALOG_REQUEST_RECEIPT_SEQUENCE_INVALID")
    sequences = tuple(item.delivery_sequence for item in checked)
    if sequences != tuple(range(len(checked))):
        raise ValueError("CATALOG_REQUEST_RECEIPT_SEQUENCE_INVALID")
    return len(checked)


class CatalogRequestReceiptV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    marker: Literal["AURORA_CATALOG_REQUEST_RECEIPT_V1"]
    state: Literal["WAITING_RETRY", "SUCCESS", "FAILED", "BLOCKED", "DEFERRED"]
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    issue_number: int = Field(ge=1)
    delivery_sequence: int = Field(ge=0, le=MAX_REQUEST_RECEIPT_SEQUENCE)
    request_sha256: Sha256
    authority_id: UUID | None
    campaign_id: Sha256 | None
    terminal_decision_sha256: Sha256 | None
    authority_record_sha256: Sha256 | None
    writer_run_id: int = Field(ge=1)
    writer_run_attempt: int = Field(ge=1)
    writer_job_id: Literal[
        "report_nonexecuting_decision",
        "record_nonterminal_wait",
        "finalize",
    ]
    writer_job_database_id: int = Field(ge=1)
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    summary_sha256: Sha256
    created_at: datetime
    retry_not_before: datetime | None = None
    receipt_sha256: Sha256

    @field_validator("created_at", "retry_not_before")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("CATALOG_REQUEST_RECEIPT_TIME_INVALID")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _shape_and_hash(self) -> "CatalogRequestReceiptV1":
        terminal_authority = self.terminal_decision_sha256 is not None
        if self.state in {"SUCCESS", "FAILED"} and not terminal_authority:
            raise ValueError("CATALOG_REQUEST_RECEIPT_TERMINAL_SHAPE_INVALID")
        if self.state in {"WAITING_RETRY", "DEFERRED"} and terminal_authority:
            raise ValueError("CATALOG_REQUEST_RECEIPT_TERMINAL_SHAPE_INVALID")
        if self.state == "BLOCKED" and terminal_authority != (self.authority_id is not None):
            raise ValueError("CATALOG_REQUEST_RECEIPT_TERMINAL_SHAPE_INVALID")
        if (self.authority_id is None) != (self.authority_record_sha256 is None):
            raise ValueError("CATALOG_REQUEST_RECEIPT_AUTHORITY_SHAPE_INVALID")
        if self.authority_id is not None and self.campaign_id is None:
            raise ValueError("CATALOG_REQUEST_RECEIPT_AUTHORITY_SHAPE_INVALID")
        if terminal_authority and self.authority_id is None:
            raise ValueError("CATALOG_REQUEST_RECEIPT_AUTHORITY_SHAPE_INVALID")
        retry_required = self.state == "WAITING_RETRY" or (
            self.state == "DEFERRED"
            and self.reason_code != "CATALOG_ADOPTED_WAITING_FOR_EXISTING"
        )
        if (self.retry_not_before is not None) is not retry_required:
            raise ValueError("CATALOG_REQUEST_RECEIPT_RETRY_SHAPE_INVALID")
        payload = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if _sha256(payload) != self.receipt_sha256:
            raise ValueError("CATALOG_REQUEST_RECEIPT_HASH_INVALID")
        return self

    @property
    def mirror_identity_sha256(self) -> str:
        """Stable identity for one append-only request-receipt delivery slot."""

        return _sha256(
            {
                "issue_number": self.issue_number,
                "delivery_sequence": self.delivery_sequence,
                "request_sha256": self.request_sha256,
            }
        )

    @property
    def artifact_name(self) -> str:
        return request_receipt_artifact_name(
            issue_number=self.issue_number,
            sequence=self.delivery_sequence,
        )

    def comment_body(self, summary: str) -> str:
        normalized = summary.rstrip()
        if hashlib.sha256(normalized.encode("utf-8")).hexdigest() != self.summary_sha256:
            raise ValueError("CATALOG_REQUEST_RECEIPT_SUMMARY_HASH_INVALID")
        return (
            normalized
            + "\n\n<!-- "
            + REQUEST_RECEIPT_MARKER
            + " -->\n```json\n"
            + _canonical_bytes(self).decode("utf-8")
            + "\n```\n"
        )


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("CATALOG_REQUEST_RECEIPT_PROVENANCE_INVALID")
    return value


def parse_request_receipt_comment(
    comment: Mapping[str, object],
    *,
    expected_author: str = "github-actions[bot]",
) -> CatalogRequestReceiptV1 | None:
    """Parse one immutable bot receipt; ignore markers from untrusted authors."""

    body = comment.get("body")
    if not isinstance(body, str) or REQUEST_RECEIPT_MARKER not in body:
        return None
    user = comment.get("user")
    author = user.get("login") if isinstance(user, Mapping) else None
    if author != expected_author:
        return None
    if (
        comment.get("created_at") != comment.get("updated_at")
        or body.count(f"<!-- {REQUEST_RECEIPT_MARKER} -->") != 1
    ):
        raise ValueError("CATALOG_REQUEST_RECEIPT_COMMENT_INVALID")
    delimiter = f"\n\n<!-- {REQUEST_RECEIPT_MARKER} -->\n```json\n"
    if body.count(delimiter) != 1 or not body.endswith("\n```\n"):
        raise ValueError("CATALOG_REQUEST_RECEIPT_COMMENT_INVALID")
    summary, encoded = body.split(delimiter, 1)
    encoded = encoded[: -len("\n```\n")]
    try:
        payload = json.loads(
            encoded,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
        receipt = CatalogRequestReceiptV1.model_validate(payload)
    except Exception:
        raise ValueError("CATALOG_REQUEST_RECEIPT_COMMENT_INVALID") from None
    if (
        encoded.encode("utf-8") != _canonical_bytes(receipt)
        or hashlib.sha256(summary.encode("utf-8")).hexdigest()
        != receipt.summary_sha256
    ):
        raise ValueError("CATALOG_REQUEST_RECEIPT_COMMENT_INVALID")
    return receipt


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("CATALOG_REQUEST_RECEIPT_JSON_DUPLICATE")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"CATALOG_REQUEST_RECEIPT_JSON_NONFINITE:{value}")


def verify_request_receipt_writer_provenance(
    receipt: CatalogRequestReceiptV1,
    snapshot: Mapping[str, object],
    *,
    expected_repository: str,
) -> str:
    """Verify the exact run/job/commit that authored one request receipt."""

    try:
        if any(
            snapshot.get(flag) is not True
            for flag in (
                "complete",
                "pagination_complete",
                "stable",
                "authenticated",
                "workflow_policy_verified",
            )
        ):
            raise ValueError
        if not isinstance(snapshot.get("etag"), str) or not snapshot["etag"]:
            raise ValueError
        if snapshot.get("run_id", snapshot.get("id")) != receipt.writer_run_id:
            raise ValueError
        if (
            snapshot.get("run_attempt", snapshot.get("attempt"))
            != receipt.writer_run_attempt
            or snapshot.get("head_sha") != receipt.protected_commit_sha
            or snapshot.get("workflow_path", snapshot.get("path"))
            not in _ALLOWED_WRITER_WORKFLOWS
            or snapshot.get("event") not in _ALLOWED_WRITER_EVENTS
            or snapshot.get("repository", snapshot.get("repository_full_name"))
            != expected_repository
        ):
            raise ValueError
        jobs = snapshot.get("jobs")
        if not isinstance(jobs, Sequence) or isinstance(jobs, (str, bytes)):
            raise ValueError
        matches = []
        for raw_job in jobs:
            job = _mapping(raw_job)
            if (
                job.get("job_id", job.get("logical_job_id"))
                == receipt.writer_job_id
                and job.get("database_id", job.get("id"))
                == receipt.writer_job_database_id
            ):
                matches.append(job)
        if len(matches) != 1:
            raise ValueError
        job = matches[0]
        if (
            job.get("issues_write") is not True
            or job.get("steps_are_allowlisted") is not True
            or job.get("request_receipt_write") is not True
        ):
            raise ValueError
    except Exception:
        raise ValueError("CATALOG_REQUEST_RECEIPT_PROVENANCE_INVALID") from None
    return _sha256(snapshot)


def build_terminal_request_receipt(
    *,
    decision: CatalogTerminalDecisionV1,
    authority_candidate: CatalogAuthorityTransitionCandidateV1,
    summary: str,
    delivery_sequence: int = 0,
) -> CatalogRequestReceiptV1:
    """Bind a terminal summary to the exact not-yet-committed authority record."""

    terminal = CatalogTerminalDecisionV1.model_validate(
        decision.model_dump(mode="json")
    )
    candidate = CatalogAuthorityTransitionCandidateV1.model_validate(
        authority_candidate.model_dump(mode="json")
    )
    record: CatalogAuthorityRecordV1 = candidate.record
    if (
        candidate.mode != "terminal"
        or candidate.decision_sha256 != terminal.terminal_decision_sha256
        or record.authority_id != terminal.authority_id
        or record.request_sha256 != terminal.request_sha256
        or record.campaign_id != terminal.campaign_id
        or record.evidence_sha256 != terminal.terminal_decision_sha256
        or record.state.value != terminal.state.value.casefold()
        or record.writer_job_id != "finalize"
    ):
        raise ValueError("CATALOG_REQUEST_RECEIPT_TERMINAL_BINDING_INVALID")
    summary = summary.rstrip()
    payload: dict[str, object] = {
        "schema_version": "1",
        "marker": REQUEST_RECEIPT_MARKER,
        "state": terminal.state.value,
        "reason_code": terminal.reason_code,
        "issue_number": record.request_issue_number,
        "delivery_sequence": delivery_sequence,
        "request_sha256": terminal.request_sha256,
        "authority_id": str(terminal.authority_id),
        "campaign_id": terminal.campaign_id,
        "terminal_decision_sha256": terminal.terminal_decision_sha256,
        "authority_record_sha256": record.record_sha256,
        "writer_run_id": record.run_id,
        "writer_run_attempt": record.run_attempt,
        "writer_job_id": "finalize",
        "writer_job_database_id": record.writer_job_database_id,
        "protected_commit_sha": record.protected_commit_sha,
        "summary_sha256": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
        "created_at": record.created_at.isoformat().replace("+00:00", "Z"),
        "retry_not_before": None,
    }
    payload["receipt_sha256"] = _sha256(payload)
    return CatalogRequestReceiptV1.model_validate(payload)


def _build_receipt(
    *,
    state: Literal["WAITING_RETRY", "SUCCESS", "FAILED", "BLOCKED", "DEFERRED"],
    reason_code: str,
    issue_number: int,
    delivery_sequence: int,
    request_sha256: str,
    campaign_id: str | None,
    authority_record: CatalogAuthorityRecordV1 | None,
    terminal_decision_sha256: str | None,
    writer_run_id: int,
    writer_run_attempt: int,
    writer_job_id: Literal[
        "report_nonexecuting_decision",
        "record_nonterminal_wait",
        "finalize",
    ],
    writer_job_database_id: int,
    protected_commit_sha: str,
    created_at: datetime,
    retry_not_before: datetime | None,
    summary: str,
) -> CatalogRequestReceiptV1:
    normalized_summary = summary.rstrip()
    payload: dict[str, object] = {
        "schema_version": "1",
        "marker": REQUEST_RECEIPT_MARKER,
        "state": state,
        "reason_code": reason_code,
        "issue_number": issue_number,
        "delivery_sequence": delivery_sequence,
        "request_sha256": request_sha256,
        "authority_id": (
            str(authority_record.authority_id) if authority_record is not None else None
        ),
        "campaign_id": campaign_id,
        "terminal_decision_sha256": terminal_decision_sha256,
        "authority_record_sha256": (
            authority_record.record_sha256 if authority_record is not None else None
        ),
        "writer_run_id": writer_run_id,
        "writer_run_attempt": writer_run_attempt,
        "writer_job_id": writer_job_id,
        "writer_job_database_id": writer_job_database_id,
        "protected_commit_sha": protected_commit_sha,
        "summary_sha256": hashlib.sha256(
            normalized_summary.encode("utf-8")
        ).hexdigest(),
        "created_at": created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "retry_not_before": (
            retry_not_before.astimezone(UTC).isoformat().replace("+00:00", "Z")
            if retry_not_before is not None
            else None
        ),
    }
    payload["receipt_sha256"] = _sha256(payload)
    return CatalogRequestReceiptV1.model_validate(payload)


def build_nonexecuting_request_receipt(
    *,
    state: Literal["SUCCESS", "FAILED", "BLOCKED", "DEFERRED"],
    reason_code: str,
    issue_number: int,
    request_sha256: str,
    campaign_id: str | None,
    authority_record: CatalogAuthorityRecordV1 | None,
    writer: CatalogAuthorityWriterContextV1,
    retry_not_before: datetime | None = None,
    summary: str,
    delivery_sequence: int = 0,
) -> CatalogRequestReceiptV1:
    """Build a no-compute request receipt from one proven controller writer."""

    writer = CatalogAuthorityWriterContextV1.model_validate(
        writer.model_dump(mode="json")
    )
    if writer.writer_job_id != "report_nonexecuting_decision":
        raise ValueError("CATALOG_REQUEST_RECEIPT_WRITER_INVALID")
    record = (
        None
        if authority_record is None
        else CatalogAuthorityRecordV1.model_validate(
            authority_record.model_dump(mode="json")
        )
    )
    if record is None:
        if state not in {"BLOCKED", "DEFERRED"}:
            raise ValueError("CATALOG_REQUEST_RECEIPT_NONEXECUTING_BINDING_INVALID")
        terminal_decision = None
    else:
        if campaign_id != record.campaign_id:
            raise ValueError("CATALOG_REQUEST_RECEIPT_NONEXECUTING_BINDING_INVALID")
        if record.state in {
            AuthorityState.RESERVED,
            AuthorityState.RUNNING,
            AuthorityState.RECOVERING,
            AuthorityState.WAITING_RETRY,
        }:
            if state != "DEFERRED":
                raise ValueError("CATALOG_REQUEST_RECEIPT_NONEXECUTING_BINDING_INVALID")
            terminal_decision = None
        else:
            expected_state = record.state.value.upper()
            if state != expected_state or record.evidence_sha256 is None:
                raise ValueError("CATALOG_REQUEST_RECEIPT_NONEXECUTING_BINDING_INVALID")
            terminal_decision = record.evidence_sha256
    return _build_receipt(
        state=state,
        reason_code=reason_code,
        issue_number=issue_number,
        delivery_sequence=delivery_sequence,
        request_sha256=request_sha256,
        campaign_id=campaign_id,
        authority_record=record,
        terminal_decision_sha256=terminal_decision,
        writer_run_id=writer.run_id,
        writer_run_attempt=writer.run_attempt,
        writer_job_id="report_nonexecuting_decision",
        writer_job_database_id=writer.writer_job_database_id,
        protected_commit_sha=writer.protected_commit_sha,
        created_at=writer.observed_at,
        retry_not_before=retry_not_before,
        summary=summary,
    )


def build_waiting_retry_request_receipt(
    *,
    authority_candidate: CatalogAuthorityTransitionCandidateV1,
    engine_outcome: CatalogEngineOutcomeV1,
    summary: str,
    delivery_sequence: int = 0,
) -> CatalogRequestReceiptV1:
    """Bind one waiting status to the exact engine evidence and ledger record."""

    candidate = CatalogAuthorityTransitionCandidateV1.model_validate(
        authority_candidate.model_dump(mode="json")
    )
    outcome = CatalogEngineOutcomeV1.model_validate(
        engine_outcome.model_dump(mode="json")
    )
    record = candidate.record
    if (
        candidate.mode != "waiting_retry"
        or record.state is not AuthorityState.WAITING_RETRY
        or record.writer_job_id != "record_nonterminal_wait"
        or outcome.state is not CatalogEngineOutcomeState.WAITING_RETRY
        or record.request_sha256 != outcome.request_sha256
        or record.authority_id != outcome.authority_id
        or record.campaign_id != outcome.campaign_id
        or record.science_sha256 != outcome.science_sha256
        or record.execution_plan_sha256 != outcome.execution_plan_sha256
        or record.execution_protocol_sha256 != outcome.execution_protocol_sha256
        or record.protected_commit_sha != outcome.protected_commit_sha
        or record.evidence_sha256 != outcome.evidence_sha256
        or record.failure_fingerprint != outcome.failure_fingerprint
        or record.failure_occurrence_count != outcome.failure_occurrence_count
        or record.reason_code != outcome.reason_code
    ):
        raise ValueError("CATALOG_REQUEST_RECEIPT_WAITING_BINDING_INVALID")
    return _build_receipt(
        state="WAITING_RETRY",
        reason_code=outcome.reason_code,
        issue_number=record.request_issue_number,
        delivery_sequence=delivery_sequence,
        request_sha256=record.request_sha256,
        campaign_id=record.campaign_id,
        authority_record=record,
        terminal_decision_sha256=None,
        writer_run_id=record.run_id,
        writer_run_attempt=record.run_attempt,
        writer_job_id="record_nonterminal_wait",
        writer_job_database_id=record.writer_job_database_id,
        protected_commit_sha=record.protected_commit_sha,
        created_at=record.created_at,
        retry_not_before=outcome.retry_not_before,
        summary=summary,
    )


__all__ = [
    "CatalogRequestReceiptV1",
    "MAX_REQUEST_RECEIPT_SEQUENCE",
    "REQUEST_RECEIPT_MARKER",
    "build_nonexecuting_request_receipt",
    "build_terminal_request_receipt",
    "build_waiting_retry_request_receipt",
    "parse_request_receipt_comment",
    "next_request_receipt_sequence",
    "request_receipt_artifact_name",
    "verify_request_receipt_writer_provenance",
]
