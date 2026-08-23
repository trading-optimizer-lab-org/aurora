from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aurora.infra.sp500_megarun.catalog_authority_ledger import (
    AuthorityState,
    CatalogAuthorityRecordV1,
    append_authority_record,
)
from aurora.infra.sp500_megarun.catalog_authority_writer import (
    CatalogAuthorityWriterContextV1,
)
from aurora.infra.sp500_megarun.catalog_mirror_delivery import (
    CatalogMirrorArtifactV1,
    CatalogMirrorRepairClaimV1,
    CatalogMirrorRepairWriterContextV1,
    CatalogMirrorWriterEvidenceV1,
    decide_authority_mirror_delivery,
    decide_request_receipt_mirror_delivery,
    prepare_catalog_mirror_repair_claim,
)
from aurora.infra.sp500_megarun.catalog_request_receipt import (
    CatalogRequestReceiptV1,
    build_nonexecuting_request_receipt,
    next_request_receipt_sequence,
)


NOW = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)
COMMIT = "a" * 40
REQUEST = "b" * 64
CAMPAIGN = "c" * 64
AUTHORITY = "11111111-1111-5111-8111-111111111111"


def _writer(*, run_id: int, database_id: int) -> CatalogAuthorityWriterContextV1:
    return CatalogAuthorityWriterContextV1(
        run_id=run_id,
        run_attempt=1,
        writer_job_id="report_nonexecuting_decision",
        writer_job_database_id=database_id,
        workflow_path=".github/workflows/catalog-run-controller.yml",
        event="issues",
        repository="trading-optimizer-lab-org/aurora",
        protected_commit_sha=COMMIT,
        observed_at=NOW,
    )


def _receipt(
    *, run_id: int, database_id: int, delivery_sequence: int = 0
) -> CatalogRequestReceiptV1:
    return build_nonexecuting_request_receipt(
        state="DEFERRED",
        reason_code="CATALOG_WAITING_FOR_FREE_CAPACITY",
        issue_number=101,
        request_sha256=REQUEST,
        campaign_id=CAMPAIGN,
        authority_record=None,
        writer=_writer(run_id=run_id, database_id=database_id),
        retry_not_before=NOW + timedelta(minutes=15),
        summary="Solicitud aplazada hasta que exista capacidad libre.",
        delivery_sequence=delivery_sequence,
    )


def _reserved(*, run_id: int, database_id: int) -> CatalogAuthorityRecordV1:
    return append_authority_record(
        previous=None,
        authority_id=AUTHORITY,
        request_issue_number=101,
        campaign_id=CAMPAIGN,
        request_sha256=REQUEST,
        science_sha256="d" * 64,
        execution_plan_sha256="e" * 64,
        execution_protocol_sha256="f" * 64,
        state=AuthorityState.RESERVED,
        run_id=run_id,
        run_attempt=1,
        writer_job_id="reserve",
        writer_job_database_id=database_id,
        protected_commit_sha=COMMIT,
        created_at=NOW,
    )


def _evidence(
    *,
    run_id: int,
    database_id: int,
    job_id: str,
    post_conclusion: str,
) -> CatalogMirrorWriterEvidenceV1:
    return CatalogMirrorWriterEvidenceV1(
        complete=True,
        stable=True,
        authenticated=True,
        repository="trading-optimizer-lab-org/aurora",
        workflow_path=".github/workflows/catalog-run-controller.yml",
        protected_commit_sha=COMMIT,
        run_id=run_id,
        run_attempt=1,
        run_status="completed",
        writer_job_id=job_id,
        writer_job_database_id=database_id,
        job_status="completed",
        upload_step_conclusion="success",
        post_step_conclusion=post_conclusion,
    )


def _repair_writer(
    *,
    run_id: int,
    database_id: int,
    observed_at: datetime = NOW,
) -> CatalogMirrorRepairWriterContextV1:
    return CatalogMirrorRepairWriterContextV1(
        run_id=run_id,
        run_attempt=1,
        writer_job_id="report_nonexecuting_decision",
        writer_job_database_id=database_id,
        workflow_path=".github/workflows/catalog-run-controller.yml",
        repository="trading-optimizer-lab-org/aurora",
        protected_commit_sha=COMMIT,
        observed_at=observed_at,
    )


def _mirror(*, artifact_id: int, name: str, payload: object) -> CatalogMirrorArtifactV1:
    return CatalogMirrorArtifactV1.create(
        artifact_id=artifact_id,
        artifact_name=name,
        expired=False,
        created_at=NOW,
        expires_at=NOW + timedelta(days=90),
        payload=payload,
    )


def test_request_mirror_slot_is_stable_across_writer_retries() -> None:
    first = _receipt(run_id=9001, database_id=9101)
    retry = _receipt(run_id=9002, database_id=9201)

    assert first.receipt_sha256 != retry.receipt_sha256
    assert first.mirror_identity_sha256 == retry.mirror_identity_sha256
    assert first.artifact_name == retry.artifact_name
    assert first.artifact_name == "catalog-request-receipt-101-0000000000"


def test_request_receipt_sequence_is_contiguous_and_gap_closed() -> None:
    first = _receipt(run_id=9001, database_id=9101, delivery_sequence=0)
    second = _receipt(run_id=9002, database_id=9201, delivery_sequence=1)
    assert next_request_receipt_sequence(
        (first, second),
        issue_number=101,
        request_sha256=REQUEST,
    ) == 2
    with pytest.raises(ValueError, match="CATALOG_REQUEST_RECEIPT_SEQUENCE_INVALID"):
        next_request_receipt_sequence(
            (second,),
            issue_number=101,
            request_sha256=REQUEST,
        )


def test_request_orphan_mirror_repairs_the_old_exact_receipt_once() -> None:
    original = _receipt(run_id=9001, database_id=9101)
    retry = _receipt(run_id=9002, database_id=9201)
    decision = decide_request_receipt_mirror_delivery(
        candidate=retry,
        artifacts=(
            _mirror(
                artifact_id=51,
                name=original.artifact_name,
                payload=original,
            ),
        ),
        comment_receipts=(),
        writer_evidence=(
            _evidence(
                run_id=9001,
                database_id=9101,
                job_id="report_nonexecuting_decision",
                post_conclusion="failure",
            ),
        ),
        now=NOW + timedelta(minutes=1),
    )

    assert decision.action == "repair_comment"
    assert decision.artifact_id == 51
    assert decision.payload_sha256 == original.receipt_sha256
    assert decision.stop_after_repair is True


def test_authority_orphan_reuses_old_writer_record_and_stops_before_compute() -> None:
    original = _reserved(run_id=9001, database_id=9101)
    retry = _reserved(run_id=9002, database_id=9201)
    assert original.artifact_name == retry.artifact_name
    assert original.record_sha256 != retry.record_sha256

    decision = decide_authority_mirror_delivery(
        candidate=retry,
        artifacts=(
            _mirror(
                artifact_id=61,
                name=original.artifact_name,
                payload=original,
            ),
        ),
        comment_records=(),
        writer_evidence=(
            _evidence(
                run_id=9001,
                database_id=9101,
                job_id="reserve",
                post_conclusion="skipped",
            ),
        ),
        now=NOW + timedelta(minutes=1),
    )

    assert decision.action == "repair_comment"
    assert decision.payload_sha256 == original.record_sha256
    assert decision.stop_after_repair is True


@pytest.mark.parametrize("kind", ("request", "authority"))
def test_successful_post_without_comment_is_tamper_not_repost(kind: str) -> None:
    if kind == "request":
        payload = _receipt(run_id=9001, database_id=9101)
        call = lambda: decide_request_receipt_mirror_delivery(
            candidate=_receipt(run_id=9002, database_id=9201),
            artifacts=(
                _mirror(
                    artifact_id=71,
                    name=payload.artifact_name,
                    payload=payload,
                ),
            ),
            comment_receipts=(),
            writer_evidence=(
                _evidence(
                    run_id=9001,
                    database_id=9101,
                    job_id="report_nonexecuting_decision",
                    post_conclusion="success",
                ),
            ),
            now=NOW + timedelta(minutes=1),
        )
    else:
        payload = _reserved(run_id=9001, database_id=9101)
        call = lambda: decide_authority_mirror_delivery(
            candidate=_reserved(run_id=9002, database_id=9201),
            artifacts=(
                _mirror(
                    artifact_id=72,
                    name=payload.artifact_name,
                    payload=payload,
                ),
            ),
            comment_records=(),
            writer_evidence=(
                _evidence(
                    run_id=9001,
                    database_id=9101,
                    job_id="reserve",
                    post_conclusion="success",
                ),
            ),
            now=NOW + timedelta(minutes=1),
        )

    with pytest.raises(ValueError, match="CATALOG_MIRROR_POST_OUTCOME_AMBIGUOUS"):
        call()


def test_exact_request_comment_and_mirror_are_an_idempotent_noop() -> None:
    original = _receipt(run_id=9001, database_id=9101)
    decision = decide_request_receipt_mirror_delivery(
        candidate=_receipt(run_id=9002, database_id=9201),
        artifacts=(
            _mirror(
                artifact_id=81,
                name=original.artifact_name,
                payload=original,
            ),
        ),
        comment_receipts=(original,),
        writer_evidence=(),
        now=NOW + timedelta(minutes=1),
    )

    assert decision.action == "idempotent"
    assert decision.stop_after_repair is True


def test_duplicate_slot_artifacts_block_even_when_their_bytes_match() -> None:
    receipt = _receipt(run_id=9001, database_id=9101)
    mirrors = tuple(
        _mirror(artifact_id=value, name=receipt.artifact_name, payload=receipt)
        for value in (91, 92)
    )
    with pytest.raises(ValueError, match="CATALOG_MIRROR_SLOT_CONFLICT"):
        decide_request_receipt_mirror_delivery(
            candidate=receipt,
            artifacts=mirrors,
            comment_receipts=(),
            writer_evidence=(),
            now=NOW,
        )


def test_empty_slot_permits_exactly_one_new_upload() -> None:
    decision = decide_request_receipt_mirror_delivery(
        candidate=_receipt(run_id=9001, database_id=9101),
        artifacts=(),
        comment_receipts=(),
        writer_evidence=(),
        now=NOW,
    )
    assert decision.action == "upload_new"
    assert decision.artifact_id is None
    assert decision.stop_after_repair is False


def test_repair_claims_form_a_bounded_hash_chain_before_each_repost() -> None:
    original = _receipt(run_id=9001, database_id=9101)
    decision = decide_request_receipt_mirror_delivery(
        candidate=_receipt(run_id=9002, database_id=9201),
        artifacts=(
            _mirror(
                artifact_id=101,
                name=original.artifact_name,
                payload=original,
            ),
        ),
        comment_receipts=(),
        writer_evidence=(
            _evidence(
                run_id=9001,
                database_id=9101,
                job_id="report_nonexecuting_decision",
                post_conclusion="failure",
            ),
        ),
        now=NOW + timedelta(minutes=1),
    )
    first = prepare_catalog_mirror_repair_claim(
        decision=decision,
        prior_claims=(),
        prior_writer_evidence=(),
        current_writer=_repair_writer(run_id=9002, database_id=9201),
    )
    second = prepare_catalog_mirror_repair_claim(
        decision=decision,
        prior_claims=(first,),
        prior_writer_evidence=(
            _evidence(
                run_id=9002,
                database_id=9201,
                job_id="report_nonexecuting_decision",
                post_conclusion="failure",
            ),
        ),
        current_writer=_repair_writer(
            run_id=9003,
            database_id=9301,
            observed_at=NOW + timedelta(minutes=2),
        ),
    )

    assert first.repair_sequence == 0
    assert first.previous_claim_sha256 is None
    assert second.repair_sequence == 1
    assert second.previous_claim_sha256 == first.claim_sha256
    assert first.artifact_name.endswith("-000")
    assert second.artifact_name.endswith("-001")


def test_successful_repair_claim_without_comment_blocks_a_second_post() -> None:
    decision = decide_request_receipt_mirror_delivery(
        candidate=_receipt(run_id=9002, database_id=9201),
        artifacts=(
            _mirror(
                artifact_id=111,
                name=_receipt(run_id=9001, database_id=9101).artifact_name,
                payload=_receipt(run_id=9001, database_id=9101),
            ),
        ),
        comment_receipts=(),
        writer_evidence=(
            _evidence(
                run_id=9001,
                database_id=9101,
                job_id="report_nonexecuting_decision",
                post_conclusion="failure",
            ),
        ),
        now=NOW + timedelta(minutes=1),
    )
    first = prepare_catalog_mirror_repair_claim(
        decision=decision,
        prior_claims=(),
        prior_writer_evidence=(),
        current_writer=_repair_writer(run_id=9002, database_id=9201),
    )

    with pytest.raises(
        ValueError,
        match="CATALOG_MIRROR_REPAIR_POST_OUTCOME_AMBIGUOUS",
    ):
        prepare_catalog_mirror_repair_claim(
            decision=decision,
            prior_claims=(first,),
            prior_writer_evidence=(
                _evidence(
                    run_id=9002,
                    database_id=9201,
                    job_id="report_nonexecuting_decision",
                    post_conclusion="success",
                ),
            ),
            current_writer=_repair_writer(
                run_id=9003,
                database_id=9301,
                observed_at=NOW + timedelta(minutes=2),
            ),
        )


def test_repair_claim_limit_blocks_unbounded_comment_retries() -> None:
    decision = decide_request_receipt_mirror_delivery(
        candidate=_receipt(run_id=9002, database_id=9201),
        artifacts=(
            _mirror(
                artifact_id=121,
                name=_receipt(run_id=9001, database_id=9101).artifact_name,
                payload=_receipt(run_id=9001, database_id=9101),
            ),
        ),
        comment_receipts=(),
        writer_evidence=(
            _evidence(
                run_id=9001,
                database_id=9101,
                job_id="report_nonexecuting_decision",
                post_conclusion="failure",
            ),
        ),
        now=NOW + timedelta(minutes=1),
    )
    claims: list[CatalogMirrorRepairClaimV1] = []
    evidence: list[CatalogMirrorWriterEvidenceV1] = []
    for offset in range(3):
        claim = prepare_catalog_mirror_repair_claim(
            decision=decision,
            prior_claims=tuple(claims),
            prior_writer_evidence=tuple(evidence),
            current_writer=_repair_writer(
                run_id=9002 + offset,
                database_id=9201 + offset,
                observed_at=NOW + timedelta(minutes=offset),
            ),
        )
        claims.append(claim)
        evidence.append(
            _evidence(
                run_id=9002 + offset,
                database_id=9201 + offset,
                job_id="report_nonexecuting_decision",
                post_conclusion="failure",
            )
        )

    with pytest.raises(ValueError, match="CATALOG_MIRROR_REPAIR_LIMIT_REACHED"):
        prepare_catalog_mirror_repair_claim(
            decision=decision,
            prior_claims=tuple(claims),
            prior_writer_evidence=tuple(evidence),
            current_writer=_repair_writer(
                run_id=9005,
                database_id=9501,
                observed_at=NOW + timedelta(minutes=5),
            ),
        )
