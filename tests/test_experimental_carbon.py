"""Tests for CarbonAwareAllocator."""
from __future__ import annotations

import pytest

from aurora.experimental.climate_carbon_aware import (
    CarbonAwareAllocator,
    DEFAULT_CARBON_SCORES,
)


def test_adjust_returns_simplex_weights():
    alloc = CarbonAwareAllocator(penalty=1.0)
    out = alloc.adjust({"AAPL": 0.5, "XOM": 0.5})
    assert pytest.approx(1.0, abs=1e-9) == sum(out.values())
    assert all(0 <= w <= 1 for w in out.values())


def test_high_carbon_assets_get_lower_weight():
    alloc = CarbonAwareAllocator(penalty=2.0)
    out = alloc.adjust({"AAPL": 0.5, "XOM": 0.5})
    # AAPL carbon = 0.05, XOM = 1.20 in the default mock
    assert out["AAPL"] > out["XOM"]


def test_zero_penalty_preserves_weights():
    alloc = CarbonAwareAllocator(penalty=0.0)
    out = alloc.adjust({"AAPL": 0.5, "XOM": 0.5})
    assert pytest.approx(0.5, abs=1e-9) == out["AAPL"]
    assert pytest.approx(0.5, abs=1e-9) == out["XOM"]


def test_unknown_ticker_uses_default_score():
    alloc = CarbonAwareAllocator(default_score=0.5, penalty=1.0)
    # Both tickers share the default score, so weights stay equal.
    out = alloc.adjust({"UNK1": 0.5, "UNK2": 0.5})
    assert pytest.approx(0.5, abs=1e-9) == out["UNK1"]


def test_custom_score_source_overrides_default():
    custom = {"FOO": 0.0, "BAR": 5.0}
    alloc = CarbonAwareAllocator(score_source=lambda t: custom[t], penalty=1.0)
    out = alloc.adjust({"FOO": 0.5, "BAR": 0.5})
    assert out["FOO"] > out["BAR"]


def test_negative_weights_are_clipped():
    alloc = CarbonAwareAllocator(penalty=1.0)
    out = alloc.adjust({"AAPL": 0.7, "XOM": -0.5})
    assert out["XOM"] == pytest.approx(0.0, abs=1e-12)


def test_portfolio_carbon_uses_weighted_average():
    alloc = CarbonAwareAllocator()
    pc = alloc.portfolio_carbon({"AAPL": 0.5, "XOM": 0.5})
    expected = (DEFAULT_CARBON_SCORES["AAPL"] + DEFAULT_CARBON_SCORES["XOM"]) / 2
    assert pc == pytest.approx(expected)


def test_constructor_rejects_negative_penalty():
    alloc = CarbonAwareAllocator(penalty=-1.0)
    with pytest.raises(ValueError):
        alloc.adjust({"AAPL": 1.0})
