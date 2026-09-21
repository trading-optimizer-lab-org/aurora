"""Restore a bounded, authenticated historical checkpoint-recovery archive.

The archive registry is only a closed set of references.  It is not proof of
the prepared bundle, its publisher, or its lifetime.  Every matching record is
therefore re-read through the existing PREPARED-artifact restore boundary,
which authenticates the current remote metadata, publisher, digest, expiry,
and bundle manifest before this module validates the recovery source.

This module is intentionally read-only with respect to the remote repository.
It publishes only the local recovery tree, and only after every local and
remote-bound validation has completed successfully.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import NoReturn, Protocol, cast

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_binding import (
    build_checkpoint_recovery_binding,
    verify_checkpoint_recovery_plan,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import (
    CheckpointRecoveryOwnerProofV1,
    verify_checkpoint_failure_owner,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    CHECKPOINT_RECOVERY_CHECKPOINT_COUNT,
    CheckpointRecoveryProfileV1,
    canonical_cached_strategy_ids_sha256,
    validate_exact_checkpoint_profile,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_restore import (
    CheckpointRecoveryRestoreResultV1,
    _derive_expected_pending_ids,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_source import (
    ValidatedCheckpointRecoverySource,
    verify_checkpoint_recovery_source,
)
from aurora.infra.sp500_megarun.catalog_fast_path import CatalogPreparationIdentityV1
from aurora.infra.sp500_megarun.catalog_fast_reservation import FastGateOwnerEvidence
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_auth import (
    CheckpointRecoveryOwnerAuthenticationV1,
)
from aurora.infra.sp500_megarun.catalog_prepared_artifact import (
    PreparedArtifactRestoreResult,
    _rename_without_overwrite,
    restore_prepared_artifact,
)


_REPOSITORY = "trading-optimizer-lab-org/aurora"
_ARCHIVE_CONFIG = "config/catalog_checkpoint_recovery_archives_v1.json"
_CONFIG_MAX_BYTES = 256 * 1024
_SEED_MAX_BYTES = 4 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_ARCHIVE_FIELDS = frozenset(
    {
        "profile_sha256",
        "identity",
        "run_id",
        "run_attempt",
        "artifact_id",
        "artifact_digest",
        "size_bytes",
        "prepared_receipt_sha256",
        "bundle_manifest_sha256",
    }
)


class _ReadOnlySource(Protocol):
    repository: str

    def get_json(self, path: str) -> tuple[object, object]: ...


class _ArchiveRecord:
    __slots__ = (
        "profile_sha256",
        "identity",
        "run_id",
        "run_attempt",
        "artifact_id",
        "artifact_digest",
        "size_bytes",
        "prepared_receipt_sha256",
        "bundle_manifest_sha256",
    )

    def __init__(
        self,
        *,
        profile_sha256: str,
        identity: CatalogPreparationIdentityV1,
        run_id: int,
        run_attempt: int,
        artifact_id: int,
        artifact_digest: str,
        size_bytes: int,
        prepared_receipt_sha256: str,
        bundle_manifest_sha256: str,
    ) -> None:
        self.profile_sha256 = profile_sha256
        self.identity = identity
        self.run_id = run_id
        self.run_attempt = run_attempt
        self.artifact_id = artifact_id
        self.artifact_digest = artifact_digest
        self.size_bytes = size_bytes
        self.prepared_receipt_sha256 = prepared_receipt_sha256
        self.bundle_manifest_sha256 = bundle_manifest_sha256


def _fail(code: str) -> NoReturn:
    raise ValueError(code)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_CONFIG_INVALID")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    _fail(f"CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_CONFIG_INVALID:{value}")


def _path_has_symlink(path: Path) -> bool:
    """Reject symlinked path components, including a symlinked config parent."""

    current = Path(path.anchor) if path.anchor else Path()
    parts = path.parts[1:] if path.anchor else path.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _repository_root(repo_root: Path) -> Path:
    supplied = Path(repo_root)
    try:
        root = supplied.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_ROOT_INVALID") from exc
    if supplied.is_symlink() or not root.is_dir():
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_ROOT_INVALID")
    return root


def _strict_json_file(path: Path, *, max_bytes: int, error_code: str) -> object:
    if _path_has_symlink(path) or not path.is_file():
        _fail(error_code)
    try:
        raw = path.read_bytes()
        if not raw or len(raw) > max_bytes:
            _fail(error_code)
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (OSError, UnicodeError, RecursionError, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("CATALOG_"):
            raise
        raise ValueError(error_code) from exc


def _positive_int(value: object, code: str) -> int:
    if type(value) is not int or value < 1:
        _fail(code)
    return value


def _sha256(value: object, code: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(code)
    return value


def _parse_archive_record(value: object) -> _ArchiveRecord:
    if not isinstance(value, Mapping) or set(value) != _ARCHIVE_FIELDS:
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_RECORD_INVALID")
    profile_sha256 = _sha256(
        value.get("profile_sha256"),
        "CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_RECORD_INVALID",
    )
    try:
        identity = CatalogPreparationIdentityV1.model_validate(value.get("identity"))
    except (TypeError, ValueError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_IDENTITY_INVALID") from exc
    artifact_digest = value.get("artifact_digest")
    if not isinstance(artifact_digest, str) or _DIGEST.fullmatch(artifact_digest) is None:
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_RECORD_INVALID")
    prepared_receipt_sha256 = _sha256(
        value.get("prepared_receipt_sha256"),
        "CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_RECORD_INVALID",
    )
    bundle_manifest_sha256 = _sha256(
        value.get("bundle_manifest_sha256"),
        "CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_RECORD_INVALID",
    )
    size_bytes = _positive_int(
        value.get("size_bytes"),
        "CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_RECORD_INVALID",
    )
    if size_bytes > _MAX_ARCHIVE_BYTES:
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_RECORD_INVALID")
    return _ArchiveRecord(
        profile_sha256=profile_sha256,
        identity=identity,
        run_id=_positive_int(
            value.get("run_id"), "CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_RECORD_INVALID"
        ),
        run_attempt=_positive_int(
            value.get("run_attempt"), "CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_RECORD_INVALID"
        ),
        artifact_id=_positive_int(
            value.get("artifact_id"), "CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_RECORD_INVALID"
        ),
        artifact_digest=artifact_digest,
        size_bytes=size_bytes,
        prepared_receipt_sha256=prepared_receipt_sha256,
        bundle_manifest_sha256=bundle_manifest_sha256,
    )


def _load_archive_records(root: Path) -> tuple[_ArchiveRecord, ...] | None:
    path = root / _ARCHIVE_CONFIG
    if _path_has_symlink(path):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_CONFIG_INVALID")
    if not path.exists():
        return None
    payload = _strict_json_file(
        path,
        max_bytes=_CONFIG_MAX_BYTES,
        error_code="CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_CONFIG_INVALID",
    )
    if (
        not isinstance(payload, Mapping)
        or set(payload) != {"schema_version", "archives"}
        or payload.get("schema_version") != "1"
        or not isinstance(payload.get("archives"), list)
    ):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_CONFIG_INVALID")
    records: list[_ArchiveRecord] = []
    for item in payload["archives"]:
        try:
            records.append(_parse_archive_record(item))
        except ValueError as exc:
            if str(exc).startswith("CATALOG_"):
                raise
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_CONFIG_INVALID") from exc
    profile_keys = tuple(record.profile_sha256 for record in records)
    identity_keys = tuple(record.identity.preparation_key_sha256 for record in records)
    artifact_ids = tuple(record.artifact_id for record in records)
    if (
        len(set(profile_keys)) != len(profile_keys)
        or len(set(identity_keys)) != len(identity_keys)
        or len(set(artifact_ids)) != len(artifact_ids)
    ):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_CONFIG_INVALID")
    return tuple(records)


def _safe_output_path(output_dir: Path) -> Path:
    supplied = Path(output_dir)
    try:
        target = supplied.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_PATH_INVALID") from exc
    if (
        not target.is_absolute()
        or supplied.is_symlink()
        or _path_has_symlink(target.parent)
        or target.exists()
        or target.is_symlink()
        or not target.parent.is_dir()
    ):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_PATH_INVALID")
    return target


def _validate_authenticated(
    profile: CheckpointRecoveryProfileV1,
    authenticated: object,
) -> CheckpointRecoveryOwnerProofV1:
    if not isinstance(authenticated, CheckpointRecoveryOwnerAuthenticationV1):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_AUTHENTICATION_INVALID")
    owner = authenticated.owner
    proof = authenticated.proof
    if not isinstance(owner, FastGateOwnerEvidence) or not isinstance(
        proof, CheckpointRecoveryOwnerProofV1
    ):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_AUTHENTICATION_INVALID")
    try:
        recomputed = verify_checkpoint_failure_owner(
            profile=profile,
            owner=owner,
            terminal=None,
        )
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_AUTHENTICATION_INVALID") from exc
    if recomputed != proof:
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_AUTHENTICATION_INVALID")
    if (
        proof.profile_sha256 != profile.profile_sha256
        or proof.campaign_key != profile.campaign_key
        or proof.target_generation != profile.target_generation
        or proof.source_request_sha256 != profile.source_request_sha256
        or proof.source_issue_number != profile.source_issue_number
        or proof.source_run_id != profile.source_run_id
        or proof.source_run_attempt != profile.source_run_attempt
        or proof.source_protected_commit_sha != profile.source_protected_commit_sha
        or proof.source_decision_sha256 != profile.source_plan_bindings["decision_sha256"]
        or proof.evidence_kind != "failed_owner_without_terminal"
    ):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_AUTHENTICATION_INVALID")
    return proof


def _validate_historical_ancestor(
    source: _ReadOnlySource,
    repository: str,
    historical_commit: str,
    protected_commit: str,
) -> None:
    if (
        source.repository != repository
        or repository != _REPOSITORY
        or _COMMIT.fullmatch(historical_commit) is None
        or _COMMIT.fullmatch(protected_commit) is None
    ):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_LINEAGE_INVALID")
    try:
        comparison, _ = source.get_json(
            f"/repos/{repository}/compare/{historical_commit}...{protected_commit}"
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_LINEAGE_INVALID") from exc
    if not isinstance(comparison, Mapping):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_LINEAGE_INVALID")
    base_commit = comparison.get("base_commit")
    merge_base = comparison.get("merge_base_commit")
    if (
        comparison.get("status") not in {"ahead", "identical"}
        or not isinstance(base_commit, Mapping)
        or not isinstance(merge_base, Mapping)
        or base_commit.get("sha") != historical_commit
        or merge_base.get("sha") != historical_commit
    ):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_LINEAGE_INVALID")


def _read_seed_document(bundle_root: Path) -> Mapping[str, object]:
    value = _strict_json_file(
        bundle_root / "evidence" / "preparation-seed.json",
        max_bytes=_SEED_MAX_BYTES,
        error_code="CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_SEED_INVALID",
    )
    if not isinstance(value, Mapping):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_SEED_INVALID")
    recovery = value.get("checkpoint_recovery")
    if not isinstance(recovery, Mapping) or recovery.get("schema_version") != "1":
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_SEED_INVALID")
    return recovery


def _validate_archived_source(
    *,
    repo_root: Path,
    bundle_root: Path,
    profile: CheckpointRecoveryProfileV1,
    proof: CheckpointRecoveryOwnerProofV1,
    prepared: PreparedArtifactRestoreResult,
) -> tuple[ValidatedCheckpointRecoverySource, Path, Path]:
    document = _read_seed_document(bundle_root)
    try:
        seed_profile = validate_exact_checkpoint_profile(repo_root, document.get("profile"))
    except (TypeError, ValueError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_PROFILE_INVALID") from exc
    if seed_profile != profile:
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_PROFILE_INVALID")
    raw_proof = document.get("owner_proof")
    if not isinstance(raw_proof, Mapping):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_PROOF_INVALID")
    try:
        seed_proof = CheckpointRecoveryOwnerProofV1(**dict(raw_proof))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_PROOF_INVALID") from exc
    if seed_proof != proof:
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_PROOF_INVALID")
    if document.get("binding") != build_checkpoint_recovery_binding(profile, proof):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_PROOF_INVALID")
    if (
        document.get("source_plan_relative") != "source-plan"
        or document.get("checkpoint_relative") != "checkpoints"
    ):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_TRANSPORT_INVALID")

    transport_root = bundle_root / "checkpoint-recovery"
    source_plan_root = transport_root / "source-plan"
    checkpoint_root = transport_root / "checkpoints"
    for path in (transport_root, source_plan_root, checkpoint_root):
        if (
            _path_has_symlink(path)
            or not path.is_dir()
            or not path.resolve(strict=True).is_relative_to(bundle_root.resolve(strict=True))
        ):
            _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_TRANSPORT_INVALID")

    template = bundle_root / "templates" / f"workers-{prepared.receipt.qualified_worker_ceiling:03d}"
    if (
        _path_has_symlink(template)
        or not template.is_dir()
        or not template.resolve(strict=True).is_relative_to(bundle_root.resolve(strict=True))
    ):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_TEMPLATE_INVALID")
    try:
        verify_checkpoint_recovery_plan(template, profile, proof)
        expected_ids = _derive_expected_pending_ids(source_plan_root, profile)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_SOURCE_INVALID") from exc

    cached = document.get("cached_strategy_ids")
    if (
        not isinstance(cached, list)
        or any(type(item) is not str or not item for item in cached)
        or len(set(cached)) != len(cached)
        or tuple(sorted(cached)) != tuple(sorted(expected_ids))
        or canonical_cached_strategy_ids_sha256(cached)
        != profile.cached_strategy_ids_sha256
        or document.get("cached_strategy_ids_sha256") != profile.cached_strategy_ids_sha256
    ):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_SOURCE_INVALID")
    try:
        source_validation = verify_checkpoint_recovery_source(
            source_plan_root,
            checkpoint_root,
            dict(profile.source_plan_bindings),
            profile.science_sha256,
            profile.catalog_manifest_sha256,
            expected_ids,
            profile.worker_ids,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_SOURCE_INVALID") from exc
    if (
        source_validation.checkpoint_count != CHECKPOINT_RECOVERY_CHECKPOINT_COUNT
        or source_validation.resume_index.physical_result_count
        != profile.expected_result_count
        or source_validation.resume_index.duplicate_result_count != 0
        or tuple(sorted(source_validation.resume_index.strategy_ids))
        != tuple(sorted(expected_ids))
        or source_validation.plan_receipt_sha256 != profile.source_plan_receipt_sha256
        or document.get("source_plan_receipt_sha256") != profile.source_plan_receipt_sha256
    ):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_SOURCE_INVALID")
    return source_validation, source_plan_root, checkpoint_root


def _compare_prepared_pins(
    *,
    record: _ArchiveRecord,
    restored: PreparedArtifactRestoreResult,
    downloaded: bytes,
) -> None:
    if (
        type(downloaded) is not bytes
        or len(downloaded) != record.size_bytes
        or restored.artifact_id != record.artifact_id
        or restored.run_id != record.run_id
        or restored.run_attempt != record.run_attempt
        or restored.digest != record.artifact_digest
        or restored.source_commit != record.identity.protected_commit_sha
        or restored.campaign_key != record.identity.campaign_key
        or restored.preparation_key_sha256 != record.identity.preparation_key_sha256
        or restored.receipt.receipt_sha256 != record.prepared_receipt_sha256
        or restored.manifest.manifest_sha256 != record.bundle_manifest_sha256
        or restored.receipt.identity != record.identity
        or restored.receipt.identity.preparation_key_sha256
        != record.identity.preparation_key_sha256
        or restored.manifest.preparation_key_sha256
        != record.identity.preparation_key_sha256
        or restored.manifest.prepared_receipt_sha256
        != record.prepared_receipt_sha256
    ):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_PIN_MISMATCH")


def _rebase_source_validation(
    source_validation: ValidatedCheckpointRecoverySource,
    old_root: Path,
    new_root: Path,
) -> ValidatedCheckpointRecoverySource:
    try:
        results = tuple(
            item.model_copy(
                update={
                    "source_path": str(
                        new_root / Path(item.source_path).relative_to(old_root)
                    )
                }
            )
            for item in source_validation.resume_index.results
        )
        identity = source_validation.resume_index.model_dump(exclude={"index_sha256"})
        identity["results"] = results
        index = source_validation.resume_index.model_copy(
            update={"results": results, "index_sha256": canonical_sha256(identity)}
        )
        return source_validation.model_copy(update={"resume_index": index})
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_INDEX_INVALID") from exc


def restore_archived_checkpoint_recovery(
    repo_root: Path,
    repository: str,
    protected_commit_sha: str,
    profile: CheckpointRecoveryProfileV1 | Mapping[str, object],
    authenticated: CheckpointRecoveryOwnerAuthenticationV1,
    output_dir: Path,
    fetch_json: object,
    download_artifact: Callable[[int], bytes],
) -> CheckpointRecoveryRestoreResultV1 | None:
    """Restore one configured historical PREPARED checkpoint-recovery bundle.

    ``None`` is reserved for the legacy route: the archive registry is absent,
    or it is present and contains no record for this exact protected profile.
    Once a matching record exists, every error is terminal and the destination
    remains unpublished.
    """

    root = _repository_root(repo_root)
    records = _load_archive_records(root)
    if records is None:
        return None
    protected_profile = validate_exact_checkpoint_profile(root, profile)
    matching = tuple(
        record for record in records if record.profile_sha256 == protected_profile.profile_sha256
    )
    if not matching:
        return None
    if len(matching) != 1:
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_CONFIG_INVALID")
    record = matching[0]
    if record.identity.campaign_key != protected_profile.campaign_key:
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_IDENTITY_INVALID")
    target = _safe_output_path(output_dir)
    if (
        repository != _REPOSITORY
        or type(protected_commit_sha) is not str
        or _COMMIT.fullmatch(protected_commit_sha) is None
        or not callable(download_artifact)
    ):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_AUTHENTICATION_INVALID")
    source = fetch_json
    if (
        not isinstance(getattr(source, "repository", None), str)
        or getattr(source, "repository", None) != repository
        or not callable(getattr(source, "get_json", None))
    ):
        _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_FETCH_INVALID")
    proof = _validate_authenticated(protected_profile, authenticated)
    _validate_historical_ancestor(
        cast(_ReadOnlySource, source),
        repository,
        record.identity.protected_commit_sha,
        protected_commit_sha,
    )

    staging_parent = Path(
        tempfile.mkdtemp(prefix=".catalog-checkpoint-recovery-archive-", dir=str(target.parent))
    )
    bundle_root = staging_parent / "prepared-bundle"
    downloaded: list[bytes] = []

    def _download(artifact_id: int) -> bytes:
        if artifact_id != record.artifact_id:
            _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_PIN_MISMATCH")
        raw = download_artifact(artifact_id)
        downloaded.append(raw)
        return raw

    try:
        restored = restore_prepared_artifact(
            client=source,
            expected_identity=record.identity,
            destination=bundle_root,
            download_archive=_download,
        )
        if not isinstance(restored, PreparedArtifactRestoreResult) or len(downloaded) != 1:
            _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_RESULT_INVALID")
        _compare_prepared_pins(record=record, restored=restored, downloaded=downloaded[0])
        source_validation, source_plan_root, checkpoint_root = _validate_archived_source(
            repo_root=root,
            bundle_root=bundle_root,
            profile=protected_profile,
            proof=proof,
            prepared=restored,
        )
        recovery_root = bundle_root / "checkpoint-recovery"
        rebased = _rebase_source_validation(source_validation, recovery_root, target)
        if target.exists() or target.is_symlink():
            _fail("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_OUTPUT_EXISTS")
        _rename_without_overwrite(recovery_root, target)
        return CheckpointRecoveryRestoreResultV1(
            profile=protected_profile,
            proof=proof,
            source_validation=rebased,
            checkpoint_root=target / "checkpoints",
            source_plan_root=target / "source-plan",
        )
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


__all__ = ["restore_archived_checkpoint_recovery"]
