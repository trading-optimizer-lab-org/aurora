"""Tests for DEXAggregator."""
from __future__ import annotations

import pytest

from aurora.experimental.dex_aggregator import DEXAggregator, _MockPool


def test_quotes_for_each_pool():
    agg = DEXAggregator()
    qs = agg.quotes(1000.0)
    names = {q["pool"] for q in qs}
    assert names == {"Uniswap", "SushiSwap", "Curve"}


def test_best_route_picks_max_output():
    agg = DEXAggregator()
    res = agg.best_route(1000.0)
    qs = agg.quotes(1000.0)
    best_amt = max(q["amount_out"] for q in qs)
    assert res["amount_out"] == best_amt


def test_best_route_returns_amount_in():
    agg = DEXAggregator()
    res = agg.best_route(500.0)
    assert res["amount_in"] == 500.0


def test_zero_or_negative_input_raises():
    agg = DEXAggregator()
    with pytest.raises(ValueError):
        agg.quotes(0.0)
    with pytest.raises(ValueError):
        agg.quotes(-10.0)


def test_empty_pools_raises():
    with pytest.raises(ValueError):
        DEXAggregator(pools=[])


def test_custom_pool_used():
    pool = _MockPool("Toy", reserve_in=1000.0, reserve_out=10_000.0, fee_bps=0)
    agg = DEXAggregator(pools=[pool])
    res = agg.best_route(100.0)
    assert res["pool"] == "Toy"
    # x*y=k: y_out = 100 * 10000 / (1000+100) ~= 909
    assert 900.0 < res["amount_out"] < 920.0
