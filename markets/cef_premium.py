"""Closed-end fund premium / discount z-score signals.

Unlike open-end ETFs, closed-end funds (CEFs) commonly trade at persistent
discounts or premia to NAV. Mean reversion in the CEF discount is a
well-documented signal source: this module computes a rolling z-score of the
discount and flags entries when the current discount is statistically wider
than its historical norm.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class CEFPremiumConfig:
    """Z-score window + signal thresholds.

    Attributes:
        cefs: tickers to mock.
        seed: mock generator seed.
        days: bars per fund.
        z_window: lookback window for discount z-score.
        z_entry: |z| above which to flag a signal.
    """
    cefs: tuple[str, ...] = ("PDI", "EOS", "BST", "UTF", "PCN")
    seed: int = 37
    days: int = 252
    z_window: int = 60
    z_entry: float = 2.0


class CEFPremiumDiscount:
    """Rolling discount z-score signals for CEFs."""

    _COLS = ("date", "cef", "price", "nav", "premium_pct")

    def __init__(self, config: Optional[CEFPremiumConfig] = None) -> None:
        self.config = config or CEFPremiumConfig()

    def analyze(self, mock: bool = True) -> pd.DataFrame:
        if not mock:
            raise NotImplementedError("Live CEF feed not configured.")
        return self._mock_history()

    def signals(self, history: pd.DataFrame) -> pd.DataFrame:
        """Per-CEF z-score of latest premium% vs rolling window.

        Signal: +1 = discount unusually deep, buy. -1 = premium unusually
        rich, sell. 0 = within normal range.
        """
        if history.empty:
            return pd.DataFrame(columns=["cef", "premium_pct", "z_score",
                                         "signal"])
        rows = []
        win = self.config.z_window
        for cef, grp in history.groupby("cef"):
            g = grp.sort_values("date")
            if len(g) < win:
                continue
            roll = g["premium_pct"].rolling(win)
            mu = roll.mean().iloc[-1]
            sd = roll.std().iloc[-1]
            current = float(g["premium_pct"].iloc[-1])
            if sd is None or np.isnan(sd) or sd == 0:
                z = 0.0
            else:
                z = (current - mu) / sd
            if z < -self.config.z_entry:
                sig = 1  # buy: discount wider than normal
            elif z > self.config.z_entry:
                sig = -1  # sell: premium richer than normal
            else:
                sig = 0
            rows.append({"cef": cef, "premium_pct": current,
                         "z_score": float(z), "signal": sig})
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Mock
    # ------------------------------------------------------------------
    def _mock_history(self) -> pd.DataFrame:
        rng = np.random.default_rng(self.config.seed)
        dates = pd.date_range("2024-01-01", periods=self.config.days, freq="B")
        rows = []
        # Each CEF has its own typical discount level.
        bias = {"PDI": 0.05, "EOS": -0.03, "BST": -0.05,
                "UTF": -0.04, "PCN": 0.02}
        for cef in self.config.cefs:
            mu_disc = bias.get(cef, -0.05)
            shocks = rng.normal(0, 0.005, size=len(dates))
            premium = mu_disc + shocks.cumsum() * 0.05
            # Force the last observation to a wide deviation so the test
            # data exercises the entry logic.
            premium[-1] = mu_disc - 0.10
            nav = 20.0 * (1 + rng.normal(0, 0.002, size=len(dates))).cumprod()
            price = nav * (1 + premium)
            for i, d in enumerate(dates):
                rows.append({"date": d, "cef": cef,
                             "price": float(price[i]),
                             "nav": float(nav[i]),
                             "premium_pct": float(premium[i])})
        return pd.DataFrame(rows, columns=list(self._COLS))
