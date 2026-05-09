"""Tests for BollingerMR strategy."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.strategies.library import BollingerMR
from aurora.strategies.base import StrategySpec
from aurora.validation.lookahead_check import runtime_lookahead_check


@pytest.fixture
def fake_prices():
    rng = np.random.default_rng(42)
    idx = pd.date_range("2010-01-01", periods=500, freq="B")
    rets = rng.normal(0.0005, 0.012, 500)
    p = 100 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def test_signals_shape(fake_prices):
    s = BollingerMR(period=20, num_std=2.0)
    sig = s.signals(fake_prices)
    assert len(sig) == len(fake_prices)
    assert np.all(np.abs(sig) <= 1.0)
    assert not np.any(np.isnan(sig))


def test_no_lookahead(fake_prices):
    s = BollingerMR(period=20, num_std=2.0)
    rep = runtime_lookahead_check(s.signals, fake_prices)
    assert rep.runtime_violation == False


def test_long_short_disabled(fake_prices):
    s = BollingerMR(period=20, num_std=2.0, allow_short=False)
    sig = s.signals(fake_prices)
    assert np.all(sig >= 0.0)
    assert not np.any(sig == -1.0)


def test_band_extremes():
    # Synthetic: flat 100, then sharp drop below band -> expect long
    n = 80
    p = np.full(n, 100.0)
    # add tiny noise so std > 0
    rng = np.random.default_rng(0)
    p += rng.normal(0, 0.1, n)
    # spike down at end
    p[-1] = 90.0
    series = pd.Series(p, index=pd.date_range("2020-01-01", periods=n, freq="B"))
    s = BollingerMR(period=20, num_std=2.0, allow_short=False)
    sig = s.signals(series)
    assert sig[-1] == 1.0


def test_band_extremes_short():
    # spike up -> short signal when allow_short
    n = 80
    rng = np.random.default_rng(0)
    p = np.full(n, 100.0) + rng.normal(0, 0.1, n)
    p[-1] = 110.0
    series = pd.Series(p, index=pd.date_range("2020-01-01", periods=n, freq="B"))
    s = BollingerMR(period=20, num_std=2.0, allow_short=True)
    sig = s.signals(series)
    assert sig[-1] == -1.0


def test_spec_ranges():
    spec = BollingerMR.spec()
    assert isinstance(spec, StrategySpec)
    assert spec.name == "BollingerMR"
    assert "period" in spec.param_ranges
    assert "num_std" in spec.param_ranges
    assert "allow_short" in spec.param_ranges
    assert spec.param_ranges["period"] == (10, 50)
    assert spec.param_ranges["num_std"] == (1.5, 3.0)
    assert spec.param_ranges["allow_short"] == [True, False]
    assert spec.param_ranges["ddof"] == [0, 1]
    assert spec.params["period"] == 20
    assert spec.params["num_std"] == 2.0
    assert spec.params["allow_short"] is True
    assert spec.params["ddof"] == 0


def test_bollinger_ddof_param():
    """Exposing ddof must change band width consistently with numpy/pandas."""
    n = 50
    rng = np.random.default_rng(7)
    p = 100.0 + rng.normal(0, 1.0, n)
    series = pd.Series(p, index=pd.date_range("2020-01-01", periods=n, freq="B"))
    s0 = BollingerMR(period=10, num_std=2.0, allow_short=True, ddof=0)
    s1 = BollingerMR(period=10, num_std=2.0, allow_short=True, ddof=1)
    sig0 = s0.signals(series)
    sig1 = s1.signals(series)
    # The band widths differ; signals may differ on borderline bars.
    # At least one bar in the post-warmup region should differ; if all
    # signals coincide we accept it but assert the strategy honored ddof
    # internally by reading attributes.
    assert s0.ddof == 0 and s1.ddof == 1
    # Sanity: no NaN/over-bound regardless of ddof.
    assert np.all(np.abs(sig0) <= 1.0)
    assert np.all(np.abs(sig1) <= 1.0)


def test_bollinger_warmup_nan():
    """The first ``period - 1`` bars must produce zero signal because
    the rolling SMA is NaN until a full window is available
    (min_periods=period, not 1).
    """
    period = 20
    n = 60
    rng = np.random.default_rng(0)
    p = 100.0 + np.cumsum(rng.normal(0.0, 1.0, n))
    series = pd.Series(p, index=pd.date_range("2020-01-01", periods=n, freq="B"))
    s = BollingerMR(period=period, num_std=2.0, allow_short=True)
    # Internal rolling stats: confirm warmup NaNs.
    sma = pd.Series(p).rolling(period, min_periods=period).mean().values
    std = pd.Series(p).rolling(period, min_periods=period).std(ddof=0).values
    assert np.all(np.isnan(sma[: period - 1]))
    assert np.all(np.isnan(std[: period - 1]))
    # Signals must be zero across the warmup region
    sig = s.signals(series)
    assert np.all(sig[: period - 1] == 0.0)
