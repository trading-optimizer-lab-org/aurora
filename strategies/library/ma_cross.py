"""Moving Average Crossover. Simplest trend-following primitive.

Numerical note: SMA is computed via a float64 cumsum. cumsum is used safely
here -- price series typically fit well within float64 range. For S&P-style
prices (~1-1e5) and bars in the millions, cumsum stays in 1e10-1e11 range,
far below float64's ~1.8e308 limit. Float64 has ~15-17 decimal digits of
precision so cancellation error in (cs[i+1]-cs[i+1-w])/w is bounded by
roughly 1e-10 of the price level, which is irrelevant for trading signals.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from quantforge.strategies.base import Strategy, StrategySpec


class MACross(Strategy):
    def __init__(self, fast: int = 20, slow: int = 100, allow_short: bool = True):
        # Project to a valid configuration: GA decoders may sample fast >= slow
        # (the spec ranges (5,60) and (50,300) overlap). Without this, the
        # genome wastes evaluations on degenerate signals=zeros. Force
        # slow >= fast + 1 so the crossover is well defined.
        f = int(fast)
        s = int(slow)
        if s <= f:
            s = f + 1
        self.fast = f
        self.slow = s
        self.allow_short = allow_short

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="MACross",
            params={"fast": 20, "slow": 100, "allow_short": True},
            param_ranges={"fast": (5, 60), "slow": (50, 300), "allow_short": [True, False]},
        )

    def signals(self, prices: pd.Series) -> np.ndarray:
        p = prices.values.astype(float)
        n = len(p)
        # ctor enforces self.slow > self.fast; defensive check kept as a
        # belt-and-braces fallback in case attrs are mutated post-construction.
        if self.fast >= self.slow:
            return np.zeros(n)
        # SMA via cumsum (no lookahead: signal[i] uses p[:i+1])
        cs = np.empty(n + 1); cs[0] = 0; np.cumsum(p, out=cs[1:])
        sma_fast = np.full(n, np.nan); sma_slow = np.full(n, np.nan)
        for i in range(self.fast - 1, n):
            sma_fast[i] = (cs[i+1] - cs[i+1-self.fast]) / self.fast
        for i in range(self.slow - 1, n):
            sma_slow[i] = (cs[i+1] - cs[i+1-self.slow]) / self.slow
        sig = np.zeros(n)
        for i in range(self.slow - 1, n):
            if sma_fast[i] > sma_slow[i]:
                sig[i] = 1.0
            elif self.allow_short:
                sig[i] = -1.0
            else:
                sig[i] = 0.0
        return sig
