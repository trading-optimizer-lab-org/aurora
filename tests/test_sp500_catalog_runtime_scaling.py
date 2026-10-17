from __future__ import annotations

from pathlib import Path
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


def test_reducer_accepts_no_worker_receipts_only_for_fully_hot_plan() -> None:
    from scripts.reduce_sp500_optimized_catalog_run import (
        _validate_worker_runtime_contract,
    )

    _validate_worker_runtime_contract(
        (),
        expected_processes_per_worker=1,
        expected_block_size=1,
        pending_recipe_count=0,
    )

    with pytest.raises(SystemExit, match="REDUCE_WORKER_RECEIPTS_MISSING"):
        _validate_worker_runtime_contract(
            (),
            expected_processes_per_worker=1,
            expected_block_size=1,
            pending_recipe_count=1,
        )


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


def test_failed_recipe_worker_microshards_are_reusable_on_another_runner(
    tmp_path: Path,
) -> None:
    from aurora.infra.sp500_megarun.catalog_resume import load_resume_index
    from scripts.run_sp500_optimized_recipe_worker import _write_resume_microshard

    science = "a" * 64
    catalog = "b" * 64
    rows = [
        {
            "strategy_id": f"strategy-{index:03d}",
            "result_json": json.dumps(
                {"score": index},
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        for index in range(64)
    ]
    _write_resume_microshard(
        tmp_path / "failed-worker" / "recovery_microshards",
        ordinal=0,
        rows=rows,
        science_identity_sha256=science,
        catalog_manifest_sha256=catalog,
    )

    recovered = load_resume_index(
        (tmp_path / "failed-worker",),
        expected_science_identity_sha256=science,
        expected_catalog_manifest_sha256=catalog,
    )
    assert recovered.physical_result_count == 64
    assert recovered.duplicate_result_count == 0
    assert recovered.strategy_ids == tuple(row["strategy_id"] for row in rows)
    assert recovered.validation_opened is False
    assert recovered.locked_opened is False


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


def test_streaming_result_store_resumes_only_committed_ordered_rows(
    tmp_path: Path,
) -> None:
    from aurora.infra.sp500_megarun.catalog_result_store import (
        CatalogResultStore,
        CatalogStreamingResultWriter,
    )

    root = tmp_path / "stream"
    writer = CatalogStreamingResultWriter(
        root,
        contract_sha256="a" * 64,
        partition_size=2,
    )
    for index in range(3):
        writer.add(
            {
                "strategy_id": f"s{index:08d}",
                "recipe_sha256": f"{index + 1:064x}",
                "position_sha256": f"{index + 11:064x}",
                "annualized_return": index / 100,
                "weekly_positive_rate": 0.5,
            }
        )
    checkpoint = writer.checkpoint()
    assert checkpoint.row_count == 3
    assert writer.max_buffered_rows <= 2

    resumed = CatalogStreamingResultWriter(
        root,
        contract_sha256="a" * 64,
        partition_size=2,
        resume=True,
    )
    with pytest.raises(ValueError, match="RESULT_STREAM_ORDER_OR_DUPLICATE_INVALID"):
        resumed.add(
            {
                "strategy_id": "s00000002",
                "recipe_sha256": "f" * 64,
                "position_sha256": "e" * 64,
                "annualized_return": 0.0,
                "weekly_positive_rate": 0.5,
            }
        )
    for index in range(3, 7):
        resumed.add(
            {
                "strategy_id": f"s{index:08d}",
                "recipe_sha256": f"{index + 1:064x}",
                "position_sha256": f"{index + 11:064x}",
                "annualized_return": index / 100,
                "weekly_positive_rate": 0.5,
            }
        )
    manifest = resumed.commit()
    store = CatalogResultStore.open(root)
    assert manifest.row_count == 7
    assert len(list(store.iter_rows())) == 7
    assert resumed.max_buffered_rows <= 2


def test_streaming_result_store_appends_arrow_batches_without_row_buffer(
    tmp_path: Path,
) -> None:
    import pyarrow as pa

    from aurora.infra.sp500_megarun.catalog_result_store import (
        CatalogResultStore,
        CatalogStreamingResultWriter,
    )

    writer = CatalogStreamingResultWriter(
        tmp_path / "arrow-stream",
        contract_sha256="b" * 64,
        partition_size=3,
    )
    count = 8
    table = pa.table(
        {
            "strategy_id": [f"s{index:08d}" for index in range(count)],
            "recipe_sha256": [f"{index + 1:064x}" for index in range(count)],
            "position_sha256": [f"{index + 11:064x}" for index in range(count)],
            "annualized_return": [index / 100 for index in range(count)],
            "weekly_positive_rate": [0.5] * count,
        }
    )
    writer.append_table(table.slice(0, 4))
    resumed = CatalogStreamingResultWriter(
        tmp_path / "arrow-stream",
        contract_sha256="b" * 64,
        partition_size=3,
        resume=True,
    )
    resumed.append_table(table.slice(4))
    manifest = resumed.commit()
    assert manifest.row_count == count
    assert resumed.max_buffered_rows == 0
    assert len(list(CatalogResultStore.open(tmp_path / "arrow-stream").iter_rows())) == count


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
                component_workers=120,
                component_processes_per_worker=4,
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
    assert winner.component_workers == 120
    assert winner.component_processes_per_worker == 4
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
    for run_id, component_processes, processes, wall in (
        (1, 4, 1, 142.0),
        (2, 4, 1, 140.0),
        (3, 4, 1, 141.0),
        (4, 1, 2, 165.0),
        (5, 1, 2, 160.0),
        (6, 1, 2, 162.0),
    ):
        history = history.append(
            CatalogBenchmarkObservationV1(
                run_id=run_id,
                head_sha="b" * 40,
                science_identity_sha256=science,
                thermal_state="component_warm",
                workers=60,
                component_workers=60,
                component_processes_per_worker=component_processes,
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
    assert decision.component_workers == 60
    assert decision.component_processes_per_worker == 4
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


def test_autotune_records_fully_hot_zero_work_without_promoting_topology() -> None:
    from aurora.infra.sp500_megarun.catalog_autotune import (
        CatalogBenchmarkObservationV1,
        CatalogPerformanceHistoryV1,
        select_history_configuration,
    )

    observation = CatalogBenchmarkObservationV1(
        run_id=7,
        head_sha="b" * 40,
        science_identity_sha256="a" * 64,
        thermal_state="fully_hot",
        workers=0,
        component_workers=120,
        component_processes_per_worker=4,
        processes_per_worker=1,
        block_size=1,
        wall_seconds=50.0,
        peak_memory_fraction=0.0,
        equivalent=True,
    )
    history = CatalogPerformanceHistoryV1.create().append(observation)

    assert history.observations == (observation,)
    with pytest.raises(
        ValueError,
        match="CATALOG_TUNING_NO_SAFE_EQUIVALENT_CANDIDATE",
    ):
        select_history_configuration(
            history,
            science_identity_sha256="a" * 64,
            thermal_state="fully_hot",
            minimum_samples=3,
            previous_best_median_seconds=None,
            max_regression_ratio=0.05,
        )

    with pytest.raises(ValueError, match="CATALOG_AUTOTUNE_ZERO_WORK_INVALID"):
        CatalogBenchmarkObservationV1(
            **observation.model_dump(mode="python")
            | {"thermal_state": "cold"}
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
        "component_workers": 120,
        "component_processes_per_worker": 4,
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
        "scientific_wall_stage_seconds": {
            "initialization": 1.0,
            "evaluation": 16.0,
            "write": 2.0,
            "selected_verification": 1.0,
        },
        "scientific_attribution_difference_ratio": 0.0,
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
    assert report["action_stage_seconds"]["recipe_evaluation"] == 20.0
    assert report["reduction_wall_ratio"] == 0.0
    assert report["upload_seconds"] == 5.0
    assert report["strategies_per_wall_minute"] == 160.0
    assert report["artifact_bytes_uploaded"] == 1000
    assert report["result_bytes_per_recipe"] == 400.0
    assert report["scientific_stage_seconds"]["objective"] == 12.0
    assert report["scientific_wall_stage_seconds"]["evaluation"] == 16.0
    assert report["scientific_attribution_difference_ratio"] == 0.0
    assert report["accounted_runner_seconds"] == report["runner_seconds"]
    assert report["accounting_difference_ratio"] <= 0.02
    assert report["worker_cpu_seconds"] == 18.0
    assert report["worker_peak_memory_fraction"] == 0.2
    assert report["workers"] == 60
    assert report["component_workers"] == 120
    assert report["component_processes_per_worker"] == 4
    assert report["processes_per_worker"] == 2
    assert report["block_size"] == 256
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False


def test_reusable_workflow_skips_empty_matrix_groups_without_blocking_reduce() -> None:
    workflow = Path(".github/workflows/catalog-optimized-run.yml").read_text("utf-8")

    assert "outputs.recipe_matrix_b_count != '0'" in workflow
    assert "outputs.recipe_matrix_c_count != '0'" in workflow
    assert "needs.evaluate_b.result == 'skipped'" in workflow
    assert "needs.evaluate_c.result == 'skipped'" in workflow


def test_checkpoint_slots_use_the_fewest_durable_low_overhead_segments() -> None:
    from scripts.plan_sp500_optimized_catalog_run import (
        select_checkpoint_slot_count,
    )

    assert (
        select_checkpoint_slot_count(
            projected_worker_seconds_p99=840.0,
            upload_verify_seconds_p95=5.0,
        )
        == 2
    )
    assert (
        select_checkpoint_slot_count(
            projected_worker_seconds_p99=2_100.0,
            upload_verify_seconds_p95=5.0,
        )
        == 4
    )
    with pytest.raises(ValueError, match="CHECKPOINT_OVERHEAD_OR_DURABILITY_UNQUALIFIED"):
        select_checkpoint_slot_count(
            projected_worker_seconds_p99=6_000.0,
            upload_verify_seconds_p95=100.0,
        )
