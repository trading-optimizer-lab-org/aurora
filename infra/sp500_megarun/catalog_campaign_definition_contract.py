"""Pure campaign-definition contracts shared across isolated runtimes."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .catalog_request_contract import (
    CAMPAIGN_KEY_PATTERN,
    FrozenModel,
    Sha256,
    canonical_model_bytes,
    canonical_sha256,
)


CatalogDefinitionRole = Literal[
    "contract",
    "schema",
    "configuration",
    "science_code",
    "workflow",
    "data_identity",
]


def _safe_repository_path(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("CATALOG_DEFINITION_PATH_INVALID")
    if value.startswith("/") or "\\" in value or "\x00" in value:
        raise ValueError("CATALOG_DEFINITION_PATH_INVALID")
    if any(ord(character) < 32 for character in value):
        raise ValueError("CATALOG_DEFINITION_PATH_INVALID")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("CATALOG_DEFINITION_PATH_INVALID")
    if any(":" in part for part in parts):
        raise ValueError("CATALOG_DEFINITION_PATH_INVALID")
    if parts[:2] == [".git", "objects"]:
        raise ValueError("CATALOG_DEFINITION_PATH_INVALID")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


class CatalogCampaignDefinitionEntryV1(FrozenModel):
    path: str
    role: CatalogDefinitionRole
    sha256: Sha256
    size_bytes: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def _require_safe_path(cls, value: str) -> str:
        return _safe_repository_path(value)

    @classmethod
    def from_bytes(
        cls,
        *,
        path: str,
        role: CatalogDefinitionRole,
        content: bytes,
    ) -> "CatalogCampaignDefinitionEntryV1":
        return cls(
            path=path,
            role=role,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )


class CatalogCampaignDefinitionManifestV1(FrozenModel):
    schema_version: Literal["1"]
    closure_algorithm: Literal["aurora-catalog-transitive-closure-v1"]
    campaign_key: str = Field(pattern=CAMPAIGN_KEY_PATTERN)
    registry_entry_sha256: Sha256
    entries: tuple[CatalogCampaignDefinitionEntryV1, ...]

    @model_validator(mode="after")
    def _require_canonical_complete_shape(
        self,
    ) -> "CatalogCampaignDefinitionManifestV1":
        if not self.entries:
            raise ValueError("CATALOG_DEFINITION_EMPTY")
        paths = tuple(entry.path for entry in self.entries)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("CATALOG_DEFINITION_ORDER_OR_DUPLICATE_INVALID")
        casefolded = tuple(path.casefold() for path in paths)
        if len(casefolded) != len(set(casefolded)):
            raise ValueError("CATALOG_DEFINITION_CASE_COLLISION")
        self_path = (
            "config/catalog_campaign_definitions/"
            f"{self.campaign_key}.manifest.json"
        )
        if self_path in paths:
            raise ValueError("CATALOG_DEFINITION_SELF_REFERENCE")
        return self

    @property
    def campaign_definition_sha256(self) -> str:
        return canonical_sha256(self)

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_model_bytes(self)


def parse_catalog_campaign_definition_bytes(
    data: bytes,
) -> CatalogCampaignDefinitionManifestV1:
    try:
        text = data.decode("utf-8")
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
        return CatalogCampaignDefinitionManifestV1.model_validate(payload)
    except Exception as exc:
        raise ValueError(f"CATALOG_CAMPAIGN_DEFINITION_INVALID: {exc}") from None


def registry_entry_sha256(value: FrozenModel) -> str:
    return canonical_sha256(value)


__all__ = [
    "CatalogCampaignDefinitionEntryV1",
    "CatalogCampaignDefinitionManifestV1",
    "CatalogDefinitionRole",
    "parse_catalog_campaign_definition_bytes",
    "registry_entry_sha256",
]
