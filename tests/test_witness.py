"""Tests for core.witness (R146)."""
from __future__ import annotations

import time
from pathlib import Path

from aurora.core.witness import (
    Witness,
    WitnessRecorder,
    read_witnesses,
    write_witness,
)


def test_recorder_captures_kind_and_compute_seconds():
    with WitnessRecorder(kind="backtest", seed=42) as rec:
        time.sleep(0.01)
        rec.set_output({"sharpe": 1.2})
    w = rec.witness
    assert w is not None
    assert w.kind == "backtest"
    assert w.seed == 42
    assert w.compute_seconds >= 0.005


def test_recorder_accepts_zero_perf_counter_origin(monkeypatch):
    ticks = iter((0, 10_000_000))
    monkeypatch.setattr(time, "perf_counter_ns", lambda: next(ticks))
    with WitnessRecorder(kind="backtest") as rec:
        pass
    assert rec.witness is not None
    assert rec.witness.compute_seconds == 0.01


def test_recorder_hashes_input_and_output():
    with WitnessRecorder(
        kind="validation",
        seed=42,
        input_obj={"asset": "SPY", "n": 100},
    ) as rec:
        rec.set_output({"calmar": 0.8})
    w = rec.witness
    assert w.input_hash is not None
    assert w.output_hash is not None
    assert w.input_hash != w.output_hash


def test_witness_hash_deterministic_for_same_payload():
    w1 = Witness(
        run_id="run1",
        kind="backtest",
        started_at="2026-01-01T00:00:00",
        finished_at="2026-01-01T00:00:01",
        compute_seconds=1.0,
        seed=42,
        git_hash="abc",
        forge_version="1.4.1",
        policy_hash="ph",
        snapshot_ids=["s1", "s2"],
        input_hash="ih",
        output_hash="oh",
        python_version="3.14",
        platform="windows",
    )
    w2 = Witness(**w1.to_dict())
    assert w1.witness_hash() == w2.witness_hash()


def test_witness_hash_changes_when_seed_changes():
    base = Witness(
        run_id="run1",
        kind="backtest",
        started_at="2026-01-01T00:00:00",
        finished_at="2026-01-01T00:00:01",
        compute_seconds=1.0,
        seed=42,
        git_hash="abc",
        forge_version="1.4.1",
        policy_hash=None,
        snapshot_ids=[],
        input_hash=None,
        output_hash=None,
        python_version="3.14",
        platform="windows",
    )
    other = Witness(**{**base.to_dict(), "seed": 43})
    assert base.witness_hash() != other.witness_hash()


def test_persistence_round_trip(tmp_path: Path):
    log = tmp_path / "witnesses.jsonl"
    with WitnessRecorder(kind="backtest", seed=42) as rec:
        rec.set_output({"sharpe": 1.2})
    write_witness(rec.witness, log)
    rows = read_witnesses(log)
    assert len(rows) == 1
    assert rows[0].kind == "backtest"
    assert rows[0].seed == 42


def test_recorder_captures_python_and_platform():
    with WitnessRecorder(kind="ga") as rec:
        pass
    w = rec.witness
    assert w.python_version
    assert w.platform
