"""ETF NAV vs market price arbitrage detector.

Identifies premium / discount conditions where an Authorised Participant
would profitably create or redeem creation units. Mocks a small ETF list with
NAV vs price drift.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class ETFArbitrageConfig:
    """Settings.

    Attributes:
        etfs: list of ETF tickers to mock.
        seed: mock seed.
        ap_cost_bps: round-trip AP transaction cost in basis points.
        threshold_bps: premium/discount threshold above which to flag arb.
    """
    etfs: tuple[str, ...] = ("SPY", "QQQ", "IWM", "EEM", "TLT", "GLD")
    seed: int = 31
    ap_cost_bps: float = 5.0
    threshold_bps: float = 10.0


class ETFArbitrageDetector:
    """Detect persistent price-NAV gaps."""

    _COLS = ("etf", "price", "nav", "premium_bps", "creation_units")

    def __init__(self, config: Optional[ETFArbitrageConfig] = None) -> None:
        self.config = config or ETFArbitrageConfig()

    def analyze(self, mock: bool = True) -> pd.DataFrame:
        if not mock:
            raise NotImplementedError("Live ETF NAV feed not configured.")
        return self._mock_nav()

    def signals(self, nav_data: pd.DataFrame) -> pd.DataFrame:
        """Flag arb opportunities net of AP cost.

        Signal:
          +1 = ETF trades above NAV beyond cost -> AP creates new units (sell ETF).
          -1 = ETF trades below NAV beyond cost -> AP redeems units (buy ETF).
        """
        if nav_data.empty:
            return pd.DataFrame(columns=["etf", "premium_bps", "edge_bps",
                                         "signal"])
        rows = []
        for _, r in nav_data.iterrows():
            premium_bps = float(r["premium_bps"])
            edge = abs(premium_bps) - self.config.ap_cost_bps
            if premium_bps > self.config.threshold_bps:
                signal = 1
            elif premium_bps < -self.config.threshold_bps:
                signal = -1
            else:
                signal = 0
            rows.append({"etf": r["etf"],
                         "premium_bps": premium_bps,
                         "edge_bps": float(edge),
                         "signal": signal})
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Mock
    # ------------------------------------------------------------------
    def _mock_nav(self) -> pd.DataFrame:
        rng = np.random.default_rng(self.config.seed)
        rows = []
        # Most ETFs trade close to NAV. Inject a couple of extreme premium /
        # discount cases to ensure signals fire.
        bases = {"SPY": 540.0, "QQQ": 460.0, "IWM": 215.0,
                 "EEM": 44.0, "TLT": 92.0, "GLD": 215.0}
        for i, etf in enumerate(self.config.etfs):
            base = bases.get(etf, 100.0)
            nav = base * (1 + rng.normal(0, 0.001))
            # Inject a +20bp premium on the first ETF and a -15bp discount
            # on the third, leave the rest near zero.
            if i == 0:
                price = nav * (1 + 0.0020)
            elif i == 2:
                price = nav * (1 - 0.0015)
            else:
                price = nav * (1 + rng.normal(0, 0.00015))
            premium_bps = (price / nav - 1.0) * 1e4
            rows.append({"etf": etf, "price": float(price),
                         "nav": float(nav),
                         "premium_bps": float(premium_bps),
                         "creation_units": 50000})
        return pd.DataFrame(rows, columns=list(self._COLS))
