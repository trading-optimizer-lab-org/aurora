"""Tests for quantforge.execution.twap."""
from __future__ import annotations
from datetime import datetime, timedelta

import pytest

from quantforge.execution.twap import TWAPAlgo, TWAPConfig


class MockBroker:
    symbol = "SPY"
    def __init__(self):
        self.orders = []
    def submit_order(self, order):
        self.orders.append(order)
        return {"status": "filled", "filled_qty": order["qty"]}


def test_twap_config_defaults():
    cfg = TWAPConfig()
    assert cfg.n_slices == 10
    assert cfg.side == "buy"


def test_twap_invalid_n_slices():
    with pytest.raises(ValueError):
        TWAPConfig(n_slices=0)


def test_twap_invalid_side():
    with pytest.raises(ValueError):
        TWAPConfig(side="hold")


def test_twap_invalid_jitter():
    with pytest.raises(ValueError):
        TWAPConfig(jitter_seconds=-1.0)


def test_twap_schedule_basic():
    algo = TWAPAlgo(TWAPConfig(n_slices=4))
    start = datetime(2025, 1, 1, 9, 30)
    end = start + timedelta(hours=1)
    sched = algo.schedule(parent_qty=100, start=start, end=end)
    assert len(sched) == 4
    # quantities sum to parent
    assert sum(s.qty for s in sched) == pytest.approx(100.0)
    # timestamps strictly increasing
    for a, b in zip(sched, sched[1:]):
        assert a.scheduled_at < b.scheduled_at


def test_twap_schedule_residual_in_last_slice():
    algo = TWAPAlgo(TWAPConfig(n_slices=3))
    start = datetime(2025, 1, 1)
    end = start + timedelta(minutes=30)
    sched = algo.schedule(parent_qty=10, start=start, end=end)
    assert sum(s.qty for s in sched) == pytest.approx(10.0)


def test_twap_invalid_parent_qty():
    algo = TWAPAlgo()
    start = datetime(2025, 1, 1)
    with pytest.raises(ValueError):
        algo.schedule(0, start, start + timedelta(hours=1))


def test_twap_invalid_window():
    algo = TWAPAlgo()
    start = datetime(2025, 1, 1)
    with pytest.raises(ValueError):
        algo.schedule(100, start, start)


def test_twap_jitter_within_window():
    import numpy as np
    algo = TWAPAlgo(TWAPConfig(n_slices=5, jitter_seconds=10.0))
    start = datetime(2025, 1, 1, 9, 30)
    end = start + timedelta(minutes=10)
    rng = np.random.default_rng(42)
    sched = algo.schedule(100, start, end, rng=rng)
    for s in sched:
        assert start <= s.scheduled_at <= end


def test_twap_execute_via_broker():
    algo = TWAPAlgo(TWAPConfig(n_slices=3))
    broker = MockBroker()
    start = datetime(2025, 1, 1)
    end = start + timedelta(hours=1)
    sched = algo.schedule(60, start, end)
    res = algo.execute(sched, broker)
    assert len(res) == 3
    assert len(broker.orders) == 3
    assert all(o["side"] == "buy" for o in broker.orders)


def test_twap_sell_side():
    algo = TWAPAlgo(TWAPConfig(n_slices=2, side="sell"))
    sched = algo.schedule(50, datetime(2025, 1, 1),
                          datetime(2025, 1, 1, 1))
    assert all(s.side == "sell" for s in sched)
