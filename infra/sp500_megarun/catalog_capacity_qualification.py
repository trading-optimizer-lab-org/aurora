"""Closed operational qualification models shared by planner and admission."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from aurora.infra.github_performance.contracts import FrozenModel


PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
BundleCount = Literal[8, 16, 32, 64, 96, 128]


class BundleLayoutQualificationV1(FrozenModel):
    """Measured evidence for one fixed component-bundle layout."""

    bundle_count: BundleCount
    equivalent: Literal[True]
    sample_count: Annotated[int, Field(ge=0)]
    memory_safe: bool
    disk_safe: bool
    runner_timeout_safe: bool
    projected_end_to_end_p50_seconds: float = Field(gt=0)
    projected_end_to_end_p95_seconds: float = Field(gt=0)
    projected_component_download_bytes: PositiveInt
    projected_cache_uploads_per_minute: NonNegativeInt
    projected_cache_downloads_per_minute: NonNegativeInt
    checkpoint_upload_seconds_p95: float = Field(ge=0)

    @model_validator(mode="after")
    def _validate_percentiles(self) -> "BundleLayoutQualificationV1":
        if (
            self.projected_end_to_end_p95_seconds
            < self.projected_end_to_end_p50_seconds
        ):
            raise ValueError("CATALOG_LAYOUT_PERCENTILES_INVALID")
        return self
