from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from aurora.infra.github_performance.contracts import ResourceSample
from aurora.infra.github_performance.telemetry import PerformanceRecorder
from aurora.monitoring.telemetry import InMemorySink


def samples() -> ResourceSample:
    return ResourceSample(
        rss_mb=100.0,
        peak_memory_mb=200.0,
        free_disk_mb=300.0,
        cpu_seconds=0.4,
        io_wait_seconds=0.1,
    )


def test_span_records_phase_without_scientific_values(tmp_path: Path) -> None:
    recorder = PerformanceRecorder(
        run_id="r1",
        shard_id="s1",
        clock=iter([10.0, 13.5]).__next__,
        sample_resources=samples,
        workspace=tmp_path,
    )
    with recorder.start_phase("compute"):
        pass
    row = recorder.rows()[0]
    assert row.phase == "compute"
    assert row.duration_seconds == 3.5
    assert "score" not in row.model_dump()


def test_span_records_only_explicit_operational_counters(tmp_path: Path) -> None:
    recorder = PerformanceRecorder(
        run_id="r1",
        job_id="j1",
        shard_id="s1",
        attempt_id="a1",
        clock=iter([1.0, 2.0]).__next__,
        sample_resources=samples,
        workspace=tmp_path,
    )
    with recorder.start_phase("serialization") as span:
        span.add_units(7)
        span.add_bytes_read(128)
        span.add_bytes_written(64)
    row = recorder.rows()[0]
    assert (row.units_processed, row.bytes_read, row.bytes_written) == (7, 128, 64)


def test_recorder_emits_generic_aurora_telemetry(tmp_path: Path) -> None:
    sink = InMemorySink()
    recorder = PerformanceRecorder(
        run_id="r1",
        clock=iter([1.0, 2.0]).__next__,
        sample_resources=samples,
        workspace=tmp_path,
        sink=sink,
    )
    with recorder.start_phase("verify"):
        pass
    records = sink.by_name("aurora_github_phase_seconds")
    assert len(records) == 1
    assert records[0].correlation["run_id"] == "r1"
    assert records[0].labels["phase"] == "verify"


def test_parquet_export_has_fixed_schema_and_provenance(tmp_path: Path) -> None:
    recorder = PerformanceRecorder(
        run_id="r1",
        job_id="j1",
        code_sha="a" * 40,
        policy_hash="b" * 64,
        clock=iter([1.0, 2.0]).__next__,
        sample_resources=samples,
        workspace=tmp_path,
    )
    with recorder.start_phase("compute"):
        pass
    output = tmp_path / "runtime_breakdown.parquet"
    recorder.write_parquet(output)
    table = pq.read_table(output)
    assert table.schema.names == list(PerformanceRecorder.COLUMN_NAMES)
    assert table.schema.metadata[b"schema_version"] == b"1"
    assert table.schema.metadata[b"code_sha"] == b"a" * 40
    assert table.schema.metadata[b"policy_hash"] == b"b" * 64
