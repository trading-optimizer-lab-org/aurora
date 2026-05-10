"""R185 -- Exchange downtime / scheduled-maintenance windows.

Half-open ``[start_ts, end_ts)`` windows that the engine treats as a
hard refusal for any order on the named ``(exchange, kind)`` pair.
Nested or overlapping windows are explicitly allowed; the registry
returns ``True`` from :meth:`DowntimeRegistry.is_in_downtime` if *any*
matching window covers the timestamp.

Convention:

    * ``start_ts`` is inclusive
    * ``end_ts`` is exclusive
    * Windows are half-open so a contiguous (no-gap) sequence of
      adjacent windows does not double-count the boundary.

The registry is intentionally lightweight; persistent storage and
operator-driven schedules live elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

import pandas as pd

from aurora.markets.crypto_derivatives import CryptoInstrumentKind


@dataclass(frozen=True)
class DowntimeWindow:
    """One scheduled-downtime window for an exchange / kind pair.

    Attributes:
        exchange: exchange registry key (matches
            :class:`aurora.markets.exchange_capability.ExchangeCapability.name`).
        kind: which instrument kind the window applies to.
        start_ts: inclusive start of the window.
        end_ts: exclusive end of the window. Must be strictly greater
            than ``start_ts``.
        reason: plain-English description of why the window exists
            (e.g. "scheduled hardfork upgrade", "engine maintenance").
    """

    exchange: str
    kind: CryptoInstrumentKind
    start_ts: pd.Timestamp
    end_ts: pd.Timestamp
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.exchange:
            raise ValueError("DowntimeWindow.exchange must be non-empty")
        if not isinstance(self.kind, CryptoInstrumentKind):
            object.__setattr__(self, "kind", CryptoInstrumentKind.parse(self.kind))
        if not isinstance(self.start_ts, pd.Timestamp):
            object.__setattr__(self, "start_ts", pd.Timestamp(self.start_ts))
        if not isinstance(self.end_ts, pd.Timestamp):
            object.__setattr__(self, "end_ts", pd.Timestamp(self.end_ts))
        if self.end_ts <= self.start_ts:
            raise ValueError(
                f"DowntimeWindow.end_ts ({self.end_ts!s}) must be strictly "
                f"greater than start_ts ({self.start_ts!s})"
            )

    def contains(self, ts: pd.Timestamp) -> bool:
        """Return ``True`` iff ``ts`` lies in ``[start_ts, end_ts)``."""
        if not isinstance(ts, pd.Timestamp):
            ts = pd.Timestamp(ts)
        return self.start_ts <= ts < self.end_ts


class DowntimeRegistry:
    """In-memory list of :class:`DowntimeWindow` records."""

    def __init__(self, windows: Optional[Iterable[DowntimeWindow]] = None) -> None:
        self._windows: List[DowntimeWindow] = []
        for w in windows or ():
            self.add(w)

    def __len__(self) -> int:
        return len(self._windows)

    def add(self, window: DowntimeWindow) -> None:
        if not isinstance(window, DowntimeWindow):
            raise TypeError(
                f"DowntimeRegistry.add expects DowntimeWindow, got "
                f"{type(window).__name__}"
            )
        self._windows.append(window)

    def windows_for(
        self, exchange: str, kind: "str | CryptoInstrumentKind"
    ) -> tuple[DowntimeWindow, ...]:
        parsed = CryptoInstrumentKind.parse(kind)
        return tuple(
            w for w in self._windows
            if w.exchange == exchange and w.kind == parsed
        )

    def is_in_downtime(
        self,
        exchange: str,
        kind: "str | CryptoInstrumentKind",
        ts: "pd.Timestamp | str",
    ) -> bool:
        """Return ``True`` if any registered window covers ``ts``."""
        if not isinstance(ts, pd.Timestamp):
            ts = pd.Timestamp(ts)
        parsed = CryptoInstrumentKind.parse(kind)
        for w in self._windows:
            if w.exchange != exchange:
                continue
            if w.kind != parsed:
                continue
            if w.contains(ts):
                return True
        return False

    def matching_windows(
        self,
        exchange: str,
        kind: "str | CryptoInstrumentKind",
        ts: "pd.Timestamp | str",
    ) -> tuple[DowntimeWindow, ...]:
        """Return every window that covers ``ts`` (useful for nested cases)."""
        if not isinstance(ts, pd.Timestamp):
            ts = pd.Timestamp(ts)
        parsed = CryptoInstrumentKind.parse(kind)
        return tuple(
            w for w in self._windows
            if w.exchange == exchange and w.kind == parsed and w.contains(ts)
        )


__all__ = [
    "DowntimeRegistry",
    "DowntimeWindow",
]
