"""Corporate actions adjuster.

Apply splits, cash dividends, and spinoffs to historical price/volume series
using back-adjusted CRSP-style factors. Adjustments are applied to the price
panel point-in-time so a bar's adjusted close at any timestamp reflects all
events on or before that timestamp.

Action schema:
    date (datetime), symbol (str), action_type ('split'|'dividend'|'spinoff'),
    factor (float)  # split: ratio (e.g. 2.0 for 2:1); dividend: cash amount;
                    # spinoff: parent share value retained ratio (0..1).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class CorporateActionsConfig:
    """Static config.

    Attributes:
        adjust_volume: when True, scale volume by inverse of split factor.
        round_decimals: decimal places for adjusted price rounding.
    """
    adjust_volume: bool = True
    round_decimals: int = 4


class CorporateActionsAdjuster:
    """Back-adjust price + volume series for splits / dividends / spinoffs."""

    _OUT_COLS = ("date", "symbol", "open", "high", "low", "close",
                 "adj_close", "volume", "adj_factor")

    def __init__(self, config: Optional[CorporateActionsConfig] = None) -> None:
        self.config = config or CorporateActionsConfig()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def adjust(
        self,
        prices: pd.DataFrame,
        actions: pd.DataFrame,
    ) -> pd.DataFrame:
        """Return ``prices`` with split/div/spinoff back-adjustment applied.

        ``prices`` must have columns ``date, symbol, open, high, low, close,
        volume``. Output adds ``adj_close`` and ``adj_factor``.
        """
        required = {"date", "symbol", "open", "high", "low", "close", "volume"}
        missing = required - set(prices.columns)
        if missing:
            raise ValueError(f"prices missing columns: {sorted(missing)}")
        if prices.empty:
            return pd.DataFrame(columns=list(self._OUT_COLS))
        df = prices.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
        df["adj_factor"] = 1.0
        if not actions.empty:
            for symbol, sub in df.groupby("symbol", sort=False):
                sym_actions = actions[actions["symbol"] == symbol].copy()
                if sym_actions.empty:
                    continue
                sym_actions["date"] = pd.to_datetime(sym_actions["date"])
                sym_actions = sym_actions.sort_values("date")
                factors = self._compute_back_factors(
                    sub["date"].to_numpy(),
                    sub["close"].astype(float).to_numpy(),
                    sym_actions,
                )
                df.loc[sub.index, "adj_factor"] = factors
        df["adj_close"] = (df["close"].astype(float) * df["adj_factor"]).round(
            self.config.round_decimals,
        )
        if self.config.adjust_volume:
            df["volume"] = (df["volume"].astype(float) / df["adj_factor"].replace(0, 1.0)).round()
        return df[list(self._OUT_COLS)].reset_index(drop=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _compute_back_factors(
        self,
        dates: np.ndarray,
        closes: np.ndarray,
        actions: pd.DataFrame,
    ) -> np.ndarray:
        """Compound the back-adjustment factor for each price row.

        Walks events in chronological order; each event multiplies the factor
        applied to all prior rows (i.e. dates strictly before the event date).
        """
        factor = np.ones_like(closes, dtype=float)
        dates_pd = pd.to_datetime(dates)
        for _, ev in actions.iterrows():
            ev_date = pd.Timestamp(ev["date"])
            ev_type = str(ev["action_type"])
            ev_factor = float(ev["factor"])
            mask = dates_pd < ev_date
            if not mask.any():
                continue
            if ev_type == "split":
                if ev_factor <= 0:
                    continue
                # 2:1 split -> divide pre-split prices by 2 (factor 1/2).
                factor[mask] *= 1.0 / ev_factor
            elif ev_type == "dividend":
                # Use price closest to (and before) the ex-date for the
                # proportional adjustment (CRSP standard).
                idx_before = np.where(mask)[0]
                ref_close = float(closes[idx_before[-1]]) if idx_before.size else 0.0
                if ref_close <= 0:
                    continue
                adj = max(0.0, 1.0 - ev_factor / ref_close)
                factor[mask] *= adj
            elif ev_type == "spinoff":
                # ``factor`` is the retained value ratio in (0, 1].
                ratio = max(min(float(ev_factor), 1.0), 1e-6)
                factor[mask] *= ratio
            else:
                continue
        return factor
