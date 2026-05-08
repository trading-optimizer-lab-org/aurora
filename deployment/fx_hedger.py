"""FX forward hedger for foreign equity exposure.

Computes notional FX forward positions to neutralise the FX exposure of
foreign equity holdings. For each position with a non-base currency, we sell
foreign currency forward in the same notional as the equity position; the
output is a 1-row DataFrame whose entries are SIGNED forward notionals in
each FX pair (positive = buy base / sell foreign).

Forward pricing (covered interest parity, continuous compounding):
    F = S * exp((r_base - r_foreign) * T)

where ``S`` is the spot FX rate quoted as base/foreign units of base per unit
of foreign (so a USD-domiciled investor with EUR exposure uses S = USD/EUR).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

import math
import numpy as np
import pandas as pd


@dataclass
class FXHedgerConfig:
    """Configuration for :class:`FXHedger`."""
    base_currency: str = "USD"
    asset_currencies: dict = field(default_factory=dict)  # asset -> currency code
    spot_rates: dict = field(default_factory=dict)        # currency -> S (base per foreign)
    base_rate: float = 0.05                                # r_base (annual, cont.)
    foreign_rates: dict = field(default_factory=dict)     # currency -> r_foreign
    days_to_expiry: int = 30
    hedge_ratio: float = 1.0                              # 1.0 = full hedge


@dataclass
class FXHedgeResult:
    """Output of :meth:`FXHedger.allocate`."""
    weights: pd.DataFrame              # 1-row, columns = currencies (excl base)
    forward_rates: pd.Series           # currency -> implied forward F
    base_currency_notional: float      # net base exposure after hedging
    foreign_exposures: pd.Series       # gross per-currency foreign exposure


class FXHedger:
    """Forward-contract FX hedger.

    Args:
        config: :class:`FXHedgerConfig`. ``None`` -> defaults.
    """

    def __init__(self, config: Optional[FXHedgerConfig] = None):
        self.config = config or FXHedgerConfig()
        if not (0 <= self.config.hedge_ratio <= 1):
            raise ValueError("hedge_ratio must be in [0, 1]")
        if self.config.days_to_expiry <= 0:
            raise ValueError("days_to_expiry must be > 0")

    # --------------------------------------------------------------------- #
    def _forward_rate(self, currency: str) -> float:
        spot = float(self.config.spot_rates.get(currency, 1.0))
        r_for = float(self.config.foreign_rates.get(currency, 0.0))
        ttm = self.config.days_to_expiry / 365.0
        return spot * math.exp((self.config.base_rate - r_for) * ttm)

    # --------------------------------------------------------------------- #
    def allocate(
        self,
        positions: pd.Series,
    ) -> FXHedgeResult:
        """Compute FX forward hedges for the given equity positions.

        Args:
            positions: per-asset position notionals in BASE currency. Index
                values should be asset names matching
                ``config.asset_currencies``.
        """
        if not isinstance(positions, pd.Series):
            raise TypeError("positions must be a pd.Series")

        # 1. Aggregate per-currency exposures.
        per_ccy: dict[str, float] = {}
        for asset, notional in positions.items():
            ccy = self.config.asset_currencies.get(asset, self.config.base_currency)
            if ccy == self.config.base_currency:
                continue
            per_ccy[ccy] = per_ccy.get(ccy, 0.0) + float(notional)

        currencies = sorted(per_ccy.keys())
        forward_rates: dict[str, float] = {}
        hedges: dict[str, float] = {}
        for ccy in currencies:
            f = self._forward_rate(ccy)
            forward_rates[ccy] = f
            # Sell foreign forward in size -> negative forward notional in
            # foreign equals positive base notional retained when settled.
            # We report the SIGNED hedge: positive = buy base / sell foreign.
            hedges[ccy] = self.config.hedge_ratio * per_ccy[ccy]

        weights_df = pd.DataFrame(
            [pd.Series(hedges, index=currencies).values],
            index=["fx_hedge"],
            columns=currencies,
        )
        # Net base exposure after hedging foreign legs.
        gross_base = float(positions.sum())
        net_base = gross_base  # hedge fixes value, not the equity itself
        return FXHedgeResult(
            weights=weights_df,
            forward_rates=pd.Series(forward_rates),
            base_currency_notional=net_base,
            foreign_exposures=pd.Series(per_ccy),
        )
