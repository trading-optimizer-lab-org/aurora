"""Drawdown metrics."""
from __future__ import annotations
import numpy as np
import pandas as pd

from aurora.analytics.metrics_full._helpers import (
    _drawdown_series,
    _to_array,
    _to_series,
)


def max_drawdown(returns) -> float:
    """Worst peak-to-trough drawdown (negative)."""
    dd = _drawdown_series(returns)
    return float(dd.min()) if len(dd) else 0.0


def avg_drawdown(returns) -> float:
    """Average drawdown depth across all distinct drawdowns."""
    dd = _drawdown_series(returns)
    if len(dd) == 0:
        return 0.0
    in_dd = dd < 0
    if not in_dd.any():
        return 0.0
    troughs = []
    cur_min = 0.0
    for i, d in enumerate(dd):
        if d < 0:
            cur_min = min(cur_min, d)
        elif cur_min < 0:
            troughs.append(cur_min)
            cur_min = 0.0
    if cur_min < 0:
        troughs.append(cur_min)
    if not troughs:
        return 0.0
    return float(np.mean(troughs))


def avg_drawdown_days(returns) -> float:
    """Average drawdown duration in periods."""
    dd = _drawdown_series(returns)
    if len(dd) == 0:
        return 0.0
    durations = []
    cur = 0
    for d in dd:
        if d < 0:
            cur += 1
        else:
            if cur > 0:
                durations.append(cur)
                cur = 0
    if cur > 0:
        durations.append(cur)
    return float(np.mean(durations)) if durations else 0.0


def recovery_factor(returns) -> float:
    """Total return / |max drawdown|."""
    from aurora.analytics.metrics_full.returns import compounded_return
    mdd = max_drawdown(returns)
    if abs(mdd) < 1e-12:
        return 0.0
    return float(compounded_return(returns) / abs(mdd))


def calmar_ratio(returns, ppy: int = 252) -> float:
    """CAGR / |max drawdown|."""
    from aurora.analytics.metrics_full.returns import cagr
    mdd = max_drawdown(returns)
    if abs(mdd) < 1e-12:
        return 0.0
    return float(cagr(returns, ppy) / abs(mdd))


def mar_ratio(returns, ppy: int = 252) -> float:
    """Same as calmar_ratio (managed-account ratio)."""
    return calmar_ratio(returns, ppy)


def conditional_drawdown(returns, alpha: float = 0.05) -> float:
    """Mean of worst alpha-quantile drawdowns."""
    dd = _drawdown_series(returns)
    if len(dd) == 0:
        return 0.0
    cutoff = np.quantile(dd, alpha)
    tail = dd[dd <= cutoff]
    return float(tail.mean()) if len(tail) else 0.0


def drawdown_details(returns) -> pd.DataFrame:
    """Per-drawdown details: start, end, depth, recovery_days."""
    s = _to_series(returns)
    if len(s) == 0:
        return pd.DataFrame(columns=["start", "end", "depth", "recovery_days"])
    eq = (1.0 + s).cumprod()
    cummax = eq.cummax()
    dd = (eq - cummax) / cummax

    rows = []
    in_dd = False
    start_idx = 0
    trough_val = 0.0
    for i, d in enumerate(dd.values):
        if d < 0 and not in_dd:
            in_dd = True
            start_idx = i
            trough_val = d
        elif d < 0 and in_dd:
            trough_val = min(trough_val, d)
        elif d >= 0 and in_dd:
            in_dd = False
            rows.append({
                "start": s.index[start_idx],
                "end": s.index[i],
                "depth": float(trough_val),
                "recovery_days": int(i - start_idx),
            })
    if in_dd:
        rows.append({
            "start": s.index[start_idx],
            "end": s.index[-1],
            "depth": float(trough_val),
            "recovery_days": int(len(s) - 1 - start_idx),
        })
    return pd.DataFrame(rows, columns=["start", "end", "depth", "recovery_days"])
