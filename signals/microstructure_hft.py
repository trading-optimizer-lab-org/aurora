"""Microstructure / order-book imbalance signal.

Computes bid-ask volume imbalance from L2 snapshots:
  imbalance = (bid_qty - ask_qty) / (bid_qty + ask_qty)

Signal:
  imbalance > +threshold -> +1 (buying pressure)
  imbalance < -threshold -> -1 (selling pressure)
  else -> 0

When real L2 absent, mock_l2_book(n) generates plausible random snapshots
suitable for testing. Real-world plug-in expects pd.DataFrame with
['ts', 'bid_qty', 'ask_qty'] (or 'bid_size'/'ask_size' as aliases).
"""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class MicrostructureConfig:
    """Config."""
    threshold: float = 0.2
    smoothing: int = 5  # rolling mean window on imbalance series


class MicrostructureSignal:
    """L2 order-book imbalance signal.

    signals(book_df) -> pd.Series of {-1, 0, +1} indexed by ts.
    """

    def __init__(self, config: MicrostructureConfig | None = None):
        self.config = config or MicrostructureConfig()
        if not 0 < self.config.threshold < 1:
            raise ValueError("threshold must be in (0, 1)")
        if self.config.smoothing < 1:
            raise ValueError("smoothing must be >= 1")

    @staticmethod
    def _normalize_cols(book: pd.DataFrame) -> pd.DataFrame:
        df = book.copy()
        if "bid_qty" not in df.columns and "bid_size" in df.columns:
            df = df.rename(columns={"bid_size": "bid_qty"})
        if "ask_qty" not in df.columns and "ask_size" in df.columns:
            df = df.rename(columns={"ask_size": "ask_qty"})
        return df

    @classmethod
    def mock_l2_book(cls, n: int = 1000, seed: int = 42) -> pd.DataFrame:
        """Generate synthetic L2 snapshots for testing."""
        rng = np.random.default_rng(seed)
        ts = pd.date_range("2024-01-01 09:30", periods=n, freq="s")
        bid = rng.lognormal(mean=4.0, sigma=0.4, size=n)
        ask = rng.lognormal(mean=4.0, sigma=0.4, size=n)
        return pd.DataFrame({"ts": ts, "bid_qty": bid, "ask_qty": ask}).set_index("ts")

    def signals(self, book: pd.DataFrame) -> pd.Series:
        if not isinstance(book, pd.DataFrame):
            raise TypeError("book must be pd.DataFrame")
        df = self._normalize_cols(book)
        if not {"bid_qty", "ask_qty"}.issubset(df.columns):
            raise ValueError("book must have bid_qty and ask_qty (or bid_size/ask_size)")
        bid = df["bid_qty"].astype(float)
        ask = df["ask_qty"].astype(float)
        denom = (bid + ask).replace(0.0, np.nan)
        imb = (bid - ask) / denom
        sm = imb.rolling(self.config.smoothing, min_periods=1).mean()
        thr = self.config.threshold
        out = pd.Series(0, index=df.index, dtype=int)
        out[sm > thr] = 1
        out[sm < -thr] = -1
        return out
