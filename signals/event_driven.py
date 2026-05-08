"""Event-driven signal: pre-event drift / post-event reversion.

Inputs:
  prices: pd.DataFrame [date x ticker]
  events: pd.DataFrame with cols [date, ticker, event_type] (earnings, M&A, split)

Behavior:
  - pre_window days BEFORE event_date -> +1 (drift up)
  - post_window days AFTER event_date  -> -1 (post-event reversion / fade)
  - else 0
"""
from __future__ import annotations
from dataclasses import dataclass

import pandas as pd


@dataclass
class EventDrivenConfig:
    """Config."""
    pre_window: int = 5
    post_window: int = 3
    pre_sign: int = 1   # +1 long pre-event drift
    post_sign: int = -1  # -1 fade post-event
    event_types: tuple[str, ...] = ("earnings", "ma", "split")


class EventDrivenSignal:
    """Discrete event-window signal.

    signals(prices, events) -> pd.DataFrame of int weights.
    """

    def __init__(self, config: EventDrivenConfig | None = None):
        self.config = config or EventDrivenConfig()
        if self.config.pre_window < 0 or self.config.post_window < 0:
            raise ValueError("windows must be >= 0")

    def signals(self, prices: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
        if not isinstance(prices, pd.DataFrame):
            raise TypeError("prices must be pd.DataFrame")
        if not isinstance(events, pd.DataFrame):
            raise TypeError("events must be pd.DataFrame")
        req = {"date", "ticker", "event_type"}
        if not req.issubset(events.columns):
            raise ValueError(f"events missing cols: need {req}")
        cfg = self.config
        out = pd.DataFrame(0, index=prices.index, columns=prices.columns, dtype=int)
        evs = events.copy()
        evs["date"] = pd.to_datetime(evs["date"])
        # Filter recognized event types
        evs = evs[evs["event_type"].isin(cfg.event_types)]
        if evs.empty:
            return out
        for _, ev in evs.iterrows():
            tkr = ev["ticker"]
            if tkr not in out.columns:
                continue
            d = ev["date"]
            # Find the bar at-or-before d
            try:
                pos = out.index.get_indexer([d], method="pad")[0]
            except Exception:
                continue
            if pos < 0:
                continue
            n = len(out.index)
            # pre-window: bars [pos - pre_window, pos)
            for k in range(1, cfg.pre_window + 1):
                p = pos - k
                if 0 <= p < n:
                    out.iat[p, out.columns.get_loc(tkr)] = cfg.pre_sign
            # post-window: bars (pos, pos + post_window]
            for k in range(1, cfg.post_window + 1):
                p = pos + k
                if 0 <= p < n:
                    out.iat[p, out.columns.get_loc(tkr)] = cfg.post_sign
        return out
