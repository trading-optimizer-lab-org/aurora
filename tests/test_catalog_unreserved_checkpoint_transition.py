"""Expired, published transport may be replaced without consuming generation 8."""
from datetime import datetime, timedelta, timezone

import pytest

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1
from tests.test_catalog_checkpoint_recovery_authority import _case
from tests.test_catalog_cloud_authority import emission, signed_request

NOW = datetime(2026, 9, 20, 17, tzinfo=timezone.utc)


def replacement_case():
    state, original, item, source_proof, lineage = _case()
    state = state.stage_checkpoint_emission(item, recovery_proof=source_proof, lineage_transition=lineage)
    state = state.advance_emission(intent_id=item.intent_id, state="PUBLICACION_INCIERTA",
                                   post_run_id=700, post_run_attempt=1)
    state = state.advance_emission(intent_id=item.intent_id, state="PUBLICADO", issue_number=342)
    prior = state.emissions[0]
    request = signed_request(campaign_key=item.request.campaign_key, launch_generation=8,
                             previous_terminal_request_sha256=original.request.request_sha256,
                             campaign_definition_sha256=item.request.campaign_definition_sha256,
                             request_id="018f47a2-6e91-7c34-8000-000000000009")
    new = emission(request=request, intent_issue_number=343,
                   intent_id="e844851d-11dd-4408-96c5-3dd7dd08eac2")
    return state, prior, new, source_proof, lineage


def proof_for(state, prior, source_proof):
    from aurora.infra.sp500_megarun.catalog_unreserved_checkpoint_recovery import UnreservedCheckpointRecoveryProofV1
    return UnreservedCheckpointRecoveryProofV1(
        repository="trading-optimizer-lab-org/aurora", authority_state_sha256=state.state_sha256,
        campaign_key=prior.request.campaign_key, target_generation=8,
        emission_sha256=canonical_sha256(prior.model_dump(mode="json")),
        failed_request_sha256=prior.request.request_sha256, failed_issue_number=342,
        failed_run_id=35521360637, failed_run_attempt=1, failed_protected_commit_sha="d" * 40,
        source_owner_issue_number=339, source_owner_run_id=source_proof.source_run_id,
        source_request_sha256=source_proof.source_request_sha256, profile_sha256=source_proof.profile_sha256,
        observed_at=NOW, expires_at=NOW + timedelta(minutes=5),
        request_expired_at=NOW - timedelta(minutes=1),
        runs_inventory_sha256="a" * 64, artifacts_inventory_sha256="b" * 64, attempts_sha256="c" * 64,
    )


def replace_emission(state, prior, new, source_proof, lineage, proof=None, now=NOW):
    method = getattr(state, "replace_unreserved_checkpoint_emission", None)
    assert method is not None, "Missing protected replacement of published unreserved generation 8"
    return method(new, recovery_proof=source_proof,
                  unreserved_proof=proof or proof_for(state, prior, source_proof),
                  lineage_transition=lineage, now=now)


def test_replacement_preserves_owner_source_archive_and_generation():
    state, prior, new, source, lineage = replacement_case()
    result = replace_emission(state, prior, new, source, lineage)
    assert result.revision == state.revision + 1
    assert result.previous_state_sha256 == state.state_sha256
    assert result.campaigns == state.campaigns
    assert result.campaigns[0].generation == 7
    assert result.recovery_superseded_intents == state.recovery_superseded_intents
    assert result.completed_intents == ()
    assert result.emissions == (new,)
    assert result.unreserved_superseded_intents[0].emission == prior
    assert result.unreserved_superseded_intents[0].successor_request_sha256 == new.request.request_sha256
    assert FastAuthorityStateV1.model_validate_json(result.model_dump_json()) == result


def test_archive_persists_full_authenticated_proof_for_future_audit():
    state, prior, new, source, lineage = replacement_case()
    proof = proof_for(state, prior, source)
    result = replace_emission(state, prior, new, source, lineage, proof=proof)
    archive = result.unreserved_superseded_intents[0]
    assert hasattr(archive, "proof"), "Archive must persist proof bytes, not only an unreconstructible digest"
    assert archive.proof == proof
    restored = FastAuthorityStateV1.model_validate_json(result.model_dump_json())
    assert restored.unreserved_superseded_intents[0].proof == proof
    assert restored.unreserved_superseded_intents[0].unreserved_evidence_sha256 == proof.evidence_sha256
    assert "unreserved_evidence_sha256" not in archive.model_dump(mode="json")


@pytest.mark.parametrize("field,value", [("emission_sha256", "0" * 64),
    ("authority_state_sha256", "0" * 64), ("failed_issue_number", 999), ("profile_sha256", "0" * 64)])
def test_archive_rejects_tampered_proof_even_if_state_hash_is_recomputed(field, value):
    from aurora.infra.sp500_megarun.catalog_fast_authority import UnreservedCheckpointSupersededIntentV1
    state, prior, new, source, lineage = replacement_case()
    result = replace_emission(state, prior, new, source, lineage)
    row = result.unreserved_superseded_intents[0]
    assert hasattr(row, "proof"), "Archive must preserve validated proof"
    payload = row.model_dump()
    payload["proof"] = row.proof.model_copy(update={field: value}).model_dump()
    with pytest.raises(ValueError):
        UnreservedCheckpointSupersededIntentV1.model_validate(payload)


def test_replacement_chain_reserves_only_new_published_request():
    state, prior, new, source, lineage = replacement_case()
    result = replace_emission(state, prior, new, source, lineage)
    for request in (prior.request, state.recovery_superseded_intents[0].emission.request):
        with pytest.raises(ValueError):
            result.reserve(request=request, issue_number=342, run_id=900)
        with pytest.raises(ValueError):
            result.reserve_checkpoint_successor(request=request, issue_number=342, run_id=900,
                                                recovery_proof=source, lineage_transition=lineage)
    published = result.advance_emission(intent_id=new.intent_id, state="PUBLICACION_INCIERTA",
                                       post_run_id=800, post_run_attempt=1).advance_emission(
                                           intent_id=new.intent_id, state="PUBLICADO", issue_number=344)
    reserved = published.reserve_checkpoint_successor(request=new.request, issue_number=344, run_id=900,
                                                       recovery_proof=source, lineage_transition=lineage)
    assert reserved.campaigns[0].generation == 8
    assert reserved.campaigns[0].owner_issue_number == 344
    assert reserved.unreserved_superseded_intents == result.unreserved_superseded_intents


def test_unreserved_replacement_is_idempotent_and_old_intent_is_read_only():
    state, prior, new, source, lineage = replacement_case()
    result = replace_emission(state, prior, new, source, lineage)
    proof = proof_for(state, prior, source)
    assert replace_emission(result, prior, new, source, lineage, proof=proof) == result
    from aurora.infra.sp500_megarun.catalog_cloud_replay import resolve_cloud_replay
    from scripts.validate_catalog_cloud_intent import _authority_contains_intent
    from tests.test_catalog_cloud_intake import _validate
    intent = _validate().model_copy(update=dict(intent_id=prior.intent_id,
        campaign_key=prior.request.campaign_key, issue_number=prior.intent_issue_number,
        repository_id=prior.repository_id, author_id=prior.actor_id, intent_sha256=prior.intent_sha256))
    assert resolve_cloud_replay(result, intent) == prior
    assert _authority_contains_intent(result, prior.intent_id)
    with pytest.raises(ValueError):
        result.stage_emission(prior)


@pytest.mark.parametrize("defect", ["authority", "emission", "expired", "future", "not_expired", "source", "profile"])
def test_replacement_rejects_wrong_or_stale_proof(defect):
    state, prior, new, source, lineage = replacement_case()
    assert hasattr(state, "replace_unreserved_checkpoint_emission"), "Missing protected replacement"
    proof = proof_for(state, prior, source)
    changes = {"authority": {"authority_state_sha256": "0" * 64},
               "emission": {"emission_sha256": "0" * 64},
               "expired": {"expires_at": NOW}, "future": {"observed_at": NOW + timedelta(seconds=1)},
               "not_expired": {"request_expired_at": NOW + timedelta(seconds=1)},
               "source": {"source_owner_run_id": 999}, "profile": {"profile_sha256": "0" * 64}}
    proof = proof.model_copy(update=changes[defect])
    with pytest.raises(ValueError):
        replace_emission(state, prior, new, source, lineage, proof=proof)


@pytest.mark.parametrize("proof_kind", ["valid", "missing", "expired"])
def test_ticket_replacement_requires_fresh_proof_and_preserves_generation(proof_kind):
    from uuid import UUID
    from aurora.infra.sp500_megarun.catalog_cloud_ticket import select_cloud_launch_ticket
    from tests.test_catalog_cloud_intake import _validate
    state, prior, new, source, lineage = replacement_case()
    intent = _validate().model_copy(update=dict(intent_id=new.intent_id, campaign_key=new.request.campaign_key,
        issue_number=new.intent_issue_number, repository_id=new.repository_id, author_id=new.actor_id,
        intent_sha256=new.intent_sha256))
    proof = proof_for(state, prior, source)
    kwargs = dict(authority=state, intent=intent, imported_ticket=None,
        campaign_definition_sha256=new.request.campaign_definition_sha256,
        prompt_sha256=new.request.prompt_sha256, lineage_transition=lineage,
        recovery_proof=source, unreserved_proof=None if proof_kind == "missing" else proof,
        now=NOW + timedelta(minutes=5) if proof_kind == "expired" else NOW,
        new_request_id=lambda: UUID(new.request.request_id))
    if proof_kind == "valid":
        ticket = select_cloud_launch_ticket(**kwargs)
        assert ticket.launch_generation == 8
        assert ticket.previous_terminal_request_sha256 == state.campaigns[0].request.request_sha256
        assert ticket.request_id != prior.request.request_id
    else:
        with pytest.raises(ValueError):
            select_cloud_launch_ticket(**kwargs)


@pytest.mark.parametrize("defect", [None, "proof", "phase", "candidate", "expired"])
def test_writer_rederives_replacement_before_any_write(monkeypatch, defect):
    from aurora.infra.sp500_megarun import catalog_fast_authority_github as writer
    state, prior, new, source, lineage = replacement_case()
    proof = proof_for(state, prior, source)
    candidate = replace_emission(state, prior, new, source, lineage, proof=proof)
    if defect == "candidate":
        candidate = candidate.model_copy(update={"completed_intents": ("forged",)})
    writes = []
    monkeypatch.setattr(writer, "_write_validated_authority", lambda **kwargs: writes.append(kwargs) or candidate)
    kwargs = dict(current=state, candidate=candidate, expected_edit_id="edit", anchor={},
        run_id=new.producer_run_id, run_attempt=1, job_id=900, phase="gate" if defect == "phase" else "intake-signed",
        commit=new.producer_commit, read_edit=lambda: {}, write_body=lambda _: None,
        lineage_transition=lineage, recovery_proof=source,
        unreserved_proof=None if defect == "proof" else proof,
        now=NOW + timedelta(minutes=5) if defect == "expired" else NOW)
    if defect is None:
        assert writer.write_current_fast_authority(**kwargs) == candidate
        assert len(writes) == 1
    else:
        with pytest.raises(ValueError):
            writer.write_current_fast_authority(**kwargs)
        assert writes == []


@pytest.mark.parametrize("concurrent_edit", [True, False])
def test_real_writer_checks_edition_before_patch_and_confirms_publication(concurrent_edit):
    from copy import deepcopy
    from aurora.infra.sp500_megarun import catalog_fast_authority_github as writer
    from aurora.infra.sp500_megarun.catalog_fast_authority import bind_authority_edit
    from tests.test_catalog_fast_authority_github import publication_transport

    state, prior, new, source, lineage = replacement_case()
    proof = proof_for(state, prior, source)
    candidate = replace_emission(state, prior, new, source, lineage, proof=proof)
    fixture = publication_transport(state=state, edit_id="E_current")
    edit = deepcopy(fixture.edit)
    issue = edit["data"]["repository"]["issue"]
    if concurrent_edit:
        issue["userContentEdits"]["nodes"][0]["id"] = "E_concurrent"
    writes = []

    def write_body(body):
        writes.append(body)
        issue["body"] = body
        issue["userContentEdits"]["nodes"][0]["id"] = "E_confirmed"
        issue["userContentEdits"]["nodes"][0]["editedAt"] = "2026-09-05T12:00:03Z"
        issue["lastEditedAt"] = "2026-09-05T12:00:03Z"

    kwargs = dict(current=state, candidate=candidate, expected_edit_id="E_current",
        anchor=fixture.anchor, run_id=new.producer_run_id, run_attempt=1, job_id=900,
        phase="intake-signed", commit=new.producer_commit, read_edit=lambda: edit,
        write_body=write_body, lineage_transition=lineage, recovery_proof=source,
        unreserved_proof=proof, now=NOW)
    if concurrent_edit:
        with pytest.raises(ValueError, match="^CATALOG_FAST_AUTHORITY_WRITE_CONFLICT$"):
            writer.write_current_fast_authority(**kwargs)
        assert writes == []
    else:
        result = writer.write_current_fast_authority(**kwargs)
        assert len(writes) == 1
        assert writes[0] == candidate.to_body() + (
            f"\n<!-- AURORA_FAST_PUBLICATION:{new.producer_run_id}:1:intake-signed:"
            f"{new.producer_commit}:900 -->")
        assert result == bind_authority_edit(
            state=candidate, issue_node_id="I_anchor", edit_node_id="E_confirmed")


def test_replaced_request_cannot_be_terminalized_or_staged_as_ordinary():
    state, prior, new, source, lineage = replacement_case()
    result = replace_emission(state, prior, new, source, lineage)
    with pytest.raises(ValueError):
        result.terminalize(request=prior.request, run_id=35521360637, terminal_receipt_sha256="f" * 64)
    with pytest.raises(ValueError):
        state.stage_emission(new, lineage_transition=lineage)
    with pytest.raises(ValueError):
        state.stage_checkpoint_emission(new, recovery_proof=source, lineage_transition=lineage)


@pytest.mark.parametrize("defect", ["lineage", "generation", "predecessor", "owner", "intent_issue", "proof_dict"])
def test_replacement_cannot_override_lineage_or_existing_owner(defect):
    state, prior, new, source, lineage = replacement_case()
    proof = proof_for(state, prior, source)
    if defect == "lineage":
        lineage = None
    elif defect in {"generation", "predecessor"}:
        request = new.request.model_copy(update={
            "launch_generation": 9} if defect == "generation" else {
                "previous_terminal_request_sha256": prior.request.request_sha256})
        new = new.model_copy(update={"request": request})
    elif defect == "owner":
        state = state.reserve_checkpoint_successor(request=prior.request, issue_number=342,
            run_id=35521360637, recovery_proof=source, lineage_transition=lineage)
    elif defect == "intent_issue":
        new = new.model_copy(update={"intent_issue_number": prior.intent_issue_number})
    else:
        proof = proof.model_dump()
    with pytest.raises(ValueError):
        replace_emission(state, prior, new, source, lineage, proof=proof)


def test_archived_replay_conflict_does_not_return_replacement():
    from aurora.infra.sp500_megarun.catalog_cloud_replay import resolve_cloud_replay
    from tests.test_catalog_cloud_intake import _validate
    state, prior, new, source, lineage = replacement_case()
    result = replace_emission(state, prior, new, source, lineage)
    intent = _validate().model_copy(update=dict(intent_id=prior.intent_id,
        campaign_key=prior.request.campaign_key, issue_number=prior.intent_issue_number,
        repository_id=prior.repository_id, author_id=999, intent_sha256=prior.intent_sha256))
    with pytest.raises(ValueError, match="CATALOG_CLOUD_INTENT_CONFLICT"):
        resolve_cloud_replay(result, intent)


def test_replacement_follows_multiple_failed_transport_links_without_rewriting_source():
    state, prior, new, source, lineage = replacement_case()
    first = replace_emission(state, prior, new, source, lineage)
    published = first.advance_emission(intent_id=new.intent_id, state="PUBLICACION_INCIERTA",
        post_run_id=800, post_run_attempt=1).advance_emission(intent_id=new.intent_id, state="PUBLICADO", issue_number=342)
    next_request = signed_request(campaign_key=new.request.campaign_key, launch_generation=8,
        previous_terminal_request_sha256=new.request.previous_terminal_request_sha256,
        campaign_definition_sha256=new.request.campaign_definition_sha256,
        request_id="018f47a2-6e91-7c34-8000-000000000010")
    next_item = emission(request=next_request, intent_issue_number=345,
        intent_id="e844851d-11dd-4408-96c5-3dd7dd08eac3")
    second = replace_emission(published, published.emissions[0], next_item, source, lineage)
    assert len(second.unreserved_superseded_intents) == 2
    assert second.recovery_superseded_intents == state.recovery_superseded_intents
    assert second._checkpoint_archive(next_request, source) == state.recovery_superseded_intents[0]


@pytest.mark.parametrize("auth_fails", [False, True])
def test_intake_authenticates_unreserved_before_signing(monkeypatch, tmp_path, auth_fails):
    from types import SimpleNamespace
    from scripts import catalog_cloud_intake as phases
    from aurora.infra.sp500_megarun import catalog_checkpoint_recovery_auth as source_auth
    from aurora.infra.sp500_megarun import catalog_unreserved_checkpoint_recovery as unreserved_auth
    state, prior, new, source, lineage = replacement_case()
    proof = proof_for(state, prior, source)
    class Clock:
        @staticmethod
        def now(tz):
            return NOW
    monkeypatch.setattr(phases, "datetime", Clock)
    monkeypatch.setenv("GH_TOKEN", "synthetic")
    monkeypatch.setattr(phases, "load_checkpoint_recovery_profile", lambda *args: object())
    monkeypatch.setattr(source_auth, "authenticate_checkpoint_recovery_owner", lambda **kwargs: SimpleNamespace(proof=source))
    calls = []
    def authenticate(**kwargs):
        assert kwargs["authority"] == state
        assert kwargs["now"] == NOW
        assert callable(kwargs["download_artifact"])
        calls.append("authenticate")
        if auth_fails:
            raise ValueError("CATALOG_UNRESERVED_CHECKPOINT_PROOF_INVALID")
        return proof
    monkeypatch.setattr(unreserved_auth, "authenticate_unreserved_checkpoint_recovery", authenticate)
    def sign(*args, **kwargs):
        assert calls == ["authenticate"]
        assert kwargs["unreserved_proof"] == proof and kwargs["recovery_proof"] == source
        calls.append("sign")
        return new
    monkeypatch.setattr(phases, "_new_emission", sign)
    monkeypatch.setattr(phases, "load_lineage_transition", lambda *args: lineage)
    def publish(**kwargs):
        candidate = kwargs["candidate"]
        assert candidate.campaigns == state.campaigns
        assert candidate.unreserved_superseded_intents[0].emission == prior
        calls.append("publish")
        return "synthetic-publication"
    monkeypatch.setattr(phases, "publish_cloud_candidate", publish)
    context = SimpleNamespace(status="NEW", replay=None, authority=state, latest_edit_id="edit",
                              intent=SimpleNamespace(campaign_key=new.request.campaign_key))
    kwargs = dict(root=tmp_path, work=tmp_path, phase="signed", context=context,
                  client=SimpleNamespace(repository="trading-optimizer-lab-org/aurora"),
                  run_id=new.producer_run_id, attempt=1, commit=new.producer_commit)
    if auth_fails:
        with pytest.raises(ValueError):
            phases.execute_phase(**kwargs)
        assert calls == ["authenticate"]
    else:
        assert phases.execute_phase(**kwargs)["changed"] == "true"
        assert calls == ["authenticate", "sign", "publish"]


@pytest.mark.parametrize("tampered", [False, True])
def test_cloud_writer_reauthenticates_and_preserves_proposal(monkeypatch, tmp_path, tampered):
    import json
    from types import SimpleNamespace
    from scripts import publish_catalog_cloud_authority as publisher
    from aurora.infra.sp500_megarun import catalog_unreserved_checkpoint_recovery as unreserved_auth
    from aurora.infra.sp500_megarun import catalog_fast_authority_github as writer
    from tests.test_catalog_run_request import REQUESTER_TEST_PUBLIC_KEY
    state, prior, new, source, lineage = replacement_case()
    initial = proof_for(state, prior, source)
    candidate = replace_emission(state, prior, new, source, lineage, proof=initial)
    if tampered:
        row = candidate.unreserved_superseded_intents[0].model_copy(update={"recovery_evidence_sha256": "f" * 64})
        candidate = FastAuthorityStateV1._create(**{**candidate.model_dump(exclude={"state_sha256"}),
                                                   "unreserved_superseded_intents": (row,)})
    fresh = initial.model_copy(update={"observed_at": NOW + timedelta(seconds=1),
                                       "expires_at": NOW + timedelta(minutes=5, seconds=1)})
    class Clock:
        @staticmethod
        def now(tz):
            return NOW + timedelta(seconds=2)
    monkeypatch.setattr(publisher, "datetime", Clock)
    config = tmp_path / "config"
    config.mkdir()
    (config / "catalog_authority_anchor_v1.json").write_text(json.dumps({"issue_number": 161}))
    (config / "catalog_controller_actors_v1.json").write_text(json.dumps({"requester_public_key_path": "key.pem"}))
    (tmp_path / "key.pem").write_bytes(REQUESTER_TEST_PUBLIC_KEY)
    for key, value in dict(GITHUB_ACTIONS="true", GITHUB_JOB="intake", GITHUB_REF="refs/heads/main",
            RUNNER_TEMP=str(tmp_path), GITHUB_RUN_ID=str(new.producer_run_id), GITHUB_RUN_ATTEMPT="1",
            GITHUB_SHA=new.producer_commit, CATALOG_PROTECTED_COMMIT_SHA=new.producer_commit, GH_TOKEN="synthetic").items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(publisher, "_publisher_job", lambda *args: 900)
    monkeypatch.setattr(publisher, "load_lineage_transition", lambda *args: lineage)
    monkeypatch.setattr(publisher, "load_checkpoint_recovery_profile", lambda *args: object())
    monkeypatch.setattr(publisher, "authenticate_checkpoint_recovery_owner", lambda **kwargs: SimpleNamespace(proof=source))
    monkeypatch.setattr(unreserved_auth, "authenticate_unreserved_checkpoint_recovery", lambda **kwargs: fresh)
    writes = []
    def record(**kwargs):
        writes.append(kwargs["candidate"])
        return SimpleNamespace(model_dump_json=lambda: "{}")
    monkeypatch.setattr(writer, "_write_validated_authority", record)
    kwargs = dict(root=tmp_path, current=state, candidate=candidate, expected_edit_id="edit",
        client=SimpleNamespace(repository="trading-optimizer-lab-org/aurora"), phase="intake-signed",
        output=tmp_path / "catalog-fast-authority-publication-v1.json")
    if tampered:
        with pytest.raises(ValueError):
            publisher.publish_cloud_candidate(**kwargs)
        assert writes == []
    else:
        publisher.publish_cloud_candidate(**kwargs)
        assert len(writes) == 1
        assert writes[0].unreserved_superseded_intents[0].unreserved_evidence_sha256 == fresh.evidence_sha256
        assert writes[0].emissions == (new,)
