"""Tests for core.timezone (R45)."""
from __future__ import annotations

import pandas as pd
import pytest

from quantforge.core.timezone import (
    EXCHANGE_TIMEZONES,
    TimezoneMismatch,
    assert_compatible,
    convert_to_exchange,
    is_tz_aware,
    localise_to_exchange,
    to_utc,
    tz_for_exchange,
)


def test_known_exchanges_resolve():
    for name, expected in [
        ("NYSE", "America/New_York"),
        ("LSE", "Europe/London"),
        ("TSE", "Asia/Tokyo"),
        ("CRYPTO", "UTC"),
    ]:
        assert tz_for_exchange(name) == expected
        assert tz_for_exchange(name.lower()) == expected


def test_unknown_exchange_raises_key_error():
    with pytest.raises(KeyError):
        tz_for_exchange("MARS_STOCK_EXCHANGE")


def test_is_tz_aware():
    naive = pd.date_range("2026-01-01", periods=3, freq="D")
    aware = naive.tz_localize("UTC")
    assert is_tz_aware(naive) is False
    assert is_tz_aware(aware) is True
    assert is_tz_aware(pd.Timestamp("2026-01-01")) is False
    assert is_tz_aware(pd.Timestamp("2026-01-01", tz="UTC")) is True


def test_assert_compatible_ok():
    naive_a = pd.date_range("2026-01-01", periods=3, freq="D")
    naive_b = pd.date_range("2026-02-01", periods=3, freq="D")
    aware_a = naive_a.tz_localize("UTC")
    aware_b = naive_b.tz_localize("America/New_York")
    assert_compatible(naive_a, naive_b)
    assert_compatible(aware_a, aware_b)


def test_assert_compatible_mismatch_raises():
    naive = pd.date_range("2026-01-01", periods=3, freq="D")
    aware = naive.tz_localize("UTC")
    with pytest.raises(TimezoneMismatch):
        assert_compatible(naive, aware)


def test_localise_then_convert_round_trip():
    naive = pd.date_range("2026-01-01 09:30", periods=3, freq="D")
    nyse_local = localise_to_exchange(naive, "NYSE")
    assert is_tz_aware(nyse_local)
    london = convert_to_exchange(nyse_local, "LSE")
    assert is_tz_aware(london)
    # London is 5h ahead of NYSE in EST.
    diff = london[0].utcoffset() - nyse_local[0].utcoffset()
    assert diff == pd.Timedelta(hours=5)


def test_localise_refuses_already_aware_index():
    aware = pd.date_range("2026-01-01", periods=3, freq="D", tz="UTC")
    with pytest.raises(ValueError):
        localise_to_exchange(aware, "NYSE")


def test_convert_refuses_naive_index():
    naive = pd.date_range("2026-01-01", periods=3, freq="D")
    with pytest.raises(ValueError):
        convert_to_exchange(naive, "NYSE")


def test_to_utc_handles_both_naive_and_aware():
    naive = pd.date_range("2026-01-01", periods=3, freq="D")
    aware = naive.tz_localize("America/New_York")
    assert str(to_utc(naive).tz) == "UTC"
    assert str(to_utc(aware).tz) == "UTC"


def test_exchange_map_covers_canonical_set():
    # Sanity: at least one exchange per major region.
    assert "NYSE" in EXCHANGE_TIMEZONES
    assert "LSE" in EXCHANGE_TIMEZONES
    assert "TSE" in EXCHANGE_TIMEZONES
    assert "CRYPTO" in EXCHANGE_TIMEZONES
