"""Block trade detector.

Flags individual prints as block trades when they exceed the size or notional
thresholds set by the SEC and exchanges. Default thresholds: > 10,000 shares
OR > $200,000 notional.

Returned columns:
    timestamp, symbol, price, size, notional, is_block, block_reason
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class BlockTradeConfig:
    """Static config.

    Attributes:
        min_shares: lower bound (inclusive) on share count to qualify as block.
        min_notional: lower bound (inclusive) on dollar notional to qualify.
        require_both: when True only flag prints meeting both thresholds.
    """
    min_shares: int = 10_000
    min_notional: float = 200_000.0
    require_both: bool = False


class BlockTradeDetector:
    """Flag individual prints as block trades."""

    _COLS = ("timestamp", "symbol", "price", "size",
             "notional", "is_block", "block_reason")

    def __init__(self, config: Optional[BlockTradeConfig] = None) -> None:
        self.config = config or BlockTradeConfig()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def detect(self, trades: pd.DataFrame) -> pd.DataFrame:
        """Annotate ``trades`` with ``notional``, ``is_block``, ``block_reason``."""
        if trades.empty:
            return pd.DataFrame(columns=list(self._COLS))
        df = trades.copy()
        if "symbol" not in df.columns:
            df["symbol"] = ""
        df["notional"] = df["price"].astype(float) * df["size"].astype(float)
        size_hit = df["size"].astype(float) >= self.config.min_shares
        not_hit = df["notional"] >= self.config.min_notional
        if self.config.require_both:
            df["is_block"] = size_hit & not_hit
        else:
            df["is_block"] = size_hit | not_hit
        df["block_reason"] = np.where(
            ~df["is_block"], "",
            np.where(size_hit & not_hit, "size+notional",
                     np.where(size_hit, "size", "notional")),
        )
        return df[list(self._COLS)].reset_index(drop=True)

    def get_blocks(self, trades: pd.DataFrame) -> pd.DataFrame:
        """Subset of ``trades`` flagged as blocks, sorted by notional desc."""
        annotated = self.detect(trades)
        blocks = annotated[annotated["is_block"]].copy()
        return blocks.sort_values("notional", ascending=False).reset_index(drop=True)

    def block_stats(self, trades: pd.DataFrame) -> dict:
        """Aggregate volume / notional and block share."""
        annotated = self.detect(trades)
        if annotated.empty:
            return {"n_blocks": 0, "block_volume": 0.0,
                    "block_notional": 0.0, "block_share_volume": 0.0}
        blocks = annotated.loc[annotated["is_block"]]
        total_vol = float(annotated["size"].sum())
        return {
            "n_blocks": int(len(blocks)),
            "block_volume": float(blocks["size"].sum()),
            "block_notional": float(blocks["notional"].sum()),
            "block_share_volume": float(blocks["size"].sum() / total_vol)
            if total_vol > 0 else 0.0,
        }
