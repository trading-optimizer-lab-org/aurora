"""Tests for CryptoFundingArbSignal."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.signals import CryptoFundingArbSignal, CryptoFundingArbConfig


@pytest.fixture
def funding_panel():
    return CryptoFundingArbSignal.fetch_funding_stub(
        symbols=["BTC", "ETH", "SOL"],
        dates=pd.date_range("2024-01-01", periods=200, freq="8h"),
        seed=42,
    )


def test_stub_shape(funding_panel):
    assert funding_panel.shape == (200, 3)
    assert list(funding_panel.columns) == ["BTC", "ETH", "SOL"]


def test_signals_columns(funding_panel):
    sig = CryptoFundingArbSignal()
    out = sig.signals(funding_panel)
    expected = ["BTC_perp", "BTC_spot", "ETH_perp", "ETH_spot", "SOL_perp", "SOL_spot"]
    assert list(out.columns) == expected


def test_legs_are_opposite_sign(funding_panel):
    sig = CryptoFundingArbSignal()
    out = sig.signals(funding_panel)
    for sym in ["BTC", "ETH", "SOL"]:
        a = out[f"{sym}_perp"].values
        b = out[f"{sym}_spot"].values
        # When non-zero, opposite signs
        nz = a != 0
        if nz.any():
            assert np.allclose(a[nz] + b[nz], 0)


def test_high_positive_funding_short_perp():
    idx = pd.date_range("2024-01-01", periods=10, freq="8h")
    f = pd.DataFrame({"BTC": [0.001] * 10}, index=idx)
    sig = CryptoFundingArbSignal(CryptoFundingArbConfig(funding_threshold=0.0001, smoothing=1))
    out = sig.signals(f)
    assert (out["BTC_perp"] == -0.5).all()
    assert (out["BTC_spot"] == 0.5).all()


def test_high_negative_funding_long_perp():
    idx = pd.date_range("2024-01-01", periods=10, freq="8h")
    f = pd.DataFrame({"BTC": [-0.001] * 10}, index=idx)
    sig = CryptoFundingArbSignal(CryptoFundingArbConfig(funding_threshold=0.0001, smoothing=1))
    out = sig.signals(f)
    assert (out["BTC_perp"] == 0.5).all()
    assert (out["BTC_spot"] == -0.5).all()


def test_zero_funding_zero_signal():
    idx = pd.date_range("2024-01-01", periods=10, freq="8h")
    f = pd.DataFrame({"BTC": [0.0] * 10}, index=idx)
    sig = CryptoFundingArbSignal()
    out = sig.signals(f)
    assert (out == 0).all().all()


def test_invalid_inputs():
    with pytest.raises(TypeError):
        CryptoFundingArbSignal().signals(np.zeros((5, 2)))
    with pytest.raises(ValueError):
        CryptoFundingArbSignal(CryptoFundingArbConfig(funding_threshold=0))
    with pytest.raises(ValueError):
        CryptoFundingArbSignal(CryptoFundingArbConfig(smoothing=0))
