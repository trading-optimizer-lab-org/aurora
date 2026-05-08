"""Tests for CrossListingArbSignal."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.signals import CrossListingArbSignal, CrossListingArbConfig


@pytest.fixture
def listings_with_spread():
    rng = np.random.default_rng(5)
    n = 200
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    base = 100.0 + np.cumsum(rng.normal(0.0, 0.3, n))
    noise = rng.normal(0.0, 0.5, n)
    a = base + noise
    b = base
    return pd.Series(a, index=idx), pd.Series(b, index=idx)


def test_signals_returns_dataframe(listings_with_spread):
    pa, pb = listings_with_spread
    sig = CrossListingArbSignal(CrossListingArbConfig(lookback=30, entry_z=1.5, exit_z=0.3))
    out = sig.signals(pa, pb)
    assert isinstance(out, pd.DataFrame)
    assert list(out.columns) == ["leg_a", "leg_b"]


def test_legs_are_opposite(listings_with_spread):
    pa, pb = listings_with_spread
    sig = CrossListingArbSignal(CrossListingArbConfig(lookback=30, entry_z=1.5, exit_z=0.3))
    out = sig.signals(pa, pb)
    sums = out.sum(axis=1)
    assert (sums.abs() < 1e-9).all()


def test_signal_values_in_set(listings_with_spread):
    pa, pb = listings_with_spread
    sig = CrossListingArbSignal()
    out = sig.signals(pa, pb)
    vals = np.unique(out.values)
    for v in vals:
        assert v in (-0.5, 0.0, 0.5)


def test_with_fx(listings_with_spread):
    pa, pb = listings_with_spread
    fx = pd.Series(1.0 + np.linspace(0, 0.05, len(pa)), index=pa.index)
    sig = CrossListingArbSignal()
    out = sig.signals(pa, pb, fx=fx)
    assert len(out) == len(pa)


def test_invalid_inputs():
    with pytest.raises(TypeError):
        CrossListingArbSignal().signals(np.arange(100), np.arange(100))


def test_short_overlap_raises():
    sig = CrossListingArbSignal(CrossListingArbConfig(lookback=100))
    idx = pd.date_range("2020-01-01", periods=20, freq="B")
    pa = pd.Series(np.arange(20, dtype=float), index=idx)
    pb = pd.Series(np.arange(20, dtype=float), index=idx)
    with pytest.raises(ValueError):
        sig.signals(pa, pb)
