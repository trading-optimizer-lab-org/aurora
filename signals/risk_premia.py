"""Risk-premia harvester.

Composite cross-sectional signal across the classic factors:
  - Carry        (yield / dividend / forward roll)
  - Value        (book/price, earnings/price, mean-reversion)
  - Low-vol      (inverse realized vol)
  - Momentum     (12-1 return)
  - Quality      (ROE proxy or stable returns)

User supplies a fundamentals DataFrame plus prices. Per-asset z-scores
are averaged with configurable weights, then ranked cross-section into
{-1, 0, +1} via top/bottom quantiles.

Designed to be data-tolerant: missing factor columns are skipped. No
external dependencies beyond numpy/pandas.
"""
from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class RiskPremiaConfig:
    """Config. weights override defaults; missing factors auto-omitted."""
    weights: dict[str, float] = field(default_factory=lambda: {
        "carry": 1.0, "value": 1.0, "low_vol": 1.0,
        "momentum": 1.0, "quality": 1.0,
    })
    momentum_lookback: int = 252
    momentum_skip: int = 21
    vol_lookback: int = 60
    long_quantile: float = 0.7
    short_quantile: float = 0.3


class RiskPremiaHarvester:
    """Composite multi-factor signal."""

    def __init__(self, config: RiskPremiaConfig | None = None):
        self.config = config or RiskPremiaConfig()
        if not 0 < self.config.short_quantile < self.config.long_quantile < 1:
            raise ValueError("require 0 < short_q < long_q < 1")

    @staticmethod
    def _xs_zscore(df: pd.DataFrame) -> pd.DataFrame:
        mu = df.mean(axis=1)
        sd = df.std(axis=1, ddof=0).replace(0.0, np.nan)
        return df.sub(mu, axis=0).div(sd, axis=0)

    def _compute_factor_scores(
        self,
        prices: pd.DataFrame,
        fundamentals: dict[str, pd.DataFrame],
    ) -> dict[str, pd.DataFrame]:
        cfg = self.config
        scores: dict[str, pd.DataFrame] = {}
        # Momentum: 12-1 (skip recent)
        mom = prices.shift(cfg.momentum_skip).pct_change(
            periods=cfg.momentum_lookback - cfg.momentum_skip
        )
        scores["momentum"] = self._xs_zscore(mom)
        # Low vol: inverse realized vol -> higher score = lower vol
        rets = prices.pct_change()
        vol = rets.rolling(cfg.vol_lookback, min_periods=cfg.vol_lookback // 2).std(ddof=0)
        inv_vol = 1.0 / vol.replace(0.0, np.nan)
        scores["low_vol"] = self._xs_zscore(inv_vol)
        # Carry: dividend yield (or yield) panel passed in
        if "carry" in fundamentals:
            scores["carry"] = self._xs_zscore(fundamentals["carry"].reindex_like(prices).ffill())
        # Value: book/price
        if "value" in fundamentals:
            scores["value"] = self._xs_zscore(fundamentals["value"].reindex_like(prices).ffill())
        # Quality
        if "quality" in fundamentals:
            scores["quality"] = self._xs_zscore(fundamentals["quality"].reindex_like(prices).ffill())
        return scores

    def signals(
        self,
        prices: pd.DataFrame,
        fundamentals: dict[str, pd.DataFrame] | None = None,
    ) -> pd.DataFrame:
        """Composite factor signal.

        Args:
            prices: panel of close prices (date x ticker).
            fundamentals: optional dict of factor->panel. Recognized:
                'carry', 'value', 'quality'. Each shape compatible with prices.

        Returns:
            DataFrame {-1, 0, +1} per (date, ticker).
        """
        if not isinstance(prices, pd.DataFrame):
            raise TypeError("prices must be pd.DataFrame")
        cfg = self.config
        funds = fundamentals or {}
        scores = self._compute_factor_scores(prices, funds)

        composite = None
        total_w = 0.0
        for name, df in scores.items():
            w = float(cfg.weights.get(name, 0.0))
            if w == 0:
                continue
            if composite is None:
                composite = df * w
            else:
                composite = composite.add(df * w, fill_value=0.0)
            total_w += abs(w)
        if composite is None or total_w == 0:
            return pd.DataFrame(0, index=prices.index, columns=prices.columns, dtype=int)
        composite = composite / total_w

        out = pd.DataFrame(0, index=prices.index, columns=prices.columns, dtype=int)
        for ts, row in composite.iterrows():
            valid = row.dropna()
            if len(valid) < 2:
                continue
            q_lo = valid.quantile(cfg.short_quantile)
            q_hi = valid.quantile(cfg.long_quantile)
            for c, v in valid.items():
                if v >= q_hi:
                    out.at[ts, c] = 1
                elif v <= q_lo:
                    out.at[ts, c] = -1
        return out
