"""Per-strategy custom session times (R96).

Allow strategies to declare an active trading window so the live
wrapper does not fire orders outside it. Honours per-exchange tz via
``core.timezone`` (R45).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import List, Optional

import pandas as pd

from quantforge.core.timezone import tz_for_exchange


@dataclass(frozen=True)
class SessionWindow:
    """A daily trading window specific to one strategy.

    Attributes:
        start: local-time start of the window (HH:MM).
        end: local-time end of the window. Same-day only; cross-midnight
            windows must be expressed as two separate entries.
        weekdays: tuple of weekday ints (0=Monday, 6=Sunday) the window
            applies to. Default: weekdays only (0..4).
        exchange: canonical exchange code; resolved through
            ``core.timezone`` to the IANA tz.
    """

    start: time
    end: time
    exchange: str = "NYSE"
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError(
                "end must be after start (cross-midnight windows are not "
                "supported; split into two SessionWindow entries)"
            )

    def contains(self, ts: datetime) -> bool:
        """True iff ``ts`` (any tz) falls inside the window."""
        tz = tz_for_exchange(self.exchange)
        if ts.tzinfo is None:
            local = pd.Timestamp(ts, tz="UTC").tz_convert(tz)
        else:
            local = pd.Timestamp(ts).tz_convert(tz)
        if local.weekday() not in self.weekdays:
            return False
        return self.start <= local.time() <= self.end


@dataclass
class StrategySessionPolicy:
    """Per-strategy session policy.

    A strategy is allowed to trade iff at least one of its windows
    contains the current timestamp. An empty windows list means "always
    on" -- compatible with current behaviour.
    """

    strategy_id: str
    windows: List[SessionWindow] = field(default_factory=list)

    def is_open(self, ts: Optional[datetime] = None) -> bool:
        if not self.windows:
            return True
        n = ts or datetime.utcnow()
        return any(w.contains(n) for w in self.windows)


__all__ = [
    "SessionWindow",
    "StrategySessionPolicy",
]
