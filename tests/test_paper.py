"""Paper-trading focused tests for aurora.deployment.brokers.PaperBroker.

Most PaperBroker behavior is exercised by test_brokers.py. This file groups
the regression tests added during the deep-audit hardening pass so they are
easy to navigate and gate on in CI.
"""
from __future__ import annotations

import pytest

from aurora.deployment.brokers import (
    BrokerConfig,
    Order,
    PaperBroker,
)


def _paper(starting_cash: float = 100_000.0) -> PaperBroker:
    return PaperBroker(BrokerConfig(name="paper", paper=True),
                       starting_cash=starting_cash)


@pytest.fixture(autouse=True)
def _isolate_audit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


def test_paper_idempotent_does_not_double_charge():
    pb = _paper(starting_cash=10_000.0)
    pb.set_last_price("SPY", 400.0)
    cid = "stable-id-1"
    o = Order(symbol="SPY", qty=2, side="buy", order_type="market",
              client_order_id=cid)
    r1 = pb.submit_order(o)
    cash = pb.get_account()["cash"]
    qty = pb.get_positions()[0].qty
    # Retry with the same id.
    r2 = pb.submit_order(Order(symbol="SPY", qty=2, side="buy",
                               order_type="market", client_order_id=cid))
    assert r1 == r2
    assert pb.get_account()["cash"] == pytest.approx(cash)
    assert pb.get_positions()[0].qty == qty


def test_paper_side_flip_resets_avg_cost():
    pb = _paper(starting_cash=200_000.0)
    pb.set_last_price("SPY", 400.0)
    pb.submit_order(Order(symbol="SPY", qty=10, side="buy",
                          order_type="market"))
    # Flip via direct internal update at 410.
    pb._update_position("SPY", -15.0, 410.0)
    pos = pb._state.positions["SPY"]
    assert pos.qty == pytest.approx(-5.0)
    assert pos.avg_price == pytest.approx(410.0)


def test_paper_local_position_tracked_after_market_fill():
    pb = _paper(starting_cash=100_000.0)
    pb.set_last_price("SPY", 400.0)
    pb.submit_order(Order(symbol="SPY", qty=5, side="buy",
                          order_type="market"))
    assert pb._local_positions["SPY"] == pytest.approx(5.0)
    pb.submit_order(Order(symbol="SPY", qty=2, side="sell",
                          order_type="market"))
    assert pb._local_positions["SPY"] == pytest.approx(3.0)
    # Fully close.
    pb.submit_order(Order(symbol="SPY", qty=3, side="sell",
                          order_type="market"))
    assert "SPY" not in pb._local_positions
