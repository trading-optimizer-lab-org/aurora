"""Authenticate the closed source owner for checkpoint recovery.

This is a read-only controller boundary.  It authenticates the protected
profile, the signed source issue, the historical source commit, the existing
fast-gate publication, and the profile's exact terminal state.  It deliberately
does not import the recovery source or any scientific/runtime module.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Protocol

from cryptography.exceptions import UnsupportedAlgorithm

from .catalog_checkpoint_recovery_owner import (
    CheckpointRecoveryOwnerProofV1,
    verify_checkpoint_failure_owner,
)
from .catalog_checkpoint_recovery_profile import (
    CHECKPOINT_RECOVERY_SOURCE8_EXPECTED_RESULT_COUNT,
    CheckpointRecoveryProfileV1,
    validate_exact_checkpoint_profile,
)
from .catalog_fast_reservation import (
    FastGateOwnerEvidence,
    bind_owner_terminal_receipt,
    is_fast_controller_issue_run,
    load_fast_gate_owner,
    load_owner_terminal_receipt,
)
from .catalog_run_request import parse_catalog_run_request
from .catalog_request_contract import CatalogRunRequestV1
from .catalog_fast_path import (
    CatalogTerminalReceipt,
    CatalogTerminalReceiptV1,
    CatalogTerminalReceiptV2,
)

if TYPE_CHECKING:
    from .catalog_reduction_recovery_profile import RecoveryPredecessorBindings


_REPOSITORY = "trading-optimizer-lab-org/aurora"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_CONFIG_BYTES = 256 * 1024
_RUN_IDENTITY_KEYS = (
    "id",
    "run_attempt",
    "head_sha",
    "head_branch",
    "status",
    "conclusion",
    "path",
    "repository",
)
_PREDECESSOR_EVALUATION_JOB_NAMES = frozenset(
    {"engine / evaluate_a", "engine / evaluate_b", "engine / evaluate_c"}
)


class _ReadOnlyClient(Protocol):
    repository: str

    def get_json(self, path: str) -> tuple[object, object]: ...

    def stable_paginated(self, path: str, *, root: str) -> object: ...


@dataclass(frozen=True)
class CheckpointRecoveryPredecessorAuthenticationV1:
    """Authenticated target-10 predecessor owner and terminal receipt."""

    owner: FastGateOwnerEvidence
    terminal: CatalogTerminalReceipt


@dataclass(frozen=True)
class CheckpointRecoveryOwnerAuthenticationV1:
    """Authenticated existing owner, closed failure proof and original terminal."""

    owner: FastGateOwnerEvidence
    proof: CheckpointRecoveryOwnerProofV1
    terminal: CatalogTerminalReceipt | None = None
    predecessor: CheckpointRecoveryPredecessorAuthenticationV1 | None = None


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
    return _read_signed_request_for_identity(
        client=client,
        root=root,
        issue_number=_profile_attr(profile, "source_issue_number"),
        expected_request_sha256=_profile_attr(profile, "source_request_sha256"),
        expected_campaign_key=_profile_attr(profile, "campaign_key"),
        expected_generation=_profile_attr(profile, "source_generation"),
    )


def _read_signed_request_for_identity(
    *,
    client: _ReadOnlyClient,
    root: Path,
    issue_number: object,
    expected_request_sha256: object,
    expected_campaign_key: object,
    expected_generation: object,
) -> CatalogRunRequestV1:
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
    except AttributeError as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_REQUEST_INVALID") from exc
    if request_sha256 != expected_request_sha256 or campaign_key != expected_campaign_key:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_REQUEST_MISMATCH")
    if launch_generation != expected_generation:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_SOURCE_GENERATION_INVALID")
    return request


def _predecessor_bindings(
    profile: CheckpointRecoveryProfileV1,
) -> RecoveryPredecessorBindings:
    if profile.target_generation != 10:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PREDECESSOR_AUTH_INVALID")
    predecessor = profile.predecessor_bindings
    if predecessor is None or profile.target_generation != predecessor.generation + 1:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PREDECESSOR_AUTH_INVALID")
    return predecessor


def _validate_predecessor_request(
    *, profile: CheckpointRecoveryProfileV1, request: CatalogRunRequestV1
) -> RecoveryPredecessorBindings:
    code = "CATALOG_CHECKPOINT_RECOVERY_PREDECESSOR_AUTH_INVALID"
    try:
        predecessor = _predecessor_bindings(profile)
        if (
            request.request_sha256 != predecessor.request_sha256
            or request.campaign_key != profile.campaign_key
            or request.launch_generation != predecessor.generation
            or request.previous_terminal_request_sha256 != profile.source_request_sha256
        ):
            raise ValueError(code)
        return predecessor
    except (AttributeError, TypeError, ValueError) as exc:
        if str(exc) == code:
            raise
        raise ValueError(code) from exc


def _validate_predecessor_owner_terminal(
    *,
    profile: CheckpointRecoveryProfileV1,
    owner: FastGateOwnerEvidence,
    terminal: CatalogTerminalReceipt | None,
) -> RecoveryPredecessorBindings:
    code = "CATALOG_CHECKPOINT_RECOVERY_PREDECESSOR_AUTH_INVALID"
    try:
        predecessor = _predecessor_bindings(profile)
        if not isinstance(owner, FastGateOwnerEvidence):
            raise ValueError(code)
        if terminal is None or not isinstance(
            terminal, (CatalogTerminalReceiptV1, CatalogTerminalReceiptV2)
        ):
            raise ValueError(code)
        if (
            owner.unlaunched_terminal
            or owner.run_id != predecessor.run_id
            or owner.run.get("id") != predecessor.run_id
            or owner.run.get("run_attempt") != predecessor.run_attempt
            or owner.run.get("head_sha") != predecessor.protected_commit_sha
            or owner.run.get("head_branch") != "main"
            or owner.run.get("status") != "completed"
            or owner.run.get("conclusion") != "failure"
            or not is_fast_controller_issue_run(owner.run)
            or not isinstance(owner.run.get("repository"), Mapping)
            or owner.run["repository"].get("full_name") != _REPOSITORY
            or owner.decision.launch_required is not True
            or owner.decision.existing_run_id is not None
            or owner.decision.request_sha256 != predecessor.request_sha256
            or owner.decision.campaign_key != profile.campaign_key
            or (
                predecessor.decision_sha256 is not None
                and owner.decision.decision_sha256 != predecessor.decision_sha256
            )
            or terminal.receipt_sha256 != predecessor.terminal_receipt_sha256
            or terminal.request_sha256 != predecessor.request_sha256
            or terminal.campaign_key != profile.campaign_key
            or terminal.state != "BLOCKED"
            or terminal.reason_code != "CATALOG_REDUCTION_FAILED"
            or terminal.expected_recipe_count != CHECKPOINT_RECOVERY_SOURCE8_EXPECTED_RESULT_COUNT
            or terminal.observed_recipe_count != 0
            or terminal.result_science_sha256 is not None
        ):
            raise ValueError(code)
        bind_owner_terminal_receipt(owner=owner, receipt=terminal)
        return predecessor
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        if str(exc) == code:
            raise
        raise ValueError(code) from exc


def validate_checkpoint_recovery_predecessor_auth(
    *,
    profile: CheckpointRecoveryProfileV1,
    authenticated: CheckpointRecoveryPredecessorAuthenticationV1,
) -> None:
    """Validate cached predecessor identity without any remote reads."""

    if not isinstance(authenticated, CheckpointRecoveryPredecessorAuthenticationV1):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PREDECESSOR_AUTH_INVALID")
    _validate_predecessor_owner_terminal(
        profile=profile, owner=authenticated.owner, terminal=authenticated.terminal
    )


def _validate_predecessor_evaluation_jobs(
    jobs: tuple[Mapping[str, Any], ...], *, error_code: str
) -> None:
    """Require the explicit zero-evaluation placeholders in a full inventory.

    The checkpoint-control path intentionally returns only the ``gate`` and
    ``finalize`` jobs.  It must not claim that evaluation jobs were inspected;
    callers that request the full Actions inventory get this stricter,
    positive-presence check instead.
    """

    observed: dict[str, Mapping[str, Any]] = {}
    for job in jobs:
        if not isinstance(job, Mapping):
            raise ValueError(error_code)
        name = job.get("name")
        if name in _PREDECESSOR_EVALUATION_JOB_NAMES:
            if name in observed:
                raise ValueError(error_code)
            observed[name] = job
    if set(observed) != _PREDECESSOR_EVALUATION_JOB_NAMES:
        raise ValueError(error_code)
    if any(
        job.get("status") != "completed" or job.get("conclusion") != "skipped"
        for job in observed.values()
    ):
        raise ValueError(error_code)


def authenticate_checkpoint_recovery_predecessor(
    *,
    repo_root: Path,
    repository: str,
    protected_commit_sha: str,
    profile: CheckpointRecoveryProfileV1,
    fetch_json: _ReadOnlyClient,
    download_artifact: Callable[[int], bytes],
    checkpoint_control_jobs: bool = True,
) -> CheckpointRecoveryPredecessorAuthenticationV1:
    """Authenticate target-10's immediate terminal owner independently."""

    code = "CATALOG_CHECKPOINT_RECOVERY_PREDECESSOR_AUTH_INVALID"
    try:
        root = _repository_root(repo_root)
        if (
            type(repository) is not str
            or repository != _REPOSITORY
            or type(protected_commit_sha) is not str
            or _COMMIT.fullmatch(protected_commit_sha) is None
            or getattr(fetch_json, "repository", None) != repository
            or not callable(getattr(fetch_json, "get_json", None))
            or not callable(getattr(fetch_json, "stable_paginated", None))
            or not callable(download_artifact)
            or type(checkpoint_control_jobs) is not bool
        ):
            raise ValueError(code)
        protected = validate_exact_checkpoint_profile(root, profile)
        if protected.target_generation != 10:
            raise ValueError(code)
        predecessor = _predecessor_bindings(protected)
        request = _read_signed_request_for_identity(
            client=fetch_json,
            root=root,
            issue_number=predecessor.issue_number,
            expected_request_sha256=predecessor.request_sha256,
            expected_campaign_key=protected.campaign_key,
            expected_generation=predecessor.generation,
        )
        _validate_predecessor_request(profile=protected, request=request)
        owner = load_fast_gate_owner(
            client=fetch_json,
            issue_number=predecessor.issue_number,
            request=request,
            approved_commits=frozenset({protected_commit_sha}),
            approve_historical_commit=lambda candidate: (
                candidate == predecessor.protected_commit_sha
                and _historical_owner_commit_approved(
                    fetch_json, candidate, protected_commit_sha
                )
            ),
            download_archive=download_artifact,
            terminal_owner_run_id=predecessor.run_id,
            pinned_owner_run_id=predecessor.run_id,
            checkpoint_control_jobs=checkpoint_control_jobs,
        )
        if not isinstance(owner, FastGateOwnerEvidence) or owner.unlaunched_terminal:
            raise ValueError(code)
        terminal = load_owner_terminal_receipt(
            client=fetch_json,
            owner=owner,
            issue_number=predecessor.issue_number,
            download_archive=download_artifact,
        )
        if terminal is None:
            raise ValueError(code)
        _validate_predecessor_owner_terminal(
            profile=protected, owner=owner, terminal=terminal
        )
        if not checkpoint_control_jobs:
            _validate_predecessor_evaluation_jobs(owner.jobs, error_code=code)
        return CheckpointRecoveryPredecessorAuthenticationV1(
            owner=owner, terminal=terminal
        )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        if str(exc) == code:
            raise
        raise ValueError(code) from exc


def revalidate_checkpoint_recovery_predecessor(
    *,
    repo_root: Path,
    repository: str,
    protected_commit_sha: str,
    profile: CheckpointRecoveryProfileV1,
    cached: CheckpointRecoveryPredecessorAuthenticationV1,
    fetch_json: _ReadOnlyClient,
    download_artifact: Callable[[int], bytes],
) -> CheckpointRecoveryPredecessorAuthenticationV1:
    """Recheck cached predecessor identity without repeating source ownership.

    The admission handoff has already authenticated the predecessor's gate
    artifact, job inventory, and historical commit.  The handoff consumer only
    rereads the signed request, the mutable owner run before and after the
    terminal artifact, and that terminal artifact itself.  This preserves the
    source authentication boundary while avoiding a second full predecessor
    authentication in the same gate job.
    """

    code = "CATALOG_CHECKPOINT_RECOVERY_PREDECESSOR_AUTH_INVALID"
    try:
        root = _repository_root(repo_root)
        if (
            type(repository) is not str
            or repository != _REPOSITORY
            or type(protected_commit_sha) is not str
            or _COMMIT.fullmatch(protected_commit_sha) is None
            or getattr(fetch_json, "repository", None) != repository
            or not callable(getattr(fetch_json, "get_json", None))
            or not callable(getattr(fetch_json, "stable_paginated", None))
            or not callable(download_artifact)
        ):
            raise ValueError(code)
        protected = validate_exact_checkpoint_profile(root, profile)
        if protected.target_generation != 10:
            raise ValueError(code)
        validate_checkpoint_recovery_predecessor_auth(
            profile=protected, authenticated=cached
        )
        predecessor = _predecessor_bindings(protected)
        request = _read_signed_request_for_identity(
            client=fetch_json,
            root=root,
            issue_number=predecessor.issue_number,
            expected_request_sha256=predecessor.request_sha256,
            expected_campaign_key=protected.campaign_key,
            expected_generation=predecessor.generation,
        )
        _validate_predecessor_request(profile=protected, request=request)

        path = f"/repos/{_REPOSITORY}/actions/runs/{predecessor.run_id}"
        run, _ = fetch_json.get_json(path)
        if not isinstance(run, dict) or any(
            run.get(key) != cached.owner.run.get(key) for key in _RUN_IDENTITY_KEYS
        ):
            raise ValueError(code)
        owner = FastGateOwnerEvidence(
            cached.owner.run_id, run, cached.owner.decision, cached.owner.jobs
        )
        terminal = load_owner_terminal_receipt(
            client=fetch_json,
            owner=owner,
            issue_number=predecessor.issue_number,
            download_archive=download_artifact,
        )
        if terminal is None:
            raise ValueError(code)
        if terminal != cached.terminal:
            raise ValueError(code)
        _validate_predecessor_owner_terminal(
            profile=protected, owner=owner, terminal=terminal
        )
        after, _ = fetch_json.get_json(path)
        if not isinstance(after, dict) or any(
            after.get(key) != run.get(key) for key in _RUN_IDENTITY_KEYS
        ):
            raise ValueError(code)
        return CheckpointRecoveryPredecessorAuthenticationV1(
            owner=owner, terminal=terminal
        )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        if str(exc) == code:
            raise
        raise ValueError(code) from exc


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
    if terminal is not None and protected.target_generation not in {9, 10}:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_TERMINAL_PRESENT")
    proof = verify_checkpoint_failure_owner(
        profile=protected,
        owner=owner,
        terminal=terminal,
    )
    predecessor = None
    if protected.target_generation == 10:
        predecessor = authenticate_checkpoint_recovery_predecessor(
            repo_root=root,
            repository=repository,
            protected_commit_sha=protected_commit_sha,
            profile=protected,
            fetch_json=client,
            download_artifact=download_artifact,
            checkpoint_control_jobs=checkpoint_control_jobs,
        )
    return CheckpointRecoveryOwnerAuthenticationV1(
        owner=owner, proof=proof, terminal=terminal, predecessor=predecessor
    )


__all__ = [
    "CheckpointRecoveryOwnerAuthenticationV1",
    "CheckpointRecoveryPredecessorAuthenticationV1",
    "authenticate_checkpoint_recovery_owner",
    "authenticate_checkpoint_recovery_predecessor",
    "revalidate_checkpoint_recovery_predecessor",
    "validate_checkpoint_recovery_predecessor_auth",
]
