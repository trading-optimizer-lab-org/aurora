"""Tests for quantforge.validation.retraining."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.core.seed import set_global_seed
from quantforge.core.costs import ZERO_costs
from quantforge.strategies.library import MACross
from quantforge.validation.retraining import (
    RetrainResult,
    simulate_retraining,
)


def _synthetic_prices(n: int, seed: int = 42, start: str = "2010-01-01") -> pd.Series:
    set_global_seed(seed)
    idx = pd.date_range(start, periods=n, freq="B")
    rets = np.random.default_rng(seed).normal(0.0005, 0.012, n)
    p = 100 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


def _fixed_macross_optimizer(train_prices: pd.Series) -> MACross:
    """Dummy optimizer: always returns MACross(10, 50). Ignores train data."""
    return MACross(fast=10, slow=50)


def test_basic():
    """Smoke: result populated for synthetic data + fixed optimizer."""
    prices = _synthetic_prices(800)
    res = simulate_retraining(
        _fixed_macross_optimizer,
        prices,
        costs=ZERO_costs,
        train_window_days=200,
        retrain_cadence_days=50,
        ppy=252,
        allow_overlap=True,
    )
    assert isinstance(res, RetrainResult)
    assert res.cadence_days == 50
    assert res.n_retrains > 0
    assert len(res.fold_metrics) == res.n_retrains
    # each fold tuple has 5 fields
    for row in res.fold_metrics:
        assert len(row) == 5
        start_d, end_d, calmar, sharpe, mdd = row
        assert isinstance(start_d, str)
        assert isinstance(end_d, str)
    # aggregates are finite numbers
    assert np.isfinite(res.avg_calmar)
    assert np.isfinite(res.median_calmar)
    assert np.isfinite(res.overall_calmar)
    assert np.isfinite(res.overall_sharpe)
    assert np.isfinite(res.overall_mdd)


def test_fold_count():
    """train=200, cadence=50, n=600 -> expect 8 folds.

    start_idx = 200; while start_idx + 50 <= 600: ... start_idx += 50
    -> start_idx visits 200, 250, 300, 350, 400, 450, 500, 550 (8 folds).
    """
    prices = _synthetic_prices(600)
    res = simulate_retraining(
        _fixed_macross_optimizer,
        prices,
        train_window_days=200,
        retrain_cadence_days=50,
        allow_overlap=True,
    )
    assert res.n_retrains == 8


def test_concatenated_metrics():
    """Concatenated OOS MDD must be at least as large (in absolute value) as
    the worst per-fold MDD. Cross-fold drawdowns can only deepen MDD."""
    prices = _synthetic_prices(1500, seed=7)
    res = simulate_retraining(
        _fixed_macross_optimizer,
        prices,
        train_window_days=300,
        retrain_cadence_days=80,
        allow_overlap=True,
    )
    assert res.n_retrains >= 3
    fold_mdds = [row[4] for row in res.fold_metrics]
    worst_fold_mdd_abs = max(abs(m) for m in fold_mdds)
    assert abs(res.overall_mdd) + 1e-9 >= worst_fold_mdd_abs


def test_decay_slope():
    """A constant-params optimizer fed stationary noise should show near-zero
    Calmar decay slope. Tolerance kept loose to absorb sample variability."""
    prices = _synthetic_prices(2000, seed=11)
    res = simulate_retraining(
        _fixed_macross_optimizer,
        prices,
        train_window_days=400,
        retrain_cadence_days=100,
        allow_overlap=True,
    )
    assert res.n_retrains >= 8
    # Slope is Calmar units per year. With stationary returns and fixed params,
    # |slope| should be small relative to typical Calmar magnitudes.
    assert abs(res.calmar_decay_per_year) < 5.0


def test_short_history_raises():
    """prices shorter than train_window + cadence -> ValueError."""
    prices = _synthetic_prices(100)
    with pytest.raises(ValueError):
        simulate_retraining(
            _fixed_macross_optimizer,
            prices,
            train_window_days=200,  # > 100
            retrain_cadence_days=50,
        )


def test_optimizer_receives_train_window():
    """Verify the optimizer is fed exactly train_window_days of bars."""
    prices = _synthetic_prices(700)
    captured: list[int] = []

    def capturing_optimizer(train_prices: pd.Series) -> MACross:
        captured.append(len(train_prices))
        return MACross(fast=10, slow=50)

    simulate_retraining(
        capturing_optimizer,
        prices,
        train_window_days=250,
        retrain_cadence_days=60,
        allow_overlap=True,
    )
    assert captured  # at least one call
    assert all(n == 250 for n in captured)


# --------------------------------------------------------------------------- #
# Overlap guard                                                               #
# --------------------------------------------------------------------------- #
def test_retraining_rejects_overlap_default():
    """Default allow_overlap=False: cadence < window raises ValueError."""
    prices = _synthetic_prices(800)
    with pytest.raises(ValueError, match="overlap"):
        simulate_retraining(
            _fixed_macross_optimizer,
            prices,
            train_window_days=300,
            retrain_cadence_days=50,  # < 300 -> overlap
        )


def test_retraining_allows_overlap_with_flag():
    """allow_overlap=True keeps the legacy behavior and emits a DeprecationWarning."""
    import warnings as _w
    prices = _synthetic_prices(800)
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        res = simulate_retraining(
            _fixed_macross_optimizer,
            prices,
            train_window_days=300,
            retrain_cadence_days=50,
            allow_overlap=True,
        )
    # at least one DeprecationWarning mentioning overlap
    assert any(
        issubclass(w.category, DeprecationWarning) and "overlap" in str(w.message)
        for w in caught
    )
    assert isinstance(res, RetrainResult)
    assert res.n_retrains > 0


def test_retraining_no_overlap_when_cadence_geq_window():
    """cadence >= window: no exception, no DeprecationWarning."""
    import warnings as _w
    prices = _synthetic_prices(2000, seed=3)
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        res = simulate_retraining(
            _fixed_macross_optimizer,
            prices,
            train_window_days=200,
            retrain_cadence_days=200,
            allow_overlap=False,
        )
    overlap_warnings = [
        w for w in caught
        if issubclass(w.category, DeprecationWarning) and "overlap" in str(w.message)
    ]
    assert overlap_warnings == []
    assert res.n_retrains > 0
