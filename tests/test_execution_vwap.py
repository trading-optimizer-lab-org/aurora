"""Tests for quantforge.execution.vwap."""
from __future__ import annotations
from datetime import datetime, timedelta

import numpy as np
import pytest

from aurora.execution.vwap import VWAPAlgo, VWAPConfig


class MockBroker:
    symbol = "AAPL"
    def __init__(self):
        self.orders = []
    def submit_order(self, order):
        self.orders.append(order)
        return {"status": "filled", "filled_qty": order["qty"]}


def test_vwap_curve_normalized():
    algo = VWAPAlgo([1, 2, 3, 4])
    assert algo.volume_share.sum() == pytest.approx(1.0)


def test_vwap_empty_curve_rejected():
    with pytest.raises(ValueError):
        VWAPAlgo([])


def test_vwap_negative_curve_rejected():
    with pytest.raises(ValueError):
        VWAPAlgo([1.0, -1.0])


def test_vwap_zero_sum_rejected():
    with pytest.raises(ValueError):
        VWAPAlgo([0.0, 0.0])


def test_vwap_schedule_qty_sums_to_parent():
    curve = [1.0, 2.0, 3.0, 4.0, 5.0]
    algo = VWAPAlgo(curve)
    start = datetime(2025, 1, 1, 9, 30)
    end = start + timedelta(hours=1)
    sched = algo.schedule(parent_qty=1000, start=start, end=end)
    assert len(sched) == len(curve)
    assert sum(s.qty for s in sched) == pytest.approx(1000.0)


def test_vwap_schedule_high_volume_buckets_get_more():
    curve = [1, 1, 8]
    algo = VWAPAlgo(curve)
    start = datetime(2025, 1, 1)
    end = start + timedelta(hours=1)
    sched = algo.schedule(100, start, end)
    assert sched[2].qty > sched[0].qty
    assert sched[2].qty > sched[1].qty


def test_vwap_invalid_parent():
    algo = VWAPAlgo([1.0])
    with pytest.raises(ValueError):
        algo.schedule(0, datetime(2025, 1, 1),
                      datetime(2025, 1, 1, 1))


def test_vwap_invalid_window():
    algo = VWAPAlgo([1.0])
    s = datetime(2025, 1, 1)
    with pytest.raises(ValueError):
        algo.schedule(100, s, s)


def test_vwap_smoothing_blends_with_uniform():
    raw = [10, 0, 0]
    smooth = VWAPAlgo(raw, VWAPConfig(smooth_alpha=0.5))
    assert smooth.volume_share[1] > 0  # not zero anymore
    assert smooth.volume_share[2] > 0


def test_vwap_invalid_smooth_alpha():
    with pytest.raises(ValueError):
        VWAPConfig(smooth_alpha=-0.1)


def test_vwap_execute_calls_broker():
    algo = VWAPAlgo([1, 2, 3])
    broker = MockBroker()
    sched = algo.schedule(100, datetime(2025, 1, 1),
                          datetime(2025, 1, 1, 1))
    res = algo.execute(sched, broker)
    assert len(res) == 3
    assert len(broker.orders) == 3


def test_vwap_sell_side():
    algo = VWAPAlgo([1, 1, 1], VWAPConfig(side="sell"))
    sched = algo.schedule(30, datetime(2025, 1, 1),
                          datetime(2025, 1, 1, 1))
    assert all(s.side == "sell" for s in sched)
