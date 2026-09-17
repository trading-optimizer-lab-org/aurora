"""Pure authentication contract for the GitHub cloud catalog intake.

This module validates an already received webhook snapshot.  It deliberately
does not perform network I/O, signature verification, authority mutation,
storage, workflow dispatch, or transaction handling; those responsibilities
remain with the protected broker/authority integration.

For a resume comment, the live issue must either still have
``updated_at == created_at`` or have ``updated_at == comment.created_at`` with
the event issue and the newly-created comment agreeing on that timestamp.
The second branch is necessary because GitHub updates an issue's
``updated_at`` when a legitimate comment is added.  That timestamp equality
does not prove the complete pre-comment history, so this pure contract only
accepts a resume when ``existing=True`` identifies an already-authorized
authority binding.  A comment with ``existing=False`` is rejected as a
potential new emission; the authority integration remains responsible for
matching its intent hash, issue, and actor binding.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import math
from typing import Literal
from uuid import RFC_4122, UUID

from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from .catalog_request_contract import CAMPAIGN_KEY_PATTERN, FrozenModel, canonical_sha256


CLOUD_INTENT_ID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
CLOUD_INTENT_TITLE_PREFIX = "[AURORA CATALOG INTENT] "
CLOUD_RESUME_COMMAND_PREFIX = "AURORA_REANUDAR_INTENCION "
CLOUD_REPOSITORY_API_PREFIX = "https://api.github.com/repos/"
CloudEventName = Literal["issues", "issue_comment"]
_ALLOWED_EVENT_NAMES: frozenset[CloudEventName] = frozenset({"issues", "issue_comment"})


class _CloudModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class CloudIntentV1(_CloudModel):
    """The closed, non-executable intent embedded in an issue body."""

    schema_version: Literal["1"] = "1"
    campaign_key: StrictStr = Field(pattern=CAMPAIGN_KEY_PATTERN)
    intent_id: StrictStr = Field(pattern=CLOUD_INTENT_ID_PATTERN)

    @field_validator("intent_id")
    @classmethod
    def _require_canonical_uuid4(cls, value: str) -> str:
        parsed = UUID(value)
        if parsed.version != 4 or parsed.variant != RFC_4122 or str(parsed) != value:
            raise ValueError("intent_id must be a canonical RFC 4122 UUIDv4")
        return value

    @property
    def intent_sha256(self) -> str:
        """Hash of the exact validated three-field intent contract."""

        return canonical_sha256(self)


class CloudIntakePolicyV1(_CloudModel):
    """Protected repository/actor and freshness limits for cloud intake."""

    schema_version: Literal["1"] = "1"
    repository_id: StrictInt = Field(strict=True, ge=1)
    repository: StrictStr = Field(min_length=1)
    allowed_actor_ids: tuple[StrictInt, ...] = Field(min_length=1, max_length=128)
    ttl_seconds: StrictInt = Field(default=86400, strict=True, ge=1)
    max_body_bytes: StrictInt = Field(default=1024, strict=True, ge=1)

    @field_validator("repository")
    @classmethod
    def _require_repository_name(cls, value: str) -> str:
        if (
            value != value.strip()
            or "\x00" in value
            or any(ord(character) < 32 for character in value)
            or value.count("/") != 1
            or any(not part for part in value.split("/"))
        ):
            raise ValueError("repository must be a canonical owner/name")
        return value

    @model_validator(mode="after")
    def _validate_actor_ids(self) -> "CloudIntakePolicyV1":
        if len(self.allowed_actor_ids) != len(set(self.allowed_actor_ids)):
            raise ValueError("allowed_actor_ids must not contain duplicates")
        return self


class AuthenticatedCloudIntentV1(CloudIntentV1):
    """Validated intent plus the authenticated GitHub identity evidence."""

    event_name: Literal["issues", "issue_comment"]
    repository_id: StrictInt = Field(strict=True, ge=1)
    repository: StrictStr = Field(min_length=1)
    issue_id: StrictInt = Field(strict=True, ge=1)
    issue_number: StrictInt = Field(strict=True, ge=1)
    issue_url: StrictStr = Field(min_length=1)
    author_id: StrictInt = Field(strict=True, ge=1)
    sender_id: StrictInt = Field(strict=True, ge=1)
    comment_actor_id: StrictInt | None = Field(default=None, strict=True, ge=1)
    created_at: datetime
    observed_at: datetime
    is_resume: StrictBool

    @field_validator("created_at", "observed_at", mode="before")
    @classmethod
    def _require_aware_datetime(cls, value: object) -> datetime:
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware datetime values")
        return value.astimezone(timezone.utc)

    @property
    def intent(self) -> CloudIntentV1:
        """Return the complete intent used to compute ``intent_sha256``."""

        return CloudIntentV1(
            schema_version=self.schema_version,
            campaign_key=self.campaign_key,
            intent_id=self.intent_id,
        )

    @property
    def cloud_intent(self) -> CloudIntentV1:
        """Named alias for integrations that distinguish transport metadata."""

        return self.intent

    @property
    def intent_sha256(self) -> str:
        return self.intent.intent_sha256

    @property
    def actor_id(self) -> int:
        """The actor that caused the accepted transport event."""

        if self.is_resume:
            if self.comment_actor_id is None:
                raise ValueError("resume intent is missing its comment actor")
            return self.comment_actor_id
        return self.sender_id

    @property
    def resumed(self) -> bool:
        return self.is_resume


def _invalid(reason: str) -> ValueError:
    return ValueError(f"CLOUD_INTAKE_INVALID: {reason}")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _reject_unsafe_values(value: object, *, seen: set[int] | None = None) -> None:
    """Reject unsafe values in webhook snapshots before field extraction."""

    if isinstance(value, str):
        if "\x00" in value:
            raise _invalid("NUL is not permitted")
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise _invalid("non-finite numeric value")
    if isinstance(value, Mapping):
        active = set() if seen is None else seen
        marker = id(value)
        if marker in active:
            raise _invalid("cyclic event value")
        active.add(marker)
        try:
            for key, child in value.items():
                _reject_unsafe_values(key, seen=active)
                _reject_unsafe_values(child, seen=active)
        finally:
            active.remove(marker)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        active = set() if seen is None else seen
        marker = id(value)
        if marker in active:
            raise _invalid("cyclic event value")
        active.add(marker)
        try:
            for child in value:
                _reject_unsafe_values(child, seen=active)
        finally:
            active.remove(marker)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or isinstance(value, (str, bytes, bytearray)):
        raise _invalid(f"{label} must be a mapping")
    if any(type(key) is not str for key in value):
        raise _invalid(f"{label} keys must be strings")
    return value


def _required(mapping: Mapping[str, object], key: str, label: str) -> object:
    if key not in mapping:
        raise _invalid(f"{label}.{key} is required")
    return mapping[key]


def _strict_id(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise _invalid(f"{label} must be a positive integer")
    return value


def _strict_text(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise _invalid(f"{label} must be a non-empty string")
    return value


def _timestamp(value: object, label: str) -> datetime:
    if type(value) is datetime:
        parsed = value
    elif type(value) is str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise _invalid(f"{label} is not a valid timestamp") from exc
    else:
        raise _invalid(f"{label} must be a timestamp string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _checked_policy(policy: object) -> CloudIntakePolicyV1:
    if not isinstance(policy, CloudIntakePolicyV1):
        raise _invalid("policy must be CloudIntakePolicyV1")
    try:
        return CloudIntakePolicyV1.model_validate(
            policy.model_dump(mode="python"),
            strict=True,
        )
    except ValidationError as exc:
        raise _invalid("policy does not match schema") from exc


def _parse_intent(body: object, policy: CloudIntakePolicyV1) -> CloudIntentV1:
    if type(body) is not str:
        raise _invalid("issue body must be a string")
    try:
        body_bytes = body.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _invalid("issue body must be valid UTF-8") from exc
    if len(body_bytes) > policy.max_body_bytes:
        raise _invalid("issue body exceeds max_body_bytes")
    if "\x00" in body:
        raise _invalid("NUL is not permitted in issue body")
    try:
        payload = json.loads(
            body,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise _invalid("issue body is not strict JSON") from exc
    if type(payload) is not dict:
        raise _invalid("issue body must be a JSON object")
    if set(payload) != {"schema_version", "campaign_key", "intent_id"}:
        raise _invalid("issue body must contain exactly the three intent fields")
    try:
        return CloudIntentV1.model_validate(payload, strict=True)
    except ValidationError as exc:
        raise _invalid("issue body does not match CloudIntentV1") from exc


def _validate_repository(
    event: Mapping[str, object], policy: CloudIntakePolicyV1
) -> None:
    repository = _mapping(_required(event, "repository", "event"), "event.repository")
    repository_id = _strict_id(_required(repository, "id", "event.repository"), "repository id")
    full_name = _strict_text(
        _required(repository, "full_name", "event.repository"),
        "repository full_name",
    )
    if repository_id != policy.repository_id or full_name != policy.repository:
        raise _invalid("repository identity is not authorized")
    expected_url = f"{CLOUD_REPOSITORY_API_PREFIX}{policy.repository}"
    if "url" in repository and repository["url"] != expected_url:
        raise _invalid("repository URL is not authorized")
    if "html_url" in repository and repository["html_url"] != f"https://github.com/{policy.repository}":
        raise _invalid("repository HTML URL is not authorized")


def _validate_issue_identity(
    issue: Mapping[str, object],
    policy: CloudIntakePolicyV1,
) -> tuple[int, int, str, int, datetime, str]:
    issue_id = _strict_id(_required(issue, "id", "issue"), "issue id")
    issue_number = _strict_id(_required(issue, "number", "issue"), "issue number")
    expected_issue_url = (
        f"{CLOUD_REPOSITORY_API_PREFIX}{policy.repository}/issues/{issue_number}"
    )
    repository_url = _strict_text(
        _required(issue, "repository_url", "issue"),
        "issue repository URL",
    )
    expected_html_url = f"https://github.com/{policy.repository}/issues/{issue_number}"
    issue_url_value = issue.get("url")
    html_url_value = issue.get("html_url")
    if issue_url_value is None and html_url_value is None:
        raise _invalid("issue URL is required")
    if issue_url_value is not None and _strict_text(issue_url_value, "issue URL") != expected_issue_url:
        raise _invalid("issue URL is not authorized")
    if html_url_value is not None and _strict_text(html_url_value, "issue HTML URL") != expected_html_url:
        raise _invalid("issue HTML URL is not authorized")
    if repository_url != f"{CLOUD_REPOSITORY_API_PREFIX}{policy.repository}":
        raise _invalid("issue repository URL is not authorized")
    if "pull_request" in issue:
        raise _invalid("pull requests are not cloud-intake issues")

    title = _strict_text(_required(issue, "title", "issue"), "issue title")
    body = _strict_text(_required(issue, "body", "issue"), "issue body")
    author = _mapping(_required(issue, "user", "issue"), "issue.user")
    author_id = _strict_id(_required(author, "id", "issue.user"), "issue author id")
    created_at = _timestamp(_required(issue, "created_at", "issue"), "issue.created_at")
    if "updated_at" in issue:
        _timestamp(issue["updated_at"], "issue.updated_at")
    return issue_id, issue_number, title, author_id, created_at, body


def _validate_live_issue(
    event_issue: Mapping[str, object],
    live_issue: Mapping[str, object],
    policy: CloudIntakePolicyV1,
    *,
    require_unedited_resume: bool,
    resume_comment_created_at: datetime | None,
    observed_at: datetime,
) -> tuple[int, int, str, datetime]:
    event_id, event_number, event_title, event_author, event_created, event_body = _validate_issue_identity(
        event_issue, policy
    )
    live_id, live_number, live_title, live_author, live_created, live_body = _validate_issue_identity(
        live_issue, policy
    )
    if (
        (live_id, live_number, live_title, live_body, live_author, live_created)
        != (event_id, event_number, event_title, event_body, event_author, event_created)
    ):
        raise _invalid("live issue differs from the event issue")
    for candidate, label in ((event_issue, "issue"), (live_issue, "live_issue")):
        for timestamp_name in ("created_at", "updated_at"):
            if timestamp_name in candidate and _timestamp(
                candidate[timestamp_name], f"{label}.{timestamp_name}"
            ) > observed_at:
                raise _invalid(f"{label}.{timestamp_name} is in the future")
    if live_created > observed_at:
        raise _invalid("live issue date is in the future")

    if require_unedited_resume:
        live_updated = _timestamp(
            _required(live_issue, "updated_at", "live issue"),
            "live_issue.updated_at",
        )
        if live_updated != live_created and live_updated != resume_comment_created_at:
            raise _invalid("resume issue was edited before the resume command")
        if live_updated != live_created:
            event_updated = _timestamp(
                _required(event_issue, "updated_at", "event issue"),
                "event_issue.updated_at",
            )
            if event_updated != resume_comment_created_at:
                raise _invalid("resume timestamp is not bound to the event comment")
    return live_id, live_number, event_title, event_created


def validate_cloud_event(
    event_name: CloudEventName,
    event: Mapping[str, object],
    live_issue: Mapping[str, object],
    policy: CloudIntakePolicyV1,
    observed_at: datetime,
    existing: bool = False,
) -> AuthenticatedCloudIntentV1:
    """Authenticate one opened intent or one exact resume comment.

    ``existing=True`` bypasses only the TTL comparison and permits an exact
    resume comment whose authority binding is checked by the caller.  Every
    repository, actor, URL, event, issue-integrity, JSON, timestamp, and
    command check is still executed before returning an authenticated intent.
    A resume with ``existing=False`` is rejected because this function has no
    independent immutable issue-history evidence to authorize a new emission.
    """

    if type(event_name) is not str or event_name not in _ALLOWED_EVENT_NAMES:
        raise _invalid("unsupported event name")
    if type(existing) is not bool:
        raise _invalid("existing must be bool")
    if type(observed_at) is not datetime or observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise _invalid("observed_at must be a timezone-aware datetime")
    observed_utc = observed_at.astimezone(timezone.utc)
    event_mapping = _mapping(event, "event")
    live_mapping = _mapping(live_issue, "live_issue")
    _reject_unsafe_values(event_mapping)
    _reject_unsafe_values(live_mapping)
    checked_policy = _checked_policy(policy)

    expected_action = "opened" if event_name == "issues" else "created"
    if event_mapping.get("action") != expected_action:
        raise _invalid("event action is not authorized")
    if "ref" in event_mapping or "pull_request" in event_mapping:
        raise _invalid("event contains an unexpected ref or pull request")

    _validate_repository(event_mapping, checked_policy)
    event_issue = _mapping(_required(event_mapping, "issue", "event"), "event.issue")
    event_issue_id, issue_number, title, author_id, created_at, body = _validate_issue_identity(
        event_issue, checked_policy
    )
    intent = _parse_intent(body, checked_policy)
    expected_title = f"{CLOUD_INTENT_TITLE_PREFIX}{intent.intent_id}"
    if title != expected_title:
        raise _invalid("issue title does not bind to intent_id")

    sender = _mapping(_required(event_mapping, "sender", "event"), "event.sender")
    sender_id = _strict_id(_required(sender, "id", "event.sender"), "sender id")
    allowed = checked_policy.allowed_actor_ids
    if author_id not in allowed or sender_id not in allowed:
        raise _invalid("issue author or event sender is not authorized")

    comment_actor_id: int | None = None
    resume_comment_created_at: datetime | None = None
    if event_name == "issue_comment":
        comment = _mapping(_required(event_mapping, "comment", "event"), "event.comment")
        comment_body = _strict_text(
            _required(comment, "body", "event.comment"),
            "comment body",
        )
        if comment_body != f"{CLOUD_RESUME_COMMAND_PREFIX}{intent.intent_id}":
            raise _invalid("resume command is not exact")
        comment_user = _mapping(
            _required(comment, "user", "event.comment"),
            "event.comment.user",
        )
        comment_actor_id = _strict_id(
            _required(comment_user, "id", "event.comment.user"),
            "comment actor id",
        )
        if comment_actor_id not in allowed:
            raise _invalid("comment actor is not authorized")
        resume_comment_created_at = _timestamp(
            _required(comment, "created_at", "event.comment"),
            "comment.created_at",
        )
        if resume_comment_created_at > observed_utc:
            raise _invalid("comment date is in the future")
        comment_updated = _timestamp(
            _required(comment, "updated_at", "event.comment"),
            "comment.updated_at",
        )
        if comment_updated != resume_comment_created_at:
            raise _invalid("resume comment was edited after creation")

    live_id, live_number, _live_title, live_created = _validate_live_issue(
        event_issue,
        live_mapping,
        checked_policy,
        require_unedited_resume=event_name == "issue_comment",
        resume_comment_created_at=resume_comment_created_at,
        observed_at=observed_utc,
    )
    if live_id != event_issue_id or live_number != issue_number or live_created != created_at:
        raise _invalid("live issue identity changed")
    if created_at > observed_utc:
        raise _invalid("issue date is in the future")
    if event_name == "issue_comment" and not existing:
        raise _invalid("resume requires an existing authority binding")
    if not existing and (observed_utc - created_at).total_seconds() > checked_policy.ttl_seconds:
        raise _invalid("cloud intent has expired")

    return AuthenticatedCloudIntentV1(
        schema_version="1",
        campaign_key=intent.campaign_key,
        intent_id=intent.intent_id,
        event_name=event_name,
        repository_id=checked_policy.repository_id,
        repository=checked_policy.repository,
        issue_id=event_issue_id,
        issue_number=issue_number,
        issue_url=f"{CLOUD_REPOSITORY_API_PREFIX}{checked_policy.repository}/issues/{issue_number}",
        author_id=author_id,
        sender_id=sender_id,
        comment_actor_id=comment_actor_id,
        created_at=created_at,
        observed_at=observed_utc,
        is_resume=event_name == "issue_comment",
    )


__all__ = [
    "AuthenticatedCloudIntentV1",
    "CLOUD_INTENT_ID_PATTERN",
    "CLOUD_INTENT_TITLE_PREFIX",
    "CLOUD_REPOSITORY_API_PREFIX",
    "CLOUD_RESUME_COMMAND_PREFIX",
    "CloudIntentV1",
    "CloudIntakePolicyV1",
    "validate_cloud_event",
]
