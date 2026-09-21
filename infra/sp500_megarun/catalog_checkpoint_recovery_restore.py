"""Restore the authenticated source-7 checkpoint transport for gen8.

This boundary owns transport and local validation only.  It authenticates the
protected profile and failed owner through the existing read-only auth helper,
reads the one complete owner-run artifact inventory once, downloads the
profile-pinned ZIPs, extracts them with the bounded recovery extractor, and
then delegates source validation to the production checkpoint validator.
It never evaluates a new recipe, publishes anything, or mutates the source
plan.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import io
import os
from pathlib import Path
import re
import shutil
import tempfile
from types import SimpleNamespace
from typing import Protocol, cast
from urllib.parse import parse_qs, urlparse
import zipfile

from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_auth import (
    CheckpointRecoveryOwnerAuthenticationV1,
    authenticate_checkpoint_recovery_owner,
)
from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.catalog_sealed_plan import (
    verify_sealed_global_reuse_execution_plan,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_owner import (
    CheckpointRecoveryOwnerProofV1,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_profile import (
    CHECKPOINT_RECOVERY_CHECKPOINT_COUNT,
    CHECKPOINT_RECOVERY_SLOT_COUNT,
    CHECKPOINT_RECOVERY_WORKER_COUNT,
    CheckpointRecoveryArtifactV1,
    CheckpointRecoveryProfileV1,
    canonical_cached_strategy_ids_sha256,
    validate_exact_checkpoint_profile,
)
from aurora.infra.sp500_megarun.catalog_checkpoint_recovery_source import (
    ValidatedCheckpointRecoverySource,
    _validate_run_plan_and_manifest,
    _read_recipe_source_assignments,
    verify_checkpoint_recovery_source,
)
from aurora.infra.sp500_megarun.catalog_fast_reservation import (
    FastGateOwnerEvidence,
    read_owner_artifact_archive,
)
from aurora.infra.sp500_megarun.catalog_github_snapshot import (
    CatalogGitHubCollection,
)
from aurora.infra.sp500_megarun.catalog_reduction_recovery_restore import (
    _safe_extract_archive,
)


_REPOSITORY = "trading-optimizer-lab-org/aurora"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9_-]{1,200}$")

# These limits intentionally match the production bounded extractor.  The
# preflight below checks the real ZIP central directory before extraction;
# _safe_extract_archive repeats the checks while writing files.
_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
_MAX_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_TOTAL_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 4096
_MAX_COMPRESSION_RATIO = 1000


class _JsonSource(Protocol):
    repository: str

    def get_json(self, path: str) -> tuple[object, object]: ...

    def stable_paginated(self, path: str, *, root: str) -> object: ...


class _ArchiveReader(Protocol):
    def __call__(self, artifact_id: int) -> bytes: ...


class _InventoryCollection(Protocol):
    @property
    def rows(self) -> Sequence[Mapping[str, object]]: ...


@dataclass(frozen=True)
class CheckpointRecoveryRestoreResultV1:
    """Immutable local evidence sufficient for PREPARED and reducer input."""

    profile: CheckpointRecoveryProfileV1
    proof: CheckpointRecoveryOwnerProofV1
    source_validation: ValidatedCheckpointRecoverySource
    checkpoint_root: Path
    source_plan_root: Path


CheckpointRecoveryRestoreResult = CheckpointRecoveryRestoreResultV1


@dataclass(frozen=True)
class ArtifactInventorySubsetEvidence:
    """One name-filtered view over one authenticated complete inventory."""

    requested_name: str
    source_inventory: object
    source_collection_sha256: str | None
    collection: object
    attempt: object
    stable: object
    observed_at: object
    snapshot_sha256: object




def _inventory_collection(value: object) -> _InventoryCollection:
    collection = getattr(value, "collection", None)
    if collection is None or getattr(value, "stable", None) is not True:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_INVENTORY_INCOMPLETE")
    if getattr(collection, "complete", None) is not True:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_INVENTORY_INCOMPLETE")
    rows = getattr(collection, "rows", None)
    if not isinstance(rows, (list, tuple)):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_INVENTORY_INVALID")
    if any(not isinstance(row, Mapping) for row in rows):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_INVENTORY_INVALID")
    return cast(_InventoryCollection, collection)


class RunArtifactInventorySubsetClient:
    """Serve exact-name owner-artifact reads from one stable run inventory.

    ``read_owner_artifact_archive`` still performs every provenance, publisher,
    digest, size, expiry, and run binding check.  This adapter only replaces
    its repeated name queries with a view over one complete authenticated
    collection; it never treats the protected profile as an inventory.
    """

    def __init__(
        self,
        client: _JsonSource,
        *,
        owner_run_id: int,
        repository: str | None = None,
    ) -> None:
        if type(owner_run_id) is not int or owner_run_id < 1:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_OWNER_RUN_INVALID")
        selected_repository = repository or getattr(client, "repository", None)
        if selected_repository != _REPOSITORY:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_REPOSITORY_INVALID")
        self.repository = selected_repository
        self._client = client
        self._owner_run_id = owner_run_id
        self._inventory: object | None = None
        self._inventory_calls = 0
        self._subsets: list[ArtifactInventorySubsetEvidence] = []

    @property
    def inventory_calls(self) -> int:
        return self._inventory_calls

    @property
    def source_inventory(self) -> object | None:
        return self._inventory

    @property
    def subset_evidence(self) -> tuple[ArtifactInventorySubsetEvidence, ...]:
        return tuple(self._subsets)

    def _load_inventory(self) -> object:
        if self._inventory is None:
            path = f"/repos/{self.repository}/actions/runs/{self._owner_run_id}/artifacts"
            inventory = self._client.stable_paginated(path, root="artifacts")
            _inventory_collection(inventory)
            self._inventory = inventory
            self._inventory_calls += 1
        return self._inventory

    def get_json(self, path: str) -> tuple[object, object]:
        return self._client.get_json(path)

    def stable_paginated(self, path: str, *, root: str) -> object:
        expected_path = f"/repos/{self.repository}/actions/runs/{self._owner_run_id}/artifacts"
        if urlparse(path).path != expected_path:
            return self._client.stable_paginated(path, root=root)
        if root != "artifacts":
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_INVENTORY_ROOT_INVALID")
        parsed = urlparse(path)
        expected_path = f"/repos/{self.repository}/actions/runs/{self._owner_run_id}/artifacts"
        query = parse_qs(parsed.query, keep_blank_values=True)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.path != expected_path
            or set(query) != {"name"}
            or len(query["name"]) != 1
        ):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_INVENTORY_PATH_INVALID")
        requested_name = query["name"][0]
        if _ARTIFACT_NAME.fullmatch(requested_name) is None:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_NAME_INVALID")

        inventory = self._load_inventory()
        collection = _inventory_collection(inventory)
        rows = tuple(row for row in collection.rows if row.get("name") == requested_name)
        source_sha = getattr(collection, "collection_sha256", None)
        source_rows = tuple(dict(row) for row in rows)
        if isinstance(collection, CatalogGitHubCollection):
            subset_collection: object = CatalogGitHubCollection(
                rows=source_rows,
                ordered_ids=tuple(int(cast(int, row["id"])) for row in source_rows if type(row.get("id")) is int),
                pages=collection.pages,
                complete=collection.complete,
                # Keep the authentic complete-collection identity.  The
                # subset is a query view, not a new claimed remote snapshot.
                collection_sha256=collection.collection_sha256,
            )
        else:
            subset_collection = SimpleNamespace(
                rows=source_rows,
                complete=getattr(collection, "complete"),
                pages=getattr(collection, "pages", None),
                ordered_ids=tuple(row.get("id") for row in source_rows),
                collection_sha256=source_sha,
            )
        subset = ArtifactInventorySubsetEvidence(
            requested_name=requested_name,
            source_inventory=inventory,
            source_collection_sha256=source_sha,
            collection=subset_collection,
            attempt=getattr(inventory, "attempt", None),
            stable=getattr(inventory, "stable", None),
            observed_at=getattr(inventory, "observed_at", None),
            snapshot_sha256=getattr(inventory, "snapshot_sha256", None),
        )
        self._subsets.append(subset)
        return subset


# Descriptive alias for callers that name the adapter after the recovery.
CheckpointRecoveryArtifactInventoryAdapter = RunArtifactInventorySubsetClient




def _derive_expected_pending_ids(
    source_plan_root: Path,
    profile: CheckpointRecoveryProfileV1,
) -> tuple[str, ...]:
    """Derive the source-worker IDs without trusting a profile ID list."""

    _, all_ids, pending_ids, _ = _validate_run_plan_and_manifest(
        source_plan_root, expected_science=profile.science_sha256,
    )
    assignments = _read_recipe_source_assignments(
        source_plan_root, all_strategy_ids=all_ids, pending_strategy_ids=pending_ids,
    )
    cached_ids = tuple(
        strategy_id for worker_id in profile.worker_ids
        for strategy_id in assignments[worker_id]["strategy_ids"]
    )
    if (
        len(all_ids) != profile.expected_total_count
        or len(cached_ids) != profile.expected_result_count
        or canonical_cached_strategy_ids_sha256(cached_ids)
        != profile.cached_strategy_ids_sha256
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PARTITION_INVALID")
    return cached_ids


def _preflight_zip(raw: bytes) -> None:
    if type(raw) is not bytes or not raw or len(raw) > _MAX_ARCHIVE_BYTES:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_SIZE_INVALID")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if not members or len(members) > _MAX_ARCHIVE_MEMBERS:
                raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_MEMBER_COUNT_INVALID")
            total = 0
            for member in members:
                size = member.file_size
                if type(size) is not int or size < 0 or size > _MAX_MEMBER_BYTES:
                    raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_MEMBER_SIZE_INVALID")
                if (
                    not member.is_dir()
                    and (not member.compress_size or size / member.compress_size > _MAX_COMPRESSION_RATIO)
                ):
                    raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_RATIO_INVALID")
                total += size
                if total > _MAX_TOTAL_UNCOMPRESSED_BYTES:
                    raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_TOTAL_SIZE_INVALID")
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARCHIVE_INVALID") from exc


def _profile_artifact_metadata(metadata: object, artifact: object) -> None:
    try:
        expected_id = getattr(artifact, "artifact_id")
        expected_name = getattr(artifact, "artifact_name")
        expected_digest = getattr(artifact, "digest")
        expected_size = getattr(artifact, "size_bytes")
        expected_job = getattr(artifact, "publisher_job_name")
        expected_step = getattr(artifact, "publish_step_name")
    except AttributeError as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_INVALID") from exc
    if (
        not isinstance(metadata, Mapping)
        or type(expected_id) is not int
        or type(expected_size) is not int
        or metadata.get("id") != expected_id
        or metadata.get("name") != expected_name
        or metadata.get("digest") != expected_digest
        or metadata.get("size_in_bytes") != expected_size
        or (
            "publisher_job_name" in metadata
            and metadata.get("publisher_job_name") != expected_job
        )
        or (
            "publish_step_name" in metadata
            and metadata.get("publish_step_name") != expected_step
        )
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_PROFILE_MISMATCH")


def _profile_artifacts(
    profile: CheckpointRecoveryProfileV1,
) -> tuple[tuple[CheckpointRecoveryArtifactV1, ...], tuple[CheckpointRecoveryArtifactV1, ...]]:
    """Recheck the closed pin set before any owner or artifact read."""

    try:
        artifacts = tuple(profile.artifacts)
        worker_ids = tuple(profile.worker_ids)
    except (AttributeError, TypeError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_INVALID") from exc
    plans = tuple(item for item in artifacts if getattr(item, "role", None) == "plan")
    checkpoints = tuple(
        item for item in artifacts if getattr(item, "role", None) == "checkpoint"
    )
    if (
        len(plans) != 1
        or len(checkpoints) != CHECKPOINT_RECOVERY_CHECKPOINT_COUNT
        or len(artifacts) != CHECKPOINT_RECOVERY_CHECKPOINT_COUNT + 1
        or len(worker_ids) != CHECKPOINT_RECOVERY_WORKER_COUNT
        or len(set(worker_ids)) != len(worker_ids)
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_ARTIFACTS_INVALID")
    ids: list[int] = []
    names: list[str] = []
    digests: list[str] = []
    coordinates: list[tuple[object, object]] = []
    for artifact in artifacts:
        try:
            artifact_id = getattr(artifact, "artifact_id")
            name = getattr(artifact, "artifact_name")
            digest = getattr(artifact, "digest")
            size = getattr(artifact, "size_bytes")
            job = getattr(artifact, "publisher_job_name")
            step = getattr(artifact, "publish_step_name")
            role = getattr(artifact, "role")
            worker_id = getattr(artifact, "worker_id")
            slot_index = getattr(artifact, "slot_index")
        except AttributeError as exc:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_INVALID") from exc
        if (
            type(artifact_id) is not int
            or artifact_id < 1
            or not isinstance(name, str)
            or _ARTIFACT_NAME.fullmatch(name) is None
            or not isinstance(digest, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
            or type(size) is not int
            or not 0 < size <= _MAX_ARCHIVE_BYTES
            or not isinstance(job, str)
            or not job
            or not isinstance(step, str)
            or not step
        ):
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_ARTIFACT_PIN_INVALID")
        if role == "plan":
            if worker_id is not None or slot_index is not None:
                raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_ARTIFACT_PIN_INVALID")
        elif role == "checkpoint":
            if (
                type(worker_id) is not int
                or worker_id not in worker_ids
                or type(slot_index) is not int
                or not 1 <= slot_index <= CHECKPOINT_RECOVERY_SLOT_COUNT
            ):
                raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_ARTIFACT_PIN_INVALID")
            coordinates.append((worker_id, slot_index))
        else:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_ARTIFACT_PIN_INVALID")
        ids.append(artifact_id)
        names.append(name)
        digests.append(digest)
    expected_coordinates = {
        (worker_id, slot_index)
        for worker_id in worker_ids
        for slot_index in range(1, CHECKPOINT_RECOVERY_SLOT_COUNT + 1)
    }
    if (
        len(set(ids)) != len(ids)
        or len(set(names)) != len(names)
        or len(set(digests)) != len(digests)
        or set(coordinates) != expected_coordinates
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_ARTIFACT_PIN_INVALID")
    return plans, checkpoints


def _validate_publisher(owner: FastGateOwnerEvidence, artifact: object) -> None:
    try:
        job_name = getattr(artifact, "publisher_job_name")
        step_name = getattr(artifact, "publish_step_name")
    except AttributeError as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_INVALID") from exc
    jobs = tuple(job for job in owner.jobs if isinstance(job, Mapping) and job.get("name") == job_name)
    if len(jobs) != 1:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_PUBLISHER_INVALID")
    steps = tuple(step for step in jobs[0].get("steps", ()) if isinstance(step, Mapping) and step.get("name") == step_name)
    if len(steps) != 1 or steps[0].get("status") != "completed" or steps[0].get("conclusion") != "success":
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_PUBLISHER_INVALID")


def _validate_output_path(repo_root: Path, output_dir: Path) -> tuple[Path, Path]:
    try:
        root = Path(repo_root).resolve(strict=True)
        target = Path(output_dir).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PATH_INVALID") from exc
    supplied_root = Path(repo_root)
    supplied_target = Path(output_dir)
    if (
        supplied_root.is_symlink()
        or not root.is_dir()
        or supplied_target.is_symlink()
        or target.exists()
        or not target.parent.is_dir()
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PATH_INVALID")
    return root, target


def _resolve_source(repository: str, fetch_json: object) -> _JsonSource:
    source = fetch_json
    if source is None:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_FETCH_INVALID")
    if not callable(getattr(source, "get_json", None)) and not callable(source):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_FETCH_INVALID")
    source_repository = getattr(source, "repository", None)
    if source_repository is not None and source_repository != repository:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_AUTH_IDENTITY_INVALID")
    if (
        source_repository != repository
        or not callable(getattr(source, "get_json", None))
        or not callable(getattr(source, "stable_paginated", None))
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_FETCH_INVALID")
    return cast(_JsonSource, source)


def restore_catalog_checkpoint_recovery(
    *,
    repo_root: Path,
    repository: str,
    protected_commit_sha: str,
    profile: CheckpointRecoveryProfileV1 | Mapping[str, object],
    output_dir: Path,
    fetch_json: object,
    download_artifact: _ArchiveReader,
) -> CheckpointRecoveryRestoreResultV1:
    """Authenticate, download, validate, and atomically restore checkpoints."""

    root, target = _validate_output_path(repo_root, output_dir)
    if repository != _REPOSITORY or type(protected_commit_sha) is not str or _COMMIT.fullmatch(protected_commit_sha) is None:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_AUTH_IDENTITY_INVALID")
    if not callable(download_artifact):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_READER_INVALID")
    source = _resolve_source(repository, fetch_json)
    protected_profile = validate_exact_checkpoint_profile(root, profile)
    if len(protected_profile.worker_ids) != CHECKPOINT_RECOVERY_WORKER_COUNT:
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PROFILE_INVALID")
    plans, checkpoints = _profile_artifacts(protected_profile)

    inventory_client = RunArtifactInventorySubsetClient(
        source, owner_run_id=protected_profile.source_run_id,
    )

    authenticated = authenticate_checkpoint_recovery_owner(
        repo_root=root,
        repository=repository,
        protected_commit_sha=protected_commit_sha,
        profile=protected_profile,
        fetch_json=inventory_client,
        download_artifact=download_artifact,
    )
    if not isinstance(authenticated, CheckpointRecoveryOwnerAuthenticationV1):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_AUTHENTICATION_INVALID")
    owner = authenticated.owner
    proof = authenticated.proof
    if (
        not isinstance(owner, FastGateOwnerEvidence)
        or not isinstance(proof, CheckpointRecoveryOwnerProofV1)
        or proof.profile_sha256 != protected_profile.profile_sha256
        or proof.source_run_id != protected_profile.source_run_id
        or proof.source_run_attempt != protected_profile.source_run_attempt
        or proof.source_protected_commit_sha != protected_profile.source_protected_commit_sha
    ):
        raise ValueError("CATALOG_CHECKPOINT_RECOVERY_AUTHENTICATION_INVALID")

    # A protected PREPARED publication may preserve the authenticated source
    # after the original short-lived plan artifact has expired.
    from .catalog_checkpoint_recovery_archive import restore_archived_checkpoint_recovery

    archived = restore_archived_checkpoint_recovery(
        repo_root=root,
        repository=repository,
        protected_commit_sha=protected_commit_sha,
        profile=protected_profile,
        authenticated=authenticated,
        output_dir=target,
        fetch_json=source,
        download_artifact=download_artifact,
    )
    if archived is not None:
        return archived

    downloaded: dict[str, bytes] = {}
    for artifact in (*plans, *checkpoints):
        _validate_publisher(owner, artifact)
        raw, metadata = read_owner_artifact_archive(
            client=inventory_client,
            owner=owner,
            artifact_name=artifact.artifact_name,
            publisher_job_name=artifact.publisher_job_name,
            publish_step_name=artifact.publish_step_name,
            download_archive=download_artifact,
        )
        _profile_artifact_metadata(metadata, artifact)
        if type(raw) is not bytes or not raw or len(raw) != artifact.size_bytes:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_SIZE_INVALID")
        if hashlib.sha256(raw).hexdigest() != artifact.digest[7:]:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_DIGEST_INVALID")
        if artifact.artifact_name in downloaded:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_ARTIFACT_DUPLICATE")
        downloaded[artifact.artifact_name] = raw

    # A fixed name would allow a stale sibling to influence a restore.  Use a
    # private temporary directory and publish only after all validation passes.
    staging = Path(tempfile.mkdtemp(prefix=".catalog-checkpoint-recovery-", dir=str(target.parent)))
    published = False
    try:
        source_plan_root = staging / "source-plan"
        checkpoint_root = staging / "checkpoints"
        _preflight_zip(downloaded[plans[0].artifact_name])
        _safe_extract_archive(downloaded[plans[0].artifact_name], source_plan_root)
        checkpoint_root.mkdir()
        for artifact in checkpoints:
            raw = downloaded[artifact.artifact_name]
            _preflight_zip(raw)
            _safe_extract_archive(raw, checkpoint_root / artifact.artifact_name)

        receipt = verify_sealed_global_reuse_execution_plan(
            source_plan_root, expected_bindings=protected_profile.source_plan_bindings,
        )
        if receipt.get("receipt_sha256") != protected_profile.source_plan_receipt_sha256:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PLAN_RECEIPT_MISMATCH")
        expected_strategy_ids = _derive_expected_pending_ids(source_plan_root, protected_profile)
        source_validation = verify_checkpoint_recovery_source(
            source_plan_root,
            checkpoint_root,
            dict(protected_profile.source_plan_bindings),
            protected_profile.science_sha256,
            protected_profile.catalog_manifest_sha256,
            expected_strategy_ids,
            tuple(protected_profile.worker_ids),
        )
        if source_validation.plan_receipt_sha256 != protected_profile.source_plan_receipt_sha256:
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_PLAN_RECEIPT_MISMATCH")

        if target.exists() or target.is_symlink():
            raise ValueError("CATALOG_CHECKPOINT_RECOVERY_OUTPUT_EXISTS")
        os.replace(staging, target)
        published = True
        if isinstance(source_validation, ValidatedCheckpointRecoverySource):
            index = source_validation.resume_index
            results = tuple(
                item.model_copy(update={"source_path": str(
                    target / Path(item.source_path).relative_to(staging)
                )}) for item in index.results
            )
            identity = index.model_dump(exclude={"index_sha256"})
            identity["results"] = results
            index = index.model_copy(update={
                "results": results, "index_sha256": canonical_sha256(identity),
            })
            source_validation = source_validation.model_copy(update={"resume_index": index})
        return CheckpointRecoveryRestoreResultV1(
            profile=protected_profile,
            proof=proof,
            source_validation=source_validation,
            checkpoint_root=target / "checkpoints",
            source_plan_root=target / "source-plan",
        )
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


restore_checkpoint_recovery = restore_catalog_checkpoint_recovery


__all__ = [
    "ArtifactInventorySubsetEvidence",
    "CheckpointRecoveryArtifactInventoryAdapter",
    "CheckpointRecoveryRestoreResult",
    "CheckpointRecoveryRestoreResultV1",
    "RunArtifactInventorySubsetClient",
    "restore_catalog_checkpoint_recovery",
    "restore_checkpoint_recovery",
]
