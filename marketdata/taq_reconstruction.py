"""NYSE TAQ tick reconstruction.

Reconstruct tick-by-tick trade and quote data from NYSE TAQ format. Live
ingestion is out of scope; the module provides a deterministic mock generator
so downstream microstructure modules and tests can run offline.

Returned columns (trades):
    timestamp, symbol, price, size, exchange, sale_condition
Returned columns (quotes):
    timestamp, symbol, bid, ask, bid_size, ask_size, exchange
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class TAQConfig:
    """Static config.

    Attributes:
        n_ticks: number of synthetic ticks to emit per ``reconstruct`` call.
        base_price: anchor price for the random walk used in mock data.
        tick_volatility: per-tick standard deviation as a fraction of price.
        session_open_hour: trading session open in exchange local hours (UTC).
    """
    n_ticks: int = 1000
    base_price: float = 100.0
    tick_volatility: float = 0.0005
    session_open_hour: int = 14  # 09:30 ET roughly = 14:30 UTC


class TAQReconstructor:
    """Tick-by-tick reconstruction over a NYSE TAQ-style schema."""

    _TRADE_COLS = (
        "timestamp", "symbol", "price", "size", "exchange", "sale_condition",
    )
    _QUOTE_COLS = (
        "timestamp", "symbol", "bid", "ask", "bid_size", "ask_size", "exchange",
    )

    def __init__(self, config: Optional[TAQConfig] = None) -> None:
        self.config = config or TAQConfig()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def reconstruct(
        self,
        symbol: str,
        as_of: Optional[datetime] = None,
        mock: bool = True,
    ) -> dict[str, pd.DataFrame]:
        """Return ``{"trades": df, "quotes": df}`` for ``symbol`` on ``as_of``."""
        as_of = as_of or datetime.now(timezone.utc)
        if not mock:  # pragma: no cover - live feed out of scope
            raise NotImplementedError("Live TAQ ingest not wired in this build")
        return {
            "trades": self._mock_trades(symbol, as_of),
            "quotes": self._mock_quotes(symbol, as_of),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _mock_trades(self, symbol: str, as_of: datetime) -> pd.DataFrame:
        rng = np.random.default_rng(
            abs(hash(("taq_t", symbol, as_of.date().toordinal()))) % (2**32)
        )
        n = self.config.n_ticks
        steps = rng.normal(0.0, self.config.tick_volatility, size=n)
        prices = self.config.base_price * np.exp(np.cumsum(steps))
        sizes = rng.integers(100, 5000, size=n)
        ts0 = pd.Timestamp(as_of.date()).tz_localize("UTC") + pd.Timedelta(
            hours=self.config.session_open_hour, minutes=30,
        )
        ts = ts0 + pd.to_timedelta(np.cumsum(rng.uniform(0.05, 1.5, size=n)), "s")
        exchanges = rng.choice(["N", "Q", "T", "P"], size=n)
        # Sale conditions: '@' regular, 'F' intermarket sweep, '4' derivative.
        conditions = rng.choice(["@", "F", "4"], size=n, p=[0.85, 0.10, 0.05])
        return pd.DataFrame({
            "timestamp": ts,
            "symbol": symbol.upper(),
            "price": np.round(prices, 4),
            "size": sizes.astype(int),
            "exchange": exchanges,
            "sale_condition": conditions,
        })[list(self._TRADE_COLS)]

    def _mock_quotes(self, symbol: str, as_of: datetime) -> pd.DataFrame:
        rng = np.random.default_rng(
            abs(hash(("taq_q", symbol, as_of.date().toordinal()))) % (2**32)
        )
        n = self.config.n_ticks
        mid = self.config.base_price * np.exp(np.cumsum(
            rng.normal(0.0, self.config.tick_volatility, size=n)
        ))
        spread = np.maximum(0.01, np.abs(rng.normal(0.02, 0.01, size=n)))
        bids = mid - spread / 2.0
        asks = mid + spread / 2.0
        ts0 = pd.Timestamp(as_of.date()).tz_localize("UTC") + pd.Timedelta(
            hours=self.config.session_open_hour, minutes=30,
        )
        ts = ts0 + pd.to_timedelta(np.cumsum(rng.uniform(0.05, 1.5, size=n)), "s")
        return pd.DataFrame({
            "timestamp": ts,
            "symbol": symbol.upper(),
            "bid": np.round(bids, 4),
            "ask": np.round(asks, 4),
            "bid_size": rng.integers(1, 50, size=n).astype(int) * 100,
            "ask_size": rng.integers(1, 50, size=n).astype(int) * 100,
            "exchange": rng.choice(["N", "Q", "T", "P"], size=n),
        })[list(self._QUOTE_COLS)]
