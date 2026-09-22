from dataclasses import replace

import pytest

from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import CheckpointRecoveryOwnerProofV1
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import CHECKPOINT_RECOVERY_SOURCE8_TERMINAL_RECEIPT_SHA256
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityCampaignV1, FastAuthorityStateV1
from aurora.infra.sp500_megarun.catalog_lineage_transition import CatalogLineageTransitionV1
from tests.test_catalog_cloud_authority import emission, signed_request


def _case():
    previous = signed_request(campaign_key="sp500-optimized-catalog-v1", launch_generation=8,
                              previous_terminal_request_sha256="f" * 64)
    prior = emission(request=previous, intent_issue_number=352).advance(
        "PUBLICACION_INCIERTA", post_run_id=35708538575, post_run_attempt=1,
    ).advance("PUBLICADO", issue_number=353)
    owner = FastAuthorityCampaignV1(request=previous, owner_issue_number=353,
        owner_run_id=35708742966, terminal_receipt_sha256=CHECKPOINT_RECOVERY_SOURCE8_TERMINAL_RECEIPT_SHA256)
    state = FastAuthorityStateV1._create(revision=2, previous_state_sha256="a" * 64,
                                       campaigns=(owner,), emissions=(prior,))
    request = signed_request(campaign_key=previous.campaign_key, launch_generation=9,
        previous_terminal_request_sha256=previous.request_sha256,
        request_id="018f47a2-6e91-7c34-8000-000000000009", campaign_definition_sha256="e" * 64)
    item = emission(request=request, intent_issue_number=354,
                    intent_id="e844851d-11dd-4408-96c5-3dd7dd08eac9")
    proof = CheckpointRecoveryOwnerProofV1(profile_sha256="d" * 64,
        campaign_key=previous.campaign_key, target_generation=9,
        source_request_sha256=previous.request_sha256, source_issue_number=353,
        source_run_id=35708742966, source_run_attempt=1,
        source_protected_commit_sha="9f22f9a1f7c6f2646f888c228a4899d0188f586c",
        source_decision_sha256="b" * 64, source_finalizer_job_id=106686205733,
        evidence_kind="failed_owner_with_terminal")
    transition = CatalogLineageTransitionV1(campaign_key=previous.campaign_key,
        previous_request_sha256=previous.request_sha256, next_generation=9,
        target_definition_sha256=request.campaign_definition_sha256,
        target_prompt_sha256=request.prompt_sha256)
    return state, item, proof, transition


def test_terminal_checkpoint_successor_uses_normal_terminal_history_and_reservation():
    state, item, proof, transition = _case()
    staged = state.stage_checkpoint_emission(item, recovery_proof=proof, lineage_transition=transition)
    assert staged == state.stage_emission(item, lineage_transition=transition)
    assert len(staged.completed_intents) == 1
    assert staged.recovery_superseded_intents == ()
    assert staged.campaigns == state.campaigns
    assert staged.stage_checkpoint_emission(item, recovery_proof=proof, lineage_transition=transition) == staged
    published = staged.advance_emission(intent_id=item.intent_id, state="PUBLICACION_INCIERTA",
        post_run_id=700, post_run_attempt=1).advance_emission(
            intent_id=item.intent_id, state="PUBLICADO", issue_number=355)
    reserved = published.reserve_checkpoint_successor(request=item.request, issue_number=355,
        run_id=800, recovery_proof=proof, lineage_transition=transition)
    assert reserved == published.reserve(request=item.request, issue_number=355, run_id=800,
                                        lineage_transition=transition)
    assert reserved.reserve_checkpoint_successor(request=item.request, issue_number=355,
        run_id=800, recovery_proof=proof, lineage_transition=transition) == reserved


@pytest.mark.parametrize("defect", ["terminal", "nonterminal", "kind", "source", "lineage"])
def test_terminal_checkpoint_successor_requires_exact_terminal_authority(defect):
    state, item, proof, transition = _case()
    if defect in {"terminal", "nonterminal"}:
        owner = state.campaigns[0].model_copy(update={
            "terminal_receipt_sha256": "e" * 64 if defect == "terminal" else None})
        state = FastAuthorityStateV1._create(revision=2, previous_state_sha256="a" * 64,
                                            campaigns=(owner,), emissions=state.emissions)
    elif defect == "kind":
        proof = replace(proof, evidence_kind="failed_owner_without_terminal")
    elif defect == "source":
        proof = replace(proof, source_run_id=999)
    else:
        transition = None
    with pytest.raises(ValueError, match="CATALOG_CHECKPOINT_RECOVERY_PREDECESSOR_INVALID"):
        state.stage_checkpoint_emission(item, recovery_proof=proof, lineage_transition=transition)
