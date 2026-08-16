"""Robust train-only cost estimates for optimized catalog planning."""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence

from pydantic import Field

from aurora.infra.github_performance.contracts import FrozenModel, canonical_sha256


class ComponentCostV1(FrozenModel):
    component_id: str = Field(min_length=1)
    median_seconds: float = Field(gt=0)
    p95_seconds: float = Field(gt=0)
    sample_count: int = Field(ge=1)


class CatalogCostModelV1(FrozenModel):
    schema_version: str = "1"
    components: tuple[ComponentCostV1, ...]
    fallback_seconds: float = Field(gt=0)
    model_sha256: str

    @classmethod
    def from_samples(
        cls,
        samples: Mapping[str, Sequence[float]],
        *,
        fallback_seconds: float,
    ) -> CatalogCostModelV1:
        entries: list[ComponentCostV1] = []
        for component_id, raw_values in sorted(samples.items()):
            values = tuple(float(value) for value in raw_values)
            if not values or not all(math.isfinite(value) and value > 0 for value in values):
                raise ValueError("CATALOG_COST_SAMPLE_INVALID")
            ordered = sorted(values)
            p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
            entries.append(
                ComponentCostV1(
                    component_id=component_id,
                    median_seconds=statistics.median(ordered),
                    p95_seconds=ordered[p95_index],
                    sample_count=len(ordered),
                )
            )
        identity = {
            "schema_version": "1",
            "components": entries,
            "fallback_seconds": float(fallback_seconds),
        }
        return cls(**identity, model_sha256=canonical_sha256(identity))

    def estimate(self, component_id: str, *, conservative: bool = True) -> float:
        for item in self.components:
            if item.component_id == component_id:
                return item.p95_seconds if conservative else item.median_seconds
        return self.fallback_seconds


__all__ = ["CatalogCostModelV1", "ComponentCostV1"]
