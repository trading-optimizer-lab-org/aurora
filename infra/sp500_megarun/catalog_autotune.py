"""Deterministic selection and regression gate for catalog execution plans."""

from __future__ import annotations

import json
from pathlib import Path
import statistics
from typing import Literal

from pydantic import Field, model_validator

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    Sha256,
    canonical_sha256,
)


ThermalState = Literal["cold", "component_warm", "fully_hot"]


class TuningCandidateV1(FrozenModel):
    workers: int = Field(ge=1, le=360)
    component_processes_per_worker: int = Field(default=1, ge=1, le=4)
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
    component_processes_per_worker: int = 1
    processes_per_worker: int
    block_size: int
    median_wall_seconds: float
    promoted: bool
    candidate_sha256: str
    sample_count: int = Field(default=0, ge=0)


class CatalogBenchmarkObservationV1(FrozenModel):
    run_id: int = Field(ge=1)
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    science_identity_sha256: Sha256
    thermal_state: ThermalState
    workers: int = Field(ge=1, le=360)
    component_processes_per_worker: int = Field(default=1, ge=1, le=4)
    processes_per_worker: int = Field(ge=1, le=4)
    block_size: int = Field(ge=1)
    wall_seconds: float = Field(gt=0)
    peak_memory_fraction: float = Field(gt=0)
    equivalent: bool
    validation_opened: Literal[False] = False
    locked_opened: Literal[False] = False


class CatalogPerformanceHistoryV1(FrozenModel):
    schema_version: Literal["1"] = "1"
    observations: tuple[CatalogBenchmarkObservationV1, ...]
    history_sha256: Sha256

    @classmethod
    def create(cls) -> CatalogPerformanceHistoryV1:
        identity = {"schema_version": "1", "observations": ()}
        return cls(**identity, history_sha256=canonical_sha256(identity))

    def _identity(self) -> dict[str, object]:
        return self.model_dump(mode="python", exclude={"history_sha256"})

    def append(
        self,
        observation: CatalogBenchmarkObservationV1,
    ) -> CatalogPerformanceHistoryV1:
        by_run = {item.run_id: item for item in self.observations}
        previous = by_run.get(observation.run_id)
        if previous is not None:
            if previous != observation:
                raise ValueError("CATALOG_AUTOTUNE_RUN_CONFLICT")
            return self
        observations = tuple(
            sorted((*self.observations, observation), key=lambda item: item.run_id)
        )
        identity = {"schema_version": "1", "observations": observations}
        return CatalogPerformanceHistoryV1(
            **identity,
            history_sha256=canonical_sha256(identity),
        )

    def write(self, path: Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(self.model_dump_json(indent=2) + "\n", "utf-8")
        temporary.replace(target)

    @classmethod
    def load(cls, path: Path) -> CatalogPerformanceHistoryV1:
        try:
            payload = json.loads(Path(path).read_text("utf-8"))
            history = cls.model_validate(payload)
        except (OSError, ValueError) as exc:
            raise ValueError("CATALOG_AUTOTUNE_HISTORY_INVALID") from exc
        if history.history_sha256 != canonical_sha256(history._identity()):
            raise ValueError("CATALOG_AUTOTUNE_HISTORY_HASH_INVALID")
        return history


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
            item.component_processes_per_worker,
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
        component_processes_per_worker=(
            winner.component_processes_per_worker
        ),
        processes_per_worker=winner.processes_per_worker,
        block_size=winner.block_size,
        median_wall_seconds=winner.median_wall_seconds,
        promoted=promoted,
        candidate_sha256=canonical_sha256(winner),
        sample_count=len(winner.wall_seconds_samples),
    )


def select_history_configuration(
    history: CatalogPerformanceHistoryV1,
    *,
    science_identity_sha256: str,
    thermal_state: ThermalState,
    minimum_samples: int,
    previous_best_median_seconds: float | None,
    max_regression_ratio: float,
    max_memory_fraction: float = 0.70,
) -> CatalogTuningDecisionV1:
    if minimum_samples < 3:
        raise ValueError("CATALOG_AUTOTUNE_MINIMUM_SAMPLES_INVALID")
    grouped: dict[tuple[int, int, int, int], list[CatalogBenchmarkObservationV1]] = {}
    for observation in history.observations:
        if (
            observation.science_identity_sha256 != science_identity_sha256
            or observation.thermal_state != thermal_state
        ):
            continue
        grouped.setdefault(
            (
                observation.workers,
                observation.component_processes_per_worker,
                observation.processes_per_worker,
                observation.block_size,
            ),
            [],
        ).append(observation)
    candidates = [
        TuningCandidateV1(
            workers=key[0],
            component_processes_per_worker=key[1],
            processes_per_worker=key[2],
            block_size=key[3],
            wall_seconds_samples=tuple(item.wall_seconds for item in observations),
            peak_memory_fraction=max(
                item.peak_memory_fraction for item in observations
            ),
            equivalent=all(item.equivalent for item in observations),
        )
        for key, observations in grouped.items()
        if len(observations) >= minimum_samples
    ]
    return select_catalog_configuration(
        candidates,
        previous_best_median_seconds=previous_best_median_seconds,
        max_regression_ratio=max_regression_ratio,
        max_memory_fraction=max_memory_fraction,
    )


__all__ = [
    "CatalogBenchmarkObservationV1",
    "CatalogPerformanceHistoryV1",
    "CatalogTuningDecisionV1",
    "ThermalState",
    "TuningCandidateV1",
    "select_catalog_configuration",
    "select_history_configuration",
]
