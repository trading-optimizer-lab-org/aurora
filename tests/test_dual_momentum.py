"""Tests for DualMomentum (Antonacci single-asset variant)."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.strategies.library import DualMomentum
from quantforge.validation.lookahead_check import runtime_lookahead_check


@pytest.fixture
def fake_prices():
    rng = np.random.default_rng(42)
    idx = pd.date_range("2010-01-01", periods=2000, freq="B")
    rets = rng.normal(0.0005, 0.012, 2000)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def _uptrend(n: int = 1000, drift: float = 0.001) -> pd.Series:
    idx = pd.date_range("2010-01-01", periods=n, freq="B")
    p = 100.0 * np.cumprod(1.0 + np.full(n, drift))
    return pd.Series(p, index=idx, name="UP")


def _downtrend(n: int = 1000, drift: float = -0.001) -> pd.Series:
    idx = pd.date_range("2010-01-01", periods=n, freq="B")
    p = 100.0 * np.cumprod(1.0 + np.full(n, drift))
    return pd.Series(p, index=idx, name="DN")


def test_signals_shape(fake_prices):
    s = DualMomentum(lookback=100, skip=21)
    sig = s.signals(fake_prices)
    assert len(sig) == len(fake_prices)
    assert np.all(np.abs(sig) <= 1.0)
    assert not np.any(np.isnan(sig))


def test_long_only_no_short(fake_prices):
    s = DualMomentum(lookback=100, skip=21, allow_short=False)
    sig = s.signals(fake_prices)
    assert np.all(sig >= 0.0)
    assert not np.any(sig == -1.0)


def test_uptrend_long():
    s = DualMomentum(lookback=100, skip=21, rf_proxy=0.0, allow_short=False)
    p = _uptrend(n=500, drift=0.001)
    sig = s.signals(p)
    # After warmup, monotonic uptrend should be long
    tail = sig[-50:]
    assert np.all(tail == 1.0)


def test_downtrend_cash_no_short():
    s = DualMomentum(lookback=100, skip=21, rf_proxy=0.0, allow_short=False)
    p = _downtrend(n=500, drift=-0.001)
    sig = s.signals(p)
    # No short allowed -> cash on downtrend
    assert np.all(sig >= 0.0)
    tail = sig[-50:]
    assert np.all(tail == 0.0)


def test_downtrend_short_when_allowed():
    s = DualMomentum(lookback=100, skip=21, rf_proxy=0.0, allow_short=True)
    p = _downtrend(n=500, drift=-0.001)
    sig = s.signals(p)
    tail = sig[-50:]
    assert np.all(tail == -1.0)


def test_skip_handling(fake_prices):
    s0 = DualMomentum(lookback=100, skip=0, allow_short=True)
    s21 = DualMomentum(lookback=100, skip=21, allow_short=True)
    sig0 = s0.signals(fake_prices)
    sig21 = s21.signals(fake_prices)
    assert len(sig0) == len(sig21)
    # First 100+0 zero for s0, first 100+21 zero for s21
    assert np.all(sig0[:100] == 0.0)
    assert np.all(sig21[:121] == 0.0)
    # Different signals somewhere in valid range
    assert not np.array_equal(sig0[121:], sig21[121:])


def test_rf_proxy_filter():
    # rf_proxy > slope of trend -> still cash
    p = _uptrend(n=500, drift=0.0001)  # ~ 0.01 over 100 bars
    s_lo = DualMomentum(lookback=100, skip=0, rf_proxy=0.0, allow_short=False)
    s_hi = DualMomentum(lookback=100, skip=0, rf_proxy=0.04, allow_short=False)
    sig_lo = s_lo.signals(p)
    sig_hi = s_hi.signals(p)
    # low rf -> long; high rf (above lookback return) -> cash
    assert sig_lo[-1] == 1.0
    # 100 bars * 0.0001 ~= 1% return; rf_period = 0.04 * 100/252 ~= 1.59%
    assert sig_hi[-1] == 0.0


def test_no_lookahead(fake_prices):
    s = DualMomentum(lookback=100, skip=21, allow_short=True)
    rep = runtime_lookahead_check(s.signals, fake_prices)
    assert rep.runtime_violation is False


def test_spec_ranges():
    sp = DualMomentum.spec()
    assert sp.name == "DualMomentum"
    assert sp.param_ranges["lookback"] == (60, 504)
    assert sp.param_ranges["skip"] == (0, 30)
    assert sp.param_ranges["rf_proxy"] == (0.0, 0.04)
    assert sp.param_ranges["allow_short"] == [True, False]


def test_rf_period_geometric_scaling():
    """rf_period must compound geometrically: (1+rf)^(L/252) - 1, not linear.

    Smoke-check by constructing two trends straddling the geometric and
    linear thresholds. With L=504 and rf=0.04:
        linear   = 0.04 * 504/252 = 0.08000
        geometric= (1.04)^2 - 1   = 0.08160
    """
    L = 504
    rf = 0.04
    geo = (1.0 + rf) ** (L / 252.0) - 1.0
    lin = rf * (L / 252.0)
    # Geometric is strictly greater than linear for L > 252.
    assert geo > lin

    # Build a series where lookback return falls just BETWEEN linear (low)
    # and geometric (high) thresholds: target slightly above linear, below
    # geometric. With current geometric formula the strategy must say 0.
    # Pick drift so that (1+drift)^L - 1 sits ~ midway.
    target = (lin + geo) / 2.0  # between lin and geo
    drift = (1.0 + target) ** (1.0 / L) - 1.0

    n = L + 200
    idx = pd.date_range("2010-01-01", periods=n, freq="B")
    p = 100.0 * np.cumprod(1.0 + np.full(n, drift))
    series = pd.Series(p, index=idx, name="MID")

    s = DualMomentum(lookback=L, skip=0, rf_proxy=rf, allow_short=False)
    sig = s.signals(series)
    # With geometric scaling, ret_lookback < geo_threshold -> sig stays 0.
    assert sig[-1] == 0.0, (
        f"Expected cash with geometric scaling: ret~{target:.5f} < "
        f"geo={geo:.5f} but >= linear={lin:.5f}; got sig={sig[-1]}"
    )
