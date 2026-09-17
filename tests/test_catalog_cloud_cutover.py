from datetime import datetime, timezone
import json

import pytest

from aurora.infra.sp500_megarun.catalog_cloud_cutover import CloudLocalRetirementV1, imported_cloud_ticket, load_cloud_retirement
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogLaunchTicketV1, canonical_sha256
from aurora.infra.sp500_megarun.catalog_requester import CatalogRequesterCampaignStatusV1
from aurora.infra.sp500_megarun.catalog_requester_broker import _ticket_journal
from tests.test_catalog_cloud_ticket import ticket_for
from tests.test_catalog_cloud_authority import emission
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1

NOW = datetime(2026, 9, 17, 13, 0, tzinfo=timezone.utc)


def retirement_payload(ticket):
    journal = _ticket_journal(ticket=ticket, state="available", submission_key_sha256=None,
        request_sha256=None, issue_number=None, created_at=NOW, updated_at=NOW)
    status = CatalogRequesterCampaignStatusV1.create(campaign_key=ticket.campaign_key,
        state="ticket_available", launch_generation=ticket.launch_generation,
        launch_ticket_sha256=ticket.launch_ticket_sha256, updated_at=NOW)
    draft = CloudLocalRetirementV1.model_construct(
        schema_version="1", repository="trading-optimizer-lab-org/aurora", source_commit="a" * 40,
        observed_at=NOW, task_name="AURORA Catalog Requester Broker", task_state="Disabled",
        running_instances=0, inbox_pending_entries=0, processing_pending_entries=0,
        authority_state_sha256="b" * 64,
        campaigns=({"journal": journal.model_dump(mode="json"), "status": status.model_dump(mode="json")},),
        receipt_sha256="0" * 64,
    )
    payload = draft.model_dump(mode="json", warnings=False)
    # Hash the same typed nested objects used by the consumer.
    from aurora.infra.sp500_megarun.catalog_cloud_cutover import CloudImportedCampaignV1
    draft = draft.model_copy(update={"campaigns": tuple(CloudImportedCampaignV1.model_validate(row) for row in payload["campaigns"])})
    payload["receipt_sha256"] = canonical_sha256(draft)
    return payload


def write_retirement(root, ticket):
    (root / "config").mkdir(exist_ok=True)
    path = root / "config/catalog_cloud_local_retirement_v1.json"
    path.write_text(json.dumps(retirement_payload(ticket)), encoding="utf-8")
    return path


def test_absent_retirement_is_not_bootstrapped(tmp_path):
    with pytest.raises(ValueError, match="LOCAL_RETIREMENT_REQUIRED"):
        load_cloud_retirement(tmp_path)


def test_actual_import_preserves_ticket_identity(tmp_path):
    ticket = ticket_for(emission().request)
    write_retirement(tmp_path, ticket)
    imported = imported_cloud_ticket(root=tmp_path, authority=FastAuthorityStateV1.bootstrap(campaigns=()),
        campaign_key=ticket.campaign_key, campaign_definition_sha256=ticket.campaign_definition_sha256,
        prompt_sha256=ticket.prompt_sha256)
    assert imported == ticket


def test_first_import_after_legacy_sp500_without_cloud_emission_is_allowed(tmp_path):
    first = emission()
    authority = FastAuthorityStateV1.bootstrap(campaigns=()).reconcile_legacy_closure(
        request=first.request,
        issue_number=first.intent_issue_number,
        historical_run_id=501,
        legacy_closure_evidence_sha256="c" * 64,
    )
    ticket = ticket_for(first.request)
    write_retirement(tmp_path, ticket)

    imported = imported_cloud_ticket(
        root=tmp_path,
        authority=authority,
        campaign_key=ticket.campaign_key,
        campaign_definition_sha256=ticket.campaign_definition_sha256,
        prompt_sha256=ticket.prompt_sha256,
    )

    assert imported == ticket
    assert authority.emissions == ()
    assert authority.campaigns[0].legacy_closure_evidence_sha256 == "c" * 64


@pytest.mark.parametrize("field,value", [
    ("task_state", "Ready"), ("running_instances", 1), ("inbox_pending_entries", 1),
    ("processing_pending_entries", 1), ("inbox_pending_entries", False),
    ("receipt_sha256", "0" * 64),
])
def test_unproven_exclusivity_or_tampering_blocks_import(field, value):
    payload = retirement_payload(ticket_for(emission().request))
    payload[field] = value
    with pytest.raises(ValueError):
        CloudLocalRetirementV1.model_validate(payload)


def test_context_migration_reuses_existing_consumer_and_never_replaces_uuid(tmp_path):
    from tests.test_catalog_fast_authority import _lineage_boundary
    state, request, approval = _lineage_boundary()
    old = state.campaigns[0].request
    ticket = CatalogLaunchTicketV1(schema_version="1", request_id=request.request_id,
        campaign_key=request.campaign_key, launch_generation=request.launch_generation,
        previous_terminal_request_sha256=old.request_sha256,
        campaign_definition_sha256=old.campaign_definition_sha256, prompt_sha256=old.prompt_sha256)
    write_retirement(tmp_path, ticket)
    (tmp_path / "config/catalog_lineage_transitions_v1.json").write_text(json.dumps({
        "schema_version": "1", "transitions": [approval.model_dump(mode="json")],
    }), encoding="utf-8")
    migrated = imported_cloud_ticket(root=tmp_path, authority=state, campaign_key=ticket.campaign_key,
        campaign_definition_sha256=request.campaign_definition_sha256, prompt_sha256=request.prompt_sha256)
    assert migrated.request_id == ticket.request_id
    assert migrated.launch_generation == ticket.launch_generation
    assert migrated.previous_terminal_request_sha256 == ticket.previous_terminal_request_sha256
    assert migrated.prompt_sha256 == request.prompt_sha256
