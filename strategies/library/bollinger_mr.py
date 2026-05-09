"""Bollinger Bands mean reversion. Long below lower, short above upper, exit at MA."""
from __future__ import annotations
import numpy as np
import pandas as pd
from aurora.strategies.base import Strategy, StrategySpec


class BollingerMR(Strategy):
    """Bollinger Bands mean reversion.

    Long when close < lower band (oversold).
    Short when close > upper band (overbought) - if allow_short.
    Exit when close crosses back above MA (long) or below MA (short).
    """

    def __init__(self, period: int = 20, num_std: float = 2.0,
                 allow_short: bool = True, ddof: int = 0):
        """
        ddof: delta degrees of freedom for the rolling std (default 0 = population
              std, matching the prior implementation). Use 1 for sample std
              (the more common econometric default). Exposed so callers can
              choose explicitly rather than depending on an undocumented
              hardcoded convention.
        """
        self.period = int(period)
        self.num_std = float(num_std)
        self.allow_short = allow_short
        self.ddof = int(ddof)

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="BollingerMR",
            params={"period": 20, "num_std": 2.0, "allow_short": True, "ddof": 0},
            param_ranges={
                "period": (10, 50),
                "num_std": (1.5, 3.0),
                "allow_short": [True, False],
                "ddof": [0, 1],
            },
        )

    def signals(self, prices: pd.Series) -> np.ndarray:
        p = prices.values.astype(float)
        n = len(p)
        sig = np.zeros(n)
        if n < self.period:
            return sig
        s = pd.Series(p)
        sma = s.rolling(self.period, min_periods=self.period).mean().values
        std = s.rolling(self.period, min_periods=self.period).std(ddof=self.ddof).values
        upper = sma + self.num_std * std
        lower = sma - self.num_std * std
        pos = 0.0
        for i in range(n):
            if np.isnan(sma[i]):
                sig[i] = 0.0
                continue
            c = p[i]
            if pos == 0.0:
                if c < lower[i]:
                    pos = 1.0
                elif c > upper[i] and self.allow_short:
                    pos = -1.0
            elif pos == 1.0:
                if c > sma[i]:
                    pos = 0.0
            elif pos == -1.0:
                if c < sma[i]:
                    pos = 0.0
            sig[i] = pos
        return sig
