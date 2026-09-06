"""Durable state transitions and exact server-edit publication binding."""

import pytest

from aurora.infra.sp500_megarun.catalog_fast_authority import (
    FastAuthorityCampaignV1, FastAuthorityStateV1, bind_authority_edit, verify_authority_edit,
)
from tests.test_catalog_fast_path import _request


def test_reservation_publication_reopens_same_revision_without_reset() -> None:
    initial = FastAuthorityStateV1.bootstrap(campaigns=())
    reserved = initial.reserve(request=_request(), issue_number=280, run_id=100)
    publication = bind_authority_edit(
        state=reserved, issue_node_id="ledger-node", edit_node_id="edit-1",
    )
    reopened = verify_authority_edit(
        body=reserved.to_body(), publication_json=publication.model_dump_json(),
        issue_node_id="ledger-node", latest_edit_node_id="edit-1",
    )
    assert reopened.revision == 2
    assert reopened.campaigns[0].generation == 1
    assert reopened.campaigns[0].owner_run_id == 100
    assert reopened.state_sha256 == reserved.state_sha256


def test_replayed_intention_keeps_original_owner_and_revision() -> None:
    state = FastAuthorityStateV1.bootstrap(campaigns=()).reserve(
        request=_request(), issue_number=280, run_id=100,
    )
    repeated = state.reserve(request=_request(), issue_number=281, run_id=101)
    assert repeated == state


def test_busy_campaign_does_not_replace_owner() -> None:
    state = FastAuthorityStateV1.bootstrap(campaigns=()).reserve(
        request=_request(), issue_number=280, run_id=100,
    )
    with pytest.raises(ValueError, match="CATALOG_CAMPAIGN_BUSY"):
        state.reserve(request=_request(request_id="018f47a2-6e91-7c34-8000-000000000002"), issue_number=281, run_id=101)


def test_terminal_requires_owner_and_preserves_high_water() -> None:
    state = FastAuthorityStateV1.bootstrap(campaigns=()).reserve(
        request=_request(), issue_number=280, run_id=100,
    )
    with pytest.raises(ValueError, match="CATALOG_FAST_AUTHORITY_OWNER_MISMATCH"):
        state.terminalize(request=_request(), run_id=101, terminal_receipt_sha256="c" * 64)
    terminal = state.terminalize(request=_request(), run_id=100, terminal_receipt_sha256="c" * 64)
    assert terminal.revision == 3
    assert terminal.campaigns[0].generation == 1
    assert terminal.campaigns[0].terminal_receipt_sha256 == "c" * 64
    assert terminal.terminalize(request=_request(), run_id=100, terminal_receipt_sha256="c" * 64) == terminal
    assert terminal.reserve(request=_request(), issue_number=282, run_id=102) == terminal


@pytest.mark.parametrize("edit,node", [("edit-restored", "ledger-node"), ("edit-1", "other-ledger")])
def test_old_publication_cannot_validate_recreated_body(edit: str, node: str) -> None:
    state = FastAuthorityStateV1.bootstrap(campaigns=())
    proof = bind_authority_edit(state=state, issue_node_id="ledger-node", edit_node_id="edit-1")
    with pytest.raises(ValueError, match="CATALOG_FAST_AUTHORITY_EDIT_MISMATCH"):
        verify_authority_edit(body=state.to_body(), publication_json=proof.model_dump_json(), issue_node_id=node, latest_edit_node_id=edit)


def test_new_generation_requires_exact_terminal_predecessor() -> None:
    request = _request()
    state = FastAuthorityStateV1.bootstrap(campaigns=()).reserve(request=request, issue_number=280, run_id=100)
    state = state.terminalize(request=request, run_id=100, terminal_receipt_sha256="c" * 64)
    with pytest.raises(ValueError, match="CATALOG_FAST_PREDECESSOR_CONFLICT"):
        state.reserve(request=_request(request_id="018f47a2-6e91-7c34-8000-000000000002", launch_generation=2, previous_terminal_request_sha256="f" * 64), issue_number=281, run_id=101)
    next_request = _request(request_id="018f47a2-6e91-7c34-8000-000000000002", launch_generation=2, previous_terminal_request_sha256=request.request_sha256)
    successor = state.reserve(request=next_request, issue_number=281, run_id=101)
    assert successor.campaigns[0].generation == 2
    assert successor.campaigns[0].owner_run_id == 101


def test_state_hash_is_verified_not_repaired_on_input() -> None:
    state = FastAuthorityStateV1.bootstrap(campaigns=())
    payload = state.model_dump(mode="json")
    payload["revision"] = 50
    payload["previous_state_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="CATALOG_FAST_AUTHORITY_HASH_INVALID"):
        FastAuthorityStateV1.model_validate(payload)


def test_maintenance_import_preserves_generation_without_inventing_science() -> None:
    old_request = _request(launch_generation=6, previous_terminal_request_sha256="e" * 64)
    imported = FastAuthorityCampaignV1.model_validate({
        "request": old_request.model_dump(mode="json"),
        "owner_issue_number": 276, "owner_run_id": 33910681070,
        "legacy_closure_evidence_sha256": "d" * 64,
    })
    state = FastAuthorityStateV1.bootstrap(campaigns=(imported,))
    reopened = FastAuthorityStateV1.model_validate_json(state.model_dump_json())
    assert reopened.campaigns[0].generation == 6
    assert reopened.campaigns[0].terminal_receipt_sha256 is None
    successor = _request(
        request_id="018f47a2-6e91-7c34-8000-000000000002", launch_generation=7,
        previous_terminal_request_sha256=old_request.request_sha256,
    )
    next_state = reopened.reserve(request=successor, issue_number=280, run_id=100)
    assert next_state.campaigns[0].generation == 7
    assert next_state.campaigns[0].legacy_closure_evidence_sha256 is None


def test_live_terminal_does_not_fabricate_legacy_closure() -> None:
    reserved = FastAuthorityStateV1.bootstrap(campaigns=()).reserve(
        request=_request(), issue_number=280, run_id=100,
    )
    closed = reserved.terminalize(request=_request(), run_id=100, terminal_receipt_sha256="c" * 64)
    assert closed.campaigns[0].legacy_closure_evidence_sha256 is None
    assert closed.campaigns[0].terminal_receipt_sha256 == "c" * 64
