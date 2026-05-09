"""Tests for DonchianBreakout strategy."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.strategies.library import DonchianBreakout


@pytest.fixture
def fake_prices():
    rng = np.random.default_rng(13)
    idx = pd.date_range("2010-01-01", periods=400, freq="B")
    rets = rng.normal(0.0005, 0.012, 400)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def test_signals_shape(fake_prices):
    s = DonchianBreakout(channel=55, exit_channel=20)
    sig = s.signals(fake_prices)
    assert isinstance(sig, np.ndarray)
    assert len(sig) == len(fake_prices)
    assert np.all(np.abs(sig) <= 1.0)
    assert not np.any(np.isnan(sig))


def test_donchian_no_lookahead(fake_prices):
    """Modify prices after some index k, verify signal[:k] unchanged.

    Runtime anti-lookahead check: signal at index i must depend only on prices[:i+1].
    Since we shift the breakout level by 1 bar, signal[i] uses data through i-1,
    so signal[:k] must remain identical when prices[k:] are shuffled.
    """
    s = DonchianBreakout(channel=20, exit_channel=10, allow_short=True)
    sig_full = s.signals(fake_prices)
    k = 200
    rng = np.random.default_rng(42)
    shuffled = fake_prices.values.copy()
    shuffled[k:] = rng.permutation(shuffled[k:])
    p_shuf = pd.Series(shuffled, index=fake_prices.index, name=fake_prices.name)
    sig_shuf = s.signals(p_shuf)
    assert np.allclose(sig_full[:k], sig_shuf[:k]), \
        "Donchian signal depends on future data (lookahead detected)"


def test_donchian_breakout_up():
    """Plateau then break above max -> should produce long signal."""
    n = 200
    plateau = np.full(150, 100.0)
    plateau = plateau + np.random.default_rng(1).normal(0, 0.02, 150)
    jump = np.linspace(101, 130, 50)
    p = np.concatenate([plateau, jump])
    prices = pd.Series(p, index=pd.date_range("2010-01-01", periods=n, freq="B"))
    s = DonchianBreakout(channel=20, exit_channel=10, allow_short=True)
    sig = s.signals(prices)
    assert np.any(sig[150:] == 1.0), "Expected long signal after upward breakout"


def test_truncated_match(fake_prices):
    """Signal computed on full series matches signal on truncated series for indices < k."""
    s = DonchianBreakout(channel=20, exit_channel=10, allow_short=True)
    sig_full = s.signals(fake_prices)
    k = 200
    truncated = fake_prices.iloc[:k]
    sig_trunc = s.signals(truncated)
    assert np.allclose(sig_full[:k], sig_trunc), \
        "Donchian signal on truncated series differs from full"


def test_spec_ranges():
    spec = DonchianBreakout.spec()
    assert spec.name == "DonchianBreakout"
    assert spec.params["channel"] == 55
    assert spec.params["exit_channel"] == 20


def test_donchian_one_bar_entry_lag():
    """Breakout above prior channel must produce position == 1 on the
    breakout bar i. Combined with engine's weights[i-1] * returns[i] shift,
    that gives the canonical 1-bar entry lag (decision visible at bar i,
    PnL accrues from bar i+1).

    Construction:
        bars 0..49: flat at 100
        bar 50: jump to 110 (well above prior channel max=100)
        prior 5-bar channel through bar 49 = max(100,...) = 100
        => p[50] > 100 -> sig[50] should be +1 (long entry).
    """
    n = 80
    p = np.full(n, 100.0)
    p[50:] = 110.0  # break above prior channel on bar 50, hold above
    prices = pd.Series(p, index=pd.date_range("2020-01-01", periods=n, freq="B"))
    s = DonchianBreakout(channel=5, exit_channel=3, allow_short=False)
    sig = s.signals(prices)
    # No signal in flat region (need warmup; first valid sig at bar > start)
    # Long position must activate on the breakout bar (bar 50) — that's the
    # 1-bar entry lag in conjunction with the engine's weights shift.
    assert sig[50] == 1.0, f"expected long entry on breakout bar 50, got {sig[50]}"
    # Earlier bars (still in flat plateau) must NOT be long-positioned.
    assert sig[49] == 0.0, f"expected flat on bar 49 before breakout, got {sig[49]}"
