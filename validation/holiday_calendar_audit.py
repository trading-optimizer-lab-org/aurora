"""Holiday calendar correctness audit (R151).

Verify that strategies do not place orders on closed exchanges.
Catches the "off-by-one weekend" issue and US-only holidays missed
when running on EU markets.

Pure data: takes a list of order timestamps + an exchange code, and
returns the timestamps that fall on a closed-exchange day.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Sequence, Set


# US equity holidays for 2026 (sample set; operators should plug in a
# full per-exchange calendar via a vendor such as
# pandas_market_calendars).
_US_HOLIDAYS_2026: Set[date] = {
    date(2026, 1, 1),    # New Year
    date(2026, 1, 19),   # MLK Day
    date(2026, 2, 16),   # Presidents Day
    date(2026, 4, 3),    # Good Friday
    date(2026, 5, 25),   # Memorial Day
    date(2026, 6, 19),   # Juneteenth
    date(2026, 7, 3),    # Independence Day (observed)
    date(2026, 9, 7),    # Labor Day
    date(2026, 11, 26),  # Thanksgiving
    date(2026, 12, 25),  # Christmas
}


_HOLIDAY_REGISTRY: Dict[str, Set[date]] = {
    "NYSE": _US_HOLIDAYS_2026,
    "NASDAQ": _US_HOLIDAYS_2026,
    "AMEX": _US_HOLIDAYS_2026,
}


@dataclass(frozen=True)
class HolidayViolation:
    """One order timestamp that fell on a closed-exchange day."""

    timestamp: datetime
    exchange: str
    reason: str  # "weekend" | "holiday"


def is_market_open(when: date, exchange: str = "NYSE") -> bool:
    """True iff ``exchange`` is open on date ``when`` (M-F minus holidays)."""
    if when.weekday() >= 5:
        return False
    holidays = _HOLIDAY_REGISTRY.get(exchange.upper(), set())
    return when not in holidays


def audit_orders(
    timestamps: Sequence[datetime],
    *,
    exchange: str = "NYSE",
) -> List[HolidayViolation]:
    """Return order timestamps that fell on a closed-exchange day."""
    violations: List[HolidayViolation] = []
    for ts in timestamps:
        when = ts.date()
        if when.weekday() >= 5:
            violations.append(HolidayViolation(
                timestamp=ts, exchange=exchange, reason="weekend",
            ))
            continue
        holidays = _HOLIDAY_REGISTRY.get(exchange.upper(), set())
        if when in holidays:
            violations.append(HolidayViolation(
                timestamp=ts, exchange=exchange, reason="holiday",
            ))
    return violations


def register_calendar(exchange: str, holidays: Set[date]) -> None:
    """Register a per-exchange holiday set for the audit."""
    _HOLIDAY_REGISTRY[exchange.upper()] = set(holidays)


__all__ = [
    "HolidayViolation",
    "is_market_open",
    "audit_orders",
    "register_calendar",
]
