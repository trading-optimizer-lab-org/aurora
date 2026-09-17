from uuid import UUID

import pytest

from aurora.infra.sp500_megarun.catalog_cloud_ticket import select_cloud_launch_ticket
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogLaunchTicketV1
from tests.test_catalog_cloud_authority import emission
from tests.test_catalog_cloud_intake import _validate, INTENT_ID


def ticket_for(request):
    return CatalogLaunchTicketV1.model_validate({
        key: getattr(request, key) for key in CatalogLaunchTicketV1.model_fields
    })


def select(state, imported=None, **changes):
    arguments = dict(
        authority=state, intent=_validate(),
        campaign_definition_sha256=emission().request.campaign_definition_sha256,
        prompt_sha256=emission().request.prompt_sha256, imported_ticket=imported,
        new_request_id=lambda: UUID("018f47a2-6e91-7c34-8000-000000000099"),
    )
    arguments.update(changes)
    return select_cloud_launch_ticket(**arguments)


def terminal_state():
    item = emission()
    state = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(item)
    state = state.advance_emission(intent_id=item.intent_id, state="PUBLICACION_INCIERTA",
                                   post_run_id=500, post_run_attempt=1)
    state = state.advance_emission(intent_id=item.intent_id, state="PUBLICADO", issue_number=401)
    state = state.reserve(request=item.request, issue_number=401, run_id=501)
    return state.terminalize(request=item.request, run_id=501, terminal_receipt_sha256="d" * 64)


def test_first_cloud_emission_preserves_imported_uuid_and_ticket_hash():
    state = FastAuthorityStateV1.bootstrap(campaigns=())
    imported = ticket_for(emission().request)
    assert select(state, imported) == imported


def test_missing_import_does_not_recreate_ticket():
    with pytest.raises(ValueError, match="CUTOVER_TICKET_REQUIRED"):
        select(FastAuthorityStateV1.bootstrap(campaigns=()))


def test_terminal_advances_one_generation_with_exact_predecessor():
    state = terminal_state()
    ticket = select(state)
    assert ticket.launch_generation == 2
    assert ticket.previous_terminal_request_sha256 == state.campaigns[0].request.request_sha256
    assert ticket.request_id == "018f47a2-6e91-7c34-8000-000000000099"
    assert state.campaigns[0].generation == 1


def test_cloud_successor_without_terminal_receipt_fails_closed():
    first = emission()
    state = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(first)
    state = state.advance_emission(intent_id=first.intent_id, state="PUBLICACION_INCIERTA",
                                   post_run_id=500, post_run_attempt=1)
    state = state.advance_emission(intent_id=first.intent_id, state="PUBLICADO", issue_number=401)
    state = state.reserve(request=first.request, issue_number=401, run_id=501)

    assert state.emissions[0].state == "PUBLICADO"
    assert state.campaigns[0].terminal_receipt_sha256 is None
    with pytest.raises(ValueError, match="CAMPAIGN_BUSY"):
        select(state)


def test_pending_emission_cannot_consume_another_ticket():
    state = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(emission())
    with pytest.raises(ValueError, match="CAMPAIGN_BUSY"):
        select(state, ticket_for(emission().request))


def test_replay_never_generates_ticket():
    item = emission(intent_id=INTENT_ID)
    state = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(item)
    with pytest.raises(ValueError, match="REPLAY_REQUIRED"):
        select(state)


def test_context_change_requires_exact_protected_lineage_permission():
    with pytest.raises(ValueError, match="LINEAGE_TRANSITION_REQUIRED"):
        select(terminal_state(), prompt_sha256="c" * 64)


def test_imported_ticket_is_not_silently_migrated():
    with pytest.raises(ValueError, match="TICKET_CONTEXT_MISMATCH"):
        select(FastAuthorityStateV1.bootstrap(campaigns=()), ticket_for(emission().request),
               prompt_sha256="c" * 64)
