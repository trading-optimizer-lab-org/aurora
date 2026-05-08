"""Bar-by-bar backtest replay debugger (R110).

Step through a backtest one bar at a time. Each bar yields a snapshot
of: bar OHLCV summary, indicator state (caller-supplied),
weight before / after, fill notional estimate, running PnL,
running drawdown.

Pure data: returns a generator. The CLI / dashboard wrappers around
this are separate and live in `cli/forge.py` / `monitoring/dashboard.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ReplayFrame:
    """One frame in the replay generator."""

    bar_index: int
    timestamp: pd.Timestamp
    price: float
    weight_before: float
    weight_after: float
    fill_notional: float
    bar_return: float
    cumulative_pnl: float
    running_drawdown: float


def replay(
    prices: pd.Series,
    weights: np.ndarray,
    *,
    portfolio_value: float = 1.0,
) -> Iterator[ReplayFrame]:
    """Yield one :class:`ReplayFrame` per bar.

    The frame layout is intentionally compact so consumers can pretty-
    print or feed a UI without further processing.
    """
    p = prices.values.astype(float)
    w = np.asarray(weights, dtype=float)
    if len(p) != len(w):
        raise ValueError("prices and weights length mismatch")
    if len(p) < 2:
        return
    rets = np.zeros(len(p))
    rets[1:] = p[1:] / p[:-1] - 1.0

    cumulative_pnl = 0.0
    peak = 0.0
    prev_w = 0.0
    for i in range(len(p)):
        bar_ret = rets[i]
        carried = prev_w
        bar_pnl = carried * bar_ret * portfolio_value
        cumulative_pnl += bar_pnl
        peak = max(peak, cumulative_pnl)
        running_dd = cumulative_pnl - peak
        delta_w = w[i] - prev_w
        fill_notional = abs(delta_w) * portfolio_value
        yield ReplayFrame(
            bar_index=i,
            timestamp=pd.Timestamp(prices.index[i]),
            price=float(p[i]),
            weight_before=float(prev_w),
            weight_after=float(w[i]),
            fill_notional=float(fill_notional),
            bar_return=float(bar_ret),
            cumulative_pnl=float(cumulative_pnl),
            running_drawdown=float(running_dd),
        )
        prev_w = w[i]


def render_frame(frame: ReplayFrame) -> str:
    """Pretty single-line representation for terminal output."""
    return (
        f"bar {frame.bar_index:>5} "
        f"ts={frame.timestamp} "
        f"px={frame.price:>10.4f} "
        f"w {frame.weight_before:+.3f}->{frame.weight_after:+.3f} "
        f"ret={frame.bar_return:+.5f} "
        f"pnl={frame.cumulative_pnl:+.4f} "
        f"dd={frame.running_drawdown:+.4f}"
    )


__all__ = [
    "ReplayFrame",
    "replay",
    "render_frame",
]
