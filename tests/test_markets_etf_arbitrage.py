"""Tests for quantforge.markets.etf_arbitrage."""
from __future__ import annotations

import pytest

from aurora.markets.etf_arbitrage import (
    ETFArbitrageConfig,
    ETFArbitrageDetector,
)


@pytest.fixture
def etf() -> ETFArbitrageDetector:
    return ETFArbitrageDetector(ETFArbitrageConfig(seed=1, threshold_bps=10))


def test_nav_has_columns(etf: ETFArbitrageDetector) -> None:
    df = etf.analyze(mock=True)
    assert {"etf", "price", "nav", "premium_bps"}.issubset(df.columns)


def test_signals_detect_premium_and_discount(
        etf: ETFArbitrageDetector) -> None:
    df = etf.analyze(mock=True)
    sigs = etf.signals(df)
    # Mock generator forces a premium on first ETF and a discount on third.
    assert (sigs["signal"] == 1).any()
    assert (sigs["signal"] == -1).any()


def test_signals_neutral_within_threshold(
        etf: ETFArbitrageDetector) -> None:
    df = etf.analyze(mock=True)
    sigs = etf.signals(df)
    # Other ETFs should be near zero.
    assert (sigs["signal"] == 0).any()
