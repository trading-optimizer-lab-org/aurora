"""Hierarchical Risk Parity within sector buckets.

Two-level HRP:
1. Group assets by GICS sector via a user-provided lookup.
2. Run HRP within each sector to get intra-sector weights.
3. Run HRP across sector portfolios (treating each sector as one synthetic
   asset) to get sector weights.
4. Final asset weight = sector_weight * intra_sector_weight, sums to 1.

Singleton sectors (one asset) get sector_intra_weight = 1.0 trivially.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from aurora.deployment.hrp import hrp_allocate


@dataclass
class SectorHRPConfig:
    """Configuration for :class:`SectorHRP`."""
    sector_lookup: dict = field(default_factory=dict)  # asset -> sector
    linkage_method: str = "single"
    cov_estimator: str = "sample"
    fallback_sector: str = "OTHER"


@dataclass
class SectorHRPResult:
    """Output of :meth:`SectorHRP.allocate`."""
    weights: pd.DataFrame             # 1-row DataFrame, columns = assets
    sector_weights: pd.Series         # weights at the sector level
    intra_sector_weights: dict        # sector -> pd.Series of intra weights


class SectorHRP:
    """Hierarchical Risk Parity within sector buckets.

    Args:
        config: :class:`SectorHRPConfig`. ``sector_lookup`` maps each asset
            name to a sector string; missing assets fall into
            ``fallback_sector``.
    """

    def __init__(self, config: Optional[SectorHRPConfig] = None):
        self.config = config or SectorHRPConfig()

    # --------------------------------------------------------------------- #
    def _bucket_assets(self, assets: list) -> dict:
        """Group asset names by sector."""
        buckets: dict = {}
        for a in assets:
            sec = self.config.sector_lookup.get(a, self.config.fallback_sector)
            buckets.setdefault(sec, []).append(a)
        return buckets

    # --------------------------------------------------------------------- #
    def allocate(self, prices: pd.DataFrame) -> SectorHRPResult:
        """Compute sector-level + intra-sector HRP weights."""
        if not isinstance(prices, pd.DataFrame):
            raise TypeError("prices must be a pd.DataFrame")
        if prices.shape[1] < 2:
            raise ValueError(f"need >= 2 assets, got {prices.shape[1]}")
        rets = prices.pct_change().dropna()
        if len(rets) < 2:
            raise ValueError("insufficient returns history")

        assets = list(prices.columns)
        buckets = self._bucket_assets(assets)

        # 1. Intra-sector HRP (or trivial weight for singletons).
        intra: dict[str, pd.Series] = {}
        sector_returns = {}
        for sec, members in buckets.items():
            sec_rets = rets[members]
            if len(members) == 1:
                intra[sec] = pd.Series(1.0, index=members)
                sector_returns[sec] = sec_rets.iloc[:, 0]
            else:
                # HRP requires at least 2 unique columns and observations.
                try:
                    res = hrp_allocate(
                        sec_rets,
                        linkage_method=self.config.linkage_method,
                        cov_estimator=self.config.cov_estimator,
                    )
                    w_intra = res.weights.reindex(members).fillna(0.0)
                except Exception:
                    # Degenerate sector: equal-weight inside.
                    w_intra = pd.Series(1.0 / len(members), index=members)
                intra[sec] = w_intra
                sector_returns[sec] = (sec_rets * w_intra).sum(axis=1)

        # 2. Cross-sector HRP on synthetic sector returns.
        sector_names = list(buckets.keys())
        if len(sector_names) == 1:
            sector_w = pd.Series(1.0, index=sector_names)
        else:
            sec_rets_df = pd.DataFrame(sector_returns)
            try:
                top = hrp_allocate(
                    sec_rets_df,
                    linkage_method=self.config.linkage_method,
                    cov_estimator=self.config.cov_estimator,
                )
                sector_w = top.weights.reindex(sector_names).fillna(0.0)
            except Exception:
                sector_w = pd.Series(1.0 / len(sector_names), index=sector_names)

        # 3. Combine: final[i] = sector_w[sec(i)] * intra[sec(i)][i]
        final = pd.Series(0.0, index=assets)
        for sec, members in buckets.items():
            sw = float(sector_w.loc[sec])
            for a in members:
                final[a] = sw * float(intra[sec].loc[a])

        # Renormalize defensively.
        s = final.sum()
        if s > 0:
            final = final / s

        weights_df = pd.DataFrame([final.values], index=["sector_hrp"],
                                  columns=assets)
        return SectorHRPResult(
            weights=weights_df,
            sector_weights=sector_w,
            intra_sector_weights=intra,
        )
