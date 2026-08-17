"""Contracts and bounded sizing helpers for the Atlas calibration."""

from __future__ import annotations

from datetime import datetime
from math import floor
from typing import Literal

from pydantic import Field

from aurora.infra.github_performance.contracts import FrozenModel, Sha256, canonical_sha256


class AtlasCalibrationReceiptV1(FrozenModel):
    schema_version: Literal["1"]
    catalog_sha256: Sha256
    started_at_iso: str = Field(min_length=1)
    stopped_at_iso: str = Field(min_length=1)
    wall_seconds: float = Field(ge=0.0, le=1200.0)
    hard_limit_seconds: Literal[1200.0]
    timed_out_cleanly: bool
    physical_recipe_count: int = Field(ge=0)
    cache_hit_count: int = Field(ge=0)
    physical_component_count: int = Field(ge=0)
    physical_component_seconds: float = Field(ge=0.0)
    recipe_seconds: float = Field(ge=0.0)
    result_store_seconds: float = Field(ge=0.0)
    recipes_per_minute: float = Field(ge=0.0)
    recommended_mode: Literal["cold", "component_warm"]
    available_minutes_to_target: float = Field(ge=0.0)
    safety_fraction: float = Field(ge=0.5, le=0.9)
    target_recipe_count_with_margin: int = Field(ge=0)
    validation_opened: Literal[False]
    locked_opened: Literal[False]

    @property
    def receipt_sha256(self) -> str:
        return canonical_sha256(self)


def target_minutes(
    *,
    now_iso: str,
    target_end_iso: str,
) -> float:
    """Return non-negative minutes between two timezone-aware timestamps."""

    now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    target = datetime.fromisoformat(target_end_iso.replace("Z", "+00:00"))
    if now.tzinfo is None or target.tzinfo is None:
        raise ValueError("ATLAS_TARGET_TIMEZONE_REQUIRED")
    return max(0.0, (target - now).total_seconds() / 60.0)


def target_recipe_count(
    *,
    available_minutes: float,
    recipes_per_minute: float,
    safety_fraction: float = 0.80,
) -> int:
    if available_minutes < 0.0 or recipes_per_minute < 0.0:
        raise ValueError("ATLAS_TARGET_SIZING_INPUT_INVALID")
    if not 0.5 <= safety_fraction <= 0.9:
        raise ValueError("ATLAS_TARGET_SAFETY_INVALID")
    return max(0, floor(available_minutes * recipes_per_minute * safety_fraction))


__all__ = [
    "AtlasCalibrationReceiptV1",
    "target_minutes",
    "target_recipe_count",
]
