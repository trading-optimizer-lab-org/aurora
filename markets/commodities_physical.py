"""Physical commodities roll-yield analyzer.

Detects contango / backwardation regimes from a multi-contract futures curve
and computes the implied roll yield for the front-second spread.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class CommoditiesRollConfig:
    """Configuration for the roll analyzer.

    Attributes:
        symbols: which commodity codes to mock-generate (e.g. CL, GC).
        seed: mock-generator seed.
        n_contracts: contracts per symbol on the futures curve.
    """
    symbols: tuple[str, ...] = ("CL", "GC", "NG", "HG")
    seed: int = 19
    n_contracts: int = 6


class CommoditiesRollAnalyzer:
    """Compute roll yield + regime classification for a futures curve."""

    _CURVE_COLS = ("symbol", "contract_month", "price", "tenor_years")

    def __init__(self,
                 config: Optional[CommoditiesRollConfig] = None) -> None:
        self.config = config or CommoditiesRollConfig()

    def analyze(self, mock: bool = True) -> pd.DataFrame:
        if not mock:
            raise NotImplementedError("Live commodities feed not configured.")
        return self._mock_curve()

    def signals(self, curve: pd.DataFrame) -> pd.DataFrame:
        """Per-symbol regime + roll yield (% annualised front -> next).

        Regime: 'contango' if next > front, 'backwardation' if next < front.
        """
        if curve.empty:
            return pd.DataFrame(columns=["symbol", "regime", "roll_yield",
                                         "front_price", "next_price"])
        rows = []
        for sym, grp in curve.groupby("symbol"):
            g = grp.sort_values("tenor_years")
            if len(g) < 2:
                continue
            front = float(g["price"].iloc[0])
            nxt = float(g["price"].iloc[1])
            t_front = float(g["tenor_years"].iloc[0])
            t_next = float(g["tenor_years"].iloc[1])
            dt = max(t_next - t_front, 1e-9)
            # Roll yield (long): if backwardation (next < front), positive.
            roll = (front - nxt) / nxt / dt
            regime = ("contango" if nxt > front else
                      ("backwardation" if nxt < front else "flat"))
            rows.append({"symbol": sym, "regime": regime,
                         "roll_yield": float(roll),
                         "front_price": front, "next_price": nxt})
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Mock
    # ------------------------------------------------------------------
    def _mock_curve(self) -> pd.DataFrame:
        rng = np.random.default_rng(self.config.seed)
        rows = []
        # Mix contango (oil, gas) and backwardation (sometimes copper) to
        # exercise both regimes.
        bases = {"CL": 78.0, "GC": 2350.0, "NG": 2.8, "HG": 4.05}
        slopes = {"CL": 0.02, "GC": 0.005, "NG": 0.05, "HG": -0.01}
        for sym in self.config.symbols:
            base = bases.get(sym, 100.0)
            slope = slopes.get(sym, 0.01)
            for i in range(self.config.n_contracts):
                tenor = (i + 1) / 12.0
                px = base * (1 + slope * (i + 1)) + rng.normal(0, base * 0.001)
                rows.append({"symbol": sym,
                             "contract_month": f"M{i+1}",
                             "price": float(px),
                             "tenor_years": tenor})
        return pd.DataFrame(rows, columns=list(self._CURVE_COLS))
