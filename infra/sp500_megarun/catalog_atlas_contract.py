"""Fail-closed contract for a finite static SP500 Atlas catalog run."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    Sha256,
    canonical_sha256,
)
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    RunOptimizationContractV1,
)


class AtlasTargetWindowV1(FrozenModel):
    """The planned wall-clock window used for sizing, not a hard cutoff."""

    target_end_iso: str = Field(min_length=1)
    available_minutes: float = Field(gt=0.0)
    safety_fraction: float = Field(ge=0.5, le=0.9)

    @field_validator("target_end_iso")
    @classmethod
    def _require_timezone(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("ATLAS_TARGET_END_INVALID_ISO") from exc
        if parsed.tzinfo is None:
            raise ValueError("ATLAS_TARGET_END_MISSING_TIMEZONE")
        return value


class AtlasCatalogSpecV1(FrozenModel):
    """Scope of one immutable Atlas catalog."""

    catalog_id: str = Field(min_length=1)
    catalog_dir: str = Field(min_length=1)
    train_end: Literal["2010-12-31"]
    validation_opened: Literal[False]
    locked_opened: Literal[False]
    include_inverses: Literal[True]
    max_strategy_arity: Literal[2]
    target_window: AtlasTargetWindowV1


class AtlasRunContractV1(FrozenModel):
    """Immutable admission identity for a static Atlas campaign."""

    schema_version: Literal["1"]
    mode: Literal["atlas_static"]
    science: object
    atlas: AtlasCatalogSpecV1
    optimization: RunOptimizationContractV1

    @property
    def contract_sha256(self) -> str:
        return canonical_sha256(self)

    @classmethod
    def load(cls, path: str) -> "AtlasRunContractV1":
        from pathlib import Path

        return cls.model_validate_json(Path(path).read_text("utf-8"))


__all__ = [
    "AtlasCatalogSpecV1",
    "AtlasRunContractV1",
    "AtlasTargetWindowV1",
]
