"""Tests for quantforge.execution.iceberg."""
from __future__ import annotations

import pytest

from quantforge.execution.iceberg import (
    IcebergConfig,
    IcebergOrderManager,
)


class MockBroker:
    symbol = "BTC"
    def __init__(self, fill_full=True):
        self.orders = []
        self.fill_full = fill_full
    def submit_order(self, order):
        self.orders.append(order)
        return {
            "status": "filled",
            "filled_qty": order["qty"] if self.fill_full else 0,
        }


def test_iceberg_config_defaults():
    cfg = IcebergConfig()
    assert cfg.display_qty > 0


def test_iceberg_config_invalid():
    with pytest.raises(ValueError):
        IcebergConfig(display_qty=0)
    with pytest.raises(ValueError):
        IcebergConfig(side="x")
    with pytest.raises(ValueError):
        IcebergConfig(max_replenishments=0)


def test_iceberg_invalid_parent():
    mgr = IcebergOrderManager()
    with pytest.raises(ValueError):
        mgr.open(0)


def test_iceberg_open_initializes_displayed_and_hidden():
    mgr = IcebergOrderManager(IcebergConfig(display_qty=10))
    state = mgr.open(parent_qty=50)
    assert state.displayed_qty == 10
    assert state.hidden_qty == 40
    assert state.filled_qty == 0
    assert not state.closed


def test_iceberg_on_fill_replenishes():
    mgr = IcebergOrderManager(IcebergConfig(display_qty=10))
    state = mgr.open(parent_qty=30)
    mgr.on_fill(state, 10.0)
    assert state.filled_qty == 10
    assert state.displayed_qty == 10  # replenished
    assert state.hidden_qty == 10
    assert state.replenishments == 1


def test_iceberg_completes_on_full_fill():
    mgr = IcebergOrderManager(IcebergConfig(display_qty=5))
    state = mgr.open(parent_qty=10)
    mgr.on_fill(state, 5)
    mgr.on_fill(state, 5)
    assert state.closed
    assert state.filled_qty == 10
    assert state.remaining == 0


def test_iceberg_partial_fills():
    mgr = IcebergOrderManager(IcebergConfig(display_qty=10))
    state = mgr.open(parent_qty=30)
    mgr.on_fill(state, 4)
    assert state.displayed_qty == pytest.approx(6)
    assert state.replenishments == 0
    mgr.on_fill(state, 6)
    # display drained -> replenish
    assert state.replenishments == 1


def test_iceberg_fill_too_large_rejected():
    mgr = IcebergOrderManager(IcebergConfig(display_qty=10))
    state = mgr.open(parent_qty=30)
    with pytest.raises(ValueError):
        mgr.on_fill(state, 50)


def test_iceberg_fill_after_close_rejected():
    mgr = IcebergOrderManager(IcebergConfig(display_qty=5))
    state = mgr.open(5)
    mgr.on_fill(state, 5)
    assert state.closed
    with pytest.raises(ValueError):
        mgr.on_fill(state, 1)


def test_iceberg_negative_fill_rejected():
    mgr = IcebergOrderManager()
    state = mgr.open(100)
    with pytest.raises(ValueError):
        mgr.on_fill(state, 0)


def test_iceberg_max_replenishments():
    mgr = IcebergOrderManager(
        IcebergConfig(display_qty=1, max_replenishments=2)
    )
    state = mgr.open(parent_qty=10)
    mgr.on_fill(state, 1)  # replen 1
    mgr.on_fill(state, 1)  # replen 2
    mgr.on_fill(state, 1)  # would be replen 3 -> close
    assert state.closed


def test_iceberg_execute_drives_broker():
    mgr = IcebergOrderManager(IcebergConfig(display_qty=10))
    broker = MockBroker()
    state = mgr.open(parent_qty=30)
    res = mgr.execute(state, broker, fills=[10, 10, 10])
    assert len(res) == 3
    assert state.filled_qty == 30
