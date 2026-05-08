"""Tests for quantforge.markets.commodities_physical."""
from __future__ import annotations

import pytest

from quantforge.markets.commodities_physical import (
    CommoditiesRollAnalyzer,
    CommoditiesRollConfig,
)


@pytest.fixture
def cr() -> CommoditiesRollAnalyzer:
    return CommoditiesRollAnalyzer(CommoditiesRollConfig(seed=1))


def test_curve_has_n_contracts(cr: CommoditiesRollAnalyzer) -> None:
    df = cr.analyze(mock=True)
    assert not df.empty
    assert {"symbol", "contract_month", "price", "tenor_years"}.issubset(
        df.columns)


def test_signals_classify_regime(cr: CommoditiesRollAnalyzer) -> None:
    df = cr.analyze(mock=True)
    sigs = cr.signals(df)
    assert {"symbol", "regime", "roll_yield"}.issubset(sigs.columns)
    assert set(sigs["regime"].unique()).issubset(
        {"contango", "backwardation", "flat"})


def test_oil_default_is_contango(cr: CommoditiesRollAnalyzer) -> None:
    df = cr.analyze(mock=True)
    sigs = cr.signals(df)
    cl = sigs[sigs["symbol"] == "CL"].iloc[0]
    assert cl["regime"] == "contango"
