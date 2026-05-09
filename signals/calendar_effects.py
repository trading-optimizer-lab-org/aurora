"""Calendar-effects signal: turn-of-month, day-of-week, holiday-adjacent.

Configurable rule set — each rule is a function (ts: pd.Timestamp) -> int.
Combined output is the SUM of active rule signs, clipped to {-1, 0, +1}.

Defaults (US-equity flavor):
  - last 1 day + first 4 days of month -> +1 (turn-of-month effect)
  - Monday -> -1 (Monday-blues empirical)
  - Friday -> +1 (pre-weekend bid)

User can override via config.rules: list of callables.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd


def _turn_of_month(ts: pd.Timestamp, prev_eom: bool = True, post_n: int = 4) -> int:
    if not isinstance(ts, pd.Timestamp):
        return 0
    # Last business day of month (treated as +1)
    next_day = ts + pd.tseries.offsets.BDay(1)
    if prev_eom and next_day.month != ts.month:
        return 1
    # First post_n business days of month
    first_bday = ts.replace(day=1)
    if not (first_bday.weekday() < 5):
        first_bday = first_bday + pd.tseries.offsets.BDay(0)
    bdays = pd.bdate_range(first_bday, ts)
    if 1 <= len(bdays) <= post_n:
        return 1
    return 0


def _monday_blues(ts: pd.Timestamp) -> int:
    return -1 if ts.weekday() == 0 else 0


def _friday_lift(ts: pd.Timestamp) -> int:
    return 1 if ts.weekday() == 4 else 0


@dataclass
class CalendarEffectsConfig:
    """Config."""
    rules: list[Callable[[pd.Timestamp], int]] = field(
        default_factory=lambda: [_turn_of_month, _monday_blues, _friday_lift]
    )


class CalendarEffectsSignal:
    """Aggregate calendar-rule signal (clipped to {-1, 0, +1})."""

    DEFAULT_RULES = (_turn_of_month, _monday_blues, _friday_lift)

    def __init__(self, config: CalendarEffectsConfig | None = None):
        self.config = config or CalendarEffectsConfig()
        if not self.config.rules:
            raise ValueError("at least one rule required")

    def signals(self, dates: pd.DatetimeIndex) -> pd.Series:
        if not isinstance(dates, pd.DatetimeIndex):
            try:
                dates = pd.DatetimeIndex(dates)
            except Exception as e:
                raise TypeError("dates must be DatetimeIndex-compatible") from e
        out: np.ndarray = np.zeros(len(dates), dtype=int)
        for i, ts in enumerate(dates):
            s = 0
            for rule in self.config.rules:
                s += int(rule(ts))
            if s > 1:
                s = 1
            elif s < -1:
                s = -1
            out[i] = s
        return pd.Series(out, index=dates, dtype=int)
