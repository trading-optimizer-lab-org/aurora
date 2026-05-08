"""Continuous futures contract construction.

Builds a continuous price series from individual contract months by handling
roll dates with either ``ratio`` or ``back_adjusted`` methods.

Mock generator produces a 4-contract chain for one symbol so tests can verify
roll behaviour without external data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np
import pandas as pd

RollMethod = Literal["ratio", "back_adjusted", "none"]


@dataclass
class FuturesConfig:
    """Roll settings.

    Attributes:
        roll_method: 'ratio' multiplies the past series by new/old to splice;
            'back_adjusted' subtracts (new - old); 'none' just concatenates.
        roll_days_before_expiry: how many business days before expiry to roll.
        mock_contracts: how many quarterly contracts to generate.
    """
    roll_method: RollMethod = "ratio"
    roll_days_before_expiry: int = 5
    mock_contracts: int = 4
    seed: int = 11


class FuturesContinuous:
    """Continuous futures price builder."""

    _COLS = ("date", "symbol", "contract", "close", "continuous")

    def __init__(self, config: Optional[FuturesConfig] = None) -> None:
        self.config = config or FuturesConfig()

    def analyze(self, symbol: str = "CL", mock: bool = True) -> pd.DataFrame:
        """Return a DataFrame with raw + continuous prices."""
        if not mock:
            raise NotImplementedError("Live futures feed not configured.")
        chain = self._mock_chain(symbol)
        return self.build_continuous(chain)

    def build_continuous(self, chain: pd.DataFrame) -> pd.DataFrame:
        """Splice individual contracts into a continuous series.

        ``chain`` requires columns: date, symbol, contract, close, expiry.
        Each contract is the active "front month" for dates before its roll
        date (= expiry minus ``roll_days_before_expiry``).
        """
        required = {"date", "symbol", "contract", "close", "expiry"}
        missing = required - set(chain.columns)
        if missing:
            raise ValueError(f"chain missing columns: {missing}")
        if chain.empty:
            return pd.DataFrame(columns=list(self._COLS))

        df = chain.sort_values(["contract", "date"]).copy()
        contracts = sorted(df["contract"].unique(),
                           key=lambda c: df[df["contract"] == c]["expiry"].iloc[0])

        # Build active map: each date assigned to its front contract.
        offset = pd.tseries.offsets.BDay(self.config.roll_days_before_expiry)
        active_segments = []
        prev_roll = pd.Timestamp.min
        for c in contracts:
            sub = df[df["contract"] == c]
            expiry = pd.Timestamp(sub["expiry"].iloc[0])
            roll_date = expiry - offset
            seg = sub[(sub["date"] > prev_roll) & (sub["date"] <= roll_date)].copy()
            if not seg.empty:
                active_segments.append((c, seg, roll_date))
            prev_roll = roll_date

        if not active_segments:
            return pd.DataFrame(columns=list(self._COLS))

        # Adjust prior segments based on the roll method and the splice gap at
        # each roll date.
        adjusted = []
        cum_factor = 1.0
        cum_offset = 0.0
        # Walk segments backwards: most-recent contract is unadjusted; earlier
        # ones get scaled or shifted to remove the gap at the roll boundary.
        for i, (c, seg, roll_date) in enumerate(active_segments):
            seg = seg.copy()
            seg["continuous"] = seg["close"] * cum_factor + cum_offset
            adjusted.append(seg.assign(symbol=seg["symbol"], contract=c))
            # Compute splice gap to the next contract on the roll date.
            if i + 1 < len(active_segments):
                next_c, next_seg, _ = active_segments[i + 1]
                old_px_rows = seg[seg["date"] == roll_date]
                new_px_rows = next_seg[next_seg["date"] == roll_date]
                if not old_px_rows.empty and not new_px_rows.empty:
                    old_px = float(old_px_rows["close"].iloc[0])
                    new_px = float(new_px_rows["close"].iloc[0])
                    if self.config.roll_method == "ratio" and old_px != 0:
                        cum_factor *= old_px / new_px
                    elif self.config.roll_method == "back_adjusted":
                        cum_offset += old_px - new_px
        # Order so newest contract is last (as expected in time).
        out = pd.concat(adjusted).sort_values("date")
        return out[list(self._COLS)].reset_index(drop=True)

    def signals(self, continuous: pd.DataFrame) -> pd.DataFrame:
        """20/60 SMA cross signal on the continuous series."""
        if continuous.empty:
            return pd.DataFrame(columns=["symbol", "signal", "fast", "slow"])
        rows = []
        for sym, grp in continuous.groupby("symbol"):
            g = grp.sort_values("date")
            if len(g) < 60:
                continue
            fast = g["continuous"].rolling(20).mean().iloc[-1]
            slow = g["continuous"].rolling(60).mean().iloc[-1]
            sig = 1 if fast > slow else (-1 if fast < slow else 0)
            rows.append({"symbol": sym, "signal": sig,
                         "fast": float(fast), "slow": float(slow)})
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # Mock
    # ------------------------------------------------------------------
    def _mock_chain(self, symbol: str) -> pd.DataFrame:
        rng = np.random.default_rng(self.config.seed)
        rows = []
        # 4 quarterly contracts each with 90 business days of data ending at
        # expiry. Successive contracts trade in higher absolute prices to
        # exercise the splice logic.
        start = pd.Timestamp("2024-01-02")
        for i in range(self.config.mock_contracts):
            contract = f"{symbol}{i+1}"
            expiry = start + pd.tseries.offsets.BDay(60 + i * 30)
            dates = pd.date_range(end=expiry,
                                  periods=90, freq="B")
            base = 70.0 + i * 2.0  # contango-style step-up between contracts
            close = base + rng.normal(0, 0.5, size=len(dates)).cumsum()
            for d, px in zip(dates, close):
                rows.append({"date": d, "symbol": symbol,
                             "contract": contract, "close": float(px),
                             "expiry": expiry})
        return pd.DataFrame(rows)
