"""Tests for VolTargetForecaster.

Run: pytest aurora/tests/test_vol_target_forecast.py -v
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.deployment.vol_target_forecast import (
    VolTargetForecastConfig,
    VolTargetForecastResult,
    VolTargetForecaster,
)


@pytest.fixture
def varied_vol_prices():
    """Three assets with markedly different vol levels."""
    rng = np.random.default_rng(7)
    n = 300
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    a = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.005, n))
    b = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.015, n))
    c = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.025, n))
    return pd.DataFrame({"LO": a, "MD": b, "HI": c}, index=idx)


def test_default_config_valid():
    cfg = VolTargetForecastConfig()
    assert cfg.target_annual_vol > 0
    assert cfg.max_leverage > 0


def test_invalid_target_vol():
    with pytest.raises(ValueError):
        VolTargetForecaster(VolTargetForecastConfig(target_annual_vol=0))


def test_returns_dataframe(varied_vol_prices):
    vt = VolTargetForecaster()
    res = vt.allocate(varied_vol_prices)
    assert isinstance(res, VolTargetForecastResult)
    assert isinstance(res.weights, pd.DataFrame)


def test_weights_sum_to_one(varied_vol_prices):
    vt = VolTargetForecaster()
    res = vt.allocate(varied_vol_prices)
    assert pytest.approx(res.weights.iloc[0].sum(), abs=1e-6) == 1.0


def test_low_vol_gets_more_weight(varied_vol_prices):
    """Low-vol asset should get a larger relative weight than high-vol asset."""
    vt = VolTargetForecaster()
    res = vt.allocate(varied_vol_prices)
    row = res.weights.iloc[0]
    assert row["LO"] > row["HI"]


def test_forecast_vol_present(varied_vol_prices):
    vt = VolTargetForecaster()
    res = vt.allocate(varied_vol_prices)
    assert isinstance(res.forecast_vol, pd.Series)
    assert (res.forecast_vol > 0).all()


def test_max_leverage_caps_weight():
    """Very low realized vol -> raw_leverage should be capped at max_leverage."""
    rng = np.random.default_rng(1)
    n = 200
    idx = pd.date_range("2021-01-01", periods=n, freq="B")
    near_zero = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 1e-5, n))
    df = pd.DataFrame({"FLAT": near_zero, "OK": near_zero * 1.0001}, index=idx)
    cfg = VolTargetForecastConfig(target_annual_vol=0.10, max_leverage=2.0)
    vt = VolTargetForecaster(cfg)
    res = vt.allocate(df)
    assert res.raw_leverage.max() <= cfg.max_leverage + 1e-9


def test_requires_dataframe():
    vt = VolTargetForecaster()
    with pytest.raises(TypeError):
        vt.allocate([1, 2, 3])


def test_used_garch_flag_is_bool(varied_vol_prices):
    vt = VolTargetForecaster()
    res = vt.allocate(varied_vol_prices)
    assert isinstance(res.used_garch, bool)
