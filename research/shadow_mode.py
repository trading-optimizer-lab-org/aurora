"""Shadow mode runner.

Run a candidate strategy in "shadow" alongside a live strategy. The
shadow strategy receives the same prices but its trades never go to the
broker -- instead the runner accumulates a hypothetical PnL series and
exposes summary stats so we can compare against the live PnL.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable
import math
import numpy as np
import pandas as pd


@dataclass
class ShadowReport:
    n_steps: int
    live_pnl: list[float] = field(default_factory=list)
    shadow_pnl: list[float] = field(default_factory=list)
    live_total: float = 0.0
    shadow_total: float = 0.0
    correlation: float = 0.0
    tracking_error: float = 0.0


class ShadowModeRunner:
    """Compare a hypothetical (shadow) strategy against a live one."""

    def __init__(self, live_signal_fn: Callable[[pd.Series], np.ndarray],
                 shadow_signal_fn: Callable[[pd.Series], np.ndarray]):
        if not callable(live_signal_fn):
            raise TypeError("live_signal_fn must be callable")
        if not callable(shadow_signal_fn):
            raise TypeError("shadow_signal_fn must be callable")
        self.live_signal_fn = live_signal_fn
        self.shadow_signal_fn = shadow_signal_fn

    def run(self, prices: pd.Series) -> ShadowReport:
        if not isinstance(prices, pd.Series):
            raise TypeError("prices must be a pandas Series")
        if len(prices) < 3:
            raise ValueError("need at least 3 price observations")
        p = prices.values.astype(float)
        rets = np.diff(p) / p[:-1]  # length n-1
        sig_live = np.asarray(self.live_signal_fn(prices), dtype=float)
        sig_shadow = np.asarray(self.shadow_signal_fn(prices), dtype=float)
        if len(sig_live) != len(prices):
            raise ValueError("live signal length must match prices")
        if len(sig_shadow) != len(prices):
            raise ValueError("shadow signal length must match prices")
        # apply yesterday's signal to today's return
        live_pnl = sig_live[:-1] * rets
        shadow_pnl = sig_shadow[:-1] * rets
        live_total = float(live_pnl.sum())
        shadow_total = float(shadow_pnl.sum())
        if live_pnl.std() > 0 and shadow_pnl.std() > 0:
            corr = float(np.corrcoef(live_pnl, shadow_pnl)[0, 1])
        else:
            corr = 0.0
        diff = shadow_pnl - live_pnl
        te = float(diff.std(ddof=1)) if len(diff) > 1 else 0.0
        if math.isnan(corr):
            corr = 0.0
        return ShadowReport(
            n_steps=int(len(rets)),
            live_pnl=live_pnl.tolist(), shadow_pnl=shadow_pnl.tolist(),
            live_total=live_total, shadow_total=shadow_total,
            correlation=corr, tracking_error=te,
        )

    def summary(self, report: ShadowReport) -> dict[str, float]:
        return {
            "live_total": report.live_total,
            "shadow_total": report.shadow_total,
            "edge": report.shadow_total - report.live_total,
            "correlation": report.correlation,
            "tracking_error": report.tracking_error,
            "n_steps": float(report.n_steps),
        }
