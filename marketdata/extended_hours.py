"""Extended-hours bar builder.

Aggregates trades into pre-market (04:00-09:30 ET) and after-hours
(16:00-20:00 ET) bars. Regular market session (09:30-16:00 ET) is excluded
since standard intraday adapters already cover it.

Returned columns (per bar):
    bar_start, bar_end, symbol, session, open, high, low, close, volume, vwap
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd


# Sessions are expressed in UTC. ET is UTC-5 (UTC-4 during DST). We keep the
# math UTC-relative; a DST aware mode is out of scope for this build.
@dataclass
class ExtendedHoursConfig:
    """Static config.

    Attributes:
        bar_minutes: bar interval in minutes.
        premarket_open_utc: pre-market session open (UTC hour, decimal).
        premarket_close_utc: pre-market session close (UTC hour, decimal).
        afterhours_open_utc: after-hours session open (UTC hour, decimal).
        afterhours_close_utc: after-hours session close (UTC hour, decimal).
    """
    bar_minutes: int = 30
    premarket_open_utc: float = 9.0   # 04:00 ET
    premarket_close_utc: float = 14.5  # 09:30 ET
    afterhours_open_utc: float = 21.0  # 16:00 ET
    afterhours_close_utc: float = 25.0  # 20:00 ET (next-day 01:00 UTC)


class ExtendedHoursBars:
    """Build pre-market + after-hours bars from a tick frame."""

    _COLS = ("bar_start", "bar_end", "symbol", "session",
             "open", "high", "low", "close", "volume", "vwap")

    def __init__(self, config: Optional[ExtendedHoursConfig] = None) -> None:
        self.config = config or ExtendedHoursConfig()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def build(self, trades: pd.DataFrame) -> pd.DataFrame:
        """Aggregate ``trades`` into pre-market + after-hours OHLCV bars."""
        if trades.empty:
            return pd.DataFrame(columns=list(self._COLS))
        df = trades.copy()
        if "symbol" not in df.columns:
            df["symbol"] = ""
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df["session"] = df["timestamp"].apply(self._session_for)
        df = df[df["session"] != "regular"].reset_index(drop=True)
        if df.empty:
            return pd.DataFrame(columns=list(self._COLS))
        df["bar_start"] = df["timestamp"].dt.floor(f"{self.config.bar_minutes}min")
        df["dollar"] = df["price"].astype(float) * df["size"].astype(float)
        grouped = df.groupby(["symbol", "session", "bar_start"], sort=True)
        agg = grouped.agg(
            open=("price", "first"),
            high=("price", "max"),
            low=("price", "min"),
            close=("price", "last"),
            volume=("size", "sum"),
            dollar=("dollar", "sum"),
        ).reset_index()
        agg["vwap"] = agg["dollar"] / agg["volume"].clip(lower=1)
        agg["bar_end"] = agg["bar_start"] + pd.Timedelta(minutes=self.config.bar_minutes)
        return agg[list(self._COLS)].reset_index(drop=True)

    def get_session_volume(self, trades: pd.DataFrame) -> dict:
        """Total volume per session label."""
        if trades.empty:
            return {"premarket": 0.0, "afterhours": 0.0, "regular": 0.0}
        df = trades.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df["session"] = df["timestamp"].apply(self._session_for)
        out = df.groupby("session")["size"].sum().to_dict()
        return {k: float(out.get(k, 0.0)) for k in ("premarket", "afterhours", "regular")}

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _session_for(self, ts: pd.Timestamp) -> str:
        cfg = self.config
        # Convert UTC hour-of-day, allowing the after-hours window to wrap
        # past midnight via a >24 hour cutoff.
        h = ts.hour + ts.minute / 60.0 + ts.second / 3600.0
        # Wrapped after-hours: if close time > 24, also accept the small
        # next-day window from 0 to (close - 24).
        ah_close = cfg.afterhours_close_utc
        in_afterhours = (cfg.afterhours_open_utc <= h < min(ah_close, 24.0)) or (
            ah_close > 24.0 and h < (ah_close - 24.0)
        )
        if cfg.premarket_open_utc <= h < cfg.premarket_close_utc:
            return "premarket"
        if in_afterhours:
            return "afterhours"
        return "regular"
