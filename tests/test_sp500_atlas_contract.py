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
    RunOptimizationContractV1,
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
        "science": {"identity": HASH},
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
        science={"identity": "b" * 64},
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
