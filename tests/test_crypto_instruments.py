"""Tests for aurora.markets.crypto_derivatives (R185)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.markets.crypto_derivatives import (
    CryptoInstrument,
    CryptoInstrumentKind,
    FundingRateRecord,
    apply_funding,
)


# ---------------------------------------------------------------------------
# Instrument kind / equality / record validation
# ---------------------------------------------------------------------------


def test_crypto_instrument_kind_distinct() -> None:
    """SPOT, DATED_FUTURE and PERPETUAL are three distinct enum values."""
    kinds = {
        CryptoInstrumentKind.SPOT,
        CryptoInstrumentKind.DATED_FUTURE,
        CryptoInstrumentKind.PERPETUAL,
    }
    assert len(kinds) == 3
    assert CryptoInstrumentKind.SPOT.value == "spot"
    assert CryptoInstrumentKind.DATED_FUTURE.value == "dated_future"
    assert CryptoInstrumentKind.PERPETUAL.value == "perpetual"


def test_spot_and_perpetual_distinct_records() -> None:
    """A spot record and a perpetual record with similar fields are not equal."""
    spot = CryptoInstrument(
        symbol="BTCUSDT",
        kind=CryptoInstrumentKind.SPOT,
        base_currency="BTC",
        quote_currency="USDT",
        exchange="binance_spot",
    )
    perp = CryptoInstrument(
        symbol="BTCUSDT",
        kind=CryptoInstrumentKind.PERPETUAL,
        base_currency="BTC",
        quote_currency="USDT",
        exchange="binance_perpetual",
    )
    assert spot != perp
    assert spot.is_spot()
    assert perp.is_perpetual()
    assert not perp.is_spot()


def test_dated_future_requires_expiry() -> None:
    """Constructing a DATED_FUTURE without an expiry must raise."""
    with pytest.raises(ValueError, match="expiry"):
        CryptoInstrument(
            symbol="BTC-26SEP25",
            kind=CryptoInstrumentKind.DATED_FUTURE,
            base_currency="BTC",
            quote_currency="USD",
            exchange="binance_futures",
            expiry=None,
        )


def test_spot_forbids_expiry() -> None:
    """SPOT must not have an expiry."""
    with pytest.raises(ValueError, match="must not have an expiry"):
        CryptoInstrument(
            symbol="BTCUSDT",
            kind=CryptoInstrumentKind.SPOT,
            base_currency="BTC",
            quote_currency="USDT",
            exchange="binance_spot",
            expiry=pd.Timestamp("2026-01-01"),
        )


def test_perpetual_forbids_expiry() -> None:
    """PERPETUAL must not have an expiry."""
    with pytest.raises(ValueError, match="must not have an expiry"):
        CryptoInstrument(
            symbol="BTC-PERP",
            kind=CryptoInstrumentKind.PERPETUAL,
            base_currency="BTC",
            quote_currency="USD",
            exchange="binance_perpetual",
            expiry=pd.Timestamp("2026-01-01"),
        )


def test_dated_future_expiry_coerced_to_timestamp() -> None:
    """A datetime/string expiry is coerced into a pandas Timestamp."""
    inst = CryptoInstrument(
        symbol="BTC-26SEP25",
        kind=CryptoInstrumentKind.DATED_FUTURE,
        base_currency="BTC",
        quote_currency="USD",
        exchange="binance_futures",
        expiry="2025-09-26T00:00:00Z",
    )
    assert isinstance(inst.expiry, pd.Timestamp)
    assert inst.expiry.year == 2025


# ---------------------------------------------------------------------------
# FundingRateRecord
# ---------------------------------------------------------------------------


def test_funding_rate_record_deterministic() -> None:
    """Two records with the same fields hash and compare equal (frozen)."""
    a = FundingRateRecord(
        instrument_symbol="BTC-PERP",
        exchange="binance_perpetual",
        ts=pd.Timestamp("2026-01-01T00:00:00Z"),
        rate=0.0001,
    )
    b = FundingRateRecord(
        instrument_symbol="BTC-PERP",
        exchange="binance_perpetual",
        ts=pd.Timestamp("2026-01-01T00:00:00Z"),
        rate=0.0001,
    )
    assert a == b
    assert a.interval_seconds == 28800
    # 0.0001 per 8h * 3 per day * 365 days = 0.1095
    assert a.annualised() == pytest.approx(0.0001 * 3 * 365, rel=1e-9)


def test_funding_rate_record_validates_interval() -> None:
    """interval_seconds must be > 0."""
    with pytest.raises(ValueError, match="interval_seconds"):
        FundingRateRecord(
            instrument_symbol="BTC-PERP",
            exchange="binance_perpetual",
            ts=pd.Timestamp("2026-01-01"),
            rate=0.0001,
            interval_seconds=0,
        )


# ---------------------------------------------------------------------------
# apply_funding sign convention
# ---------------------------------------------------------------------------


def _make_rates(rates: list[float]) -> list[FundingRateRecord]:
    base = pd.Timestamp("2026-01-01T00:00:00Z")
    return [
        FundingRateRecord(
            instrument_symbol="BTC-PERP",
            exchange="binance_perpetual",
            ts=base + pd.Timedelta(hours=8 * i),
            rate=r,
        )
        for i, r in enumerate(rates)
    ]


def test_apply_funding_long_positive_rate_loses() -> None:
    """A long perp with rate > 0 loses funding (positive rate => long pays)."""
    pnl = [0.0, 0.0, 0.0]
    pos = [1.0, 1.0, 1.0]  # long
    rates = _make_rates([0.0001, 0.0002, 0.0001])
    out = apply_funding(pnl, rates, pos)
    # funding cash flow = pos * rate = +0.0001, +0.0002, +0.0001 (subtracted)
    assert out[0] == pytest.approx(-0.0001)
    assert out[1] == pytest.approx(-0.0002)
    assert out[2] == pytest.approx(-0.0001)
    assert (out < 0).all()


def test_apply_funding_short_positive_rate_gains() -> None:
    """A short perp with rate > 0 gains funding (long pays the short)."""
    pnl = [0.0, 0.0]
    pos = [-1.0, -1.0]
    rates = _make_rates([0.0001, 0.0002])
    out = apply_funding(pnl, rates, pos)
    assert out[0] == pytest.approx(0.0001)
    assert out[1] == pytest.approx(0.0002)
    assert (out > 0).all()


def test_apply_funding_long_negative_rate_gains() -> None:
    """A long perp with rate < 0 gains funding (shorts pay longs)."""
    pnl = [0.0, 0.0]
    pos = [1.0, 1.0]
    rates = _make_rates([-0.0003, -0.0001])
    out = apply_funding(pnl, rates, pos)
    assert (out > 0).all()
    assert out[0] == pytest.approx(0.0003)


def test_apply_funding_added_to_existing_pnl() -> None:
    """apply_funding subtracts funding from an existing PnL series."""
    pnl = np.array([5.0, -2.0, 1.0])
    pos = np.array([2.0, 2.0, 2.0])
    rates = _make_rates([0.0001, 0.0001, 0.0001])
    out = apply_funding(pnl, rates, pos)
    expected = pnl - pos * np.array([0.0001, 0.0001, 0.0001])
    np.testing.assert_allclose(out, expected)


def test_apply_funding_shape_mismatch_raises() -> None:
    """Mismatched lengths between PnL, position and rates must raise."""
    rates = _make_rates([0.0001, 0.0001])
    with pytest.raises(ValueError, match="length"):
        apply_funding([1.0, 2.0, 3.0], rates, [1.0, 1.0, 1.0])
