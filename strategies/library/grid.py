"""Grid trading strategy template (R124).

Place buy orders at evenly spaced steps below the current price, sell
at steps above. Hard caps on grid depth + cumulative position prevent
the classic grid-blowup failure mode.

NOTE: martingale-style position-doubling-after-loss variants are
deliberately NOT shipped. They magnify the worst case rather than
managing it.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantforge.strategies.base import Strategy, StrategySpec


class GridStrategy(Strategy):
    """Symmetric grid around the rolling reference price.

    Args:
        lookback: rolling window used to anchor the grid centre.
        step_pct: spacing between grid levels (fraction of price).
        max_depth: maximum number of levels above and below.
        max_position: cap on cumulative absolute position (in [0, 1]).
        allow_short: whether the upper grid sells short (True) or just
            scales out an existing long (False).
    """

    def __init__(
        self,
        lookback: int = 50,
        step_pct: float = 0.02,
        max_depth: int = 5,
        max_position: float = 1.0,
        allow_short: bool = False,
    ) -> None:
        if step_pct <= 0:
            raise ValueError("step_pct must be > 0")
        if max_depth < 1:
            raise ValueError("max_depth must be >= 1")
        if not 0.0 < max_position <= 1.0:
            raise ValueError("max_position must be in (0, 1]")
        self.lookback = int(lookback)
        self.step_pct = float(step_pct)
        self.max_depth = int(max_depth)
        self.max_position = float(max_position)
        self.allow_short = bool(allow_short)

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec.make(
            name="GridStrategy",
            hypothesis="Grid trading around a rolling anchor price.",
            strategy_class="quantforge.strategies.library.grid.GridStrategy",
            params={
                "lookback": 50,
                "step_pct": 0.02,
                "max_depth": 5,
                "max_position": 1.0,
                "allow_short": False,
            },
            expected_edge_bps=0.0,
            regime_dependence=["range-bound"],
            failure_modes=["trending market", "grid_blowup"],
            universe=["SPY"],
            rebalance="1d",
            generator="grid_template",
        )

    def signals(self, prices: pd.Series) -> np.ndarray:
        p = prices.values.astype(float)
        n = len(p)
        sig = np.zeros(n)
        if n < self.lookback + 1:
            return sig
        ref = pd.Series(p).rolling(
            self.lookback, min_periods=self.lookback
        ).mean().values
        for i in range(self.lookback, n):
            anchor = ref[i]
            if not np.isfinite(anchor) or anchor <= 0:
                continue
            diff_pct = (p[i] - anchor) / anchor
            steps = int(diff_pct / self.step_pct)
            steps = max(-self.max_depth, min(self.max_depth, steps))
            # Below anchor (steps < 0) -> long; above -> flat or short.
            if steps < 0:
                size = -steps / self.max_depth * self.max_position
                sig[i] = size
            elif steps > 0 and self.allow_short:
                size = steps / self.max_depth * self.max_position
                sig[i] = -size
            else:
                sig[i] = 0.0
        return sig
