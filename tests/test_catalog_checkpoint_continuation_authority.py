"""Target-generation-10 authority keeps source and immediate predecessor distinct."""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID
from types import SimpleNamespace

import pytest

from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import (
    CheckpointRecoveryOwnerProofV1,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    CHECKPOINT_RECOVERY_CAMPAIGN_KEY,
    CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER,
    CHECKPOINT_RECOVERY_CONTINUATION_PREDECESSOR_GENERATION,
    CHECKPOINT_RECOVERY_CONTINUATION_PROTECTED_COMMIT_SHA,
    CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256,
    CHECKPOINT_RECOVERY_CONTINUATION_RUN_ATTEMPT,
    CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID,
    CHECKPOINT_RECOVERY_CONTINUATION_TERMINAL_RECEIPT_SHA256,
    CHECKPOINT_RECOVERY_SOURCE8_ISSUE_NUMBER,
    CHECKPOINT_RECOVERY_SOURCE8_PROTECTED_COMMIT_SHA,
    CHECKPOINT_RECOVERY_SOURCE8_REQUEST_SHA256,
    CHECKPOINT_RECOVERY_SOURCE8_RUN_ATTEMPT,
    CHECKPOINT_RECOVERY_SOURCE8_RUN_ID,
    CHECKPOINT_RECOVERY_SOURCE8_TERMINAL_RECEIPT_SHA256,
)
from aurora.infra.sp500_megarun.catalog_cloud_emission import CatalogCloudEmissionV1
from aurora.infra.sp500_megarun.catalog_fast_authority import (
    FastAuthorityStateV1,
)
from aurora.infra.sp500_megarun.catalog_lineage_transition import (
    CatalogLineageTransitionV1,
)
from aurora.infra.sp500_megarun.catalog_request_contract import (
    CatalogRunRequestV1,
    CatalogLaunchTicketV1,
)
from tests.test_catalog_checkpoint_terminal_authority import _case as terminal_case
from tests.test_catalog_cloud_authority import emission, signed_request
from tests.test_catalog_cloud_intake import _validate
from aurora.infra.sp500_megarun.catalog_cloud_ticket import select_cloud_launch_ticket


GEN9_REQUEST_ID = "018f47a2-6e91-7c34-8000-000000000009"
GEN10_REQUEST_ID = "018f47a2-6e91-7c34-8000-000000000010"
GEN10_INTENT_ID = "e844851d-11dd-4408-96c5-3dd7dd08eaca"
GEN10_PROFILE_SHA256 = "d" * 64


def test_cloud_ticket10_keeps_terminal360_not_physical_source353(monkeypatch):
    state, item, proof, lineage = _case(monkeypatch)
    ticket = select_cloud_launch_ticket(
        authority=state, intent=_validate(),
        campaign_definition_sha256=item.request.campaign_definition_sha256,
        prompt_sha256=item.request.prompt_sha256, imported_ticket=None,
        lineage_transition=lineage, recovery_proof=proof,
        new_request_id=lambda: UUID(GEN10_REQUEST_ID),
    )
    assert ticket.launch_generation == 10
    assert ticket.previous_terminal_request_sha256 == CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256
    assert ticket.previous_terminal_request_sha256 != proof.source_request_sha256


@pytest.mark.parametrize("reject_predecessor", [False, True])
def test_generation10_admission_authenticates_before_reserving(monkeypatch, tmp_path, reject_predecessor):
    from scripts import admit_catalog_fast_request as admission

    state, item, proof, lineage = _case(monkeypatch)
    staged = state.stage_checkpoint_emission(item, recovery_proof=proof, lineage_transition=lineage)
    staged = staged.advance_emission(intent_id=item.intent_id, state="PUBLICACION_INCIERTA",
                                     post_run_id=700, post_run_attempt=1)
    staged = staged.advance_emission(intent_id=item.intent_id, state="PUBLICADO", issue_number=362)
    profile = object()
    monkeypatch.setattr(admission, "load_checkpoint_recovery_profile", lambda *args: profile)
    monkeypatch.setattr(admission, "load_lineage_transition", lambda *args: lineage)
    calls = []

    def authenticate(**kwargs):
        assert kwargs["profile"] is profile
        calls.append("authenticate")
        if reject_predecessor:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PREDECESSOR_AUTH_INVALID")
        return SimpleNamespace(proof=proof)

    monkeypatch.setattr(admission, "authenticate_checkpoint_recovery_owner", authenticate)
    authenticated = []
    arguments = dict(root=tmp_path, authority=staged, request=item.request, issue_number=362,
                     run_id=800, client=SimpleNamespace(repository="trading-optimizer-lab-org/aurora"),
                     protected_commit="a" * 40, download_archive=lambda _: b"",
                     on_authenticated=authenticated.append)
    if reject_predecessor:
        with pytest.raises(ValueError, match="PREDECESSOR_AUTH_INVALID"):
            admission._reserve_new_fast_request(**arguments)
        assert authenticated == []
    else:
        actual_profile, actual_proof = admission._reserve_new_fast_request(**arguments)
        assert actual_profile is profile and actual_proof is proof
        assert len(authenticated) == 1
    assert calls == ["authenticate"]


def _bind_closed_gen9_request_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the existing signed-request builder represent the closed owner pin."""

    original = CatalogRunRequestV1.request_sha256
    assert isinstance(original, property)

    def request_sha256_getter(request: CatalogRunRequestV1) -> str:
        if request.launch_generation == 8:
            return CHECKPOINT_RECOVERY_SOURCE8_REQUEST_SHA256
        if request.request_id == GEN9_REQUEST_ID and request.launch_generation == 9:
            return CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256
        assert original.fget is not None
        return original.fget(request)

    monkeypatch.setattr(
        CatalogRunRequestV1,
        "request_sha256",
        property(request_sha256_getter),
    )


def _state_with(state: FastAuthorityStateV1, **updates: object) -> FastAuthorityStateV1:
    values = state.model_dump(mode="python", exclude={"state_sha256"})
    values.update(updates)
    return FastAuthorityStateV1._create(**values)


def _case(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    FastAuthorityStateV1,
    CatalogCloudEmissionV1,
    CheckpointRecoveryOwnerProofV1,
    CatalogLineageTransitionV1,
]:
    _bind_closed_gen9_request_hash(monkeypatch)

    source_state, gen9_item, source_proof, source_lineage = terminal_case()
    staged_gen9 = source_state.stage_checkpoint_emission(
        gen9_item,
        recovery_proof=source_proof,
        lineage_transition=source_lineage,
    )
    published_gen9 = staged_gen9.advance_emission(
        intent_id=gen9_item.intent_id,
        state="PUBLICACION_INCIERTA",
        post_run_id=700,
        post_run_attempt=1,
    ).advance_emission(
        intent_id=gen9_item.intent_id,
        state="PUBLICADO",
        issue_number=CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER,
    )
    reserved_gen9 = published_gen9.reserve_checkpoint_successor(
        request=gen9_item.request,
        issue_number=CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER,
        run_id=CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID,
        recovery_proof=source_proof,
        lineage_transition=source_lineage,
    )
    state = reserved_gen9.terminalize(
        request=gen9_item.request,
        run_id=CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID,
        terminal_receipt_sha256=CHECKPOINT_RECOVERY_CONTINUATION_TERMINAL_RECEIPT_SHA256,
    )
    current = state.campaigns[0]
    assert current.owner_issue_number == CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER
    assert current.owner_run_id == CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID
    assert current.request.request_sha256 == CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256
    assert current.terminal_receipt_sha256 == CHECKPOINT_RECOVERY_CONTINUATION_TERMINAL_RECEIPT_SHA256

    target_request = signed_request(
        campaign_key=CHECKPOINT_RECOVERY_CAMPAIGN_KEY,
        launch_generation=10,
        previous_terminal_request_sha256=current.request.request_sha256,
        request_id=GEN10_REQUEST_ID,
        campaign_definition_sha256=current.request.campaign_definition_sha256,
        prompt_sha256=current.request.prompt_sha256,
    )
    target_ticket = CatalogLaunchTicketV1.model_validate(
        {
            field: getattr(target_request, field)
            for field in CatalogLaunchTicketV1.model_fields
        }
    )
    assert target_ticket.launch_generation == 10
    assert target_ticket.previous_terminal_request_sha256 == current.request.request_sha256
    target_item = emission(
        request=target_request,
        intent_id=GEN10_INTENT_ID,
        intent_issue_number=CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER + 1,
    )
    proof = CheckpointRecoveryOwnerProofV1(
        profile_sha256=GEN10_PROFILE_SHA256,
        campaign_key=CHECKPOINT_RECOVERY_CAMPAIGN_KEY,
        target_generation=10,
        source_request_sha256=CHECKPOINT_RECOVERY_SOURCE8_REQUEST_SHA256,
        source_issue_number=CHECKPOINT_RECOVERY_SOURCE8_ISSUE_NUMBER,
        source_run_id=CHECKPOINT_RECOVERY_SOURCE8_RUN_ID,
        source_run_attempt=CHECKPOINT_RECOVERY_SOURCE8_RUN_ATTEMPT,
        source_protected_commit_sha=CHECKPOINT_RECOVERY_SOURCE8_PROTECTED_COMMIT_SHA,
        source_decision_sha256="b" * 64,
        source_finalizer_job_id=106686205733,
        evidence_kind="failed_owner_with_terminal",
    )
    binding = proof.predecessor_bindings
    assert binding is not None
    assert asdict(binding) == {
        "generation": CHECKPOINT_RECOVERY_CONTINUATION_PREDECESSOR_GENERATION,
        "request_sha256": CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256,
        "issue_number": CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER,
        "run_id": CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID,
        "run_attempt": CHECKPOINT_RECOVERY_CONTINUATION_RUN_ATTEMPT,
        "protected_commit_sha": CHECKPOINT_RECOVERY_CONTINUATION_PROTECTED_COMMIT_SHA,
        "terminal_receipt_sha256": CHECKPOINT_RECOVERY_CONTINUATION_TERMINAL_RECEIPT_SHA256,
        "decision_sha256": None,
    }
    lineage = CatalogLineageTransitionV1(
        campaign_key=target_request.campaign_key,
        previous_request_sha256=current.request.request_sha256,
        next_generation=10,
        target_definition_sha256=target_request.campaign_definition_sha256,
        target_prompt_sha256=target_request.prompt_sha256,
    )
    return state, target_item, proof, lineage


def test_generation10_stages_replays_and_reserves_without_erasing_source_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, item, proof, lineage = _case(monkeypatch)
    source_root = state.completed_intents[0]
    assert source_root.issue_number == CHECKPOINT_RECOVERY_SOURCE8_ISSUE_NUMBER
    assert source_root.request_sha256 == CHECKPOINT_RECOVERY_SOURCE8_REQUEST_SHA256
    assert source_root.terminal_receipt_sha256 == CHECKPOINT_RECOVERY_SOURCE8_TERMINAL_RECEIPT_SHA256

    staged = state.stage_checkpoint_emission(
        item,
        recovery_proof=proof,
        lineage_transition=lineage,
    )
    assert staged.campaigns == state.campaigns
    assert staged.recovery_superseded_intents == ()
    assert staged.completed_intents[0] == source_root
    assert len(staged.completed_intents) == 2
    predecessor_root = next(
        row for row in staged.completed_intents
        if row.issue_number == CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER
    )
    assert predecessor_root.request_sha256 == CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256
    assert predecessor_root.terminal_receipt_sha256 == CHECKPOINT_RECOVERY_CONTINUATION_TERMINAL_RECEIPT_SHA256
    assert staged.stage_checkpoint_emission(
        item,
        recovery_proof=proof,
        lineage_transition=lineage,
    ) == staged

    published = staged.advance_emission(
        intent_id=item.intent_id,
        state="PUBLICACION_INCIERTA",
        post_run_id=701,
        post_run_attempt=1,
    ).advance_emission(
        intent_id=item.intent_id,
        state="PUBLICADO",
        issue_number=CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER + 1,
    )
    reserved = published.reserve_checkpoint_successor(
        request=item.request,
        issue_number=CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER + 1,
        run_id=900,
        recovery_proof=proof,
        lineage_transition=lineage,
    )
    assert reserved.campaigns[0].generation == 10
    assert reserved.campaigns[0].owner_issue_number == CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER + 1
    assert reserved.campaigns[0].owner_run_id == 900
    assert reserved.completed_intents == staged.completed_intents
    assert reserved.reserve_checkpoint_successor(
        request=item.request,
        issue_number=CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER + 1,
        run_id=900,
        recovery_proof=proof,
        lineage_transition=lineage,
    ) == reserved


@pytest.mark.parametrize("defect", [
    "previous_source",
    "wrong_terminal",
    "wrong_owner_issue",
    "wrong_owner_run",
])
def test_generation10_rejects_wrong_immediate_predecessor(
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
) -> None:
    state, item, proof, lineage = _case(monkeypatch)
    if defect == "previous_source":
        request = signed_request(
            campaign_key=CHECKPOINT_RECOVERY_CAMPAIGN_KEY,
            launch_generation=10,
            previous_terminal_request_sha256=CHECKPOINT_RECOVERY_SOURCE8_REQUEST_SHA256,
            request_id=GEN10_REQUEST_ID,
            campaign_definition_sha256=item.request.campaign_definition_sha256,
            prompt_sha256=item.request.prompt_sha256,
        )
        item = emission(request=request, intent_id=GEN10_INTENT_ID, intent_issue_number=361)
    elif defect == "wrong_terminal":
        owner = state.campaigns[0].model_copy(update={"terminal_receipt_sha256": "e" * 64})
        state = _state_with(state, campaigns=(owner,))
    elif defect == "wrong_owner_issue":
        owner = state.campaigns[0].model_copy(update={"owner_issue_number": 359})
        state = _state_with(state, campaigns=(owner,))
    else:
        owner = state.campaigns[0].model_copy(update={"owner_run_id": 1})
        state = _state_with(state, campaigns=(owner,))

    with pytest.raises(ValueError):
        state.stage_checkpoint_emission(
            item,
            recovery_proof=proof,
            lineage_transition=lineage,
        )


def test_generation10_rejects_missing_source_root(monkeypatch: pytest.MonkeyPatch) -> None:
    state, item, proof, lineage = _case(monkeypatch)
    state = _state_with(state, completed_intents=())
    with pytest.raises(ValueError):
        state.stage_checkpoint_emission(item, recovery_proof=proof, lineage_transition=lineage)


def test_generation10_rejects_duplicate_source_root(monkeypatch: pytest.MonkeyPatch) -> None:
    state, _, _, _ = _case(monkeypatch)
    root = state.completed_intents[0]
    with pytest.raises(ValueError, match="CATALOG_CLOUD_EMISSIONS_INVALID"):
        _state_with(state, completed_intents=(root, root))


def test_generation10_rejects_wrong_source_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    state, item, proof, lineage = _case(monkeypatch)
    root = state.completed_intents[0].model_copy(update={"request_sha256": "d" * 64})
    state = _state_with(state, completed_intents=(root,))
    with pytest.raises(ValueError):
        state.stage_checkpoint_emission(item, recovery_proof=proof, lineage_transition=lineage)
