"""Stop-loss / take-profit wrapper. Close-only proxy with lockout."""
from __future__ import annotations
import numpy as np
import pandas as pd
from quantforge.strategies.base import Strategy, StrategySpec


class StopWrapper(Strategy):
    """Wraps any base Strategy with stop-loss and take-profit on close-only proxy.

    Logic:
    - Tracks position entry price.
    - On bar i with open position, compute return since entry.
    - If return <= -stop_pct: exit (signal=0), lockout K bars.
    - If return >= take_pct: exit (signal=0), lockout K bars.
    - Otherwise: pass through base.signals.

    Note: close-only proxy stops fire at close not intraday. For intraday HL
    stops, future engine extension needed.

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

    def __init__(self, base: Strategy = None, stop_pct: float = 0.05,
                 take_pct: float = 0.20, lockout: int = 5):
        if base is None:
            raise TypeError(
                "StopWrapper requires a base Strategy. This wrapper cannot "
                "be constructed from spec().param_ranges alone; pass `base=...` "
                "explicitly or use a wrapper_factory in run_ga."
            )
        self.base = base
        self.stop_pct = float(stop_pct)
        self.take_pct = float(take_pct)
        self.lockout = int(lockout)

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="StopWrapper",
            params={"stop_pct": 0.05, "take_pct": 0.20, "lockout": 5},
            param_ranges={
                "stop_pct": (0.01, 0.10),
                "take_pct": (0.05, 0.50),
                "lockout": (0, 20),
            },
        )

    def signals(self, prices: pd.Series) -> np.ndarray:
        base_sig = np.asarray(self.base.signals(prices), dtype=float)
        p = prices.values.astype(float)
        n = len(p)
        out = np.zeros(n)

        cur_pos = 0.0
        entry_px = 0.0
        lockout_until = -1  # last bar index (inclusive) where lockout is active

        for i in range(n):
            in_lockout = i <= lockout_until
            base_i = base_sig[i] if not np.isnan(base_sig[i]) else 0.0

            if cur_pos != 0.0:
                # check stop / take based on close[i] vs entry
                if entry_px > 0.0:
                    ret = (p[i] - entry_px) / entry_px * np.sign(cur_pos)
                else:
                    ret = 0.0
                if ret <= -self.stop_pct or ret >= self.take_pct:
                    # exit + start lockout: bars [i+1 .. i+lockout] are blocked (lockout bars total)
                    cur_pos = 0.0
                    entry_px = 0.0
                    lockout_until = i + self.lockout
                    out[i] = 0.0
                    continue
                # still in position: check if base flipped or exited
                if base_i == 0.0:
                    cur_pos = 0.0
                    entry_px = 0.0
                    out[i] = 0.0
                elif np.sign(base_i) != np.sign(cur_pos):
                    # flip: new entry at this close
                    cur_pos = base_i
                    entry_px = p[i]
                    out[i] = cur_pos
                else:
                    # same side, pass through (allow size changes from base)
                    cur_pos = base_i
                    out[i] = cur_pos
            else:
                # flat
                if in_lockout:
                    out[i] = 0.0
                    continue
                if base_i != 0.0:
                    cur_pos = base_i
                    entry_px = p[i]
                    out[i] = cur_pos
                else:
                    out[i] = 0.0
        return out
