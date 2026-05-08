"""Cross-asset rank-momentum signal.

Across an arbitrary panel of tickers (FX, commodities, equities), compute
multi-lookback total returns, z-score within each lookback, average z, then
rank cross-section. Top-quantile -> +1 (long), bottom -> -1 (short), else 0.

Anti-lookahead: at bar i only prices[:i+1] used.
"""
from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class CrossAssetMomentumConfig:
    """Config."""
    lookbacks: tuple[int, ...] = (21, 63, 126, 252)
    long_quantile: float = 0.7
    short_quantile: float = 0.3
    min_assets: int = 3
    skip_recent: int = 5  # skip last N bars (1-month reversal control)


class CrossAssetMomentum:
    """Rank-based cross-sectional momentum.

    signals(prices) -> pd.DataFrame of {-1, 0, +1} per (date, asset).
    """

    def __init__(self, config: CrossAssetMomentumConfig | None = None):
        self.config = config or CrossAssetMomentumConfig()
        if not self.config.lookbacks:
            raise ValueError("lookbacks must be non-empty")
        if not 0 < self.config.short_quantile < self.config.long_quantile < 1:
            raise ValueError("require 0 < short_quantile < long_quantile < 1")

    def signals(self, prices: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(prices, pd.DataFrame):
            raise TypeError("prices must be pd.DataFrame")
        if prices.shape[1] < self.config.min_assets:
            raise ValueError(f"need >= {self.config.min_assets} assets")
        cfg = self.config
        max_lb = max(cfg.lookbacks) + cfg.skip_recent + 1
        if prices.shape[0] < max_lb:
            raise ValueError(f"insufficient bars: {prices.shape[0]} < {max_lb}")

        # Compute aggregate score per bar
        prices = prices.ffill()
        skip = cfg.skip_recent
        scores_all = []
        for lb in cfg.lookbacks:
            # ret over [t-lb-skip, t-skip]
            base = prices.shift(skip)
            past = prices.shift(skip + lb)
            ret = (base / past) - 1.0
            # Cross-sectional z-score per row
            mu = ret.mean(axis=1)
            sd = ret.std(axis=1, ddof=0).replace(0.0, np.nan)
            z = ret.sub(mu, axis=0).div(sd, axis=0)
            scores_all.append(z)
        score = sum(scores_all) / len(scores_all)

        # Cross-section quantile -> {-1, 0, +1}
        out = pd.DataFrame(0, index=prices.index, columns=prices.columns, dtype=int)
        for ts, row in score.iterrows():
            valid = row.dropna()
            if len(valid) < cfg.min_assets:
                continue
            q_lo = valid.quantile(cfg.short_quantile)
            q_hi = valid.quantile(cfg.long_quantile)
            for c, v in valid.items():
                if v >= q_hi:
                    out.at[ts, c] = 1
                elif v <= q_lo:
                    out.at[ts, c] = -1
        return out
