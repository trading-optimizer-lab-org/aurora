from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aurora.infra.sp500_megarun.catalog_atlas_contract import (
    AtlasCatalogSpecV1,
    AtlasRunContractV1,
    AtlasTargetWindowV1,
)
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    CatalogAcceptanceV1,
    CatalogExecutionV1,
    CatalogLimitsV1,
    CatalogScienceIdentityV1,
    CatalogWorkloadV1,
    ComponentStoreExecutionV1,
    PayloadExecutionV1,
    PreparedInputExecutionV1,
    RebuildableStoreExecutionV1,
    RecoveryExecutionV1,
    RunOptimizationContractV1,
    RuntimePreparationV1,
)


HASH = "a" * 64


def _optimization() -> RunOptimizationContractV1:
    return RunOptimizationContractV1(
        schema_version="1",
        optimization_mode="required",
        allow_unoptimized_run=False,
        infrastructure_sha256=HASH,
        science=CatalogScienceIdentityV1(
            evaluator_sha256=HASH,
            data_snapshot_sha256=HASH,
            catalog_manifest_sha256=HASH,
            train_end="2010-12-31",
            validation_opened=False,
            locked_opened=False,
            numeric_profile="atlas-test",
        ),
        workload=CatalogWorkloadV1(
            requested_recipes=100,
            canonical_recipes=100,
            unique_components=10,
            expected_new_recipes=100,
            expected_prior_cache_hits=0,
            estimated_position_equivalences=0,
        ),
        execution=CatalogExecutionV1(
            scheduler_version="test",
            workers=10,
            component_workers=10,
            component_processes_per_worker=1,
            processes_per_worker=1,
            block_size=10,
            component_replication_budget=0,
            retry_only_unfinished=True,
            checkpoint_interval_seconds=60,
        ),
        limits=CatalogLimitsV1(
            max_result_bytes_per_recipe=1024,
            max_expected_tail_ratio_p99_p50=4.0,
            max_redundant_component_build_ratio=0.0,
            max_memory_fraction=0.7,
        ),
        acceptance=CatalogAcceptanceV1(
            require_reference_equivalence=True,
            require_cold_and_hot_benchmarks=True,
            require_verified_manifest=True,
            max_performance_regression_ratio=0.05,
        ),
        runtime_preparation=RuntimePreparationV1(
            build_once_per_runtime_identity=True,
            reuse_verified_runtime_store_required=True,
            dependency_lock_required=True,
            worker_network_install_allowed=False,
            wheelhouse_sha256_required=True,
            runtime_mode="offline_wheelhouse",
        ),
        component_store_execution=ComponentStoreExecutionV1(
            build_before_recipe_evaluation=True,
            global_deduplication=True,
            recipe_worker_build_allowed=False,
            exact_component_bundles=True,
            conflicting_successes_block=True,
            consumer_hypergraph_partition_required=True,
            component_download_amplification_receipt_required=True,
            qualified_bundle_count_required=True,
        ),
        payload_execution=PayloadExecutionV1(
            exact_assignment_member_only=True,
            exact_data_partitions_only=True,
            exact_component_bundles_only=True,
            download_all_attempts_allowed=False,
            download_all_checkpoints_allowed=False,
        ),
        prepared_input_execution=PreparedInputExecutionV1(
            prepare_once_per_input_identity=True,
            reuse_verified_partitions_required=True,
            partial_store_build_missing_only=True,
            approximate_substitution_allowed=False,
        ),
        rebuildable_store_execution=RebuildableStoreExecutionV1(
            actions_cache_preferred=True,
            cache_authoritative_evidence_allowed=False,
            repository_cache_limit_gb=10,
            repository_cache_retention_days=90,
            paid_cache_storage_allowed=False,
            component_cache_bundle_count_options=(8, 16, 32, 64, 96, 128),
            maximum_new_cache_entries_per_campaign=160,
            maximum_component_cache_bundles_per_campaign=128,
            maximum_cache_upload_requests_per_minute=160,
            maximum_cache_download_requests_per_minute=1200,
            persistent_duplicate_payload_artifact_allowed=False,
            same_run_transport_artifact_max_retention_days=1,
        ),
        recovery_execution=RecoveryExecutionV1(
            checkpoint_required=True,
            checkpoint_slot_options=(1, 2, 4, 8),
            maximum_unpersisted_seconds_p99=600,
            maximum_checkpoint_overhead_fraction_p95=0.05,
            valid_work_reuse_required=True,
            global_rerun_allowed=False,
            max_same_failure_occurrences=3,
        ),
    )


def _contract(**changes: object) -> AtlasRunContractV1:
    target = AtlasTargetWindowV1(
        target_end_iso="2026-08-20T07:31:00+02:00",
        available_minutes=4091.1666667,
        safety_fraction=0.8,
    )
    atlas = AtlasCatalogSpecV1(
        catalog_id="sp500-atlas-1",
        catalog_dir="config/sp500_atlas_1",
        train_end="2010-12-31",
        validation_opened=False,
        locked_opened=False,
        include_inverses=True,
        max_strategy_arity=2,
        target_window=target,
    )
    payload = {
        "schema_version": "1",
        "mode": "atlas_static",
        "science": {
            "evaluator_sha256": HASH,
            "data_snapshot_sha256": HASH,
            "catalog_manifest_sha256": HASH,
            "train_end": "2010-12-31",
            "validation_opened": False,
            "locked_opened": False,
            "numeric_profile": "atlas-test",
        },
        "atlas": atlas,
        "optimization": _optimization(),
    }
    payload.update(changes)
    return AtlasRunContractV1(**payload)


def test_contract_is_train_only_and_hash_bound() -> None:
    contract = _contract()
    assert contract.atlas.validation_opened is False
    assert contract.atlas.locked_opened is False
    assert len(contract.contract_sha256) == 64
    changed = _contract(
        science={
            "evaluator_sha256": "b" * 64,
            "data_snapshot_sha256": HASH,
            "catalog_manifest_sha256": HASH,
            "train_end": "2010-12-31",
            "validation_opened": False,
            "locked_opened": False,
            "numeric_profile": "atlas-test",
        },
    )
    assert changed.contract_sha256 != contract.contract_sha256


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("train_end", "2011-12-31"),
        ("validation_opened", True),
        ("locked_opened", True),
        ("include_inverses", False),
        ("max_strategy_arity", 3),
    ],
)
def test_contract_rejects_protected_or_out_of_scope_values(
    field: str,
    value: object,
) -> None:
    atlas = {
        "catalog_id": "sp500-atlas-1",
        "catalog_dir": "config/sp500_atlas_1",
        "train_end": "2010-12-31",
        "validation_opened": False,
        "locked_opened": False,
        "include_inverses": True,
        "max_strategy_arity": 2,
        "target_window": {
            "target_end_iso": "2026-08-20T07:31:00+02:00",
            "available_minutes": 4091.0,
            "safety_fraction": 0.8,
        },
    }
    atlas[field] = value
    with pytest.raises(ValueError):
        AtlasRunContractV1(
            schema_version="1",
            mode="atlas_static",
            science={"identity": HASH},
            atlas=atlas,
            optimization=_optimization(),
        )


@pytest.mark.parametrize(
    "target_end",
    ["2026-08-20T07:31:00", "not-a-date"],
)
def test_target_end_requires_timezone_and_valid_iso(target_end: str) -> None:
    with pytest.raises(ValueError):
        AtlasTargetWindowV1(
            target_end_iso=target_end,
            available_minutes=1.0,
            safety_fraction=0.8,
        )
