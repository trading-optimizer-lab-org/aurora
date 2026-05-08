"""Credit market: CDS spreads, IG/HY index returns.

Generates mock CDX (US) and iTraxx (Europe) index spread series and provides
basic credit signals: spread z-score and IG vs HY divergence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class CreditConfig:
    """Mock + signals settings.

    Attributes:
        days: bars to generate.
        z_window: lookback window for spread z-score.
        seed: deterministic mock generator seed.
    """
    days: int = 252
    z_window: int = 60
    seed: int = 17


class CreditMarket:
    """Credit-index spread analytics."""

    _SPREAD_COLS = ("date", "index", "spread_bps", "total_return")
    _INDICES = (
        ("CDX_IG", 60.0, 0.10),  # name, base bps, vol
        ("CDX_HY", 360.0, 0.30),
        ("ITRAXX_MAIN", 65.0, 0.10),
        ("ITRAXX_XOVER", 320.0, 0.30),
    )

    def __init__(self, config: Optional[CreditConfig] = None) -> None:
        self.config = config or CreditConfig()

    def analyze(self, mock: bool = True) -> pd.DataFrame:
        if not mock:
            raise NotImplementedError("Live CDS feed not configured.")
        return self._mock_spreads()

    def signals(self, spreads: pd.DataFrame) -> pd.DataFrame:
        """Z-score of spread vs rolling window, plus IG/HY divergence flag."""
        if spreads.empty:
            return pd.DataFrame(columns=["index", "spread_bps", "z_score",
                                         "signal"])
        rows = []
        win = self.config.z_window
        for name, grp in spreads.groupby("index"):
            g = grp.sort_values("date")
            if len(g) < win:
                continue
            roll = g["spread_bps"].rolling(win)
            mu = roll.mean().iloc[-1]
            sd = roll.std().iloc[-1]
            if sd is None or np.isnan(sd) or sd == 0:
                z = 0.0
            else:
                z = (g["spread_bps"].iloc[-1] - mu) / sd
            # Signal: short credit (sell protection) when spreads are
            # extremely tight (z < -1.5), long credit when extremely wide
            # (z > 1.5).
            if z > 1.5:
                sig = 1
            elif z < -1.5:
                sig = -1
            else:
                sig = 0
            rows.append({"index": name,
                         "spread_bps": float(g["spread_bps"].iloc[-1]),
                         "z_score": float(z), "signal": sig})
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Mock
    # ------------------------------------------------------------------
    def _mock_spreads(self) -> pd.DataFrame:
        rng = np.random.default_rng(self.config.seed)
        dates = pd.date_range("2024-01-01", periods=self.config.days, freq="B")
        rows = []
        for name, base, vol in self._INDICES:
            shocks = rng.normal(0, vol * base / 100, size=len(dates))
            spread = base + shocks.cumsum()
            spread = np.clip(spread, base * 0.5, base * 2.0)
            # crude total return: -duration * d(spread). Use 4yr duration.
            d_spread = np.diff(spread, prepend=spread[0])
            tr = -4.0 * d_spread / 1e4
            for i, d in enumerate(dates):
                rows.append({"date": d, "index": name,
                             "spread_bps": float(spread[i]),
                             "total_return": float(tr[i])})
        return pd.DataFrame(rows, columns=list(self._SPREAD_COLS))
