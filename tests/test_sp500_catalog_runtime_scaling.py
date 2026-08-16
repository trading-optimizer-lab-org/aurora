from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


def test_persistent_cache_reuses_only_exact_science_and_detects_conflict(
    tmp_path: Path,
) -> None:
    from aurora.infra.sp500_megarun.catalog_evaluation_cache import (
        CatalogEvaluationCache,
        EvaluationCacheKeyV1,
    )

    cache = CatalogEvaluationCache(tmp_path / "cache")
    key = EvaluationCacheKeyV1(
        evaluator_sha256="a" * 64,
        data_snapshot_sha256="b" * 64,
        recipe_sha256="c" * 64,
        numeric_profile="cpu-f64-v1",
    )
    first = {"annualized_return": 0.12, "position_sha256": "d" * 64}
    assert cache.put(key, first, origin="physical") is True
    assert cache.put(key, dict(first), origin="physical") is False
    hit = cache.get(key)
    assert hit is not None
    assert hit.result == first
    assert hit.origin == "physical"
    with pytest.raises(ValueError, match="EVALUATION_CACHE_CONFLICT"):
        cache.put(key, {**first, "annualized_return": 0.13}, origin="physical")
    incompatible = key.model_copy(update={"data_snapshot_sha256": "e" * 64})
    assert cache.get(incompatible) is None


def test_adaptive_process_topology_requires_speed_and_safe_memory() -> None:
    from aurora.infra.sp500_megarun.catalog_multiprocessing import (
        ProcessBenchmarkV1,
        select_process_topology,
    )

    selected = select_process_topology(
        [
            ProcessBenchmarkV1(processes=1, wall_seconds=100, peak_memory_bytes=2_000),
            ProcessBenchmarkV1(processes=2, wall_seconds=60, peak_memory_bytes=3_000),
            ProcessBenchmarkV1(processes=4, wall_seconds=45, peak_memory_bytes=5_000),
        ],
        available_memory_bytes=10_000,
    )
    assert selected.processes == 4
    assert selected.speedup_vs_one > 2.0

    fallback = select_process_topology(
        [
            ProcessBenchmarkV1(processes=1, wall_seconds=100, peak_memory_bytes=2_000),
            ProcessBenchmarkV1(processes=4, wall_seconds=95, peak_memory_bytes=8_000),
        ],
        available_memory_bytes=10_000,
    )
    assert fallback.processes == 1


def test_microshard_checkpoint_resumes_only_pending_units(tmp_path: Path) -> None:
    from aurora.infra.sp500_megarun.catalog_checkpoint import CatalogCheckpoint

    checkpoint = CatalogCheckpoint.create(
        tmp_path / "checkpoint.json",
        plan_sha256="a" * 64,
        unit_ids=("u0", "u1", "u2"),
    )
    checkpoint = checkpoint.commit("u1", result_sha256="b" * 64)
    restored = CatalogCheckpoint.load(tmp_path / "checkpoint.json")

    assert restored.completed_unit_ids == ("u1",)
    assert restored.pending_unit_ids == ("u0", "u2")
    assert restored.checkpoint_sha256 == checkpoint.checkpoint_sha256
    with pytest.raises(ValueError, match="CHECKPOINT_RESULT_CONFLICT"):
        restored.commit("u1", result_sha256="c" * 64)


def test_columnar_result_store_is_partitioned_verified_and_streamable(
    tmp_path: Path,
) -> None:
    from aurora.infra.sp500_megarun.catalog_result_store import (
        CatalogResultStore,
        CatalogResultWriter,
    )

    writer = CatalogResultWriter(
        tmp_path / "results",
        contract_sha256="a" * 64,
        partition_size=2,
    )
    for index in range(5):
        writer.add(
            {
                "strategy_id": f"s{index}",
                "recipe_sha256": f"{index + 1:064x}",
                "position_sha256": f"{index + 11:064x}",
                "annualized_return": index / 100,
                "weekly_positive_rate": 0.5 + index / 100,
            }
        )
    manifest = writer.commit()
    store = CatalogResultStore.open(tmp_path / "results")

    assert manifest.row_count == 5
    assert manifest.partition_count == 3
    assert [row["strategy_id"] for row in store.iter_rows()] == [
        "s0",
        "s1",
        "s2",
        "s3",
        "s4",
    ]
    assert manifest.validation_opened is False
    assert manifest.locked_opened is False


def test_autotuner_selects_fastest_safe_candidate_and_blocks_regression() -> None:
    from aurora.infra.sp500_megarun.catalog_autotune import (
        TuningCandidateV1,
        select_catalog_configuration,
    )

    winner = select_catalog_configuration(
        [
            TuningCandidateV1(
                workers=60,
                processes_per_worker=1,
                block_size=256,
                wall_seconds_samples=(100.0, 101.0, 99.0),
                peak_memory_fraction=0.3,
                equivalent=True,
            ),
            TuningCandidateV1(
                workers=90,
                processes_per_worker=2,
                block_size=512,
                wall_seconds_samples=(70.0, 72.0, 71.0),
                peak_memory_fraction=0.6,
                equivalent=True,
            ),
        ],
        previous_best_median_seconds=75.0,
        max_regression_ratio=0.05,
    )
    assert winner.workers == 90
    assert winner.promoted is True

    with pytest.raises(ValueError, match="CATALOG_PERFORMANCE_REGRESSION"):
        select_catalog_configuration(
            [
                TuningCandidateV1(
                    workers=60,
                    processes_per_worker=1,
                    block_size=256,
                    wall_seconds_samples=(90.0, 91.0, 92.0),
                    peak_memory_fraction=0.3,
                    equivalent=True,
                )
            ],
            previous_best_median_seconds=75.0,
            max_regression_ratio=0.05,
        )


def test_multi_asset_panel_preserves_calendar_and_asset_isolation() -> None:
    from aurora.infra.sp500_megarun.catalog_multi_asset import build_asset_panel

    panel = build_asset_panel(
        {
            "AAA": {1: 10.0, 2: 11.0, 4: 12.0},
            "BBB": {2: 20.0, 3: 19.0, 4: 21.0},
        }
    )

    assert panel.asset_ids == ("AAA", "BBB")
    assert panel.sessions == (1, 2, 3, 4)
    np.testing.assert_array_equal(
        panel.valid_mask,
        np.array([[True, True, False, True], [False, True, True, True]]),
    )
    assert np.isnan(panel.values[0, 2])
    assert np.isnan(panel.values[1, 0])


def test_cross_sectional_engine_uses_point_in_time_membership_only() -> None:
    from aurora.infra.sp500_megarun.catalog_cross_sectional import (
        build_point_in_time_portfolio,
    )

    signals = np.array(
        [[1.0, 3.0, 2.0], [2.0, 1.0, 4.0], [3.0, 2.0, 1.0]],
    )
    membership = np.array(
        [[True, True, False], [True, False, True], [False, True, True]],
    )
    portfolio = build_point_in_time_portfolio(
        signals,
        membership,
        top_count=1,
        bottom_count=1,
    )

    np.testing.assert_array_equal(portfolio.weights[~membership], 0.0)
    np.testing.assert_allclose(portfolio.weights.sum(axis=1), 0.0)
    assert portfolio.max_active_assets == 2
    assert portfolio.validation_opened is False
    assert portfolio.locked_opened is False
