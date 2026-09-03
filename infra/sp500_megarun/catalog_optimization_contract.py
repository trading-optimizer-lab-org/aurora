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
    component_workers: Annotated[int, Field(ge=1, le=360)]
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


class RuntimePreparationV1(FrozenModel):
    build_once_per_runtime_identity: Literal[True]
    reuse_verified_runtime_store_required: Literal[True]
    dependency_lock_required: Literal[True]
    worker_network_install_allowed: Literal[False]
    wheelhouse_sha256_required: Literal[True]
    runtime_mode: Literal[
        "verified_relocatable_archive",
        "offline_wheelhouse",
    ]


class ComponentStoreExecutionV1(FrozenModel):
    build_before_recipe_evaluation: Literal[True]
    global_deduplication: Literal[True]
    recipe_worker_build_allowed: Literal[False]
    exact_component_bundles: Literal[True]
    conflicting_successes_block: Literal[True]
    consumer_hypergraph_partition_required: Literal[True]
    component_download_amplification_receipt_required: Literal[True]
    qualified_bundle_count_required: Literal[True]


class PayloadExecutionV1(FrozenModel):
    exact_assignment_member_only: Literal[True]
    exact_data_partitions_only: Literal[True]
    exact_component_bundles_only: Literal[True]
    download_all_attempts_allowed: Literal[False]
    download_all_checkpoints_allowed: Literal[False]


class PreparedInputExecutionV1(FrozenModel):
    prepare_once_per_input_identity: Literal[True]
    reuse_verified_partitions_required: Literal[True]
    partial_store_build_missing_only: Literal[True]
    approximate_substitution_allowed: Literal[False]


class RebuildableStoreExecutionV1(FrozenModel):
    actions_cache_preferred: Literal[True]
    cache_authoritative_evidence_allowed: Literal[False]
    repository_cache_limit_gb: Literal[10]
    repository_cache_retention_days: Literal[90]
    paid_cache_storage_allowed: Literal[False]
    component_cache_bundle_count_options: tuple[
        Literal[8, 16, 32, 64, 96, 128],
        ...,
    ]
    maximum_new_cache_entries_per_campaign: Literal[160]
    maximum_component_cache_bundles_per_campaign: Literal[128]
    maximum_cache_upload_requests_per_minute: Literal[160]
    maximum_cache_download_requests_per_minute: Literal[1200]
    persistent_duplicate_payload_artifact_allowed: Literal[False]
    same_run_transport_artifact_max_retention_days: Literal[1]

    @model_validator(mode="after")
    def _validate_bundle_options(self) -> RebuildableStoreExecutionV1:
        if self.component_cache_bundle_count_options != (8, 16, 32, 64, 96, 128):
            raise ValueError("CATALOG_COMPONENT_BUNDLE_OPTIONS_INVALID")
        return self


class RecoveryExecutionV1(FrozenModel):
    checkpoint_required: Literal[True]
    checkpoint_slot_options: tuple[Literal[1, 2, 4, 8], ...]
    maximum_unpersisted_seconds_p99: Literal[600]
    maximum_checkpoint_overhead_fraction_p95: Literal[0.05]
    valid_work_reuse_required: Literal[True]
    global_rerun_allowed: Literal[False]
    max_same_failure_occurrences: Literal[3]
    max_total_recovery_waves: Annotated[int, Field(ge=1, le=6)] = 6

    @model_validator(mode="after")
    def _validate_checkpoint_options(self) -> RecoveryExecutionV1:
        if self.checkpoint_slot_options != (1, 2, 4, 8):
            raise ValueError("CATALOG_CHECKPOINT_SLOT_OPTIONS_INVALID")
        return self


class CatalogComponentIdentityV1(FrozenModel):
    """Every scientific field that can change one reusable component."""

    evaluator_sha256: Sha256
    data_snapshot_sha256: Sha256
    numeric_profile_sha256: Sha256
    feature_definition_sha256: Sha256
    parameters_sha256: Sha256
    dtype_sha256: Sha256
    output_schema_sha256: Sha256

    @property
    def component_key_sha256(self) -> str:
        return canonical_sha256(self)


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
    runtime_preparation: RuntimePreparationV1
    component_store_execution: ComponentStoreExecutionV1
    payload_execution: PayloadExecutionV1
    prepared_input_execution: PreparedInputExecutionV1
    rebuildable_store_execution: RebuildableStoreExecutionV1
    recovery_execution: RecoveryExecutionV1

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
    "CatalogComponentIdentityV1",
    "CatalogExecutionV1",
    "CatalogLimitsV1",
    "CatalogScienceIdentityV1",
    "CatalogWorkloadV1",
    "ComponentStoreExecutionV1",
    "PayloadExecutionV1",
    "PreparedInputExecutionV1",
    "RebuildableStoreExecutionV1",
    "RecoveryExecutionV1",
    "RunOptimizationContractV1",
    "RuntimePreparationV1",
]
