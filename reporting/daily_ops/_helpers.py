"""Shared helpers for the daily ops builder.

Module-private. Public API stays at ``aurora.reporting.daily_ops.builder``.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd


SEVERITY_LEVELS = ("info", "warn", "critical")


def _safe_get(d: Optional[Mapping[str, Any]], key: str, default: Any = None) -> Any:
    if d is None:
        return default
    return d.get(key, default)


def _series_returns_through(returns: Optional[pd.Series],
                            asof: pd.Timestamp,
                            window_days: Optional[int] = None) -> pd.Series:
    """Slice a returns series up to ``asof`` (inclusive), optionally last N."""
    if returns is None or len(returns) == 0:
        return pd.Series(dtype=float)
    s = returns.copy()
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index)
    s = s[s.index <= asof]
    if window_days is not None and len(s) > window_days:
        s = s.iloc[-window_days:]
    return s


def _annualized_sharpe(returns: pd.Series, ppy: int = 252) -> float:
    if returns is None or len(returns) < 2:
        return 0.0
    r = returns.dropna().to_numpy(dtype=float)
    if r.size < 2:
        return 0.0
    mu = float(r.mean())
    sd = float(r.std(ddof=1))
    if sd <= 1e-12:
        return 0.0
    return float(mu / sd * np.sqrt(ppy))


def _drawdown_series(returns: pd.Series) -> pd.Series:
    if returns is None or len(returns) == 0:
        return pd.Series(dtype=float)
    eq = (1.0 + returns.fillna(0.0)).cumprod()
    cummax = eq.cummax()
    return (eq - cummax) / cummax


def _max_drawdown(returns: pd.Series) -> float:
    dd = _drawdown_series(returns)
    return float(dd.min()) if len(dd) else 0.0


def _current_drawdown(returns: pd.Series) -> float:
    dd = _drawdown_series(returns)
    return float(dd.iloc[-1]) if len(dd) else 0.0


def _days_in_drawdown(returns: pd.Series) -> int:
    """Return the number of consecutive bars with non-zero drawdown."""
    dd = _drawdown_series(returns)
    if len(dd) == 0:
        return 0
    n = 0
    for v in reversed(dd.tolist()):
        if v < -1e-12:
            n += 1
        else:
            break
    return n


def _win_rate(trades: Optional[pd.Series], n: int = 20) -> Optional[float]:
    if trades is None or len(trades) == 0:
        return None
    last = trades.dropna().iloc[-n:]
    if len(last) == 0:
        return None
    return float((last > 0).mean())
