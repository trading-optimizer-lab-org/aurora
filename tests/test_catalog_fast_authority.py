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


def test_definition_change_cannot_reuse_imported_generation_without_maintenance() -> None:
    """Regression: fixing only the local generation-seven ticket is insufficient."""
    old_request = _request(launch_generation=6, previous_terminal_request_sha256="e" * 64)
    imported = FastAuthorityCampaignV1(
        request=old_request, owner_issue_number=276, owner_run_id=33910681070,
        legacy_closure_evidence_sha256="d" * 64,
    )
    state = FastAuthorityStateV1.bootstrap(campaigns=(imported,))
    before = state.model_dump_json()
    successor = _request(
        request_id="018f47a2-6e91-7c34-8000-000000000002", launch_generation=7,
        previous_terminal_request_sha256=old_request.request_sha256,
        campaign_definition_sha256="a" * 64,
    )
    assert successor.campaign_definition_sha256 != old_request.campaign_definition_sha256
    with pytest.raises(ValueError, match="^CATALOG_FAST_AUTHORITY_LINEAGE_CHANGE_REQUIRES_MAINTENANCE$"):
        state.reserve(request=successor, issue_number=280, run_id=100)
    assert state.model_dump_json() == before


def _lineage_boundary():
    from aurora.infra.sp500_megarun.catalog_fast_authority import CatalogLineageTransitionV1

    old = _request(launch_generation=6, previous_terminal_request_sha256="e" * 64)
    state = FastAuthorityStateV1.bootstrap(campaigns=(FastAuthorityCampaignV1(
        request=old, owner_issue_number=276, owner_run_id=100,
        legacy_closure_evidence_sha256="d" * 64,
    ),))
    new = _request(
        request_id="018f47a2-6e91-7c34-8000-000000000002", launch_generation=7,
        previous_terminal_request_sha256=old.request_sha256,
        campaign_definition_sha256="a" * 64, prompt_sha256="b" * 64,
    )
    approval = CatalogLineageTransitionV1(
        campaign_key=old.campaign_key, previous_request_sha256=old.request_sha256,
        next_generation=7, target_definition_sha256=new.campaign_definition_sha256,
        target_prompt_sha256=new.prompt_sha256,
    )
    return state, new, approval


def test_approved_lineage_boundary_preserves_old_request_and_revision_chain() -> None:
    state, request, approval = _lineage_boundary()
    original = state.model_dump_json()
    reserved = state.reserve(request=request, issue_number=280, run_id=101,
                             lineage_transition=approval)
    assert state.model_dump_json() == original
    assert reserved.previous_state_sha256 == state.state_sha256
    assert reserved.revision == state.revision + 1
    assert reserved.campaigns[0].request == request
    assert reserved.campaigns[0].generation == 7
    assert not reserved.campaigns[0].is_terminal
    assert reserved.reserve(request=request, issue_number=281, run_id=102) == reserved


@pytest.mark.parametrize("field,value", [
    ("campaign_key", "another-campaign"),
    ("previous_request_sha256", "f" * 64),
    ("next_generation", 8),
    ("target_definition_sha256", "f" * 64),
    ("target_prompt_sha256", "f" * 64),
])
def test_lineage_approval_must_match_every_boundary_field(field, value) -> None:
    state, request, approval = _lineage_boundary()
    approval = type(approval).model_validate({**approval.model_dump(), field: value})
    with pytest.raises(ValueError, match="LINEAGE_CHANGE_REQUIRES_MAINTENANCE"):
        state.reserve(request=request, issue_number=280, run_id=101,
                      lineage_transition=approval)


def test_lineage_approval_cannot_release_active_owner() -> None:
    state, request, approval = _lineage_boundary()
    active = FastAuthorityStateV1.bootstrap(campaigns=(FastAuthorityCampaignV1(
        request=state.campaigns[0].request, owner_issue_number=276, owner_run_id=100,
    ),))
    with pytest.raises(ValueError, match="CATALOG_CAMPAIGN_BUSY"):
        active.reserve(request=request, issue_number=280, run_id=101,
                       lineage_transition=approval)


def test_lineage_permission_is_loaded_only_from_fixed_protected_config(tmp_path) -> None:
    import json
    from aurora.infra.sp500_megarun.catalog_fast_authority import load_lineage_transition

    state, request, approval = _lineage_boundary()
    assert load_lineage_transition(tmp_path, request) is None
    config = tmp_path / "config"
    config.mkdir()
    (config / "catalog_lineage_transitions_v1.json").write_text(json.dumps({
        "schema_version": "1", "transitions": [approval.model_dump(mode="json")],
    }))
    loaded = load_lineage_transition(tmp_path, request)
    assert state.reserve(request=request, issue_number=280, run_id=101,
                         lineage_transition=loaded).campaigns[0].generation == 7


@pytest.mark.parametrize("defect", ["duplicate_field", "duplicate_boundary", "unknown_field", "oversized"])
def test_ambiguous_or_malformed_lineage_config_never_authorizes(tmp_path, defect) -> None:
    import json
    from aurora.infra.sp500_megarun.catalog_fast_authority import load_lineage_transition

    _, request, approval = _lineage_boundary()
    payload = {"schema_version": "1", "transitions": [approval.model_dump(mode="json")]}
    if defect == "duplicate_boundary":
        payload["transitions"].append(approval.model_dump(mode="json"))
    if defect == "unknown_field":
        payload["allow_any_version"] = True
    raw = json.dumps(payload)
    if defect == "duplicate_field":
        raw = raw.replace('"schema_version": "1"', '"schema_version": "1", "schema_version": "1"')
    if defect == "oversized":
        raw += " " * 65536
    (tmp_path / "config").mkdir()
    (tmp_path / "config/catalog_lineage_transitions_v1.json").write_text(raw)
    with pytest.raises(ValueError, match="CATALOG_LINEAGE_CONFIG_INVALID"):
        load_lineage_transition(tmp_path, request)
