"""Time-series momentum. Long if past N-period return > 0.

Default skip=21 follows Moskowitz/Ooi/Pedersen (2012) "Time Series Momentum"
research convention: skip the most recent month to avoid the short-horizon
mean-reversion contamination at the 1-month horizon. Set legacy_skip=True
to restore the older skip=0 behavior used by some simpler implementations.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from aurora.strategies.base import Strategy, StrategySpec


class TSMomentum(Strategy):
    def __init__(self, lookback: int = 252, skip: int = 21, allow_short: bool = True,
                 legacy_skip: bool = False):
        """Time-series momentum.

        Args:
            lookback: number of bars used to compute past return.
            skip: number of most-recent bars to skip before measuring lookback.
                Default 21 (~1 month) follows research convention. Trade-off:
                skip>0 reduces 1-month reversal noise but truncates the most
                recent signal information; skip=0 uses the freshest data but
                bleeds in mean-reversion at very short horizons.
            allow_short: if True, take -1 when past return < 0; else 0.
            legacy_skip: if True, force skip=0 (old default) regardless of
                the skip arg. Provided for backward compatibility.
        """
        self.lookback = int(lookback)
        self.skip = 0 if legacy_skip else int(skip)
        self.allow_short = allow_short
        self.legacy_skip = bool(legacy_skip)

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="TSMomentum",
            params={"lookback": 252, "skip": 21, "allow_short": True,
                    "legacy_skip": False},
            param_ranges={
                "lookback": (20, 504), "skip": (0, 21),
                "allow_short": [True, False], "legacy_skip": [True, False],
            },
        )

    def signals(self, prices: pd.Series) -> np.ndarray:
        p = prices.values.astype(float)
        n = len(p)
        sig = np.zeros(n)
        L = self.lookback; sk = self.skip
        for i in range(L + sk, n):
            past_close = p[i - sk]
            old_close = p[i - sk - L]
            if old_close <= 0: continue
            ret = past_close / old_close - 1.0
            if ret > 0: sig[i] = 1.0
            elif self.allow_short: sig[i] = -1.0
        return sig
