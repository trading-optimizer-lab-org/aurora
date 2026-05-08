"""Tests for quantforge.dataeng.cdc_capture."""
from __future__ import annotations

import pytest

from quantforge.dataeng.cdc_capture import CDCConfig, ChangeDataCapture


@pytest.fixture
def cdc() -> ChangeDataCapture:
    return ChangeDataCapture(CDCConfig())


def test_initial_capture_is_all_inserts(cdc: ChangeDataCapture):
    events = cdc.capture({
        "AAPL": {"qty": 10.0, "avg_price": 150.0},
        "MSFT": {"qty": 5.0, "avg_price": 300.0},
    })
    ops = sorted(e.op for e in events)
    assert ops == ["insert", "insert"]


def test_no_change_emits_nothing(cdc: ChangeDataCapture):
    state = {"AAPL": {"qty": 10.0, "avg_price": 150.0}}
    cdc.capture(state)
    events = cdc.capture(dict(state))
    assert events == []


def test_update_detected(cdc: ChangeDataCapture):
    cdc.capture({"AAPL": {"qty": 10.0, "avg_price": 150.0}})
    events = cdc.capture({"AAPL": {"qty": 12.0, "avg_price": 150.0}})
    assert len(events) == 1
    assert events[0].op == "update"
    assert events[0].before["qty"] == 10.0
    assert events[0].after["qty"] == 12.0


def test_delete_detected(cdc: ChangeDataCapture):
    cdc.capture({"AAPL": {"qty": 10.0, "avg_price": 150.0}})
    events = cdc.capture({})
    assert len(events) == 1
    assert events[0].op == "delete"
    assert events[0].key == "AAPL"


def test_tolerance_skips_tiny_diff(cdc: ChangeDataCapture):
    cdc.capture({"AAPL": {"qty": 10.0, "avg_price": 150.0}})
    events = cdc.capture(
        {"AAPL": {"qty": 10.0 + 1e-12, "avg_price": 150.0 + 1e-9}})
    assert events == []


def test_reset_clears_snapshot(cdc: ChangeDataCapture):
    cdc.capture({"AAPL": {"qty": 1.0, "avg_price": 1.0}})
    cdc.reset()
    assert cdc.snapshot() == {}
    events = cdc.capture({"MSFT": {"qty": 1.0, "avg_price": 1.0}})
    assert events[0].op == "insert"
