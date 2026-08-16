"""Deterministic performance evidence for SP500 catalog evaluation.

This module records operational work only.  It never reads market data and it
never changes the catalog's scientific result.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence, TypeVar


T = TypeVar("T")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_component(lane_id: str, configuration_sha256: str) -> None:
    if not lane_id:
        raise ValueError("CATALOG_PERFORMANCE_LANE_EMPTY")
    if (
        len(configuration_sha256) != 64
        or any(character not in "0123456789abcdef" for character in configuration_sha256)
    ):
        raise ValueError("CATALOG_PERFORMANCE_COMPONENT_HASH_INVALID")


@dataclass(frozen=True)
class CatalogPerformanceOutputs:
    """Paths and integrity evidence emitted by one recorder."""

    summary_path: Path
    events_path: Path
    event_count: int
    summary_path_sha256: str
    events_path_sha256: str

    @property
    def summary_sha256(self) -> str:
        return self.summary_path_sha256


class _ComponentBuildSpan(AbstractContextManager["_ComponentBuildSpan"]):
    def __init__(
        self,
        recorder: CatalogPerformanceRecorder,
        lane_id: str,
        configuration_sha256: str,
    ) -> None:
        _require_component(lane_id, configuration_sha256)
        self._recorder = recorder
        self._lane_id = lane_id
        self._configuration_sha256 = configuration_sha256
        self._wall_started = 0.0
        self._cpu_started = 0.0
        self._memory_started = 0.0

    def __enter__(self) -> _ComponentBuildSpan:
        self._memory_started = float(self._recorder.memory_mb())
        self._wall_started = float(self._recorder.clock())
        self._cpu_started = float(self._recorder.cpu_clock())
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        cpu_completed = float(self._recorder.cpu_clock())
        wall_completed = float(self._recorder.clock())
        memory_completed = float(self._recorder.memory_mb())
        self._recorder._append_event(
            {
                "event_index": len(self._recorder._events),
                "event_kind": "component",
                "lane_id": self._lane_id,
                "configuration_sha256": self._configuration_sha256,
                "evaluation_origin": "physical",
                "physical": True,
                "cache_hit": False,
                "duration_seconds": max(0.0, wall_completed - self._wall_started),
                "cpu_seconds": max(0.0, cpu_completed - self._cpu_started),
                "peak_memory_mb": max(self._memory_started, memory_completed),
                "succeeded": exc_type is None,
            }
        )


class _OperationalPhaseSpan(AbstractContextManager["_OperationalPhaseSpan"]):
    def __init__(
        self,
        recorder: CatalogPerformanceRecorder,
        phase: str,
        *,
        sample_memory: bool,
    ) -> None:
        if not phase or any(character.isspace() for character in phase):
            raise ValueError("CATALOG_PERFORMANCE_PHASE_INVALID")
        self._recorder = recorder
        self._phase = phase
        self._sample_memory = sample_memory
        self._wall_started = 0.0
        self._cpu_started = 0.0
        self._memory_started = 0.0
        self._units_processed = 0
        self._bytes_read = 0
        self._bytes_written = 0

    def add_units(self, value: int) -> None:
        if value < 0:
            raise ValueError("CATALOG_PERFORMANCE_UNITS_NEGATIVE")
        self._units_processed += value

    def add_bytes_read(self, value: int) -> None:
        if value < 0:
            raise ValueError("CATALOG_PERFORMANCE_BYTES_READ_NEGATIVE")
        self._bytes_read += value

    def add_bytes_written(self, value: int) -> None:
        if value < 0:
            raise ValueError("CATALOG_PERFORMANCE_BYTES_WRITTEN_NEGATIVE")
        self._bytes_written += value

    def __enter__(self) -> _OperationalPhaseSpan:
        if self._sample_memory:
            self._memory_started = float(self._recorder.memory_mb())
        self._wall_started = float(self._recorder.clock())
        self._cpu_started = float(self._recorder.cpu_clock())
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        cpu_completed = float(self._recorder.cpu_clock())
        wall_completed = float(self._recorder.clock())
        memory_completed = (
            float(self._recorder.memory_mb()) if self._sample_memory else 0.0
        )
        self._recorder._append_event(
            {
                "event_index": len(self._recorder._events),
                "event_kind": "phase",
                "phase": self._phase,
                "duration_seconds": max(0.0, wall_completed - self._wall_started),
                "cpu_seconds": max(0.0, cpu_completed - self._cpu_started),
                "units_processed": self._units_processed,
                "bytes_read": self._bytes_read,
                "bytes_written": self._bytes_written,
                "peak_memory_mb": max(self._memory_started, memory_completed),
                "succeeded": exc_type is None,
            }
        )


def _nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return float(ordered[rank - 1])


class CatalogPerformanceRecorder:
    """Collect component-level evidence without affecting scientific code."""

    THERMAL_STATES = {
        "cold",
        "runtime_warm",
        "component_warm",
        "fully_hot",
    }

    def __init__(
        self,
        *,
        shard_index: int,
        total_shards: int,
        thermal_state: str,
        clock: Callable[[], float] = time.perf_counter,
        cpu_clock: Callable[[], float] = time.process_time,
        memory_mb: Callable[[], float] = lambda: 0.0,
    ) -> None:
        if total_shards <= 0 or not 0 <= shard_index < total_shards:
            raise ValueError("CATALOG_PERFORMANCE_SHARD_INVALID")
        if thermal_state not in self.THERMAL_STATES:
            raise ValueError("CATALOG_PERFORMANCE_THERMAL_STATE_INVALID")
        self.shard_index = shard_index
        self.total_shards = total_shards
        self.thermal_state = thermal_state
        self.clock = clock
        self.cpu_clock = cpu_clock
        self.memory_mb = memory_mb
        self._events: list[dict[str, object]] = []

    def component_build(
        self,
        lane_id: str,
        configuration_sha256: str,
    ) -> _ComponentBuildSpan:
        return _ComponentBuildSpan(self, lane_id, configuration_sha256)

    def phase(
        self,
        name: str,
        *,
        sample_memory: bool = True,
    ) -> _OperationalPhaseSpan:
        return _OperationalPhaseSpan(
            self,
            name,
            sample_memory=sample_memory,
        )

    def measure(self, name: str, operation: Callable[[], T]) -> T:
        """Time one lightweight operation and preserve its return value."""

        with self.phase(name, sample_memory=False) as span:
            result = operation()
            span.add_units(1)
        return result

    def component_cache_hit(
        self,
        lane_id: str,
        configuration_sha256: str,
    ) -> None:
        _require_component(lane_id, configuration_sha256)
        self._append_event(
            {
                "event_index": len(self._events),
                "event_kind": "component",
                "lane_id": lane_id,
                "configuration_sha256": configuration_sha256,
                "evaluation_origin": "island_cache",
                "physical": False,
                "cache_hit": True,
                "duration_seconds": 0.0,
                "cpu_seconds": 0.0,
                "peak_memory_mb": float(self.memory_mb()),
                "succeeded": True,
            }
        )

    def _append_event(self, event: dict[str, object]) -> None:
        self._events.append(event)

    def summary(self) -> dict[str, object]:
        component_events = [
            event for event in self._events if event["event_kind"] == "component"
        ]
        physical = [event for event in component_events if event["physical"]]
        cache_hits = [event for event in component_events if event["cache_hit"]]
        component_profiles: dict[str, dict[str, object]] = {}
        component_identities = sorted(
            {
                (str(event["lane_id"]), str(event["configuration_sha256"]))
                for event in component_events
            }
        )
        for lane_id, configuration_sha256 in component_identities:
            selected = [
                event
                for event in component_events
                if event["lane_id"] == lane_id
                and event["configuration_sha256"] == configuration_sha256
            ]
            selected_physical = [event for event in selected if event["physical"]]
            durations = [
                float(event["duration_seconds"]) for event in selected_physical
            ]
            component_profiles[f"{lane_id}:{configuration_sha256}"] = {
                "lane_id": lane_id,
                "configuration_sha256": configuration_sha256,
                "requests": len(selected),
                "physical_builds": len(selected_physical),
                "cache_hits": sum(bool(event["cache_hit"]) for event in selected),
                "physical_seconds": sum(durations),
                "physical_cpu_seconds": sum(
                    float(event["cpu_seconds"]) for event in selected_physical
                ),
                "p50_seconds": _nearest_rank(durations, 0.50),
                "p90_seconds": _nearest_rank(durations, 0.90),
                "p95_seconds": _nearest_rank(durations, 0.95),
                "p99_seconds": _nearest_rank(durations, 0.99),
            }
        phase_events = [
            event for event in self._events if event["event_kind"] == "phase"
        ]
        phase_totals: dict[str, dict[str, int | float]] = {}
        for phase in sorted({str(event["phase"]) for event in phase_events}):
            selected = [event for event in phase_events if event["phase"] == phase]
            durations = [float(event["duration_seconds"]) for event in selected]
            phase_totals[phase] = {
                "count": len(selected),
                "duration_seconds": sum(durations),
                "cpu_seconds": sum(float(event["cpu_seconds"]) for event in selected),
                "units_processed": sum(int(event["units_processed"]) for event in selected),
                "bytes_read": sum(int(event["bytes_read"]) for event in selected),
                "bytes_written": sum(int(event["bytes_written"]) for event in selected),
                "p50_seconds": _nearest_rank(durations, 0.50),
                "p90_seconds": _nearest_rank(durations, 0.90),
                "p95_seconds": _nearest_rank(durations, 0.95),
                "p99_seconds": _nearest_rank(durations, 0.99),
            }
        peak_memory_mb = (
            max(float(event["peak_memory_mb"]) for event in self._events)
            if self._events
            else float(self.memory_mb())
        )
        return {
            "schema_version": 1,
            "shard_index": self.shard_index,
            "total_shards": self.total_shards,
            "thermal_state": self.thermal_state,
            "component_requests": len(component_events),
            "physical_component_builds": len(physical),
            "component_cache_hits": len(cache_hits),
            "component_profiles": component_profiles,
            "physical_component_seconds": sum(
                float(event["duration_seconds"]) for event in physical
            ),
            "physical_component_cpu_seconds": sum(
                float(event["cpu_seconds"]) for event in physical
            ),
            "operational_phase_seconds": sum(
                float(event["duration_seconds"]) for event in phase_events
            ),
            "operational_phase_cpu_seconds": sum(
                float(event["cpu_seconds"]) for event in phase_events
            ),
            "phase_totals": phase_totals,
            "peak_memory_mb": peak_memory_mb,
            "validation_opened": False,
            "locked_opened": False,
        }

    def write(self, output_dir: Path) -> CatalogPerformanceOutputs:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_path = output_dir / "performance.json"
        events_path = output_dir / "performance_events.jsonl"
        summary_bytes = _canonical_json_bytes(self.summary()) + b"\n"
        events_bytes = b"".join(
            _canonical_json_bytes(event) + b"\n" for event in self._events
        )
        summary_path.write_bytes(summary_bytes)
        events_path.write_bytes(events_bytes)
        return CatalogPerformanceOutputs(
            summary_path=summary_path,
            events_path=events_path,
            event_count=len(self._events),
            summary_path_sha256=_sha256_bytes(summary_bytes),
            events_path_sha256=_sha256_bytes(events_bytes),
        )


def aggregate_catalog_performance(roots: Sequence[Path]) -> dict[str, object]:
    """Reduce verified shard telemetry and expose cross-shard duplication."""

    if not roots:
        raise ValueError("CATALOG_PERFORMANCE_SHARDS_EMPTY")
    summaries: list[dict[str, object]] = []
    events: list[dict[str, object]] = []
    for root in roots:
        root = Path(root)
        summary_path = root / "performance.json"
        events_path = root / "performance_events.jsonl"
        if not summary_path.is_file() or not events_path.is_file():
            raise ValueError("CATALOG_PERFORMANCE_SHARD_INCOMPLETE")
        summary = json.loads(summary_path.read_text("utf-8"))
        if (
            summary.get("schema_version") != 1
            or summary.get("validation_opened") is not False
            or summary.get("locked_opened") is not False
        ):
            raise ValueError("CATALOG_PERFORMANCE_BOUNDARY_INVALID")
        summaries.append(summary)
        events.extend(
            json.loads(line)
            for line in events_path.read_text("utf-8").splitlines()
            if line
        )
    total_shards = {int(summary["total_shards"]) for summary in summaries}
    shard_indices = [int(summary["shard_index"]) for summary in summaries]
    if (
        len(total_shards) != 1
        or len(set(shard_indices)) != len(shard_indices)
        or len(summaries) != next(iter(total_shards))
        or set(shard_indices) != set(range(len(summaries)))
    ):
        raise ValueError("CATALOG_PERFORMANCE_SHARD_SET_INVALID")
    component_events = [
        event for event in events if event.get("event_kind") == "component"
    ]
    physical = [event for event in component_events if event.get("physical") is True]
    unique_physical = {
        (str(event["lane_id"]), str(event["configuration_sha256"]))
        for event in physical
    }
    redundant = len(physical) - len(unique_physical)
    return {
        "schema_version": 1,
        "completed_shards": len(summaries),
        "total_shards": next(iter(total_shards)),
        "thermal_states": sorted({str(summary["thermal_state"]) for summary in summaries}),
        "event_count": len(events),
        "component_requests": len(component_events),
        "physical_component_builds": len(physical),
        "component_cache_hits": sum(
            event.get("cache_hit") is True for event in component_events
        ),
        "unique_physical_components": len(unique_physical),
        "redundant_component_builds": redundant,
        "redundant_component_build_ratio": (
            float(redundant / len(physical)) if physical else 0.0
        ),
        "physical_component_seconds": sum(
            float(event["duration_seconds"]) for event in physical
        ),
        "physical_component_cpu_seconds": sum(
            float(event["cpu_seconds"]) for event in physical
        ),
        "peak_memory_mb": max(float(summary["peak_memory_mb"]) for summary in summaries),
        "validation_opened": False,
        "locked_opened": False,
    }


__all__ = [
    "CatalogPerformanceOutputs",
    "CatalogPerformanceRecorder",
    "aggregate_catalog_performance",
]
