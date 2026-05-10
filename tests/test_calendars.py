"""R160 - Tests for the market-calendar registry and series validator.

These tests pin down the calendar-aware presence checks: NYSE skips
holidays and weekends, ETF_US tracks NYSE, FRED follows business days,
crypto runs 24/7, FX is weekday-only.
"""
from __future__ import annotations

import pandas as pd
import pytest

from aurora.data_contracts.calendars import (
    CalendarRecord,
    CalendarRegistry,
    MarketCalendarKind,
    expected_sessions,
    validate_series,
)


# ---------------------------------------------------------------------------
# expected_sessions
# ---------------------------------------------------------------------------


def test_expected_sessions_nyse_skips_new_year_and_weekends():
    sessions = expected_sessions("2024-01-01", "2024-01-08", MarketCalendarKind.NYSE)
    iso = list(sessions.strftime("%Y-%m-%d"))
    # Jan 1 is New Year's Day (closed). Jan 6, 7 are weekend. Jan 2 - 5
    # and Jan 8 should be sessions.
    assert "2024-01-01" not in iso
    assert "2024-01-06" not in iso
    assert "2024-01-07" not in iso
    assert "2024-01-02" in iso
    assert "2024-01-05" in iso
    assert "2024-01-08" in iso


def test_expected_sessions_crypto_returns_every_day():
    sessions = expected_sessions(
        "2024-01-01", "2024-01-07", MarketCalendarKind.CRYPTO_24X7,
    )
    assert len(sessions) == 7
    iso = set(sessions.strftime("%Y-%m-%d"))
    assert "2024-01-06" in iso  # Saturday
    assert "2024-01-07" in iso  # Sunday


def test_expected_sessions_fx_skips_weekends_only():
    sessions = expected_sessions(
        "2024-01-01", "2024-01-07", MarketCalendarKind.FX_WEEKDAY,
    )
    iso = list(sessions.strftime("%Y-%m-%d"))
    # FX has no holiday rules in this seed, only weekend gating.
    assert "2024-01-01" in iso  # Monday: weekday, FX trades.
    assert "2024-01-06" not in iso
    assert "2024-01-07" not in iso


def test_expected_sessions_fred_business_days_only():
    sessions = expected_sessions(
        "2024-01-01", "2024-01-31", MarketCalendarKind.FRED_MACRO,
    )
    iso = set(sessions.strftime("%Y-%m-%d"))
    # MLK day Jan 15 2024 should be a federal holiday.
    assert "2024-01-15" not in iso
    # Regular weekday should be present.
    assert "2024-01-09" in iso


def test_expected_sessions_etf_matches_nyse():
    nyse = expected_sessions("2024-01-01", "2024-01-31", MarketCalendarKind.NYSE)
    etf = expected_sessions("2024-01-01", "2024-01-31", MarketCalendarKind.ETF_US)
    assert list(nyse) == list(etf)


def test_expected_sessions_empty_window_when_end_before_start():
    sessions = expected_sessions(
        "2024-01-10", "2024-01-05", MarketCalendarKind.NYSE,
    )
    assert len(sessions) == 0


def test_registry_kinds_includes_all_seeded():
    reg = CalendarRegistry()
    assert MarketCalendarKind.NYSE in reg.kinds()
    assert MarketCalendarKind.CRYPTO_24X7 in reg.kinds()
    assert MarketCalendarKind.FX_WEEKDAY in reg.kinds()
    assert MarketCalendarKind.ETF_US in reg.kinds()
    assert MarketCalendarKind.FRED_MACRO in reg.kinds()


def test_registry_get_unknown_kind_raises():
    reg = CalendarRegistry()
    with pytest.raises(KeyError):
        reg.get("NOT_A_REAL_CALENDAR")


def test_registry_get_accepts_string():
    reg = CalendarRegistry()
    rec = reg.get("NYSE")
    assert isinstance(rec, CalendarRecord)
    assert rec.kind is MarketCalendarKind.NYSE


# ---------------------------------------------------------------------------
# validate_series
# ---------------------------------------------------------------------------


def _series(dates: list[str]) -> pd.Series:
    return pd.Series(pd.to_datetime(dates))


def test_validate_series_nyse_rejects_weekend_bar():
    # Mon Jan 8 + Sat Jan 13 (weekend bar) -- NYSE should flag the
    # weekend as unexpected.
    s = _series([
        "2024-01-08", "2024-01-09", "2024-01-10",
        "2024-01-11", "2024-01-12", "2024-01-13",
    ])
    rep = validate_series(s, MarketCalendarKind.NYSE)
    assert rep["weekend_bars"] == ["2024-01-13"]
    assert "2024-01-13" in rep["unexpected_sessions"]
    assert rep["passed"] is False


def test_validate_series_nyse_accepts_holiday_gap():
    # Jan 15 2024 is MLK day. Skip it explicitly. The validator must
    # NOT report it as missing (it's a real holiday, not a data gap).
    s = _series([
        "2024-01-12", "2024-01-16", "2024-01-17",
    ])
    rep = validate_series(s, MarketCalendarKind.NYSE)
    assert "2024-01-15" not in rep["missing_sessions"]
    # The window is 2024-01-12 .. 2024-01-17. Expected weekdays minus
    # the Saturday/Sunday and minus the MLK holiday.
    assert rep["expected_sessions"] == 3  # 12, 16, 17
    assert rep["passed"] is True


def test_validate_series_nyse_flags_missing_session_data():
    # Drop Jan 9 (a normal trading day) inside the window.
    s = _series([
        "2024-01-08", "2024-01-10", "2024-01-11", "2024-01-12",
    ])
    rep = validate_series(s, MarketCalendarKind.NYSE)
    assert "2024-01-09" in rep["missing_sessions"]
    assert rep["passed"] is False


def test_validate_series_crypto_accepts_24_7():
    dates = pd.date_range("2024-01-01", "2024-01-14", freq="D")
    s = pd.Series(dates)
    rep = validate_series(s, MarketCalendarKind.CRYPTO_24X7)
    assert rep["missing_sessions"] == []
    assert rep["unexpected_sessions"] == []
    assert rep["weekend_bars"] == []
    assert rep["passed"] is True


def test_validate_series_fx_rejects_weekend_bars():
    s = _series([
        "2024-01-08", "2024-01-09", "2024-01-13",  # Sat
    ])
    rep = validate_series(s, MarketCalendarKind.FX_WEEKDAY)
    assert "2024-01-13" in rep["weekend_bars"]
    assert rep["passed"] is False


def test_validate_series_fx_does_not_flag_holiday_gap():
    # MLK day (Jan 15 2024) is NOT an FX holiday in our seed --
    # validate_series should treat it as expected.
    s = _series([
        "2024-01-12", "2024-01-16",  # missing Jan 15
    ])
    rep = validate_series(s, MarketCalendarKind.FX_WEEKDAY)
    assert "2024-01-15" in rep["missing_sessions"]


def test_validate_series_fred_accepts_business_day_macro_data():
    s = _series([
        "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05",
        "2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11",
        "2024-01-12",  # skip MLK Jan 15
        "2024-01-16", "2024-01-17", "2024-01-18", "2024-01-19",
    ])
    rep = validate_series(s, MarketCalendarKind.FRED_MACRO)
    assert rep["passed"] is True
    assert rep["missing_sessions"] == []
    assert rep["weekend_bars"] == []


def test_validate_series_empty_input_passes():
    rep = validate_series(pd.Series([], dtype="datetime64[ns]"), MarketCalendarKind.NYSE)
    assert rep["expected_sessions"] == 0
    assert rep["passed"] is True


def test_validate_series_holiday_gap_field_lists_holidays_seen_as_bars():
    # If the operator's data has a holiday bar (Jan 1) we surface it
    # via holiday_gaps so they can distinguish "stray weekend" from
    # "stray holiday print".
    s = _series([
        "2024-01-01",  # NY Day -- closed
        "2024-01-02", "2024-01-03",
    ])
    rep = validate_series(s, MarketCalendarKind.NYSE)
    assert "2024-01-01" in rep["holiday_gaps"]
    assert rep["passed"] is False


def test_calendar_record_dataclass_is_frozen():
    rec = CalendarRecord(kind=MarketCalendarKind.CRYPTO_24X7, weekend_open=True)
    with pytest.raises(Exception):
        rec.weekend_open = False  # type: ignore[misc]


def test_validate_series_kind_string_resolves():
    s = _series(["2024-01-02", "2024-01-03"])
    rep = validate_series(s, "NYSE")
    assert rep["calendar_kind"] == "NYSE"
