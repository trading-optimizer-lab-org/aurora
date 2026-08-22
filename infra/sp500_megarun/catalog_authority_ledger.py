"""Fail-closed, hash-chained authority ledger for catalog campaigns."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import Enum
import hashlib
import json
import re
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, field_validator, model_validator

from .catalog_request_contract import FrozenModel, Sha256


AUTHORITY_COMMENT_START = "<!-- AURORA_CATALOG_AUTHORITY_V1 -->"
AUTHORITY_COMMENT_END = "<!-- /AURORA_CATALOG_AUTHORITY_V1 -->"
AUTHORITY_REPOSITORY = "trading-optimizer-lab-org/aurora"
AUTHORITY_TITLE = "AURORA CATALOG AUTHORITY LEDGER - DO NOT EDIT"
LEDGER_ACTOR = "github-actions[bot]"
_TERMINAL_STATES = frozenset({"success", "failed", "blocked"})
_ALLOWED_WORKFLOWS = frozenset(
    {
        ".github/workflows/catalog-run-controller.yml",
        ".github/workflows/catalog-request-reconciler.yml",
        ".github/workflows/catalog-ledger-guard.yml",
        ".github/workflows/catalog-run-watchdog.yml",
    }
)
_ALLOWED_EVENTS = frozenset(
    {"issues", "issue_comment", "workflow_call", "workflow_run", "schedule"}
)
_STATE_WRITER_JOBS: dict[str, frozenset[str]] = {
    "reserved": frozenset({"reserve"}),
    "running": frozenset({"record_running"}),
    "recovering": frozenset({"reserve", "record_nonterminal_wait", "finalize"}),
    "waiting_retry": frozenset({"record_nonterminal_wait", "finalize"}),
    "success": frozenset({"finalize"}),
    "failed": frozenset({"finalize"}),
    "blocked": frozenset(
        {
            "issue_tamper_guard",
            "report_nonexecuting_decision",
            "record_nonterminal_wait",
            "finalize",
        }
    ),
}
_TRANSITIONS: dict[str, frozenset[str]] = {
    "reserved": frozenset({"running", "blocked"}),
    "running": frozenset(
        {"running", "recovering", "waiting_retry", "success", "failed", "blocked"}
    ),
    "recovering": frozenset({"recovering", "waiting_retry", "success", "failed", "blocked"}),
    "waiting_retry": frozenset({"recovering", "blocked"}),
}
_FORBIDDEN_AUTHORITY_LIFECYCLE_EVENTS = frozenset(
    {"edited", "deleted", "transferred", "closed", "reopened", "locked", "unlocked"}
)
_REQUEST_LIFECYCLE_MUTATIONS = frozenset(
    {
        "edited",
        "deleted",
        "transferred",
        "closed",
        "reopened",
        "renamed",
        "locked",
        "unlocked",
        "labeled",
        "unlabeled",
    }
)
_UNSET = object()


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


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _record_hash_payload(value: Mapping[str, object]) -> dict[str, object]:
    return {key: item for key, item in value.items() if key != "record_sha256"}


def _checkpoint_hash_payload(value: Mapping[str, object]) -> dict[str, object]:
    return {key: item for key, item in value.items() if key != "checkpoint_sha256"}


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp missing")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    return _aware_utc(datetime.fromisoformat(candidate))


def _mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="python")
        if isinstance(dumped, Mapping):
            return dumped
    raise ValueError("expected mapping")


class AuthorityState(str, Enum):
    RESERVED = "reserved"
    RUNNING = "running"
    RECOVERING = "recovering"
    WAITING_RETRY = "waiting_retry"
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"


class CatalogAuthorityRecordV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    sequence: int = Field(ge=0)
    previous_record_sha256: Sha256 | None
    record_sha256: Sha256
    authority_id: UUID
    request_issue_number: int = Field(ge=1)
    campaign_id: Sha256
    request_sha256: Sha256
    science_sha256: Sha256
    execution_plan_sha256: Sha256
    execution_protocol_sha256: Sha256
    state: AuthorityState
    run_id: int = Field(ge=1)
    run_attempt: int = Field(ge=1)
    writer_job_id: str = Field(min_length=1, max_length=128)
    writer_job_database_id: int = Field(ge=1)
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    failure_fingerprint: Sha256 | None
    failure_occurrence_count: int = Field(ge=0, le=3)
    reason_code: str | None
    evidence_sha256: Sha256 | None
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _require_utc_timestamp(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _verify_internal_integrity(self) -> "CatalogAuthorityRecordV1":
        payload = self.model_dump(mode="json")
        if self.record_sha256 != _canonical_sha256(_record_hash_payload(payload)):
            raise ValueError("CATALOG_LEDGER_HASH_INVALID")
        if (self.sequence == 0) != (self.previous_record_sha256 is None):
            raise ValueError("CATALOG_LEDGER_CHAIN_INVALID")
        if (self.failure_fingerprint is None) != (self.failure_occurrence_count == 0):
            raise ValueError("CATALOG_FAILURE_COUNT_INVALID")
        if self.failure_occurrence_count == 3 and self.state is not AuthorityState.BLOCKED:
            raise ValueError("CATALOG_FAILURE_LIMIT_REACHED")
        if self.state.value in _TERMINAL_STATES and self.evidence_sha256 is None:
            raise ValueError("CATALOG_AUTHORITY_TERMINAL_EVIDENCE_REQUIRED")
        return self

    @property
    def artifact_name(self) -> str:
        return f"catalog-authority-ledger-{self.authority_id}-{self.sequence:010d}"

    def to_comment(self) -> str:
        return (
            f"{AUTHORITY_COMMENT_START}\n"
            f"{_canonical_bytes(self).decode('utf-8')}\n"
            f"{AUTHORITY_COMMENT_END}"
        )


class CatalogAuthorityCheckpointV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    covered_through_sequence: int = Field(ge=0)
    record_count: int = Field(ge=1)
    root_record_sha256: Sha256
    tail_record_sha256: Sha256
    records: tuple[CatalogAuthorityRecordV1, ...]
    writer_provenance_sha256s: tuple[Sha256, ...]
    ledger_prefix_sha256: Sha256
    created_at: datetime
    expires_at: datetime
    checkpoint_sha256: Sha256

    @field_validator("created_at", "expires_at")
    @classmethod
    def _require_utc_timestamp(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _verify_checkpoint_integrity(self) -> "CatalogAuthorityCheckpointV1":
        if self.expires_at <= self.created_at:
            raise ValueError("CATALOG_AUTHORITY_CHECKPOINT_INVALID")
        if self.record_count != len(self.records) or not self.records:
            raise ValueError("CATALOG_AUTHORITY_CHECKPOINT_INVALID")
        _verify_record_sequence(self.records)
        if self.covered_through_sequence != self.records[-1].sequence:
            raise ValueError("CATALOG_AUTHORITY_CHECKPOINT_INVALID")
        if self.root_record_sha256 != self.records[0].record_sha256:
            raise ValueError("CATALOG_AUTHORITY_CHECKPOINT_INVALID")
        if self.tail_record_sha256 != self.records[-1].record_sha256:
            raise ValueError("CATALOG_AUTHORITY_CHECKPOINT_INVALID")
        if len(set(self.writer_provenance_sha256s)) != len(self.writer_provenance_sha256s):
            raise ValueError("CATALOG_AUTHORITY_CHECKPOINT_INVALID")
        if len(self.writer_provenance_sha256s) != len({record.run_id for record in self.records}):
            raise ValueError("CATALOG_AUTHORITY_CHECKPOINT_INVALID")
        prefix_payload = {
            "record_sha256s": [record.record_sha256 for record in self.records],
            "writer_provenance_sha256s": list(self.writer_provenance_sha256s),
        }
        if self.ledger_prefix_sha256 != _canonical_sha256(prefix_payload):
            raise ValueError("CATALOG_AUTHORITY_CHECKPOINT_INVALID")
        payload = self.model_dump(mode="json")
        if self.checkpoint_sha256 != _canonical_sha256(_checkpoint_hash_payload(payload)):
            raise ValueError("CATALOG_AUTHORITY_CHECKPOINT_INVALID")
        return self

    @classmethod
    def build(
        cls,
        *,
        records: Sequence[CatalogAuthorityRecordV1],
        writer_provenance_sha256s: Sequence[str],
        created_at: datetime,
        expires_at: datetime,
    ) -> "CatalogAuthorityCheckpointV1":
        checked_records = tuple(_validated_record(record) for record in records)
        _verify_record_sequence(checked_records)
        writer_hashes = tuple(writer_provenance_sha256s)
        prefix_payload = {
            "record_sha256s": [record.record_sha256 for record in checked_records],
            "writer_provenance_sha256s": list(writer_hashes),
        }
        payload: dict[str, object] = {
            "schema_version": "1",
            "covered_through_sequence": checked_records[-1].sequence,
            "record_count": len(checked_records),
            "root_record_sha256": checked_records[0].record_sha256,
            "tail_record_sha256": checked_records[-1].record_sha256,
            "records": [record.model_dump(mode="json") for record in checked_records],
            "writer_provenance_sha256s": list(writer_hashes),
            "ledger_prefix_sha256": _canonical_sha256(prefix_payload),
            "created_at": _aware_utc(created_at).isoformat().replace("+00:00", "Z"),
            "expires_at": _aware_utc(expires_at).isoformat().replace("+00:00", "Z"),
        }
        payload["checkpoint_sha256"] = _canonical_sha256(payload)
        return cls.model_validate(payload)

    @property
    def artifact_name(self) -> str:
        return f"catalog-authority-checkpoint-{self.tail_record_sha256}"


class VerifiedAuthorityLedgerV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    records: tuple[CatalogAuthorityRecordV1, ...]
    verified_writer_run_ids: tuple[int, ...]
    ledger_sha256: Sha256

    @model_validator(mode="after")
    def _verify_ledger(self) -> "VerifiedAuthorityLedgerV1":
        _verify_record_sequence(self.records)
        if tuple(sorted(set(self.verified_writer_run_ids))) != self.verified_writer_run_ids:
            raise ValueError("CATALOG_LEDGER_WRITER_PROVENANCE_INVALID")
        expected = _canonical_sha256(
            {
                "schema_version": "1",
                "record_sha256s": [record.record_sha256 for record in self.records],
                "verified_writer_run_ids": list(self.verified_writer_run_ids),
            }
        )
        if self.ledger_sha256 != expected:
            raise ValueError("CATALOG_LEDGER_HASH_INVALID")
        return self

    @property
    def latest(self) -> CatalogAuthorityRecordV1 | None:
        return self.records[-1] if self.records else None

    @classmethod
    def from_records(
        cls,
        records: Sequence[CatalogAuthorityRecordV1],
        *,
        verified_writer_run_ids: Sequence[int] = (),
    ) -> "VerifiedAuthorityLedgerV1":
        checked = tuple(_validated_record(record) for record in records)
        _verify_record_sequence(checked)
        run_ids = tuple(sorted(set(verified_writer_run_ids)))
        payload = {
            "schema_version": "1",
            "record_sha256s": [record.record_sha256 for record in checked],
            "verified_writer_run_ids": list(run_ids),
        }
        return cls(
            records=checked,
            verified_writer_run_ids=run_ids,
            ledger_sha256=_canonical_sha256(payload),
        )


class CatalogControllerActorsV1(FrozenModel):
    schema_version: Literal["1"]
    production_enabled: bool
    request_actors: tuple[str, ...]
    required_request_actor_kind: Literal["non_admin_github_app"]
    requester_public_key_path: Literal["config/catalog_requester_public_key_v1.pem"] | None
    requester_public_key_sha256: Sha256 | None
    ledger_actor: Literal["github-actions[bot]"]
    authority_issue_repository_variable: Literal["CATALOG_AUTHORITY_ISSUE_NUMBER"]
    deny_actor_if_repository_admin_credential_is_exposed: Literal[True]

    @model_validator(mode="after")
    def _verify_actor_separation(self) -> "CatalogControllerActorsV1":
        if len(set(self.request_actors)) != len(self.request_actors):
            raise ValueError("CATALOG_REQUEST_ACTOR_INVALID")
        for actor in self.request_actors:
            if (
                actor != actor.casefold()
                or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\[bot\]", actor)
                or actor == self.ledger_actor
            ):
                raise ValueError("CATALOG_REQUEST_ACTOR_INVALID")
        if (self.requester_public_key_path is None) != (self.requester_public_key_sha256 is None):
            raise ValueError("CATALOG_REQUESTER_PUBLIC_KEY_INVALID")
        if self.production_enabled and (
            not self.request_actors
            or self.requester_public_key_path is None
            or self.requester_public_key_sha256 is None
        ):
            raise ValueError("CATALOG_REQUEST_ACTOR_NOT_BOOTSTRAPPED")
        return self


class CatalogAuthorityAnchorV1(FrozenModel):
    schema_version: Literal["1"]
    production_enabled: bool
    repository: Literal["trading-optimizer-lab-org/aurora"]
    repository_node_id: str | None
    issue_number: int | None = Field(default=None, ge=1)
    issue_node_id: str | None
    exact_title: Literal["AURORA CATALOG AUTHORITY LEDGER - DO NOT EDIT"]
    creator_login: str | None
    created_at: datetime | None

    @field_validator("created_at")
    @classmethod
    def _require_utc_timestamp(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware_utc(value)

    @model_validator(mode="after")
    def _verify_anchor_completeness(self) -> "CatalogAuthorityAnchorV1":
        identities = (
            self.repository_node_id,
            self.issue_number,
            self.issue_node_id,
            self.creator_login,
            self.created_at,
        )
        if self.production_enabled and any(value is None for value in identities):
            raise ValueError("CATALOG_AUTHORITY_ANCHOR_INVALID")
        return self


class CatalogAuthorityMirrorReconciliationV1(FrozenModel):
    status: Literal["verified", "repair_required"]
    missing_comment_records: tuple[CatalogAuthorityRecordV1, ...] = ()
    missing_artifact_records: tuple[CatalogAuthorityRecordV1, ...] = ()
    covered_through_sequence: int = Field(ge=-1)
    safe_to_schedule_compute: bool


class CatalogRequestTamperReconciliationV1(FrozenModel):
    authority_blocked: bool
    request_ui_untrusted: bool
    blocked_request_numbers: tuple[int, ...]


class CatalogRequestLifecycleReconciliationV1(FrozenModel):
    authority_blocked: bool
    request_ui_untrusted: bool
    atomic_terminal_close_verified: bool
    reason_code: str


class CatalogAuthorityIssueTamperReconciliationV1(FrozenModel):
    all_catalog_authorities_blocked: bool
    recreate_authority_issue_allowed: Literal[False]
    append_to_damaged_authority_allowed: bool
    reason_code: str


class CatalogAuthorityAnchorVerificationV1(FrozenModel):
    status: Literal["ready"]
    repository: Literal["trading-optimizer-lab-org/aurora"]
    issue_number: int = Field(ge=1)
    issue_node_id: str


def _validated_record(record: CatalogAuthorityRecordV1) -> CatalogAuthorityRecordV1:
    try:
        return CatalogAuthorityRecordV1.model_validate(record.model_dump(mode="json"))
    except Exception as exc:
        message = str(exc)
        if "CATALOG_LEDGER_HASH_INVALID" in message:
            raise ValueError("CATALOG_LEDGER_HASH_INVALID") from None
        raise ValueError(f"CATALOG_LEDGER_RECORD_INVALID: {exc}") from None


def _verify_identity_transition(
    previous: CatalogAuthorityRecordV1,
    current: CatalogAuthorityRecordV1,
) -> None:
    if previous.state.value in _TERMINAL_STATES:
        raise ValueError("CATALOG_AUTHORITY_TERMINAL")
    if current.state.value not in _TRANSITIONS[previous.state.value]:
        raise ValueError("CATALOG_AUTHORITY_TRANSITION_INVALID")

    immutable_fields = (
        "request_issue_number",
        "campaign_id",
        "request_sha256",
        "science_sha256",
        "execution_protocol_sha256",
    )
    if any(getattr(previous, field) != getattr(current, field) for field in immutable_fields):
        if previous.execution_protocol_sha256 != current.execution_protocol_sha256:
            raise ValueError("CATALOG_EXECUTION_PROTOCOL_CHANGED")
        raise ValueError("CATALOG_AUTHORITY_IDENTITY_CHANGED")
    if previous.execution_plan_sha256 != current.execution_plan_sha256 and (
        current.state not in {AuthorityState.RECOVERING, AuthorityState.WAITING_RETRY}
        or current.evidence_sha256 is None
    ):
        raise ValueError("CATALOG_OPERATIONAL_REPLAN_UNPROVEN")
    _verify_failure_evolution(previous, current)


def _verify_failure_evolution(
    previous: CatalogAuthorityRecordV1,
    current: CatalogAuthorityRecordV1,
) -> None:
    previous_pair = (
        previous.failure_fingerprint,
        previous.failure_occurrence_count,
    )
    current_pair = (current.failure_fingerprint, current.failure_occurrence_count)
    if current_pair == previous_pair:
        return
    if current.failure_fingerprint is None:
        raise ValueError("CATALOG_FAILURE_COUNT_INVALID")
    if current.failure_fingerprint == previous.failure_fingerprint:
        expected = previous.failure_occurrence_count + 1
    else:
        expected = 1
    if current.failure_occurrence_count != expected or expected > 3:
        raise ValueError("CATALOG_FAILURE_COUNT_INVALID")
    if expected == 3 and current.state is not AuthorityState.BLOCKED:
        raise ValueError("CATALOG_FAILURE_LIMIT_REACHED")


def _verify_record_sequence(records: Sequence[CatalogAuthorityRecordV1]) -> None:
    latest_by_authority: dict[UUID, CatalogAuthorityRecordV1] = {}
    for index, raw_record in enumerate(records):
        record = _validated_record(raw_record)
        if record.sequence != index:
            raise ValueError("CATALOG_LEDGER_SEQUENCE_GAP")
        expected_previous = None if index == 0 else records[index - 1].record_sha256
        if record.previous_record_sha256 != expected_previous:
            raise ValueError("CATALOG_LEDGER_CHAIN_INVALID")
        previous_authority = latest_by_authority.get(record.authority_id)
        if previous_authority is None:
            if record.state is not AuthorityState.RESERVED:
                raise ValueError("CATALOG_AUTHORITY_TRANSITION_INVALID")
        else:
            _verify_identity_transition(previous_authority, record)
        latest_by_authority[record.authority_id] = record


def append_authority_record(
    *,
    previous: CatalogAuthorityRecordV1 | None,
    state: AuthorityState | str,
    created_at: datetime,
    authority_id: UUID | str | None = None,
    request_issue_number: int | None = None,
    campaign_id: str | None = None,
    request_sha256: str | None = None,
    science_sha256: str | None = None,
    execution_plan_sha256: str | None = None,
    execution_protocol_sha256: str | None = None,
    run_id: int | None = None,
    run_attempt: int | None = None,
    writer_job_id: str | None = None,
    writer_job_database_id: int | None = None,
    protected_commit_sha: str | None = None,
    failure_fingerprint: str | None | object = _UNSET,
    failure_occurrence_count: int | None = None,
    reason_code: str | None = None,
    evidence_sha256: str | None = None,
    safe_operational_replan: bool = False,
) -> CatalogAuthorityRecordV1:
    state = AuthorityState(state)
    if previous is not None:
        previous = _validated_record(previous)

    parsed_authority_id = UUID(str(authority_id)) if authority_id is not None else None
    is_new_authority = previous is None or (
        parsed_authority_id is not None and parsed_authority_id != previous.authority_id
    )
    if is_new_authority:
        if state is not AuthorityState.RESERVED:
            raise ValueError("CATALOG_AUTHORITY_TRANSITION_INVALID")
        request_issue_number = 1 if request_issue_number is None else request_issue_number
        required_identity = {
            "campaign_id": campaign_id,
            "request_sha256": request_sha256,
            "science_sha256": science_sha256,
            "execution_plan_sha256": execution_plan_sha256,
            "execution_protocol_sha256": execution_protocol_sha256,
            "run_id": run_id,
            "run_attempt": run_attempt,
            "writer_job_id": writer_job_id,
            "writer_job_database_id": writer_job_database_id,
            "protected_commit_sha": protected_commit_sha,
        }
        missing = [name for name, value in required_identity.items() if value is None]
        if missing:
            raise ValueError("CATALOG_AUTHORITY_RECORD_INCOMPLETE: " + ",".join(missing))
        if parsed_authority_id is None:
            parsed_authority_id = uuid5(
                NAMESPACE_URL,
                f"aurora-catalog:{request_issue_number}:{request_sha256}:{campaign_id}",
            )
        selected_failure = None if failure_fingerprint is _UNSET else failure_fingerprint
        selected_count = 0 if failure_occurrence_count is None else failure_occurrence_count
        if selected_failure is not None or selected_count != 0:
            raise ValueError("CATALOG_FAILURE_COUNT_INVALID")
        sequence = 0 if previous is None else previous.sequence + 1
        previous_sha = None if previous is None else previous.record_sha256
    else:
        assert previous is not None
        parsed_authority_id = previous.authority_id
        if previous.state.value in _TERMINAL_STATES:
            raise ValueError("CATALOG_AUTHORITY_TERMINAL")
        if state.value not in _TRANSITIONS[previous.state.value]:
            raise ValueError("CATALOG_AUTHORITY_TRANSITION_INVALID")

        supplied_identity = {
            "request_issue_number": request_issue_number,
            "campaign_id": campaign_id,
            "request_sha256": request_sha256,
            "science_sha256": science_sha256,
        }
        for name, supplied in supplied_identity.items():
            if supplied is not None and supplied != getattr(previous, name):
                raise ValueError("CATALOG_AUTHORITY_IDENTITY_CHANGED")
        if (
            execution_protocol_sha256 is not None
            and execution_protocol_sha256 != previous.execution_protocol_sha256
        ):
            raise ValueError("CATALOG_EXECUTION_PROTOCOL_CHANGED")
        if (
            execution_plan_sha256 is not None
            and execution_plan_sha256 != previous.execution_plan_sha256
            and not safe_operational_replan
        ):
            raise ValueError("CATALOG_OPERATIONAL_REPLAN_UNPROVEN")
        if (
            execution_plan_sha256 is not None
            and execution_plan_sha256 != previous.execution_plan_sha256
            and evidence_sha256 is None
        ):
            raise ValueError("CATALOG_OPERATIONAL_REPLAN_UNPROVEN")

        request_issue_number = previous.request_issue_number
        campaign_id = previous.campaign_id
        request_sha256 = previous.request_sha256
        science_sha256 = previous.science_sha256
        execution_plan_sha256 = (
            previous.execution_plan_sha256
            if execution_plan_sha256 is None
            else execution_plan_sha256
        )
        execution_protocol_sha256 = previous.execution_protocol_sha256
        run_id = previous.run_id if run_id is None else run_id
        run_attempt = previous.run_attempt if run_attempt is None else run_attempt
        writer_job_id = previous.writer_job_id if writer_job_id is None else writer_job_id
        writer_job_database_id = (
            previous.writer_job_database_id
            if writer_job_database_id is None
            else writer_job_database_id
        )
        protected_commit_sha = (
            previous.protected_commit_sha if protected_commit_sha is None else protected_commit_sha
        )
        reason_code = reason_code if reason_code is not None else previous.reason_code
        evidence_sha256 = (
            evidence_sha256 if evidence_sha256 is not None else previous.evidence_sha256
        )

        if failure_fingerprint is _UNSET and failure_occurrence_count is None:
            selected_failure = previous.failure_fingerprint
            selected_count = previous.failure_occurrence_count
        else:
            selected_failure = (
                previous.failure_fingerprint
                if failure_fingerprint is _UNSET
                else failure_fingerprint
            )
            if failure_occurrence_count is None:
                selected_count = (
                    previous.failure_occurrence_count + 1
                    if selected_failure == previous.failure_fingerprint
                    else 1
                )
            else:
                selected_count = failure_occurrence_count
            if selected_failure is None:
                raise ValueError("CATALOG_FAILURE_COUNT_INVALID")
            expected = (
                previous.failure_occurrence_count + 1
                if selected_failure == previous.failure_fingerprint
                else 1
            )
            if selected_count != expected or selected_count > 3:
                raise ValueError("CATALOG_FAILURE_COUNT_INVALID")
            if selected_count == 3 and state is not AuthorityState.BLOCKED:
                raise ValueError("CATALOG_FAILURE_LIMIT_REACHED")
        sequence = previous.sequence + 1
        previous_sha = previous.record_sha256

    payload: dict[str, object] = {
        "schema_version": "1",
        "sequence": sequence,
        "previous_record_sha256": previous_sha,
        "authority_id": str(parsed_authority_id),
        "request_issue_number": request_issue_number,
        "campaign_id": campaign_id,
        "request_sha256": request_sha256,
        "science_sha256": science_sha256,
        "execution_plan_sha256": execution_plan_sha256,
        "execution_protocol_sha256": execution_protocol_sha256,
        "state": state.value,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "writer_job_id": writer_job_id,
        "writer_job_database_id": writer_job_database_id,
        "protected_commit_sha": protected_commit_sha,
        "failure_fingerprint": selected_failure,
        "failure_occurrence_count": selected_count,
        "reason_code": reason_code,
        "evidence_sha256": evidence_sha256,
        "created_at": _aware_utc(created_at).isoformat().replace("+00:00", "Z"),
    }
    payload["record_sha256"] = _canonical_sha256(payload)
    return CatalogAuthorityRecordV1.model_validate(payload)


def _extract_comment_record(
    comment: Mapping[str, object],
    *,
    expected_author: str,
) -> CatalogAuthorityRecordV1 | None:
    body = comment.get("body")
    if not isinstance(body, str):
        return None
    has_marker = AUTHORITY_COMMENT_START in body or AUTHORITY_COMMENT_END in body
    if not has_marker:
        return None
    expected_prefix = AUTHORITY_COMMENT_START + "\n"
    expected_suffix = "\n" + AUTHORITY_COMMENT_END
    if not body.startswith(expected_prefix) or not body.endswith(expected_suffix):
        raise ValueError("CATALOG_LEDGER_COMMENT_FORMAT_INVALID")
    author = _mapping(comment.get("user", {})).get("login")
    if author != expected_author:
        raise ValueError("CATALOG_LEDGER_AUTHOR_INVALID")
    try:
        created_at = _parse_datetime(comment.get("created_at"))
        updated_at = _parse_datetime(comment.get("updated_at"))
    except Exception:
        raise ValueError("CATALOG_LEDGER_COMMENT_TIMESTAMP_INVALID") from None
    if created_at != updated_at:
        raise ValueError("CATALOG_LEDGER_COMMENT_EDITED")
    raw_payload = body[len(expected_prefix) : -len(expected_suffix)]
    try:
        payload = json.loads(
            raw_payload,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
        return CatalogAuthorityRecordV1.model_validate(payload)
    except Exception as exc:
        message = str(exc)
        if "CATALOG_LEDGER_HASH_INVALID" in message:
            raise ValueError("CATALOG_LEDGER_HASH_INVALID") from None
        raise ValueError(f"CATALOG_LEDGER_COMMENT_FORMAT_INVALID: {exc}") from None


def _snapshot_map(
    snapshots: Mapping[object, object] | Sequence[object],
) -> dict[int, Mapping[str, Any]]:
    result: dict[int, Mapping[str, Any]] = {}
    values: Sequence[object]
    if isinstance(snapshots, Mapping):
        values = tuple(snapshots.values())
    else:
        values = snapshots
    for raw in values:
        snapshot = _mapping(raw)
        run_id = snapshot.get("run_id", snapshot.get("id"))
        if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1:
            raise ValueError("CATALOG_LEDGER_WRITER_PROVENANCE_INVALID")
        if run_id in result:
            raise ValueError("CATALOG_LEDGER_WRITER_PROVENANCE_INVALID")
        result[run_id] = snapshot
    return result


def _verify_writer_record(
    record: CatalogAuthorityRecordV1,
    snapshot: Mapping[str, Any],
    *,
    expected_repository: str,
    allowed_workflow_paths: frozenset[str],
) -> None:
    try:
        required_flags = (
            "complete",
            "pagination_complete",
            "stable",
            "authenticated",
            "workflow_policy_verified",
        )
        if any(snapshot.get(flag) is not True for flag in required_flags):
            raise ValueError
        if not isinstance(snapshot.get("etag"), str) or not snapshot["etag"]:
            raise ValueError
        if snapshot.get("run_id", snapshot.get("id")) != record.run_id:
            raise ValueError
        if snapshot.get("run_attempt", snapshot.get("attempt")) != record.run_attempt:
            raise ValueError
        if snapshot.get("head_sha") != record.protected_commit_sha:
            raise ValueError
        workflow_path = snapshot.get("workflow_path", snapshot.get("path"))
        if workflow_path not in allowed_workflow_paths:
            raise ValueError
        if snapshot.get("event") not in _ALLOWED_EVENTS:
            raise ValueError
        repository = snapshot.get("repository", snapshot.get("repository_full_name"))
        if repository != expected_repository:
            raise ValueError
        raw_jobs = snapshot.get("jobs")
        if not isinstance(raw_jobs, Sequence) or isinstance(raw_jobs, (str, bytes)):
            raise ValueError
        matches: list[Mapping[str, Any]] = []
        for raw_job in raw_jobs:
            job = _mapping(raw_job)
            logical_id = job.get("job_id", job.get("logical_job_id"))
            database_id = job.get("database_id", job.get("id"))
            if logical_id == record.writer_job_id and database_id == record.writer_job_database_id:
                matches.append(job)
        if len(matches) != 1:
            raise ValueError
        job = matches[0]
        if record.writer_job_id not in _STATE_WRITER_JOBS[record.state.value]:
            raise ValueError
        allowed_states = job.get("allowed_states")
        if (
            not isinstance(allowed_states, Sequence)
            or isinstance(allowed_states, (str, bytes))
            or record.state.value not in allowed_states
        ):
            raise ValueError
        if job.get("issues_write") is not True:
            raise ValueError
        if job.get("steps_are_allowlisted") is not True:
            raise ValueError
    except Exception:
        raise ValueError("CATALOG_LEDGER_WRITER_PROVENANCE_INVALID") from None


def extract_authority_comment_records(
    comments: Sequence[Mapping[str, object]],
    *,
    expected_author: str,
) -> tuple[CatalogAuthorityRecordV1, ...]:
    """Parse and chain-check records before fetching their writer runs."""

    if expected_author != LEDGER_ACTOR:
        raise ValueError("CATALOG_LEDGER_AUTHOR_INVALID")
    records = tuple(
        record
        for comment in comments
        if (record := _extract_comment_record(comment, expected_author=expected_author))
        is not None
    )
    ordered = tuple(sorted(records, key=lambda record: record.sequence))
    sequences = [record.sequence for record in ordered]
    if len(sequences) != len(set(sequences)):
        raise ValueError("CATALOG_LEDGER_SEQUENCE_DUPLICATE")
    _verify_record_sequence(ordered)
    return ordered


def parse_authority_comments(
    comments: Sequence[Mapping[str, object]],
    *,
    expected_author: str,
    writer_run_snapshots: Mapping[object, object] | Sequence[object],
    expected_repository: str = AUTHORITY_REPOSITORY,
    allowed_workflow_paths: Sequence[str] = tuple(_ALLOWED_WORKFLOWS),
) -> VerifiedAuthorityLedgerV1:
    if expected_author != LEDGER_ACTOR:
        raise ValueError("CATALOG_LEDGER_AUTHOR_INVALID")
    ordered = extract_authority_comment_records(
        comments,
        expected_author=expected_author,
    )

    try:
        snapshots = _snapshot_map(writer_run_snapshots)
    except Exception:
        raise ValueError("CATALOG_LEDGER_WRITER_PROVENANCE_INVALID") from None
    allowed_paths = frozenset(allowed_workflow_paths)
    verified_run_ids: set[int] = set()
    for record in ordered:
        snapshot = snapshots.get(record.run_id)
        if snapshot is None:
            raise ValueError("CATALOG_LEDGER_WRITER_PROVENANCE_INVALID")
        _verify_writer_record(
            record,
            snapshot,
            expected_repository=expected_repository,
            allowed_workflow_paths=allowed_paths,
        )
        verified_run_ids.add(record.run_id)
    return VerifiedAuthorityLedgerV1.from_records(
        ordered,
        verified_writer_run_ids=tuple(sorted(verified_run_ids)),
    )


def verify_authority_checkpoint(
    checkpoint: CatalogAuthorityCheckpointV1,
    *,
    live_records: Sequence[CatalogAuthorityRecordV1],
    now: datetime,
) -> CatalogAuthorityCheckpointV1:
    try:
        checked = CatalogAuthorityCheckpointV1.model_validate(checkpoint.model_dump(mode="json"))
        if checked.expires_at <= _aware_utc(now):
            raise ValueError
        live = tuple(_validated_record(record) for record in live_records)
        if len(live) < checked.record_count:
            raise ValueError
        for expected, actual in zip(checked.records, live, strict=False):
            if _canonical_bytes(expected) != _canonical_bytes(actual):
                raise ValueError
        return checked
    except Exception:
        raise ValueError("CATALOG_AUTHORITY_CHECKPOINT_INVALID") from None


def _record_map(
    records: Sequence[CatalogAuthorityRecordV1],
    *,
    conflict_reason: str,
) -> dict[int, CatalogAuthorityRecordV1]:
    result: dict[int, CatalogAuthorityRecordV1] = {}
    for raw in records:
        record = _validated_record(raw)
        previous = result.get(record.sequence)
        if previous is not None and _canonical_bytes(previous) != _canonical_bytes(record):
            raise ValueError(conflict_reason)
        result[record.sequence] = record
    return result


def reconcile_authority_mirrors(
    *,
    comment_records: Sequence[CatalogAuthorityRecordV1],
    artifact_records: Sequence[CatalogAuthorityRecordV1],
    tamper_incidents: Sequence[object],
    checkpoints: Sequence[CatalogAuthorityCheckpointV1] = (),
    now: datetime,
) -> CatalogAuthorityMirrorReconciliationV1:
    for incident in tamper_incidents:
        data = _mapping(incident)
        if data.get("verified", True) is not True:
            raise ValueError("CATALOG_LEDGER_TAMPER_INCIDENT")
        if data.get("action") in {"edited", "deleted"}:
            raise ValueError("CATALOG_LEDGER_TAMPER_INCIDENT")

    comments = _record_map(
        comment_records,
        conflict_reason="CATALOG_LEDGER_MIRROR_CONFLICT",
    )
    artifacts = _record_map(
        artifact_records,
        conflict_reason="CATALOG_LEDGER_MIRROR_CONFLICT",
    )
    for sequence in comments.keys() & artifacts.keys():
        if _canonical_bytes(comments[sequence]) != _canonical_bytes(artifacts[sequence]):
            raise ValueError("CATALOG_LEDGER_MIRROR_CONFLICT")

    if comments:
        _verify_record_sequence(tuple(comments[index] for index in sorted(comments)))
    union = {**artifacts, **comments}
    if union:
        ordered_union = tuple(union[index] for index in sorted(union))
        try:
            _verify_record_sequence(ordered_union)
        except Exception:
            raise ValueError("CATALOG_LEDGER_MIRROR_COVERAGE_INVALID") from None
    else:
        ordered_union = ()

    verified_checkpoints: list[CatalogAuthorityCheckpointV1] = []
    for checkpoint in checkpoints:
        try:
            verified_checkpoints.append(
                verify_authority_checkpoint(
                    checkpoint,
                    live_records=ordered_union,
                    now=now,
                )
            )
        except Exception:
            raise ValueError("CATALOG_LEDGER_MIRROR_COVERAGE_INVALID") from None
    for index, left in enumerate(verified_checkpoints):
        for right in verified_checkpoints[index + 1 :]:
            overlap = min(left.record_count, right.record_count)
            if any(
                _canonical_bytes(a) != _canonical_bytes(b)
                for a, b in zip(left.records[:overlap], right.records[:overlap], strict=False)
            ):
                raise ValueError("CATALOG_LEDGER_MIRROR_COVERAGE_INVALID")
            if (
                left.covered_through_sequence == right.covered_through_sequence
                and left.ledger_prefix_sha256 != right.ledger_prefix_sha256
            ):
                raise ValueError("CATALOG_LEDGER_MIRROR_COVERAGE_INVALID")

    checkpoint_coverage = -1
    if verified_checkpoints:
        checkpoint_coverage = max(
            checkpoint.covered_through_sequence for checkpoint in verified_checkpoints
        )
    covered_sequences = set(artifacts)
    covered_sequences.update(range(checkpoint_coverage + 1))
    missing_artifacts = tuple(
        comments[index] for index in sorted(set(comments) - covered_sequences)
    )
    missing_comments = tuple(artifacts[index] for index in sorted(set(artifacts) - set(comments)))
    if len(missing_artifacts) > 1 or len(missing_comments) > 1:
        raise ValueError("CATALOG_LEDGER_MIRROR_COVERAGE_INVALID")

    contiguous_coverage = -1
    while contiguous_coverage + 1 in covered_sequences:
        contiguous_coverage += 1
    repair_required = bool(missing_artifacts or missing_comments)
    return CatalogAuthorityMirrorReconciliationV1(
        status="repair_required" if repair_required else "verified",
        missing_comment_records=missing_comments,
        missing_artifact_records=missing_artifacts,
        covered_through_sequence=contiguous_coverage,
        safe_to_schedule_compute=not repair_required,
    )


def reconcile_request_tamper(
    authority: CatalogAuthorityRecordV1,
    incidents: Sequence[object],
) -> CatalogRequestTamperReconciliationV1:
    authority = _validated_record(authority)
    blocked_numbers: set[int] = set()
    origin_tampered = False
    for incident in incidents:
        data = _mapping(incident)
        if data.get("verified", True) is not True:
            raise ValueError("CATALOG_REQUEST_TAMPER_INVALID")
        action = data.get("action")
        if action not in {"edited", "deleted"}:
            raise ValueError("CATALOG_REQUEST_TAMPER_INVALID")
        issue_number = data.get("issue_number")
        if isinstance(issue_number, bool) or not isinstance(issue_number, int):
            raise ValueError("CATALOG_REQUEST_TAMPER_INVALID")
        if data.get("kind") == "request_receipt_comment":
            provenance = data.get("original_receipt_writer_provenance")
            if not isinstance(provenance, Mapping) or provenance.get("verified") is not True:
                raise ValueError("CATALOG_REQUEST_TAMPER_PROVENANCE_INVALID")
        blocked_numbers.add(issue_number)
        if issue_number == authority.request_issue_number:
            origin_tampered = True
    terminal = authority.state.value in _TERMINAL_STATES
    return CatalogRequestTamperReconciliationV1(
        authority_blocked=origin_tampered and not terminal,
        request_ui_untrusted=origin_tampered,
        blocked_request_numbers=tuple(sorted(blocked_numbers)),
    )


def reconcile_request_lifecycle(
    authority: CatalogAuthorityRecordV1,
    *,
    complete_timeline: object | None,
    terminal_close_provenance: object | None,
) -> CatalogRequestLifecycleReconciliationV1:
    """Fail closed on restored request mutations and admit one proven final close."""

    authority = _validated_record(authority)
    terminal = authority.state.value in _TERMINAL_STATES
    if complete_timeline is None:
        return CatalogRequestLifecycleReconciliationV1(
            authority_blocked=not terminal,
            request_ui_untrusted=True,
            atomic_terminal_close_verified=False,
            reason_code="CATALOG_REQUEST_LIFECYCLE_HISTORY_UNAVAILABLE",
        )
    timeline = _mapping(complete_timeline)
    if any(
        timeline.get(flag) is not True for flag in ("complete", "pagination_complete", "stable")
    ):
        return CatalogRequestLifecycleReconciliationV1(
            authority_blocked=not terminal,
            request_ui_untrusted=True,
            atomic_terminal_close_verified=False,
            reason_code="CATALOG_REQUEST_LIFECYCLE_HISTORY_UNAVAILABLE",
        )
    raw_events = timeline.get("historical_events", timeline.get("events", ()))
    if not isinstance(raw_events, Sequence) or isinstance(raw_events, (str, bytes)):
        return CatalogRequestLifecycleReconciliationV1(
            authority_blocked=not terminal,
            request_ui_untrusted=True,
            atomic_terminal_close_verified=False,
            reason_code="CATALOG_REQUEST_LIFECYCLE_HISTORY_INVALID",
        )
    events: list[Mapping[str, object]] = []
    try:
        for event in raw_events:
            events.append(_mapping(event))
    except ValueError:
        return CatalogRequestLifecycleReconciliationV1(
            authority_blocked=not terminal,
            request_ui_untrusted=True,
            atomic_terminal_close_verified=False,
            reason_code="CATALOG_REQUEST_LIFECYCLE_HISTORY_INVALID",
        )
    mutations = tuple(
        event for event in events if event.get("event") in _REQUEST_LIFECYCLE_MUTATIONS
    )
    if not mutations:
        return CatalogRequestLifecycleReconciliationV1(
            authority_blocked=False,
            request_ui_untrusted=False,
            atomic_terminal_close_verified=False,
            reason_code="CATALOG_REQUEST_LIFECYCLE_VERIFIED",
        )

    proof = (
        _mapping(terminal_close_provenance)
        if isinstance(terminal_close_provenance, Mapping)
        else {}
    )
    mutation_names = tuple(str(event.get("event")) for event in mutations)
    expected_actor = proof.get("writer_actor")
    terminal_close_verified = (
        terminal
        and mutation_names == ("labeled", "closed")
        and timeline.get("current_state") == "closed"
        and timeline.get("current_state_reason") == "completed"
        and timeline.get("current_labels") == ["catalog-run-terminal-v1"]
        and mutations[0].get("label") == "catalog-run-terminal-v1"
        and isinstance(expected_actor, str)
        and expected_actor == "github-actions[bot]"
        and all(event.get("actor") == expected_actor for event in mutations)
        and proof.get("verified") is True
        and proof.get("atomic_patch") is True
        and proof.get("receipt_precedes_events") is True
        and proof.get("request_issue_number") == authority.request_issue_number
        and proof.get("authority_id") == str(authority.authority_id)
        and proof.get("terminal_state") == authority.state.value
        and proof.get("writer_run_job_commit_provenance_verified") is True
    )
    if terminal_close_verified:
        return CatalogRequestLifecycleReconciliationV1(
            authority_blocked=False,
            request_ui_untrusted=False,
            atomic_terminal_close_verified=True,
            reason_code="CATALOG_REQUEST_TERMINAL_CLOSE_VERIFIED",
        )
    return CatalogRequestLifecycleReconciliationV1(
        authority_blocked=not terminal,
        request_ui_untrusted=True,
        atomic_terminal_close_verified=False,
        reason_code="CATALOG_REQUEST_LIFECYCLE_TAMPERED",
    )


def reconcile_authority_issue_tamper(
    *,
    ledger: VerifiedAuthorityLedgerV1,
    incident: object | None,
    complete_timeline: object | None = None,
) -> CatalogAuthorityIssueTamperReconciliationV1:
    VerifiedAuthorityLedgerV1.model_validate(ledger.model_dump(mode="json"))
    if incident is not None:
        data = _mapping(incident)
        action = data.get("action")
        if data.get("verified", True) is not True or action not in (
            _FORBIDDEN_AUTHORITY_LIFECYCLE_EVENTS
        ):
            reason = "CATALOG_AUTHORITY_LIFECYCLE_HISTORY_INVALID"
        else:
            reason = "CATALOG_AUTHORITY_ISSUE_TAMPER"
        return CatalogAuthorityIssueTamperReconciliationV1(
            all_catalog_authorities_blocked=True,
            recreate_authority_issue_allowed=False,
            append_to_damaged_authority_allowed=False,
            reason_code=reason,
        )

    if complete_timeline is None:
        return CatalogAuthorityIssueTamperReconciliationV1(
            all_catalog_authorities_blocked=True,
            recreate_authority_issue_allowed=False,
            append_to_damaged_authority_allowed=False,
            reason_code="CATALOG_AUTHORITY_LIFECYCLE_HISTORY_UNAVAILABLE",
        )
    timeline = _mapping(complete_timeline)
    if any(
        timeline.get(flag) is not True for flag in ("complete", "pagination_complete", "stable")
    ):
        reason = "CATALOG_AUTHORITY_LIFECYCLE_HISTORY_UNAVAILABLE"
        blocked = True
    else:
        raw_events = timeline.get("historical_events", timeline.get("events", ()))
        if not isinstance(raw_events, Sequence) or isinstance(raw_events, (str, bytes)):
            reason = "CATALOG_AUTHORITY_LIFECYCLE_HISTORY_INVALID"
            blocked = True
        else:
            event_names = {
                str(_mapping(event).get("event")) if isinstance(event, Mapping) else str(event)
                for event in raw_events
            }
            blocked = bool(event_names & _FORBIDDEN_AUTHORITY_LIFECYCLE_EVENTS)
            reason = (
                "CATALOG_AUTHORITY_LIFECYCLE_HISTORY_INVALID"
                if blocked
                else "CATALOG_AUTHORITY_LIFECYCLE_HISTORY_VERIFIED"
            )
    return CatalogAuthorityIssueTamperReconciliationV1(
        all_catalog_authorities_blocked=blocked,
        recreate_authority_issue_allowed=False,
        append_to_damaged_authority_allowed=not blocked,
        reason_code=reason,
    )


def select_campaign_authority(
    ledger: VerifiedAuthorityLedgerV1,
    campaign_id: str,
) -> CatalogAuthorityRecordV1 | None:
    checked = VerifiedAuthorityLedgerV1.model_validate(ledger.model_dump(mode="json"))
    latest_by_authority: dict[UUID, CatalogAuthorityRecordV1] = {}
    for record in checked.records:
        if record.campaign_id == campaign_id:
            latest_by_authority[record.authority_id] = record
    if len(latest_by_authority) > 1:
        raise ValueError("CATALOG_AUTHORITY_DUPLICATE")
    return next(iter(latest_by_authority.values()), None)


def verify_authority_issue_anchor(
    *,
    anchor: CatalogAuthorityAnchorV1,
    repository_variable_number: str | int | None,
    repository_snapshot: Mapping[str, object] | None,
    issue_snapshot: Mapping[str, object] | None,
) -> CatalogAuthorityAnchorVerificationV1:
    try:
        checked = CatalogAuthorityAnchorV1.model_validate(anchor.model_dump(mode="json"))
        if not checked.production_enabled:
            raise ValueError
        if repository_snapshot is None or issue_snapshot is None:
            raise ValueError
        if str(repository_variable_number) != str(checked.issue_number):
            raise ValueError
        if repository_snapshot.get("full_name") != checked.repository:
            raise ValueError
        if repository_snapshot.get("node_id") != checked.repository_node_id:
            raise ValueError
        if issue_snapshot.get("number") != checked.issue_number:
            raise ValueError
        if issue_snapshot.get("node_id") != checked.issue_node_id:
            raise ValueError
        if issue_snapshot.get("title") != checked.exact_title:
            raise ValueError
        if _mapping(issue_snapshot.get("user", {})).get("login") != checked.creator_login:
            raise ValueError
        if _parse_datetime(issue_snapshot.get("created_at")) != checked.created_at:
            raise ValueError
        if issue_snapshot.get("state") != "open" or issue_snapshot.get("locked") is not False:
            raise ValueError
        expected_url = f"https://api.github.com/repos/{checked.repository}"
        if issue_snapshot.get("repository_url") != expected_url:
            raise ValueError
        assert checked.issue_number is not None
        assert checked.issue_node_id is not None
        return CatalogAuthorityAnchorVerificationV1(
            status="ready",
            repository=checked.repository,
            issue_number=checked.issue_number,
            issue_node_id=checked.issue_node_id,
        )
    except Exception:
        raise ValueError("CATALOG_AUTHORITY_ANCHOR_INVALID") from None


__all__ = [
    "AUTHORITY_COMMENT_END",
    "AUTHORITY_COMMENT_START",
    "AuthorityState",
    "CatalogAuthorityAnchorV1",
    "CatalogAuthorityAnchorVerificationV1",
    "CatalogAuthorityCheckpointV1",
    "CatalogAuthorityIssueTamperReconciliationV1",
    "CatalogAuthorityMirrorReconciliationV1",
    "CatalogAuthorityRecordV1",
    "CatalogControllerActorsV1",
    "CatalogRequestTamperReconciliationV1",
    "CatalogRequestLifecycleReconciliationV1",
    "VerifiedAuthorityLedgerV1",
    "append_authority_record",
    "extract_authority_comment_records",
    "parse_authority_comments",
    "reconcile_authority_issue_tamper",
    "reconcile_authority_mirrors",
    "reconcile_request_lifecycle",
    "reconcile_request_tamper",
    "select_campaign_authority",
    "verify_authority_checkpoint",
    "verify_authority_issue_anchor",
]
