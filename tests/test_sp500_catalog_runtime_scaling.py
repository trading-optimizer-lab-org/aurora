from __future__ import annotations

from pathlib import Path
import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
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


def test_resource_usage_receipt_reports_cpu_memory_and_capacity() -> None:
    from aurora.infra.sp500_megarun.catalog_resources import (
        ResourceUsageSnapshot,
        resource_usage_delta,
    )

    started = ResourceUsageSnapshot.capture()
    _ = sum(index * index for index in range(10_000))
    usage = resource_usage_delta(started, ResourceUsageSnapshot.capture())

    assert usage["cpu_seconds"] >= 0.0
    assert usage["peak_memory_bytes"] >= 1
    assert usage["available_memory_bytes"] >= usage["peak_memory_bytes"]
    assert 0.0 < usage["peak_memory_fraction"] <= 1.0


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


def _write_resume_partition(
    root: Path,
    *,
    science_identity_sha256: str,
    catalog_manifest_sha256: str,
    rows: list[dict[str, str]],
) -> None:
    from aurora.infra.github_performance.shard_planner import sha256_file

    root.mkdir(parents=True)
    path = root / "results.parquet"
    pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")
    (root / "receipt.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "science_identity_sha256": science_identity_sha256,
                "catalog_manifest_sha256": catalog_manifest_sha256,
                "result_sha256": sha256_file(path),
                "validation_opened": False,
                "locked_opened": False,
            }
        ),
        "utf-8",
    )


def test_resume_index_reuses_only_compatible_results_and_detects_conflict(
    tmp_path: Path,
) -> None:
    from aurora.infra.sp500_megarun.catalog_resume import load_resume_index

    result = {
        "fitness": 1.0,
        "cost": 27.0,
        "info": {
            "position_fingerprint": "d" * 64,
            "objective_runtime_seconds": 0.2,
            "validation_opened": False,
            "locked_opened": False,
        },
    }
    row = {"strategy_id": "s1", "result_json": json.dumps(result, sort_keys=True)}
    _write_resume_partition(
        tmp_path / "first",
        science_identity_sha256="a" * 64,
        catalog_manifest_sha256="b" * 64,
        rows=[row],
    )
    index = load_resume_index(
        [tmp_path / "first"],
        expected_science_identity_sha256="a" * 64,
        expected_catalog_manifest_sha256="b" * 64,
    )
    assert index.strategy_ids == ("s1",)
    assert index.physical_result_count == 1
    assert index.validation_opened is False
    assert index.locked_opened is False

    with pytest.raises(ValueError, match="RESUME_SOURCE_INCOMPATIBLE"):
        load_resume_index(
            [tmp_path / "first"],
            expected_science_identity_sha256="c" * 64,
            expected_catalog_manifest_sha256="b" * 64,
        )

    conflicting = {
        **result,
        "info": {**result["info"], "position_fingerprint": "e" * 64},
    }
    _write_resume_partition(
        tmp_path / "second",
        science_identity_sha256="a" * 64,
        catalog_manifest_sha256="b" * 64,
        rows=[
            {
                "strategy_id": "s1",
                "result_json": json.dumps(conflicting, sort_keys=True),
            }
        ],
    )
    with pytest.raises(ValueError, match="RESUME_RESULT_CONFLICT"):
        load_resume_index(
            [tmp_path / "first", tmp_path / "second"],
            expected_science_identity_sha256="a" * 64,
            expected_catalog_manifest_sha256="b" * 64,
        )


def test_resume_work_manifest_schedules_only_missing_recipes() -> None:
    from aurora.infra.sp500_megarun.catalog_resume import build_resume_work_manifest

    manifest = build_resume_work_manifest(
        ("s0", "s1", "s2", "s3", "s4"),
        cached_strategy_ids=("s1", "s3"),
        maximum_workers=360,
    )

    assert manifest.cached_strategy_ids == ("s1", "s3")
    assert manifest.pending_strategy_ids == ("s0", "s2", "s4")
    assert manifest.active_workers == 3
    assert manifest.assign(0) == ("s0",)
    assert manifest.assign(1) == ("s2",)
    assert manifest.assign(2) == ("s4",)
    assert manifest.validation_opened is False
    assert manifest.locked_opened is False


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


def test_autotune_history_is_hash_bound_reproducible_and_requires_three_runs(
    tmp_path: Path,
) -> None:
    from aurora.infra.sp500_megarun.catalog_autotune import (
        CatalogBenchmarkObservationV1,
        CatalogPerformanceHistoryV1,
        select_history_configuration,
    )

    science = "a" * 64
    history = CatalogPerformanceHistoryV1.create()
    for run_id, processes, wall in (
        (1, 1, 142.0),
        (2, 1, 140.0),
        (3, 1, 141.0),
        (4, 2, 165.0),
        (5, 2, 160.0),
        (6, 2, 162.0),
    ):
        history = history.append(
            CatalogBenchmarkObservationV1(
                run_id=run_id,
                head_sha="b" * 40,
                science_identity_sha256=science,
                thermal_state="component_warm",
                workers=60,
                processes_per_worker=processes,
                block_size=256,
                wall_seconds=wall,
                peak_memory_fraction=0.05,
                equivalent=True,
            )
        )

    path = tmp_path / "history.json"
    history.write(path)
    restored = CatalogPerformanceHistoryV1.load(path)
    decision = select_history_configuration(
        restored,
        science_identity_sha256=science,
        thermal_state="component_warm",
        minimum_samples=3,
        previous_best_median_seconds=145.0,
        max_regression_ratio=0.05,
    )

    assert decision.workers == 60
    assert decision.processes_per_worker == 1
    assert decision.median_wall_seconds == 141.0
    assert decision.sample_count == 3
    assert decision.promoted is True

    with pytest.raises(ValueError, match="CATALOG_AUTOTUNE_RUN_CONFLICT"):
        restored.append(
            CatalogBenchmarkObservationV1(
                run_id=1,
                head_sha="c" * 40,
                science_identity_sha256=science,
                thermal_state="component_warm",
                workers=60,
                processes_per_worker=4,
                block_size=256,
                wall_seconds=1.0,
                peak_memory_fraction=0.05,
                equivalent=True,
            )
        )


def test_autotune_ingest_rejects_non_equivalent_or_open_boundaries(tmp_path: Path) -> None:
    from scripts.update_sp500_catalog_autotune import update_autotune_history

    audits: list[Path] = []
    equivalences: list[Path] = []
    for run_id, wall in ((11, 140.0), (12, 142.0), (13, 141.0)):
        audit = tmp_path / f"audit-{run_id}.json"
        audit.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "head_sha": "d" * 40,
                    "thermal_state": "component_warm",
                    "workers": 60,
                    "processes_per_worker": 1,
                    "block_size": 256,
                    "wall_seconds": wall,
                    "worker_peak_memory_fraction": 0.04,
                    "validation_opened": False,
                    "locked_opened": False,
                }
            ),
            "utf-8",
        )
        equivalence = tmp_path / f"equivalence-{run_id}.json"
        equivalence.write_text(
            json.dumps(
                {
                    "equivalent": True,
                    "difference_count": 0,
                    "validation_opened": False,
                    "locked_opened": False,
                }
            ),
            "utf-8",
        )
        audits.append(audit)
        equivalences.append(equivalence)

    history, decision = update_autotune_history(
        history_path=None,
        runtime_audit_paths=tuple(audits),
        equivalence_paths=tuple(equivalences),
        science_identity_sha256="e" * 64,
        thermal_state="component_warm",
        minimum_samples=3,
        previous_best_median_seconds=145.0,
        max_regression_ratio=0.05,
    )
    assert len(history.observations) == 3
    assert decision.median_wall_seconds == 141.0

    payload = json.loads(equivalences[0].read_text("utf-8"))
    payload["locked_opened"] = True
    equivalences[0].write_text(json.dumps(payload), "utf-8")
    with pytest.raises(ValueError, match="CATALOG_AUTOTUNE_EQUIVALENCE_INVALID"):
        update_autotune_history(
            history_path=None,
            runtime_audit_paths=tuple(audits),
            equivalence_paths=tuple(equivalences),
            science_identity_sha256="e" * 64,
            thermal_state="component_warm",
            minimum_samples=3,
            previous_best_median_seconds=145.0,
            max_regression_ratio=0.05,
        )

def test_actions_runtime_audit_reports_wall_runner_setup_compute_and_bytes() -> None:
    from aurora.infra.sp500_megarun.catalog_actions_audit import (
        build_actions_runtime_audit,
    )

    jobs = [
        {
            "name": "optimized / plan",
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-01-01T00:00:00Z",
            "started_at": "2026-01-01T00:00:02Z",
            "completed_at": "2026-01-01T00:00:12Z",
            "steps": [],
        },
        {
            "name": "optimized / evaluate_a (0) / evaluate",
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-01-01T00:00:12Z",
            "started_at": "2026-01-01T00:00:15Z",
            "completed_at": "2026-01-01T00:00:45Z",
            "steps": [
                {
                    "name": "Run setup",
                    "started_at": "2026-01-01T00:00:15Z",
                    "completed_at": "2026-01-01T00:00:20Z",
                },
                {
                    "name": "Run python -m scripts.run_sp500_optimized_recipe_worker",
                    "started_at": "2026-01-01T00:00:20Z",
                    "completed_at": "2026-01-01T00:00:40Z",
                },
                {
                    "name": "Run actions/upload-artifact",
                    "started_at": "2026-01-01T00:00:40Z",
                    "completed_at": "2026-01-01T00:00:45Z",
                },
            ],
        },
    ]
    receipt = {
        "strategy_count": 120,
        "physical_recipe_evaluations": 100,
        "prior_result_cache_hits": 20,
        "worker_receipt_count": 1,
        "workers": 60,
        "processes_per_worker": 2,
        "block_size": 256,
        "result_bytes": 48000,
        "scientific_stage_seconds": {
            "component_load": 2.0,
            "composition": 3.0,
            "objective": 12.0,
            "serialization": 1.0,
            "write": 2.0,
        },
        "worker_cpu_seconds": 18.0,
        "worker_peak_memory_bytes": 2_000,
        "worker_available_memory_bytes": 10_000,
        "worker_peak_memory_fraction": 0.2,
        "validation_opened": False,
        "locked_opened": False,
    }
    report = build_actions_runtime_audit(
        run={
            "id": 7,
            "head_sha": "a" * 40,
            "run_started_at": "2026-01-01T00:00:00Z",
        },
        jobs=jobs,
        artifacts=[{"name": "first", "size_in_bytes": 1000}],
        receipt=receipt,
        thermal_state="component_warm",
    )

    assert report["wall_seconds"] == 45.0
    assert report["runner_seconds"] == 40.0
    assert report["queue_seconds"] == 5.0
    assert report["setup_seconds_p50"] == 5.0
    assert report["compute_seconds"] == 20.0
    assert report["upload_seconds"] == 5.0
    assert report["strategies_per_wall_minute"] == 160.0
    assert report["artifact_bytes_uploaded"] == 1000
    assert report["result_bytes_per_recipe"] == 400.0
    assert report["scientific_stage_seconds"]["objective"] == 12.0
    assert report["accounted_runner_seconds"] == report["runner_seconds"]
    assert report["accounting_difference_ratio"] <= 0.02
    assert report["worker_cpu_seconds"] == 18.0
    assert report["worker_peak_memory_fraction"] == 0.2
    assert report["workers"] == 60
    assert report["processes_per_worker"] == 2
    assert report["block_size"] == 256
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False


def test_reusable_workflow_skips_empty_matrix_groups_without_blocking_reduce() -> None:
    workflow = Path(".github/workflows/catalog-optimized-run.yml").read_text("utf-8")

    assert "fromJSON(needs.plan.outputs.active_workers) > 120" in workflow
    assert "fromJSON(needs.plan.outputs.active_workers) > 240" in workflow
    assert "needs.evaluate_b.result == 'skipped'" in workflow
    assert "needs.evaluate_c.result == 'skipped'" in workflow


def test_multi_asset_panel_preserves_calendar_and_asset_isolation() -> None:
    from aurora.infra.sp500_megarun.catalog_multi_asset import (
        build_asset_panel,
        evaluate_multi_asset_panel,
    )

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

    evaluated = evaluate_multi_asset_panel(panel, lookback=1)
    assert evaluated.asset_count == 2
    assert evaluated.shared_calendar_builds == 1
    assert evaluated.asset_specific_work_units == 2
    assert evaluated.validation_opened is False
    assert evaluated.locked_opened is False

    changed = panel.values.copy()
    changed[:, -1] = np.array([9999.0, -9999.0])
    changed_panel = type(panel)(
        asset_ids=panel.asset_ids,
        sessions=panel.sessions,
        values=changed,
        valid_mask=panel.valid_mask,
    )
    changed_evaluation = evaluate_multi_asset_panel(changed_panel, lookback=1)
    np.testing.assert_array_equal(
        evaluated.independent_signals[:, :-1],
        changed_evaluation.independent_signals[:, :-1],
    )
    np.testing.assert_array_equal(
        evaluated.cross_asset_signals[:, :-1],
        changed_evaluation.cross_asset_signals[:, :-1],
    )


def test_cross_sectional_engine_uses_point_in_time_membership_only() -> None:
    from aurora.infra.sp500_megarun.catalog_cross_sectional import (
        build_point_in_time_portfolio,
        build_sparse_point_in_time_portfolio,
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

    sparse = build_sparse_point_in_time_portfolio(
        np.where(membership, signals, np.nan),
        membership,
        top_count=1,
        bottom_count=1,
    )
    np.testing.assert_array_equal(sparse.to_dense(), portfolio.weights)
    assert sparse.nonzero_weight_count == 6


def test_cross_sectional_sparse_engine_scales_to_one_thousand_assets() -> None:
    from aurora.infra.sp500_megarun.catalog_cross_sectional import (
        build_sparse_point_in_time_portfolio,
    )

    dates = 64
    assets = 1000
    signals = np.arange(dates * assets, dtype=np.float64).reshape(dates, assets)
    membership = np.ones((dates, assets), dtype=bool)
    membership[:, ::17] = False
    signals[~membership] = np.nan

    portfolio = build_sparse_point_in_time_portfolio(
        signals,
        membership,
        top_count=10,
        bottom_count=10,
    )

    assert portfolio.asset_count == assets
    assert portfolio.nonzero_weight_count == dates * 20
    assert portfolio.storage_bytes < signals.nbytes / 10
    np.testing.assert_allclose(portfolio.to_dense().sum(axis=1), 0.0)
    assert portfolio.validation_opened is False
    assert portfolio.locked_opened is False


def test_future_architecture_qualification_is_github_only_and_bounded() -> None:
    workflow = Path(".github/workflows/catalog-future-architecture.yml").read_text(
        "utf-8"
    )
    script = Path("scripts/benchmark_catalog_future_architecture.py").read_text(
        "utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "workflow_call:" in workflow
    assert "requirements/catalog-architecture.lock" in workflow
    entrypoint = Path(
        ".github/workflows/sp500-search-method-benchmark-short.yml"
    ).read_text("utf-8")
    assert "optimized_catalog_future_architecture" in entrypoint
    assert "uses: ./.github/workflows/catalog-future-architecture.yml" in entrypoint
    assert "100, 256" in script
    assert "128, 1000" in script
    assert "512, 4096" in script
    assert '"validation_opened": False' in script
    assert '"locked_opened": False' in script
