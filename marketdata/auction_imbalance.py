"""Open and close auction imbalance tracker.

Models the NYSE/NASDAQ imbalance feed prior to opening/closing auctions.
Provides a deterministic mock generator so tests can verify the imbalance
direction signal without a live exchange feed.

Returned columns:
    timestamp, symbol, auction_type, paired_volume, imbalance_volume,
    imbalance_side, indicative_price, reference_price
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class AuctionConfig:
    """Static config.

    Attributes:
        update_interval_seconds: how often the imbalance feed publishes.
        n_updates: total number of feed messages emitted by the mock.
        base_price: anchor price used by the mock generator.
    """
    update_interval_seconds: int = 30
    n_updates: int = 20
    base_price: float = 100.0


class AuctionImbalanceTracker:
    """Track imbalance updates leading into the open / close auction."""

    _COLS = (
        "timestamp", "symbol", "auction_type", "paired_volume",
        "imbalance_volume", "imbalance_side", "indicative_price",
        "reference_price",
    )

    def __init__(self, config: Optional[AuctionConfig] = None) -> None:
        self.config = config or AuctionConfig()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def get_imbalance_feed(
        self,
        symbol: str,
        auction_type: str = "close",
        as_of: Optional[datetime] = None,
        mock: bool = True,
    ) -> pd.DataFrame:
        """Return the imbalance update stream for ``symbol``.

        ``auction_type`` must be ``"open"`` or ``"close"``.
        """
        if auction_type not in ("open", "close"):
            raise ValueError("auction_type must be 'open' or 'close'")
        as_of = as_of or datetime.now(timezone.utc)
        if not mock:  # pragma: no cover - live feed out of scope
            raise NotImplementedError("Live imbalance feed not wired in this build")
        return self._mock_feed(symbol, auction_type, as_of)

    def latest_signal(self, feed: pd.DataFrame) -> dict:
        """Latest imbalance reading summarized as a directional signal."""
        if feed.empty:
            return {"side": "none", "imbalance_volume": 0.0,
                    "indicative_premium_bps": 0.0}
        last = feed.sort_values("timestamp").iloc[-1]
        ref = float(last["reference_price"])
        ind = float(last["indicative_price"])
        premium = (ind - ref) / ref * 1e4 if ref else 0.0
        return {
            "side": str(last["imbalance_side"]),
            "imbalance_volume": float(last["imbalance_volume"]),
            "indicative_premium_bps": float(premium),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _mock_feed(
        self, symbol: str, auction_type: str, as_of: datetime,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(
            abs(hash(("auction", symbol, auction_type,
                      as_of.date().toordinal()))) % (2**32)
        )
        n = self.config.n_updates
        # Open auction publishes pre-market 09:00-09:30 ET (~13:00-13:30 UTC).
        # Close auction publishes 15:50-16:00 ET (~19:50-20:00 UTC).
        if auction_type == "open":
            base_ts = pd.Timestamp(as_of.date()).tz_localize("UTC") + pd.Timedelta(hours=13)
        else:
            base_ts = pd.Timestamp(as_of.date()).tz_localize("UTC") + pd.Timedelta(hours=19, minutes=50)
        ts = [base_ts + pd.Timedelta(seconds=self.config.update_interval_seconds * i)
              for i in range(n)]
        # Paired volume grows toward auction; imbalance shrinks but persists.
        paired = np.linspace(50_000, 500_000, n) + rng.normal(0, 5000, size=n)
        imbalance = rng.integers(10_000, 100_000, size=n)
        side = np.where(rng.random(size=n) < 0.55, "buy", "sell")
        ref_price = self.config.base_price * (1 + rng.normal(0, 0.001, size=n).cumsum())
        # Buy imbalance pushes indicative price up; sell pushes it down.
        offset = (np.where(side == "buy", 1.0, -1.0)
                  * (imbalance / 1_000_000.0) * ref_price)
        ind_price = ref_price + offset
        return pd.DataFrame({
            "timestamp": ts,
            "symbol": symbol.upper(),
            "auction_type": auction_type,
            "paired_volume": paired.astype(float),
            "imbalance_volume": imbalance.astype(float),
            "imbalance_side": side,
            "indicative_price": np.round(ind_price, 4),
            "reference_price": np.round(ref_price, 4),
        })[list(self._COLS)]
