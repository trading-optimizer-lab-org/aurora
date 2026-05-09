"""Tests for quantforge.execution.liquidity_seeking."""
from __future__ import annotations

import pytest

from aurora.execution.liquidity_seeking import (
    LiquiditySeekingAlgo,
    LiquiditySeekingConfig,
    VenueQuote,
)


class MockBroker:
    symbol = "ETH"
    def __init__(self):
        self.orders = []
    def submit_order(self, order):
        self.orders.append(order)
        return {"status": "filled", "filled_qty": order["qty"]}


def test_ls_config_defaults():
    cfg = LiquiditySeekingConfig()
    assert cfg.side == "buy"
    assert cfg.max_venues_per_tick >= 1


def test_ls_config_invalid():
    with pytest.raises(ValueError):
        LiquiditySeekingConfig(side="hold")
    with pytest.raises(ValueError):
        LiquiditySeekingConfig(max_venues_per_tick=0)


def test_ls_invalid_parent_qty():
    algo = LiquiditySeekingAlgo()
    with pytest.raises(ValueError):
        algo.schedule(0, [[]])


def test_ls_routes_to_cheapest_venue_for_buy():
    algo = LiquiditySeekingAlgo()
    snap = [[
        VenueQuote(venue="A", side_size=100, price=10.05, fee_bps=0),
        VenueQuote(venue="B", side_size=100, price=10.00, fee_bps=0),
        VenueQuote(venue="C", side_size=100, price=10.02, fee_bps=0),
    ]]
    plan = algo.schedule(parent_qty=50, venue_snapshots=snap)
    # First fill goes to B (cheapest)
    assert plan[0][0].venue == "B"


def test_ls_routes_to_richest_venue_for_sell():
    algo = LiquiditySeekingAlgo(LiquiditySeekingConfig(side="sell"))
    snap = [[
        VenueQuote(venue="A", side_size=100, price=10.05, fee_bps=0),
        VenueQuote(venue="B", side_size=100, price=10.00, fee_bps=0),
    ]]
    plan = algo.schedule(parent_qty=50, venue_snapshots=snap)
    assert plan[0][0].venue == "A"


def test_ls_respects_remaining_quantity():
    algo = LiquiditySeekingAlgo()
    snap = [[
        VenueQuote(venue="A", side_size=100, price=10.0),
        VenueQuote(venue="B", side_size=100, price=10.1),
    ]]
    plan = algo.schedule(parent_qty=80, venue_snapshots=snap)
    total = sum(a.qty for tick in plan for a in tick)
    assert total == pytest.approx(80.0)


def test_ls_respects_min_venue_size():
    algo = LiquiditySeekingAlgo(
        LiquiditySeekingConfig(min_venue_size=200)
    )
    snap = [[
        VenueQuote(venue="A", side_size=100, price=10.0),
    ]]
    plan = algo.schedule(parent_qty=50, venue_snapshots=snap)
    assert plan[0] == []


def test_ls_max_venues_per_tick():
    algo = LiquiditySeekingAlgo(
        LiquiditySeekingConfig(max_venues_per_tick=2)
    )
    snap = [[
        VenueQuote(venue=f"V{i}", side_size=10, price=10.0 + i * 0.01)
        for i in range(5)
    ]]
    plan = algo.schedule(parent_qty=20, venue_snapshots=snap)
    assert len(plan[0]) <= 2


def test_ls_aggressive_takes_full_size():
    algo = LiquiditySeekingAlgo(
        LiquiditySeekingConfig(aggressive=True, max_venues_per_tick=1)
    )
    snap = [[
        VenueQuote(venue="A", side_size=200, price=10.0),
    ]]
    plan = algo.schedule(parent_qty=500, venue_snapshots=snap)
    assert plan[0][0].qty == pytest.approx(200.0)


def test_ls_fee_changes_ranking():
    cheap_with_fee = LiquiditySeekingAlgo()
    snap = [[
        VenueQuote(venue="A", side_size=100, price=10.00, fee_bps=50),
        VenueQuote(venue="B", side_size=100, price=10.02, fee_bps=0),
    ]]
    plan = cheap_with_fee.schedule(parent_qty=50, venue_snapshots=snap)
    # B is more expensive headline but lower effective due to fee
    assert plan[0][0].venue == "B"


def test_ls_execute_calls_broker():
    algo = LiquiditySeekingAlgo()
    broker = MockBroker()
    snap = [[VenueQuote(venue="A", side_size=100, price=10.0)]]
    plan = algo.schedule(parent_qty=50, venue_snapshots=snap)
    res = algo.execute(plan, broker)
    assert len(res) == 1
    assert broker.orders[0]["venue"] == "A"


def test_ls_empty_snapshot_yields_empty_plan():
    algo = LiquiditySeekingAlgo()
    plan = algo.schedule(100, [[]])
    assert plan == [[]]
