"""Tests for quantforge.ml.automl_features."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.ml.automl_features import (
    AutoMLConfig,
    AutoMLFeatureEngineer,
    SKLEARN_AVAILABLE,
)


@pytest.fixture
def prices():
    rng = np.random.default_rng(42)
    n = 300
    rets = rng.normal(0.0005, 0.012, n)
    p = 100.0 * np.cumprod(1.0 + rets)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.Series(p, index=idx, name="close")


@pytest.fixture
def target(prices):
    # next-bar return
    return np.log(prices).diff().shift(-1).rename("y")


def test_generate_returns_dataframe_with_many_features(prices):
    eng = AutoMLFeatureEngineer()
    feats = eng.generate(prices)
    assert isinstance(feats, pd.DataFrame)
    # default config easily produces 100+ candidates
    assert feats.shape[1] >= 50
    assert len(feats) == len(prices)


def test_generate_anti_lookahead(prices):
    """Every column must depend only on data <= bar t."""
    eng = AutoMLFeatureEngineer(AutoMLConfig(rolling_windows=(5,), lag_steps=(1,), pairwise_interactions=False))
    feats = eng.generate(prices)
    # Modify the last bar of prices and recompute. Earlier feature rows
    # must not change.
    prices_mut = prices.copy()
    prices_mut.iloc[-1] = prices_mut.iloc[-1] * 2.0
    feats_mut = eng.generate(prices_mut)
    # All rows except the last are unchanged.
    pd.testing.assert_frame_equal(feats.iloc[:-1], feats_mut.iloc[:-1])


def test_generate_validates_input():
    eng = AutoMLFeatureEngineer()
    with pytest.raises(TypeError):
        eng.generate([1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        eng.generate(pd.Series([1.0, 2.0]))


def test_rank_corr_method_returns_sorted_series(prices, target):
    eng = AutoMLFeatureEngineer(AutoMLConfig(rolling_windows=(5,), lag_steps=(1,), pairwise_interactions=False))
    feats = eng.generate(prices)
    scores = eng.rank(feats, target, method="corr")
    assert isinstance(scores, pd.Series)
    assert len(scores) > 0
    # Sorted descending
    arr = scores.dropna().to_numpy()
    assert np.all(arr[:-1] >= arr[1:])


def test_rank_mi_method(prices, target):
    if not SKLEARN_AVAILABLE:
        pytest.skip("scikit-learn not installed")
    eng = AutoMLFeatureEngineer(AutoMLConfig(rolling_windows=(5, 10), lag_steps=(1,), pairwise_interactions=False))
    feats = eng.generate(prices)
    scores = eng.rank(feats, target, method="mi")
    assert isinstance(scores, pd.Series)
    assert len(scores) == feats.shape[1]
    assert (scores >= 0).all()


def test_select_returns_top_k(prices, target):
    eng = AutoMLFeatureEngineer()
    top = eng.select(prices, target, k=10, method="corr")
    assert isinstance(top, pd.DataFrame)
    assert top.shape[1] == 10
    assert len(top) == len(prices)


def test_rank_unknown_method_raises(prices, target):
    eng = AutoMLFeatureEngineer()
    feats = eng.generate(prices)
    with pytest.raises(ValueError):
        eng.rank(feats, target, method="bogus")
