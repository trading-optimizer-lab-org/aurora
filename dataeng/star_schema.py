"""Star-schema warehouse for trades + market data.

Implements the classic fact-and-dimension model entirely in pandas. Designed
for analytical queries (sum / avg / count by dimension) rather than OLTP.

Dimensions:
  - ``dim_symbol``    (symbol_key, symbol)
  - ``dim_date``      (date_key, date, year, month, dow)

Facts:
  - ``fact_trades``   (trade_id, symbol_key, date_key, qty, price, side)
  - ``fact_market``   (symbol_key, date_key, open, high, low, close, volume)
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

import pandas as pd


@dataclass
class StarSchemaConfig:
    """Static config for :class:`StarSchemaWarehouse`.

    Attributes:
        date_format: format used to parse date strings.
    """
    date_format: str = "%Y-%m-%d"


_DIM_SYMBOL_COLS = ("symbol_key", "symbol")
_DIM_DATE_COLS = ("date_key", "date", "year", "month", "dow")
_FACT_TRADES_COLS = (
    "trade_id", "symbol_key", "date_key", "qty", "price", "side",
)
_FACT_MARKET_COLS = (
    "symbol_key", "date_key", "open", "high", "low", "close", "volume",
)


def _stable_key(value: str) -> int:
    """Stable 32-bit positive integer key for a string."""
    h = hashlib.sha1(value.encode("utf-8")).hexdigest()
    return int(h[:8], 16)


class StarSchemaWarehouse:
    """Fact / dimension store with pandas-backed tables."""

    def __init__(self, config: Optional[StarSchemaConfig] = None) -> None:
        self.config = config or StarSchemaConfig()
        self.dim_symbol = pd.DataFrame(columns=list(_DIM_SYMBOL_COLS))
        self.dim_date = pd.DataFrame(columns=list(_DIM_DATE_COLS))
        self.fact_trades = pd.DataFrame(columns=list(_FACT_TRADES_COLS))
        self.fact_market = pd.DataFrame(columns=list(_FACT_MARKET_COLS))

    # ------------------------------------------------------------------
    # Dimension upserts
    # ------------------------------------------------------------------
    def upsert_symbol(self, symbol: str) -> int:
        key = _stable_key(symbol)
        if not (self.dim_symbol["symbol_key"] == key).any():
            row = pd.DataFrame([[key, symbol]], columns=list(_DIM_SYMBOL_COLS))
            self.dim_symbol = pd.concat(
                [self.dim_symbol, row], ignore_index=True)
        return int(key)

    def upsert_date(self, date_str: str) -> int:
        ts = pd.Timestamp(date_str)
        key = int(ts.strftime("%Y%m%d"))
        if not (self.dim_date["date_key"] == key).any():
            row = pd.DataFrame(
                [[key, ts.date().isoformat(), int(ts.year), int(ts.month),
                  int(ts.dayofweek)]],
                columns=list(_DIM_DATE_COLS),
            )
            self.dim_date = pd.concat([self.dim_date, row], ignore_index=True)
        return key

    # ------------------------------------------------------------------
    # Fact loaders
    # ------------------------------------------------------------------
    def load_trades(self, trades: Iterable[dict]) -> int:
        rows = []
        for t in trades:
            sym_key = self.upsert_symbol(str(t["symbol"]))
            date_key = self.upsert_date(str(t["date"]))
            rows.append({
                "trade_id": str(t.get("trade_id", "")),
                "symbol_key": sym_key,
                "date_key": date_key,
                "qty": float(t["qty"]),
                "price": float(t["price"]),
                "side": str(t.get("side", "buy")),
            })
        if rows:
            self.fact_trades = pd.concat(
                [self.fact_trades, pd.DataFrame(rows)], ignore_index=True)
        return len(rows)

    def load_market(self, bars: Iterable[dict]) -> int:
        rows = []
        for b in bars:
            sym_key = self.upsert_symbol(str(b["symbol"]))
            date_key = self.upsert_date(str(b["date"]))
            rows.append({
                "symbol_key": sym_key,
                "date_key": date_key,
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": float(b.get("volume", 0.0)),
            })
        if rows:
            self.fact_market = pd.concat(
                [self.fact_market, pd.DataFrame(rows)], ignore_index=True)
        return len(rows)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def trades_by_symbol(self) -> pd.DataFrame:
        if self.fact_trades.empty:
            return pd.DataFrame(columns=["symbol", "n_trades", "qty_total"])
        joined = self.fact_trades.merge(
            self.dim_symbol, on="symbol_key", how="left")
        out = joined.groupby("symbol", as_index=False).agg(
            n_trades=("trade_id", "count"),
            qty_total=("qty", "sum"),
        )
        return out

    def daily_close(self) -> pd.DataFrame:
        if self.fact_market.empty:
            return pd.DataFrame(columns=["date", "symbol", "close"])
        joined = self.fact_market.merge(
            self.dim_symbol, on="symbol_key", how="left")
        joined = joined.merge(self.dim_date[["date_key", "date"]],
                              on="date_key", how="left")
        return joined[["date", "symbol", "close"]].sort_values(
            ["date", "symbol"]).reset_index(drop=True)

    def schema_summary(self) -> dict[str, int]:
        return {
            "dim_symbol": int(len(self.dim_symbol)),
            "dim_date": int(len(self.dim_date)),
            "fact_trades": int(len(self.fact_trades)),
            "fact_market": int(len(self.fact_market)),
        }
