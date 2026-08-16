"""Deterministic selection and regression gate for catalog execution plans."""

from __future__ import annotations

import statistics

from pydantic import Field, model_validator

from aurora.infra.github_performance.contracts import FrozenModel, canonical_sha256


class TuningCandidateV1(FrozenModel):
    workers: int = Field(ge=1, le=360)
    processes_per_worker: int = Field(ge=1, le=4)
    block_size: int = Field(ge=1)
    wall_seconds_samples: tuple[float, ...]
    peak_memory_fraction: float = Field(gt=0)
    equivalent: bool

    @model_validator(mode="after")
    def _samples_valid(self) -> TuningCandidateV1:
        if len(self.wall_seconds_samples) < 3 or any(
            value <= 0 for value in self.wall_seconds_samples
        ):
            raise ValueError("CATALOG_TUNING_SAMPLES_INVALID")
        return self

    @property
    def median_wall_seconds(self) -> float:
        return float(statistics.median(self.wall_seconds_samples))


class CatalogTuningDecisionV1(FrozenModel):
    workers: int
    processes_per_worker: int
    block_size: int
    median_wall_seconds: float
    promoted: bool
    candidate_sha256: str


def select_catalog_configuration(
    candidates: list[TuningCandidateV1],
    *,
    previous_best_median_seconds: float | None,
    max_regression_ratio: float,
    max_memory_fraction: float = 0.70,
) -> CatalogTuningDecisionV1:
    eligible = [
        item
        for item in candidates
        if item.equivalent and item.peak_memory_fraction <= max_memory_fraction
    ]
    if not eligible:
        raise ValueError("CATALOG_TUNING_NO_SAFE_EQUIVALENT_CANDIDATE")
    winner = min(
        eligible,
        key=lambda item: (
            item.median_wall_seconds,
            item.workers,
            item.processes_per_worker,
            item.block_size,
        ),
    )
    if (
        previous_best_median_seconds is not None
        and winner.median_wall_seconds
        > previous_best_median_seconds * (1.0 + max_regression_ratio)
    ):
        raise ValueError("CATALOG_PERFORMANCE_REGRESSION")
    promoted = (
        previous_best_median_seconds is None
        or winner.median_wall_seconds <= previous_best_median_seconds
    )
    return CatalogTuningDecisionV1(
        workers=winner.workers,
        processes_per_worker=winner.processes_per_worker,
        block_size=winner.block_size,
        median_wall_seconds=winner.median_wall_seconds,
        promoted=promoted,
        candidate_sha256=canonical_sha256(winner),
    )


__all__ = [
    "CatalogTuningDecisionV1",
    "TuningCandidateV1",
    "select_catalog_configuration",
]
