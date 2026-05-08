"""Tests for TSMomentum strategy.

Default skip is now 21 (per Moskowitz/Ooi/Pedersen). legacy_skip=True
restores the older skip=0 behavior.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.strategies.library import TSMomentum
from quantforge.strategies.base import StrategySpec


@pytest.fixture
def trending_prices():
    rng = np.random.default_rng(7)
    idx = pd.date_range("2010-01-01", periods=600, freq="B")
    rets = rng.normal(0.001, 0.01, 600)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def test_default_skip_is_21():
    s = TSMomentum()
    assert s.skip == 21
    assert s.legacy_skip is False


def test_legacy_skip_overrides():
    """legacy_skip=True forces skip=0 regardless of the skip arg."""
    s = TSMomentum(skip=21, legacy_skip=True)
    assert s.skip == 0
    assert s.legacy_skip is True


def test_signals_shape(trending_prices):
    s = TSMomentum(lookback=100, skip=21)
    sig = s.signals(trending_prices)
    assert isinstance(sig, np.ndarray)
    assert len(sig) == len(trending_prices)
    assert np.all(np.abs(sig) <= 1.0)
    assert not np.any(np.isnan(sig))


def test_warmup_zero_until_lookback_plus_skip(trending_prices):
    """No signal before bar L+skip."""
    L = 60
    sk = 21
    s = TSMomentum(lookback=L, skip=sk)
    sig = s.signals(trending_prices)
    assert np.all(sig[: L + sk] == 0.0)


def test_skip_changes_signal(trending_prices):
    """skip=0 vs skip=21 must yield different signal arrays in general."""
    s0 = TSMomentum(lookback=100, skip=0)
    s21 = TSMomentum(lookback=100, skip=21)
    sig0 = s0.signals(trending_prices)
    sig21 = s21.signals(trending_prices)
    assert not np.array_equal(sig0, sig21)


def test_legacy_skip_reproduces_old_behavior(trending_prices):
    """legacy_skip=True must equal skip=0 explicit."""
    s_legacy = TSMomentum(lookback=100, legacy_skip=True)
    s_skip0 = TSMomentum(lookback=100, skip=0)
    assert np.array_equal(s_legacy.signals(trending_prices),
                          s_skip0.signals(trending_prices))


def test_long_only_when_short_disabled(trending_prices):
    s = TSMomentum(lookback=100, skip=21, allow_short=False)
    sig = s.signals(trending_prices)
    assert np.all(sig >= 0.0)


def test_no_lookahead(trending_prices):
    """Truncating the series must not change earlier signals."""
    s = TSMomentum(lookback=100, skip=21)
    sig_full = s.signals(trending_prices)
    k = 300
    sig_trunc = s.signals(trending_prices.iloc[:k])
    assert np.allclose(sig_trunc, sig_full[:k])


def test_spec_defaults_updated():
    spec = TSMomentum.spec()
    assert isinstance(spec, StrategySpec)
    assert spec.params["skip"] == 21
    assert spec.params["legacy_skip"] is False
    assert "skip" in spec.param_ranges
    assert "legacy_skip" in spec.param_ranges
