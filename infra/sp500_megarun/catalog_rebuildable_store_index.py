"""Immutable evidence indexes for verified rebuildable catalog caches."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    Sha256,
    canonical_sha256,
)

from .catalog_rebuildable_store import (
    RebuildableStoreCandidateV1,
    RebuildableStoreInventoryV1,
)


CommitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Repository = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"),
]
AuthorityId = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}$"
        )
    ),
]
WriterWorkflow = Literal[
    ".github/workflows/catalog-optimized-run.yml",
]


class CatalogRebuildableStoreIndexV1(FrozenModel):
    """One mirror-first index produced after exact cache content verification."""

    schema_version: Literal["1"] = "1"
    artifact_name: Literal["catalog-rebuildable-store-index-v1"]
    repository: Repository
    writer_workflow: WriterWorkflow
    writer_run_id: int = Field(ge=1)
    writer_run_attempt: int = Field(ge=1)
    protected_commit_sha: CommitSha
    source_branch: Literal["main"]
    authority_id: AuthorityId
    campaign_id: Sha256
    science_sha256: Sha256
    execution_plan_sha256: Sha256
    execution_protocol_sha256: Sha256
    candidates: tuple[RebuildableStoreCandidateV1, ...]
    validation_opened: Literal[False] = False
    locked_opened: Literal[False] = False
    index_sha256: Sha256

    @field_validator("candidates")
    @classmethod
    def _require_canonical_candidates(
        cls,
        value: tuple[RebuildableStoreCandidateV1, ...],
    ) -> tuple[RebuildableStoreCandidateV1, ...]:
        keys = tuple(_candidate_sort_key(candidate) for candidate in value)
        if not value or keys != tuple(sorted(set(keys))):
            raise ValueError("CATALOG_STORE_INDEX_CANDIDATES_INVALID")
        if any(
            candidate.status != "verified"
            or candidate.storage_kind != "actions_cache"
            or candidate.source_branch != "main"
            or (
                candidate.object_family == "component"
                and (
                    not candidate.logical_content_bindings
                    or tuple(
                        item[0] for item in candidate.logical_content_bindings
                    )
                    != candidate.contained_logical_ids
                )
            )
            for candidate in value
        ):
            raise ValueError("CATALOG_STORE_INDEX_CANDIDATES_INVALID")
        return value

    @model_validator(mode="after")
    def _verify_hash(self) -> "CatalogRebuildableStoreIndexV1":
        identity = self.model_dump(mode="json", exclude={"index_sha256"})
        if self.index_sha256 != canonical_sha256(identity):
            raise ValueError("CATALOG_STORE_INDEX_HASH_INVALID")
        return self

    @classmethod
    def create(cls, **values: object) -> "CatalogRebuildableStoreIndexV1":
        raw_candidates = values.get("candidates")
        if not isinstance(raw_candidates, tuple | list):
            raise ValueError("CATALOG_STORE_INDEX_CANDIDATES_INVALID")
        candidates = tuple(
            sorted(
                (
                    item
                    if isinstance(item, RebuildableStoreCandidateV1)
                    else RebuildableStoreCandidateV1.model_validate(item)
                    for item in raw_candidates
                ),
                key=_candidate_sort_key,
            )
        )
        identity = {
            "schema_version": "1",
            **values,
            "candidates": [item.model_dump(mode="json") for item in candidates],
            "validation_opened": False,
            "locked_opened": False,
        }
        identity.pop("index_sha256", None)
        return cls.model_validate(
            {**identity, "index_sha256": canonical_sha256(identity)}
        )


def _candidate_sort_key(
    candidate: RebuildableStoreCandidateV1,
) -> tuple[str, ...]:
    return (
        candidate.object_family,
        candidate.logical_id,
        candidate.identity_sha256,
        candidate.content_manifest_sha256,
        candidate.content_sha256,
        candidate.cache_key or "",
        canonical_sha256(candidate.model_dump(mode="json")),
    )


def inventory_from_verified_indexes(
    indexes: tuple[CatalogRebuildableStoreIndexV1, ...],
    *,
    live_cache_keys: frozenset[str],
    runtime_source_commit_sha: str | None = None,
) -> RebuildableStoreInventoryV1:
    """Keep only exact indexes whose immutable cache key still exists."""

    candidates: dict[tuple[str, ...], RebuildableStoreCandidateV1] = {}
    for index in indexes:
        for candidate in index.candidates:
            # Runtime manifests bind source commits; data/components retain their
            # independent content identities and remain reusable across commits.
            if (
                candidate.object_family == "runtime"
                and runtime_source_commit_sha is not None
                and index.protected_commit_sha != runtime_source_commit_sha
            ):
                continue
            if candidate.cache_key not in live_cache_keys:
                continue
            candidates[_candidate_sort_key(candidate)] = candidate
    return RebuildableStoreInventoryV1(
        listing_complete=True,
        source_branch="main",
        candidates=tuple(candidates[key] for key in sorted(candidates)),
    )
