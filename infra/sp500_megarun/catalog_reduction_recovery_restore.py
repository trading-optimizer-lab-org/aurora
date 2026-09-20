"""Restore one authenticated, immutable catalog reduction source.

This reader is deliberately narrower than admission.  It authenticates the
already-published predecessor and its terminal failure, downloads only the
artifacts named by the sealed recovery profile, validates the historical
source, and publishes the extracted files once.  It never evaluates science,
launches workers, mutates GitHub, or imports admission/authority runtime
modules.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
from typing import Any, Protocol
import zipfile

from aurora.infra.sp500_megarun.catalog_fast_reservation import (
    load_fast_gate_owner,
    load_owner_terminal_receipt,
    read_owner_artifact_archive,
)
from aurora.infra.sp500_megarun.catalog_github_snapshot import CatalogGitHubReadOnlyClient
from aurora.infra.sp500_megarun.catalog_reduction_recovery_profile import (
    read_sealed_reduction_recovery_profile,
)
from aurora.infra.sp500_megarun.catalog_reduction_recovery_source import (
    verify_reduction_recovery_source,
)
from aurora.infra.sp500_megarun.catalog_run_request import parse_catalog_run_request


_REPOSITORY = "trading-optimizer-lab-org/aurora"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
_MAX_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 4096
_MAX_COMPRESSION_RATIO = 1000


class _ReadOnlyClient(Protocol):
    repository: str

    def get_json(self, path: str) -> tuple[object, object]: ...

    def stable_paginated(self, path: str, *, root: str) -> object: ...


@dataclass(frozen=True)
class ReductionRecoveryRestoreResult:
    """Evidence returned after the restored directory was published."""

    output_dir: Path
    profile_sha256: str
    owner_run_id: int
    terminal_receipt_sha256: str
    source_plan_receipt_sha256: str
    group_receipt_sha256s: tuple[str, ...]


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("CATALOG_RECOVERY_JSON_DUPLICATE_KEY")
        value[key] = item
    return value


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"CATALOG_RECOVERY_JSON_NONFINITE:{value}")


def _strict_json(raw: bytes, *, error_code: str) -> object:
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError(error_code) from exc


def _strict_json_file(path: Path, *, error_code: str, maximum_bytes: int = 256 * 1024) -> object:
    if path.is_symlink() or not path.is_file():
        raise ValueError(error_code)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(error_code) from exc
    if not raw or len(raw) > maximum_bytes:
        raise ValueError(error_code)
    return _strict_json(raw, error_code=error_code)


def _mapping(value: object, error_code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(error_code)
    return value


def _safe_repository_file(root: Path, relative: object, *, error_code: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError(error_code)
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or "." in candidate.parts:
        raise ValueError(error_code)
    target = root / candidate
    try:
        resolved = target.resolve(strict=True)
    except OSError as exc:
        raise ValueError(error_code) from exc
    if target.is_symlink() or not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(error_code)
    return resolved


def _load_controller_actors(root: Path) -> tuple[tuple[str, ...], bytes]:
    payload = _mapping(
        _strict_json_file(
            root / "config/catalog_controller_actors_v1.json",
            error_code="CATALOG_RECOVERY_ACTOR_CONFIG_INVALID",
        ),
        "CATALOG_RECOVERY_ACTOR_CONFIG_INVALID",
    )
    if payload.get("schema_version") != "1":
        raise ValueError("CATALOG_RECOVERY_ACTOR_CONFIG_INVALID")
    actors = payload.get("request_actors")
    if (
        not isinstance(actors, list)
        or not actors
        or any(type(actor) is not str or not actor for actor in actors)
        or len(set(actors)) != len(actors)
        or payload.get("required_request_actor_kind") != "non_admin_github_app"
    ):
        raise ValueError("CATALOG_RECOVERY_ACTOR_CONFIG_INVALID")
    key_path = _safe_repository_file(
        root,
        payload.get("requester_public_key_path"),
        error_code="CATALOG_RECOVERY_REQUESTER_KEY_INVALID",
    )
    try:
        public_key = key_path.read_bytes()
    except OSError as exc:
        raise ValueError("CATALOG_RECOVERY_REQUESTER_KEY_INVALID") from exc
    expected_fingerprint = payload.get("requester_public_key_sha256")
    if not isinstance(expected_fingerprint, str) or not _SHA256.fullmatch(expected_fingerprint):
        raise ValueError("CATALOG_RECOVERY_REQUESTER_KEY_INVALID")
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        parsed = serialization.load_pem_public_key(public_key)
        if not isinstance(parsed, rsa.RSAPublicKey) or parsed.key_size < 2048:
            raise ValueError("untrusted key")
        der = parsed.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        # The actor catalog binds the DER fingerprint, which is also what
        # parse_catalog_run_request authenticates.
    except (TypeError, ValueError, OSError) as exc:
        raise ValueError("CATALOG_RECOVERY_REQUESTER_KEY_INVALID") from exc
    if hashlib.sha256(der).hexdigest() != expected_fingerprint:
        raise ValueError("CATALOG_RECOVERY_REQUESTER_KEY_INVALID")
    return tuple(actors), public_key


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


def _download_owner_archive(repository: str, token: str, artifact_id: int) -> bytes:
    """Download one bounded ZIP through ``gh`` without exposing the token."""

    if repository != _REPOSITORY or not token or type(artifact_id) is not int or artifact_id < 1:
        raise ValueError("CATALOG_RECOVERY_ARTIFACT_DOWNLOAD_INVALID")
    with tempfile.TemporaryFile() as stream:
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{repository}/actions/artifacts/{artifact_id}/zip"],
                stdout=stream,
                stderr=subprocess.PIPE,
                env={**os.environ, "GH_TOKEN": token},
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("CATALOG_RECOVERY_ARTIFACT_DOWNLOAD_FAILED") from exc
        if result.returncode != 0:
            raise ValueError("CATALOG_RECOVERY_ARTIFACT_DOWNLOAD_FAILED")
        stream.seek(0)
        raw = stream.read(_MAX_ARCHIVE_BYTES + 1)
    if not raw or len(raw) > _MAX_ARCHIVE_BYTES:
        raise ValueError("CATALOG_RECOVERY_ARTIFACT_ARCHIVE_SIZE_INVALID")
    return raw


def _profile_attr(profile: Any, name: str, error_code: str) -> Any:
    try:
        value = getattr(profile, name)
    except AttributeError as exc:
        raise ValueError(error_code) from exc
    return value


def _profile_artifact_metadata(metadata: Mapping[str, Any], artifact: Any) -> None:
    expected = {
        "id": _profile_attr(artifact, "artifact_id", "CATALOG_RECOVERY_PROFILE_INVALID"),
        "name": _profile_attr(artifact, "artifact_name", "CATALOG_RECOVERY_PROFILE_INVALID"),
        "digest": _profile_attr(artifact, "digest", "CATALOG_RECOVERY_PROFILE_INVALID"),
        "size_in_bytes": _profile_attr(
            artifact, "size_bytes", "CATALOG_RECOVERY_PROFILE_INVALID"
        ),
    }
    expected_job = _profile_attr(
        artifact, "publisher_job_name", "CATALOG_RECOVERY_PROFILE_INVALID"
    )
    expected_step = _profile_attr(
        artifact, "publish_step_name", "CATALOG_RECOVERY_PROFILE_INVALID"
    )
    expected_receipt = _profile_attr(
        artifact, "receipt_sha256", "CATALOG_RECOVERY_PROFILE_INVALID"
    )
    if (
        not isinstance(metadata, Mapping)
        or type(expected["id"]) is not int
        or not _ARTIFACT_DIGEST.fullmatch(str(expected["digest"]))
        or any(metadata.get(key) != value for key, value in expected.items())
        or metadata.get("publisher_job_name", expected_job) != expected_job
        or metadata.get("publish_step_name", expected_step) != expected_step
        or (
            "receipt_sha256" in metadata
            and metadata.get("receipt_sha256") != expected_receipt
        )
    ):
        raise ValueError("CATALOG_RECOVERY_ARTIFACT_PROFILE_MISMATCH")


def _archive_member_name(member: zipfile.ZipInfo) -> tuple[str, bool]:
    name = member.filename
    if (
        not isinstance(name, str)
        or not name
        or "\x00" in name
        or "\\" in name
        or name.startswith("/")
        or re.match(r"^[A-Za-z]:", name) is not None
    ):
        raise ValueError("CATALOG_RECOVERY_ARCHIVE_PATH_INVALID")
    directory = name.endswith("/")
    normalized = name[:-1] if directory else name
    path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("CATALOG_RECOVERY_ARCHIVE_PATH_INVALID")
    mode = (member.external_attr >> 16) & 0o170000
    if directory:
        if mode not in {0, 0o040000}:
            raise ValueError("CATALOG_RECOVERY_ARCHIVE_SYMLINK_INVALID")
    elif mode not in {0, 0o100000}:
        raise ValueError("CATALOG_RECOVERY_ARCHIVE_SYMLINK_INVALID")
    if member.flag_bits & 0x1:
        raise ValueError("CATALOG_RECOVERY_ARCHIVE_ENCRYPTED")
    if not directory and (member.file_size <= 0 or member.file_size > _MAX_MEMBER_BYTES):
        raise ValueError("CATALOG_RECOVERY_ARCHIVE_MEMBER_SIZE_INVALID")
    return path.as_posix(), directory


def _safe_extract_archive(raw: bytes, destination: Path) -> None:
    """Extract a bounded flat artifact without following archive-controlled links."""

    if not raw or len(raw) > _MAX_ARCHIVE_BYTES:
        raise ValueError("CATALOG_RECOVERY_ARCHIVE_SIZE_INVALID")
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError("CATALOG_RECOVERY_EXTRACTION_TARGET_INVALID")
    destination.mkdir(parents=True, exist_ok=False)
    root = destination.resolve(strict=True)
    seen: set[str] = set()
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if not members or len(members) > _MAX_ARCHIVE_MEMBERS:
                raise ValueError("CATALOG_RECOVERY_ARCHIVE_MEMBER_COUNT_INVALID")
            for member in members:
                name, directory = _archive_member_name(member)
                folded = name.casefold()
                if folded in seen:
                    raise ValueError("CATALOG_RECOVERY_ARCHIVE_DUPLICATE")
                seen.add(folded)
                if (
                    not directory
                    and (
                        not member.compress_size
                        or member.file_size / member.compress_size > _MAX_COMPRESSION_RATIO
                    )
                ):
                    raise ValueError("CATALOG_RECOVERY_ARCHIVE_RATIO_INVALID")
                total += member.file_size
                if total > _MAX_TOTAL_UNCOMPRESSED_BYTES:
                    raise ValueError("CATALOG_RECOVERY_ARCHIVE_TOTAL_SIZE_INVALID")
                target = destination / Path(*PurePosixPath(name).parts)
                if not target.resolve(strict=False).is_relative_to(root):
                    raise ValueError("CATALOG_RECOVERY_ARCHIVE_PATH_INVALID")
                if directory:
                    _ensure_archive_directory(target, root)
                    continue
                _ensure_archive_directory(target.parent, root)
                written = 0
                with archive.open(member, "r") as source, target.open("xb") as sink:
                    while True:
                        chunk = source.read(min(1024 * 1024, member.file_size - written + 1))
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > member.file_size:
                            raise ValueError("CATALOG_RECOVERY_ARCHIVE_MEMBER_SIZE_INVALID")
                        sink.write(chunk)
                if written != member.file_size or target.stat().st_size != member.file_size:
                    raise ValueError("CATALOG_RECOVERY_ARCHIVE_MEMBER_SIZE_INVALID")
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("CATALOG_"):
            raise
        raise ValueError("CATALOG_RECOVERY_ARCHIVE_INVALID") from exc


def _ensure_archive_directory(path: Path, root: Path) -> None:
    """Create missing archive parents while rejecting links and files."""

    try:
        relative = path.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ValueError("CATALOG_RECOVERY_ARCHIVE_PATH_INVALID") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink() or not current.is_dir():
                raise ValueError("CATALOG_RECOVERY_ARCHIVE_PARENT_INVALID")
        else:
            current.mkdir()


def _read_signed_request(
    client: _ReadOnlyClient,
    root: Path,
    profile: Any,
    parse_request: Callable[..., Any],
) -> Any:
    issue_number = _profile_attr(profile, "source_issue_number", "CATALOG_RECOVERY_PROFILE_INVALID")
    if type(issue_number) is not int or issue_number < 1:
        raise ValueError("CATALOG_RECOVERY_PROFILE_INVALID")
    issue_raw, _ = client.get_json(f"/repos/{_REPOSITORY}/issues/{issue_number}")
    issue = _mapping(issue_raw, "CATALOG_RECOVERY_SOURCE_ISSUE_INVALID")
    actors, public_key = _load_controller_actors(root)
    user = _mapping(issue.get("user"), "CATALOG_RECOVERY_SOURCE_ISSUE_INVALID")
    actor = user.get("login")
    if issue.get("number") != issue_number or actor not in actors:
        raise ValueError("CATALOG_RECOVERY_SOURCE_REQUESTER_INVALID")
    title, body = issue.get("title"), issue.get("body")
    if not isinstance(title, str) or not isinstance(body, str):
        raise ValueError("CATALOG_RECOVERY_SOURCE_ISSUE_INVALID")
    try:
        request = parse_request(title, body, public_key)
    except (TypeError, ValueError) as exc:
        raise ValueError("CATALOG_RECOVERY_SOURCE_REQUEST_INVALID") from exc
    expected_request_sha = _profile_attr(
        profile, "source_request_sha256", "CATALOG_RECOVERY_PROFILE_INVALID"
    )
    expected_campaign = _profile_attr(profile, "campaign_key", "CATALOG_RECOVERY_PROFILE_INVALID")
    if request.request_sha256 != expected_request_sha or request.campaign_key != expected_campaign:
        raise ValueError("CATALOG_RECOVERY_SOURCE_REQUEST_MISMATCH")
    if request.launch_generation != profile.source_generation:
        raise ValueError("CATALOG_RECOVERY_SOURCE_GENERATION_INVALID")
    return request


def _require_owner_and_terminal(owner: Any, terminal: Any, profile: Any, request: Any) -> None:
    if owner is None or not hasattr(owner, "run_id") or not hasattr(owner, "decision"):
        raise ValueError("CATALOG_RECOVERY_OWNER_INVALID")
    source_run_id = _profile_attr(profile, "source_run_id", "CATALOG_RECOVERY_PROFILE_INVALID")
    source_attempt = _profile_attr(
        profile, "source_run_attempt", "CATALOG_RECOVERY_PROFILE_INVALID"
    )
    if owner.run_id != source_run_id or not isinstance(owner.run, Mapping):
        raise ValueError("CATALOG_RECOVERY_OWNER_MISMATCH")
    if owner.run.get("run_attempt") != source_attempt:
        raise ValueError("CATALOG_RECOVERY_OWNER_ATTEMPT_MISMATCH")
    bindings = _mapping(
        _profile_attr(profile, "source_plan_bindings", "CATALOG_RECOVERY_PROFILE_INVALID"),
        "CATALOG_RECOVERY_PROFILE_INVALID",
    )
    if (
        owner.run.get("head_sha") != bindings.get("protected_commit_sha")
        or owner.decision.request_sha256 != request.request_sha256
        or owner.decision.decision_sha256 != bindings.get("decision_sha256")
        or owner.decision.campaign_key != profile.campaign_key
    ):
        raise ValueError("CATALOG_RECOVERY_OWNER_MISMATCH")
    if terminal is None:
        raise ValueError("CATALOG_RECOVERY_TERMINAL_MISSING")
    expected_receipt = _profile_attr(
        profile, "source_terminal_receipt_sha256", "CATALOG_RECOVERY_PROFILE_INVALID"
    )
    if (
        terminal.state != "BLOCKED"
        or terminal.reason_code != profile.terminal_reason_code
        or terminal.receipt_sha256 != expected_receipt
        or terminal.request_sha256 != request.request_sha256
        or terminal.campaign_key != profile.campaign_key
        or (profile.source_generation == 10 and (
            terminal.observed_recipe_count != 0
            or terminal.result_science_sha256 is not None
        ))
    ):
        raise ValueError("CATALOG_RECOVERY_TERMINAL_MISMATCH")


def _publish_staging(staging: Path, output_dir: Path) -> None:
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("CATALOG_RECOVERY_OUTPUT_EXISTS")
    os.replace(staging, output_dir)


def restore_catalog_reduction_recovery(
    *,
    repo_root: Path,
    sealed_plan: Path,
    output_dir: Path,
    client: _ReadOnlyClient | None = None,
    download_archive: Callable[[int], bytes] | None = None,
) -> ReductionRecoveryRestoreResult:
    """Authenticate and atomically restore the protected historical source."""

    token = os.environ.get("GH_TOKEN", "")
    protected_commit = os.environ.get("CATALOG_PROTECTED_COMMIT_SHA", "")
    repository = os.environ.get("GITHUB_REPOSITORY", _REPOSITORY)
    if repository != _REPOSITORY or not token or not _COMMIT.fullmatch(protected_commit):
        raise ValueError("CATALOG_RECOVERY_INVOCATION_INVALID")
    root = Path(repo_root).resolve(strict=True)
    sealed = Path(sealed_plan).resolve(strict=True)
    target = Path(output_dir).resolve(strict=False)
    if (
        Path(repo_root).is_symlink()
        or not root.is_dir()
        or Path(sealed_plan).is_symlink()
        or not sealed.is_dir()
        or target.exists()
        or target.is_symlink()
        or not target.parent.is_dir()
        or target == sealed
        or target.is_relative_to(sealed)
    ):
        raise ValueError("CATALOG_RECOVERY_PATH_INVALID")

    profile = read_sealed_reduction_recovery_profile(
        root,
        sealed,
        expected_bindings={"protected_commit_sha": protected_commit},
    )
    if profile is None:
        raise ValueError("CATALOG_RECOVERY_PROFILE_REQUIRED")
    if client is None:
        client = CatalogGitHubReadOnlyClient(repository, token)
    if client.repository != _REPOSITORY:
        raise ValueError("CATALOG_RECOVERY_REPOSITORY_INVALID")
    downloader = download_archive or (lambda artifact_id: _download_owner_archive(repository, token, artifact_id))
    request = _read_signed_request(client, root, profile, parse_catalog_run_request)
    owner = load_fast_gate_owner(
        client=client,
        issue_number=profile.source_issue_number,
        request=request,
        approved_commits=frozenset({protected_commit}),
        approve_historical_commit=lambda candidate: _historical_owner_commit_approved(
            client, candidate, protected_commit
        ),
        download_archive=downloader,
        terminal_owner_run_id=profile.source_run_id,
    )
    if owner is None or not hasattr(owner, "run_id"):
        raise ValueError("CATALOG_RECOVERY_OWNER_MISSING")
    terminal = load_owner_terminal_receipt(
        client=client,
        owner=owner,
        issue_number=profile.source_issue_number,
        download_archive=downloader,
    )
    _require_owner_and_terminal(owner, terminal, profile, request)

    artifacts = tuple(profile.artifacts)
    plans = tuple(item for item in artifacts if item.role == "plan")
    groups = tuple(item for item in artifacts if item.role == "group")
    if len(plans) != 1 or not groups:
        raise ValueError("CATALOG_RECOVERY_PROFILE_ARTIFACTS_INVALID")
    downloaded: dict[str, bytes] = {}
    for artifact in (*plans, *groups):
        raw, metadata = read_owner_artifact_archive(
            client=client,
            owner=owner,
            artifact_name=artifact.artifact_name,
            publisher_job_name=artifact.publisher_job_name,
            publish_step_name=artifact.publish_step_name,
            download_archive=downloader,
        )
        if not isinstance(raw, bytes) or not raw:
            raise ValueError("CATALOG_RECOVERY_ARTIFACT_BYTES_INVALID")
        _profile_artifact_metadata(metadata, artifact)
        if len(raw) != artifact.size_bytes or hashlib.sha256(raw).hexdigest() != artifact.digest[7:]:
            raise ValueError("CATALOG_RECOVERY_ARTIFACT_PROFILE_MISMATCH")
        downloaded[artifact.artifact_name] = raw

    staging = Path(tempfile.mkdtemp(prefix=".catalog-reduction-recovery-", dir=target.parent))
    published = False
    try:
        _safe_extract_archive(downloaded[plans[0].artifact_name], staging / "sealed-plan")
        groups_root = staging / "groups"
        groups_root.mkdir()
        for artifact in groups:
            _safe_extract_archive(downloaded[artifact.artifact_name], groups_root / artifact.artifact_name)

        bindings = dict(profile.source_plan_bindings)
        validated = verify_reduction_recovery_source(
            staging / "sealed-plan",
            groups_root,
            bindings,
            profile.science_sha256,
            profile.catalog_manifest_sha256,
            profile.strategy_ids,
        )
        if validated.plan_receipt_sha256 != profile.source_plan_receipt_sha256:
            raise ValueError("CATALOG_RECOVERY_PLAN_RECEIPT_MISMATCH")
        expected_group_names = {artifact.artifact_name for artifact in groups}
        actual_group_receipts = tuple(validated.group_receipts)
        actual_group_names = {
            receipt.get("reduction_artifact")
            for receipt in actual_group_receipts
            if isinstance(receipt, Mapping)
        }
        if actual_group_names != expected_group_names:
            raise ValueError("CATALOG_RECOVERY_GROUP_RECEIPT_MISMATCH")
        for artifact in groups:
            matching = [
                receipt
                for receipt in actual_group_receipts
                if receipt.get("reduction_artifact") == artifact.artifact_name
            ]
            if len(matching) != 1 or matching[0].get("receipt_sha256") != artifact.receipt_sha256:
                raise ValueError("CATALOG_RECOVERY_GROUP_RECEIPT_MISMATCH")

        _publish_staging(staging, target)
        published = True
        return ReductionRecoveryRestoreResult(
            output_dir=target,
            profile_sha256=profile.profile_sha256,
            owner_run_id=owner.run_id,
            terminal_receipt_sha256=terminal.receipt_sha256,
            source_plan_receipt_sha256=validated.plan_receipt_sha256,
            group_receipt_sha256s=tuple(validated.group_receipt_sha256s),
        )
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


# Short alias for callers that name the operation after the recovery source.
restore_reduction_recovery = restore_catalog_reduction_recovery


__all__ = [
    "ReductionRecoveryRestoreResult",
    "restore_catalog_reduction_recovery",
    "restore_reduction_recovery",
    "_historical_owner_commit_approved",
    "_safe_extract_archive",
]
