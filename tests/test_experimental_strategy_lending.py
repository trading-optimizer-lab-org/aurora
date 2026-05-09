"""Tests for StrategyLendingMarketplace."""
from __future__ import annotations

import pytest

from aurora.experimental.strategy_lending import StrategyLendingMarketplace


def test_list_and_rent_accrues_royalty():
    m = StrategyLendingMarketplace()
    m.list_strategy("strat-a", owner="alice", royalty_per_run=2.5)
    rec = m.rent_run("strat-a", renter="bob")
    assert rec["fee"] == 2.5
    assert m.accrued["alice"] == pytest.approx(2.5)


def test_settle_zeros_balance():
    m = StrategyLendingMarketplace()
    m.list_strategy("s", owner="alice", royalty_per_run=1.0)
    m.rent_run("s", renter="bob")
    m.rent_run("s", renter="carol")
    paid = m.settle("alice")
    assert paid["paid"] == pytest.approx(2.0)
    assert m.accrued["alice"] == 0.0


def test_duplicate_listing_raises():
    m = StrategyLendingMarketplace()
    m.list_strategy("s", owner="a", royalty_per_run=1.0)
    with pytest.raises(ValueError):
        m.list_strategy("s", owner="b", royalty_per_run=2.0)


def test_negative_royalty_raises():
    m = StrategyLendingMarketplace()
    with pytest.raises(ValueError):
        m.list_strategy("s", owner="a", royalty_per_run=-0.1)


def test_unknown_strategy_rent_raises():
    m = StrategyLendingMarketplace()
    with pytest.raises(ValueError):
        m.rent_run("nope", renter="bob")


def test_runs_audit_trail():
    m = StrategyLendingMarketplace()
    m.list_strategy("s", owner="a", royalty_per_run=1.0)
    m.rent_run("s", renter="bob")
    m.rent_run("s", renter="carol")
    assert len(m.runs) == 2
    assert {r["renter"] for r in m.runs} == {"bob", "carol"}


def test_empty_inputs_raise():
    m = StrategyLendingMarketplace()
    with pytest.raises(ValueError):
        m.list_strategy("", owner="a", royalty_per_run=1.0)
    m.list_strategy("s", owner="a", royalty_per_run=1.0)
    with pytest.raises(ValueError):
        m.rent_run("s", renter="")
