"""Tests for quantforge.markets.bonds."""
from __future__ import annotations

import pytest

from aurora.markets.bonds import BondConfig, BondYieldCurve


@pytest.fixture
def curve() -> BondYieldCurve:
    return BondYieldCurve(BondConfig(seed=1))


def test_analyze_returns_curve(curve: BondYieldCurve) -> None:
    df = curve.analyze(mock=True)
    assert {"tenor", "par_yield", "discount", "zero_rate"}.issubset(df.columns)
    assert (df["discount"] > 0).all()
    assert (df["discount"] <= 1).all()


def test_duration_convexity_positive(curve: BondYieldCurve) -> None:
    res = curve.duration_convexity(coupon=0.05, T=10, ytm=0.05)
    assert res["price"] > 0
    assert res["macaulay_duration"] > 0
    assert res["convexity"] > 0


def test_zero_coupon_duration_equals_maturity(curve: BondYieldCurve) -> None:
    # Zero-coupon: macaulay duration = maturity. Use a 0% coupon bond.
    res = curve.duration_convexity(coupon=0.0, T=10, ytm=0.05)
    # With semi-annual compounding and zero coupon, duration ~= 10.
    assert abs(res["macaulay_duration"] - 10.0) < 0.1


def test_signals_returns_butterfly(curve: BondYieldCurve) -> None:
    df = curve.analyze(mock=True)
    sigs = curve.signals(df)
    assert "butterfly_bps" in sigs.columns
    assert len(sigs) == 1
