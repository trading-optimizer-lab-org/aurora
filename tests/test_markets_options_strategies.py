"""Tests for quantforge.markets.options_strategies."""
from __future__ import annotations

import pytest

from aurora.markets.options_strategies import (
    OptionsStrategyBuilder,
    OptionsStrategyConfig,
)


@pytest.fixture
def builder() -> OptionsStrategyBuilder:
    return OptionsStrategyBuilder(
        OptionsStrategyConfig(spot_default=100.0, iv_default=0.25,
                              days_to_expiry=30))


def test_vertical_spread_two_legs(builder: OptionsStrategyBuilder) -> None:
    legs = builder.vertical_spread(95, 105, opt="call", debit=True)
    assert len(legs) == 2
    long_leg = next(l for l in legs if l.side == "long")
    short_leg = next(l for l in legs if l.side == "short")
    assert long_leg.strike == 95
    assert short_leg.strike == 105


def test_iron_condor_validates_strike_order(
        builder: OptionsStrategyBuilder) -> None:
    with pytest.raises(ValueError):
        builder.iron_condor(90, 95, 92, 110)


def test_iron_condor_four_legs(builder: OptionsStrategyBuilder) -> None:
    legs = builder.iron_condor(90, 95, 105, 110)
    assert len(legs) == 4
    sides = [l.side for l in legs]
    assert sides.count("long") == 2
    assert sides.count("short") == 2


def test_butterfly_payoff_peaks_at_mid(builder: OptionsStrategyBuilder) -> None:
    legs = builder.butterfly(90, 100, 110, opt="call")
    diagram = builder.payoff(legs, spot_min=80, spot_max=120, steps=41)
    peak_row = diagram.loc[diagram["payoff"].idxmax()]
    assert 95 <= peak_row["spot"] <= 105


def test_analyze_returns_greeks(builder: OptionsStrategyBuilder) -> None:
    legs = builder.vertical_spread(95, 105, opt="call", debit=True)
    net = builder.analyze(legs, spot=100.0)
    assert {"price", "delta", "gamma", "vega", "theta", "rho"}.issubset(net)
    # Long debit call spread should have positive delta.
    assert net["delta"] > 0


def test_signals_returns_dataframe(builder: OptionsStrategyBuilder) -> None:
    legs = builder.iron_condor(90, 95, 105, 110)
    sigs = builder.signals(legs)
    assert "delta" in sigs.columns
    assert len(sigs) == 1
