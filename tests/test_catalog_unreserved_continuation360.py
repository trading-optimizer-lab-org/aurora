"""Generation-10 unreserved recovery authenticates the closed generation-9 owner.

The transport is the existing read-only fixture, with its PREPARED
duplicate removed to model the original artifact topology.
"""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    CHECKPOINT_RECOVERY_CAMPAIGN_KEY,
    CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER,
    CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256,
    CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID,
    load_checkpoint_recovery_profile,
)
from aurora.infra.sp500_megarun.catalog_github_snapshot import CatalogGitHubReadOnlyClient
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1
from tests.test_catalog_cloud_authority import emission, signed_request
from tests.test_catalog_unreserved_terminal_checkpoint import _authenticated_intent
from tests.test_catalog_checkpoint_continuation_authority import _case as continuation_case
from tests.test_catalog_run_request import REQUESTER_TEST_PUBLIC_KEY
from tests.test_catalog_unreserved_checkpoint_recovery import (
    COMMIT,
    NOW,
    REPO,
    Transport,
)


ROOT = Path(__file__).resolve().parents[1]


def _original_topology(transport: Transport) -> None:
    """Remove only the duplicate PREPARED publication from the existing fixture."""

    steps = []
    for step in transport.jobs[1][0]["steps"]:
        if step["number"] == 18:
            continue
        copied = dict(step)
        if copied["number"] > 18:
            copied["number"] -= 1
        steps.append(copied)
    transport.jobs[1][0]["steps"] = steps
    transport.artifacts = [
        artifact
        for artifact in transport.artifacts
        if not artifact["name"].startswith("catalog-checkpoint-recovery-prepared-")
    ]


@pytest.fixture
def gen10_case(monkeypatch: pytest.MonkeyPatch):
    module = __import__(
        "aurora.infra.sp500_megarun.catalog_unreserved_checkpoint_recovery",
        fromlist=["authenticate_unreserved_checkpoint_recovery"],
    )
    authority, target, owner_proof, lineage = continuation_case(monkeypatch)

    # The failed gen-10 writer uses the existing bounded issue/run transport
    # fixture.  Its issue identity is independent from the closed owner 360.
    target = target.model_copy(update={"intent_issue_number": 342})
    staged = authority.stage_checkpoint_emission(
        target,
        recovery_proof=owner_proof,
        lineage_transition=lineage,
    )
    published = staged.advance_emission(
        intent_id=target.intent_id,
        state="PUBLICACION_INCIERTA",
        post_run_id=700,
        post_run_attempt=1,
    ).advance_emission(
        intent_id=target.intent_id,
        state="PUBLICADO",
        issue_number=342,
    )

    transport = Transport(published.emissions[0])
    _original_topology(transport)
    profile = load_checkpoint_recovery_profile(
        ROOT,
        CHECKPOINT_RECOVERY_CAMPAIGN_KEY,
        10,
    )
    assert profile is not None
    monkeypatch.setattr(
        module,
        "_load_controller_actors",
        lambda root: ((target.origin.requester_actor,), REQUESTER_TEST_PUBLIC_KEY),
    )
    client = CatalogGitHubReadOnlyClient(REPO, "test-only", transport=transport)
    return SimpleNamespace(module=module, authority=published, profile=profile,
                           client=client, transport=transport, failed=published.emissions[0],
                           owner_proof=replace(owner_proof, profile_sha256=profile.profile_sha256),
                           lineage=lineage)


def _authenticate(case, authority=None):
    return case.module.authenticate_unreserved_checkpoint_recovery(
        repo_root=ROOT, repository=REPO, protected_commit_sha=COMMIT,
        authority=case.authority if authority is None else authority,
        profile=case.profile, fetch_json=case.client,
        download_artifact=lambda artifact_id: case.transport.raw if artifact_id == 8000 else b"",
        now=NOW,
    )


def _state_with(case, **updates):
    values = case.authority.model_dump(exclude={"state_sha256"})
    values.update(updates)
    return FastAuthorityStateV1._create(**values)


def _replacement(case, proof):
    from aurora.infra.sp500_megarun.catalog_cloud_ticket import select_cloud_launch_ticket

    intent_id = "e844851d-11dd-4408-96c5-3dd7dd08ead1"
    ticket = select_cloud_launch_ticket(
        authority=case.authority, intent=_authenticated_intent(case.failed, intent_id),
        campaign_definition_sha256=case.failed.request.campaign_definition_sha256,
        prompt_sha256=case.failed.request.prompt_sha256, imported_ticket=None,
        lineage_transition=case.lineage, recovery_proof=case.owner_proof,
        unreserved_proof=proof, now=NOW,
        new_request_id=lambda: UUID("018f47a2-6e91-7c34-8000-000000000011"),
    )
    assert ticket.launch_generation == 10
    assert ticket.previous_terminal_request_sha256 == CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256
    request = signed_request(**{
        field: getattr(ticket, field) for field in (
            "campaign_key", "launch_generation", "previous_terminal_request_sha256",
            "campaign_definition_sha256", "prompt_sha256", "request_id",
        )
    })
    return emission(request=request, intent_id=intent_id, intent_issue_number=343,
                    producer_run_id=501, producer_commit="c" * 40)


def test_generation10_authenticates_original_transport_from_owner360(gen10_case):
    """A fresh GET-only proof must bind to owner 360, never physical source 353."""

    authority, profile, transport = gen10_case.authority, gen10_case.profile, gen10_case.transport
    before = authority.model_dump_json()

    proof = _authenticate(gen10_case)

    assert proof.target_generation == 10
    assert proof.source_owner_issue_number == CHECKPOINT_RECOVERY_CONTINUATION_ISSUE_NUMBER
    assert proof.source_owner_run_id == CHECKPOINT_RECOVERY_CONTINUATION_RUN_ID
    assert proof.source_request_sha256 == CHECKPOINT_RECOVERY_CONTINUATION_REQUEST_SHA256
    assert proof.source_request_sha256 != profile.source_request_sha256
    assert authority.model_dump_json() == before
    assert not any("/comments" in path for path in transport.calls)
    assert not any(
        artifact["name"].startswith("catalog-checkpoint-recovery-prepared-")
        for artifact in transport.artifacts
    )


def test_generation10_replacement_replay_and_reservation_preserve_both_roots(gen10_case):
    from aurora.infra.sp500_megarun.catalog_cloud_replay import resolve_cloud_replay

    case = gen10_case
    proof = _authenticate(case)
    replacement = _replacement(case, proof)
    arguments = dict(recovery_proof=case.owner_proof, unreserved_proof=proof,
                     lineage_transition=case.lineage, now=NOW)
    candidate = case.authority.replace_unreserved_checkpoint_emission(replacement, **arguments)
    assert candidate.campaigns == case.authority.campaigns
    assert candidate.completed_intents == case.authority.completed_intents
    assert {row.issue_number for row in candidate.completed_intents} == {353, 360}
    assert candidate.recovery_superseded_intents == case.authority.recovery_superseded_intents
    archive = candidate.unreserved_superseded_intents[0]
    assert archive.emission == case.failed
    assert archive.successor_request_sha256 == replacement.request.request_sha256
    assert archive.recovery_evidence_sha256 == case.owner_proof.evidence_sha256
    assert archive.proof.evidence_sha256 == proof.evidence_sha256
    assert candidate.replace_unreserved_checkpoint_emission(replacement, **arguments) == candidate
    published = candidate.advance_emission(
        intent_id=replacement.intent_id, state="PUBLICACION_INCIERTA",
        post_run_id=800, post_run_attempt=1,
    ).advance_emission(intent_id=replacement.intent_id, state="PUBLICADO", issue_number=343)
    assert resolve_cloud_replay(
        published, _authenticated_intent(replacement, replacement.intent_id)
    ) == published.emissions[0]
    reserved = published.reserve_checkpoint_successor(
        request=replacement.request, issue_number=343, run_id=900,
        recovery_proof=case.owner_proof, lineage_transition=case.lineage,
    )
    assert reserved.campaigns[0].generation == 10
    assert reserved.campaigns[0].owner_issue_number == 343
    assert reserved.campaigns[0].owner_run_id == 900
    assert reserved.completed_intents == candidate.completed_intents
    assert reserved.unreserved_superseded_intents == candidate.unreserved_superseded_intents
    with pytest.raises(ValueError):
        published.reserve(request=case.failed.request, issue_number=342, run_id=901)


def _authority_with_defect(case, defect):
    roots = case.authority.completed_intents
    owner = case.authority.campaigns[0]
    if defect.endswith("_missing"):
        issue = 353 if defect == "physical_missing" else 360
        authority = _state_with(case, completed_intents=tuple(row for row in roots if row.issue_number != issue))
    elif defect in {"physical_terminal", "predecessor_terminal"}:
        issue = 353 if defect == "physical_terminal" else 360
        authority = _state_with(case, completed_intents=tuple(
            row.model_copy(update={"terminal_receipt_sha256": "0" * 64}) if row.issue_number == issue else row
            for row in roots
        ))
    else:
        updates = {
            "owner_terminal": {"terminal_receipt_sha256": "0" * 64},
            "owner_issue": {"owner_issue_number": 359},
            "owner_run": {"owner_run_id": 35756495167},
            "owner_generation": {"request": owner.request.model_copy(update={"launch_generation": 8})},
            "legacy_closure": {"terminal_receipt_sha256": None, "legacy_closure_evidence_sha256": "f" * 64},
        }[defect]
        authority = _state_with(case, campaigns=(owner.model_copy(update=updates),))
    return authority


@pytest.mark.parametrize("defect", [
    "physical_missing", "physical_terminal", "predecessor_missing", "predecessor_terminal",
    "owner_terminal", "owner_issue", "owner_run", "owner_generation", "legacy_closure",
])
def test_generation10_unreserved_requires_both_exact_terminal_roots(gen10_case, defect):
    with pytest.raises(ValueError):
        _authenticate(gen10_case, authority=_authority_with_defect(gen10_case, defect))


@pytest.mark.parametrize("defect", ["expired", "authority", "predecessor", "profile", "reserved"])
def test_generation10_writer_rejects_stale_or_mismatched_unreserved_proof(gen10_case, defect):
    case = gen10_case
    proof = _authenticate(case)
    replacement = _replacement(case, proof)
    current = case.authority
    now = NOW
    if defect == "expired":
        now = proof.expires_at + timedelta(seconds=1)
    elif defect == "reserved":
        current = current.reserve_checkpoint_successor(
            request=case.failed.request, issue_number=342, run_id=901,
            recovery_proof=case.owner_proof, lineage_transition=case.lineage,
        )
    else:
        field = {"authority": "authority_state_sha256", "predecessor": "source_request_sha256",
                 "profile": "profile_sha256"}[defect]
        proof = proof.model_copy(update={field: "0" * 64})
    with pytest.raises(ValueError):
        current.replace_unreserved_checkpoint_emission(
            replacement, recovery_proof=case.owner_proof, unreserved_proof=proof,
            lineage_transition=case.lineage, now=now,
        )
