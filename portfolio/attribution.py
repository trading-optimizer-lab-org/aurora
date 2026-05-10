# ruff: noqa: N806
"""Portfolio return + risk attribution helpers (R172).

Pure functions, no state. The caller owns the inputs:

- ``contribution_to_return(weights, returns)`` -- per-asset contribution
  to total portfolio return (sum equals portfolio mean return up to
  numerical noise).
- ``contribution_to_risk(weights, returns)`` -- per-asset contribution
  to portfolio variance via the marginal-RC decomposition.
- ``benchmark_relative_alpha(portfolio_returns, benchmark_returns)`` --
  ordinary-least-squares regression alpha + beta.
- ``exposure_by_group(weights, group_labels)`` -- weight sum per group.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

__all__ = [
    "benchmark_relative_alpha",
    "contribution_to_return",
    "contribution_to_risk",
    "exposure_by_group",
]


def contribution_to_return(
    weights: Sequence[float],
    returns: np.ndarray,
) -> dict[str, float | np.ndarray]:
    """Per-asset contribution to mean portfolio return.

    For weights w (length N) and returns R (T, N), the per-asset
    contribution to *mean* portfolio return is ``w_i * mean(R_:,i)``.
    Sum equals ``mean(R @ w)`` up to floating-point noise.

    Returns a dict with:
        - ``per_asset``  : np.ndarray length N, contribution per asset
        - ``total``      : float, sum of per-asset contributions
        - ``portfolio``  : float, sample mean of R @ w (sanity check)
    """
    w = np.asarray(weights, dtype=float).ravel()
    R = np.asarray(returns, dtype=float)
    if R.ndim == 1:
        R = R.reshape(-1, 1)
    if R.size == 0 or w.size == 0:
        return {
            "per_asset": np.zeros(w.size, dtype=float),
            "total": 0.0,
            "portfolio": 0.0,
        }
    if w.size != R.shape[1]:
        raise ValueError(
            f"weights size {w.size} != returns columns {R.shape[1]}"
        )
    mean_assets = np.mean(R, axis=0)
    per_asset = w * mean_assets
    return {
        "per_asset": per_asset,
        "total": float(np.sum(per_asset)),
        "portfolio": float(np.mean(R @ w)),
    }


def contribution_to_risk(
    weights: Sequence[float],
    returns: np.ndarray,
) -> dict[str, float | np.ndarray]:
    """Per-asset contribution to portfolio variance.

    Decomposition: portfolio variance ``var(w'R) = w' Sigma w``. The
    per-asset risk contribution is

        RC_i = w_i * (Sigma w)_i

    and ``sum(RC) == w' Sigma w``. We also report the share-of-variance
    ``RC_i / sum(RC)`` so callers can plot a pie / bar chart directly.

    Returns dict with:
        - ``per_asset``  : np.ndarray length N
        - ``share``      : np.ndarray length N (RC_i / total, NaN-safe)
        - ``total``      : float, equals portfolio variance
    """
    w = np.asarray(weights, dtype=float).ravel()
    R = np.asarray(returns, dtype=float)
    if R.ndim == 1:
        R = R.reshape(-1, 1)
    if R.size == 0 or w.size == 0:
        return {
            "per_asset": np.zeros(w.size, dtype=float),
            "share": np.zeros(w.size, dtype=float),
            "total": 0.0,
        }
    if w.size != R.shape[1]:
        raise ValueError(
            f"weights size {w.size} != returns columns {R.shape[1]}"
        )
    if R.shape[0] < 2:
        return {
            "per_asset": np.zeros(w.size, dtype=float),
            "share": np.zeros(w.size, dtype=float),
            "total": 0.0,
        }
    Sigma = np.cov(R, rowvar=False, ddof=1)
    if np.isscalar(Sigma) or Sigma.ndim == 0:
        # single-column R returns a scalar variance from np.cov
        Sigma = np.atleast_2d(np.asarray(Sigma, dtype=float))
    Sw = Sigma @ w
    rc = w * Sw
    total = float(np.sum(rc))
    if total > 0:
        share = rc / total
    else:
        share = np.zeros_like(rc)
    return {
        "per_asset": rc,
        "share": share,
        "total": total,
    }


def benchmark_relative_alpha(
    portfolio_returns: Sequence[float],
    benchmark_returns: Sequence[float],
    risk_free_rate: float = 0.0,
) -> dict[str, float]:
    """OLS alpha / beta of portfolio vs benchmark.

    Returns:
        - alpha         : intercept from OLS (per-period excess return)
        - beta          : slope from OLS
        - tracking_error: std-dev of (portfolio - benchmark) returns
        - residual_std  : std-dev of OLS residual
        - r_squared     : coefficient of determination
    """
    p = np.asarray(portfolio_returns, dtype=float).ravel()
    b = np.asarray(benchmark_returns, dtype=float).ravel()
    if p.size != b.size:
        raise ValueError(
            f"portfolio length {p.size} != benchmark length {b.size}"
        )
    if p.size < 2:
        return {
            "alpha": 0.0,
            "beta": 0.0,
            "tracking_error": 0.0,
            "residual_std": 0.0,
            "r_squared": 0.0,
        }
    # Excess returns
    p_ex = p - risk_free_rate
    b_ex = b - risk_free_rate

    # Beta = cov(p, b) / var(b); alpha = mean(p) - beta * mean(b)
    cov = float(np.cov(p_ex, b_ex, ddof=1)[0, 1])
    var_b = float(np.var(b_ex, ddof=1))
    if var_b <= 1e-16:
        beta = 0.0
    else:
        beta = cov / var_b
    alpha = float(np.mean(p_ex) - beta * np.mean(b_ex))

    diff = p - b
    tracking_error = float(np.std(diff, ddof=1)) if diff.size > 1 else 0.0
    residual = p_ex - (alpha + beta * b_ex)
    residual_std = (
        float(np.std(residual, ddof=1)) if residual.size > 1 else 0.0
    )
    var_p = float(np.var(p_ex, ddof=1))
    if var_p <= 1e-16:
        r_squared = 0.0
    else:
        r_squared = float(1.0 - np.var(residual, ddof=1) / var_p)
    return {
        "alpha": alpha,
        "beta": beta,
        "tracking_error": tracking_error,
        "residual_std": residual_std,
        "r_squared": r_squared,
    }


def exposure_by_group(
    weights: Sequence[float],
    group_labels: Sequence[str | None],
) -> dict[str, float]:
    """Sum of weights per group label.

    Missing labels (None / empty / NaN-like) bucket into ``"unknown"``.
    Use this for sector / asset-class / country / strategy-family
    exposure breakdowns.
    """
    w = np.asarray(weights, dtype=float).ravel()
    if len(group_labels) != w.size:
        raise ValueError(
            f"group_labels length {len(group_labels)} != weights {w.size}"
        )
    out: dict[str, float] = {}
    for i, label in enumerate(group_labels):
        key = label if label not in (None, "") else "unknown"
        # also catch float NaN explicitly (np arrays with object dtype)
        if isinstance(key, float) and np.isnan(key):
            key = "unknown"
        out[key] = out.get(key, 0.0) + float(w[i])
    return out
