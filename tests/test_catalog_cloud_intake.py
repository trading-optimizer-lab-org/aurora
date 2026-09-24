from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from aurora.infra.sp500_megarun.catalog_cloud_intake import (
    AuthenticatedCloudIntentV1,
    CloudIntentV1,
    CloudIntakePolicyV1,
    validate_cloud_event,
)


UTC = timezone.utc
OBSERVED_AT = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
CREATED_AT = OBSERVED_AT - timedelta(minutes=5)
CAMPAIGN = "sp500-optimized-catalog-v1"
INTENT_ID = "018f47a2-6e91-4c34-8000-000000000001"
REPOSITORY = "aurora/catalog"
REPOSITORY_ID = 1232647748
ACTOR_ID = 271768688
ISSUE_ID = 987654321
ISSUE_NUMBER = 400


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _intent(*, intent_id: str = INTENT_ID, campaign_key: str = CAMPAIGN) -> CloudIntentV1:
    return CloudIntentV1(
        schema_version="1",
        campaign_key=campaign_key,
        intent_id=intent_id,
    )


def _body(*, intent_id: str = INTENT_ID, extra: dict[str, object] | None = None) -> str:
    value: dict[str, object] = {
        "schema_version": "1",
        "campaign_key": CAMPAIGN,
        "intent_id": intent_id,
    }
    if extra:
        value.update(extra)
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _policy(**updates: object) -> CloudIntakePolicyV1:
    values: dict[str, object] = {
        "schema_version": "1",
        "repository_id": REPOSITORY_ID,
        "repository": REPOSITORY,
        "allowed_actor_ids": (ACTOR_ID, 777),
    }
    values.update(updates)
    return CloudIntakePolicyV1(**values)


def _issue(
    *,
    author_id: int = ACTOR_ID,
    issue_id: int = ISSUE_ID,
    title: str | None = None,
    body: str | None = None,
    created_at: datetime = CREATED_AT,
    updated_at: datetime | None = None,
    pull_request: object = None,
) -> dict[str, object]:
    issue: dict[str, object] = {
        "id": issue_id,
        "number": ISSUE_NUMBER,
        "title": title or f"[AURORA CATALOG INTENT] {INTENT_ID}",
        "body": _body() if body is None else body,
        "user": {"id": author_id, "login": "aurora-operator"},
        "created_at": _iso(created_at),
        "updated_at": _iso(created_at if updated_at is None else updated_at),
        "url": f"https://api.github.com/repos/{REPOSITORY}/issues/{ISSUE_NUMBER}",
        "repository_url": f"https://api.github.com/repos/{REPOSITORY}",
    }
    if pull_request is not None:
        issue["pull_request"] = pull_request
    return issue


def _event(
    *,
    event_name: str = "issues",
    action: str = "opened",
    sender_id: int = ACTOR_ID,
    author_id: int = ACTOR_ID,
    comment_actor_id: int = ACTOR_ID,
    issue: dict[str, object] | None = None,
    comment_body: str | None = None,
    created_at: datetime = CREATED_AT,
) -> tuple[dict[str, object], dict[str, object]]:
    issue_value = _issue(author_id=author_id, created_at=created_at) if issue is None else issue
    event: dict[str, object] = {
        "action": action,
        "repository": {
            "id": REPOSITORY_ID,
            "full_name": REPOSITORY,
            "url": f"https://api.github.com/repos/{REPOSITORY}",
        },
        "issue": issue_value,
        "sender": {"id": sender_id, "login": "aurora-operator"},
    }
    if event_name == "issue_comment":
        event["comment"] = {
            "id": 444,
            "body": comment_body or f"AURORA_REANUDAR_INTENCION {INTENT_ID}",
            "user": {"id": comment_actor_id, "login": "aurora-operator"},
            "created_at": _iso(created_at),
            "updated_at": _iso(created_at),
        }
    return event, deepcopy(issue_value)


def _validate(
    event_name: str = "issues",
    *,
    event: dict[str, object] | None = None,
    live_issue: dict[str, object] | None = None,
    policy: CloudIntakePolicyV1 | None = None,
    observed_at: datetime = OBSERVED_AT,
    existing: bool = False,
) -> AuthenticatedCloudIntentV1:
    if event is None:
        event, default_live = _event(event_name=event_name)
        if live_issue is None:
            live_issue = default_live
    assert live_issue is not None
    return validate_cloud_event(
        event_name,
        event,
        live_issue,
        policy or _policy(),
        observed_at,
        existing=existing,
    )


def test_policy_defaults_and_strict_cloud_intent_shape() -> None:
    policy = CloudIntakePolicyV1(
        repository_id=REPOSITORY_ID,
        repository=REPOSITORY,
        allowed_actor_ids=(ACTOR_ID,),
    )

    assert policy.schema_version == "1"
    assert policy.ttl_seconds == 86400
    assert policy.max_body_bytes == 1024
    assert _intent().model_dump() == {
        "schema_version": "1",
        "campaign_key": CAMPAIGN,
        "intent_id": INTENT_ID,
    }


def test_policy_json_array_is_loaded_as_typed_tuple() -> None:
    loaded = CloudIntakePolicyV1.model_validate_json(
        json.dumps(
            {
                "schema_version": "1",
                "repository_id": REPOSITORY_ID,
                "repository": REPOSITORY,
                "allowed_actor_ids": [ACTOR_ID],
                "ttl_seconds": 86400,
                "max_body_bytes": 1024,
            }
        )
    )

    assert loaded.allowed_actor_ids == (ACTOR_ID,)


def test_accepts_opened_cloud_intent() -> None:
    result = _validate()

    assert isinstance(result, AuthenticatedCloudIntentV1)
    assert result.schema_version == "1"
    assert result.campaign_key == CAMPAIGN
    assert result.intent_id == INTENT_ID
    assert result.event_name == "issues"
    assert result.intent == _intent()
    assert result.intent_sha256 == _intent().intent_sha256
    assert result.issue_number == ISSUE_NUMBER
    assert result.author_id == ACTOR_ID
    assert result.sender_id == ACTOR_ID
    assert result.comment_actor_id is None
    assert result.is_resume is False
    assert result.created_at == CREATED_AT
    assert result.observed_at == OBSERVED_AT


def test_accepts_created_resume_command_only_after_unchanged_issue() -> None:
    event, live_issue = _event(
        event_name="issue_comment",
        action="created",
    )

    result = _validate("issue_comment", event=event, live_issue=live_issue, existing=True)

    assert result.event_name == "issue_comment"
    assert result.is_resume is True
    assert result.comment_actor_id == ACTOR_ID


def test_accepts_resume_when_the_command_comment_updates_issue_timestamp() -> None:
    event, live_issue = _event(event_name="issue_comment", action="created")
    comment_created_at = CREATED_AT + timedelta(minutes=1)
    assert isinstance(event["comment"], dict)
    assert isinstance(event["issue"], dict)
    event["comment"]["created_at"] = _iso(comment_created_at)
    event["comment"]["updated_at"] = _iso(comment_created_at)
    event["issue"]["updated_at"] = _iso(comment_created_at)
    live_issue["updated_at"] = _iso(comment_created_at)

    result = _validate("issue_comment", event=event, live_issue=live_issue, existing=True)

    assert result.is_resume is True


def test_resume_cannot_create_a_new_emission_without_existing_binding() -> None:
    event, live_issue = _event(event_name="issue_comment", action="created")

    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate("issue_comment", event=event, live_issue=live_issue)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sender", {"id": 999}),
        ("author", {"id": 999}),
    ],
)
def test_rejects_unauthorized_sender_or_issue_author(field: str, value: dict[str, int]) -> None:
    event, live_issue = _event()
    if field == "sender":
        event["sender"] = value
    else:
        assert isinstance(event["issue"], dict)
        event["issue"]["user"] = value

    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate(event=event, live_issue=live_issue)


def test_rejects_unauthorized_comment_actor_even_when_sender_is_allowed() -> None:
    event, live_issue = _event(
        event_name="issue_comment",
        action="created",
        comment_actor_id=999,
    )

    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate("issue_comment", event=event, live_issue=live_issue, existing=True)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda event: event["repository"].update({"id": 99}),
        lambda event: event["repository"].update({"full_name": "other/repo"}),
        lambda event: event["issue"].update({"repository_url": "https://api.github.com/repos/other/repo"}),
        lambda event: event["issue"].update({"url": "https://api.github.com/repos/aurora/catalog/issues/401"}),
        lambda event: event["issue"].update({"pull_request": {"url": "https://example.invalid/pr"}}),
    ],
)
def test_rejects_repository_issue_url_or_pull_request_mismatch(mutation) -> None:
    event, live_issue = _event()
    mutation(event)

    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate(event=event, live_issue=live_issue)


@pytest.mark.parametrize(
    ("event_name", "action"),
    [
        ("push", "opened"),
        ("issues", "closed"),
        ("issue_comment", "edited"),
    ],
)
def test_rejects_unsupported_event_or_action(event_name: str, action: str) -> None:
    event, live_issue = _event(event_name=event_name, action=action)

    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate(event_name, event=event, live_issue=live_issue)


def test_rejects_unexpected_ref_in_event() -> None:
    event, live_issue = _event()
    event["ref"] = "refs/heads/main"

    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate(event=event, live_issue=live_issue)


@pytest.mark.parametrize(
    "body",
    [
        '{"schema_version":"1","campaign_key":"sp500-optimized-catalog-v1",'
        '"intent_id":"018f47a2-6e91-4c34-8000-000000000001",'
        '"intent_id":"018f47a2-6e91-4c34-8000-000000000001"}',
        '{"schema_version":"1","campaign_key":"sp500-optimized-catalog-v1",'
        '"intent_id":NaN}',
        '{"schema_version":"1","campaign_key":"sp500-optimized-catalog-v1",'
        '"intent_id":"018f47a2-6e91-4c34-8000-000000000001","extra":true}',
        '{"schema_version":"1","campaign_key":"sp500-optimized-catalog-v1",'
        '"intent_id":"018F47A2-6E91-4C34-8000-000000000001"}',
    ],
)
def test_rejects_ambiguous_or_non_closed_json_body(body: str) -> None:
    event, live_issue = _event(issue=_issue(body=body))

    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate(event=event, live_issue=live_issue)


def test_rejects_nul_and_oversized_body() -> None:
    event, live_issue = _event(issue=_issue(body=_body() + "\x00"))
    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate(event=event, live_issue=live_issue)

    oversized = _body() + (" " * 1024)
    event, live_issue = _event(issue=_issue(body=oversized))
    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate(event=event, live_issue=live_issue)


def test_rejects_invalid_cloud_intent_uuid() -> None:
    event, live_issue = _event(issue=_issue(body=_body(intent_id="not-a-uuid")))

    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate(event=event, live_issue=live_issue)


@pytest.mark.parametrize("field", ["title", "body", "id", "created_at", "author"])
def test_rejects_live_issue_edit(field: str) -> None:
    event, live_issue = _event()
    if field == "author":
        live_issue["user"] = {"id": 999, "login": "changed"}
    elif field == "id":
        live_issue["id"] = ISSUE_ID + 1
    elif field == "created_at":
        live_issue[field] = _iso(CREATED_AT + timedelta(seconds=1))
    elif field == "body":
        live_issue[field] = _body(extra={"changed": True})
    else:
        live_issue[field] = "changed"

    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate(event=event, live_issue=live_issue)


def test_resume_rejects_prior_issue_edit_and_wrong_command() -> None:
    event, live_issue = _event(event_name="issue_comment", action="created")
    live_issue["updated_at"] = _iso(CREATED_AT + timedelta(seconds=1))
    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate("issue_comment", event=event, live_issue=live_issue, existing=True)

    event, live_issue = _event(event_name="issue_comment", action="created")
    assert isinstance(event["comment"], dict)
    event["comment"]["updated_at"] = _iso(CREATED_AT + timedelta(seconds=1))
    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate("issue_comment", event=event, live_issue=live_issue, existing=True)

    event, live_issue = _event(
        event_name="issue_comment",
        action="created",
        comment_body=f"AURORA_REANUDAR_INTENCION {INTENT_ID} ",
    )
    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate("issue_comment", event=event, live_issue=live_issue, existing=True)


def test_rejects_expired_intent_but_existing_only_skips_expiry() -> None:
    old_created_at = OBSERVED_AT - timedelta(seconds=86401)
    event, live_issue = _event(created_at=old_created_at)

    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate(event=event, live_issue=live_issue)

    accepted = _validate(event=event, live_issue=live_issue, existing=True)
    assert accepted.intent_id == INTENT_ID

    event["sender"] = {"id": 999}
    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate(event=event, live_issue=live_issue, existing=True)


@pytest.mark.parametrize(
    "invalid_policy",
    [
        {"repository_id": True},
        {"allowed_actor_ids": (True,)},
        {"ttl_seconds": True},
        {"max_body_bytes": False},
    ],
)
def test_policy_uses_strict_types(invalid_policy: dict[str, object]) -> None:
    values: dict[str, object] = {
        "repository_id": REPOSITORY_ID,
        "repository": REPOSITORY,
        "allowed_actor_ids": (ACTOR_ID,),
    }
    values.update(invalid_policy)

    with pytest.raises(ValueError):
        CloudIntakePolicyV1(**values)


def test_rejects_naive_or_future_dates() -> None:
    event, live_issue = _event(created_at=OBSERVED_AT + timedelta(seconds=1))
    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate(event=event, live_issue=live_issue)

    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate(observed_at=OBSERVED_AT.replace(tzinfo=None))

    event, live_issue = _event()
    assert isinstance(event["issue"], dict)
    event["issue"]["updated_at"] = _iso(OBSERVED_AT + timedelta(seconds=1))
    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate(event=event, live_issue=live_issue)


def test_rejects_comment_actor_when_it_is_a_bool_instead_of_an_int() -> None:
    event, live_issue = _event(event_name="issue_comment", action="created")
    assert isinstance(event["comment"], dict)
    event["comment"]["user"] = {"id": True, "login": "aurora-operator"}

    with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
        _validate("issue_comment", event=event, live_issue=live_issue)


def test_only_prevalidated_unstaged_atlas_issue_can_resume_without_authority_binding() -> None:
    created = datetime(2026, 9, 24, 9, 56, 6, tzinfo=UTC)
    commented = created + timedelta(days=2)
    intent_id = "7ce685e5-b48d-494e-a1d4-a115c9507dcb"
    issue = _issue(
        issue_id=5566551792,
        title=f"[AURORA CATALOG INTENT] {intent_id}",
        body=(f'{{"schema_version":"1","campaign_key":"sp500-atlas-v1",'
              f'"intent_id":"{intent_id}"}}'),
        created_at=created,
        updated_at=commented,
    )
    issue["number"] = 368
    issue["url"] = "https://api.github.com/repos/trading-optimizer-lab-org/aurora/issues/368"
    issue["repository_url"] = "https://api.github.com/repos/trading-optimizer-lab-org/aurora"
    event, live_issue = _event(
        event_name="issue_comment", action="created", issue=issue,
        comment_body=f"AURORA_REANUDAR_INTENCION {intent_id}", created_at=commented,
    )
    event["repository"] = {
        "id": REPOSITORY_ID, "full_name": "trading-optimizer-lab-org/aurora",
        "url": "https://api.github.com/repos/trading-optimizer-lab-org/aurora",
    }
    policy = _policy(repository="trading-optimizer-lab-org/aurora")
    accepted = _validate(
        "issue_comment", event=event, live_issue=live_issue, policy=policy,
        observed_at=commented + timedelta(seconds=1),
    )
    assert accepted.intent_id == intent_id
    assert accepted.is_resume is True

    for field, value in (("id", 5566551793), ("number", 369)):
        changed_event, changed_live = deepcopy(event), deepcopy(live_issue)
        changed_issue = changed_event["issue"]
        assert isinstance(changed_issue, dict)
        changed_issue[field] = value
        changed_live[field] = value
        with pytest.raises(ValueError, match="CLOUD_INTAKE_INVALID"):
            _validate(
                "issue_comment", event=changed_event, live_issue=changed_live,
                policy=policy, observed_at=commented + timedelta(seconds=1),
            )
