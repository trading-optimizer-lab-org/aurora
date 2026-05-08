"""Crypto perpetual-futures funding-rate arbitrage signal.

When perpetual funding rate > +threshold (positive carry to shorts),
short the perp + long the spot to harvest funding (cash-and-carry).
Symmetric on the other side: funding < -threshold -> long perp + short spot.

Returns DataFrame with two legs per asset: f"{sym}_perp", f"{sym}_spot",
each in {-0.5, 0, +0.5} so net dollar gross is 1.0 per active asset.

Real exchange API integration is left as an injection point: pass a
DataFrame of funding rates [date x symbol] from any source. A stub
fetcher `fetch_funding_stub` returns mock rates for offline testing.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class CryptoFundingArbConfig:
    """Config. Threshold typically 0.01% per 8h => annualized ~10%."""
    funding_threshold: float = 0.0001  # 0.01% per funding interval
    smoothing: int = 3  # bars to confirm sustained funding


class CryptoFundingArbSignal:
    """Cash-and-carry signal on perp funding rates."""

    def __init__(self, config: CryptoFundingArbConfig | None = None):
        self.config = config or CryptoFundingArbConfig()
        if self.config.funding_threshold <= 0:
            raise ValueError("funding_threshold must be > 0")
        if self.config.smoothing < 1:
            raise ValueError("smoothing >= 1 required")

    @classmethod
    def fetch_funding_stub(
        cls,
        symbols: list[str],
        dates: pd.DatetimeIndex,
        seed: int = 42,
    ) -> pd.DataFrame:
        """Mock funding-rate panel for offline tests."""
        rng = np.random.default_rng(seed)
        data = rng.normal(loc=0.00005, scale=0.0002, size=(len(dates), len(symbols)))
        return pd.DataFrame(data, index=dates, columns=symbols)

    def signals(self, funding: pd.DataFrame) -> pd.DataFrame:
        """Convert funding panel into per-leg signals.

        Args:
            funding: DataFrame [date x symbol] of funding rates.

        Returns:
            DataFrame with two columns per symbol: {sym}_perp and {sym}_spot,
            values in {-0.5, 0, +0.5}.
        """
        if not isinstance(funding, pd.DataFrame):
            raise TypeError("funding must be pd.DataFrame")
        cfg = self.config
        sm = funding.rolling(cfg.smoothing, min_periods=1).mean()
        thr = cfg.funding_threshold
        cols = []
        legs = {}
        for sym in funding.columns:
            perp = pd.Series(0.0, index=funding.index)
            spot = pd.Series(0.0, index=funding.index)
            f = sm[sym]
            mask_pos = f > thr
            mask_neg = f < -thr
            # Positive funding: short perp, long spot
            perp[mask_pos] = -0.5
            spot[mask_pos] = 0.5
            # Negative funding: long perp, short spot
            perp[mask_neg] = 0.5
            spot[mask_neg] = -0.5
            cols.append(f"{sym}_perp")
            cols.append(f"{sym}_spot")
            legs[f"{sym}_perp"] = perp
            legs[f"{sym}_spot"] = spot
        return pd.DataFrame(legs, index=funding.index)[cols]
