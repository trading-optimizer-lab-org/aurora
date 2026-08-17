"""Fail-closed optimization contract for every SP500 catalog run."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from aurora.infra.github_performance.contracts import (
    FrozenModel,
    Sha256,
    canonical_sha256,
)


PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
UnitFraction = Annotated[float, Field(ge=0.0, le=1.0)]


class CatalogScienceIdentityV1(FrozenModel):
    evaluator_sha256: Sha256
    data_snapshot_sha256: Sha256
    catalog_manifest_sha256: Sha256
    train_end: Literal["2010-12-31"]
    validation_opened: Literal[False]
    locked_opened: Literal[False]
    numeric_profile: str = Field(min_length=1)


class CatalogWorkloadV1(FrozenModel):
    requested_recipes: PositiveInt
    canonical_recipes: PositiveInt
    unique_components: PositiveInt
    expected_new_recipes: NonNegativeInt
    expected_prior_cache_hits: NonNegativeInt
    estimated_position_equivalences: NonNegativeInt

    @model_validator(mode="after")
    def _validate_counts(self) -> CatalogWorkloadV1:
        if self.canonical_recipes > self.requested_recipes:
            raise ValueError("canonical recipes exceed requested recipes")
        if (
            self.expected_new_recipes + self.expected_prior_cache_hits
            != self.canonical_recipes
        ):
            raise ValueError("new recipes and cache hits must reconcile")
        if self.estimated_position_equivalences > self.canonical_recipes:
            raise ValueError("position equivalences exceed canonical recipes")
        return self


class CatalogExecutionV1(FrozenModel):
    scheduler_version: str = Field(min_length=1)
    workers: Annotated[int, Field(ge=1, le=360)]
    component_workers: Annotated[int, Field(ge=1, le=120)]
    component_processes_per_worker: Annotated[int, Field(ge=1, le=4)]
    processes_per_worker: Annotated[int, Field(ge=1, le=4)]
    block_size: PositiveInt
    component_replication_budget: NonNegativeInt
    retry_only_unfinished: Literal[True]
    checkpoint_interval_seconds: PositiveInt


class CatalogLimitsV1(FrozenModel):
    max_result_bytes_per_recipe: PositiveInt
    max_expected_tail_ratio_p99_p50: Annotated[float, Field(ge=1.0)]
    max_redundant_component_build_ratio: UnitFraction
    max_memory_fraction: Annotated[float, Field(gt=0.0, le=0.95)]


class CatalogAcceptanceV1(FrozenModel):
    require_reference_equivalence: Literal[True]
    require_cold_and_hot_benchmarks: Literal[True]
    require_verified_manifest: Literal[True]
    max_performance_regression_ratio: UnitFraction


class RunOptimizationContractV1(FrozenModel):
    """Immutable evidence that one catalog run cannot bypass optimization."""

    schema_version: Literal["1"]
    optimization_mode: Literal["required"]
    allow_unoptimized_run: Literal[False]
    infrastructure_sha256: Sha256
    science: CatalogScienceIdentityV1
    workload: CatalogWorkloadV1
    execution: CatalogExecutionV1
    limits: CatalogLimitsV1
    acceptance: CatalogAcceptanceV1

    @model_validator(mode="after")
    def _validate_replication_budget(self) -> RunOptimizationContractV1:
        ratio = (
            self.execution.component_replication_budget
            / self.workload.unique_components
        )
        if ratio > self.limits.max_redundant_component_build_ratio:
            raise ValueError("component replication budget exceeds limit")
        return self

    @property
    def contract_sha256(self) -> str:
        return canonical_sha256(self)


__all__ = [
    "CatalogAcceptanceV1",
    "CatalogExecutionV1",
    "CatalogLimitsV1",
    "CatalogScienceIdentityV1",
    "CatalogWorkloadV1",
    "RunOptimizationContractV1",
]
