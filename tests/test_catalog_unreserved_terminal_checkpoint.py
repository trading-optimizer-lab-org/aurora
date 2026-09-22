"""Generation-9 unreserved transport stays below terminal authority."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import UUID

import pytest

from aurora.infra.sp500_megarun.catalog_cloud_emission import CatalogCloudEmissionV1
from aurora.infra.sp500_megarun.catalog_cloud_intake import CloudIntentV1
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import (
    CheckpointRecoveryOwnerProofV1,
)
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1
from aurora.infra.sp500_megarun.catalog_github_snapshot import (
    CatalogGitHubReadOnlyClient,
)
from aurora.infra.sp500_megarun.catalog_lineage_transition import (
    CatalogLineageTransitionV1,
)
from tests.test_catalog_checkpoint_terminal_authority import _case as terminal_case
from tests.test_catalog_cloud_authority import emission, signed_request
from tests.test_catalog_run_request import REQUESTER_TEST_PUBLIC_KEY
from tests.test_catalog_unreserved_checkpoint_recovery import (
    COMMIT,
    NOW,
    REPO,
    Transport,
)


ROOT = Path(__file__).resolve().parents[1]
GEN9_PROFILE_SHA256 = "d" * 64
GEN9_REPLACEMENT_INTENT_ID = "e844851d-11dd-4408-96c5-3dd7dd08eac4"
GEN9_REPLACEMENT_REQUEST_ID = "018f47a2-6e91-7c34-8000-000000000010"


@dataclass(frozen=True)
class Gen9Case:
    module: ModuleType
    authority: FastAuthorityStateV1
    failed: CatalogCloudEmissionV1
    owner_proof: CheckpointRecoveryOwnerProofV1
    lineage: CatalogLineageTransitionV1
    profile: SimpleNamespace
    transport: Transport
    client: CatalogGitHubReadOnlyClient


def _gen9_profile(authority: FastAuthorityStateV1, owner_proof: CheckpointRecoveryOwnerProofV1) -> SimpleNamespace:
    owner = authority.campaigns[0]
    return SimpleNamespace(
        profile_sha256=GEN9_PROFILE_SHA256,
        campaign_key=owner.request.campaign_key,
        source_generation=8,
        target_generation=9,
        source_issue_number=owner.owner_issue_number,
        source_run_id=owner.owner_run_id,
        source_run_attempt=owner_proof.source_run_attempt,
        source_request_sha256=owner.request.request_sha256,
        source_protected_commit_sha=owner_proof.source_protected_commit_sha,
        source_terminal_receipt_sha256=owner.terminal_receipt_sha256,
        source_plan_bindings={
            "request_sha256": owner.request.request_sha256,
            "decision_sha256": owner_proof.source_decision_sha256,
            "protected_commit_sha": owner_proof.source_protected_commit_sha,
        },
        expected_total_count=37258,
    )


@pytest.fixture
def gen9_case(monkeypatch: pytest.MonkeyPatch) -> Gen9Case:
    module = __import__(
        "aurora.infra.sp500_megarun.catalog_unreserved_checkpoint_recovery",
        fromlist=["authenticate_unreserved_checkpoint_recovery"],
    )
    state, item, owner_proof, lineage = terminal_case()
    # Keep the existing Transport's bounded issue/run fixture (issue 342),
    # while preserving the exact terminal-authority source from issue 353.
    failed = item.model_copy(update={"intent_issue_number": 342})
    staged = state.stage_checkpoint_emission(
        failed, recovery_proof=owner_proof, lineage_transition=lineage,
    )
    authority = staged.advance_emission(
        intent_id=failed.intent_id,
        state="PUBLICACION_INCIERTA",
        post_run_id=700,
        post_run_attempt=1,
    ).advance_emission(intent_id=failed.intent_id, state="PUBLICADO", issue_number=342)
    transport = Transport(authority.emissions[0])
    profile = _gen9_profile(authority, owner_proof)
    monkeypatch.setattr(module, "validate_exact_checkpoint_profile", lambda root, value: value)
    monkeypatch.setattr(
        module,
        "_load_controller_actors",
        lambda root: ((failed.origin.requester_actor,), REQUESTER_TEST_PUBLIC_KEY),
    )
    client = CatalogGitHubReadOnlyClient(REPO, "test-only", transport=transport)
    return Gen9Case(
        module=module,
        authority=authority,
        failed=failed,
        owner_proof=owner_proof,
        lineage=lineage,
        profile=profile,
        transport=transport,
        client=client,
    )


def _authenticate(
    case: Gen9Case,
    *,
    authority: FastAuthorityStateV1 | None = None,
    profile: SimpleNamespace | None = None,
):
    return case.module.authenticate_unreserved_checkpoint_recovery(
        repo_root=ROOT,
        repository=REPO,
        protected_commit_sha=COMMIT,
        authority=case.authority if authority is None else authority,
        profile=case.profile if profile is None else profile,
        fetch_json=case.client,
        download_artifact=lambda artifact_id: (
            case.transport.raw if artifact_id == 8000 else b""
        ),
        now=NOW,
    )


def _authenticated_intent(emission: CatalogCloudEmissionV1, intent_id: str):
    from tests.test_catalog_cloud_intake import _validate

    intent_sha256 = CloudIntentV1(
        schema_version="1",
        campaign_key=emission.request.campaign_key,
        intent_id=intent_id,
    ).intent_sha256
    return _validate().model_copy(
        update={
            "intent_id": intent_id,
            "campaign_key": emission.request.campaign_key,
            "issue_number": emission.intent_issue_number,
            "repository_id": emission.repository_id,
            "author_id": emission.actor_id,
            "intent_sha256": intent_sha256,
        }
    )


def _replacement_ticket(case: Gen9Case, unreserved_proof):
    from aurora.infra.sp500_megarun.catalog_cloud_ticket import select_cloud_launch_ticket

    intent = _authenticated_intent(case.failed, "e844851d-11dd-4408-96c5-3dd7dd08eac5")
    return select_cloud_launch_ticket(
        authority=case.authority,
        intent=intent,
        campaign_definition_sha256=case.failed.request.campaign_definition_sha256,
        prompt_sha256=case.failed.request.prompt_sha256,
        imported_ticket=None,
        lineage_transition=case.lineage,
        recovery_proof=case.owner_proof,
        unreserved_proof=unreserved_proof,
        now=NOW,
        new_request_id=lambda: UUID(GEN9_REPLACEMENT_REQUEST_ID),
    )


def _replacement(case: Gen9Case, unreserved_proof):
    ticket = _replacement_ticket(case, unreserved_proof)
    signed_replacement = signed_request(
        campaign_key=ticket.campaign_key,
        launch_generation=ticket.launch_generation,
        previous_terminal_request_sha256=ticket.previous_terminal_request_sha256,
        campaign_definition_sha256=ticket.campaign_definition_sha256,
        prompt_sha256=ticket.prompt_sha256,
        request_id=ticket.request_id,
    )
    return emission(
        request=signed_replacement,
        intent_id=GEN9_REPLACEMENT_INTENT_ID,
        intent_issue_number=343,
        producer_run_id=501,
        producer_commit="c" * 40,
    )


@pytest.mark.parametrize('original_prepared', [False, True])
def test_gen9_expired_failed_writer_is_get_only_and_roots_in_completed_intents(gen9_case: Gen9Case, original_prepared):
    if original_prepared:
        steps = gen9_case.transport.jobs[1][0]['steps']
        for step in list(steps):
            if step['number'] == 18:
                steps.remove(step)
            elif step['number'] > 18:
                step['number'] -= 1
        gen9_case.transport.artifacts = [row for row in gen9_case.transport.artifacts
                                       if not row['name'].startswith('catalog-checkpoint-recovery-prepared-')]
    before = gen9_case.authority.model_dump_json()

    proof = _authenticate(gen9_case)

    owner = gen9_case.authority.campaigns[0]
    root = gen9_case.authority.completed_intents[0]
    assert proof.target_generation == 9
    assert proof.source_owner_issue_number == 353
    assert proof.source_owner_run_id == owner.owner_run_id
    assert owner.generation == 8 and owner.is_terminal
    assert root.request_id == owner.request.request_id
    assert root.request_sha256 == owner.request.request_sha256
    assert root.campaign_key == owner.request.campaign_key
    assert root.issue_number == owner.owner_issue_number == 353
    assert root.terminal_receipt_sha256 == owner.terminal_receipt_sha256
    assert gen9_case.authority.recovery_superseded_intents == ()
    assert gen9_case.authority.model_dump_json() == before
    assert not any("/comments" in path for path in gen9_case.transport.calls)


def test_gen9_fresh_proof_ticket_replace_replay_publish_reserves_only_new(gen9_case: Gen9Case):
    from aurora.infra.sp500_megarun.catalog_cloud_replay import resolve_cloud_replay

    unreserved_proof = _authenticate(gen9_case)
    ticket = _replacement_ticket(gen9_case, unreserved_proof)
    assert ticket.launch_generation == 9
    assert ticket.previous_terminal_request_sha256 == gen9_case.authority.campaigns[0].request.request_sha256

    replacement = _replacement(gen9_case, unreserved_proof)
    candidate = gen9_case.authority.replace_unreserved_checkpoint_emission(
        replacement,
        recovery_proof=gen9_case.owner_proof,
        unreserved_proof=unreserved_proof,
        lineage_transition=gen9_case.lineage,
        now=NOW,
    )
    archive = candidate.unreserved_superseded_intents[0]
    assert candidate.campaigns == gen9_case.authority.campaigns
    assert candidate.completed_intents == gen9_case.authority.completed_intents
    assert candidate.recovery_superseded_intents == ()
    assert archive.emission == gen9_case.authority.emissions[0]
    assert archive.successor_request_sha256 == replacement.request.request_sha256
    assert archive.recovery_evidence_sha256 == gen9_case.owner_proof.evidence_sha256
    assert archive.proof.evidence_sha256 == unreserved_proof.evidence_sha256

    assert candidate.replace_unreserved_checkpoint_emission(
        replacement,
        recovery_proof=gen9_case.owner_proof,
        unreserved_proof=unreserved_proof,
        lineage_transition=gen9_case.lineage,
        now=NOW,
    ) == candidate
    published = candidate.advance_emission(
        intent_id=replacement.intent_id,
        state="PUBLICACION_INCIERTA",
        post_run_id=800,
        post_run_attempt=1,
    ).advance_emission(intent_id=replacement.intent_id, state="PUBLICADO", issue_number=343)
    replay_intent = _authenticated_intent(replacement, replacement.intent_id)
    assert resolve_cloud_replay(published, replay_intent) == published.emissions[0]
    assert published.emissions[0].request == replacement.request

    reserved = published.reserve_checkpoint_successor(
        request=replacement.request,
        issue_number=343,
        run_id=900,
        recovery_proof=gen9_case.owner_proof,
        lineage_transition=gen9_case.lineage,
    )
    assert reserved.campaigns[0].generation == 9
    assert reserved.campaigns[0].owner_issue_number == 343
    assert reserved.campaigns[0].owner_run_id == 900
    assert reserved.completed_intents == candidate.completed_intents
    assert reserved.unreserved_superseded_intents == candidate.unreserved_superseded_intents
    with pytest.raises(ValueError):
        published.reserve(request=gen9_case.failed.request, issue_number=342, run_id=901)


def _authority_with(gen9_case: Gen9Case, **updates) -> FastAuthorityStateV1:
    values = gen9_case.authority.model_dump(exclude={"state_sha256"})
    values.update(updates)
    return FastAuthorityStateV1._create(**values)


@pytest.mark.parametrize("defect", ["missing_root", "wrong_terminal", "legacy_closure", "no_source_terminal"])
def test_gen9_auth_rejects_missing_or_nonexact_terminal_root(gen9_case: Gen9Case, defect: str):
    owner = gen9_case.authority.campaigns[0]
    if defect == "missing_root":
        authority = _authority_with(gen9_case, completed_intents=())
    elif defect == "wrong_terminal":
        authority = _authority_with(
            gen9_case,
            campaigns=(owner.model_copy(update={"terminal_receipt_sha256": "e" * 64}),),
        )
    elif defect == "legacy_closure":
        authority = _authority_with(
            gen9_case,
            campaigns=(owner.model_copy(update={
                "terminal_receipt_sha256": None,
                "legacy_closure_evidence_sha256": "f" * 64,
            }),),
        )
    else:
        authority = _authority_with(
            gen9_case,
            campaigns=(owner.model_copy(update={
                "terminal_receipt_sha256": None,
                "legacy_closure_evidence_sha256": None,
            }),),
        )
    with pytest.raises(ValueError):
        _authenticate(gen9_case, authority=authority)


def test_gen9_authority_rejects_duplicate_completed_root(gen9_case: Gen9Case):
    root = gen9_case.authority.completed_intents[0]
    with pytest.raises(ValueError):
        _authority_with(gen9_case, completed_intents=(root, root))


@pytest.mark.parametrize("defect", ["profile", "predecessor", "link_hash", "replay"])
def test_gen9_writer_rejects_wrong_proof_predecessor_chain_or_replay(
    gen9_case: Gen9Case, defect: str,
):
    unreserved_proof = _authenticate(gen9_case)
    replacement = _replacement(gen9_case, unreserved_proof)
    if defect == "profile":
        with pytest.raises(ValueError):
            _replacement_ticket(
                gen9_case,
                unreserved_proof.model_copy(update={"profile_sha256": "0" * 64}),
            )
        return
    if defect == "predecessor":
        from dataclasses import replace

        with pytest.raises(ValueError):
            gen9_case.authority.replace_unreserved_checkpoint_emission(
                replacement,
                recovery_proof=replace(gen9_case.owner_proof, source_request_sha256="0" * 64),
                unreserved_proof=unreserved_proof,
                lineage_transition=gen9_case.lineage,
                now=NOW,
            )
        return
    candidate = gen9_case.authority.replace_unreserved_checkpoint_emission(
        replacement,
        recovery_proof=gen9_case.owner_proof,
        unreserved_proof=unreserved_proof,
        lineage_transition=gen9_case.lineage,
        now=NOW,
    )
    if defect == "link_hash":
        row = candidate.unreserved_superseded_intents[0].model_copy(
            update={"recovery_evidence_sha256": "0" * 64},
        )
        tampered = _authority_with(
            gen9_case,
            campaigns=candidate.campaigns,
            emissions=candidate.emissions,
            completed_intents=candidate.completed_intents,
            recovery_superseded_intents=candidate.recovery_superseded_intents,
            unreserved_superseded_intents=(row,),
        )
        with pytest.raises(ValueError):
            tampered.replace_unreserved_checkpoint_emission(
                replacement,
                recovery_proof=gen9_case.owner_proof,
                unreserved_proof=unreserved_proof,
                lineage_transition=gen9_case.lineage,
                now=NOW,
            )
        return
    with pytest.raises(ValueError):
        candidate.replace_unreserved_checkpoint_emission(
            replacement,
            recovery_proof=gen9_case.owner_proof,
            unreserved_proof=unreserved_proof.model_copy(
                update={"authority_state_sha256": "0" * 64},
            ),
            lineage_transition=gen9_case.lineage,
            now=NOW,
        )


def test_gen9_writer_adapter_rederives_unreserved_candidate_before_write(
    gen9_case: Gen9Case, monkeypatch: pytest.MonkeyPatch,
):
    from aurora.infra.sp500_megarun import catalog_fast_authority_github as writer

    unreserved_proof = _authenticate(gen9_case)
    replacement = _replacement(gen9_case, unreserved_proof)
    candidate = gen9_case.authority.replace_unreserved_checkpoint_emission(
        replacement,
        recovery_proof=gen9_case.owner_proof,
        unreserved_proof=unreserved_proof,
        lineage_transition=gen9_case.lineage,
        now=NOW,
    )
    writes: list[FastAuthorityStateV1] = []

    def record_write(**kwargs: object) -> FastAuthorityStateV1:
        writes.append(candidate)
        return candidate

    monkeypatch.setattr(
        writer,
        "_write_validated_authority",
        record_write,
    )
    result = writer.write_current_fast_authority(
        current=gen9_case.authority,
        candidate=candidate,
        expected_edit_id="edit",
        anchor={},
        run_id=replacement.producer_run_id,
        run_attempt=1,
        job_id=900,
        phase="intake-signed",
        commit=replacement.producer_commit,
        read_edit=lambda: {},
        write_body=lambda body: None,
        lineage_transition=gen9_case.lineage,
        recovery_proof=gen9_case.owner_proof,
        unreserved_proof=unreserved_proof,
        now=NOW,
    )
    assert result == candidate
    assert writes == [candidate]
