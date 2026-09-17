"""Cloud emission is a transaction of the existing authority, not a second ledger."""

import json
from functools import lru_cache

import pytest

from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1
from aurora.infra.sp500_megarun.catalog_cloud_emission import CatalogCloudEmissionV1
from aurora.infra.sp500_megarun.catalog_cloud_intake import CloudIntentV1
from aurora.infra.sp500_megarun.catalog_request_contract import CatalogLaunchTicketV1, CatalogRunRequestV1
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request
from tests.test_catalog_fast_path import _request
from tests.test_catalog_run_request import sign_request_fixture, REQUESTER_TEST_PRIVATE_KEY, REQUESTER_TEST_PUBLIC_KEY


@lru_cache
def signed_request(**updates):
    # Cache fixture bytes so repeated fixture reads do not generate a new RSA salt.
    draft = _request(**updates).intent.model_dump(mode="json")
    ticket = CatalogLaunchTicketV1.model_validate({
        field: draft[field] for field in CatalogLaunchTicketV1.model_fields
    })
    draft["launch_ticket_sha256"] = ticket.launch_ticket_sha256
    return CatalogRunRequestV1.model_validate(sign_request_fixture(payload=draft, private_key=REQUESTER_TEST_PRIVATE_KEY))


def emission(**updates):
    values = dict(
        intent_id="e844851d-11dd-4408-96c5-3dd7dd08eac0",
        intent_issue_number=400,
        repository_id=1232647748,
        actor_id=271768688,
        intent_sha256="a" * 64,
        request=signed_request(),
        producer_run_id=500,
        producer_commit="b" * 40,
        state="SIGNED",
    )
    values.update(updates)
    if "origin" not in updates:
        values["origin"] = dict(
            app_id=4693452, installation_id=155982969,
            requester_actor="aurora-catalog-request-f10c7b40e1[bot]",
            requester_public_key_sha256=values["request"].requester_public_key_sha256,
            environment="catalog-cloud-intake",
            permissions=(("issues", "write"), ("metadata", "read")),
            retirement_receipt_sha256="f" * 64,
            launch_ticket_sha256=values["request"].launch_ticket_sha256,
        )
    if "intent_sha256" not in updates:
        values["intent_sha256"] = CloudIntentV1(
            intent_id=values["intent_id"], campaign_key=values["request"].campaign_key,
        ).intent_sha256
    return CatalogCloudEmissionV1(**values)


def test_legacy_authority_retains_exact_wire_shape_and_hash():
    state = FastAuthorityStateV1.bootstrap(campaigns=())
    raw = state.model_dump_json()
    assert "emissions" not in json.loads(raw)
    assert FastAuthorityStateV1.model_validate_json(raw).to_body() == state.to_body()


def test_staging_preserves_scientific_owner_and_reopens_signed_bytes():
    current = FastAuthorityStateV1.bootstrap(campaigns=())
    staged = current.stage_emission(emission())
    reopened = FastAuthorityStateV1.model_validate_json(staged.model_dump_json())
    assert reopened.campaigns == ()
    assert reopened.emissions[0].body == emission().body
    assert reopened.emissions[0].request.request_sha256 == emission().request.request_sha256
    assert parse_catalog_run_request(reopened.emissions[0].title, reopened.emissions[0].body,
                                     REQUESTER_TEST_PUBLIC_KEY) == emission().request
    assert reopened.previous_state_sha256 == current.state_sha256
    assert reopened.stage_emission(emission()) == reopened


def test_same_intent_different_content_is_conflict():
    state = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(emission())
    with pytest.raises(ValueError, match="CLOUD_INTENT_CONFLICT"):
        state.stage_emission(emission(intent_sha256="c" * 64))


def test_campaign_pending_emission_does_not_consume_another_generation():
    state = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(emission())
    with pytest.raises(ValueError, match="CAMPAIGN_BUSY"):
        state.stage_emission(emission(intent_id="976e8478-4784-4c79-b882-47d5dfbe9b7c"))


def test_uncertainty_precedes_published_and_cannot_be_reversed():
    item = emission()
    state = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(item)
    with pytest.raises(ValueError, match="EMISSION_TRANSITION"):
        state.advance_emission(intent_id=item.intent_id, state="PUBLICADO", issue_number=401)
    uncertain = state.advance_emission(intent_id=item.intent_id, state="PUBLICACION_INCIERTA",
                                       post_run_id=500, post_run_attempt=1)
    assert uncertain.emissions[0].request == item.request
    published = uncertain.advance_emission(intent_id=item.intent_id, state="PUBLICADO", issue_number=401)
    assert published.emissions[0].issue_number == 401
    assert published.advance_emission(intent_id=item.intent_id, state="PUBLICADO", issue_number=401) == published
    with pytest.raises(ValueError, match="EMISSION_TRANSITION"):
        published.advance_emission(intent_id=item.intent_id, state="SIGNED")


def test_terminal_allows_successor_without_overwriting_historical_request():
    first = emission()
    state = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(first)
    state = state.advance_emission(intent_id=first.intent_id, state="PUBLICACION_INCIERTA",
                                   post_run_id=500, post_run_attempt=1)
    state = state.advance_emission(intent_id=first.intent_id, state="PUBLICADO", issue_number=401)
    state = state.reserve(request=first.request, issue_number=401, run_id=501)
    assert state.emissions[0].request == first.request
    assert state.emissions[0].state == "PUBLICADO"
    state = state.terminalize(request=first.request, run_id=501, terminal_receipt_sha256="d" * 64)
    successor = emission(
        intent_id="976e8478-4784-4c79-b882-47d5dfbe9b7c",
        intent_issue_number=402,
        request=signed_request(request_id="018f47a2-6e91-7c34-8000-000000000002", launch_generation=2,
                         previous_terminal_request_sha256=first.request.request_sha256),
    )
    staged = state.stage_emission(successor)
    assert staged.campaigns == state.campaigns
    assert staged.campaigns[0].request == first.request
    assert staged.emissions == (successor,)
    assert staged.completed_intents[0].intent_id == first.intent_id
    assert staged.completed_intents[0].request_sha256 == first.request.request_sha256
    with pytest.raises(ValueError, match="INTENT_ALREADY_COMPLETED"):
        staged.stage_emission(first)


def test_staged_emission_does_not_allow_uncoordinated_same_generation_request():
    state = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(emission())
    with pytest.raises(ValueError, match="EMISSION_REQUEST_MISMATCH"):
        state.reserve(request=signed_request(request_id="018f47a2-6e91-7c34-8000-000000000002"),
                      issue_number=401, run_id=501)


def test_post_attempt_identity_cannot_move_to_a_rerun():
    first = emission()
    state = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(first)
    uncertain = state.advance_emission(intent_id=first.intent_id, state="PUBLICACION_INCIERTA",
                                       post_run_id=500, post_run_attempt=1)
    with pytest.raises(ValueError, match="EMISSION_TRANSITION"):
        uncertain.advance_emission(intent_id=first.intent_id, state="PUBLICADO", issue_number=401,
                                   post_run_id=500, post_run_attempt=2)


@pytest.mark.parametrize("defect", [None, "actor", "triggering_actor", "repository", "branch", "path", "event", "write_step", "digest"])
def test_cloud_publication_uses_real_provenance_reader(defect):
    from aurora.infra.sp500_megarun.catalog_fast_authority_github import load_current_fast_authority
    from tests.test_catalog_fast_authority_github import publication_transport

    item = emission(producer_run_id=123, producer_commit="a" * 40)
    state = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(item)
    fixture = publication_transport(state=state, phase="intake-signed")
    fixture.run.update(path=".github/workflows/catalog-cloud-intake.yml", event="issues",
                       actor={"id": 271768688}, triggering_actor={"id": 271768688})
    fixture.run["repository"]["id"] = 1232647748
    fixture.artifact["workflow_run"].update(repository_id=1232647748, head_repository_id=1232647748)
    fixture.job["name"] = "intake"
    for step in fixture.job["steps"]:
        step["name"] += " (intake-signed)"
    if defect in {"actor", "triggering_actor"}:
        fixture.run[defect] = {"id": 999}
    elif defect == "repository":
        fixture.run["repository"]["id"] = 999
    elif defect == "branch":
        fixture.run["head_branch"] = "untrusted"
    elif defect == "path":
        fixture.run["path"] = ".github/workflows/other.yml"
    elif defect == "event":
        fixture.run["event"] = "pull_request"
    elif defect == "write_step":
        fixture.job["steps"][0]["conclusion"] = "failure"
    elif defect == "digest":
        fixture.artifact["digest"] = "sha256:" + "0" * 64
    def load():
        return load_current_fast_authority(client=fixture.client, anchor=fixture.anchor,
            protected_commit="a" * 40, read_edit=lambda: fixture.edit, download_archive=lambda _: fixture.raw)
    if defect is None:
        assert load() == state
    else:
        with pytest.raises(ValueError, match="CATALOG_FAST_AUTHORITY_"):
            load()


@pytest.mark.parametrize("phase", ["intake-signed", "intake-uncertain", "intake-published"])
@pytest.mark.parametrize("lost_response", [False, True])
def test_cloud_writer_preserves_science_and_binds_one_edit(phase, lost_response):
    from aurora.infra.sp500_megarun.catalog_fast_authority import verify_authority_edit
    from aurora.infra.sp500_megarun.catalog_fast_authority_github import write_current_fast_authority
    from tests.test_catalog_fast_authority_github import publication_transport

    item = emission(producer_run_id=123, producer_commit="a" * 40)
    empty = FastAuthorityStateV1.bootstrap(campaigns=())
    signed = empty.stage_emission(item)
    uncertain = signed.advance_emission(intent_id=item.intent_id, state="PUBLICACION_INCIERTA",
                                         post_run_id=123, post_run_attempt=1)
    published = uncertain.advance_emission(intent_id=item.intent_id, state="PUBLICADO", issue_number=401)
    current, candidate = {
        "intake-signed": (empty, signed),
        "intake-uncertain": (signed, uncertain),
        "intake-published": (uncertain, published),
    }[phase]
    fixture = publication_transport(state=current)
    issue = fixture.edit["data"]["repository"]["issue"]
    writes = []
    def patch(body):
        writes.append(body)
        issue["body"] = body
        issue["userContentEdits"]["nodes"][0]["id"] = "E_written"
        if lost_response:
            raise TimeoutError("response lost after commit")
    publication = write_current_fast_authority(
        current=current, candidate=candidate, expected_edit_id="E_current", anchor=fixture.anchor,
        run_id=123, run_attempt=1, job_id=789, phase=phase, commit="a" * 40,
        read_edit=lambda: fixture.edit, write_body=patch,
    )
    reopened = verify_authority_edit(
        body=candidate.to_body(), publication_json=publication.model_dump_json(),
        issue_node_id="I_anchor", latest_edit_node_id="E_written",
    )
    assert reopened == candidate and len(writes) == 1
    assert reopened.campaigns == current.campaigns
