"""Tests for aurora.markets.cef_premium."""
from __future__ import annotations

import pytest

from aurora.markets.cef_premium import (
    CEFPremiumConfig,
    CEFPremiumDiscount,
)


@pytest.fixture
def cef() -> CEFPremiumDiscount:
    return CEFPremiumDiscount(CEFPremiumConfig(days=120, z_window=30,
                                               z_entry=1.5, seed=1))


def test_history_columns(cef: CEFPremiumDiscount) -> None:
    df = cef.analyze(mock=True)
    assert {"date", "cef", "price", "nav", "premium_pct"}.issubset(df.columns)


def test_signals_include_z_score(cef: CEFPremiumDiscount) -> None:
    df = cef.analyze(mock=True)
    sigs = cef.signals(df)
    assert {"cef", "premium_pct", "z_score", "signal"}.issubset(sigs.columns)
    assert sigs["signal"].isin([-1, 0, 1]).all()


def test_extreme_negative_z_triggers_buy(cef: CEFPremiumDiscount) -> None:
    df = cef.analyze(mock=True)
    sigs = cef.signals(df)
    # Mock forces last bar to a wide deviation; expect at least one buy signal.
    assert (sigs["signal"] == 1).any()
