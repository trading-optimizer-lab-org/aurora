"""Tests for quantforge.markets.volatility_products."""
from __future__ import annotations

import pytest

from quantforge.markets.volatility_products import (
    VolatilityProductsConfig,
    VolatilityProductsTrader,
)


@pytest.fixture
def vol() -> VolatilityProductsTrader:
    return VolatilityProductsTrader(VolatilityProductsConfig(seed=1))


def test_curve_has_term_structure(vol: VolatilityProductsTrader) -> None:
    df = vol.analyze(mock=True)
    assert not df.empty
    assert {"contract", "tenor_months", "price"}.issubset(df.columns)


def test_signals_have_both_products(vol: VolatilityProductsTrader) -> None:
    df = vol.analyze(mock=True)
    sigs = vol.signals(df)
    assert set(sigs["product"]) == {"VXX", "SVXY"}


def test_vxx_decays_in_contango(vol: VolatilityProductsTrader) -> None:
    df = vol.analyze(mock=True)
    sigs = vol.signals(df)
    vxx = sigs[sigs["product"] == "VXX"].iloc[0]
    svxy = sigs[sigs["product"] == "SVXY"].iloc[0]
    if vxx["regime"] == "contango":
        assert vxx["daily_drift"] < 0
        assert svxy["daily_drift"] > 0
