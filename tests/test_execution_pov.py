"""Tests for quantforge.execution.pov."""
from __future__ import annotations
from datetime import datetime, timedelta

import pytest

from aurora.execution.pov import POVAlgo, POVConfig


class MockBroker:
    symbol = "MSFT"
    def __init__(self):
        self.orders = []
    def submit_order(self, order):
        self.orders.append(order)
        return {"status": "filled", "filled_qty": order["qty"]}


def _vol_stream(n=10, vol=1000.0):
    start = datetime(2025, 1, 1, 9, 30)
    return [(start + timedelta(seconds=i), vol) for i in range(n)]


def test_pov_config_defaults():
    cfg = POVConfig()
    assert 0 < cfg.target_rate <= 1.0
    assert cfg.side == "buy"


def test_pov_invalid_rate():
    with pytest.raises(ValueError):
        POVConfig(target_rate=0.0)
    with pytest.raises(ValueError):
        POVConfig(target_rate=1.5)


def test_pov_invalid_side():
    with pytest.raises(ValueError):
        POVConfig(side="?")


def test_pov_schedule_respects_target_rate():
    algo = POVAlgo(POVConfig(target_rate=0.1, min_slice_qty=1.0))
    sched = algo.schedule(parent_qty=10_000, market_volume=_vol_stream(20))
    # each bucket sees 1000 vol, 10% = 100
    assert sched[0].qty == pytest.approx(100.0)


def test_pov_schedule_stops_when_remaining_zero():
    algo = POVAlgo(POVConfig(target_rate=0.5, min_slice_qty=1.0))
    sched = algo.schedule(parent_qty=200, market_volume=_vol_stream(10, vol=100))
    total = sum(s.qty for s in sched)
    assert total == pytest.approx(200.0)


def test_pov_negative_volume_rejected():
    algo = POVAlgo()
    bad = [(datetime(2025, 1, 1), -10)]
    with pytest.raises(ValueError):
        algo.schedule(100, bad)


def test_pov_invalid_parent():
    algo = POVAlgo()
    with pytest.raises(ValueError):
        algo.schedule(0, _vol_stream())


def test_pov_max_slice_cap():
    algo = POVAlgo(POVConfig(target_rate=0.5, max_slice_qty=50,
                             min_slice_qty=1.0))
    sched = algo.schedule(parent_qty=10_000,
                          market_volume=_vol_stream(20, vol=1000))
    # without cap each slice would be 500
    for s in sched:
        assert s.qty <= 50.0


def test_pov_remaining_decrements():
    algo = POVAlgo(POVConfig(target_rate=0.1, min_slice_qty=1.0))
    sched = algo.schedule(parent_qty=300, market_volume=_vol_stream(5, vol=1000))
    for a, b in zip(sched, sched[1:]):
        assert b.remaining_after <= a.remaining_after


def test_pov_skips_bucket_too_small():
    # qty target = 0.5 (target_rate * 1) but min_slice_qty=1
    algo = POVAlgo(POVConfig(target_rate=0.5, min_slice_qty=1.0))
    sched = algo.schedule(parent_qty=100,
                          market_volume=[(datetime(2025, 1, 1), 1.0)])
    assert sched == []


def test_pov_execute_via_broker():
    algo = POVAlgo(POVConfig(target_rate=0.1, min_slice_qty=1.0))
    broker = MockBroker()
    sched = algo.schedule(1000, _vol_stream(5, vol=1000))
    res = algo.execute(sched, broker)
    assert len(res) == len(broker.orders)
    assert len(res) > 0


def test_pov_zero_volume_skipped():
    algo = POVAlgo(POVConfig(target_rate=0.1, min_slice_qty=1.0))
    stream = [
        (datetime(2025, 1, 1), 0),
        (datetime(2025, 1, 1, 0, 1), 1000),
    ]
    sched = algo.schedule(parent_qty=100, market_volume=stream)
    assert len(sched) == 1
