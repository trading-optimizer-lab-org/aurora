from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aurora.infra.sp500_megarun.catalog_authority_ledger import (
    AuthorityState,
    VerifiedAuthorityLedgerV1,
    append_authority_record,
)
from aurora.infra.sp500_megarun.catalog_authority_writer import (
    CatalogAuthorityWriterContextV1,
    catalog_authority_writer_context_from_github,
    prepare_catalog_authority_transition,
    prepare_catalog_terminal_transition,
    verify_catalog_authority_commit,
)
from aurora.infra.sp500_megarun.catalog_controller import (
    CatalogRequestQueueEvidenceV1,
    CatalogSealedInputsV1,
    ControllerOutcome,
    _decision,
    catalog_authority_id,
)
from aurora.infra.sp500_megarun.catalog_controller_reporting import (
    finalize_catalog_run,
)
from aurora.infra.sp500_megarun.catalog_request_receipt import (
    CatalogRequestReceiptV1,
    build_nonexecuting_request_receipt,
    build_terminal_request_receipt,
    build_waiting_retry_request_receipt,
)
from aurora.infra.sp500_megarun.catalog_engine_outcome import (
    CatalogEngineOutcomeState,
    select_catalog_engine_outcome,
)
from test_catalog_admission_adapter import _auditor_receipt
from test_catalog_controller_reporting import valid_final_evidence
from aurora.infra.sp500_megarun.catalog_routing import (
    CatalogRoutingCommandV1,
    CatalogRoutingPrerequisitesV1,
)


NOW = datetime(2026, 8, 22, 8, 0, tzinfo=UTC)
REQUEST = "1" * 64
CAMPAIGN = "2" * 64
SCIENCE = "3" * 64
PLAN = "4" * 64
PROTOCOL = "5" * 64
COMMIT = "6" * 40
AUTHORITY = catalog_authority_id(request_sha256=REQUEST, campaign_id=CAMPAIGN)


def _sealed(*, authority_id=AUTHORITY) -> CatalogSealedInputsV1:
    return CatalogSealedInputsV1(
        engine_id="optimized_catalog_v1",
        request_sha256=REQUEST,
        campaign_id=CAMPAIGN,
        science_sha256=SCIENCE,
        execution_plan_sha256=PLAN,
        execution_protocol_sha256=PROTOCOL,
        protected_commit_sha=COMMIT,
        prompt_sha256="7" * 64,
        prompt_policy_sha256="8" * 64,
        campaign_registry_sha256="9" * 64,
        campaign_definition_manifest_sha256="a" * 64,
        campaign_definition_sha256="b" * 64,
        campaign_definition_rehash_receipt_sha256="c" * 64,
        authority_id=authority_id,
        authority_anchor_evidence_sha256="d" * 64,
        github_controls_receipt_sha256="e" * 64,
        capacity_receipt_sha256="f" * 64,
        source_artifact_manifest_sha256="0" * 64,
        artifact_plan_sha256="1" * 64,
    )


def _admitted():
    sealed = _sealed()
    return _decision(
        outcome=ControllerOutcome.ADMITTED,
        reason_code="CATALOG_ADMITTED",
        request_sha256=REQUEST,
        campaign_id=CAMPAIGN,
        science_sha256=SCIENCE,
        execution_plan_sha256=PLAN,
        execution_protocol_sha256=PROTOCOL,
        authority_id=AUTHORITY,
        should_create_authority=True,
        should_schedule_compute=True,
        sealed_inputs=sealed,
    )


def _context(job: str, database_id: int) -> CatalogAuthorityWriterContextV1:
    return CatalogAuthorityWriterContextV1(
        run_id=9001,
        run_attempt=1,
        writer_job_id=job,
        writer_job_database_id=database_id,
        workflow_path=".github/workflows/catalog-run-controller.yml",
        event="issues",
        repository="trading-optimizer-lab-org/aurora",
        protected_commit_sha=COMMIT,
        observed_at=NOW,
    )


def _queue(*, current: int = 101, eligible: tuple[int, ...] = (101,)):
    return CatalogRequestQueueEvidenceV1(
        status="ready",
        observed_at=NOW,
        source_sha256="2" * 64,
        content_sha256="3" * 64,
        receipt_sha256="4" * 64,
        reason_codes=(),
        complete=True,
        stable=True,
        current_issue_number=current,
        eligible_open_issue_numbers=eligible,
        request_queue_snapshot_sha256="5" * 64,
    )


def _command(
    ledger: VerifiedAuthorityLedgerV1,
    *,
    current: int = 101,
    eligible: tuple[int, ...] = (101,),
    active=(),
) -> CatalogRoutingCommandV1:
    return CatalogRoutingCommandV1(
        request_sha256=REQUEST,
        request_issue_number=current,
        campaign_id=CAMPAIGN,
        queue=_queue(current=current, eligible=eligible),
        ledger=ledger,
        prerequisites=CatalogRoutingPrerequisitesV1(
            observed_at=NOW,
            request_verified=True,
            campaign_registered=True,
            protected_head_verified=True,
            authority_anchor_verified=True,
            ledger_mirrors_verified=True,
            lifecycle_tamper_free=True,
            snapshot_complete=True,
            snapshot_stable=True,
            validation_opened=False,
            locked_opened=False,
            active_owner_authority_ids=tuple(active),
            routing_snapshot_sha256="6" * 64,
        ),
        verified_github_now=NOW,
    )


def _terminal_other_campaign() -> VerifiedAuthorityLedgerV1:
    first = append_authority_record(
        previous=None,
        authority_id="11111111-1111-5111-8111-111111111111",
        request_issue_number=90,
        campaign_id="a" * 64,
        request_sha256="b" * 64,
        science_sha256="c" * 64,
        execution_plan_sha256="d" * 64,
        execution_protocol_sha256="e" * 64,
        state=AuthorityState.RESERVED,
        run_id=8001,
        run_attempt=1,
        writer_job_id="reserve",
        writer_job_database_id=8101,
        protected_commit_sha=COMMIT,
        created_at=NOW - timedelta(minutes=3),
    )
    running = append_authority_record(
        previous=first,
        state=AuthorityState.RUNNING,
        writer_job_id="record_running",
        writer_job_database_id=8102,
        created_at=NOW - timedelta(minutes=2),
    )
    success = append_authority_record(
        previous=running,
        state=AuthorityState.SUCCESS,
        writer_job_id="finalize",
        writer_job_database_id=8103,
        evidence_sha256="f" * 64,
        created_at=NOW - timedelta(minutes=1),
    )
    return VerifiedAuthorityLedgerV1.from_records((first, running, success))


def test_reserve_extends_the_global_chain_instead_of_restarting_at_zero() -> None:
    ledger = _terminal_other_campaign()
    candidate = prepare_catalog_authority_transition(
        mode="reserve",
        decision=_admitted(),
        fresh_command=_command(ledger),
        writer=_context("reserve", 9101),
    )

    assert candidate.append_required is True
    assert candidate.authority_committed is False
    assert candidate.record is not None
    assert candidate.record.sequence == 3
    assert candidate.record.previous_record_sha256 == ledger.latest.record_sha256
    assert candidate.record.state is AuthorityState.RESERVED


def test_reserve_refuses_a_request_that_lost_fifo_eligibility() -> None:
    with pytest.raises(ValueError, match="CATALOG_AUTHORITY_RESERVE_ROUTE_INVALID"):
        prepare_catalog_authority_transition(
            mode="reserve",
            decision=_admitted(),
            fresh_command=_command(
                VerifiedAuthorityLedgerV1.from_records(()),
                current=102,
                eligible=(101, 102),
            ),
            writer=_context("reserve", 9101),
        )


def test_running_is_created_only_after_the_exact_reserved_record() -> None:
    reserved_candidate = prepare_catalog_authority_transition(
        mode="reserve",
        decision=_admitted(),
        fresh_command=_command(VerifiedAuthorityLedgerV1.from_records(())),
        writer=_context("reserve", 9101),
    )
    assert reserved_candidate.record is not None
    reserved_ledger = VerifiedAuthorityLedgerV1.from_records(
        (reserved_candidate.record,)
    )

    running_candidate = prepare_catalog_authority_transition(
        mode="running",
        decision=_admitted(),
        fresh_command=_command(reserved_ledger, active=(AUTHORITY,)),
        writer=_context("record_running", 9102),
    )

    assert running_candidate.append_required is True
    assert running_candidate.record is not None
    assert running_candidate.record.state is AuthorityState.RUNNING
    assert running_candidate.record.previous_record_sha256 == (
        reserved_candidate.record.record_sha256
    )


def test_commit_is_true_only_after_the_fresh_verified_ledger_contains_exact_record() -> None:
    candidate = prepare_catalog_authority_transition(
        mode="reserve",
        decision=_admitted(),
        fresh_command=_command(VerifiedAuthorityLedgerV1.from_records(())),
        writer=_context("reserve", 9101),
    )
    assert candidate.record is not None
    committed = verify_catalog_authority_commit(
        candidate=candidate,
        fresh_ledger=VerifiedAuthorityLedgerV1.from_records(
            (candidate.record,), verified_writer_run_ids=(9001,)
        ),
    )
    assert committed.authority_committed is True

    with pytest.raises(ValueError, match="CATALOG_AUTHORITY_COMMIT_NOT_VERIFIED"):
        verify_catalog_authority_commit(
            candidate=candidate,
            fresh_ledger=VerifiedAuthorityLedgerV1.from_records(()),
        )


def test_waiting_retry_requires_closed_failure_evidence_and_never_accepts_third_retry() -> None:
    reserved = prepare_catalog_authority_transition(
        mode="reserve",
        decision=_admitted(),
        fresh_command=_command(VerifiedAuthorityLedgerV1.from_records(())),
        writer=_context("reserve", 9101),
    ).record
    running = append_authority_record(
        previous=reserved,
        state=AuthorityState.RUNNING,
        run_id=9001,
        run_attempt=1,
        writer_job_id="record_running",
        writer_job_database_id=9102,
        protected_commit_sha=COMMIT,
        created_at=NOW + timedelta(seconds=1),
    )
    ledger = VerifiedAuthorityLedgerV1.from_records((reserved, running))
    waiting = prepare_catalog_authority_transition(
        mode="waiting_retry",
        decision=_admitted(),
        fresh_command=_command(ledger, active=(AUTHORITY,)),
        writer=_context("record_nonterminal_wait", 9103),
        evidence_sha256="a" * 64,
        failure_fingerprint="b" * 64,
        failure_occurrence_count=1,
        reason_code="CATALOG_RETRY_AFTER_RATE_LIMIT",
    )
    assert waiting.record.state is AuthorityState.WAITING_RETRY
    assert waiting.record.failure_occurrence_count == 1

    with pytest.raises(ValueError, match="CATALOG_AUTHORITY_WAIT_EVIDENCE_INVALID"):
        prepare_catalog_authority_transition(
            mode="waiting_retry",
            decision=_admitted(),
            fresh_command=_command(ledger, active=(AUTHORITY,)),
            writer=_context("record_nonterminal_wait", 9103),
            evidence_sha256="a" * 64,
            failure_fingerprint="b" * 64,
            failure_occurrence_count=3,
            reason_code="CATALOG_RETRY_AFTER_RATE_LIMIT",
        )


def test_writer_context_requires_the_exact_current_job_and_protected_commit() -> None:
    run = {
        "id": 9001,
        "run_attempt": 1,
        "path": ".github/workflows/catalog-run-controller.yml",
        "event": "issues",
        "head_sha": COMMIT,
        "status": "in_progress",
        "repository": {"full_name": "trading-optimizer-lab-org/aurora"},
    }
    jobs = (
        {
            "id": 9101,
            "name": "reserve",
            "status": "in_progress",
            "conclusion": None,
        },
    )
    context = catalog_authority_writer_context_from_github(
        run=run,
        jobs=jobs,
        expected_run_id=9001,
        expected_run_attempt=1,
        expected_job_id="reserve",
        expected_protected_commit_sha=COMMIT,
        observed_at=NOW,
    )
    assert context.writer_job_database_id == 9101

    with pytest.raises(ValueError, match="CATALOG_AUTHORITY_WRITER_PROVENANCE_INVALID"):
        catalog_authority_writer_context_from_github(
            run={**run, "head_sha": "0" * 40},
            jobs=jobs,
            expected_run_id=9001,
            expected_run_attempt=1,
            expected_job_id="reserve",
            expected_protected_commit_sha=COMMIT,
            observed_at=NOW,
        )


@pytest.mark.parametrize("event", ("schedule", "workflow_dispatch"))
def test_writer_context_accepts_the_exact_reusable_job_suffix_without_ambiguity(
    event: str,
) -> None:
    context = catalog_authority_writer_context_from_github(
        run={
            "id": 9002,
            "run_attempt": 1,
            "path": ".github/workflows/catalog-request-reconciler.yml",
            "event": event,
            "head_sha": COMMIT,
            "status": "in_progress",
            "repository": {"full_name": "trading-optimizer-lab-org/aurora"},
        },
        jobs=(
            {
                "id": 9201,
                "name": "call_controller (101) / reserve",
                "status": "in_progress",
                "conclusion": None,
            },
        ),
        expected_run_id=9002,
        expected_run_attempt=1,
        expected_job_id="reserve",
        expected_protected_commit_sha=COMMIT,
        observed_at=NOW,
    )
    assert context.workflow_path == ".github/workflows/catalog-request-reconciler.yml"
    assert context.writer_job_database_id == 9201
    assert context.event == event


def _terminal_decision():
    evidence = valid_final_evidence()["final_evidence"]
    payload = evidence.model_dump(mode="json")
    payload.update(
        {
            "request_sha256": REQUEST,
            "authority_id": str(AUTHORITY),
            "campaign_id": CAMPAIGN,
            "science_sha256": SCIENCE,
            "execution_plan_sha256": PLAN,
            "execution_protocol_sha256": PROTOCOL,
            "protected_commit_sha": COMMIT,
        }
    )
    return finalize_catalog_run(
        final_evidence=type(evidence).model_validate(payload)
    )


def _running_ledger() -> VerifiedAuthorityLedgerV1:
    reserved = prepare_catalog_authority_transition(
        mode="reserve",
        decision=_admitted(),
        fresh_command=_command(VerifiedAuthorityLedgerV1.from_records(())),
        writer=_context("reserve", 9101),
    ).record
    running = append_authority_record(
        previous=reserved,
        state=AuthorityState.RUNNING,
        run_id=9001,
        run_attempt=1,
        writer_job_id="record_running",
        writer_job_database_id=9102,
        protected_commit_sha=COMMIT,
        created_at=NOW + timedelta(seconds=1),
    )
    return VerifiedAuthorityLedgerV1.from_records((reserved, running))


def _terminal_controls(*, observed_at=NOW):
    return _auditor_receipt(
        audit_use_context="controller_terminal",
        audit_context_sha256="a" * 64,
        protected_commit_sha=COMMIT,
        observed_default_branch_sha=COMMIT,
        caller_job="live_controls_audit_before_terminal",
        observed_at=observed_at,
        github_api_observed_at=observed_at,
    )


def test_terminal_transition_uses_only_fresh_bound_decision_and_audit() -> None:
    terminal = _terminal_decision()
    candidate = prepare_catalog_terminal_transition(
        decision=_admitted(),
        terminal_decision=terminal,
        fresh_command=_command(_running_ledger(), active=(AUTHORITY,)),
        writer=_context("finalize", 9104),
        terminal_controls=_terminal_controls(),
        expected_audit_context_sha256="a" * 64,
    )
    assert candidate.mode == "terminal"
    assert candidate.record.state is AuthorityState.SUCCESS
    assert candidate.record.evidence_sha256 == terminal.terminal_decision_sha256
    assert candidate.record.reason_code == "CATALOG_SUCCESS"
    summary = terminal.human_summary
    receipt = build_terminal_request_receipt(
        decision=terminal,
        authority_candidate=candidate,
        summary=summary,
    )
    assert receipt.authority_record_sha256 == candidate.record.record_sha256
    assert receipt.writer_job_database_id == 9104
    assert receipt.artifact_name == "catalog-request-receipt-101-0000000000"
    assert receipt.receipt_sha256 in receipt.comment_body(summary)


def test_preauthority_blocked_receipt_is_closed_without_fake_terminal_decision() -> None:
    summary = "Solicitud bloqueada antes de crear una autoridad.\n"
    receipt = build_nonexecuting_request_receipt(
        state="BLOCKED",
        reason_code="CATALOG_REQUEST_INVALID",
        issue_number=101,
        request_sha256=REQUEST,
        campaign_id=None,
        authority_record=None,
        writer=_context("report_nonexecuting_decision", 9105),
        summary=summary,
    )
    assert receipt.state == "BLOCKED"
    assert receipt.authority_id is None
    assert receipt.terminal_decision_sha256 is None
    assert receipt.writer_job_database_id == 9105
    assert receipt.comment_body(summary).startswith(
        "Solicitud bloqueada antes de crear una autoridad.\n\n"
    )
    CatalogRequestReceiptV1.model_validate(receipt.model_dump(mode="json"))


def test_nonexecuting_receipt_binds_an_adopted_active_authority() -> None:
    active = _running_ledger().records[-1]
    receipt = build_nonexecuting_request_receipt(
        state="DEFERRED",
        reason_code="CATALOG_ADOPTED_WAITING_FOR_EXISTING",
        issue_number=202,
        request_sha256="a" * 64,
        campaign_id=CAMPAIGN,
        authority_record=active,
        writer=_context("report_nonexecuting_decision", 9105),
        summary="La solicitud queda enlazada al run existente.",
    )
    assert receipt.authority_id == active.authority_id
    assert receipt.authority_record_sha256 == active.record_sha256
    assert receipt.terminal_decision_sha256 is None
    assert receipt.retry_not_before is None


def test_deferred_request_receipt_carries_its_exact_retry_deadline() -> None:
    retry_at = NOW + timedelta(minutes=15)
    receipt = build_nonexecuting_request_receipt(
        state="DEFERRED",
        reason_code="CATALOG_WAITING_FOR_FREE_CAPACITY",
        issue_number=203,
        request_sha256="b" * 64,
        campaign_id=CAMPAIGN,
        authority_record=None,
        writer=_context("report_nonexecuting_decision", 9105),
        retry_not_before=retry_at,
        summary="La solicitud se volverá a revisar cuando venza el plazo.",
    )
    assert receipt.retry_not_before == retry_at


def test_capacity_deferred_request_receipt_requires_a_retry_deadline() -> None:
    with pytest.raises(
        ValueError, match="CATALOG_REQUEST_RECEIPT_RETRY_SHAPE_INVALID"
    ):
        build_nonexecuting_request_receipt(
            state="DEFERRED",
            reason_code="CATALOG_WAITING_FOR_FREE_CAPACITY",
            issue_number=203,
            request_sha256="b" * 64,
            campaign_id=CAMPAIGN,
            authority_record=None,
            writer=_context("report_nonexecuting_decision", 9105),
            summary="Solicitud aplazada.",
        )


def test_waiting_retry_receipt_binds_the_verified_engine_outcome_and_record() -> None:
    ledger = _running_ledger()
    retry_at = NOW + timedelta(minutes=5)
    outcome = select_catalog_engine_outcome(
        request_sha256=REQUEST,
        authority_id=AUTHORITY,
        campaign_id=CAMPAIGN,
        science_sha256=SCIENCE,
        execution_plan_sha256=PLAN,
        execution_protocol_sha256=PROTOCOL,
        protected_commit_sha=COMMIT,
        engine_run_id=9001,
        engine_run_attempt=1,
        stage_results={
            "engine_verify_sealed_plan": "success",
            "prepare_runtime_and_inputs": "success",
            "verify_component_store": "success",
            "reconcile_wave_0": "failure",
            "reduce": "skipped",
            "verify_terminal_science": "skipped",
            "audit_runtime": "skipped",
        },
        recovery_statuses=("waiting_retry",),
        final_evidence_artifact=None,
        runtime_audit_artifact=None,
        science_evidence_artifact=None,
        recovery_evidence_artifact="catalog-recovery-evidence-9001",
        failure_fingerprint="b" * 64,
        failure_occurrence_count=1,
        failure_reason_code="PROVIDER_429",
        retry_not_before=retry_at,
        terminal_failure_code=None,
        created_at=NOW,
    )
    assert outcome.state is CatalogEngineOutcomeState.WAITING_RETRY
    candidate = prepare_catalog_authority_transition(
        mode="waiting_retry",
        decision=_admitted(),
        fresh_command=_command(ledger, active=(AUTHORITY,)),
        writer=_context("record_nonterminal_wait", 9103),
        evidence_sha256=outcome.evidence_sha256,
        failure_fingerprint=outcome.failure_fingerprint,
        failure_occurrence_count=outcome.failure_occurrence_count,
        reason_code=outcome.reason_code,
    )
    receipt = build_waiting_retry_request_receipt(
        authority_candidate=candidate,
        engine_outcome=outcome,
        summary="Reintento aplazado hasta la hora indicada.",
    )
    assert receipt.state == "WAITING_RETRY"
    assert receipt.authority_record_sha256 == candidate.record.record_sha256
    assert receipt.reason_code == "PROVIDER_429"
    assert receipt.terminal_decision_sha256 is None
    assert receipt.retry_not_before == retry_at


def test_nonexecuting_receipt_rejects_the_wrong_writer_job() -> None:
    with pytest.raises(ValueError, match="CATALOG_REQUEST_RECEIPT_WRITER_INVALID"):
        build_nonexecuting_request_receipt(
            state="DEFERRED",
            reason_code="CATALOG_WAITING_FOR_ACTIVE_CAMPAIGN",
            issue_number=101,
            request_sha256=REQUEST,
            campaign_id=CAMPAIGN,
            authority_record=None,
            writer=_context("reserve", 9101),
            summary="Solicitud aplazada.",
        )


def test_terminal_transition_rejects_expired_audit_without_appending() -> None:
    with pytest.raises(ValueError, match="CATALOG_TERMINAL_AUDIT_EXPIRED"):
        prepare_catalog_terminal_transition(
            decision=_admitted(),
            terminal_decision=_terminal_decision(),
            fresh_command=_command(_running_ledger(), active=(AUTHORITY,)),
            writer=_context("finalize", 9104),
            terminal_controls=_terminal_controls(
                observed_at=NOW - timedelta(seconds=301)
            ),
            expected_audit_context_sha256="a" * 64,
        )
