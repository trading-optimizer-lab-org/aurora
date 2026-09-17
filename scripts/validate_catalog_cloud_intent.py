#!/usr/bin/env python3
"""Validate one cloud catalog intent before any secret or publication step.

This command is deliberately an admission reader.  It reads the GitHub event
from the Actions-provided environment, reads the exact live issue and the
authenticated authority, and writes only a public validation result.  It does
not sign, create, edit, dispatch, or otherwise mutate a GitHub object.  A
producer must call :func:`load_validated_cloud_context` again after obtaining
its secret and must revalidate the returned authority binding.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Literal, cast


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from pydantic import ConfigDict, Field, StrictInt, StrictStr, model_validator

from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    CatalogCampaignEntryV1,
    CatalogCampaignRegistryV1,
    load_catalog_campaign_registry,
    resolve_catalog_campaign,
)
from aurora.infra.sp500_megarun.catalog_cloud_emission import (
    CatalogCloudCompletedIntentV1,
    CatalogCloudEmissionV1,
)
from aurora.infra.sp500_megarun.catalog_cloud_intake import (
    AuthenticatedCloudIntentV1,
    CloudEventName,
    CloudIntentV1,
    CloudIntakePolicyV1,
    validate_cloud_event,
)
from aurora.infra.sp500_megarun.catalog_cloud_replay import resolve_cloud_replay
from aurora.infra.sp500_megarun.catalog_fast_authority import FastAuthorityStateV1
from aurora.infra.sp500_megarun.catalog_fast_authority_github import load_current_fast_authority
from aurora.infra.sp500_megarun.catalog_github_snapshot import (
    CatalogGitHubReadOnlyClient,
    CatalogGitHubSnapshotError,
)
from aurora.infra.sp500_megarun.catalog_request_contract import FrozenModel, Sha256
from scripts.admit_catalog_fast_request import (
    _download_owner_archive,
    _historical_owner_commit_approved,
)
from scripts.verify_catalog_fast_authority import read_live_edit


_REPOSITORY = "trading-optimizer-lab-org/aurora"
_REPOSITORY_ID = 1232647748
_CANARY_CAMPAIGN = "catalog-fast-canary-v1"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_MODES = {"OFF", "CANARY_ONLY", "OPEN_REGISTERED"}
_STATUS = Literal[
    "NEW",
    "SIGNED",
    "PUBLICACION_INCIERTA",
    "PUBLICADO",
    "COMPLETED",
]


class CloudIntakePublicResultV1(FrozenModel):
    """Public, validated evidence; this is not an emission authorization."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["1"] = "1"
    status: _STATUS
    authenticated_intent: AuthenticatedCloudIntentV1
    intent_sha256: Sha256
    authority_revision: StrictInt = Field(strict=True, ge=1)
    authority_state_sha256: Sha256
    latest_edit_id: StrictStr = Field(strict=True, min_length=1)

    @model_validator(mode="after")
    def _bind_intent_hash(self) -> "CloudIntakePublicResultV1":
        if self.intent_sha256 != self.authenticated_intent.intent_sha256:
            raise ValueError("CATALOG_CLOUD_PUBLIC_RESULT_INTENT_CONFLICT")
        return self


@dataclass(frozen=True, slots=True)
class CloudValidatedContextV1:
    """The reusable authoritative read returned to the secret-bearing writer.

    ``intent`` is the complete :class:`AuthenticatedCloudIntentV1`, ``authority``
    is loaded from the live protected publication, and ``latest_edit_id`` is the
    edit id from the final live authority read.  ``replay`` is the exact row
    returned by ``resolve_cloud_replay`` (or ``None`` for a new intent).
    """

    intent: AuthenticatedCloudIntentV1
    authority: FastAuthorityStateV1
    latest_edit_id: str
    replay: CatalogCloudEmissionV1 | CatalogCloudCompletedIntentV1 | None

    @property
    def authenticated_intent(self) -> AuthenticatedCloudIntentV1:
        """Named alias for callers that use the public output terminology."""

        return self.intent

    @property
    def status(self) -> _STATUS:
        if self.replay is None:
            return "NEW"
        if isinstance(self.replay, CatalogCloudCompletedIntentV1):
            return "COMPLETED"
        return self.replay.state


def _invalid(reason: str) -> ValueError:
    return ValueError(f"CATALOG_CLOUD_INTAKE_INVALID: {reason}")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _invalid("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise _invalid(f"non-finite JSON constant: {value}")


def _reject_nul(value: object) -> None:
    if isinstance(value, str):
        if "\x00" in value:
            raise _invalid("NUL is not permitted")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            _reject_nul(key)
            _reject_nul(child)
    elif isinstance(value, list):
        for child in value:
            _reject_nul(child)


def _strict_json_file(path: Path, *, max_bytes: int = 4 * 1024 * 1024) -> object:
    if path.is_symlink() or not path.is_file():
        raise _invalid("JSON input is not a regular file")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise _invalid("JSON input is unavailable") from exc
    if len(raw) > max_bytes:
        raise _invalid("JSON input is oversized")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("CATALOG_CLOUD_INTAKE_INVALID"):
            raise
        raise _invalid("JSON input is not strict UTF-8 JSON") from exc
    _reject_nul(value)
    return value


def _repository_path(root: Path, relative: str) -> Path:
    candidate = root / relative
    if candidate.is_symlink() or not candidate.is_file():
        raise _invalid(f"protected file unavailable: {relative}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise _invalid(f"protected file escapes repository: {relative}")
    return resolved


def _root_path(repo_root: Path) -> Path:
    supplied = Path(repo_root)
    if supplied.is_symlink():
        raise _invalid("repository root must not be a symlink")
    try:
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise _invalid("repository root is unavailable") from exc
    if not root.is_dir():
        raise _invalid("repository root is not a directory")
    return root


def _load_policy(root: Path) -> CloudIntakePolicyV1:
    path = _repository_path(root, "config/catalog_cloud_intake_policy_v1.json")
    raw = _strict_json_file(path, max_bytes=32 * 1024)
    if not isinstance(raw, Mapping):
        raise _invalid("cloud policy must be an object")
    try:
        policy = CloudIntakePolicyV1.model_validate_json(
            json.dumps(raw, ensure_ascii=False, allow_nan=False)
        )
    except Exception as exc:
        raise _invalid("cloud policy does not match CloudIntakePolicyV1") from exc
    if policy.repository != _REPOSITORY or policy.repository_id != _REPOSITORY_ID:
        raise _invalid("cloud policy repository is not protected")
    return policy


def _load_anchor(root: Path) -> dict[str, object]:
    path = _repository_path(root, "config/catalog_authority_anchor_v1.json")
    raw = _strict_json_file(path, max_bytes=32 * 1024)
    if not isinstance(raw, dict):
        raise _invalid("authority anchor must be an object")
    return raw


def _load_registry(root: Path) -> CatalogCampaignRegistryV1:
    path = _repository_path(root, "config/catalog_campaign_registry_v1.json")
    try:
        return load_catalog_campaign_registry(path)
    except (OSError, ValueError) as exc:
        raise _invalid("campaign registry is unavailable or invalid") from exc


def _mode() -> str:
    value = os.environ.get("CATALOG_CLOUD_INTAKE_MODE", "OFF")
    if value not in _MODES:
        raise _invalid("CATALOG_CLOUD_INTAKE_MODE is invalid")
    if value == "OFF":
        raise _invalid("cloud intake is disabled")
    return value


def _git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise _invalid("git HEAD is unavailable")
    return result.stdout.strip()


def _verify_actions_origin(root: Path, policy: CloudIntakePolicyV1) -> str:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise _invalid("execution is not GitHub Actions")
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise _invalid("protected ref is not main")
    if os.environ.get("GITHUB_REF_NAME") != "main":
        raise _invalid("protected ref name is not main")
    if os.environ.get("GITHUB_REPOSITORY") != policy.repository:
        raise _invalid("GitHub repository is not protected")
    commit = os.environ.get("GITHUB_SHA", "")
    if not _COMMIT.fullmatch(commit) or _git_head(root) != commit:
        raise _invalid("checkout HEAD does not match GITHUB_SHA")
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise _invalid("GH_TOKEN is missing")
    return commit


def _event_file() -> tuple[CloudEventName, Mapping[str, object]]:
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if event_name not in {"issues", "issue_comment"}:
        raise _invalid("GITHUB_EVENT_NAME is invalid")
    raw_path = os.environ.get("GITHUB_EVENT_PATH", "")
    if not raw_path:
        raise _invalid("GITHUB_EVENT_PATH is missing")
    path = Path(raw_path)
    value = _strict_json_file(path)
    if not isinstance(value, Mapping):
        raise _invalid("GitHub event must be an object")
    return cast(CloudEventName, event_name), value


def _strict_positive_int(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise _invalid(f"{label} must be a positive integer")
    return value


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise _invalid(f"{label} must be an object")
    return value


def _preview_event(
    event_name: CloudEventName,
    event: Mapping[str, object],
    policy: CloudIntakePolicyV1,
) -> tuple[CloudIntentV1, int]:
    """Strictly identify the issue and UUID before any authority lookup."""

    expected_action = "opened" if event_name == "issues" else "created"
    if event.get("action") != expected_action:
        raise _invalid("event action is not authorized")
    if "ref" in event or "pull_request" in event:
        raise _invalid("event contains an unexpected ref or pull request")
    repository = _mapping(event.get("repository"), "event.repository")
    if (
        _strict_positive_int(repository.get("id"), "repository id") != policy.repository_id
        or repository.get("full_name") != policy.repository
    ):
        raise _invalid("event repository is not authorized")
    issue = _mapping(event.get("issue"), "event.issue")
    issue_number = _strict_positive_int(issue.get("number"), "issue number")
    if "pull_request" in issue:
        raise _invalid("pull requests are not cloud-intake issues")
    body = issue.get("body")
    if type(body) is not str or len(body.encode("utf-8")) > policy.max_body_bytes or "\x00" in body:
        raise _invalid("issue body is invalid or oversized")
    try:
        body_value = json.loads(
            body,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
        if not isinstance(body_value, dict) or set(body_value) != {
            "schema_version",
            "campaign_key",
            "intent_id",
        }:
            raise _invalid("issue body must contain exactly the three intent fields")
        intent = CloudIntentV1.model_validate(body_value, strict=True)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("CATALOG_CLOUD_INTAKE_INVALID"):
            raise
        raise _invalid("issue body does not match CloudIntentV1") from exc
    if issue.get("title") != f"[AURORA CATALOG INTENT] {intent.intent_id}":
        raise _invalid("issue title does not bind to intent_id")
    author = _mapping(issue.get("user"), "event.issue.user")
    if _strict_positive_int(author.get("id"), "issue author id") not in policy.allowed_actor_ids:
        raise _invalid("issue author is not authorized")
    sender = _mapping(event.get("sender"), "event.sender")
    if _strict_positive_int(sender.get("id"), "sender id") not in policy.allowed_actor_ids:
        raise _invalid("event sender is not authorized")
    if event_name == "issue_comment":
        comment = _mapping(event.get("comment"), "event.comment")
        if comment.get("body") != f"AURORA_REANUDAR_INTENCION {intent.intent_id}":
            raise _invalid("resume command is not exact")
        comment_user = _mapping(comment.get("user"), "event.comment.user")
        if _strict_positive_int(comment_user.get("id"), "comment actor id") not in policy.allowed_actor_ids:
            raise _invalid("comment actor is not authorized")
    return intent, issue_number


def _make_client(repository: str, token: str) -> CatalogGitHubReadOnlyClient:
    """Construct the existing bounded GET-only GitHub client."""

    return CatalogGitHubReadOnlyClient(repository, token)


def _authority_edit_id(payload: object) -> str:
    try:
        data = _mapping(
            _mapping(payload, "authority response").get("data"),
            "authority response.data",
        )
        repository = _mapping(data.get("repository"), "authority response.repository")
        issue = _mapping(repository.get("issue"), "authority response.repository.issue")
        edits = _mapping(issue.get("userContentEdits"), "authority response.issue.userContentEdits")
        nodes = edits.get("nodes")
    except (KeyError, TypeError) as exc:
        raise _invalid("authority edit response is malformed") from exc
    if not isinstance(nodes, list) or len(nodes) != 1:
        raise _invalid("authority edit response is not singular")
    edit_id = _mapping(nodes[0], "authority edit").get("id")
    if type(edit_id) is not str or not edit_id:
        raise _invalid("authority edit id is invalid")
    return edit_id


def _authority_contains_intent(authority: FastAuthorityStateV1, intent_id: str) -> bool:
    rows = (*authority.emissions, *authority.completed_intents)
    return any(row.intent_id == intent_id for row in rows)


def _registered_campaign(
    root: Path,
    registry: CatalogCampaignRegistryV1,
    campaign_key: str,
    mode: str,
) -> CatalogCampaignEntryV1:
    try:
        entry = resolve_catalog_campaign(registry, campaign_key, root)
    except ValueError as exc:
        raise _invalid("campaign is not active and registered") from exc
    if mode == "CANARY_ONLY" and entry.campaign_key != _CANARY_CAMPAIGN:
        raise _invalid("campaign is outside CANARY_ONLY")
    return entry


def load_validated_cloud_context(repo_root: Path) -> CloudValidatedContextV1:
    """Read and validate one cloud intent against the live protected authority.

    This is the API intended for the secret-bearing writer.  It performs no
    signing or mutation and returns the authenticated intent, the verified
    authority, the final authority edit id, and the exact replay binding.  The
    caller must invoke it again after loading a secret; the output JSON is not
    an authorization token.
    """

    mode = _mode()
    root = _root_path(repo_root)
    policy = _load_policy(root)
    commit = _verify_actions_origin(root, policy)
    event_name, event = _event_file()
    preview, issue_number = _preview_event(event_name, event, policy)
    registry = _load_registry(root)
    _registered_campaign(root, registry, preview.campaign_key, mode)

    token = os.environ["GH_TOKEN"]
    client = _make_client(policy.repository, token)
    from scripts.verify_catalog_cloud_qualification import require_cloud_qualification
    require_cloud_qualification(root, client, commit)
    try:
        live_raw, _ = client.get_json(f"/repos/{policy.repository}/issues/{issue_number}")
    except (CatalogGitHubSnapshotError, OSError, ValueError) as exc:
        raise _invalid("live issue read failed") from exc
    live_issue = _mapping(live_raw, "live issue")

    # The authority loader is intentionally the real authenticated reader.  A
    # local snapshot is never accepted as a substitute for this path.
    anchor = _load_anchor(root)
    latest_edit_id: str | None = None

    def read_edit() -> Mapping[str, object]:
        nonlocal latest_edit_id
        payload = read_live_edit(anchor)
        latest_edit_id = _authority_edit_id(payload)
        return payload

    try:
        authority = load_current_fast_authority(
            client=client,
            anchor=anchor,
            protected_commit=commit,
            read_edit=read_edit,
            download_archive=lambda artifact_id: _download_owner_archive(
                policy.repository, token, artifact_id
            ),
            approve_historical_commit=lambda candidate: _historical_owner_commit_approved(
                client, candidate, commit
            ),
        )
    except (
        CatalogGitHubSnapshotError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
    ) as exc:
        raise _invalid("live authority read failed") from exc
    if latest_edit_id is None:
        raise _invalid("live authority edit id is unavailable")

    # The UUID was parsed before the authority lookup.  Only an exact durable
    # authority occurrence can grant the TTL exception for a replay.
    existing = _authority_contains_intent(authority, preview.intent_id)
    observed_at = getattr(client, "observed_at", None)
    if observed_at is None:
        raise _invalid("GitHub observation time is unavailable")
    intent = validate_cloud_event(
        event_name,
        event,
        live_issue,
        policy,
        observed_at,
        existing=existing,
    )
    replay = resolve_cloud_replay(authority, intent)
    return CloudValidatedContextV1(
        intent=intent,
        authority=authority,
        latest_edit_id=latest_edit_id,
        replay=replay,
    )


def _output_target(path: Path) -> tuple[Path, Path]:
    runner_temp_raw = os.environ.get("RUNNER_TEMP", "")
    if not runner_temp_raw:
        raise _invalid("RUNNER_TEMP is missing")
    runner_temp_arg = Path(runner_temp_raw)
    if runner_temp_arg.is_symlink():
        raise _invalid("RUNNER_TEMP must not be a symlink")
    try:
        runner_temp = runner_temp_arg.resolve(strict=True)
    except OSError as exc:
        raise _invalid("RUNNER_TEMP is unavailable") from exc
    if not runner_temp.is_dir():
        raise _invalid("RUNNER_TEMP is not a directory")
    target_arg = Path(path)
    if target_arg.is_symlink() or target_arg.exists():
        raise _invalid("output must be a new regular path")
    target = target_arg.resolve(strict=False)
    if not target.is_relative_to(runner_temp) or not target.parent.is_dir():
        raise _invalid("output must be inside RUNNER_TEMP")
    cursor = target.parent
    while cursor != runner_temp:
        if cursor.is_symlink() or not cursor.is_dir():
            raise _invalid("output parent path is not safe")
        cursor = cursor.parent
    return runner_temp, target


def _write_exclusive(path: Path, result: CloudIntakePublicResultV1) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    payload = result.model_dump_json() + "\n"
    try:
        descriptor = os.open(str(path), flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
    except OSError as exc:
        raise _invalid("output exclusive create failed") from exc


def _public_result(context: CloudValidatedContextV1) -> CloudIntakePublicResultV1:
    return CloudIntakePublicResultV1(
        schema_version="1",
        status=context.status,
        authenticated_intent=context.intent,
        intent_sha256=context.intent.intent_sha256,
        authority_revision=context.authority.revision,
        authority_state_sha256=context.authority.state_sha256,
        latest_edit_id=context.latest_edit_id,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        _, output = _output_target(args.output)
        context = load_validated_cloud_context(args.repo_root)
        result = _public_result(context)
        _write_exclusive(output, result)
        print(result.model_dump_json())
        return 0
    except (
        CatalogGitHubSnapshotError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        reason = str(exc).split(":", 1)[0]
        if not re.fullmatch(r"(?:CATALOG_|CLOUD_)[A-Z0-9_]+", reason):
            reason = "CATALOG_CLOUD_INTAKE_UNAVAILABLE"
        print(reason, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CloudIntakePublicResultV1",
    "CloudValidatedContextV1",
    "load_validated_cloud_context",
    "main",
]
