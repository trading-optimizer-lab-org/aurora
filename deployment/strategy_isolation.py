"""Concurrent strategy isolation primitive (R71).

Two strategies trading the same symbol simultaneously can produce
contradictory orders or oscillating positions. The repository previously
had no documented inter-strategy lock. This module ships the chosen
approach: **hard separation** -- a per-symbol mutex enforced at the live
wrapper boundary. A strategy that wants to trade a symbol must acquire
the symbol's exclusive lease; a second strategy attempting the same
symbol is refused with a typed error.

Design choice rationale
-----------------------

Three options were considered:

1. Per-symbol mutex at the broker layer.
2. Strategy-aware position netter (allow two strats; net their orders).
3. Hard separation (only one strategy holds a position in a symbol at
   a time).

Choice: **hard separation**. The position netter introduces a new
optimisation surface (which strategy "wins" partial fills, how to
attribute PnL) that pulls more weight than it gives. Hard separation
matches the project's bias toward refusing ambiguous configurations
loud and early. Operators that want netting can run two strategies on
disjoint universes, or build a meta-strategy that orchestrates both.

Lease lifecycle
---------------

- ``acquire(strategy_id, symbol)`` returns a ``Lease`` if free, raises
  ``IsolationConflict`` otherwise. The lease records who holds it and
  when.
- ``release(lease)`` returns the symbol to the free pool.
- ``acquired_by(symbol)`` is a read-only query.
- ``current_leases()`` lists every active lease for the daily ops
  report.

Persistence is in-process today. R71 follow-up adds a cross-process
file-backed lease store so two `forge` invocations do not silently
clobber each other.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional


class IsolationConflict(RuntimeError):
    """A second strategy attempted to acquire a symbol already held."""


@dataclass(frozen=True)
class Lease:
    """Frozen record of an exclusive symbol lease."""

    strategy_id: str
    symbol: str
    acquired_at: datetime


class StrategyIsolation:
    """Per-symbol exclusive-lease registry.

    Thread-safe. Cross-process safety is a follow-up.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._leases: Dict[str, Lease] = {}

    # ---- mutation -------------------------------------------------------

    def acquire(self, strategy_id: str, symbol: str) -> Lease:
        """Acquire ``symbol`` for ``strategy_id``.

        Raises:
            IsolationConflict: when ``symbol`` is already held by a
                different strategy.

        If the same strategy re-acquires its own symbol, the call is a
        no-op and returns the existing lease (idempotent re-entry).
        """
        with self._lock:
            existing = self._leases.get(symbol)
            if existing is not None and existing.strategy_id != strategy_id:
                raise IsolationConflict(
                    f"symbol {symbol!r} is already held by "
                    f"strategy {existing.strategy_id!r} since "
                    f"{existing.acquired_at.isoformat()}; "
                    f"refusing acquire by {strategy_id!r}"
                )
            if existing is not None:
                return existing
            lease = Lease(
                strategy_id=strategy_id,
                symbol=symbol,
                acquired_at=datetime.utcnow(),
            )
            self._leases[symbol] = lease
            return lease

    def release(self, lease: Lease) -> None:
        """Release ``lease``. No-op if the lease is no longer active."""
        with self._lock:
            current = self._leases.get(lease.symbol)
            if current is None:
                return
            if current.strategy_id != lease.strategy_id:
                # Refuse to release a lease held by someone else.
                raise IsolationConflict(
                    f"cannot release {lease.symbol!r}: held by "
                    f"{current.strategy_id!r}, not {lease.strategy_id!r}"
                )
            del self._leases[lease.symbol]

    def release_all_for(self, strategy_id: str) -> int:
        """Release every symbol held by ``strategy_id``. Returns count."""
        with self._lock:
            to_drop = [
                sym for sym, lease in self._leases.items()
                if lease.strategy_id == strategy_id
            ]
            for sym in to_drop:
                del self._leases[sym]
            return len(to_drop)

    # ---- queries --------------------------------------------------------

    def acquired_by(self, symbol: str) -> Optional[Lease]:
        """Return the active lease for ``symbol`` if any."""
        with self._lock:
            return self._leases.get(symbol)

    def current_leases(self) -> list[Lease]:
        """Return a snapshot of every active lease."""
        with self._lock:
            return list(self._leases.values())

    def is_free(self, symbol: str) -> bool:
        """True iff no strategy currently holds ``symbol``."""
        with self._lock:
            return symbol not in self._leases


__all__ = [
    "IsolationConflict",
    "Lease",
    "StrategyIsolation",
]
