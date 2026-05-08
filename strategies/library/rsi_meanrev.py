"""RSI mean-reversion. Long when oversold, short when overbought."""
from __future__ import annotations
import numpy as np
import pandas as pd
from quantforge.strategies.base import Strategy, StrategySpec


def _rsi(p: np.ndarray, n: int, smoothing: str = "wilder") -> np.ndarray:
    """Compute RSI.

    Seed convention (canonical Wilder):
        At index i = n the seed average is mean of the first n price diffs:
        g[:n].mean() == mean(p[1]-p[0], p[2]-p[1], ..., p[n]-p[n-1]).
        That includes the diff ending at bar n-1 (i.e. p[n-1] vs p[n-2]) and
        the diff into bar n (p[n] vs p[n-1]); no bar in [0, n] is dropped.
        rsi[i] is NaN for i < n. The first valid RSI lives at bar n; the
        EMA-style update then runs for i >= n+1 using g[i-1] / l[i-1].

    smoothing:
        'wilder' (canonical, default) -- recursive form avg = (avg*(n-1) + new) / n
            equivalent to an EMA with alpha = 1/n. This is Wilder's original
            smoothing as defined in "New Concepts in Technical Trading Systems".
        'ema' -- standard EMA with alpha = 2/(n+1) applied to gains/losses.
    """
    rsi = np.full(len(p), np.nan)
    if len(p) < n + 1:
        return rsi
    d = np.diff(p)
    g = np.where(d > 0, d, 0.0)
    l = np.where(d < 0, -d, 0.0)
    if smoothing == "wilder":
        # Seed includes g[n-1] (diff from bar n-1 to bar n) so no bar is dropped.
        ag = g[:n].mean()
        al = l[:n].mean()
        for i in range(n, len(p)):
            if i > n:
                ag = (ag * (n - 1) + g[i - 1]) / n
                al = (al * (n - 1) + l[i - 1]) / n
            rsi[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    elif smoothing == "ema":
        alpha = 2.0 / (n + 1.0)
        # Same seed convention as Wilder: mean of the first n diffs.
        ag = g[:n].mean()
        al = l[:n].mean()
        for i in range(n, len(p)):
            if i > n:
                ag = alpha * g[i - 1] + (1.0 - alpha) * ag
                al = alpha * l[i - 1] + (1.0 - alpha) * al
            rsi[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    else:
        raise ValueError(f"smoothing must be 'wilder' or 'ema', got {smoothing!r}")
    return rsi


class RSIMeanRev(Strategy):
    def __init__(self, period: int = 2, oversold: float = 10, overbought: float = 90,
                 allow_short: bool = True, smoothing: str = "wilder"):
        self.period = int(period)
        # GA decoders may sample oversold > overbought (ranges (5, 35) and
        # (65, 95) don't overlap by default but consumers passing custom
        # ranges or hand-tuned params can produce inverted thresholds). Swap
        # them rather than degenerate to a no-op.
        os_v = float(oversold)
        ob_v = float(overbought)
        if os_v > ob_v:
            os_v, ob_v = ob_v, os_v
        self.oversold = os_v
        self.overbought = ob_v
        self.allow_short = allow_short
        if smoothing not in ("wilder", "ema"):
            raise ValueError(f"smoothing must be 'wilder' or 'ema', got {smoothing!r}")
        self.smoothing = smoothing

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="RSIMeanRev",
            params={"period": 2, "oversold": 10.0, "overbought": 90.0,
                    "allow_short": True, "smoothing": "wilder"},
            param_ranges={
                "period": (2, 14), "oversold": (5.0, 35.0),
                "overbought": (65.0, 95.0), "allow_short": [True, False],
                "smoothing": ["wilder", "ema"],
            },
        )

    def signals(self, prices: pd.Series) -> np.ndarray:
        p = prices.values.astype(float)
        rsi = _rsi(p, self.period, self.smoothing)
        sig = np.zeros(len(p))
        last = 0.0
        for i in range(len(p)):
            if np.isnan(rsi[i]):
                sig[i] = 0.0; continue
            if rsi[i] < self.oversold:
                last = 1.0
            elif rsi[i] > self.overbought:
                last = -1.0 if self.allow_short else 0.0
            sig[i] = last
        return sig
