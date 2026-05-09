# ruff: noqa: N806
"""Rolling portfolio analytics.

Pure numpy helpers that emit rolling-window statistics on a return path.
All warmup periods (``window - 1`` first entries) are returned as ``NaN``
so that callers can detect insufficient data without losing alignment.

Conventions
-----------
- ``returns`` / ``a`` / ``b`` are 1-D arrays of per-period fractional returns
  (e.g. 0.01 = 1%).
- ``window`` must be a positive integer.
- ``ppy`` (periods per year) defaults to 252 trading days; pass 12 for
  monthly data, 52 for weekly, etc.
- All functions return a numpy array of the same length as the input.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def _as_1d(x: Sequence[float]) -> np.ndarray:
    return np.asarray(x, dtype=float).ravel()


def _validate_window(window: int, n: int) -> None:
    if not isinstance(window, int) or window <= 0:
        raise ValueError(f"window must be a positive int, got {window!r}")
    if window > n:
        raise ValueError(
            f"window={window} larger than series length n={n}"
        )


def rolling_volatility(
    returns: Sequence[float], window: int
) -> np.ndarray:
    """Rolling sample standard deviation (ddof=1) over ``window`` periods.

    First ``window - 1`` entries are ``NaN``.
    """
    r = _as_1d(returns)
    _validate_window(window, r.size)
    out: np.ndarray = np.full(r.size, np.nan, dtype=float)
    for i in range(window - 1, r.size):
        chunk = r[i - window + 1 : i + 1]
        out[i] = float(np.std(chunk, ddof=1))
    return out


def rolling_sharpe(
    returns: Sequence[float], window: int, ppy: int = 252
) -> np.ndarray:
    """Annualised rolling Sharpe ratio with zero risk-free rate.

    Sharpe = mean / std * sqrt(ppy). Windows with zero variance produce
    ``NaN`` to avoid division by zero. First ``window - 1`` entries are
    ``NaN`` (warmup).
    """
    r = _as_1d(returns)
    _validate_window(window, r.size)
    if ppy <= 0:
        raise ValueError(f"ppy must be > 0, got {ppy}")
    out: np.ndarray = np.full(r.size, np.nan, dtype=float)
    scale = float(np.sqrt(ppy))
    for i in range(window - 1, r.size):
        chunk = r[i - window + 1 : i + 1]
        std = float(np.std(chunk, ddof=1))
        if std == 0.0 or not np.isfinite(std):
            out[i] = np.nan
            continue
        mean = float(np.mean(chunk))
        out[i] = mean / std * scale
    return out


def rolling_max_drawdown(
    returns: Sequence[float], window: int
) -> np.ndarray:
    """Rolling max drawdown over ``window`` periods.

    The drawdown is reported as a *signed negative fraction* (0.0 means no
    drawdown in the window, -0.05 means a 5% peak-to-trough loss). First
    ``window - 1`` entries are ``NaN``.
    """
    r = _as_1d(returns)
    _validate_window(window, r.size)
    out: np.ndarray = np.full(r.size, np.nan, dtype=float)
    for i in range(window - 1, r.size):
        chunk = r[i - window + 1 : i + 1]
        equity = np.cumprod(1.0 + chunk)
        peak = np.maximum.accumulate(equity)
        dd = (equity - peak) / peak  # <= 0
        out[i] = float(np.min(dd))
    return out


def rolling_correlation(
    a: Sequence[float], b: Sequence[float], window: int
) -> np.ndarray:
    """Rolling Pearson correlation between two return series.

    Both inputs must have the same length. Windows where either series has
    zero variance produce ``NaN``. First ``window - 1`` entries are ``NaN``.
    """
    x = _as_1d(a)
    y = _as_1d(b)
    if x.size != y.size:
        raise ValueError(
            f"length mismatch: len(a)={x.size}, len(b)={y.size}"
        )
    _validate_window(window, x.size)
    out: np.ndarray = np.full(x.size, np.nan, dtype=float)
    for i in range(window - 1, x.size):
        cx = x[i - window + 1 : i + 1]
        cy = y[i - window + 1 : i + 1]
        sx = float(np.std(cx, ddof=1))
        sy = float(np.std(cy, ddof=1))
        if sx == 0.0 or sy == 0.0 or not np.isfinite(sx) or not np.isfinite(sy):
            out[i] = np.nan
            continue
        # np.corrcoef yields a 2x2 matrix; pick the off-diagonal entry.
        out[i] = float(np.corrcoef(cx, cy)[0, 1])
    return out


__all__ = [
    "rolling_volatility",
    "rolling_sharpe",
    "rolling_max_drawdown",
    "rolling_correlation",
]
