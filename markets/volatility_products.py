"""VIX futures term structure + VXX/SVXY decay analytics.

Builds a mock VIX futures curve and estimates expected daily decay for
volatility ETPs based on the front-month / second-month roll.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class VolatilityProductsConfig:
    """Settings for VIX-product analytics.

    Attributes:
        spot_vix: VIX spot level used in mock curves.
        contango_slope: monthly contango slope as a fraction of front price.
        n_months: number of contracts on the term structure.
        seed: mock seed.
    """
    spot_vix: float = 16.5
    contango_slope: float = 0.04
    n_months: int = 7
    seed: int = 23


class VolatilityProductsTrader:
    """Term structure + decay analytics for VIX-linked products."""

    _CURVE_COLS = ("contract", "tenor_months", "price")

    def __init__(self,
                 config: Optional[VolatilityProductsConfig] = None) -> None:
        self.config = config or VolatilityProductsConfig()

    def analyze(self, mock: bool = True) -> pd.DataFrame:
        if not mock:
            raise NotImplementedError("Live VIX feed not configured.")
        return self._mock_curve()

    def signals(self, curve: pd.DataFrame) -> pd.DataFrame:
        """Compute VXX expected daily decay and SVXY expected daily gain.

        Approximation: VXX rolls from M1 to M2 each day. Daily roll cost is
        (M2 - M1) / M1 / business_days_per_month. SVXY is short -1x and so
        gains the inverse minus a fee buffer (ignored here).
        """
        if curve.empty:
            return pd.DataFrame(columns=["product", "daily_drift", "regime"])
        g = curve.sort_values("tenor_months")
        if len(g) < 2:
            return pd.DataFrame(columns=["product", "daily_drift", "regime"])
        m1 = float(g["price"].iloc[0])
        m2 = float(g["price"].iloc[1])
        bdays = 21.0
        # VXX daily roll cost (negative drift in contango, positive in backwardation).
        vxx_drift = -(m2 - m1) / m1 / bdays
        svxy_drift = -vxx_drift
        regime = ("contango" if m2 > m1 else
                  ("backwardation" if m2 < m1 else "flat"))
        return pd.DataFrame([
            {"product": "VXX", "daily_drift": float(vxx_drift),
             "regime": regime},
            {"product": "SVXY", "daily_drift": float(svxy_drift),
             "regime": regime},
        ])

    # ------------------------------------------------------------------
    # Mock
    # ------------------------------------------------------------------
    def _mock_curve(self) -> pd.DataFrame:
        rng = np.random.default_rng(self.config.seed)
        rows = []
        spot = self.config.spot_vix
        slope = self.config.contango_slope
        for i in range(self.config.n_months):
            tenor = (i + 1) / 12.0
            # Slight curvature: log-shaped
            px = spot * (1 + slope * np.log1p(i + 1))
            px += rng.normal(0, spot * 0.005)
            rows.append({"contract": f"VX{i+1}",
                         "tenor_months": i + 1, "price": float(px)})
        return pd.DataFrame(rows, columns=list(self._CURVE_COLS))
