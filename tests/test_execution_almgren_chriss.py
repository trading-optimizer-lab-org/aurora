"""Tests for aurora.execution.almgren_chriss."""
from __future__ import annotations
from datetime import datetime

import numpy as np
import pytest

from aurora.execution.almgren_chriss import (
    AlmgrenChrissExecutor,
    AlmgrenChrissConfig,
)


class MockBroker:
    symbol = "TSLA"
    def __init__(self):
        self.orders = []
    def submit_order(self, order):
        self.orders.append(order)
        return {"status": "filled", "filled_qty": order["qty"]}


def test_ac_config_defaults():
    cfg = AlmgrenChrissConfig()
    assert cfg.n_steps >= 1
    assert cfg.eta > 0


def test_ac_config_invalid():
    with pytest.raises(ValueError):
        AlmgrenChrissConfig(n_steps=0)
    with pytest.raises(ValueError):
        AlmgrenChrissConfig(eta=0.0)
    with pytest.raises(ValueError):
        AlmgrenChrissConfig(side="x")


def test_ac_trajectory_endpoints():
    ex = AlmgrenChrissExecutor(AlmgrenChrissConfig(n_steps=10))
    x = ex.trajectory(parent_qty=1000)
    assert x[0] == pytest.approx(1000.0)
    assert x[-1] == pytest.approx(0.0)


def test_ac_trajectory_zero_risk_is_linear():
    ex = AlmgrenChrissExecutor(
        AlmgrenChrissConfig(n_steps=4, risk_aversion=0.0)
    )
    x = ex.trajectory(1000)
    diffs = np.diff(x)
    # all step sizes equal under risk neutral
    assert np.allclose(diffs, diffs[0])


def test_ac_trajectory_high_risk_is_front_loaded():
    low = AlmgrenChrissExecutor(
        AlmgrenChrissConfig(n_steps=10, risk_aversion=0.0,
                            sigma=0.02, eta=1e-3, gamma=1e-4)
    )
    high = AlmgrenChrissExecutor(
        AlmgrenChrissConfig(n_steps=10, risk_aversion=20.0,
                            sigma=0.02, eta=1e-3, gamma=1e-4)
    )
    qty = 1000
    # holdings after first trade: high risk_aversion sells more
    x_low = low.trajectory(qty)
    x_high = high.trajectory(qty)
    assert x_high[1] <= x_low[1]


def test_ac_invalid_qty():
    ex = AlmgrenChrissExecutor()
    with pytest.raises(ValueError):
        ex.trajectory(0)


def test_ac_schedule_trades_sum_to_parent():
    ex = AlmgrenChrissExecutor(AlmgrenChrissConfig(n_steps=8))
    sched = ex.schedule(parent_qty=400, start=datetime(2025, 1, 1))
    total = sum(s.trade_qty for s in sched)
    assert total == pytest.approx(400.0)


def test_ac_expected_cost_positive_pieces():
    ex = AlmgrenChrissExecutor()
    cost = ex.expected_cost(1000)
    assert cost["impact_cost"] >= 0
    assert cost["trajectory_variance"] >= 0
    assert cost["objective"] >= 0


def test_ac_execute_via_broker():
    ex = AlmgrenChrissExecutor(AlmgrenChrissConfig(n_steps=4))
    broker = MockBroker()
    sched = ex.schedule(100, datetime(2025, 1, 1))
    res = ex.execute(sched, broker)
    assert len(res) == 4


def test_ac_step_indices_are_one_indexed():
    ex = AlmgrenChrissExecutor(AlmgrenChrissConfig(n_steps=3))
    sched = ex.schedule(30, datetime(2025, 1, 1))
    assert [s.step for s in sched] == [1, 2, 3]


def test_ac_holdings_monotonic_for_sell():
    ex = AlmgrenChrissExecutor(AlmgrenChrissConfig(n_steps=10))
    sched = ex.schedule(1000, datetime(2025, 1, 1))
    holdings = [s.holdings_after for s in sched]
    for a, b in zip(holdings, holdings[1:]):
        assert b <= a + 1e-9
