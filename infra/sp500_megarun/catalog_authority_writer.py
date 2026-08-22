"""Pure, fail-closed preparation and verification of catalog-ledger writes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .catalog_authority_ledger import (
    AuthorityState,
    CatalogAuthorityRecordV1,
    VerifiedAuthorityLedgerV1,
    append_authority_record,
    select_campaign_authority,
)
from .catalog_controller import CatalogControllerDecisionV1, ControllerOutcome
from .catalog_controller_reporting import (
    CatalogTerminalDecisionV1,
    CatalogTerminalState,
)
from .catalog_github_controls import AuditorCatalogGithubControlsReceiptV1
from .catalog_request_contract import FrozenModel, Sha256
from .catalog_routing import (
    CatalogRouteOutcome,
    CatalogRoutingCommandV1,
    route_catalog_command,
)


_CONTROLLER_WORKFLOW = ".github/workflows/catalog-run-controller.yml"
_REPOSITORY = "trading-optimizer-lab-org/aurora"
_WRITER_CALLER_WORKFLOWS = frozenset(
    {
        _CONTROLLER_WORKFLOW,
        ".github/workflows/catalog-request-reconciler.yml",
        ".github/workflows/catalog-run-watchdog.yml",
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
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


class CatalogAuthorityWriterContextV1(FrozenModel):
    """GitHub-proven writer identity, captured with GET-only API calls."""

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
    event: Literal["issues", "workflow_call", "schedule", "workflow_run"]
    repository: Literal["trading-optimizer-lab-org/aurora"]
    protected_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("CATALOG_AUTHORITY_WRITER_TIME_INVALID")
        return value.astimezone(UTC)


def catalog_authority_writer_context_from_github(
    *,
    run: Mapping[str, object],
    jobs: Sequence[Mapping[str, object]],
    expected_run_id: int,
    expected_run_attempt: int,
    expected_job_id: Literal[
        "report_nonexecuting_decision",
        "reserve",
        "record_running",
        "record_nonterminal_wait",
        "finalize",
    ],
    expected_protected_commit_sha: str,
    observed_at: datetime,
) -> CatalogAuthorityWriterContextV1:
    """Normalize an exact current run/job snapshot into the writer contract."""

    repository = run.get("repository")
    repository_name = (
        repository.get("full_name") if isinstance(repository, Mapping) else None
    )
    matching = [
        job
        for job in jobs
        if job.get("name") == expected_job_id
        or (
            isinstance(job.get("name"), str)
            and str(job["name"]).endswith(f" / {expected_job_id}")
        )
    ]
    workflow_path = run.get("path")
    if (
        run.get("id") != expected_run_id
        or run.get("run_attempt") != expected_run_attempt
        or workflow_path not in _WRITER_CALLER_WORKFLOWS
        or run.get("event") not in {"issues", "workflow_call", "schedule", "workflow_run"}
        or repository_name != _REPOSITORY
        or run.get("head_sha") != expected_protected_commit_sha
        or run.get("status") not in {"queued", "in_progress"}
        or len(matching) != 1
    ):
        raise ValueError("CATALOG_AUTHORITY_WRITER_PROVENANCE_INVALID")
    job = matching[0]
    database_id = job.get("id")
    if (
        isinstance(database_id, bool)
        or not isinstance(database_id, int)
        or database_id < 1
        or job.get("status") not in {"queued", "in_progress"}
        or job.get("conclusion") is not None
    ):
        raise ValueError("CATALOG_AUTHORITY_WRITER_PROVENANCE_INVALID")
    return CatalogAuthorityWriterContextV1(
        run_id=expected_run_id,
        run_attempt=expected_run_attempt,
        writer_job_id=expected_job_id,
        writer_job_database_id=database_id,
        workflow_path=str(workflow_path),
        event=str(run["event"]),
        repository=_REPOSITORY,
        protected_commit_sha=expected_protected_commit_sha,
        observed_at=observed_at,
    )


class CatalogAuthorityTransitionCandidateV1(FrozenModel):
    """One bounded ledger candidate; it is not committed until read-back."""

    schema_version: Literal["1"] = "1"
    mode: Literal["reserve", "running", "waiting_retry", "terminal"]
    decision_sha256: Sha256
    expected_ledger_sha256: Sha256
    expected_state: AuthorityState
    record: CatalogAuthorityRecordV1
    append_required: bool
    commit_allowed_for_current_writer: bool
    authority_committed: bool
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")
    candidate_sha256: Sha256

    @model_validator(mode="after")
    def _verify_shape_and_hash(self) -> "CatalogAuthorityTransitionCandidateV1":
        payload = self.model_dump(mode="json", exclude={"candidate_sha256"})
        if _sha256(payload) != self.candidate_sha256:
            raise ValueError("CATALOG_AUTHORITY_CANDIDATE_HASH_INVALID")
        if self.record.state is not self.expected_state:
            raise ValueError("CATALOG_AUTHORITY_CANDIDATE_STATE_INVALID")
        if self.authority_committed and not self.commit_allowed_for_current_writer:
            raise ValueError("CATALOG_AUTHORITY_COMMIT_NOT_ALLOWED")
        if self.append_required and self.authority_committed:
            raise ValueError("CATALOG_AUTHORITY_COMMIT_NOT_VERIFIED")
        return self

    @property
    def artifact_name(self) -> str:
        return self.record.artifact_name

    @property
    def comment_body(self) -> str:
        return self.record.to_comment() + "\n"


def _candidate(
    *,
    mode: Literal["reserve", "running", "waiting_retry", "terminal"],
    decision_sha256: str,
    ledger: VerifiedAuthorityLedgerV1,
    record: CatalogAuthorityRecordV1,
    append_required: bool,
    commit_allowed: bool,
    committed: bool = False,
    reason_code: str,
) -> CatalogAuthorityTransitionCandidateV1:
    payload: dict[str, object] = {
        "schema_version": "1",
        "mode": mode,
        "decision_sha256": decision_sha256,
        "expected_ledger_sha256": ledger.ledger_sha256,
        "expected_state": record.state.value,
        "record": record.model_dump(mode="json"),
        "append_required": append_required,
        "commit_allowed_for_current_writer": commit_allowed,
        "authority_committed": committed,
        "reason_code": reason_code,
    }
    payload["candidate_sha256"] = _sha256(payload)
    return CatalogAuthorityTransitionCandidateV1.model_validate(payload)


def _verify_common(
    *,
    decision: CatalogControllerDecisionV1,
    command: CatalogRoutingCommandV1,
    writer: CatalogAuthorityWriterContextV1,
) -> None:
    sealed = decision.sealed_inputs
    if (
        not decision.should_schedule_compute
        or sealed is None
        or decision.authority_id is None
        or sealed.authority_id != decision.authority_id
        or sealed.request_sha256 != decision.request_sha256
        or command.request_sha256 != decision.request_sha256
        or command.campaign_id != decision.campaign_id
        or sealed.campaign_id != command.campaign_id
        or sealed.science_sha256 != decision.science_sha256
        or sealed.execution_plan_sha256 != decision.execution_plan_sha256
        or sealed.execution_protocol_sha256 != decision.execution_protocol_sha256
        or sealed.protected_commit_sha != writer.protected_commit_sha
        or writer.workflow_path not in _WRITER_CALLER_WORKFLOWS
        or writer.repository != _REPOSITORY
    ):
        raise ValueError("CATALOG_AUTHORITY_DECISION_BINDING_INVALID")
    prerequisites = command.prerequisites
    if any(
        value is not True
        for value in (
            prerequisites.request_verified,
            prerequisites.campaign_registered,
            prerequisites.protected_head_verified,
            prerequisites.authority_anchor_verified,
            prerequisites.ledger_mirrors_verified,
            prerequisites.lifecycle_tamper_free,
            prerequisites.snapshot_complete,
            prerequisites.snapshot_stable,
            command.queue.complete,
            command.queue.stable,
        )
    ) or prerequisites.validation_opened or prerequisites.locked_opened:
        raise ValueError("CATALOG_AUTHORITY_FRESH_SNAPSHOT_INVALID")


def _latest_for_decision(
    decision: CatalogControllerDecisionV1,
    ledger: VerifiedAuthorityLedgerV1,
) -> CatalogAuthorityRecordV1 | None:
    matching = select_campaign_authority(ledger, str(decision.campaign_id))
    if matching is not None and matching.authority_id != decision.authority_id:
        raise ValueError("CATALOG_AUTHORITY_IDENTITY_CONFLICT")
    return matching


def _prepare_reserve(
    *,
    decision: CatalogControllerDecisionV1,
    command: CatalogRoutingCommandV1,
    writer: CatalogAuthorityWriterContextV1,
) -> CatalogAuthorityTransitionCandidateV1:
    if writer.writer_job_id != "reserve":
        raise ValueError("CATALOG_AUTHORITY_WRITER_JOB_INVALID")
    route = route_catalog_command(command)
    if route.outcome is not CatalogRouteOutcome.ELIGIBLE or not route.needs_live_audit:
        raise ValueError("CATALOG_AUTHORITY_RESERVE_ROUTE_INVALID")
    matching = _latest_for_decision(decision, command.ledger)
    if decision.outcome is ControllerOutcome.ADMITTED:
        if matching is not None or not decision.should_create_authority:
            raise ValueError("CATALOG_AUTHORITY_RESERVE_CONFLICT")
        record = append_authority_record(
            previous=command.ledger.latest,
            authority_id=decision.authority_id,
            request_issue_number=command.request_issue_number,
            campaign_id=decision.campaign_id,
            request_sha256=decision.request_sha256,
            science_sha256=decision.science_sha256,
            execution_plan_sha256=decision.execution_plan_sha256,
            execution_protocol_sha256=decision.execution_protocol_sha256,
            state=AuthorityState.RESERVED,
            run_id=writer.run_id,
            run_attempt=writer.run_attempt,
            writer_job_id=writer.writer_job_id,
            writer_job_database_id=writer.writer_job_database_id,
            protected_commit_sha=writer.protected_commit_sha,
            created_at=writer.observed_at,
        )
        return _candidate(
            mode="reserve",
            decision_sha256=decision.decision_sha256,
            ledger=command.ledger,
            record=record,
            append_required=True,
            commit_allowed=True,
            reason_code="CATALOG_AUTHORITY_RESERVE_PREPARED",
        )
    if (
        decision.outcome is not ControllerOutcome.ADOPTED
        or not decision.should_resume_existing
        or matching is None
    ):
        raise ValueError("CATALOG_AUTHORITY_RECOVERY_INVALID")
    record = append_authority_record(
        previous=matching,
        state=AuthorityState.RECOVERING,
        run_id=writer.run_id,
        run_attempt=writer.run_attempt,
        writer_job_id=writer.writer_job_id,
        writer_job_database_id=writer.writer_job_database_id,
        execution_plan_sha256=decision.execution_plan_sha256,
        evidence_sha256=decision.decision_sha256,
        safe_operational_replan=True,
        created_at=writer.observed_at,
    )
    return _candidate(
        mode="reserve",
        decision_sha256=decision.decision_sha256,
        ledger=command.ledger,
        record=record,
        append_required=True,
        commit_allowed=True,
        reason_code="CATALOG_AUTHORITY_RECOVERY_PREPARED",
    )


def _prepare_running(
    *,
    decision: CatalogControllerDecisionV1,
    command: CatalogRoutingCommandV1,
    writer: CatalogAuthorityWriterContextV1,
) -> CatalogAuthorityTransitionCandidateV1:
    if writer.writer_job_id != "record_running":
        raise ValueError("CATALOG_AUTHORITY_WRITER_JOB_INVALID")
    matching = _latest_for_decision(decision, command.ledger)
    if matching is None:
        raise ValueError("CATALOG_AUTHORITY_RESERVED_RECORD_MISSING")
    if (
        decision.outcome is ControllerOutcome.ADOPTED
        and decision.should_resume_existing
        and matching.state is AuthorityState.RECOVERING
    ):
        owned = matching.run_id == writer.run_id and matching.writer_job_id == "reserve"
        return _candidate(
            mode="running",
            decision_sha256=decision.decision_sha256,
            ledger=command.ledger,
            record=matching,
            append_required=False,
            commit_allowed=owned,
            reason_code=(
                "CATALOG_AUTHORITY_RECOVERY_COMMITTED"
                if owned
                else "CATALOG_AUTHORITY_OWNED_BY_OTHER_RUN"
            ),
        )
    if decision.outcome is not ControllerOutcome.ADMITTED:
        raise ValueError("CATALOG_AUTHORITY_RUNNING_DECISION_INVALID")
    if matching.state is AuthorityState.RUNNING:
        owned = (
            matching.run_id == writer.run_id
            and matching.writer_job_id == writer.writer_job_id
            and matching.writer_job_database_id == writer.writer_job_database_id
        )
        return _candidate(
            mode="running",
            decision_sha256=decision.decision_sha256,
            ledger=command.ledger,
            record=matching,
            append_required=False,
            commit_allowed=owned,
            reason_code=(
                "CATALOG_AUTHORITY_RUNNING_ALREADY_COMMITTED"
                if owned
                else "CATALOG_AUTHORITY_OWNED_BY_OTHER_RUN"
            ),
        )
    if matching.state is not AuthorityState.RESERVED:
        raise ValueError("CATALOG_AUTHORITY_RESERVED_RECORD_INVALID")
    if matching.run_id != writer.run_id or matching.writer_job_id != "reserve":
        return _candidate(
            mode="running",
            decision_sha256=decision.decision_sha256,
            ledger=command.ledger,
            record=matching,
            append_required=False,
            commit_allowed=False,
            reason_code="CATALOG_AUTHORITY_OWNED_BY_OTHER_RUN",
        )
    record = append_authority_record(
        previous=matching,
        state=AuthorityState.RUNNING,
        run_id=writer.run_id,
        run_attempt=writer.run_attempt,
        writer_job_id=writer.writer_job_id,
        writer_job_database_id=writer.writer_job_database_id,
        protected_commit_sha=writer.protected_commit_sha,
        created_at=writer.observed_at,
    )
    return _candidate(
        mode="running",
        decision_sha256=decision.decision_sha256,
        ledger=command.ledger,
        record=record,
        append_required=True,
        commit_allowed=True,
        reason_code="CATALOG_AUTHORITY_RUNNING_PREPARED",
    )


def _prepare_waiting_retry(
    *,
    decision: CatalogControllerDecisionV1,
    command: CatalogRoutingCommandV1,
    writer: CatalogAuthorityWriterContextV1,
    evidence_sha256: str | None,
    failure_fingerprint: str | None,
    failure_occurrence_count: int | None,
    reason_code: str | None,
) -> CatalogAuthorityTransitionCandidateV1:
    if writer.writer_job_id != "record_nonterminal_wait":
        raise ValueError("CATALOG_AUTHORITY_WRITER_JOB_INVALID")
    if (
        evidence_sha256 is None
        or failure_fingerprint is None
        or failure_occurrence_count not in {1, 2}
        or reason_code is None
    ):
        raise ValueError("CATALOG_AUTHORITY_WAIT_EVIDENCE_INVALID")
    matching = _latest_for_decision(decision, command.ledger)
    if matching is None:
        raise ValueError("CATALOG_AUTHORITY_RUNNING_RECORD_MISSING")
    if matching.state is AuthorityState.WAITING_RETRY:
        owned = (
            matching.run_id == writer.run_id
            and matching.writer_job_id == writer.writer_job_id
            and matching.writer_job_database_id == writer.writer_job_database_id
        )
        return _candidate(
            mode="waiting_retry",
            decision_sha256=decision.decision_sha256,
            ledger=command.ledger,
            record=matching,
            append_required=False,
            commit_allowed=owned,
            reason_code=(
                "CATALOG_AUTHORITY_WAIT_ALREADY_COMMITTED"
                if owned
                else "CATALOG_AUTHORITY_OWNED_BY_OTHER_RUN"
            ),
        )
    if matching.state not in {AuthorityState.RUNNING, AuthorityState.RECOVERING}:
        raise ValueError("CATALOG_AUTHORITY_WAIT_TRANSITION_INVALID")
    record = append_authority_record(
        previous=matching,
        state=AuthorityState.WAITING_RETRY,
        run_id=writer.run_id,
        run_attempt=writer.run_attempt,
        writer_job_id=writer.writer_job_id,
        writer_job_database_id=writer.writer_job_database_id,
        protected_commit_sha=writer.protected_commit_sha,
        failure_fingerprint=failure_fingerprint,
        failure_occurrence_count=failure_occurrence_count,
        reason_code=reason_code,
        evidence_sha256=evidence_sha256,
        created_at=writer.observed_at,
    )
    return _candidate(
        mode="waiting_retry",
        decision_sha256=decision.decision_sha256,
        ledger=command.ledger,
        record=record,
        append_required=True,
        commit_allowed=True,
        reason_code="CATALOG_AUTHORITY_WAIT_PREPARED",
    )


def prepare_catalog_authority_transition(
    *,
    mode: Literal["reserve", "running", "waiting_retry"],
    decision: CatalogControllerDecisionV1,
    fresh_command: CatalogRoutingCommandV1,
    writer: CatalogAuthorityWriterContextV1,
    evidence_sha256: str | None = None,
    failure_fingerprint: str | None = None,
    failure_occurrence_count: int | None = None,
    reason_code: str | None = None,
) -> CatalogAuthorityTransitionCandidateV1:
    """Prepare one write from a fresh dual-ledger snapshot, without mutating GitHub."""

    decision = CatalogControllerDecisionV1.model_validate(decision.model_dump(mode="json"))
    command = CatalogRoutingCommandV1.model_validate(fresh_command.model_dump(mode="json"))
    writer = CatalogAuthorityWriterContextV1.model_validate(writer.model_dump(mode="json"))
    _verify_common(decision=decision, command=command, writer=writer)
    if mode == "reserve":
        return _prepare_reserve(decision=decision, command=command, writer=writer)
    if mode == "running":
        return _prepare_running(decision=decision, command=command, writer=writer)
    if mode == "waiting_retry":
        return _prepare_waiting_retry(
            decision=decision,
            command=command,
            writer=writer,
            evidence_sha256=evidence_sha256,
            failure_fingerprint=failure_fingerprint,
            failure_occurrence_count=failure_occurrence_count,
            reason_code=reason_code,
        )
    raise ValueError("CATALOG_AUTHORITY_TRANSITION_MODE_INVALID")


def prepare_catalog_terminal_transition(
    *,
    decision: CatalogControllerDecisionV1,
    terminal_decision: CatalogTerminalDecisionV1,
    fresh_command: CatalogRoutingCommandV1,
    writer: CatalogAuthorityWriterContextV1,
    terminal_controls: AuditorCatalogGithubControlsReceiptV1,
    expected_audit_context_sha256: str,
) -> CatalogAuthorityTransitionCandidateV1:
    """Prepare the only terminal record after a fresh, bound controls audit."""

    decision = CatalogControllerDecisionV1.model_validate(
        decision.model_dump(mode="json")
    )
    terminal = CatalogTerminalDecisionV1.model_validate(
        terminal_decision.model_dump(mode="json")
    )
    command = CatalogRoutingCommandV1.model_validate(
        fresh_command.model_dump(mode="json")
    )
    writer = CatalogAuthorityWriterContextV1.model_validate(
        writer.model_dump(mode="json")
    )
    controls = AuditorCatalogGithubControlsReceiptV1.model_validate(
        terminal_controls.model_dump(mode="json")
    )
    _verify_common(decision=decision, command=command, writer=writer)
    if writer.writer_job_id != "finalize":
        raise ValueError("CATALOG_AUTHORITY_WRITER_JOB_INVALID")
    sealed = decision.sealed_inputs
    assert sealed is not None
    if (
        not terminal.authority_append_allowed
        or terminal.authority_terminal_record_created
        or terminal.request_sha256 != sealed.request_sha256
        or terminal.authority_id != sealed.authority_id
        or terminal.campaign_id != sealed.campaign_id
        or terminal.science_sha256 != sealed.science_sha256
        or terminal.execution_plan_sha256 != sealed.execution_plan_sha256
        or terminal.protected_commit_sha != sealed.protected_commit_sha
    ):
        raise ValueError("CATALOG_TERMINAL_DECISION_BINDING_INVALID")
    if (
        controls.status != "ready"
        or controls.audit_use_context != "controller_terminal"
        or controls.caller_workflow != _CONTROLLER_WORKFLOW
        or controls.caller_job != "live_controls_audit_before_terminal"
        or controls.protected_commit_sha != sealed.protected_commit_sha
        or controls.audit_context_sha256 != expected_audit_context_sha256
    ):
        raise ValueError("CATALOG_TERMINAL_CONTROLS_INVALID")
    age = writer.observed_at - controls.github_api_observed_at
    if age > timedelta(seconds=300) or age < -timedelta(seconds=30):
        raise ValueError("CATALOG_TERMINAL_AUDIT_EXPIRED")
    matching = _latest_for_decision(decision, command.ledger)
    if matching is None:
        raise ValueError("CATALOG_AUTHORITY_RUNNING_RECORD_MISSING")
    state = {
        CatalogTerminalState.SUCCESS: AuthorityState.SUCCESS,
        CatalogTerminalState.FAILED: AuthorityState.FAILED,
        CatalogTerminalState.BLOCKED: AuthorityState.BLOCKED,
    }[terminal.state]
    if matching.state in {
        AuthorityState.SUCCESS,
        AuthorityState.FAILED,
        AuthorityState.BLOCKED,
    }:
        exact = (
            matching.state is state
            and matching.evidence_sha256 == terminal.terminal_decision_sha256
            and matching.reason_code == terminal.reason_code
        )
        if not exact:
            raise ValueError("CATALOG_AUTHORITY_TERMINAL_CONFLICT")
        return _candidate(
            mode="terminal",
            decision_sha256=terminal.terminal_decision_sha256,
            ledger=command.ledger,
            record=matching,
            append_required=False,
            commit_allowed=True,
            reason_code="CATALOG_AUTHORITY_TERMINAL_ALREADY_COMMITTED",
        )
    if matching.state is AuthorityState.WAITING_RETRY and state is not AuthorityState.BLOCKED:
        raise ValueError("CATALOG_AUTHORITY_TERMINAL_TRANSITION_INVALID")
    record = append_authority_record(
        previous=matching,
        state=state,
        run_id=writer.run_id,
        run_attempt=writer.run_attempt,
        writer_job_id=writer.writer_job_id,
        writer_job_database_id=writer.writer_job_database_id,
        protected_commit_sha=writer.protected_commit_sha,
        reason_code=terminal.reason_code,
        evidence_sha256=terminal.terminal_decision_sha256,
        created_at=writer.observed_at,
    )
    return _candidate(
        mode="terminal",
        decision_sha256=terminal.terminal_decision_sha256,
        ledger=command.ledger,
        record=record,
        append_required=True,
        commit_allowed=True,
        reason_code="CATALOG_AUTHORITY_TERMINAL_PREPARED",
    )


def verify_catalog_authority_commit(
    *,
    candidate: CatalogAuthorityTransitionCandidateV1,
    fresh_ledger: VerifiedAuthorityLedgerV1,
) -> CatalogAuthorityTransitionCandidateV1:
    """Set committed only after the exact record and writer provenance read back."""

    candidate = CatalogAuthorityTransitionCandidateV1.model_validate(
        candidate.model_dump(mode="json")
    )
    ledger = VerifiedAuthorityLedgerV1.model_validate(fresh_ledger.model_dump(mode="json"))
    latest = ledger.latest
    if (
        not candidate.commit_allowed_for_current_writer
        or latest is None
        or latest.sequence != candidate.record.sequence
        or _canonical_bytes(latest) != _canonical_bytes(candidate.record)
        or candidate.record.run_id not in ledger.verified_writer_run_ids
    ):
        raise ValueError("CATALOG_AUTHORITY_COMMIT_NOT_VERIFIED")
    return _candidate(
        mode=candidate.mode,
        decision_sha256=candidate.decision_sha256,
        ledger=VerifiedAuthorityLedgerV1.model_construct(
            ledger_sha256=candidate.expected_ledger_sha256
        ),
        record=candidate.record,
        append_required=False,
        commit_allowed=True,
        committed=True,
        reason_code="CATALOG_AUTHORITY_COMMIT_VERIFIED",
    )


__all__ = [
    "CatalogAuthorityTransitionCandidateV1",
    "CatalogAuthorityWriterContextV1",
    "catalog_authority_writer_context_from_github",
    "prepare_catalog_authority_transition",
    "prepare_catalog_terminal_transition",
    "verify_catalog_authority_commit",
]
