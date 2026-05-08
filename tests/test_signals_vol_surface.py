"""Tests for VolSurfaceSignal."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.signals import VolSurfaceSignal, VolSurfaceConfig


@pytest.fixture
def synthetic_chain():
    """Mock options chain. Calls + puts at varying strikes with skewed IV."""
    spot = 100.0
    strikes = np.linspace(80, 120, 9)
    rows = []
    for K in strikes:
        # Higher IV for OTM puts (negative skew)
        moneyness = K / spot
        iv_call = 0.20 + 0.05 * max(0, moneyness - 1.0)
        iv_put = 0.20 + 0.10 * max(0, 1.0 - moneyness)
        rows.append({"strike": K, "impliedVolatility": iv_call, "type": "call"})
        rows.append({"strike": K, "impliedVolatility": iv_put, "type": "put"})
    return pd.DataFrame(rows), spot


def test_compute_skew_from_chain_returns_float(synthetic_chain):
    chain, spot = synthetic_chain
    sig = VolSurfaceSignal()
    sk = sig.compute_skew_from_chain(chain, spot, T_years=0.25)
    assert isinstance(sk, float)
    assert np.isfinite(sk)


def test_skew_is_positive_for_negative_skewed_chain(synthetic_chain):
    chain, spot = synthetic_chain
    sig = VolSurfaceSignal()
    sk = sig.compute_skew_from_chain(chain, spot, T_years=0.25)
    # Puts have higher IV than calls -> skew > 0
    assert sk >= 0


def test_signals_returns_pd_series_int():
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-01", periods=120, freq="B")
    skew = pd.Series(rng.normal(0, 1, 120), index=idx)
    sig = VolSurfaceSignal(VolSurfaceConfig(rolling_window=30, z_threshold=1.0, min_periods=10))
    out = sig.signals(skew)
    assert isinstance(out, pd.Series)
    assert set(np.unique(out.values)).issubset({-1, 0, 1})
    assert len(out) == len(skew)


def test_signals_empty_chain():
    sig = VolSurfaceSignal()
    res = sig.compute_skew_from_chain(pd.DataFrame(), 100.0, 0.25)
    assert np.isnan(res)


def test_signals_requires_series():
    sig = VolSurfaceSignal()
    with pytest.raises(TypeError):
        sig.signals(np.zeros(100))


def test_fetch_skew_history_offline_safe():
    sig = VolSurfaceSignal()
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    out = sig.fetch_skew_history("DOES_NOT_EXIST_TICKER_XYZ", idx)
    assert isinstance(out, pd.Series)
    assert len(out) == 5
