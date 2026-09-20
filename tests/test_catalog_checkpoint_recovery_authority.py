"""A failed owner can only be superseded through its explicit recovery proof."""
from dataclasses import replace

import pytest

from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import CheckpointRecoveryOwnerProofV1
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityCampaignV1, FastAuthorityStateV1
from aurora.infra.sp500_megarun.catalog_lineage_transition import CatalogLineageTransitionV1
from tests.test_catalog_cloud_authority import emission, signed_request


def _case():
    previous = signed_request(campaign_key='sp500-optimized-catalog-v1', launch_generation=7,
                              previous_terminal_request_sha256='f' * 64)
    prior = emission(request=previous, intent_issue_number=338).advance(
        'PUBLICACION_INCIERTA', post_run_id=35504326076, post_run_attempt=1,
    ).advance('PUBLICADO', issue_number=339)
    owner = FastAuthorityCampaignV1(request=previous, owner_issue_number=339, owner_run_id=35504391586)
    state = FastAuthorityStateV1._create(revision=2, previous_state_sha256='a' * 64,
                                       campaigns=(owner,), emissions=(prior,))
    request = signed_request(campaign_key=previous.campaign_key, launch_generation=8,
                             previous_terminal_request_sha256=previous.request_sha256,
                             request_id='018f47a2-6e91-7c34-8000-000000000008',
                             campaign_definition_sha256='e' * 64)
    item = emission(request=request, intent_issue_number=340,
                    intent_id='e844851d-11dd-4408-96c5-3dd7dd08eac1')
    proof = CheckpointRecoveryOwnerProofV1(
        profile_sha256='d' * 64, campaign_key=previous.campaign_key, target_generation=8,
        source_request_sha256=previous.request_sha256, source_issue_number=339,
        source_run_id=35504391586, source_run_attempt=1,
        source_protected_commit_sha='d12a374ab84bfb4e79bd5039343ffd5bd963c115',
        source_decision_sha256='b' * 64, source_finalizer_job_id=106062671367,
    )
    lineage = CatalogLineageTransitionV1(
        campaign_key=previous.campaign_key, previous_request_sha256=previous.request_sha256,
        next_generation=8, target_definition_sha256=request.campaign_definition_sha256,
        target_prompt_sha256=request.prompt_sha256,
    )
    return state, prior, item, proof, lineage


def _stage(state, item, proof, lineage):
    method = getattr(state, 'stage_checkpoint_emission', None)
    assert method is not None, 'Recovery must not pretend the previous owner has a terminal'
    return method(item, recovery_proof=proof, lineage_transition=lineage)


def test_checkpoint_successor_preserves_original_nonterminal_history():
    state, prior, item, proof, lineage = _case()
    staged = _stage(state, item, proof, lineage)
    assert staged.campaigns == state.campaigns
    assert not staged.campaigns[0].is_terminal
    assert staged.completed_intents == ()
    assert staged.emissions == (item,)
    archived = staged.recovery_superseded_intents[0]
    assert archived.emission == prior
    assert archived.source_owner_run_id == 35504391586
    assert archived.recovery_evidence_sha256 == proof.evidence_sha256
    assert archived.successor_request_sha256 == item.request.request_sha256
    assert staged.stage_checkpoint_emission(item, recovery_proof=proof, lineage_transition=lineage) == staged
    uncertain = staged.advance_emission(intent_id=item.intent_id, state='PUBLICACION_INCIERTA',
                                         post_run_id=700, post_run_attempt=1)
    published = uncertain.advance_emission(intent_id=item.intent_id, state='PUBLICADO', issue_number=341)
    reserved = published.reserve_checkpoint_successor(request=item.request, issue_number=341,
                                                       run_id=800, recovery_proof=proof,
                                                       lineage_transition=lineage)
    assert reserved.campaigns[0].generation == 8
    assert reserved.campaigns[0].owner_run_id == 800
    assert reserved.campaigns[0].terminal_receipt_sha256 is None
    assert reserved.recovery_superseded_intents == staged.recovery_superseded_intents
    assert reserved.previous_state_sha256 == published.state_sha256
    assert reserved.reserve_checkpoint_successor(request=item.request, issue_number=341, run_id=801,
                                                  recovery_proof=proof, lineage_transition=lineage) == reserved
    terminal = reserved.terminalize(request=item.request, run_id=800, terminal_receipt_sha256='c' * 64)
    assert terminal.recovery_superseded_intents == staged.recovery_superseded_intents
    reopened = FastAuthorityStateV1.model_validate_json(terminal.model_dump_json())
    assert reopened == terminal


def test_normal_reservation_still_rejects_missing_terminal():
    state, prior, item, proof, lineage = _case()
    with pytest.raises(ValueError, match='CATALOG_CLOUD_EMISSION_REQUEST_MISMATCH'):
        state.reserve(request=item.request, issue_number=341, run_id=800, lineage_transition=lineage)
    with pytest.raises(ValueError, match='CATALOG_CAMPAIGN_BUSY'):
        state.stage_emission(item, lineage_transition=lineage)


@pytest.mark.parametrize('defect', ['run', 'issue', 'request', 'campaign', 'generation', 'lineage', 'terminal', 'unpublished'])
def test_checkpoint_transition_rejects_mismatched_source(defect):
    state, prior, item, proof, lineage = _case()
    if defect == 'run':
        proof = replace(proof, source_run_id=123)
    elif defect == 'issue':
        proof = replace(proof, source_issue_number=123)
    elif defect == 'request':
        proof = replace(proof, source_request_sha256='e' * 64)
    elif defect == 'campaign':
        proof = replace(proof, campaign_key='catalog-fast-canary-v1')
    elif defect == 'generation':
        proof = replace(proof, target_generation=9)
    elif defect == 'lineage':
        lineage = None
    elif defect == 'terminal':
        state = state.terminalize(request=prior.request, run_id=35504391586, terminal_receipt_sha256='c' * 64)
    elif defect == 'unpublished':
        state = FastAuthorityStateV1._create(revision=state.revision, previous_state_sha256=state.previous_state_sha256,
                                           campaigns=state.campaigns, emissions=(emission(request=prior.request),))
    with pytest.raises(ValueError, match='CATALOG_CHECKPOINT_RECOVERY_'):
        _stage(state, item, proof, lineage)


def test_legacy_authority_wire_shape_does_not_gain_recovery_fields():
    state = FastAuthorityStateV1.bootstrap(campaigns=())
    assert 'recovery_superseded_intents' not in state.model_dump(mode='json')


@pytest.mark.parametrize('operation', ['reserve', 'terminalize'])
def test_superseded_source_cannot_be_reserved_or_terminalized(operation):
    state, prior, item, proof, lineage = _case()
    staged = _stage(state, item, proof, lineage)
    with pytest.raises(ValueError, match='CATALOG_CHECKPOINT_RECOVERY_SOURCE_SUPERSEDED'):
        if operation == 'reserve':
            staged.reserve(request=prior.request, issue_number=339, run_id=999)
        else:
            staged.terminalize(request=prior.request, run_id=35504391586,
                               terminal_receipt_sha256='c' * 64)


@pytest.mark.parametrize('mismatch', [None, 'issue_number', 'author_id'])
def test_superseded_intent_replays_original_published_request(mismatch):
    from aurora.infra.sp500_megarun.catalog_cloud_replay import resolve_cloud_replay
    from tests.test_catalog_cloud_intake import _validate

    state, prior, item, proof, lineage = _case()
    staged = _stage(state, item, proof, lineage)
    intent = _validate().model_copy(update={
        'intent_id': prior.intent_id, 'campaign_key': prior.request.campaign_key,
        'issue_number': prior.intent_issue_number, 'repository_id': prior.repository_id,
        'author_id': prior.actor_id,
    })
    if mismatch:
        intent = intent.model_copy(update={mismatch: 999})
        with pytest.raises(ValueError, match='CATALOG_CLOUD_INTENT_CONFLICT'):
            resolve_cloud_replay(staged, intent)
    else:
        assert resolve_cloud_replay(staged, intent) == prior
        assert resolve_cloud_replay(staged, intent).state == 'PUBLICADO'
        assert not staged.campaigns[0].is_terminal
