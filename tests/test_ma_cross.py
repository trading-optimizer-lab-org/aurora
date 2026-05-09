"""Tests for MACross strategy."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.strategies.library import MACross
from aurora.strategies.base import StrategySpec


@pytest.fixture
def fake_prices():
    rng = np.random.default_rng(7)
    idx = pd.date_range("2010-01-01", periods=500, freq="B")
    rets = rng.normal(0.0005, 0.012, 500)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def test_signals_shape(fake_prices):
    s = MACross(fast=20, slow=100, allow_short=True)
    sig = s.signals(fake_prices)
    assert isinstance(sig, np.ndarray)
    assert len(sig) == len(fake_prices)
    assert np.all(np.abs(sig) <= 1.0)
    assert not np.any(np.isnan(sig))


def test_warmup_zero(fake_prices):
    """Bars before slow window has filled must be zero."""
    s = MACross(fast=20, slow=100, allow_short=True)
    sig = s.signals(fake_prices)
    assert np.all(sig[: 99] == 0.0)


def test_fast_ge_slow_projected_in_ctor():
    """Misconfigured fast >= slow must be projected to slow = fast + 1 by the
    ctor so the GA does not waste budget on degenerate genomes that produce
    all-zero signals.
    """
    s = MACross(fast=100, slow=100)
    assert s.slow == s.fast + 1, f"expected slow=fast+1 after projection, got slow={s.slow}"
    s2 = MACross(fast=120, slow=100)
    assert s2.slow == s2.fast + 1, f"expected slow=fast+1 after projection, got slow={s2.slow}"
    # Sanity: signals should now be non-zero somewhere on a real series.
    p = pd.Series(np.linspace(100, 200, 300),
                  index=pd.date_range("2020-01-01", periods=300, freq="B"))
    sig = MACross(fast=100, slow=100, allow_short=True).signals(p)
    assert np.any(sig != 0.0)


def test_fast_ge_slow_returns_zero_only_if_attr_mutated():
    """Defensive check: if attrs are mutated post-construction to fast>=slow,
    signals fall back to zeros via the runtime guard.
    """
    p = pd.Series(np.linspace(100, 110, 200),
                  index=pd.date_range("2020-01-01", periods=200, freq="B"))
    s = MACross(fast=20, slow=100)
    # Force a degenerate state post-init.
    s.fast = 100
    s.slow = 100
    assert np.all(s.signals(p) == 0.0)


def test_uptrend_long(fake_prices):
    """Sustained uptrend -> fast > slow -> long position."""
    p = pd.Series(np.linspace(100, 200, 200),
                  index=pd.date_range("2020-01-01", periods=200, freq="B"))
    s = MACross(fast=20, slow=100, allow_short=False)
    sig = s.signals(p)
    assert sig[-1] == 1.0


def test_downtrend_short_when_allowed():
    p = pd.Series(np.linspace(200, 100, 200),
                  index=pd.date_range("2020-01-01", periods=200, freq="B"))
    s_short = MACross(fast=20, slow=100, allow_short=True)
    s_no_short = MACross(fast=20, slow=100, allow_short=False)
    assert s_short.signals(p)[-1] == -1.0
    assert s_no_short.signals(p)[-1] == 0.0


def test_no_lookahead(fake_prices):
    """Truncating the series must not change earlier signals."""
    s = MACross(fast=20, slow=100, allow_short=True)
    sig_full = s.signals(fake_prices)
    k = 250
    sig_trunc = s.signals(fake_prices.iloc[:k])
    assert np.allclose(sig_trunc, sig_full[:k])


def test_cumsum_matches_naive_sma(fake_prices):
    """cumsum-based SMA must equal a naive pandas rolling mean within float tol."""
    s = MACross(fast=20, slow=100, allow_short=True)
    sig = s.signals(fake_prices)
    p = fake_prices.values.astype(float)
    naive_fast = pd.Series(p).rolling(20, min_periods=20).mean().values
    naive_slow = pd.Series(p).rolling(100, min_periods=100).mean().values
    # rebuild expected signal from naive SMAs
    n = len(p)
    expected = np.zeros(n)
    for i in range(99, n):
        if naive_fast[i] > naive_slow[i]:
            expected[i] = 1.0
        else:
            expected[i] = -1.0
    assert np.allclose(sig, expected)


def test_spec_ranges():
    spec = MACross.spec()
    assert isinstance(spec, StrategySpec)
    assert spec.name == "MACross"
    assert spec.params["fast"] == 20
    assert spec.params["slow"] == 100
    assert spec.param_ranges["fast"] == (5, 60)
    assert spec.param_ranges["slow"] == (50, 300)


def test_ma_cross_ctor_does_not_mutate_when_valid():
    """When fast < slow already, ctor must leave attrs untouched."""
    s = MACross(fast=10, slow=50)
    assert s.fast == 10
    assert s.slow == 50
