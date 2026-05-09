"""Tests for ATRBreakout strategy."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.strategies.library import ATRBreakout
from aurora.strategies.library.atr_breakout import ATRBreakout as ATRDirect


@pytest.fixture
def fake_prices():
    rng = np.random.default_rng(7)
    idx = pd.date_range("2010-01-01", periods=500, freq="B")
    rets = rng.normal(0.0005, 0.012, 500)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def test_signals_shape(fake_prices):
    s = ATRBreakout(period=20, atr_period=14, k=1.5)
    sig = s.signals(fake_prices)
    assert isinstance(sig, np.ndarray)
    assert len(sig) == len(fake_prices)
    assert np.all(np.abs(sig) <= 1.0)
    assert not np.any(np.isnan(sig))


def test_no_lookahead(fake_prices):
    """Signal at i must depend only on prices[:i+1]."""
    s = ATRBreakout(period=20, atr_period=14, k=1.5, allow_short=True)
    sig_full = s.signals(fake_prices)
    # Truncate prices at index k and recompute. signal[k-1] must match.
    k = 200
    truncated = fake_prices.iloc[:k]
    sig_trunc = s.signals(truncated)
    # Check last index of truncated matches full at same position
    assert np.allclose(sig_trunc, sig_full[:k]), \
        "Signal depends on future data (lookahead detected)"


def test_atr_no_lookahead(fake_prices):
    """Modify prices after index k, verify signal[:k+1] unchanged.

    Runtime anti-lookahead check via shuffled-future pattern. Since rolling
    stats and ATR both use windows ending at i-1, signal[i] for i < k must be
    invariant to prices[k:].
    """
    s = ATRBreakout(period=20, atr_period=14, k=1.5, allow_short=True)
    sig_full = s.signals(fake_prices)
    k = 200
    rng = np.random.default_rng(42)
    shuffled = fake_prices.values.copy()
    shuffled[k:] = rng.permutation(shuffled[k:])
    p_shuf = pd.Series(shuffled, index=fake_prices.index, name=fake_prices.name)
    sig_shuf = s.signals(p_shuf)
    assert np.allclose(sig_full[:k], sig_shuf[:k]), \
        "ATR signal depends on future data (lookahead detected)"


def test_breakout_up():
    """Plateau then big jump up -> should produce long signal."""
    n = 200
    plateau = np.full(150, 100.0)
    # Small noise on plateau so ATR > 0 but tiny
    plateau = plateau + np.random.default_rng(1).normal(0, 0.05, 150)
    jump = np.linspace(101, 130, 50)  # sharp upward move
    p = np.concatenate([plateau, jump])
    prices = pd.Series(p, index=pd.date_range("2010-01-01", periods=n, freq="B"))
    s = ATRBreakout(period=20, atr_period=14, k=1.5, allow_short=True)
    sig = s.signals(prices)
    # Some long signal must occur post-jump
    assert np.any(sig[150:] == 1.0), "Expected long signal after upward breakout"


def test_breakout_down():
    """Plateau then big jump down + allow_short -> should produce short signal."""
    n = 200
    plateau = np.full(150, 100.0)
    plateau = plateau + np.random.default_rng(2).normal(0, 0.05, 150)
    jump = np.linspace(99, 70, 50)  # sharp downward move
    p = np.concatenate([plateau, jump])
    prices = pd.Series(p, index=pd.date_range("2010-01-01", periods=n, freq="B"))
    s = ATRBreakout(period=20, atr_period=14, k=1.5, allow_short=True)
    sig = s.signals(prices)
    assert np.any(sig[150:] == -1.0), "Expected short signal after downward breakout"


def test_long_only_disabled():
    """allow_short=False -> never -1 even on downward breakout."""
    n = 200
    plateau = np.full(150, 100.0)
    plateau = plateau + np.random.default_rng(3).normal(0, 0.05, 150)
    jump = np.linspace(99, 70, 50)
    p = np.concatenate([plateau, jump])
    prices = pd.Series(p, index=pd.date_range("2010-01-01", periods=n, freq="B"))
    s = ATRBreakout(period=20, atr_period=14, k=1.5, allow_short=False)
    sig = s.signals(prices)
    assert np.all(sig >= 0.0), "allow_short=False must never produce -1"


def test_spec_ranges():
    spec = ATRBreakout.spec()
    assert spec.name == "ATRBreakout"
    assert spec.param_ranges["period"] == (10, 100)
    assert spec.param_ranges["atr_period"] == (5, 30)
    assert spec.param_ranges["k"] == (0.5, 3.0)
    assert spec.param_ranges["allow_short"] == [True, False]
    # default params present
    assert spec.params["period"] == 20
    assert spec.params["atr_period"] == 14
    assert spec.params["k"] == 1.5
    assert spec.params["allow_short"] is True


def test_import_from_library():
    """Verify ATRBreakout exported from library package."""
    assert ATRBreakout is ATRDirect


def test_atr_one_bar_entry_lag():
    """Breakout strictly above (rolling_max + k*atr) must trigger position
    on the breakout bar. Combined with the engine's weights[i-1] * returns[i]
    shift this gives a 1-bar entry lag (decision at bar i, PnL from bar i+1).

    Construction:
        bars 0..29: tiny noise around 100 (very low ATR)
        bar 30: large jump to 130 (well above max + k*atr)
        => sig[30] should be +1.
    """
    n = 80
    rng = np.random.default_rng(11)
    base = 100.0 + rng.normal(0, 0.02, n)  # very low ATR plateau
    base[30:] = 130.0  # sharp upside breakout from bar 30 onward
    prices = pd.Series(base, index=pd.date_range("2020-01-01", periods=n, freq="B"))
    s = ATRBreakout(period=5, atr_period=5, k=1.5, allow_short=False)
    sig = s.signals(prices)
    # Long entry on the breakout bar (bar 30). The decision is visible on
    # bar 30; PnL accrual then lives on bar 31 via the engine's shift.
    assert sig[30] == 1.0, f"expected long entry on breakout bar 30, got {sig[30]}"
    # Bar 29 (last bar of plateau) must not be long.
    assert sig[29] == 0.0, f"expected flat on bar 29 before breakout, got {sig[29]}"
