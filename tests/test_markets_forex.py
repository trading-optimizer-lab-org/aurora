"""Tests for quantforge.markets.forex."""
from __future__ import annotations

import pandas as pd
import pytest

from quantforge.markets.forex import ForexConfig, ForexUniverse


@pytest.fixture
def fx() -> ForexUniverse:
    return ForexUniverse(ForexConfig(mock_days=40, seed=1))


def test_pairs_list_includes_majors(fx: ForexUniverse) -> None:
    pairs = fx.pairs()
    assert "EUR/USD" in pairs
    assert "USD/JPY" in pairs
    assert len(pairs) >= 7


def test_pip_size_jpy_vs_default() -> None:
    assert ForexUniverse.pip_size("USD/JPY") == 0.01
    assert ForexUniverse.pip_size("EUR/USD") == 0.0001


def test_spread_value_jpy(fx: ForexUniverse) -> None:
    spread = fx.spread_value("USD/JPY", pips=2.0)
    assert spread == pytest.approx(0.02)


def test_analyze_returns_ohlc(fx: ForexUniverse) -> None:
    df = fx.analyze(mock=True)
    assert not df.empty
    assert {"open", "high", "low", "close", "pair", "date"}.issubset(df.columns)


def test_signals_emit_directions(fx: ForexUniverse) -> None:
    ohlc = fx.analyze(mock=True)
    sigs = fx.signals(ohlc)
    assert {"pair", "momentum_pips", "signal"}.issubset(sigs.columns)
    assert sigs["signal"].isin([-1, 0, 1]).all()
