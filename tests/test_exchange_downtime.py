"""Tests for aurora.markets.exchange_downtime (R185)."""
from __future__ import annotations

import pandas as pd
import pytest

from aurora.markets.crypto_derivatives import CryptoInstrumentKind
from aurora.markets.exchange_downtime import DowntimeRegistry, DowntimeWindow


def _w(start: str, end: str, *, exchange: str = "binance_spot",
       kind: CryptoInstrumentKind = CryptoInstrumentKind.SPOT,
       reason: str = "maintenance") -> DowntimeWindow:
    return DowntimeWindow(
        exchange=exchange,
        kind=kind,
        start_ts=pd.Timestamp(start),
        end_ts=pd.Timestamp(end),
        reason=reason,
    )


def test_in_window_blocks_order() -> None:
    reg = DowntimeRegistry([_w("2026-01-01T00:00", "2026-01-01T02:00")])
    assert reg.is_in_downtime(
        "binance_spot", CryptoInstrumentKind.SPOT, "2026-01-01T01:00"
    )


def test_out_of_window_allows_order() -> None:
    reg = DowntimeRegistry([_w("2026-01-01T00:00", "2026-01-01T02:00")])
    assert not reg.is_in_downtime(
        "binance_spot", CryptoInstrumentKind.SPOT, "2026-01-01T03:00"
    )


def test_window_end_is_exclusive() -> None:
    """end_ts is exclusive: an order exactly at end_ts is NOT in downtime."""
    reg = DowntimeRegistry([_w("2026-01-01T00:00", "2026-01-01T02:00")])
    assert not reg.is_in_downtime(
        "binance_spot", CryptoInstrumentKind.SPOT, "2026-01-01T02:00"
    )
    assert reg.is_in_downtime(
        "binance_spot", CryptoInstrumentKind.SPOT, "2026-01-01T00:00"
    )


def test_nested_windows_handled() -> None:
    """Two overlapping windows both match a timestamp inside the inner one."""
    outer = _w("2026-01-01T00:00", "2026-01-01T10:00",
               reason="full-day maintenance")
    inner = _w("2026-01-01T05:00", "2026-01-01T06:00", reason="db migration")
    reg = DowntimeRegistry([outer, inner])
    matches = reg.matching_windows(
        "binance_spot", CryptoInstrumentKind.SPOT, "2026-01-01T05:30"
    )
    assert len(matches) == 2
    assert reg.is_in_downtime(
        "binance_spot", CryptoInstrumentKind.SPOT, "2026-01-01T05:30"
    )


def test_window_does_not_leak_across_kind() -> None:
    """A SPOT downtime does NOT block a perpetual order on the same exchange."""
    reg = DowntimeRegistry([
        _w(
            "2026-01-01T00:00",
            "2026-01-01T02:00",
            exchange="binance_perpetual",
            kind=CryptoInstrumentKind.SPOT,
        )
    ])
    assert not reg.is_in_downtime(
        "binance_perpetual",
        CryptoInstrumentKind.PERPETUAL,
        "2026-01-01T01:00",
    )


def test_invalid_window_end_before_start_raises() -> None:
    with pytest.raises(ValueError, match="strictly greater"):
        DowntimeWindow(
            exchange="binance_spot",
            kind=CryptoInstrumentKind.SPOT,
            start_ts=pd.Timestamp("2026-01-01T02:00"),
            end_ts=pd.Timestamp("2026-01-01T01:00"),
        )
