"""Tests for quantforge.research.hf_benchmark."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.research.hf_benchmark import (
    FACTOR_NAMES,
    HedgeFundBenchmark,
    StyleAttributionReport,
    synthetic_factor_returns,
)


def test_synthetic_factor_returns_shape():
    df = synthetic_factor_returns(n=100)
    assert isinstance(df, pd.DataFrame)
    assert df.shape == (100, len(FACTOR_NAMES))
    for c in FACTOR_NAMES:
        assert c in df.columns


def test_attribute_basic():
    df = synthetic_factor_returns(n=300)
    rng = np.random.default_rng(0)
    rets = pd.Series(rng.normal(0.0005, 0.01, 300), index=df.index)
    bench = HedgeFundBenchmark(df)
    rep = bench.attribute(rets)
    assert isinstance(rep, StyleAttributionReport)
    assert set(rep.betas.keys()) == set(FACTOR_NAMES)
    assert isinstance(rep.alpha, float)
    assert -2.0 <= rep.r_squared <= 1.0


def test_attribute_recovers_synthetic_alpha():
    """If the strategy returns are intercept + 2*Mkt-RF, beta on Mkt-RF should be near 2."""
    df = synthetic_factor_returns(n=400)
    y = 0.0001 + 2.0 * df["Mkt-RF"] + 0.0
    bench = HedgeFundBenchmark(df)
    rep = bench.attribute(pd.Series(y, index=df.index))
    assert abs(rep.betas["Mkt-RF"] - 2.0) < 0.1
    assert abs(rep.alpha - 0.0001) < 0.01


def test_attribute_requires_series():
    bench = HedgeFundBenchmark()
    with pytest.raises(TypeError):
        bench.attribute(np.zeros(100))


def test_attribute_empty_series():
    bench = HedgeFundBenchmark()
    rets = pd.Series([np.nan, np.nan], index=pd.date_range("2020-01-01", periods=2, freq="B"))
    with pytest.raises(ValueError):
        bench.attribute(rets)


def test_attribute_too_few_obs():
    df = synthetic_factor_returns(n=300)
    rets = pd.Series(np.zeros(2), index=df.index[:2])
    bench = HedgeFundBenchmark(df)
    with pytest.raises(ValueError):
        bench.attribute(rets)


def test_compare_includes_keys():
    df = synthetic_factor_returns(n=200)
    rng = np.random.default_rng(0)
    rets = pd.Series(rng.normal(0.001, 0.01, 200), index=df.index)
    bench = HedgeFundBenchmark(df)
    out = bench.compare(rets)
    assert "strategy_sharpe_ann" in out
    for f in FACTOR_NAMES:
        assert f"{f}_sharpe_ann" in out


def test_factors_must_be_dataframe():
    with pytest.raises(TypeError):
        HedgeFundBenchmark(np.zeros((10, 8)))


def test_empty_factors_raises():
    with pytest.raises(ValueError):
        HedgeFundBenchmark(pd.DataFrame())
