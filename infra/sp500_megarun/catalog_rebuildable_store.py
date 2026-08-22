"""Closed, content-bound inventory for reusable catalog objects."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Mapping

from pydantic import Field, model_validator

from aurora.infra.github_performance.contracts import FrozenModel, Sha256


StoreStatus = Literal["verified", "missing", "evicted", "expired", "corrupt"]


class RebuildableStoreCandidateV1(FrozenModel):
    object_family: Literal["runtime", "prepared_input", "component"]
    logical_id: str = Field(min_length=1)
    identity_sha256: Sha256
    content_manifest_sha256: Sha256
    content_sha256: Sha256
    storage_kind: Literal["actions_cache", "artifact"]
    status: StoreStatus
    source_branch: Literal["main"]
    contained_logical_ids: tuple[str, ...] = ()
    logical_identity_bindings: tuple[tuple[str, Sha256], ...] = ()
    logical_content_bindings: tuple[tuple[str, Sha256], ...] = ()
    cache_key: str | None = None
    artifact_run_id: int | None = Field(default=None, ge=1)
    artifact_id: int | None = Field(default=None, ge=1)
    file_hashes: tuple[tuple[str, Sha256], ...]
    manifest_verified: bool
    content_verified: bool
    scope_verified: bool

    @model_validator(mode="after")
    def _validate_location_and_manifest(self) -> "RebuildableStoreCandidateV1":
        paths = tuple(path for path, _ in self.file_hashes)
        if paths != tuple(sorted(set(paths))) or any(
            not path or Path(path).is_absolute() or ".." in Path(path).parts
            for path in paths
        ):
            raise ValueError("REBUILDABLE_STORE_FILE_LIST_INVALID")
        if self.status == "verified":
            if not (
                self.file_hashes
                and self.manifest_verified
                and self.content_verified
                and self.scope_verified
            ):
                raise ValueError("REBUILDABLE_STORE_VERIFICATION_INCOMPLETE")
            if self.storage_kind == "actions_cache":
                expected = (
                    "aurora-catalog-v1-"
                    f"{self.identity_sha256}-"
                    f"{self.content_manifest_sha256}-main"
                )
                if (
                    self.cache_key != expected
                    or self.artifact_run_id is not None
                    or self.artifact_id is not None
                ):
                    raise ValueError("REBUILDABLE_CACHE_LOCATION_INVALID")
            elif (
                self.cache_key is not None
                or self.artifact_run_id is None
                or self.artifact_id is None
            ):
                raise ValueError("REBUILDABLE_ARTIFACT_LOCATION_INVALID")
        if bool(self.contained_logical_ids) != bool(
            self.logical_identity_bindings
        ):
            raise ValueError("REBUILDABLE_STORE_LOGICAL_BINDINGS_INVALID")
        if self.contained_logical_ids:
            if self.contained_logical_ids != tuple(
                sorted(set(self.contained_logical_ids))
            ):
                raise ValueError("REBUILDABLE_STORE_LOGICAL_BINDINGS_INVALID")
            binding_ids = tuple(item[0] for item in self.logical_identity_bindings)
            if (
                self.logical_identity_bindings
                != tuple(sorted(set(self.logical_identity_bindings)))
                or binding_ids != self.contained_logical_ids
            ):
                raise ValueError("REBUILDABLE_STORE_LOGICAL_BINDINGS_INVALID")
        if self.logical_content_bindings:
            content_ids = tuple(item[0] for item in self.logical_content_bindings)
            if (
                not self.contained_logical_ids
                or self.logical_content_bindings
                != tuple(sorted(set(self.logical_content_bindings)))
                or content_ids != self.contained_logical_ids
            ):
                raise ValueError("REBUILDABLE_STORE_CONTENT_BINDINGS_INVALID")
        return self


class RebuildableStoreInventoryV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    listing_complete: Literal[True]
    source_branch: Literal["main"]
    candidates: tuple[RebuildableStoreCandidateV1, ...]


def reconcile_verified_store_candidates(
    inventory: RebuildableStoreInventoryV1,
) -> dict[tuple[str, str, str], RebuildableStoreCandidateV1]:
    """Resolve exact verified objects; never turn uncertainty into a miss."""

    if not inventory.listing_complete or inventory.source_branch != "main":
        raise ValueError("REBUILDABLE_STORE_LISTING_UNKNOWN")
    grouped: dict[
        tuple[str, str, str],
        list[RebuildableStoreCandidateV1],
    ] = {}
    for candidate in inventory.candidates:
        if candidate.status != "verified":
            continue
        key = (
            candidate.object_family,
            candidate.logical_id,
            candidate.identity_sha256,
        )
        grouped.setdefault(key, []).append(candidate)
    resolved: dict[tuple[str, str, str], RebuildableStoreCandidateV1] = {}
    for key, candidates in grouped.items():
        content_identities = {
            (
                candidate.content_manifest_sha256,
                candidate.content_sha256,
                candidate.file_hashes,
            )
            for candidate in candidates
        }
        if len(content_identities) != 1:
            raise ValueError("REBUILDABLE_STORE_IDENTITY_CONFLICT")
        resolved[key] = min(
            candidates,
            key=lambda item: (
                0 if item.storage_kind == "actions_cache" else 1,
                item.cache_key or "",
                item.artifact_run_id or 0,
                item.artifact_id or 0,
            ),
        )
    return resolved


def select_component_store_candidates(
    candidates: tuple[RebuildableStoreCandidateV1, ...],
    *,
    required_identity_by_id: Mapping[str, str],
) -> dict[str, RebuildableStoreCandidateV1]:
    """Choose overlapping valid bundles once and reject content conflicts."""

    required_ids = frozenset(required_identity_by_id)
    options: dict[str, list[RebuildableStoreCandidateV1]] = {
        component_id: [] for component_id in required_ids
    }
    content_by_option: dict[tuple[str, str], str | None] = {}
    for candidate in candidates:
        if candidate.object_family != "component":
            continue
        bindings = (
            candidate.logical_identity_bindings
            if candidate.logical_identity_bindings
            else ((candidate.logical_id, candidate.identity_sha256),)
        )
        content_bindings = dict(candidate.logical_content_bindings)
        for component_id, component_identity in bindings:
            required_identity = required_identity_by_id.get(component_id)
            if required_identity is None:
                continue
            if component_identity != required_identity:
                raise ValueError("REBUILDABLE_COMPONENT_IDENTITY_MISMATCH")
            options[component_id].append(candidate)
            content_by_option[(component_id, candidate.cache_key or "")] = (
                content_bindings.get(component_id)
            )

    selected: dict[str, RebuildableStoreCandidateV1] = {}
    for component_id in sorted(options):
        component_options = options[component_id]
        if not component_options:
            continue
        content_hashes = {
            content_by_option[(component_id, candidate.cache_key or "")]
            for candidate in component_options
        }
        if len(component_options) > 1 and (
            None in content_hashes or len(content_hashes) != 1
        ):
            raise ValueError("REBUILDABLE_COMPONENT_CONTENT_CONFLICT")

        def rank(candidate: RebuildableStoreCandidateV1) -> tuple[int, int, str]:
            contained = frozenset(
                candidate.contained_logical_ids or (candidate.logical_id,)
            )
            return (
                -len(contained & required_ids),
                len(contained - required_ids),
                candidate.cache_key or "",
            )

        selected[component_id] = min(component_options, key=rank)
    return selected
