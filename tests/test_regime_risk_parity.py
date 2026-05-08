"""Tests for RegimeRiskParity.

Run: pytest quantforge/tests/test_regime_risk_parity.py -v
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.deployment.regime_risk_parity import (
    RegimeRiskParity,
    RegimeRPConfig,
    RegimeRPResult,
)


@pytest.fixture
def synthetic_prices_with_regimes():
    rng = np.random.default_rng(13)
    n = 400
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    # Two distinct cov regimes: low-vol first half, high-vol second half.
    rets = np.zeros((n, 3))
    rets[:n // 2, :] = rng.normal(0.0005, 0.005, (n // 2, 3))
    rets[n // 2:, :] = rng.normal(-0.0002, 0.02, (n - n // 2, 3))
    prices = pd.DataFrame(
        100.0 * np.cumprod(1.0 + rets, axis=0),
        columns=["X", "Y", "Z"], index=idx,
    )
    regime = pd.Series(["bull"] * (n // 2) + ["bear"] * (n - n // 2), index=idx)
    return prices, regime


def test_default_config():
    cfg = RegimeRPConfig()
    assert cfg.min_obs_per_regime > 0


def test_returns_dataframe(synthetic_prices_with_regimes):
    prices, regime = synthetic_prices_with_regimes
    rrp = RegimeRiskParity()
    res = rrp.allocate(prices, regime, current_regime="bull")
    assert isinstance(res, RegimeRPResult)
    assert isinstance(res.weights, pd.DataFrame)
    assert list(res.weights.columns) == list(prices.columns)


def test_weights_sum_to_one(synthetic_prices_with_regimes):
    prices, regime = synthetic_prices_with_regimes
    rrp = RegimeRiskParity()
    res = rrp.allocate(prices, regime, current_regime="bear")
    s = res.weights.iloc[0].sum()
    assert pytest.approx(s, abs=1e-3) == 1.0


def test_uses_conditional_cov(synthetic_prices_with_regimes):
    prices, regime = synthetic_prices_with_regimes
    rrp = RegimeRiskParity()
    bull = rrp.allocate(prices, regime, current_regime="bull")
    bear = rrp.allocate(prices, regime, current_regime="bear")
    # The two cov matrices should differ (bear is higher vol).
    assert bull.cov_used.values.diagonal().mean() < bear.cov_used.values.diagonal().mean()


def test_fallback_when_regime_too_small(synthetic_prices_with_regimes):
    prices, regime = synthetic_prices_with_regimes
    rrp = RegimeRiskParity(RegimeRPConfig(min_obs_per_regime=10_000))
    res = rrp.allocate(prices, regime, current_regime="bull")
    assert res.fallback_to_global is True


def test_unknown_regime_triggers_fallback(synthetic_prices_with_regimes):
    prices, regime = synthetic_prices_with_regimes
    rrp = RegimeRiskParity()
    res = rrp.allocate(prices, regime, current_regime="zzzz")
    assert res.fallback_to_global is True


def test_requires_dataframe_prices():
    rrp = RegimeRiskParity()
    with pytest.raises(TypeError):
        rrp.allocate([1, 2], pd.Series(["a"]), "a")


def test_requires_series_regimes(synthetic_prices_with_regimes):
    prices, _ = synthetic_prices_with_regimes
    rrp = RegimeRiskParity()
    with pytest.raises(TypeError):
        rrp.allocate(prices, ["bull"] * len(prices), "bull")


def test_n_obs_in_regime_counted(synthetic_prices_with_regimes):
    prices, regime = synthetic_prices_with_regimes
    rrp = RegimeRiskParity()
    res = rrp.allocate(prices, regime, current_regime="bull")
    assert res.n_obs_in_regime > 0
