"""Trade-by-trade microstructure analyzer.

Signs trade flow using the Lee-Ready algorithm (compare trade price to
prevailing midpoint; tick test as fallback) and tags each print as lit or
dark based on exchange code. Aggregates buy/sell volume and dollar volume.

Returned columns:
    timestamp, symbol, price, size, midpoint, aggressor_side,
    venue_type, signed_size, signed_dollar
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


# Off-exchange / TRF venue codes used by the SIP tape.
_DARK_VENUE_CODES = frozenset({"D", "FINRA", "TRF", "ADF", "Z"})


@dataclass
class MicrostructureConfig:
    """Static config.

    Attributes:
        midpoint_tolerance: relative tolerance around the midpoint inside
            which the print is treated as ambiguous and the tick test is
            applied instead of the price test.
        dark_venue_codes: override the default off-exchange venue set.
    """
    midpoint_tolerance: float = 1e-6
    dark_venue_codes: tuple[str, ...] = tuple(_DARK_VENUE_CODES)


class TradeMicrostructureAnalyzer:
    """Sign trade flow and tag lit vs dark venue per print."""

    _COLS = (
        "timestamp", "symbol", "price", "size", "midpoint",
        "aggressor_side", "venue_type", "signed_size", "signed_dollar",
    )

    def __init__(self, config: Optional[MicrostructureConfig] = None) -> None:
        self.config = config or MicrostructureConfig()
        self._dark = frozenset(self.config.dark_venue_codes)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def analyze(
        self,
        trades: pd.DataFrame,
        quotes: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Annotate ``trades`` with signed flow and venue type.

        ``trades`` must have columns ``timestamp, price, size`` and may have
        ``symbol`` and ``exchange``. ``quotes`` (optional) adds context for the
        Lee-Ready price test; without it we fall back to the tick test only.
        """
        if trades.empty:
            return pd.DataFrame(columns=list(self._COLS))
        df = trades.copy()
        if "symbol" not in df.columns:
            df["symbol"] = ""
        if "exchange" not in df.columns:
            df["exchange"] = ""
        df = df.sort_values("timestamp").reset_index(drop=True)
        df["midpoint"] = self._midpoint_series(df, quotes)
        df["aggressor_side"] = self._lee_ready(df)
        df["venue_type"] = np.where(
            df["exchange"].astype(str).isin(self._dark), "dark", "lit",
        )
        sign = np.where(df["aggressor_side"] == "buy", 1,
                        np.where(df["aggressor_side"] == "sell", -1, 0))
        df["signed_size"] = sign * df["size"].astype(float)
        df["signed_dollar"] = df["signed_size"] * df["price"].astype(float)
        return df[list(self._COLS)]

    def aggregate(self, signed: pd.DataFrame) -> dict:
        """Top-line metrics for an analyzed frame."""
        if signed.empty:
            return {
                "buy_volume": 0.0, "sell_volume": 0.0, "net_volume": 0.0,
                "buy_dollar": 0.0, "sell_dollar": 0.0, "net_dollar": 0.0,
                "lit_pct": 0.0, "dark_pct": 0.0,
            }
        buys = signed.loc[signed["aggressor_side"] == "buy"]
        sells = signed.loc[signed["aggressor_side"] == "sell"]
        total = signed["size"].sum()
        dark = signed.loc[signed["venue_type"] == "dark", "size"].sum()
        return {
            "buy_volume": float(buys["size"].sum()),
            "sell_volume": float(sells["size"].sum()),
            "net_volume": float(buys["size"].sum() - sells["size"].sum()),
            "buy_dollar": float((buys["price"] * buys["size"]).sum()),
            "sell_dollar": float((sells["price"] * sells["size"]).sum()),
            "net_dollar": float(signed["signed_dollar"].sum()),
            "lit_pct": float(1.0 - dark / total) if total else 0.0,
            "dark_pct": float(dark / total) if total else 0.0,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _midpoint_series(
        self, trades: pd.DataFrame, quotes: Optional[pd.DataFrame],
    ) -> pd.Series:
        if quotes is None or quotes.empty:
            # Use a rolling smoothed price as a midpoint proxy.
            return trades["price"].rolling(5, min_periods=1).mean()
        q = quotes[["timestamp", "bid", "ask"]].sort_values("timestamp").copy()
        q["midpoint"] = (q["bid"] + q["ask"]) / 2.0
        merged = pd.merge_asof(
            trades[["timestamp"]].sort_values("timestamp"),
            q[["timestamp", "midpoint"]],
            on="timestamp",
            direction="backward",
        )
        return merged["midpoint"].ffill().fillna(trades["price"])

    def _lee_ready(self, df: pd.DataFrame) -> pd.Series:
        tol = self.config.midpoint_tolerance
        diff = df["price"].astype(float) - df["midpoint"].astype(float)
        # Price test: above midpoint -> buy; below -> sell.
        side = np.where(diff > tol * df["midpoint"], "buy",
                        np.where(diff < -tol * df["midpoint"], "sell", ""))
        # Tick test for ambiguous prints.
        prev_price = df["price"].shift(1)
        tick = np.where(df["price"] > prev_price, "buy",
                        np.where(df["price"] < prev_price, "sell", "neutral"))
        side = np.where(side == "", tick, side)
        # First trade with no precedent -> neutral.
        return pd.Series(side, index=df.index, dtype=object)
