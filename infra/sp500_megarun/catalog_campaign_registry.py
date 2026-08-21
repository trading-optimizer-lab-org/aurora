"""Closed catalog campaign registry with repository-safe path resolution."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, field_validator

from .catalog_request_contract import FrozenModel


_PATH_FIELDS = (
    "definition_manifest_path",
    "optimization_policy_path",
    "campaign_contract_path",
    "catalog_dir",
    "selected_config_path",
    "admission_evidence_path",
    "data_contract_path",
    "feature_contract_path",
)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _validate_repository_path(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("repository path must be non-empty and trimmed")
    if "\\" in value or "\x00" in value:
        raise ValueError("repository path contains a forbidden character")
    if any(ord(character) < 32 for character in value):
        raise ValueError("repository path contains a control character")

    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ValueError("repository path contains an unsafe segment")
    if any(":" in part for part in raw_parts):
        raise ValueError("repository path contains a drive or stream marker")

    pure = PurePosixPath(value)
    if pure.is_absolute() or pure.anchor:
        raise ValueError("repository path must be relative")
    lowered = tuple(part.casefold() for part in pure.parts)
    if lowered[:2] == (".github", "workflows"):
        raise ValueError("workflow paths cannot be supplied as campaign data")
    if pure.as_posix() != value:
        raise ValueError("repository path must use canonical POSIX form")
    return value


class CatalogCampaignEntryV1(FrozenModel):
    campaign_key: str
    engine_id: Literal["optimized_catalog_v1"]
    definition_manifest_path: str
    optimization_policy_path: str
    campaign_contract_path: str
    catalog_dir: str
    selected_config_path: str
    admission_evidence_path: str
    data_contract_path: str
    feature_contract_path: str
    runtime_input_run_id: int = Field(ge=1)
    reference_run_id: int = Field(ge=1)
    max_free_workers: int = Field(ge=1, le=360)
    active: bool

    @field_validator(*_PATH_FIELDS)
    @classmethod
    def _require_safe_repository_path(cls, value: str) -> str:
        return _validate_repository_path(value)

    @property
    def repository_paths(self) -> tuple[str, ...]:
        return (
            self.optimization_policy_path,
            self.campaign_contract_path,
            self.catalog_dir,
            self.selected_config_path,
            self.admission_evidence_path,
            self.data_contract_path,
            self.feature_contract_path,
        )

    def select_safe_worker_ceiling(
        self,
        *,
        compatible_qualified_ceiling: int,
        current_safe_free_capacity: int,
    ) -> int:
        """Return the strictest independently established free-worker ceiling."""
        values = (compatible_qualified_ceiling, current_safe_free_capacity)
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in values):
            raise ValueError("CATALOG_WORKER_CEILING_INVALID")
        return min(self.max_free_workers, *values)


class CatalogCampaignRegistryV1(FrozenModel):
    schema_version: Literal["1"]
    campaigns: tuple[CatalogCampaignEntryV1, ...]


def load_catalog_campaign_registry(path: Path) -> CatalogCampaignRegistryV1:
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
        return CatalogCampaignRegistryV1.model_validate(payload)
    except Exception as exc:
        raise ValueError(f"CATALOG_REGISTRY_INVALID: {exc}") from None


def resolve_catalog_campaign(
    registry: CatalogCampaignRegistryV1,
    campaign_key: str,
    repo_root: Path,
) -> CatalogCampaignEntryV1:
    matches = tuple(
        campaign
        for campaign in registry.campaigns
        if campaign.active and campaign.campaign_key == campaign_key
    )
    if len(matches) != 1:
        raise ValueError("CATALOG_CAMPAIGN_UNRESOLVED")

    entry = matches[0]
    try:
        root = repo_root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("repository root is not a directory")
        resolved_paths = tuple(
            (root / PurePosixPath(value)).resolve(strict=False)
            for value in entry.repository_paths
        )
        if any(not path.is_relative_to(root) for path in resolved_paths):
            raise ValueError("repository path escapes root")
        if any(not path.exists() for path in resolved_paths):
            raise ValueError("repository path does not exist")
    except Exception as exc:
        raise ValueError(f"CATALOG_CAMPAIGN_PATH_INVALID: {exc}") from None
    return entry

