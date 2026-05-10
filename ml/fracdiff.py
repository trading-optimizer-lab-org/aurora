"""Fractional differentiation (fixed-window FFD).

Lopez de Prado, AFML Ch.5 — produce stationary series while preserving memory.
Reference: mlfinlab/features/fracdiff.py
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd

_ADF_IMPORT_ERROR: ImportError | None = None
try:
    from statsmodels.tsa.stattools import adfuller as _adfuller
except ImportError as _e:  # pragma: no cover
    _adfuller = None
    _ADF_IMPORT_ERROR = _e


def _require_statsmodels() -> None:
    if _adfuller is None:
        raise ImportError(
            "fracdiff: statsmodels is required for ADF tests. "
            "Install with: uv add statsmodels  (or: pip install statsmodels)"
        ) from _ADF_IMPORT_ERROR


def get_weights_ffd(d: float, threshold: float = 1e-5) -> np.ndarray:
    """Fixed-window fractional differentiation weights.

    Standard recursion: w_k = -w_{k-1} * (d - k + 1) / k, w_0 = 1.
    Truncate at the first index where |w_k| < threshold.
    Returns weights ordered with the newest weight (w_0 = 1) first,
    so a dot product with the most-recent K observations applies the
    correct lag alignment when the array is reversed.

    The returned array w has w[0] = 1.0 (current bar weight).
    """
    if threshold <= 0:
        raise ValueError("threshold must be > 0")
    w = [1.0]
    k = 1
    # Hard cap to avoid pathological infinite loops for tiny d.
    max_k = 10000
    while k < max_k:
        w_k = -w[-1] * (d - k + 1) / k
        if abs(w_k) < threshold:
            break
        w.append(w_k)
        k += 1
    return np.asarray(w, dtype=float)


def frac_diff_ffd(
    series: pd.Series,
    d: float,
    threshold: float = 1e-5,
) -> pd.Series:
    """Apply fixed-window fractional differentiation.

    Args:
        series: input series (typically log prices).
        d: differentiation order in [0, 1] (0 = raw, 1 = integer diff).
        threshold: weight cutoff for window length.

    Returns:
        Differentiated series with the same index as ``series``.
        The first ``len(weights) - 1`` bars are NaN (warm-up).
    """
    if not isinstance(series, pd.Series):
        raise TypeError("series must be a pandas Series")
    w = get_weights_ffd(d, threshold=threshold)
    width = len(w) - 1  # number of NaN warm-up bars
    out = np.full(len(series), np.nan, dtype=float)
    values = series.to_numpy(dtype=float)
    if width >= len(series):
        return pd.Series(out, index=series.index, name=series.name)
    # w[0] is the weight on the *current* bar; w[k] applies to lag k.
    # So the convolution at time t is sum_{k=0..width} w[k] * x[t-k].
    # For numpy dot with the most recent window x[t-width:t+1],
    # we need weights reversed: w_rev[i] = w[width - i].
    w_rev = w[::-1]
    for t in range(width, len(values)):
        window = values[t - width : t + 1]
        if np.isnan(window).any():
            continue
        out[t] = float(np.dot(w_rev, window))
    return pd.Series(out, index=series.index, name=series.name)


def find_min_d(
    series: pd.Series,
    max_d: float = 1.0,
    step: float = 0.05,
    threshold: float = 1e-5,
    adf_pvalue: float = 0.05,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Find minimum d such that frac_diff_ffd(series, d) is stationary.

    Linear sweep d = 0, step, 2*step, ..., max_d. Stop at the first d whose
    ADF p-value is <= ``adf_pvalue``.

    Returns:
        (min_d, adf_stat, p_value) on success.
        (None, None, None) if no d in the sweep produces a stationary series.
    """
    _require_statsmodels()
    if step <= 0:
        raise ValueError("step must be > 0")
    if max_d <= 0:
        raise ValueError("max_d must be > 0")

    # ``n_steps`` already includes the +1 for the inclusive endpoint, so
    # iterating ``range(n_steps + 1)`` produced one duplicate sweep at d=max_d.
    n_steps = int(np.floor(max_d / step)) + 1
    for i in range(n_steps):
        d = min(i * step, max_d)
        diffed = frac_diff_ffd(series, d=d, threshold=threshold).dropna()
        if len(diffed) < 20:
            if d >= max_d:
                break
            continue
        try:
            adf_res = _adfuller(diffed.values, maxlag=1, regression="c", autolag=None)
        except Exception:
            if d >= max_d:
                break
            continue
        adf_stat = float(adf_res[0])
        p_value = float(adf_res[1])
        if p_value <= adf_pvalue:
            return float(d), adf_stat, p_value
        if d >= max_d:
            break
    return None, None, None


def fracdiff_correlation(
    series: pd.Series,
    max_d: float = 1.0,
    step: float = 0.1,
    threshold: float = 1e-5,
) -> pd.DataFrame:
    """Sweep d and compute ADF stat plus correlation with the original series.

    Used to pick a d that retains memory (high correlation) while becoming
    stationary (ADF p-value below the chosen threshold).

    Returns:
        DataFrame with columns: ``d, adf_stat, adf_pvalue, corr_with_original``.
    """
    _require_statsmodels()
    if step <= 0:
        raise ValueError("step must be > 0")
    if max_d <= 0:
        raise ValueError("max_d must be > 0")

    rows = []
    # ``n_steps`` already includes the +1 for the inclusive endpoint, so
    # iterating ``range(n_steps + 1)`` produced one duplicate sweep at d=max_d.
    n_steps = int(np.floor(max_d / step)) + 1
    for i in range(n_steps):
        d = min(i * step, max_d)
        diffed = frac_diff_ffd(series, d=d, threshold=threshold)
        valid = diffed.dropna()
        if len(valid) < 20:
            rows.append(
                {
                    "d": float(d),
                    "adf_stat": np.nan,
                    "adf_pvalue": np.nan,
                    "corr_with_original": np.nan,
                }
            )
            if d >= max_d:
                break
            continue
        try:
            adf_res = _adfuller(valid.values, maxlag=1, regression="c", autolag=None)
            adf_stat = float(adf_res[0])
            adf_pvalue = float(adf_res[1])
        except Exception:
            adf_stat = np.nan
            adf_pvalue = np.nan
        aligned_orig = series.reindex(valid.index)
        if aligned_orig.std() == 0 or valid.std() == 0:
            corr = np.nan
        else:
            corr = float(aligned_orig.corr(valid))
        rows.append(
            {
                "d": float(d),
                "adf_stat": adf_stat,
                "adf_pvalue": adf_pvalue,
                "corr_with_original": corr,
            }
        )
        if d >= max_d:
            break
    return pd.DataFrame(rows, columns=["d", "adf_stat", "adf_pvalue", "corr_with_original"])


__all__ = [
    "get_weights_ffd",
    "frac_diff_ffd",
    "find_min_d",
    "fracdiff_correlation",
]
