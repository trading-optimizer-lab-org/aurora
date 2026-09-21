"""Authenticate the closed source owner for checkpoint recovery.

This is a read-only controller boundary.  It authenticates the protected
profile, the signed source issue, the historical source commit, the existing
fast-gate publication, and the absence of a terminal receipt.  It deliberately
does not import the recovery source or any scientific/runtime module.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Protocol

from cryptography.exceptions import UnsupportedAlgorithm

from .catalog_checkpoint_recovery_owner import (
    CheckpointRecoveryOwnerProofV1,
    verify_checkpoint_failure_owner,
)
from .catalog_checkpoint_recovery_profile import (
    CheckpointRecoveryProfileV1,
    validate_exact_checkpoint_profile,
)
from .catalog_fast_reservation import (
    FastGateOwnerEvidence,
    load_fast_gate_owner,
    load_owner_terminal_receipt,
)
from .catalog_run_request import parse_catalog_run_request


_REPOSITORY = "trading-optimizer-lab-org/aurora"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_CONFIG_BYTES = 256 * 1024


class _ReadOnlyClient(Protocol):
    repository: str

    def get_json(self, path: str) -> tuple[object, object]: ...

    def stable_paginated(self, path: str, *, root: str) -> object: ...


@dataclass(frozen=True)
class CheckpointRecoveryOwnerAuthenticationV1:
    """Authenticated existing owner and proof of the missing terminal only."""

    owner: FastGateOwnerEvidence
    proof: CheckpointRecoveryOwnerProofV1


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"CATALOG_CHECKPOINT_RECOVERY_JSON_NONFINITE:{value}")


def _strict_json_file(path: Path, *, error_code: str) -> object:
    if path.is_symlink() or not path.is_file():
        raise ValueError(error_code)
    try:
        raw = path.read_bytes()
        if not raw or len(raw) > _MAX_CONFIG_BYTES:
            raise ValueError(error_code)
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (OSError, UnicodeError, RecursionError, ValueError) as exc:
        raise ValueError(error_code) from exc


def _mapping(value: object, error_code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(error_code)
    return value


def _repository_root(repo_root: Path) -> Path:
    supplied = Path(repo_root)
    try:
        root = supplied.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ROOT_INVALID") from exc
    if supplied.is_symlink() or not root.is_dir():
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ROOT_INVALID")
    return root


def _safe_repository_file(root: Path, relative: object, *, error_code: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError(error_code)
    candidate = Path(relative)
    if candidate.is_absolute() or "." in candidate.parts or ".." in candidate.parts:
        raise ValueError(error_code)
    target = root / candidate
    try:
        resolved = target.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(error_code) from exc
    if target.is_symlink() or not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(error_code)
    return resolved


def _load_controller_actors(root: Path) -> tuple[tuple[str, ...], bytes]:
    payload = _mapping(
        _strict_json_file(
            root / "config/catalog_controller_actors_v1.json",
            error_code="CATALOG_CHECKPOINT_RECOVERY_ACTOR_CONFIG_INVALID",
        ),
        "CATALOG_CHECKPOINT_RECOVERY_ACTOR_CONFIG_INVALID",
    )
    if payload.get("schema_version") != "1":
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ACTOR_CONFIG_INVALID")
    actors = payload.get("request_actors")
    if (
        not isinstance(actors, list)
        or not actors
        or any(type(actor) is not str or not actor for actor in actors)
        or len(set(actors)) != len(actors)
        or payload.get("required_request_actor_kind") != "non_admin_github_app"
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ACTOR_CONFIG_INVALID")
    key_path = _safe_repository_file(
        root,
        payload.get("requester_public_key_path"),
        error_code="CATALOG_CHECKPOINT_RECOVERY_REQUESTER_KEY_INVALID",
    )
    try:
        public_key = key_path.read_bytes()
    except OSError as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_REQUESTER_KEY_INVALID") from exc
    expected_fingerprint = payload.get("requester_public_key_sha256")
    if not isinstance(expected_fingerprint, str) or not _SHA256.fullmatch(expected_fingerprint):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_REQUESTER_KEY_INVALID")
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        parsed = serialization.load_pem_public_key(public_key)
        if not isinstance(parsed, rsa.RSAPublicKey) or parsed.key_size < 2048:
            raise ValueError("untrusted requester key")
        der = parsed.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    except (OSError, TypeError, UnsupportedAlgorithm, ValueError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_REQUESTER_KEY_INVALID") from exc
    if hashlib.sha256(der).hexdigest() != expected_fingerprint:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_REQUESTER_KEY_INVALID")
    return tuple(actors), public_key


def _profile_attr(profile: object, name: str) -> object:
    try:
        return getattr(profile, name)
    except AttributeError as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_INVALID") from exc


def _read_signed_request(
    client: _ReadOnlyClient,
    root: Path,
    profile: CheckpointRecoveryProfileV1,
) -> object:
    issue_number = _profile_attr(profile, "source_issue_number")
    if type(issue_number) is not int or issue_number < 1:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_INVALID")
    issue_raw, _ = client.get_json(f"/repos/{_REPOSITORY}/issues/{issue_number}")
    issue = _mapping(issue_raw, "CATALOG_CHECKPOINT_RECOVERY_SOURCE_ISSUE_INVALID")
    actors, public_key = _load_controller_actors(root)
    user = _mapping(issue.get("user"), "CATALOG_CHECKPOINT_RECOVERY_SOURCE_ISSUE_INVALID")
    actor = user.get("login")
    if issue.get("number") != issue_number or actor not in actors:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_REQUESTER_INVALID")
    title, body = issue.get("title"), issue.get("body")
    if not isinstance(title, str) or not isinstance(body, str):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_ISSUE_INVALID")
    try:
        request = parse_catalog_run_request(title, body, public_key)
    except (TypeError, ValueError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_REQUEST_INVALID") from exc
    try:
        request_sha256 = request.request_sha256
        campaign_key = request.campaign_key
        launch_generation = request.launch_generation
        expected_request_sha256 = _profile_attr(profile, "source_request_sha256")
        expected_campaign_key = _profile_attr(profile, "campaign_key")
        expected_generation = _profile_attr(profile, "source_generation")
    except AttributeError as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_REQUEST_INVALID") from exc
    if request_sha256 != expected_request_sha256 or campaign_key != expected_campaign_key:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_REQUEST_MISMATCH")
    if launch_generation != expected_generation:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_GENERATION_INVALID")
    return request


def _historical_owner_commit_approved(
    client: _ReadOnlyClient, candidate: str, protected: str
) -> bool:
    """Approve only a source commit that is an ancestor of protected HEAD."""

    if not _COMMIT.fullmatch(candidate) or not _COMMIT.fullmatch(protected):
        return False
    comparison, _ = client.get_json(f"/repos/{_REPOSITORY}/compare/{candidate}...{protected}")
    return (
        isinstance(comparison, Mapping)
        and comparison.get("status") in {"ahead", "identical"}
        and isinstance(comparison.get("base_commit"), Mapping)
        and isinstance(comparison.get("merge_base_commit"), Mapping)
        and comparison["base_commit"].get("sha") == candidate
        and comparison["merge_base_commit"].get("sha") == candidate
    )


def authenticate_checkpoint_recovery_owner(
    *,
    repo_root: Path,
    repository: str,
    protected_commit_sha: str,
    profile: CheckpointRecoveryProfileV1,
    fetch_json: _ReadOnlyClient,
    download_artifact: Callable[[int], bytes],
    checkpoint_control_jobs: bool = False,
) -> CheckpointRecoveryOwnerAuthenticationV1:
    """Authenticate the source owner without publishing or mutating anything.

    ``fetch_json`` is the existing read-only GitHub client; its ``get_json`` and
    ``stable_paginated`` methods are used.  The injected artifact reader is
    likewise GET-only and receives an artifact id.  The protected profile is
    revalidated against the repository config before any source evidence is
    accepted.
    """

    root = _repository_root(repo_root)
    if (
        type(repository) is not str
        or repository != _REPOSITORY
        or type(protected_commit_sha) is not str
        or _COMMIT.fullmatch(protected_commit_sha) is None
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_AUTH_IDENTITY_INVALID")
    source_repository = getattr(fetch_json, "repository", None)
    if (
        source_repository != repository
        or not callable(getattr(fetch_json, "get_json", None))
        or not callable(getattr(fetch_json, "stable_paginated", None))
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_AUTH_IDENTITY_INVALID")
    if not callable(download_artifact):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_READER_INVALID")

    protected = validate_exact_checkpoint_profile(root, profile)
    client = fetch_json
    request = _read_signed_request(client, root, protected)
    owner = load_fast_gate_owner(
        client=client,
        issue_number=protected.source_issue_number,
        request=request,
        approved_commits=frozenset({protected_commit_sha}),
        approve_historical_commit=lambda candidate: _historical_owner_commit_approved(
            client, candidate, protected_commit_sha
        ),
        download_archive=download_artifact,
        terminal_owner_run_id=protected.source_run_id,
        pinned_owner_run_id=protected.source_run_id,
        checkpoint_control_jobs=checkpoint_control_jobs,
    )
    if not isinstance(owner, FastGateOwnerEvidence):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_OWNER_MISSING")
    terminal = load_owner_terminal_receipt(
        client=client,
        owner=owner,
        issue_number=protected.source_issue_number,
        download_archive=download_artifact,
    )
    if terminal is not None:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_TERMINAL_PRESENT")
    proof = verify_checkpoint_failure_owner(
        profile=protected,
        owner=owner,
        terminal=terminal,
    )
    return CheckpointRecoveryOwnerAuthenticationV1(owner=owner, proof=proof)


__all__ = [
    "CheckpointRecoveryOwnerAuthenticationV1",
    "authenticate_checkpoint_recovery_owner",
]
