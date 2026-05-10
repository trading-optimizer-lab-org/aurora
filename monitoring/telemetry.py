"""R179 - Local telemetry and metrics contract.

A small, stdlib-only telemetry surface so paper, validation and data
runs can emit consistent metric and event records without taking on
Prometheus / OpenTelemetry as a runtime dependency. The default sink is
a local JSONL file; tests pass an in-memory sink to avoid filesystem
churn.

Correlation ids are required when known: ``run_id``, ``dataset_id``,
``snapshot_hash``, ``policy_hash``, ``strategy_id``, ``validation_id``,
``broker_order_id``, ``internal_order_id``, ``evidence_pack_id``.
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol


# Canonical correlation-id field names. Helpers in this module accept
# arbitrary kwargs but record only well-known keys to avoid drift.
KNOWN_CORRELATION_FIELDS = (
    "run_id",
    "dataset_id",
    "snapshot_hash",
    "policy_hash",
    "strategy_id",
    "validation_id",
    "broker_order_id",
    "internal_order_id",
    "evidence_pack_id",
)


@dataclass(frozen=True)
class TelemetryRecord:
    """One emitted metric or event."""

    kind: str  # "metric" | "event"
    name: str
    value: float
    timestamp: str
    correlation: Dict[str, str] = field(default_factory=dict)
    labels: Dict[str, str] = field(default_factory=dict)
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, default=str)


class TelemetrySink(Protocol):
    """Anything that can swallow a :class:`TelemetryRecord`."""

    def emit(self, record: TelemetryRecord) -> None: ...


class InMemorySink:
    """Test-only sink that retains every record in memory."""

    def __init__(self) -> None:
        self._records: List[TelemetryRecord] = []
        self._lock = threading.Lock()

    def emit(self, record: TelemetryRecord) -> None:
        with self._lock:
            self._records.append(record)

    def records(self) -> List[TelemetryRecord]:
        with self._lock:
            return list(self._records)

    def by_name(self, name: str) -> List[TelemetryRecord]:
        return [r for r in self.records() if r.name == name]


class JsonLineSink:
    """Append-only JSONL sink."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def emit(self, record: TelemetryRecord) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(record.to_json() + "\n")


class NullSink:
    """Sink that swallows everything; used as a default safety net."""

    def emit(self, record: TelemetryRecord) -> None:  # pragma: no cover - trivial
        return None


# ---------------------------------------------------------------------------
# Globals (default sink, swappable)
# ---------------------------------------------------------------------------


_default_lock = threading.Lock()
_default_sink: TelemetrySink = NullSink()


def set_default_sink(sink: TelemetrySink) -> None:
    """Swap the module-level default sink."""
    global _default_sink
    with _default_lock:
        _default_sink = sink


def get_default_sink() -> TelemetrySink:
    return _default_sink


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _select_correlation(values: Mapping[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key in KNOWN_CORRELATION_FIELDS:
        v = values.get(key)
        if v is None:
            continue
        out[key] = str(v)
    return out


def emit_metric(
    name: str,
    value: float,
    *,
    sink: Optional[TelemetrySink] = None,
    labels: Optional[Mapping[str, str]] = None,
    timestamp: Optional[str] = None,
    **correlation: Any,
) -> TelemetryRecord:
    """Emit a numeric metric. Returns the record so callers can assert."""
    record = TelemetryRecord(
        kind="metric",
        name=name,
        value=float(value),
        timestamp=timestamp or _now_iso(),
        correlation=_select_correlation(correlation),
        labels=dict(labels or {}),
        payload={},
    )
    (sink or _default_sink).emit(record)
    return record


def emit_event(
    name: str,
    *,
    sink: Optional[TelemetrySink] = None,
    payload: Optional[Mapping[str, Any]] = None,
    labels: Optional[Mapping[str, str]] = None,
    timestamp: Optional[str] = None,
    **correlation: Any,
) -> TelemetryRecord:
    """Emit a structured event. ``value`` is held at ``1.0`` for occurrence
    counting; richer numbers belong on metrics."""
    record = TelemetryRecord(
        kind="event",
        name=name,
        value=1.0,
        timestamp=timestamp or _now_iso(),
        correlation=_select_correlation(correlation),
        labels=dict(labels or {}),
        payload=dict(payload or {}),
    )
    (sink or _default_sink).emit(record)
    return record


# ---------------------------------------------------------------------------
# Convenience emitters used by the data + execution layers
# ---------------------------------------------------------------------------


def emit_data_freshness(
    *,
    dataset_id: str,
    last_observed_ts: str,
    delay_seconds: float,
    sink: Optional[TelemetrySink] = None,
    **correlation: Any,
) -> TelemetryRecord:
    return emit_metric(
        "aurora_data_freshness_seconds",
        delay_seconds,
        sink=sink,
        labels={"last_observed_ts": last_observed_ts},
        dataset_id=dataset_id,
        **correlation,
    )


def emit_validation_gate(
    *,
    gate: str,
    passed: bool,
    sink: Optional[TelemetrySink] = None,
    **correlation: Any,
) -> TelemetryRecord:
    return emit_metric(
        "aurora_validation_gate",
        1.0 if passed else 0.0,
        sink=sink,
        labels={"gate": gate, "outcome": "pass" if passed else "fail"},
        **correlation,
    )


def emit_order_latency(
    *,
    broker_order_id: str,
    latency_ms: float,
    sink: Optional[TelemetrySink] = None,
    **correlation: Any,
) -> TelemetryRecord:
    return emit_metric(
        "aurora_order_submit_latency_ms",
        latency_ms,
        sink=sink,
        broker_order_id=broker_order_id,
        **correlation,
    )


def emit_kill_switch_state(
    *, armed: bool, sink: Optional[TelemetrySink] = None, **correlation: Any,
) -> TelemetryRecord:
    return emit_metric(
        "aurora_kill_switch_armed",
        1.0 if armed else 0.0,
        sink=sink,
        **correlation,
    )


__all__ = [
    "InMemorySink",
    "JsonLineSink",
    "KNOWN_CORRELATION_FIELDS",
    "NullSink",
    "TelemetryRecord",
    "TelemetrySink",
    "emit_data_freshness",
    "emit_event",
    "emit_kill_switch_state",
    "emit_metric",
    "emit_order_latency",
    "emit_validation_gate",
    "get_default_sink",
    "set_default_sink",
]
