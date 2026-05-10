"""R160 - Market calendar registry and series validation.

Aurora needs a deterministic notion of "what days should this price series
have bars on?". Without it, naive ``pd.bdate_range`` checks falsely flag
holiday gaps as missing data on equities and falsely flag weekend bars as
missing on crypto.

This module ships a small set of seeded :class:`CalendarRecord` objects --
NYSE, ETF_US, FRED_MACRO, CRYPTO_24X7, FX_WEEKDAY -- expressed in a
hand-rolled rule format that depends only on stdlib + pandas. The
calendars are intentionally approximate (production-grade exchange
calendars belong in a vendor library) but they are good enough to
distinguish closed-market gaps from missing-data gaps in the validator.

Public API:

* :class:`MarketCalendarKind` -- enum of supported calendar kinds.
* :class:`CalendarRecord` -- immutable record (kind, holidays, early closes, tz).
* :class:`CalendarRegistry` -- lookup of seeded records.
* :func:`expected_sessions` -- expected ``DatetimeIndex`` for a window.
* :func:`validate_series` -- compare a timestamp series against the
  expected sessions and return a small report dict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date_type
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USLaborDay,
    USMartinLutherKingJr,
    USMemorialDay,
    USPresidentsDay,
    USThanksgivingDay,
)


# --------------------------------------------------------------------------
# Kinds
# --------------------------------------------------------------------------


class MarketCalendarKind(str, Enum):
    """Calendar families Aurora can reason about today.

    Values are strings so ``MarketCalendarKind.NYSE.value`` is JSON-safe
    for snapshot manifests.
    """

    NYSE = "NYSE"
    ETF_US = "ETF_US"
    FRED_MACRO = "FRED_MACRO"
    CRYPTO_24X7 = "CRYPTO_24X7"
    FX_WEEKDAY = "FX_WEEKDAY"


# --------------------------------------------------------------------------
# Hand-rolled NYSE-ish holiday rules
# --------------------------------------------------------------------------


# US-equity-style holiday set. Approximate -- excludes ad-hoc closures
# (e.g. presidential funerals, Hurricane Sandy 2012) and early closes,
# which we expose separately.
_NYSE_RULES = [
    Holiday("NewYearsDay", month=1, day=1, observance=None),
    USMartinLutherKingJr,
    USPresidentsDay,
    GoodFriday,
    USMemorialDay,
    Holiday("Juneteenth", month=6, day=19, start_date="2021-06-19"),
    Holiday("IndependenceDay", month=7, day=4),
    USLaborDay,
    USThanksgivingDay,
    Holiday("Christmas", month=12, day=25),
]


class _NYSEHolidayCalendar(AbstractHolidayCalendar):
    rules = _NYSE_RULES


# FRED macro releases are essentially business-day only with no NYSE-specific
# closures (most series respect federal holidays only).
_FRED_RULES = [
    Holiday("NewYearsDay", month=1, day=1),
    USMartinLutherKingJr,
    USPresidentsDay,
    USMemorialDay,
    Holiday("Juneteenth", month=6, day=19, start_date="2021-06-19"),
    Holiday("IndependenceDay", month=7, day=4),
    USLaborDay,
    USThanksgivingDay,
    Holiday("Christmas", month=12, day=25),
]


class _FREDHolidayCalendar(AbstractHolidayCalendar):
    rules = _FRED_RULES


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CalendarRecord:
    """Frozen description of one trading calendar.

    Attributes:
        kind: which family this calendar belongs to.
        tz: IANA timezone string (informational; sessions are date-only).
        holidays: known full closures (frozen tuple of ISO date strings).
            Empty tuple means "compute from rules at lookup time".
        early_closes: known half-day sessions (still trading days but
            shorter). Validators treat these as full sessions for the
            purposes of presence checks.
        weekend_open: whether saturday/sunday count as sessions
            (``True`` only for crypto).
        rules_calendar: optional pandas holiday-calendar class used to
            derive holidays dynamically. Stored as a string name so the
            dataclass stays pickle/hash friendly.
    """

    kind: MarketCalendarKind
    tz: str = "UTC"
    holidays: Tuple[str, ...] = ()
    early_closes: Tuple[str, ...] = ()
    weekend_open: bool = False
    rules_calendar: Optional[str] = None

    def holiday_set(
        self, start: pd.Timestamp, end: pd.Timestamp,
    ) -> FrozenSet[pd.Timestamp]:
        """Return the set of full-closure days in ``[start, end]``."""
        # caveman: prefer explicit list when provided
        explicit = {pd.Timestamp(d).normalize() for d in self.holidays}
        if self.rules_calendar == "NYSE":
            cal = _NYSEHolidayCalendar()
            derived = set(cal.holidays(start, end).normalize())
            explicit = explicit | derived
        elif self.rules_calendar == "FRED":
            cal = _FREDHolidayCalendar()
            derived = set(cal.holidays(start, end).normalize())
            explicit = explicit | derived
        # Filter to window
        return frozenset(d for d in explicit if start <= d <= end)


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


class CalendarRegistry:
    """In-memory registry of seeded :class:`CalendarRecord` objects."""

    def __init__(
        self, records: Optional[Dict[MarketCalendarKind, CalendarRecord]] = None,
    ) -> None:
        if records is None:
            records = self._seed()
        self._records: Dict[MarketCalendarKind, CalendarRecord] = dict(records)

    @staticmethod
    def _seed() -> Dict[MarketCalendarKind, CalendarRecord]:
        nyse = CalendarRecord(
            kind=MarketCalendarKind.NYSE,
            tz="America/New_York",
            holidays=(),
            early_closes=(),
            weekend_open=False,
            rules_calendar="NYSE",
        )
        # ETF US uses the same trading days as NYSE for the purposes of
        # presence checks. We model it as a separate record so manifests
        # can attribute the calendar id without conflating instruments.
        etf_us = CalendarRecord(
            kind=MarketCalendarKind.ETF_US,
            tz="America/New_York",
            holidays=(),
            early_closes=(),
            weekend_open=False,
            rules_calendar="NYSE",
        )
        fred = CalendarRecord(
            kind=MarketCalendarKind.FRED_MACRO,
            tz="America/New_York",
            holidays=(),
            early_closes=(),
            weekend_open=False,
            rules_calendar="FRED",
        )
        crypto = CalendarRecord(
            kind=MarketCalendarKind.CRYPTO_24X7,
            tz="UTC",
            holidays=(),
            early_closes=(),
            weekend_open=True,
            rules_calendar=None,
        )
        fx = CalendarRecord(
            kind=MarketCalendarKind.FX_WEEKDAY,
            tz="UTC",
            holidays=(),
            early_closes=(),
            weekend_open=False,
            rules_calendar=None,
        )
        return {
            MarketCalendarKind.NYSE: nyse,
            MarketCalendarKind.ETF_US: etf_us,
            MarketCalendarKind.FRED_MACRO: fred,
            MarketCalendarKind.CRYPTO_24X7: crypto,
            MarketCalendarKind.FX_WEEKDAY: fx,
        }

    def get(self, kind: Union[MarketCalendarKind, str]) -> CalendarRecord:
        if isinstance(kind, str):
            try:
                kind = MarketCalendarKind(kind)
            except ValueError as exc:
                raise KeyError(f"unknown calendar kind {kind!r}") from exc
        try:
            return self._records[kind]
        except KeyError as exc:
            raise KeyError(f"calendar kind {kind} is not registered") from exc

    def kinds(self) -> Tuple[MarketCalendarKind, ...]:
        return tuple(self._records.keys())


# --------------------------------------------------------------------------
# Expected sessions
# --------------------------------------------------------------------------


_DEFAULT_REGISTRY = CalendarRegistry()


def _coerce_date(value: Union[str, _date_type, pd.Timestamp]) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def expected_sessions(
    start: Union[str, _date_type, pd.Timestamp],
    end: Union[str, _date_type, pd.Timestamp],
    kind: Union[MarketCalendarKind, str],
    *,
    registry: Optional[CalendarRegistry] = None,
) -> pd.DatetimeIndex:
    """Return the expected trading sessions in ``[start, end]`` (inclusive).

    For weekday-only calendars (NYSE, ETF_US, FRED, FX) we drop weekends
    and registered holidays. For 24/7 crypto we return every day.
    """
    reg = registry or _DEFAULT_REGISTRY
    record = reg.get(kind)
    s = _coerce_date(start)
    e = _coerce_date(end)
    if e < s:
        return pd.DatetimeIndex([])
    full_range = pd.date_range(s, e, freq="D").normalize()
    if record.weekend_open:
        # Crypto: every day counts.
        return full_range
    # Drop weekends (Saturday=5, Sunday=6).
    weekday_mask = full_range.weekday < 5
    weekdays = full_range[weekday_mask]
    holidays = record.holiday_set(s, e)
    if not holidays:
        return weekdays
    keep = [d for d in weekdays if d not in holidays]
    return pd.DatetimeIndex(keep)


# --------------------------------------------------------------------------
# Series validation
# --------------------------------------------------------------------------


def _normalise_series(ts_series: pd.Series) -> pd.DatetimeIndex:
    s = pd.to_datetime(ts_series, errors="coerce")
    s = s.dropna()
    if s.empty:
        return pd.DatetimeIndex([])
    # Strip TZ for date-only comparisons (we only care about session date).
    try:
        if getattr(s.dtype, "tz", None) is not None:
            s = s.dt.tz_convert("UTC").dt.tz_localize(None)
    except (AttributeError, TypeError):
        pass
    return pd.DatetimeIndex(s.values).normalize().drop_duplicates().sort_values()


def validate_series(
    ts_series: pd.Series,
    kind: Union[MarketCalendarKind, str],
    *,
    registry: Optional[CalendarRegistry] = None,
) -> Dict[str, object]:
    """Compare ``ts_series`` against the expected sessions for ``kind``.

    Returns a dict with:

    * ``calendar_kind``: string value of the kind.
    * ``expected_sessions``: count of expected trading sessions.
    * ``present_sessions``: count of unique session dates in the input.
    * ``missing_sessions``: list of expected dates not in the input.
    * ``unexpected_sessions``: list of input dates not in the expected set.
    * ``weekend_bars``: list of weekend dates seen (always empty for crypto).
    * ``holiday_gaps``: list of holiday dates seen as bars (always empty
      for crypto). These count as ``unexpected_sessions`` too but we
      surface them separately so callers can distinguish "operator
      forgot a holiday" from "operator's data has a stray weekend bar".
    * ``passed``: True iff there are no missing or unexpected sessions.
    """
    reg = registry or _DEFAULT_REGISTRY
    record = reg.get(kind)
    actual = _normalise_series(ts_series)
    if actual.empty:
        return {
            "calendar_kind": MarketCalendarKind(kind).value if isinstance(kind, str) else kind.value,
            "expected_sessions": 0,
            "present_sessions": 0,
            "missing_sessions": [],
            "unexpected_sessions": [],
            "weekend_bars": [],
            "holiday_gaps": [],
            "passed": True,
        }
    start = actual.min()
    end = actual.max()
    expected = expected_sessions(start, end, kind, registry=reg)
    expected_set = set(expected)
    actual_set = set(actual)
    missing = sorted(d for d in expected_set if d not in actual_set)
    unexpected = sorted(d for d in actual_set if d not in expected_set)
    weekend_bars: List[pd.Timestamp] = []
    holiday_gaps: List[pd.Timestamp] = []
    if not record.weekend_open:
        weekend_bars = [d for d in unexpected if d.weekday() >= 5]
    holidays = record.holiday_set(start, end)
    holiday_gaps = sorted(d for d in actual_set if d in holidays)

    def _iso(items: List[pd.Timestamp]) -> List[str]:
        return [d.strftime("%Y-%m-%d") for d in items]

    kind_value = MarketCalendarKind(kind).value if isinstance(kind, str) else kind.value
    return {
        "calendar_kind": kind_value,
        "expected_sessions": int(len(expected)),
        "present_sessions": int(len(actual)),
        "missing_sessions": _iso(missing),
        "unexpected_sessions": _iso(unexpected),
        "weekend_bars": _iso(weekend_bars),
        "holiday_gaps": _iso(holiday_gaps),
        "passed": not missing and not unexpected,
    }


__all__ = [
    "CalendarRecord",
    "CalendarRegistry",
    "MarketCalendarKind",
    "expected_sessions",
    "validate_series",
]
