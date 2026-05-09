"""Pair trading via z-score of price spread.

Two assets A and B with static hedge ratio.
Spread = priceA - hedge_ratio * priceB.
z-score = (spread - rolling_mean) / rolling_std (lookback window).

Entry/exit (state machine):
- pos==0 and z >  entry_z -> short spread (-1): short A, long B*hedge_ratio
- pos==0 and z < -entry_z -> long  spread (+1): long  A, short B*hedge_ratio
- pos!=0 and |z| < exit_z -> flat (0)

Per-asset weights returned in [-0.5, 0.5] so gross sums to 1.0 in the
multi-asset engine (each leg gets half the gross exposure).

Anti-lookahead: rolling stats at bar i use only spread[:i+1].
"""
from __future__ import annotations
from typing import Any
import numpy as np
import pandas as pd

from aurora.strategies.base import StrategySpec


class PairTrade:
    """Pair trading via z-score of price spread.

    NOT a subclass of Strategy: returns dict[symbol -> weights] for two assets,
    consumed by MultiAssetEngine. Strategy.signals() is single-asset only.
    """

    def __init__(
        self,
        sym_a: str,
        sym_b: str,
        lookback: int = 60,
        entry_z: float = 2.0,
        exit_z: float = 0.5,
        hedge_ratio: float = 1.0,
        recompute_hedge_ratio_every: int = 0,
        ddof: int = 0,
    ):
        """
        Args:
            hedge_ratio: When ``recompute_hedge_ratio_every == 0`` this is the
                fixed hedge ratio used for every bar. When
                ``recompute_hedge_ratio_every > 0`` it is **only the warmup
                seed**: it is carried forward until the first rolling-OLS
                refit (which fires once ``i >= lookback - 1``), after which
                the recomputed ratio replaces it. Pass any reasonable seed
                in that mode; the value mainly matters for the first
                ``lookback - 1`` bars where no refit has occurred yet.
        """
        if not sym_a or not sym_b:
            raise ValueError("sym_a and sym_b required")
        if sym_a == sym_b:
            raise ValueError(f"sym_a and sym_b must differ, got {sym_a!r}")
        if lookback < 2:
            raise ValueError(f"lookback must be >= 2, got {lookback}")
        if entry_z <= 0:
            raise ValueError(f"entry_z must be > 0, got {entry_z}")
        if exit_z < 0:
            raise ValueError(f"exit_z must be >= 0, got {exit_z}")
        if recompute_hedge_ratio_every < 0:
            raise ValueError(
                f"recompute_hedge_ratio_every must be >= 0, "
                f"got {recompute_hedge_ratio_every}"
            )
        # Project exit_z into the feasible region exit_z < entry_z instead of
        # raising. Empirically ~28% of GA samples land in the infeasible
        # exit_z >= entry_z region (param_ranges entry_z=(1.0, 3.5) and
        # exit_z=(0.0, 1.5) overlap in [1.0, 1.5]). Raising there caused the
        # GA to score those genomes as -99 sentinel and waste samples.
        # Projection clamps exit_z to ``min(exit_z, 0.99 * entry_z)`` so the
        # state machine stays well-defined (strict inequality preserved).
        entry_z_f = float(entry_z)
        exit_z_f = float(exit_z)
        if exit_z_f >= entry_z_f:
            exit_z_f = entry_z_f * 0.99
        self.sym_a = str(sym_a)
        self.sym_b = str(sym_b)
        self.lookback = int(lookback)
        self.entry_z = entry_z_f
        self.exit_z = exit_z_f
        self.hedge_ratio = float(hedge_ratio)
        self.recompute_hedge_ratio_every = int(recompute_hedge_ratio_every)
        self.ddof = int(ddof)

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="PairTrade",
            params={
                "lookback": 60,
                "entry_z": 2.0,
                "exit_z": 0.5,
                "hedge_ratio": 1.0,
                "recompute_hedge_ratio_every": 0,
            },
            param_ranges={
                "lookback": (20, 252),
                "entry_z": (1.0, 3.5),
                "exit_z": (0.0, 1.5),
                "hedge_ratio": (0.5, 2.0),
                "recompute_hedge_ratio_every": (0, 252),
            },
        )

    def weights(self, price_dict: dict) -> dict:
        """Compute per-asset weight arrays.

        Args:
            price_dict: {sym_a: pd.Series, sym_b: pd.Series} with DatetimeIndex.

        Returns:
            {sym_a: np.ndarray, sym_b: np.ndarray} aligned to common index.
            Each value in [-0.5, 0.5]. Opposite signs by construction.
        """
        if self.sym_a not in price_dict:
            raise KeyError(f"price_dict missing {self.sym_a!r}")
        if self.sym_b not in price_dict:
            raise KeyError(f"price_dict missing {self.sym_b!r}")

        pa_full = price_dict[self.sym_a]
        pb_full = price_dict[self.sym_b]
        if not isinstance(pa_full, pd.Series):
            raise TypeError(f"price_dict[{self.sym_a}] must be pd.Series")
        if not isinstance(pb_full, pd.Series):
            raise TypeError(f"price_dict[{self.sym_b}] must be pd.Series")

        # Align on common index (intersection)
        common_idx = pa_full.index.intersection(pb_full.index)
        if len(common_idx) < self.lookback + 1:
            raise ValueError(
                f"insufficient overlapping bars: {len(common_idx)} "
                f"< lookback+1 ({self.lookback + 1})"
            )

        pa = pa_full.reindex(common_idx).values.astype(float)
        pb = pb_full.reindex(common_idx).values.astype(float)
        if np.any(np.isnan(pa)) or np.any(np.isnan(pb)):
            raise ValueError("NaN in aligned prices")

        n = len(common_idx)

        # Hedge ratio: fixed (default) or rolling-OLS recomputed every N bars.
        # Anti-lookahead: at bar i, the ratio is fit on pa[i-lookback+1 : i+1]
        # vs pb[i-lookback+1 : i+1]. The ratio used for spread[i] only depends
        # on pb[:i+1].
        if self.recompute_hedge_ratio_every > 0:
            hedge = np.full(n, self.hedge_ratio, dtype=float)
            step = self.recompute_hedge_ratio_every
            # Wait until we have a full lookback window before first refit.
            # Between refits, carry the most recent ratio forward.
            current = self.hedge_ratio
            for i in range(n):
                if i >= self.lookback - 1 and (i - (self.lookback - 1)) % step == 0:
                    win_a = pa[i - self.lookback + 1 : i + 1]
                    win_b = pb[i - self.lookback + 1 : i + 1]
                    var_b = float(np.var(win_b))
                    if var_b > 0:
                        cov_ab = float(np.cov(win_a, win_b, ddof=0)[0, 1])
                        current = cov_ab / var_b
                hedge[i] = current
            spread = pa - hedge * pb
        else:
            spread = pa - self.hedge_ratio * pb

        # Rolling mean + std using only past data through bar i
        s = pd.Series(spread)
        mean = s.rolling(self.lookback, min_periods=self.lookback).mean().values
        std = s.rolling(self.lookback, min_periods=self.lookback).std(ddof=self.ddof).values

        # Avoid div-by-zero: if std==0 -> z=0 -> no signal
        z = np.zeros(n, dtype=float)
        valid = ~np.isnan(mean) & ~np.isnan(std) & (std > 0)
        z[valid] = (spread[valid] - mean[valid]) / std[valid]

        # State machine for position over time
        pos = np.zeros(n, dtype=float)
        cur = 0.0
        for i in range(n):
            if not valid[i]:
                pos[i] = 0.0
                cur = 0.0
                continue
            zi = z[i]
            if cur == 0.0:
                if zi > self.entry_z:
                    cur = -1.0   # short spread
                elif zi < -self.entry_z:
                    cur = 1.0    # long spread
            else:
                if abs(zi) < self.exit_z:
                    cur = 0.0
            pos[i] = cur

        # Half gross per leg, opposite signs
        w_a = pos * 0.5
        w_b = -pos * 0.5

        return {self.sym_a: w_a, self.sym_b: w_b}

    def with_params(self, **kwargs: Any) -> "PairTrade":
        """Return new instance with updated params (matches Strategy.with_params shape)."""
        new = PairTrade(
            sym_a=kwargs.get("sym_a", self.sym_a),
            sym_b=kwargs.get("sym_b", self.sym_b),
            lookback=kwargs.get("lookback", self.lookback),
            entry_z=kwargs.get("entry_z", self.entry_z),
            exit_z=kwargs.get("exit_z", self.exit_z),
            hedge_ratio=kwargs.get("hedge_ratio", self.hedge_ratio),
            recompute_hedge_ratio_every=kwargs.get(
                "recompute_hedge_ratio_every", self.recompute_hedge_ratio_every
            ),
            ddof=kwargs.get("ddof", self.ddof),
        )
        return new
