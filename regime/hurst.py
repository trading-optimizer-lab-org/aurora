"""Hurst exponent and Detrended Fluctuation Analysis (DFA).

References
----------
- Hurst, H. E. (1951). Long-term storage capacity of reservoirs.
  Transactions of the American Society of Civil Engineers, 116, 770-808.
- Peng, C.-K., et al. (1994). Mosaic organization of DNA nucleotides.
  Physical Review E, 49(2), 1685-1689.

Interpretation
--------------
- H = 0.5  -> random walk (no long-range memory)
- H > 0.5  -> persistent / trending
- H < 0.5  -> anti-persistent / mean-reverting

Methods
-------
- R/S: Rescaled Range. Partition series into chunks of size n, compute
  R = max(cumsum(x - mean)) - min(cumsum(x - mean)) and S = std(x), average
  R/S across chunks. Hurst = slope of log(R/S) vs log(n).
- DFA: Cumulate the (mean-removed) series, partition into windows, fit a
  polynomial trend per window, compute the RMS fluctuation around that trend,
  and regress log(F(n)) vs log(n). The slope is the Hurst (alpha) exponent.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


__all__ = [
    "HurstResult",
    "hurst_rs",
    "hurst_dfa",
    "rolling_hurst",
    "hurst_regime_filter",
]


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class HurstResult:
    """Container for Hurst exponent estimation diagnostics."""

    hurst: float
    method: str  # 'rs' | 'dfa' | 'variance'
    interpretation: str  # 'trending' | 'random_walk' | 'mean_reverting' | 'unknown'
    log_lags: np.ndarray
    log_rs: np.ndarray
    fit_slope: float
    fit_intercept: float
    r_squared: float


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _coerce_series(series) -> np.ndarray:
    """Coerce input to 1D float array, drop NaN."""
    s = pd.Series(series).astype(float).dropna()
    return s.to_numpy()


def _classify(h: float, trend_threshold: float = 0.55,
              mr_threshold: float = 0.45) -> str:
    if h > trend_threshold:
        return "trending"
    if h < mr_threshold:
        return "mean_reverting"
    return "random_walk"


def _loglog_fit(log_x: np.ndarray,
                log_y: np.ndarray) -> tuple[float, float, float]:
    """Linear fit y = slope*x + intercept. Returns (slope, intercept, r2)."""
    if len(log_x) < 2:
        return float("nan"), float("nan"), float("nan")
    slope, intercept = np.polyfit(log_x, log_y, 1)
    y_hat = slope * log_x + intercept
    ss_res = float(np.sum((log_y - y_hat) ** 2))
    ss_tot = float(np.sum((log_y - log_y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return float(slope), float(intercept), float(r2)


# ---------------------------------------------------------------------------
# R/S method
# ---------------------------------------------------------------------------


def hurst_rs(
    series,
    lags: tuple = (10, 20, 40, 80, 160),
    clip_warn: bool = True,
    nan_on_unstable: bool = True,
) -> HurstResult:
    """Rescaled Range (R/S) method for the Hurst exponent.

    Parameters
    ----------
    series : pd.Series | np.ndarray | list
        Input series (returns or stationary-like values).
    lags : tuple of int
        Window sizes used for the R/S statistic. Each lag must be at least 2
        and not exceed the series length.
    clip_warn : bool
        When True (default) and the raw slope falls outside [0, 1], emit a
        ``RuntimeWarning`` before clipping. The estimate is unstable when
        this happens; usually caused by short series or weakly stationary
        input.
    nan_on_unstable : bool
        When True (default), return ``hurst=NaN`` instead of clipping a
        slope that lies outside [0, 1]. Useful upstream of regime
        classifiers that should drop unstable estimates rather than treat
        clipped values as valid.

        .. note::
           The default flipped from ``False`` (clip silently to [0, 1]) to
           ``True`` in v1.3 of the audit cycle. Downstream callers that
           depended on always receiving a finite value in [0, 1] must now
           opt back into the legacy clipping behavior with
           ``nan_on_unstable=False`` or guard with ``np.isfinite``.
           :func:`hurst_regime_filter` already classifies NaN as "no
           label" via :func:`np.isfinite`, so it is unaffected.

    Returns
    -------
    HurstResult
    """
    arr = _coerce_series(series)
    n = arr.size
    if n < 20:
        raise ValueError(f"Need >= 20 observations for R/S, got {n}")

    valid_lags = [int(L) for L in lags if 2 <= int(L) <= n // 2]
    if len(valid_lags) < 2:
        raise ValueError(
            f"Need >= 2 valid lags within [2, n/2={n // 2}], got {valid_lags}"
        )

    rs_means = []
    used_lags = []
    for L in valid_lags:
        n_chunks = n // L
        chunks = arr[: n_chunks * L].reshape(n_chunks, L)
        rs_vals = []
        for chunk in chunks:
            mu = chunk.mean()
            dev = chunk - mu
            cum = np.cumsum(dev)
            R = cum.max() - cum.min()
            S = chunk.std(ddof=0)
            if S > 0:
                rs_vals.append(R / S)
        if rs_vals:
            rs_means.append(float(np.mean(rs_vals)))
            used_lags.append(L)

    if len(used_lags) < 2:
        raise ValueError("Insufficient non-degenerate chunks to fit R/S.")

    log_lags = np.log(np.asarray(used_lags, dtype=float))
    log_rs = np.log(np.asarray(rs_means, dtype=float))
    slope, intercept, r2 = _loglog_fit(log_lags, log_rs)
    out_of_range = not (0.0 <= slope <= 1.0)
    if out_of_range:
        if clip_warn:
            warnings.warn(
                f"Hurst R/S slope {slope:.4f} outside [0, 1] before clipping; "
                "estimate may be unstable.",
                RuntimeWarning,
                stacklevel=2,
            )
        if nan_on_unstable:
            h = float("nan")
        else:
            h = float(np.clip(slope, 0.0, 1.0))
    else:
        h = float(slope)
    return HurstResult(
        hurst=h,
        method="rs",
        # Distinguish "estimated H within the random-walk band" (h is finite,
        # in [mr_threshold, trend_threshold]) from "estimate failed / NaN".
        # The previous sentinel collided both cases on "random_walk", which
        # caused regime filters to treat unstable estimates as random walks.
        interpretation=_classify(h) if np.isfinite(h) else "unknown",
        log_lags=log_lags,
        log_rs=log_rs,
        fit_slope=slope,
        fit_intercept=intercept,
        r_squared=r2,
    )


# ---------------------------------------------------------------------------
# DFA method
# ---------------------------------------------------------------------------


def _default_dfa_scales(n: int) -> tuple:
    """Geometric grid of window sizes from 4 to n // 4."""
    upper = max(8, n // 4)
    if upper < 8:
        return (4, 8)
    # geometric spacing in log2 to keep ~6-10 scales
    n_steps = max(4, int(np.log2(upper / 4.0)) + 1)
    grid = np.unique(
        np.round(np.geomspace(4, upper, num=n_steps)).astype(int)
    )
    return tuple(int(s) for s in grid if s >= 4)


def hurst_dfa(
    series,
    scales: Optional[tuple] = None,
    order: int = 1,
    clip_warn: bool = True,
    nan_on_unstable: bool = True,
) -> HurstResult:
    """Detrended Fluctuation Analysis.

    Parameters
    ----------
    series : pd.Series | np.ndarray | list
        Input series. Typically prices (or a non-stationary signal). The
        function will integrate (cumulative sum of mean-removed values)
        before partitioning, so passing returns also works.
    scales : tuple of int, optional
        Window sizes. Default = geometric grid 4 .. N/4.
    order : int
        Detrending polynomial order (1 = linear, 2 = quadratic, ...).
    clip_warn : bool
        When True (default) and the raw slope falls outside [0, 1], emit a
        ``RuntimeWarning`` before clipping.
    nan_on_unstable : bool
        When True (default), return ``hurst=NaN`` instead of clipping an
        out-of-range slope. See :func:`hurst_rs` for the contract change
        notice (default flipped from ``False`` to ``True`` in v1.3).

    Returns
    -------
    HurstResult
    """
    arr = _coerce_series(series)
    n = arr.size
    if n < 16:
        raise ValueError(f"Need >= 16 observations for DFA, got {n}")
    if order < 1:
        raise ValueError("order must be >= 1")

    if scales is None:
        scales = _default_dfa_scales(n)
    valid_scales = [int(s) for s in scales if order + 1 < int(s) <= n // 2]
    if len(valid_scales) < 2:
        raise ValueError(
            f"Need >= 2 valid scales within ({order + 1}, n/2={n // 2}], "
            f"got {valid_scales}"
        )

    # Profile: cumulative sum of mean-removed series.
    profile = np.cumsum(arr - arr.mean())

    flucts = []
    used_scales = []
    for s in valid_scales:
        n_segs = n // s
        if n_segs < 1:
            continue
        # Both forward and reverse segmentation (Peng et al. recommendation).
        segs_fwd = profile[: n_segs * s].reshape(n_segs, s)
        segs_bwd = profile[-n_segs * s:].reshape(n_segs, s)
        x = np.arange(s, dtype=float)
        seg_var = []
        for seg in np.vstack([segs_fwd, segs_bwd]):
            coeffs = np.polyfit(x, seg, order)
            trend = np.polyval(coeffs, x)
            seg_var.append(float(np.mean((seg - trend) ** 2)))
        if seg_var:
            f_n = float(np.sqrt(np.mean(seg_var)))
            if f_n > 0:
                flucts.append(f_n)
                used_scales.append(s)

    if len(used_scales) < 2:
        raise ValueError("Insufficient valid DFA segments.")

    log_scales = np.log(np.asarray(used_scales, dtype=float))
    log_flucts = np.log(np.asarray(flucts, dtype=float))
    slope, intercept, r2 = _loglog_fit(log_scales, log_flucts)
    out_of_range = not (0.0 <= slope <= 1.0)
    if out_of_range:
        if clip_warn:
            warnings.warn(
                f"Hurst DFA slope {slope:.4f} outside [0, 1] before clipping; "
                "estimate may be unstable.",
                RuntimeWarning,
                stacklevel=2,
            )
        if nan_on_unstable:
            h = float("nan")
        else:
            h = float(np.clip(slope, 0.0, 1.0))
    else:
        h = float(slope)
    return HurstResult(
        hurst=h,
        method="dfa",
        # See ``hurst_rs`` — "unknown" sentinel separates failed fits from
        # genuinely random-walk estimates so downstream filters can drop
        # the former without treating them as meaningful regime calls.
        interpretation=_classify(h) if np.isfinite(h) else "unknown",
        log_lags=log_scales,
        log_rs=log_flucts,
        fit_slope=slope,
        fit_intercept=intercept,
        r_squared=r2,
    )


# ---------------------------------------------------------------------------
# Rolling Hurst + regime filter
# ---------------------------------------------------------------------------


def _hurst_value(arr: np.ndarray, method: str) -> float:
    """Compute a single Hurst value for an array; NaN on failure."""
    try:
        if method == "rs":
            n = arr.size
            # adapt lags so they fit in the window
            base = [10, 20, 40, 80, 160]
            lags = tuple(L for L in base if 2 <= L <= n // 2)
            if len(lags) < 2:
                return float("nan")
            return hurst_rs(arr, lags=lags).hurst
        if method == "dfa":
            return hurst_dfa(arr).hurst
        raise ValueError(f"Unknown method: {method}")
    except (ValueError, np.linalg.LinAlgError):
        return float("nan")


def rolling_hurst(series, window: int = 252,
                  method: str = "rs") -> pd.Series:
    """Rolling Hurst exponent over a sliding window.

    Parameters
    ----------
    series : pd.Series | np.ndarray | list
        Input series.
    window : int
        Sliding window length. Must be >= 30 for stable estimation.
    method : str
        'rs' or 'dfa'.

    Returns
    -------
    pd.Series of Hurst values aligned with the input index. The first
    ``window - 1`` entries are NaN.
    """
    s = pd.Series(series).astype(float)
    if window < 30:
        raise ValueError(f"window must be >= 30, got {window}")
    if method not in {"rs", "dfa"}:
        raise ValueError(f"method must be 'rs' or 'dfa', got {method!r}")

    arr = s.to_numpy()
    n = arr.size
    out = np.full(n, np.nan, dtype=float)
    if n < window:
        return pd.Series(out, index=s.index, name=f"hurst_{method}")

    for i in range(window - 1, n):
        chunk = arr[i - window + 1: i + 1]
        if np.isnan(chunk).any():
            continue
        out[i] = _hurst_value(chunk, method)

    return pd.Series(out, index=s.index, name=f"hurst_{method}")


def hurst_regime_filter(series, window: int = 252,
                        trend_threshold: float = 0.55,
                        mr_threshold: float = 0.45,
                        method: str = "rs") -> pd.Series:
    """Classify regimes from rolling Hurst exponent.

    Parameters
    ----------
    series : pd.Series | np.ndarray | list
        Input series.
    window : int
        Rolling window length.
    trend_threshold : float
        H above this -> 'trending'.
    mr_threshold : float
        H below this -> 'mean_reverting'.
    method : str
        'rs' or 'dfa'.

    Returns
    -------
    pd.Series of {'trending', 'random', 'mean_reverting', 'unknown', NaN}.
    The first ``window - 1`` entries (rolling warm-up) are ``NaN``. After
    that, an unstable per-window fit produces ``'unknown'`` so callers
    can distinguish a genuine random-walk regime from a failed estimate.
    """
    if not 0.0 < mr_threshold < trend_threshold < 1.0:
        raise ValueError(
            "Require 0 < mr_threshold < trend_threshold < 1, "
            f"got mr={mr_threshold}, trend={trend_threshold}"
        )
    h = rolling_hurst(series, window=window, method=method)
    # Rows where the rolling hurst itself is NaN split into:
    # - rolling warm-up (first window-1 rows): keep NaN so callers can
    #   ``dropna()`` the warm-up region as before.
    # - unstable per-window fits inside the populated region: emit the
    #   distinct ``"unknown"`` sentinel so callers can tell a failed fit
    #   apart from a successful "random" classification.
    warmup_mask = np.zeros(len(h), dtype=bool)
    warmup_mask[: max(0, window - 1)] = True

    def _label_finite(x: float) -> str:
        if x > trend_threshold:
            return "trending"
        if x < mr_threshold:
            return "mean_reverting"
        return "random"

    out: list = []
    for i, x in enumerate(h.to_numpy()):
        if not np.isfinite(x):
            out.append(np.nan if warmup_mask[i] else "unknown")
        else:
            out.append(_label_finite(float(x)))
    return pd.Series(out, index=h.index, name="hurst_regime")
