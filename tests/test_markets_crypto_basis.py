"""Tests for quantforge.markets.crypto_basis."""
from __future__ import annotations

import pytest

from aurora.markets.crypto_basis import (
    CryptoBasisConfig,
    CryptoBasisTrader,
)


@pytest.fixture
def cb() -> CryptoBasisTrader:
    return CryptoBasisTrader(CryptoBasisConfig(seed=1))


def test_quotes_have_columns(cb: CryptoBasisTrader) -> None:
    df = cb.analyze(mock=True)
    assert {"symbol", "spot", "perp", "dated", "days_to_expiry"}.issubset(
        df.columns)


def test_signals_emit_basis(cb: CryptoBasisTrader) -> None:
    df = cb.analyze(mock=True)
    sigs = cb.signals(df)
    assert {"symbol", "dated_carry_apy", "perp_funding_apy",
            "basis_signal"}.issubset(sigs.columns)
    assert sigs["basis_signal"].isin([-1, 0, 1]).all()


def test_carry_positive_when_dated_above_spot(cb: CryptoBasisTrader) -> None:
    df = cb.analyze(mock=True)
    sigs = cb.signals(df)
    # Mock generator pushes dated > spot for all rows; carry should be positive.
    assert (sigs["dated_carry_apy"] > 0).all()
