"""Account-level circuit breaker (R120).

Hard stop trading when daily / weekly drawdown exceeds a configured
threshold. Different from per-strategy stops because it integrates
across all running strategies.

Trip semantics
--------------

- ``record_pnl(strategy_id, pnl_delta)`` updates the rolling totals.
- ``check_state()`` returns the current ``CircuitBreakerState``:
  ``OK`` / ``WARN`` (within 80% of threshold) / ``TRIPPED``.
- A tripped breaker refuses every subsequent stage / commit / push at
  the agent gateway boundary. Reset requires an explicit operator
  ceremony recorded in the audit trail.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Deque, Dict, Optional, Tuple


class CircuitBreakerState(str, Enum):
    OK = "ok"
    WARN = "warn"
    TRIPPED = "tripped"


@dataclass
class CircuitBreakerConfig:
    """Rolling drawdown thresholds.

    Attributes:
        daily_max_dd_fraction: trip when realised daily drawdown is
            below ``-daily_max_dd_fraction`` (e.g. 0.02 = -2%).
        weekly_max_dd_fraction: trip on the rolling 7-day drawdown.
        warn_at_fraction: emit WARN when realised dd is past
            ``warn_at_fraction * threshold``. Default 0.80.
        starting_nav: NAV to anchor the percentage-of-NAV calculation.
            Required at construction so the breaker can compute
            absolute fractions independently of strategy-level book-
            keeping.
    """

    starting_nav: float
    daily_max_dd_fraction: float = 0.02
    weekly_max_dd_fraction: float = 0.05
    warn_at_fraction: float = 0.80


@dataclass
class CircuitBreaker:
    """In-process daily / weekly drawdown circuit breaker."""

    config: CircuitBreakerConfig
    _events: Deque[Tuple[datetime, float]] = field(default_factory=deque)
    _state: CircuitBreakerState = CircuitBreakerState.OK

    # ---- mutation -------------------------------------------------------

    def record_pnl(self, pnl_delta: float, when: Optional[datetime] = None) -> None:
        ts = when or datetime.utcnow()
        self._events.append((ts, float(pnl_delta)))
        # Trim entries older than 8 days (one extra day buffer).
        cutoff = ts - timedelta(days=8)
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()
        self._state = self._compute_state(now=ts)

    def reset(self) -> None:
        """Operator ceremony: clear state. Audit responsibility caller."""
        self._state = CircuitBreakerState.OK
        self._events.clear()

    # ---- queries --------------------------------------------------------

    @property
    def state(self) -> CircuitBreakerState:
        return self._state

    @property
    def is_tripped(self) -> bool:
        return self._state is CircuitBreakerState.TRIPPED

    def daily_pnl_fraction(self, now: Optional[datetime] = None) -> float:
        n = now or datetime.utcnow()
        cutoff = n - timedelta(days=1)
        total = sum(v for ts, v in self._events if ts >= cutoff)
        return total / self.config.starting_nav if self.config.starting_nav else 0.0

    def weekly_pnl_fraction(self, now: Optional[datetime] = None) -> float:
        n = now or datetime.utcnow()
        cutoff = n - timedelta(days=7)
        total = sum(v for ts, v in self._events if ts >= cutoff)
        return total / self.config.starting_nav if self.config.starting_nav else 0.0

    # ---- internal -------------------------------------------------------

    def _compute_state(self, now: datetime) -> CircuitBreakerState:
        d_frac = self.daily_pnl_fraction(now=now)
        w_frac = self.weekly_pnl_fraction(now=now)

        d_trip = -self.config.daily_max_dd_fraction
        w_trip = -self.config.weekly_max_dd_fraction
        if d_frac <= d_trip or w_frac <= w_trip:
            return CircuitBreakerState.TRIPPED
        warn_d = d_trip * self.config.warn_at_fraction
        warn_w = w_trip * self.config.warn_at_fraction
        if d_frac <= warn_d or w_frac <= warn_w:
            return CircuitBreakerState.WARN
        return CircuitBreakerState.OK


__all__ = [
    "CircuitBreakerConfig",
    "CircuitBreaker",
    "CircuitBreakerState",
]
