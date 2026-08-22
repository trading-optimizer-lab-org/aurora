from __future__ import annotations

import json
from pathlib import Path

import pytest


class _Clock:
    def __init__(self, *values: float) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


def test_catalog_profiler_separates_physical_components_from_cache_hits(
    tmp_path: Path,
) -> None:
    """A cache hit must never be reported as a physical component build."""

    from aurora.infra.sp500_megarun.catalog_performance import (
        CatalogPerformanceRecorder,
    )

    recorder = CatalogPerformanceRecorder(
        shard_index=7,
        total_shards=360,
        thermal_state="cold",
        clock=_Clock(10.0, 12.5),
        cpu_clock=_Clock(3.0, 4.5),
        memory_mb=lambda: 128.0,
    )

    with recorder.component_build("F069", "a" * 64):
        pass
    recorder.component_cache_hit("F069", "a" * 64)

    summary = recorder.summary()
    assert summary["physical_component_builds"] == 1
    assert summary["component_cache_hits"] == 1
    assert summary["component_requests"] == 2
    assert summary["physical_component_seconds"] == 2.5
    assert summary["physical_component_cpu_seconds"] == 1.5
    assert summary["peak_memory_mb"] == 128.0
    assert summary["validation_opened"] is False
    assert summary["locked_opened"] is False
    assert summary["component_profiles"] == {
        "F069:" + "a" * 64: {
            "lane_id": "F069",
            "configuration_sha256": "a" * 64,
            "requests": 2,
            "physical_builds": 1,
            "cache_hits": 1,
            "physical_seconds": 2.5,
            "physical_cpu_seconds": 1.5,
            "p50_seconds": 2.5,
            "p90_seconds": 2.5,
            "p95_seconds": 2.5,
            "p99_seconds": 2.5,
        }
    }

    outputs = recorder.write(tmp_path)
    written_summary = json.loads(outputs.summary_path.read_text("utf-8"))
    assert written_summary == summary
    assert outputs.event_count == 2
    assert outputs.summary_sha256 == outputs.summary_path_sha256


def test_catalog_profiler_aggregates_operational_phases() -> None:
    """A missing or misnamed phase must be visible in the final receipt."""

    from aurora.infra.sp500_megarun.catalog_performance import (
        CatalogPerformanceRecorder,
    )

    recorder = CatalogPerformanceRecorder(
        shard_index=0,
        total_shards=1,
        thermal_state="runtime_warm",
        clock=_Clock(0.0, 2.0, 2.0, 5.0),
        cpu_clock=_Clock(0.0, 1.0, 1.0, 2.25),
        memory_mb=lambda: 64.0,
    )
    with recorder.phase("data_load") as span:
        span.add_units(1)
        span.add_bytes_read(4_096)
    with recorder.phase("recipe_scoring") as span:
        span.add_units(8)
        span.add_bytes_written(512)

    summary = recorder.summary()
    assert summary["phase_totals"] == {
        "data_load": {
            "count": 1,
            "duration_seconds": 2.0,
            "cpu_seconds": 1.0,
            "units_processed": 1,
            "bytes_read": 4_096,
            "bytes_written": 0,
            "p50_seconds": 2.0,
            "p90_seconds": 2.0,
            "p95_seconds": 2.0,
            "p99_seconds": 2.0,
        },
        "recipe_scoring": {
            "count": 1,
            "duration_seconds": 3.0,
            "cpu_seconds": 1.25,
            "units_processed": 8,
            "bytes_read": 0,
            "bytes_written": 512,
            "p50_seconds": 3.0,
            "p90_seconds": 3.0,
            "p95_seconds": 3.0,
            "p99_seconds": 3.0,
        },
    }
    assert summary["operational_phase_seconds"] == 5.0
    assert summary["operational_phase_cpu_seconds"] == 2.25


def test_lightweight_phase_does_not_sample_memory() -> None:
    """Per-recipe timings must not add an expensive RSS lookup per span."""

    from aurora.infra.sp500_megarun.catalog_performance import (
        CatalogPerformanceRecorder,
    )

    recorder = CatalogPerformanceRecorder(
        shard_index=0,
        total_shards=1,
        thermal_state="fully_hot",
        clock=_Clock(1.0, 1.1),
        cpu_clock=_Clock(2.0, 2.05),
        memory_mb=lambda: (_ for _ in ()).throw(
            AssertionError("memory sampler called")
        ),
    )
    with recorder.phase("signal_composition", sample_memory=False) as span:
        span.add_units(1)

    summary = recorder.summary()
    assert summary["peak_memory_mb"] == 0.0
    assert summary["phase_totals"]["signal_composition"][
        "duration_seconds"
    ] == pytest.approx(0.1)


def test_measure_returns_operation_value_and_records_one_unit() -> None:
    """Scientific calls wrapped for timing must return their result unchanged."""

    from aurora.infra.sp500_megarun.catalog_performance import (
        CatalogPerformanceRecorder,
    )

    recorder = CatalogPerformanceRecorder(
        shard_index=0,
        total_shards=1,
        thermal_state="cold",
        clock=_Clock(4.0, 4.5),
        cpu_clock=_Clock(1.0, 1.2),
        memory_mb=lambda: 0.0,
    )

    result = recorder.measure("strategy_scoring", lambda: {"score": 7})

    assert result == {"score": 7}
    assert recorder.summary()["phase_totals"]["strategy_scoring"] == {
        "count": 1,
        "duration_seconds": 0.5,
        "cpu_seconds": pytest.approx(0.2),
        "units_processed": 1,
        "bytes_read": 0,
        "bytes_written": 0,
        "p50_seconds": 0.5,
        "p90_seconds": 0.5,
        "p95_seconds": 0.5,
        "p99_seconds": 0.5,
    }


def test_global_profile_detects_repeated_component_builds_between_shards(
    tmp_path: Path,
) -> None:
    """The run-level report must expose physical duplication across shards."""

    from aurora.infra.sp500_megarun.catalog_performance import (
        CatalogPerformanceRecorder,
        aggregate_catalog_performance,
    )

    roots = []
    for shard_index in (0, 1):
        recorder = CatalogPerformanceRecorder(
            shard_index=shard_index,
            total_shards=2,
            thermal_state="cold",
            clock=_Clock(0.0, 1.0 + shard_index),
            cpu_clock=_Clock(0.0, 0.5 + shard_index),
            memory_mb=lambda: 100.0,
        )
        with recorder.component_build("F069", "b" * 64):
            pass
        root = tmp_path / f"shard-{shard_index}"
        recorder.write(root)
        roots.append(root)

    report = aggregate_catalog_performance(roots)
    assert report["completed_shards"] == 2
    assert report["component_requests"] == 2
    assert report["physical_component_builds"] == 2
    assert report["unique_physical_components"] == 1
    assert report["redundant_component_builds"] == 1
    assert report["redundant_component_build_ratio"] == 0.5
    assert report["physical_component_seconds"] == 3.0
    profile = report["component_profiles"][f"F069:{'b' * 64}"]
    assert profile["sample_count"] == 2
    assert profile["duration_samples"] == [1.0, 2.0]
    assert profile["p50_seconds"] == 1.0
    assert profile["p95_seconds"] == 2.0
    assert report["peak_memory_mb"] == 100.0
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False


def test_reducer_writes_global_performance_report(tmp_path: Path) -> None:
    """A complete shard set must produce one run-level performance artifact."""

    from aurora.infra.sp500_megarun.catalog_performance import (
        CatalogPerformanceRecorder,
    )
    from scripts.reduce_sp500_strategy_catalog_run import (
        reduce_performance_evidence,
    )

    input_root = tmp_path / "inputs"
    for shard_index in (0, 1):
        recorder = CatalogPerformanceRecorder(
            shard_index=shard_index,
            total_shards=2,
            thermal_state="cold",
            clock=_Clock(0.0, 1.0),
            cpu_clock=_Clock(0.0, 0.5),
            memory_mb=lambda: 20.0,
        )
        with recorder.component_build(f"F00{shard_index + 1}", str(shard_index) * 64):
            pass
        recorder.write(input_root / f"shard-{shard_index}")

    output_dir = tmp_path / "final"
    report = reduce_performance_evidence(input_root, output_dir)

    assert report["completed_shards"] == 2
    assert report["unique_physical_components"] == 2
    assert json.loads((output_dir / "performance.json").read_text("utf-8")) == report


def test_bundle_layout_selects_fastest_qualified_end_to_end_candidate() -> None:
    from scripts.plan_sp500_optimized_catalog_run import (
        BundleLayoutQualificationV1,
        select_qualified_bundle_layout,
    )

    candidates = tuple(
        BundleLayoutQualificationV1(
            bundle_count=count,
            equivalent=True,
            sample_count=3,
            memory_safe=True,
            disk_safe=True,
            runner_timeout_safe=True,
            projected_end_to_end_p50_seconds=p50,
            projected_end_to_end_p95_seconds=p50 * 1.1,
            projected_component_download_bytes=bytes_,
            projected_cache_uploads_per_minute=20,
            projected_cache_downloads_per_minute=200,
            checkpoint_upload_seconds_p95=2.0,
        )
        for count, p50, bytes_ in (
            (8, 120.0, 10_000),
            (16, 90.0, 15_000),
            (32, 92.0, 8_000),
            (64, 140.0, 7_000),
            (96, 150.0, 6_000),
            (128, 160.0, 5_000),
        )
    )
    selected = select_qualified_bundle_layout(candidates)
    assert selected.bundle_count == 16

    unsafe_fast = candidates[0].model_copy(
        update={
            "projected_end_to_end_p50_seconds": 1.0,
            "memory_safe": False,
        }
    )
    selected = select_qualified_bundle_layout((unsafe_fast, *candidates[1:]))
    assert selected.memory_safe is True
