from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from aurora.infra.sp500_megarun.catalog_cloud_intake import CloudIntentV1
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1
from scripts import validate_catalog_cloud_intent as command
from scripts import verify_catalog_cloud_qualification as qualification_gate
from tests.test_catalog_cloud_authority import emission
from tests.test_catalog_fast_authority_github import publication_transport


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "trading-optimizer-lab-org/aurora"
REPOSITORY_ID = 1232647748
ACTOR_ID = 271768688
ISSUE_ID = 987654321
ISSUE_NUMBER = 400
CREATED_AT = datetime(2026, 9, 17, 11, 55, tzinfo=timezone.utc)
OBSERVED_AT = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
SHA = "a" * 40


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _body(*, intent_id: str, campaign_key: str = "sp500-optimized-catalog-v1") -> str:
    return json.dumps(
        {
            "schema_version": "1",
            "campaign_key": campaign_key,
            "intent_id": intent_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _event(
    *,
    event_name: str = "issues",
    intent_id: str = "018f47a2-6e91-4c34-8000-000000000001",
    body: str | None = None,
    issue_updated_at: datetime | None = None,
    comment_created_at: datetime | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    updated_at = issue_updated_at or CREATED_AT
    issue = {
        "id": ISSUE_ID,
        "number": ISSUE_NUMBER,
        "title": f"[AURORA CATALOG INTENT] {intent_id}",
        "body": _body(intent_id=intent_id) if body is None else body,
        "user": {"id": ACTOR_ID, "login": "aurora-operator"},
        "created_at": _iso(CREATED_AT),
        "updated_at": _iso(updated_at),
        "url": f"https://api.github.com/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}",
        "repository_url": f"https://api.github.com/repos/{REPOSITORY}",
    }
    event: dict[str, object] = {
        "action": "opened" if event_name == "issues" else "created",
        "repository": {
            "id": REPOSITORY_ID,
            "full_name": REPOSITORY,
            "url": f"https://api.github.com/repos/{REPOSITORY}",
        },
        "issue": issue,
        "sender": {"id": ACTOR_ID, "login": "aurora-operator"},
    }
    if event_name == "issue_comment":
        comment_at = comment_created_at or CREATED_AT
        event["comment"] = {
            "id": 444,
            "body": f"AURORA_REANUDAR_INTENCION {intent_id}",
            "user": {"id": ACTOR_ID, "login": "aurora-operator"},
            "created_at": _iso(comment_at),
            "updated_at": _iso(comment_at),
        }
    return event, deepcopy(issue)


def _install_bound_network(monkeypatch, tmp_path: Path, event, live_issue, *, state=None):
    """Use real authority/replay consumers and replace only network boundaries."""
    event_path = tmp_path / "github-event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issues" if "comment" not in event else "issue_comment")
    monkeypatch.setenv("GH_TOKEN", "read-only-test-token")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("CATALOG_CLOUD_INTAKE_MODE", "OPEN_REGISTERED")
    monkeypatch.setenv("CATALOG_CLOUD_QUALIFICATION_RUN_ID", "700")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setattr(command, "_git_head", lambda _root: SHA)
    # Unit tests isolate this external gate; the integration pipeline below
    # exercises the real W2 verifier against a synthetic GitHub frontier.
    monkeypatch.setattr(qualification_gate, "require_cloud_qualification", lambda *_args: None)

    current = state or FastAuthorityStateV1.bootstrap(campaigns=())
    fixture = publication_transport(state=current, phase="intake-signed")
    fixture.run.update(
        path=".github/workflows/catalog-cloud-intake.yml",
        event="issues",
        actor={"id": ACTOR_ID},
        triggering_actor={"id": ACTOR_ID},
    )
    fixture.run["repository"]["id"] = REPOSITORY_ID
    fixture.artifact["workflow_run"].update(
        repository_id=REPOSITORY_ID,
        head_repository_id=REPOSITORY_ID,
    )
    fixture.job["name"] = "intake"
    for step in fixture.job["steps"]:
        step["name"] += " (intake-signed)"

    original_get_json = fixture.client.get_json

    def get_json(path):
        if path == f"/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}":
            return live_issue, None
        return original_get_json(path)

    fixture.client.get_json = get_json
    fixture.client.observed_at = OBSERVED_AT
    monkeypatch.setattr(command, "_make_client", lambda _repository, _token: fixture.client)
    monkeypatch.setattr(command, "_load_anchor", lambda _root: fixture.anchor)
    monkeypatch.setattr(command, "read_live_edit", lambda _anchor: fixture.edit)
    monkeypatch.setattr(command, "_download_owner_archive", lambda *_args: fixture.raw)
    return fixture


def test_mode_off_is_the_default_and_stops_before_any_reader(tmp_path, monkeypatch):
    monkeypatch.delenv("CATALOG_CLOUD_INTAKE_MODE", raising=False)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))

    result = command.main(["--repo-root", str(ROOT), "--output", str(tmp_path / "out.json")])

    assert result == 2
    assert not (tmp_path / "out.json").exists()


def test_origin_requires_actions_main_ref_and_matching_head(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_CLOUD_INTAKE_MODE", "OPEN_REGISTERED")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("GITHUB_ACTIONS", "false")

    result = command.main(["--repo-root", str(ROOT), "--output", str(tmp_path / "out.json")])

    assert result == 2
    assert not (tmp_path / "out.json").exists()


def test_canary_only_rejects_a_non_canary_registered_campaign_before_reader(tmp_path, monkeypatch):
    event, live_issue = _event()
    _install_bound_network(monkeypatch, tmp_path, event, live_issue)
    monkeypatch.setenv("CATALOG_CLOUD_INTAKE_MODE", "CANARY_ONLY")
    monkeypatch.setattr(command, "_make_client", lambda *_args: pytest.fail("lookup reached"))

    with pytest.raises(ValueError, match="CANARY_ONLY"):
        command.load_validated_cloud_context(ROOT)


def test_output_must_be_new_and_inside_runner_temp(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    outside = tmp_path.parent / "cloud-intent-public.json"

    result = command.main(["--repo-root", str(ROOT), "--output", str(outside)])

    assert result == 2
    assert not outside.exists()


def test_initial_strict_body_validation_precedes_authority_lookup(tmp_path, monkeypatch):
    event, live_issue = _event(body=(
        '{"schema_version":"1","campaign_key":"sp500-optimized-catalog-v1",'
        '"intent_id":"018f47a2-6e91-4c34-8000-000000000001",'
        '"intent_id":"018f47a2-6e91-4c34-8000-000000000001"}'
    ))
    _install_bound_network(monkeypatch, tmp_path, event, live_issue)
    monkeypatch.setattr(command, "_make_client", lambda *_args: pytest.fail("lookup reached"))

    with pytest.raises(ValueError, match="CLOUD"):
        command.load_validated_cloud_context(ROOT)


def test_qualification_gate_failure_propagates_before_live_issue_read(tmp_path, monkeypatch):
    event, live_issue = _event()
    fixture = _install_bound_network(monkeypatch, tmp_path, event, live_issue)

    def reject(*_args):
        raise ValueError("CLOUD_QUALIFICATION_RUN_PROVENANCE_INVALID")

    monkeypatch.setattr(qualification_gate, "require_cloud_qualification", reject)

    with pytest.raises(ValueError, match="CLOUD_QUALIFICATION_RUN_PROVENANCE_INVALID"):
        command.load_validated_cloud_context(ROOT)
    assert fixture.calls == []


def test_new_issue_uses_real_authority_loader_and_returns_writer_context(tmp_path, monkeypatch):
    event, live_issue = _event()
    fixture = _install_bound_network(monkeypatch, tmp_path, event, live_issue)

    context = command.load_validated_cloud_context(ROOT)

    assert context.intent.intent_id == "018f47a2-6e91-4c34-8000-000000000001"
    assert context.authority == fixture.state
    assert context.latest_edit_id == "E_current"
    assert context.replay is None


def test_existing_uuid_sets_existing_only_after_authority_binding(tmp_path, monkeypatch):
    item = emission()
    authority = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(item)
    event, live_issue = _event(intent_id=item.intent_id)
    fixture = _install_bound_network(monkeypatch, tmp_path, event, live_issue, state=authority)

    context = command.load_validated_cloud_context(ROOT)

    assert context.intent.intent_id == item.intent_id
    assert context.replay == item
    assert context.status == "SIGNED"
    assert fixture.calls


def test_existing_resume_accepts_issue_timestamp_changed_by_that_comment(tmp_path, monkeypatch):
    item = emission()
    authority = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(item)
    comment_at = CREATED_AT.replace(minute=56)
    event, live_issue = _event(
        event_name="issue_comment",
        intent_id=item.intent_id,
        issue_updated_at=comment_at,
        comment_created_at=comment_at,
    )
    fixture = _install_bound_network(monkeypatch, tmp_path, event, live_issue, state=authority)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issue_comment")
    # The real fixture is the network boundary; replay and intake validation remain real.
    context = command.load_validated_cloud_context(ROOT)

    assert context.intent.is_resume is True
    assert context.replay == item
    assert fixture.state == context.authority


def test_replay_binding_conflict_is_not_an_authorization_boolean(tmp_path, monkeypatch):
    item = emission(actor_id=999)
    authority = FastAuthorityStateV1.bootstrap(campaigns=()).stage_emission(item)
    event, live_issue = _event(intent_id=item.intent_id)
    _install_bound_network(monkeypatch, tmp_path, event, live_issue, state=authority)

    with pytest.raises(ValueError, match="INTENT_CONFLICT"):
        command.load_validated_cloud_context(ROOT)


def test_main_writes_only_validated_public_result(tmp_path, monkeypatch):
    event, live_issue = _event()
    _install_bound_network(monkeypatch, tmp_path, event, live_issue)
    output = tmp_path / "public-result.json"

    result = command.main(["--repo-root", str(ROOT), "--output", str(output)])

    assert result == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "NEW"
    assert payload["authenticated_intent"]["intent_id"] == "018f47a2-6e91-4c34-8000-000000000001"
    assert "authorized" not in payload
