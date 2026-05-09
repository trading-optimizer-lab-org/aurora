"""Tests for PairDiscoveryEngine."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.strategies.library import (
    PairDiscoveryEngine, PairDiscoveryConfig, PairResult,
)


@pytest.fixture
def cointegrated_universe():
    """3 cointegrated assets sharing a factor + 2 random walks."""
    rng = np.random.default_rng(7)
    n = 400
    idx = pd.date_range("2010-01-01", periods=n, freq="B")
    factor = np.cumsum(rng.normal(0.0, 0.01, n))
    noise = lambda: rng.normal(0.0, 0.005, n).cumsum()
    coint_a = 100 + factor + noise() * 0.1
    coint_b = 100 + 1.0 * factor + noise() * 0.1
    coint_c = 100 + 0.8 * factor + noise() * 0.1
    rw_d = 100 + np.cumsum(rng.normal(0.0, 0.02, n))
    rw_e = 100 + np.cumsum(rng.normal(0.0, 0.02, n))
    return {
        "AAA": pd.Series(coint_a, index=idx),
        "BBB": pd.Series(coint_b, index=idx),
        "CCC": pd.Series(coint_c, index=idx),
        "DDD": pd.Series(rw_d, index=idx),
        "EEE": pd.Series(rw_e, index=idx),
    }


def test_engine_returns_pair_results(cointegrated_universe):
    eng = PairDiscoveryEngine(PairDiscoveryConfig(
        p_value_threshold=0.5, min_overlap=200, max_half_life=400, min_half_life=0.1,
    ))
    res = eng.discover(cointegrated_universe)
    assert isinstance(res, list)
    for r in res:
        assert isinstance(r, PairResult)
        assert r.sym_a < r.sym_b


def test_engine_ranks_by_pvalue(cointegrated_universe):
    eng = PairDiscoveryEngine(PairDiscoveryConfig(
        p_value_threshold=1.0, min_overlap=100, max_half_life=10000, min_half_life=0.0,
    ))
    res = eng.discover(cointegrated_universe)
    if len(res) >= 2:
        assert res[0].p_value <= res[1].p_value


def test_engine_filters_p_value(cointegrated_universe):
    eng = PairDiscoveryEngine(PairDiscoveryConfig(
        p_value_threshold=0.0001, min_overlap=200, max_half_life=10000, min_half_life=0.0,
    ))
    res = eng.discover(cointegrated_universe)
    for r in res:
        assert r.p_value <= 0.0001


def test_engine_handles_too_few_assets():
    eng = PairDiscoveryEngine()
    assert eng.discover({}) == []
    s = pd.Series([1.0, 2.0, 3.0], index=pd.date_range("2020-01-01", periods=3))
    assert eng.discover({"AAA": s}) == []


def test_engine_skips_when_overlap_too_short():
    eng = PairDiscoveryEngine(PairDiscoveryConfig(min_overlap=300))
    idx = pd.date_range("2020-01-01", periods=50, freq="B")
    pa = pd.Series(np.arange(50, dtype=float), index=idx)
    pb = pd.Series(np.arange(50, dtype=float) * 0.5, index=idx)
    res = eng.discover({"A": pa, "B": pb})
    assert res == []


def test_half_life_sane(cointegrated_universe):
    eng = PairDiscoveryEngine(PairDiscoveryConfig(
        p_value_threshold=1.0, min_overlap=100, max_half_life=10000, min_half_life=0.0,
    ))
    res = eng.discover(cointegrated_universe)
    for r in res:
        assert np.isfinite(r.half_life)
        assert r.half_life > 0


def test_fallback_path_no_statsmodels(cointegrated_universe):
    eng = PairDiscoveryEngine(PairDiscoveryConfig(
        p_value_threshold=1.0, min_overlap=100, max_half_life=10000,
        min_half_life=0.0, use_statsmodels=False,
    ))
    res = eng.discover(cointegrated_universe)
    for r in res:
        assert 0.0 <= r.p_value <= 1.0
