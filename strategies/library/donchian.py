"""Donchian channel breakout. Classic trend-following turtle-style."""
from __future__ import annotations
import numpy as np
import pandas as pd
from quantforge.strategies.base import Strategy, StrategySpec


class DonchianBreakout(Strategy):
    def __init__(self, channel: int = 55, exit_channel: int = 20, allow_short: bool = True):
        self.channel = int(channel)
        self.exit_channel = int(exit_channel)
        self.allow_short = allow_short

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="DonchianBreakout",
            params={"channel": 55, "exit_channel": 20, "allow_short": True},
            param_ranges={
                "channel": (20, 200), "exit_channel": (5, 50), "allow_short": [True, False],
            },
        )

    def signals(self, prices: pd.Series) -> np.ndarray:
        p = prices.values.astype(float)
        n = len(p)
        sig = np.zeros(n)
        pos = 0.0
        # Prior channel: bars [i-channel .. i-1] (length=channel, ends at i-1).
        # Anti-lookahead (strategy-side): signal[i] uses prices through bar i,
        # i.e. p[:i+1] only. The breakout test compares p[i] against the
        # rolling max/min of p[i-channel:i] which excludes p[i] itself.
        # Engine convention (separate concern): the backtest engine applies
        # weights[i] to returns[i+1], so breakout detected at bar i is acted
        # on at bar i+1's open. That 1-bar lag belongs to the engine, NOT to
        # this strategy.
        start = max(self.channel, self.exit_channel)
        for i in range(start, n):
            high_n = p[i - self.channel:i].max()
            low_n = p[i - self.channel:i].min()
            high_e = p[i - self.exit_channel:i].max()
            low_e = p[i - self.exit_channel:i].min()
            if pos == 0:
                if p[i] > high_n: pos = 1.0
                elif self.allow_short and p[i] < low_n: pos = -1.0
            elif pos > 0 and p[i] < low_e:
                pos = 0.0
            elif pos < 0 and p[i] > high_e:
                pos = 0.0
            sig[i] = pos
        return sig
