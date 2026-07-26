"""Operational telemetry for GitHub-only Aurora workloads."""

from __future__ import annotations

import os
import shutil
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import Field, field_validator

from aurora.infra.github_performance.contracts import FrozenModel, ResourceSample
from aurora.monitoring.telemetry import TelemetrySink, emit_metric


SCHEMA_VERSION = "1"


class ProcessRecord(FrozenModel):
    """One process record used to aggregate a complete descendant tree."""

    pid: int = Field(ge=1)
    parent_pid: int = Field(ge=0)
    rss_mb: float = Field(ge=0)
    peak_memory_mb: float = Field(ge=0)
    cpu_seconds: float = Field(ge=0)
    io_read_bytes: int = Field(ge=0)
    io_write_bytes: int = Field(ge=0)
    io_wait_seconds: float = Field(ge=0)


class ProcessTreeAggregate(FrozenModel):
    """Summed operational counters for root and all descendants."""

    process_count: int = Field(ge=1)
    rss_mb: float = Field(ge=0)
    peak_memory_mb: float = Field(ge=0)
    cpu_seconds: float = Field(ge=0)
    io_read_bytes: int = Field(ge=0)
    io_write_bytes: int = Field(ge=0)
    io_wait_seconds: float = Field(ge=0)


class ResourceObservation(FrozenModel):
    """One child-aware, point-in-time resource observation."""

    observed_at: datetime
    root_pid: int = Field(ge=1)
    process_count: int = Field(ge=1)
    child_aware: bool
    rss_mb: float = Field(ge=0)
    peak_memory_mb: float = Field(ge=0)
    total_memory_mb: float = Field(gt=0)
    free_disk_mb: float = Field(ge=0)
    cpu_seconds: float = Field(ge=0)
    io_read_bytes: int = Field(ge=0)
    io_write_bytes: int = Field(ge=0)
    io_wait_seconds: float = Field(ge=0)
    load_1m: float = Field(ge=0)

    @field_validator("observed_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return value


class ResourceSummary(FrozenModel):
    """Tail-aware resource summary used by final performance evidence."""

    sample_count: int = Field(ge=0)
    sampling_error_count: int = Field(ge=0)
    evidence_complete: bool
    child_aware: bool
    max_rss_mb: float = Field(ge=0)
    p95_rss_mb: float = Field(ge=0)
    max_peak_memory_mb: float = Field(ge=0)
    minimum_free_disk_mb: float = Field(ge=0)
    maximum_process_count: int = Field(ge=0)
    final_cpu_seconds: float = Field(ge=0)
    final_io_read_bytes: int = Field(ge=0)
    final_io_write_bytes: int = Field(ge=0)
    final_io_wait_seconds: float = Field(ge=0)


def aggregate_process_tree(
    records: Sequence[ProcessRecord],
    *,
    root_pid: int,
) -> ProcessTreeAggregate:
    """Aggregate the root process and recursively discovered descendants."""

    by_pid = {record.pid: record for record in records}
    if root_pid not in by_pid:
        raise ValueError(f"root process is missing: {root_pid}")
    children: dict[int, list[int]] = {}
    for record in records:
        children.setdefault(record.parent_pid, []).append(record.pid)
    selected: list[ProcessRecord] = []
    pending = [root_pid]
    seen: set[int] = set()
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        current_record = by_pid.get(pid)
        if current_record is None:
            continue
        selected.append(current_record)
        pending.extend(children.get(pid, ()))
    return ProcessTreeAggregate(
        process_count=len(selected),
        rss_mb=sum(record.rss_mb for record in selected),
        peak_memory_mb=sum(
            record.peak_memory_mb for record in selected
        ),
        cpu_seconds=sum(record.cpu_seconds for record in selected),
        io_read_bytes=sum(record.io_read_bytes for record in selected),
        io_write_bytes=sum(record.io_write_bytes for record in selected),
        io_wait_seconds=sum(
            record.io_wait_seconds for record in selected
        ),
    )


def _proc_status_peak_mb(pid: int, fallback_mb: float) -> float:
    try:
        lines = Path(f"/proc/{pid}/status").read_text(
            encoding="ascii"
        ).splitlines()
    except OSError:
        return fallback_mb
    for line in lines:
        if line.startswith("VmHWM:"):
            try:
                return float(line.split()[1]) / 1024.0
            except (IndexError, ValueError):
                return fallback_mb
    return fallback_mb


def _proc_io(pid: int) -> tuple[int, int]:
    try:
        lines = Path(f"/proc/{pid}/io").read_text(
            encoding="ascii"
        ).splitlines()
    except OSError:
        return 0, 0
    values: dict[str, int] = {}
    for line in lines:
        name, separator, raw = line.partition(":")
        if separator:
            try:
                values[name] = int(raw.strip())
            except ValueError:
                continue
    return values.get("read_bytes", 0), values.get("write_bytes", 0)


def _linux_process_records() -> tuple[ProcessRecord, ...]:
    clock_ticks = float(os.sysconf("SC_CLK_TCK"))
    page_mb = float(os.sysconf("SC_PAGE_SIZE")) / (1024.0 * 1024.0)
    records: list[ProcessRecord] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        try:
            text = (entry / "stat").read_text(encoding="ascii")
            fields = text.rsplit(")", maxsplit=1)[1].strip().split()
            parent_pid = int(fields[1])
            cpu_seconds = (
                float(fields[11]) + float(fields[12])
            ) / clock_ticks
            rss_mb = float(fields[21]) * page_mb
            io_wait_seconds = float(fields[39]) / clock_ticks
        except (IndexError, OSError, ValueError):
            continue
        read_bytes, write_bytes = _proc_io(pid)
        records.append(
            ProcessRecord(
                pid=pid,
                parent_pid=parent_pid,
                rss_mb=max(0.0, rss_mb),
                peak_memory_mb=max(
                    0.0,
                    _proc_status_peak_mb(pid, rss_mb),
                ),
                cpu_seconds=max(0.0, cpu_seconds),
                io_read_bytes=max(0, read_bytes),
                io_write_bytes=max(0, write_bytes),
                io_wait_seconds=max(0.0, io_wait_seconds),
            )
        )
    return tuple(records)


def _total_memory_mb() -> float:
    try:
        lines = Path("/proc/meminfo").read_text(
            encoding="ascii"
        ).splitlines()
    except OSError:
        return 1.0
    for line in lines:
        if line.startswith("MemTotal:"):
            try:
                return max(1.0, float(line.split()[1]) / 1024.0)
            except (IndexError, ValueError):
                break
    return 1.0


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


def sample_process_tree_resources(
    workspace: Path,
    *,
    root_pid: int | None = None,
) -> ResourceObservation:
    """Sample the current process and every live descendant on Linux."""

    root = os.getpid() if root_pid is None else root_pid
    free_disk_mb = shutil.disk_usage(workspace).free / (1024.0 * 1024.0)
    if Path("/proc").is_dir():
        aggregate = aggregate_process_tree(
            _linux_process_records(),
            root_pid=root,
        )
        try:
            load_1m = max(0.0, float(os.getloadavg()[0]))
        except (AttributeError, OSError):
            load_1m = 0.0
        return ResourceObservation(
            observed_at=datetime.now(timezone.utc),
            root_pid=root,
            process_count=aggregate.process_count,
            child_aware=True,
            rss_mb=aggregate.rss_mb,
            peak_memory_mb=aggregate.peak_memory_mb,
            total_memory_mb=_total_memory_mb(),
            free_disk_mb=free_disk_mb,
            cpu_seconds=aggregate.cpu_seconds,
            io_read_bytes=aggregate.io_read_bytes,
            io_write_bytes=aggregate.io_write_bytes,
            io_wait_seconds=aggregate.io_wait_seconds,
            load_1m=load_1m,
        )
    current = sample_process_resources(workspace)
    return ResourceObservation(
        observed_at=datetime.now(timezone.utc),
        root_pid=root,
        process_count=1,
        child_aware=False,
        rss_mb=current.rss_mb,
        peak_memory_mb=current.peak_memory_mb,
        total_memory_mb=1.0,
        free_disk_mb=current.free_disk_mb,
        cpu_seconds=current.cpu_seconds,
        io_read_bytes=0,
        io_write_bytes=0,
        io_wait_seconds=current.io_wait_seconds,
        load_1m=0.0,
    )


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, int((percentile * len(ordered)) + 0.999999999))
    return float(ordered[min(rank, len(ordered)) - 1])


class ResourceMonitor:
    """Periodically sample child-aware resource use without blocking work."""

    COLUMN_NAMES = (
        "observed_at",
        "root_pid",
        "process_count",
        "child_aware",
        "rss_mb",
        "peak_memory_mb",
        "total_memory_mb",
        "free_disk_mb",
        "cpu_seconds",
        "io_read_bytes",
        "io_write_bytes",
        "io_wait_seconds",
        "load_1m",
    )

    ARROW_SCHEMA = pa.schema(
        [
            pa.field("observed_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("root_pid", pa.int64(), nullable=False),
            pa.field("process_count", pa.int64(), nullable=False),
            pa.field("child_aware", pa.bool_(), nullable=False),
            pa.field("rss_mb", pa.float64(), nullable=False),
            pa.field("peak_memory_mb", pa.float64(), nullable=False),
            pa.field("total_memory_mb", pa.float64(), nullable=False),
            pa.field("free_disk_mb", pa.float64(), nullable=False),
            pa.field("cpu_seconds", pa.float64(), nullable=False),
            pa.field("io_read_bytes", pa.int64(), nullable=False),
            pa.field("io_write_bytes", pa.int64(), nullable=False),
            pa.field("io_wait_seconds", pa.float64(), nullable=False),
            pa.field("load_1m", pa.float64(), nullable=False),
        ]
    )

    def __init__(
        self,
        *,
        workspace: Path,
        interval_seconds: float = 5.0,
        sampler: Callable[[], ResourceObservation] | None = None,
        on_sample: Callable[[ResourceObservation], None] | None = None,
    ) -> None:
        if not 0.01 <= interval_seconds <= 60.0:
            raise ValueError("interval_seconds must be between 0.01 and 60")
        self.workspace = Path(workspace)
        self.interval_seconds = interval_seconds
        self._sampler = sampler or (
            lambda: sample_process_tree_resources(self.workspace)
        )
        self._on_sample = on_sample
        self._samples: list[ResourceObservation] = []
        self._sampling_error_count = 0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def sample_once(self) -> ResourceObservation | None:
        try:
            observation = self._sampler()
        except Exception:
            with self._lock:
                self._sampling_error_count += 1
            return None
        with self._lock:
            self._samples.append(observation)
        if self._on_sample is not None:
            self._on_sample(observation)
        return observation

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.sample_once()
            if self._stop_event.wait(self.interval_seconds):
                break

    def start(self) -> None:
        if self.running:
            raise RuntimeError("resource monitor is already running")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="aurora-resource-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(1.0, self.interval_seconds * 2.0))
        self._thread = None

    def __enter__(self) -> ResourceMonitor:
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.stop()

    def samples(self) -> tuple[ResourceObservation, ...]:
        with self._lock:
            return tuple(self._samples)

    def summary(self) -> ResourceSummary:
        samples = self.samples()
        with self._lock:
            error_count = self._sampling_error_count
        if not samples:
            return ResourceSummary(
                sample_count=0,
                sampling_error_count=error_count,
                evidence_complete=False,
                child_aware=False,
                max_rss_mb=0.0,
                p95_rss_mb=0.0,
                max_peak_memory_mb=0.0,
                minimum_free_disk_mb=0.0,
                maximum_process_count=0,
                final_cpu_seconds=0.0,
                final_io_read_bytes=0,
                final_io_write_bytes=0,
                final_io_wait_seconds=0.0,
            )
        final = samples[-1]
        child_aware = all(sample.child_aware for sample in samples)
        evidence_complete = error_count == 0 and child_aware
        return ResourceSummary(
            sample_count=len(samples),
            sampling_error_count=error_count,
            evidence_complete=evidence_complete,
            child_aware=child_aware,
            max_rss_mb=max(sample.rss_mb for sample in samples),
            p95_rss_mb=_nearest_rank(
                [sample.rss_mb for sample in samples],
                0.95,
            ),
            max_peak_memory_mb=max(
                sample.peak_memory_mb for sample in samples
            ),
            minimum_free_disk_mb=min(
                sample.free_disk_mb for sample in samples
            ),
            maximum_process_count=max(
                sample.process_count for sample in samples
            ),
            final_cpu_seconds=final.cpu_seconds,
            final_io_read_bytes=final.io_read_bytes,
            final_io_write_bytes=final.io_write_bytes,
            final_io_wait_seconds=final.io_wait_seconds,
        )

    def write_parquet(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [
            sample.model_dump(mode="python") for sample in self.samples()
        ]
        table = pa.Table.from_pylist(records, schema=self.ARROW_SCHEMA)
        temporary = path.with_suffix(path.suffix + ".tmp")
        pq.write_table(table, temporary, compression="zstd")
        temporary.replace(path)
        return path


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
