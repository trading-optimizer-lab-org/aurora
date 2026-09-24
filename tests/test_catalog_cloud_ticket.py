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


def test_protected_atlas_initial_ticket_is_generation_one_only():
    intent = _validate().model_copy(update={"campaign_key": "sp500-atlas-v1"})
    state = FastAuthorityStateV1.bootstrap(campaigns=())
    ticket = select(state, intent=intent, cloud_native_initial=True)
    assert ticket.campaign_key == "sp500-atlas-v1"
    assert ticket.launch_generation == 1
    assert ticket.previous_terminal_request_sha256 is None
    assert ticket.request_id == "018f47a2-6e91-7c34-8000-000000000099"
    assert ticket.campaign_definition_sha256 == emission().request.campaign_definition_sha256

    with pytest.raises(ValueError, match="CUTOVER_TICKET_REQUIRED"):
        select(state, cloud_native_initial=True)


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


@pytest.mark.parametrize('defect', [None, 'run', 'request', 'generation', 'lineage'])
def test_checkpoint_ticket_requires_exact_failed_owner_and_lineage(defect):
    from dataclasses import replace
    from tests.test_catalog_checkpoint_recovery_authority import _case

    state, _, item, proof, lineage = _case()
    intent = _validate().model_copy(update={
        'campaign_key': item.request.campaign_key, 'intent_id': item.intent_id,
    })
    if defect == 'run':
        proof = replace(proof, source_run_id=123)
    elif defect == 'request':
        proof = replace(proof, source_request_sha256='f' * 64)
    elif defect == 'generation':
        proof = replace(proof, target_generation=9)
    elif defect == 'lineage':
        lineage = None
    arguments = dict(authority=state, intent=intent,
        campaign_definition_sha256=item.request.campaign_definition_sha256,
        prompt_sha256=item.request.prompt_sha256, imported_ticket=None,
        lineage_transition=lineage, recovery_proof=proof,
        new_request_id=lambda: UUID(item.request.request_id))
    if defect:
        with pytest.raises(ValueError, match='CATALOG_CHECKPOINT_RECOVERY_'):
            select_cloud_launch_ticket(**arguments)
    else:
        ticket = select_cloud_launch_ticket(**arguments)
        assert ticket == ticket_for(item.request)
        assert not state.campaigns[0].is_terminal


def test_checkpoint_ticket_without_source_emission_is_rejected_before_signing():
    from tests.test_catalog_checkpoint_recovery_authority import _case

    state, _, item, proof, lineage = _case()
    without_emission = FastAuthorityStateV1._create(revision=state.revision,
        previous_state_sha256=state.previous_state_sha256, campaigns=state.campaigns)
    intent = _validate().model_copy(update={'campaign_key': item.request.campaign_key,
                                          'intent_id': item.intent_id})
    with pytest.raises(ValueError, match='CATALOG_CHECKPOINT_RECOVERY_EMISSION_INVALID'):
        select_cloud_launch_ticket(authority=without_emission, intent=intent,
            campaign_definition_sha256=item.request.campaign_definition_sha256,
            prompt_sha256=item.request.prompt_sha256, imported_ticket=ticket_for(item.request),
            lineage_transition=lineage, recovery_proof=proof)
