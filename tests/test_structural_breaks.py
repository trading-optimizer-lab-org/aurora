"""Tests for structural break detection (Chow, CUSUM, SADF)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.core.seed import set_global_seed
from aurora.validation.structural_breaks import (
    chow_test,
    cusum_filter,
    sadf_test,
    ChowResult,
    CUSUMResult,
    SADFResult,
)


# ---------------------------------------------------------------------------
# Chow
# ---------------------------------------------------------------------------

def test_chow_no_break() -> None:
    set_global_seed(7)
    rng = np.random.default_rng(7)
    n = 500
    idx = pd.date_range("2015-01-01", periods=n, freq="B")
    rets = pd.Series(rng.normal(0.0, 0.01, n), index=idx)
    res = chow_test(rets, breakpoint=n // 2)
    assert isinstance(res, ChowResult)
    assert res.p_value > 0.05
    assert not res.has_break


def test_chow_known_break() -> None:
    set_global_seed(11)
    rng = np.random.default_rng(11)
    n = 600
    bp = n // 2
    idx = pd.date_range("2015-01-01", periods=n, freq="B")
    pre = rng.normal(0.0, 0.01, bp)
    post = rng.normal(0.01, 0.01, n - bp)  # mean shift
    rets = pd.Series(np.concatenate([pre, post]), index=idx)
    res = chow_test(rets, breakpoint=bp)
    assert res.p_value < 0.05
    assert res.has_break
    assert res.f_stat > 0.0


# ---------------------------------------------------------------------------
# CUSUM
# ---------------------------------------------------------------------------

def test_cusum_no_break() -> None:
    set_global_seed(13)
    rng = np.random.default_rng(13)
    n = 400
    idx = pd.date_range("2015-01-01", periods=n, freq="B")
    rets = pd.Series(rng.normal(0.0, 0.001, n), index=idx)
    # Tiny vol, threshold high enough to never trigger.
    res = cusum_filter(rets, threshold=1.0)
    assert isinstance(res, CUSUMResult)
    assert len(res.break_dates) == 0
    assert not res.has_break
    assert len(res.test_stats) == n


def test_cusum_known_break() -> None:
    set_global_seed(17)
    rng = np.random.default_rng(17)
    n = 400
    idx = pd.date_range("2015-01-01", periods=n, freq="B")
    pre = rng.normal(0.0, 0.001, n // 2)
    post = rng.normal(0.02, 0.001, n - n // 2)  # large mean jump
    rets = pd.Series(np.concatenate([pre, post]), index=idx)
    res = cusum_filter(rets, threshold=0.05)
    assert res.has_break
    assert len(res.break_dates) > 0
    # First detected break should fall in the post-shift region.
    assert res.break_dates[0] >= idx[n // 2]


# ---------------------------------------------------------------------------
# SADF
# ---------------------------------------------------------------------------

def test_sadf_no_bubble() -> None:
    pytest.importorskip("statsmodels")
    set_global_seed(19)
    rng = np.random.default_rng(19)
    n = 200
    idx = pd.date_range("2015-01-01", periods=n, freq="B")
    log_p = pd.Series(rng.normal(0.0, 0.01, n).cumsum(), index=idx)
    res = sadf_test(log_p, lags=2, min_window=40, model="constant")
    assert isinstance(res, SADFResult)
    valid = res.sadf_series.dropna()
    assert len(valid) > 0
    # Random walk SADF should rarely cross the constant-model 95% crit.
    assert valid.max() < res.critical_value + 1.0
    # Stationary noise typically won't trigger a break.
    assert res.break_date is None or valid.max() <= res.critical_value + 0.5


def test_sadf_explosive() -> None:
    pytest.importorskip("statsmodels")
    set_global_seed(23)
    rng = np.random.default_rng(23)
    n = 200
    idx = pd.date_range("2015-01-01", periods=n, freq="B")
    # Explosive (rho > 1) AR(1) on log price.
    log_p = np.zeros(n)
    rho = 1.02
    for t in range(1, n):
        log_p[t] = rho * log_p[t - 1] + rng.normal(0.0, 0.01)
    series = pd.Series(log_p, index=idx)
    res = sadf_test(series, lags=2, min_window=40, model="constant")
    valid = res.sadf_series.dropna()
    assert valid.max() > res.critical_value
    assert res.break_date is not None
    assert res.has_break


def test_sadf_warmup_nan() -> None:
    pytest.importorskip("statsmodels")
    set_global_seed(29)
    rng = np.random.default_rng(29)
    n = 150
    min_window = 40
    idx = pd.date_range("2015-01-01", periods=n, freq="B")
    log_p = pd.Series(rng.normal(0.0, 0.01, n).cumsum(), index=idx)
    res = sadf_test(log_p, lags=2, min_window=min_window, model="constant")
    # First min_window bars must be NaN.
    assert res.sadf_series.iloc[: min_window - 1].isna().all()
