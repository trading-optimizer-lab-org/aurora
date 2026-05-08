"""Vol-target wrapper: scales any base strategy weights by realized-vol scalar."""
from __future__ import annotations
import numpy as np
import pandas as pd
from quantforge.strategies.base import Strategy, StrategySpec


class VolTargetWrapper(Strategy):
    """Wraps another Strategy. weight_final = weight_base * min(target_vol/realized_vol, max_w).

    NOTE: This is a wrapper strategy and is NOT directly runnable from run_ga
    via spec()-only param sampling, because the ctor requires a `base: Strategy`
    positional argument that spec().param_ranges does not include. To use in
    a GA, build a wrapper_factory that closes over a concrete base strategy
    and pass it as the strategy_class adapter, OR skip this class via the
    is_wrapper sentinel attribute below in any GA discovery.
    """

    # Sentinel for GA-discovery code: signals that this strategy cannot be
    # constructed from spec().param_ranges alone and should be skipped.
    is_wrapper: bool = True

    def __init__(self, base: Strategy = None, target_vol: float = 0.15, max_w: float = 0.20,
                 vol_window: int = 60):
        if base is None:
            raise TypeError(
                "VolTargetWrapper requires a base Strategy. This wrapper cannot "
                "be constructed from spec().param_ranges alone; pass `base=...` "
                "explicitly or use a wrapper_factory in run_ga."
            )
        self.base = base
        self.target_vol = float(target_vol)
        self.max_w = float(max_w)
        self.vol_window = int(vol_window)

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="VolTargetWrapper",
            params={"target_vol": 0.15, "max_w": 0.20, "vol_window": 60},
            param_ranges={
                "target_vol": (0.05, 0.30),
                "max_w": (0.05, 1.0),
                "vol_window": (10, 120),
            },
        )

    def signals(self, prices: pd.Series) -> np.ndarray:
        base_sig = self.base.signals(prices)
        p = prices.values.astype(float)
        n = len(p)
        # rets[i] is the return of bar i (close[i]/close[i-1] - 1).
        rets = np.zeros(n); rets[1:] = p[1:] / p[:-1] - 1.0
        vol = np.full(n, np.nan)
        w = self.vol_window
        # Anti-lookahead: vol[i] uses returns through bar i-1 only
        # (rets[i-w : i] excludes rets[i]) so the volatility scalar applied
        # to base_sig[i] is computable from prices[:i] alone. This preserves
        # the Strategy invariant that signal[i] uses prices[:i+1] only --
        # in fact this scalar is even stricter (prices[:i] only).
        for i in range(w, n):
            vol[i] = np.std(rets[i - w:i]) * np.sqrt(252)
        out = np.zeros(n)
        for i in range(n):
            # Pre-warmup region (vol[i] still NaN): keep the wrapper output
            # at 0 instead of falling back to target_vol. Using target_vol
            # silently scales the base signal during the warmup window with
            # no realized-vol estimate, which causes spurious early-period
            # exposure in tests and live mode. Treat warmup as flat.
            if np.isnan(vol[i]):
                out[i] = 0.0
                continue
            v = vol[i] if vol[i] > 0 else self.target_vol
            scale = min(self.target_vol / v, self.max_w)
            out[i] = base_sig[i] * scale
        return np.clip(out, -1.0, 1.0)
