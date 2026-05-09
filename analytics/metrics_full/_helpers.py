"""Internal helpers shared by the metrics_full submodules.

Not part of the public API. Tests should not import from this module
directly; use the public symbols re-exported from
``aurora.analytics.metrics_full``.
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd


def _to_series(returns) -> pd.Series:
    """Coerce to pd.Series; preserve DatetimeIndex if present, else use RangeIndex."""
    if isinstance(returns, pd.Series):
        s = returns.dropna().astype(float)
    else:
        arr = np.asarray(returns, dtype=float)
        arr = arr[~np.isnan(arr)]
        s = pd.Series(arr)
    return s


def _to_array(returns) -> np.ndarray:
    if isinstance(returns, pd.Series):
        return returns.dropna().to_numpy(dtype=float)
    arr = np.asarray(returns, dtype=float)
    return arr[~np.isnan(arr)]


def _equity_curve(returns) -> np.ndarray:
    r = _to_array(returns)
    return np.cumprod(1.0 + r) if len(r) else np.array([1.0])


def _drawdown_series(returns) -> np.ndarray:
    eq = _equity_curve(returns)
    if len(eq) == 0:
        return np.array([0.0])
    cummax = np.maximum.accumulate(eq)
    return (eq - cummax) / cummax


def _autocorr_penalty(r: np.ndarray) -> float:
    """quantstats-style penalty: sqrt(1 + 2 * sum_{i=1..N} ((N - i)/N) * |corr_i|)."""
    n = len(r)
    coef = 0.0
    for i in range(1, min(n, 21)):  # cap at lag 20 for stability
        c = np.corrcoef(r[:-i], r[i:])[0, 1]
        if not math.isfinite(c):
            continue
        coef += ((n - i) / n) * abs(c)
    return math.sqrt(1.0 + 2.0 * coef)


def _resample_returns(returns, freq: str) -> pd.Series:
    """Resample returns to given frequency by compounding.

    When the input does not carry a DatetimeIndex, a synthetic daily index
    is fabricated so that bar-count aggregations (``positive_months``,
    ``negative_months``) still work. Calendar-labelled outputs
    (``monthly_returns`` pivot, ``yearly_returns``, ``best_month``,
    ``worst_month``, ``best_year``, ``worst_year``) must NOT trust the
    fabricated labels and should bail out instead -- see ``_has_real_dt``.
    """
    s = _to_series(returns)
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.date_range("2000-01-01", periods=len(s), freq="D")
    return (1.0 + s).resample(freq).prod() - 1.0


def _has_real_dt(returns) -> bool:
    """True only when caller supplied a real DatetimeIndex. Calendar-
    labelled outputs are meaningless without one."""
    s = _to_series(returns) if not isinstance(returns, pd.Series) else returns
    return isinstance(s.index, pd.DatetimeIndex)
