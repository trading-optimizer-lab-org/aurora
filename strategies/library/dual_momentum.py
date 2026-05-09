"""Antonacci dual momentum (single-asset variant).

For SINGLE asset: applies absolute momentum filter:
- LONG if past lookback return > rf_period AND past return > 0
- SHORT (if allow_short) if past return < -rf_period
- else CASH (return 0)

Note: Full Antonacci is cross-sectional (multi-asset). This is the
single-asset reduction. For full multi-asset version, see future
multi-asset extension.

rf_proxy is annualized; converted to a lookback-period rate using the
correct geometric (compound) scaling: ``rf_period = (1 + rf_proxy) ** (L/252) - 1``.
The previous linear formula ``rf_proxy * (L/252)`` understated rf for L > 252
and overstated it for L < 252, biasing the long/short threshold against the
intended risk-free hurdle.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from aurora.strategies.base import Strategy, StrategySpec


class DualMomentum(Strategy):
    def __init__(self, lookback: int = 252, skip: int = 21,
                 rf_proxy: float = 0.0, allow_short: bool = False):
        self.lookback = int(lookback)
        self.skip = int(skip)
        self.rf_proxy = float(rf_proxy)
        self.allow_short = bool(allow_short)

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="DualMomentum",
            params={
                "lookback": 252, "skip": 21,
                "rf_proxy": 0.0, "allow_short": False,
            },
            param_ranges={
                "lookback": (60, 504),
                "skip": (0, 30),
                "rf_proxy": (0.0, 0.04),
                "allow_short": [True, False],
            },
        )

    def signals(self, prices: pd.Series) -> np.ndarray:
        p = prices.values.astype(float)
        n = len(p)
        sig = np.zeros(n)
        L = self.lookback
        sk = self.skip
        # Convert annualized rf to lookback-period equivalent via compound
        # (geometric) scaling so the threshold matches the geometric return
        # ``past_close / old_close - 1``. Linear scaling (* L/252) is wrong
        # for L != 252.
        rf_period = (1.0 + self.rf_proxy) ** (L / 252.0) - 1.0
        start = L + sk
        for i in range(start, n):
            past_close = p[i - sk]
            old_close = p[i - sk - L]
            if old_close <= 0:
                continue
            ret = past_close / old_close - 1.0
            if ret > rf_period and ret > 0:
                sig[i] = 1.0
            elif self.allow_short and ret < -rf_period:
                sig[i] = -1.0
        return sig
