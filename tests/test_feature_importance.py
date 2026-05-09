"""Tests for quantforge.ml.feature_importance (AFML Ch.8)."""
from __future__ import annotations
import os

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sklearn")
from sklearn.ensemble import RandomForestRegressor
from sklearn.tree import DecisionTreeRegressor

from aurora.core.seed import set_global_seed
from aurora.ml.feature_importance import (
    mean_decrease_impurity,
    mean_decrease_accuracy,
    single_feature_importance,
    plot_importance,
)


def _synthetic_data(n: int = 400, n_features: int = 5, seed: int = 7):
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n, n_features))
    # feature 0 strongly drives target, others noise
    y = 3.0 * X[:, 0] + 0.1 * rng.standard_normal(n)
    cols = [f"f{i}" for i in range(n_features)]
    Xdf = pd.DataFrame(X, columns=cols)
    yser = pd.Series(y, name="y")
    return Xdf, yser


def _fit_rf(X, y, seed=7):
    rf = RandomForestRegressor(n_estimators=20, random_state=seed, n_jobs=1)
    rf.fit(X, y)
    return rf


def test_mdi_basic():
    set_global_seed(42)
    X, y = _synthetic_data()
    rf = _fit_rf(X, y)
    df = mean_decrease_impurity(rf, list(X.columns))

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["mean", "std"]
    assert len(df) == X.shape[1]
    # Sorted descending by mean
    means = df["mean"].to_numpy()
    assert np.all(np.diff(means) <= 1e-12)


def test_mdi_strong_feature():
    set_global_seed(42)
    X, y = _synthetic_data()
    rf = _fit_rf(X, y)
    df = mean_decrease_impurity(rf, list(X.columns))
    # f0 should rank first
    assert df.index[0] == "f0"


def test_mda_perm_drop():
    set_global_seed(42)
    X, y = _synthetic_data()
    rf = RandomForestRegressor(n_estimators=15, random_state=7, n_jobs=1)
    df = mean_decrease_accuracy(
        rf, X, y, cv=3, n_repeats=2, scoring="neg_mean_squared_error"
    )
    assert list(df.columns) == ["mean", "std"]
    # f0 is the strong feature: permuting it should produce the largest drop
    assert df.index[0] == "f0"
    assert df.loc["f0", "mean"] > 0.0


def test_mda_unused_feature():
    set_global_seed(42)
    rng = np.random.default_rng(11)
    n = 300
    X = pd.DataFrame(
        {
            "signal": rng.standard_normal(n),
            "noise": rng.standard_normal(n),
        }
    )
    y = pd.Series(2.5 * X["signal"].to_numpy() + 0.05 * rng.standard_normal(n))
    rf = RandomForestRegressor(n_estimators=15, random_state=7, n_jobs=1)

    df = mean_decrease_accuracy(rf, X, y, cv=3, n_repeats=2)
    # Noise feature importance should be small in magnitude relative to signal
    assert abs(df.loc["noise", "mean"]) < df.loc["signal", "mean"]
    # And much closer to zero
    assert abs(df.loc["noise", "mean"]) < 0.5 * df.loc["signal", "mean"]


def test_sfi_strong_feature():
    set_global_seed(42)
    X, y = _synthetic_data()

    def factory():
        return DecisionTreeRegressor(max_depth=4, random_state=7)

    df = single_feature_importance(
        X, y, factory, cv=3, scoring="neg_mean_squared_error"
    )
    assert list(df.columns) == ["mean", "std"]
    assert len(df) == X.shape[1]
    # Higher (less-negative) score means stronger feature
    assert df.index[0] == "f0"


def test_mda_raises_when_cv_class_cannot_accept_n_splits():
    """Audit fix: when cv_class is a class without an n_splits-compatible
    signature (and no shuffled-KFold signature), the user-provided ``cv`` int
    cannot propagate. The function must raise TypeError instead of silently
    using a different number of folds.
    """
    set_global_seed(42)
    X, y = _synthetic_data(n=200)
    rf = RandomForestRegressor(n_estimators=10, random_state=7, n_jobs=1)

    # A class whose constructor accepts no kwargs and no n_splits.
    class _BadSplitter:
        def __init__(self):
            self._n_splits = 3

        def split(self, X, y=None, groups=None):
            n = len(X)
            third = n // 3
            yield np.arange(third, n), np.arange(0, third)
            yield np.r_[0:third, 2 * third:n], np.arange(third, 2 * third)
            yield np.arange(0, 2 * third), np.arange(2 * third, n)

        def get_n_splits(self, X=None, y=None, groups=None):
            return self._n_splits

    with pytest.raises(TypeError, match="n_splits"):
        mean_decrease_accuracy(
            rf, X, y, cv=5, n_repeats=1, cv_class=_BadSplitter,
        )


def test_mda_perm_in_place_does_not_corrupt_X():
    """Audit fix: in-place column permutation must always restore the
    original column at the end of each repeat-feature pair, even on
    scorer exceptions. We pin this by checking that the input frame is
    bitwise-identical after the call.
    """
    set_global_seed(42)
    X, y = _synthetic_data(n=200)
    X_before = X.copy()
    rf = RandomForestRegressor(n_estimators=10, random_state=7, n_jobs=1)
    _ = mean_decrease_accuracy(rf, X, y, cv=3, n_repeats=2)
    # Caller's frame is untouched (we only mutate an internal working copy).
    pd.testing.assert_frame_equal(X, X_before)


def test_plot_creates_file(tmp_path):
    set_global_seed(42)
    df = pd.DataFrame(
        {"mean": [0.5, 0.3, 0.1], "std": [0.05, 0.04, 0.02]},
        index=["f0", "f1", "f2"],
    )
    out = tmp_path / "importance.png"
    result = plot_importance(df, title="Test", output_path=str(out))
    assert result == str(out)
    assert out.exists()
    assert out.stat().st_size > 0
