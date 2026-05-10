"""Tests for R179 local telemetry."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aurora.monitoring.telemetry import (
    InMemorySink,
    JsonLineSink,
    KNOWN_CORRELATION_FIELDS,
    NullSink,
    TelemetryRecord,
    emit_data_freshness,
    emit_event,
    emit_kill_switch_state,
    emit_metric,
    emit_order_latency,
    emit_validation_gate,
    get_default_sink,
    set_default_sink,
)


def test_in_memory_sink_records():
    sink = InMemorySink()
    emit_metric("x", 1.0, sink=sink)
    emit_metric("x", 2.0, sink=sink)
    records = sink.records()
    assert [r.value for r in records] == [1.0, 2.0]


def test_in_memory_sink_filter_by_name():
    sink = InMemorySink()
    emit_metric("a", 1.0, sink=sink)
    emit_metric("b", 2.0, sink=sink)
    assert [r.name for r in sink.by_name("a")] == ["a"]


def test_emit_metric_drops_unknown_correlation_fields():
    sink = InMemorySink()
    emit_metric(
        "x", 1.0, sink=sink,
        run_id="R1",
        unknown_field="ignored",
        snapshot_hash="S1",
    )
    rec = sink.records()[0]
    assert rec.correlation == {"run_id": "R1", "snapshot_hash": "S1"}


def test_emit_event_payload_kept():
    sink = InMemorySink()
    emit_event(
        "kill_switch_armed", sink=sink,
        payload={"reason": "drawdown breach"},
        strategy_id="alpha",
    )
    rec = sink.records()[0]
    assert rec.kind == "event"
    assert rec.payload["reason"] == "drawdown breach"
    assert rec.correlation["strategy_id"] == "alpha"


def test_default_sink_swappable():
    set_default_sink(NullSink())
    assert isinstance(get_default_sink(), NullSink)
    sink = InMemorySink()
    set_default_sink(sink)
    emit_metric("x", 1.0)
    assert sink.records()
    set_default_sink(NullSink())


def test_jsonline_sink_writes_lines(tmp_path: Path):
    path = tmp_path / "telemetry.jsonl"
    sink = JsonLineSink(path)
    emit_metric("x", 1.0, sink=sink, run_id="R1")
    emit_event("y", sink=sink, run_id="R1")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    payloads = [json.loads(line) for line in lines]
    assert payloads[0]["kind"] == "metric"
    assert payloads[1]["kind"] == "event"


def test_data_freshness_emits_metric_and_label():
    sink = InMemorySink()
    emit_data_freshness(
        dataset_id="prices_daily",
        last_observed_ts="2026-05-09T20:00:00Z",
        delay_seconds=120.0,
        sink=sink,
    )
    rec = sink.records()[0]
    assert rec.name == "aurora_data_freshness_seconds"
    assert rec.value == 120.0
    assert rec.labels["last_observed_ts"] == "2026-05-09T20:00:00Z"


def test_validation_gate_metric():
    sink = InMemorySink()
    emit_validation_gate(gate="benchmark", passed=True, sink=sink)
    emit_validation_gate(gate="data_quality", passed=False, sink=sink)
    records = sink.records()
    assert records[0].value == 1.0
    assert records[1].value == 0.0
    assert records[1].labels["outcome"] == "fail"


def test_order_latency_records_correlation():
    sink = InMemorySink()
    emit_order_latency(
        broker_order_id="BO-1",
        latency_ms=42.0,
        sink=sink,
        strategy_id="alpha",
    )
    rec = sink.records()[0]
    assert rec.value == 42.0
    assert rec.correlation["broker_order_id"] == "BO-1"
    assert rec.correlation["strategy_id"] == "alpha"


def test_kill_switch_metric_value_matches_state():
    sink = InMemorySink()
    emit_kill_switch_state(armed=True, sink=sink)
    emit_kill_switch_state(armed=False, sink=sink)
    records = sink.records()
    assert records[0].value == 1.0
    assert records[1].value == 0.0


def test_known_correlation_fields_include_required_ids():
    required = {
        "run_id", "snapshot_hash", "policy_hash", "strategy_id",
        "validation_id", "broker_order_id", "internal_order_id",
        "evidence_pack_id", "dataset_id",
    }
    assert required.issubset(set(KNOWN_CORRELATION_FIELDS))


def test_telemetry_record_to_json_round_trip():
    rec = TelemetryRecord(
        kind="metric", name="x", value=1.0,
        timestamp="2026-05-10T00:00:00+00:00",
        correlation={"run_id": "R1"},
        labels={"l": "1"},
    )
    payload = json.loads(rec.to_json())
    assert payload["name"] == "x"
    assert payload["correlation"]["run_id"] == "R1"
