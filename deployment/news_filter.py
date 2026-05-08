"""News / event filter (R94).

Block trading during scheduled high-impact events (Fed, NFP, CPI,
earnings for held names). Pluggable provider so operators wire their
own news feed; the in-tree implementation operates on a list of
``(start_utc, end_utc, label)`` blackout windows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional


@dataclass(frozen=True)
class BlackoutWindow:
    """A trading-blackout interval."""

    start_utc: datetime
    end_utc: datetime
    label: str

    def __post_init__(self) -> None:
        if self.end_utc <= self.start_utc:
            raise ValueError("end_utc must be > start_utc")

    def contains(self, when: datetime) -> bool:
        return self.start_utc <= when <= self.end_utc


@dataclass
class NewsFilter:
    """List-driven news filter.

    Operators populate ``windows`` from their preferred provider
    (econ calendar, earnings calendar, custom JSON feed). The filter
    answers a single question: is ``when`` inside any blackout?
    """

    windows: List[BlackoutWindow] = field(default_factory=list)

    def add(self, window: BlackoutWindow) -> None:
        self.windows.append(window)

    def is_blocked(self, when: Optional[datetime] = None) -> bool:
        n = when or datetime.utcnow()
        return any(w.contains(n) for w in self.windows)

    def active_windows(self, when: Optional[datetime] = None) -> List[BlackoutWindow]:
        n = when or datetime.utcnow()
        return [w for w in self.windows if w.contains(n)]

    def upcoming(
        self,
        within: timedelta = timedelta(hours=4),
        when: Optional[datetime] = None,
    ) -> List[BlackoutWindow]:
        """Return windows that start inside ``within`` from ``when``."""
        n = when or datetime.utcnow()
        cutoff = n + within
        return [
            w for w in self.windows
            if n < w.start_utc <= cutoff
        ]


__all__ = [
    "BlackoutWindow",
    "NewsFilter",
]
