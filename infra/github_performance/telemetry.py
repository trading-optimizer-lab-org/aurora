"""Operational telemetry for GitHub-only Aurora workloads."""

from __future__ import annotations

import os
import shutil
import time
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import Field

from aurora.infra.github_performance.contracts import FrozenModel, ResourceSample
from aurora.monitoring.telemetry import TelemetrySink, emit_metric


SCHEMA_VERSION = "1"


class PerformanceRow(FrozenModel):
    run_id: str
    job_id: str
    shard_id: str
    attempt_id: str
    phase: str
    started_at: datetime
    completed_at: datetime
    duration_seconds: float = Field(ge=0)
    units_processed: int = Field(ge=0)
    bytes_read: int = Field(ge=0)
    bytes_written: int = Field(ge=0)
    peak_memory_mb: float = Field(ge=0)
    peak_disk_mb: float = Field(ge=0)
    cpu_seconds: float = Field(ge=0)
    io_wait_seconds: float = Field(ge=0)


def _read_io_wait_seconds() -> float:
    stat_path = Path("/proc/self/stat")
    if not stat_path.is_file():
        return 0.0
    try:
        tail = stat_path.read_text(encoding="ascii").rsplit(")", maxsplit=1)[1]
        fields_from_state = tail.strip().split()
        block_io_ticks = float(fields_from_state[39])
        return block_io_ticks / float(os.sysconf("SC_CLK_TCK"))
    except (IndexError, OSError, ValueError):
        return 0.0


def sample_process_resources(workspace: Path) -> ResourceSample:
    """Collect bounded process and disk observations without optional SDKs."""

    peak_memory_mb = 0.0
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        scale = 1024.0 if os.name != "darwin" else 1024.0 * 1024.0
        peak_memory_mb = float(usage.ru_maxrss) / scale
    except ImportError:
        peak_memory_mb = 0.0
    free_disk_mb = shutil.disk_usage(workspace).free / (1024.0 * 1024.0)
    return ResourceSample(
        rss_mb=peak_memory_mb,
        peak_memory_mb=peak_memory_mb,
        free_disk_mb=free_disk_mb,
        cpu_seconds=time.process_time(),
        io_wait_seconds=_read_io_wait_seconds(),
    )


class PerformanceSpan(AbstractContextManager["PerformanceSpan"]):
    """One bounded operational phase."""

    def __init__(self, recorder: PerformanceRecorder, phase: str) -> None:
        self._recorder = recorder
        self._phase = phase
        self._started_perf = 0.0
        self._started_at = datetime.now(timezone.utc)
        self._started_resources: ResourceSample | None = None
        self._units_processed = 0
        self._bytes_read = 0
        self._bytes_written = 0

    def add_units(self, value: int) -> None:
        if value < 0:
            raise ValueError("units must be non-negative")
        self._units_processed += value

    def add_bytes_read(self, value: int) -> None:
        if value < 0:
            raise ValueError("bytes_read must be non-negative")
        self._bytes_read += value

    def add_bytes_written(self, value: int) -> None:
        if value < 0:
            raise ValueError("bytes_written must be non-negative")
        self._bytes_written += value

    def __enter__(self) -> PerformanceSpan:
        self._started_at = datetime.now(timezone.utc)
        self._started_resources = self._recorder.sample_resources()
        self._started_perf = self._recorder.clock()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        completed_perf = self._recorder.clock()
        completed_at = datetime.now(timezone.utc)
        completed_resources = self._recorder.sample_resources()
        started_resources = self._started_resources or completed_resources
        row = PerformanceRow(
            run_id=self._recorder.run_id,
            job_id=self._recorder.job_id,
            shard_id=self._recorder.shard_id,
            attempt_id=self._recorder.attempt_id,
            phase=self._phase,
            started_at=self._started_at,
            completed_at=completed_at,
            duration_seconds=max(0.0, completed_perf - self._started_perf),
            units_processed=self._units_processed,
            bytes_read=self._bytes_read,
            bytes_written=self._bytes_written,
            peak_memory_mb=max(
                started_resources.peak_memory_mb,
                completed_resources.peak_memory_mb,
            ),
            peak_disk_mb=max(
                0.0,
                started_resources.free_disk_mb - completed_resources.free_disk_mb,
            ),
            cpu_seconds=max(
                0.0,
                completed_resources.cpu_seconds - started_resources.cpu_seconds,
            ),
            io_wait_seconds=max(
                0.0,
                completed_resources.io_wait_seconds - started_resources.io_wait_seconds,
            ),
        )
        self._recorder.append(row)


class PerformanceRecorder:
    """Collect and export phase-level operational telemetry."""

    COLUMN_NAMES = (
        "run_id",
        "job_id",
        "shard_id",
        "attempt_id",
        "phase",
        "started_at",
        "completed_at",
        "duration_seconds",
        "units_processed",
        "bytes_read",
        "bytes_written",
        "peak_memory_mb",
        "peak_disk_mb",
        "cpu_seconds",
        "io_wait_seconds",
    )

    ARROW_SCHEMA = pa.schema(
        [
            pa.field("run_id", pa.string(), nullable=False),
            pa.field("job_id", pa.string(), nullable=False),
            pa.field("shard_id", pa.string(), nullable=False),
            pa.field("attempt_id", pa.string(), nullable=False),
            pa.field("phase", pa.string(), nullable=False),
            pa.field("started_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("completed_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("duration_seconds", pa.float64(), nullable=False),
            pa.field("units_processed", pa.int64(), nullable=False),
            pa.field("bytes_read", pa.int64(), nullable=False),
            pa.field("bytes_written", pa.int64(), nullable=False),
            pa.field("peak_memory_mb", pa.float64(), nullable=False),
            pa.field("peak_disk_mb", pa.float64(), nullable=False),
            pa.field("cpu_seconds", pa.float64(), nullable=False),
            pa.field("io_wait_seconds", pa.float64(), nullable=False),
        ]
    )

    def __init__(
        self,
        run_id: str,
        *,
        job_id: str = "",
        shard_id: str = "",
        attempt_id: str = "",
        code_sha: str = "",
        policy_hash: str = "",
        clock: Callable[[], float] = time.perf_counter,
        sample_resources: Callable[[], ResourceSample] | None = None,
        workspace: Path | None = None,
        sink: TelemetrySink | None = None,
    ) -> None:
        self.run_id = run_id
        self.job_id = job_id
        self.shard_id = shard_id
        self.attempt_id = attempt_id
        self.code_sha = code_sha
        self.policy_hash = policy_hash
        self.clock = clock
        self.workspace = Path.cwd() if workspace is None else Path(workspace)
        self.sample_resources = sample_resources or (
            lambda: sample_process_resources(self.workspace)
        )
        self.sink = sink
        self._rows: list[PerformanceRow] = []

    def start_phase(self, name: str) -> PerformanceSpan:
        if not name or any(character.isspace() for character in name):
            raise ValueError("phase name must be a non-empty machine identifier")
        return PerformanceSpan(self, name)

    def append(self, row: PerformanceRow) -> None:
        self._rows.append(row)
        emit_metric(
            "aurora_github_phase_seconds",
            row.duration_seconds,
            sink=self.sink,
            labels={
                "phase": row.phase,
                "job_id": row.job_id,
                "shard_id": row.shard_id,
                "attempt_id": row.attempt_id,
            },
            run_id=row.run_id,
        )

    def rows(self) -> tuple[PerformanceRow, ...]:
        return tuple(self._rows)

    def write_parquet(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [row.model_dump(mode="python") for row in self._rows]
        metadata = {
            b"schema_version": SCHEMA_VERSION.encode("ascii"),
            b"code_sha": self.code_sha.encode("ascii"),
            b"run_id": self.run_id.encode("utf-8"),
            b"policy_hash": self.policy_hash.encode("ascii"),
        }
        schema = self.ARROW_SCHEMA.with_metadata(metadata)
        table = pa.Table.from_pylist(records, schema=schema)
        pq.write_table(table, path, compression="zstd")
