"""ATR-based volatility breakout (close-only proxy).

Trade-off: Strategy.signals(prices) takes only close (pd.Series), not OHLC.
True ATR requires high/low/close. This implementation uses a closes-only proxy:
TR_proxy[i] = |close[i] - close[i-1]|, then ATR = rolling mean of TR_proxy.
Less accurate than true Wilder ATR but works with current API. For true OHLC
ATR, future Strategy API extension to accept DataFrame would be required.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from aurora.strategies.base import Strategy, StrategySpec


class ATRBreakout(Strategy):
    """ATR-based volatility breakout (close-only proxy).

    Enter LONG when close > rolling_max(N) + k * ATR.
    Enter SHORT when close < rolling_min(N) - k * ATR -- if allow_short.
    Exit when close crosses back to mid range (rolling MA(N)).

    Uses simplified ATR = rolling mean of |close[i]-close[i-1]| over period.
    For true OHLC ATR, future Strategy API extension required.
    """

    def __init__(self, period: int = 20, atr_period: int = 14,
                 k: float = 1.5, allow_short: bool = True):
        self.period = int(period)
        self.atr_period = int(atr_period)
        self.k = float(k)
        self.allow_short = bool(allow_short)

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="ATRBreakout",
            params={"period": 20, "atr_period": 14, "k": 1.5, "allow_short": True},
            param_ranges={
                "period": (10, 100),
                "atr_period": (5, 30),
                "k": (0.5, 3.0),
                "allow_short": [True, False],
            },
        )

    def signals(self, prices: pd.Series) -> np.ndarray:
        p = prices.values.astype(float)
        n = len(p)
        sig = np.zeros(n)
        if n < 2:
            return sig

        # Close-only proxy TR: |close[i] - close[i-1]|. TR[0] = 0.
        tr = np.zeros(n)
        tr[1:] = np.abs(np.diff(p))

        warmup = max(self.period, self.atr_period) + 1
        pos = 0.0
        for i in range(warmup, n):
            # Anti-lookahead (strategy-side): signal[i] uses prices through
            # bar i, i.e. p[:i+1] only. ATR/window comparators below use
            # p[:i] (rolling stats) and compare against p[i].
            # Engine convention (separate concern): the backtest engine
            # applies weights[i] to returns[i+1] -> breakout signal observed
            # at bar i is acted on at bar i+1's open. That 1-bar lag belongs
            # to the engine, NOT to this strategy.
            atr_i = tr[i - self.atr_period:i].mean()
            window = p[i - self.period:i]
            rolling_max_prev = window.max()
            rolling_min_prev = window.min()
            mid_i = window.mean()

            if pos == 0.0:
                if p[i] > rolling_max_prev + self.k * atr_i:
                    pos = 1.0
                elif self.allow_short and p[i] < rolling_min_prev - self.k * atr_i:
                    pos = -1.0
            elif pos > 0.0 and p[i] < mid_i:
                pos = 0.0
            elif pos < 0.0 and p[i] > mid_i:
                pos = 0.0
            sig[i] = pos
        return sig
