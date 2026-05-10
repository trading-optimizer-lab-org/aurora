"""R163 - tests for the liquidity, cost and capacity dataset."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from aurora.data_contracts.liquidity import (
    LiquidityRecord,
    LiquidityValidationGate,
    compute_liquidity_features,
    flag_thin_symbols,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def constant_volume_prices() -> pd.DataFrame:
    """Constant-close, constant-volume bar series; ADV is exactly the
    daily dollar volume by construction."""
    idx = pd.date_range("2024-01-01", periods=60, freq="B")
    return pd.DataFrame(
        {
            "close": np.full(60, 100.0),
            "volume": np.full(60, 1_000_000.0),
        },
        index=idx,
    )


@pytest.fixture
def gbm_prices() -> pd.DataFrame:
    """Geometric Brownian motion close + Poisson-ish volume."""
    rng = np.random.default_rng(42)
    n = 80
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    rets = rng.normal(loc=0.0005, scale=0.012, size=n)
    close = 100.0 * np.cumprod(1.0 + rets)
    volume = rng.uniform(800_000.0, 1_200_000.0, size=n)
    return pd.DataFrame({"close": close, "volume": volume}, index=idx)


@pytest.fixture
def thin_symbol_prices() -> pd.DataFrame:
    """A symbol whose dollar volume is clearly below typical floors."""
    idx = pd.date_range("2024-01-01", periods=40, freq="B")
    return pd.DataFrame(
        {
            "close": np.full(40, 5.0),
            "volume": np.full(40, 2_000.0),  # $10k/day, clearly thin
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# compute_liquidity_features tests
# ---------------------------------------------------------------------------


def test_rolling_adv_stable_for_constant_volume(constant_volume_prices):
    asof = constant_volume_prices.index[-1]
    rec = compute_liquidity_features(
        constant_volume_prices, symbol="AAA", asof=asof, window=20
    )
    assert rec.rolling_adv == pytest.approx(100.0 * 1_000_000.0)


def test_dollar_volume_close_times_volume_summed(constant_volume_prices):
    asof = constant_volume_prices.index[-1]
    rec = compute_liquidity_features(
        constant_volume_prices, symbol="AAA", asof=asof, window=20
    )
    # 20 bars * 100 * 1e6 = 2e9
    assert rec.dollar_volume == pytest.approx(2.0e9)


def test_volatility_annualised_reasonable_for_gbm(gbm_prices):
    asof = gbm_prices.index[-1]
    rec = compute_liquidity_features(
        gbm_prices, symbol="GBM", asof=asof, window=60
    )
    # daily sigma ~1.2% -> annualised ~1.2% * sqrt(252) ~= 19%
    assert 0.05 < rec.volatility_annualised < 0.5


def test_turnover_zero_for_constant_volume(constant_volume_prices):
    asof = constant_volume_prices.index[-1]
    rec = compute_liquidity_features(
        constant_volume_prices, symbol="AAA", asof=asof, window=20
    )
    assert rec.turnover == pytest.approx(0.0, abs=1e-12)


def test_estimated_spread_label(constant_volume_prices):
    """Any value derived from price-only proxies must be labelled estimated."""
    asof = constant_volume_prices.index[-1]
    rec = compute_liquidity_features(
        constant_volume_prices, symbol="AAA", asof=asof, window=20
    )
    assert rec.observed_or_estimated == "estimated"
    assert rec.estimated_spread_bps > 0.0


def test_low_volume_flag_triggers_below_floor(thin_symbol_prices):
    asof = thin_symbol_prices.index[-1]
    rec = compute_liquidity_features(
        thin_symbol_prices,
        symbol="THIN",
        asof=asof,
        window=20,
        low_volume_floor=1.0e6,
    )
    assert rec.low_volume_flag is True


def test_low_volume_flag_off_for_liquid(constant_volume_prices):
    asof = constant_volume_prices.index[-1]
    rec = compute_liquidity_features(
        constant_volume_prices,
        symbol="AAA",
        asof=asof,
        window=20,
        low_volume_floor=1.0e6,
    )
    assert rec.low_volume_flag is False


def test_capacity_usd_positive_for_liquid(constant_volume_prices):
    asof = constant_volume_prices.index[-1]
    rec = compute_liquidity_features(
        constant_volume_prices,
        symbol="AAA",
        asof=asof,
        window=20,
        participation_cap=0.05,
    )
    # 5% of $100m ADV
    assert rec.capacity_usd == pytest.approx(0.05 * 100.0 * 1_000_000.0)


def test_compute_features_requires_close_and_volume():
    df = pd.DataFrame(
        {"close": [1.0, 2.0]},
        index=pd.date_range("2024-01-01", periods=2, freq="B"),
    )
    with pytest.raises(ValueError, match="volume"):
        compute_liquidity_features(df, symbol="AAA", asof=df.index[-1])


def test_compute_features_rejects_short_window(constant_volume_prices):
    asof = constant_volume_prices.index[-1]
    with pytest.raises(ValueError, match="window"):
        compute_liquidity_features(
            constant_volume_prices, symbol="AAA", asof=asof, window=1
        )


# ---------------------------------------------------------------------------
# flag_thin_symbols tests
# ---------------------------------------------------------------------------


def test_flag_thin_symbols_returns_sorted_list(
    constant_volume_prices, thin_symbol_prices
):
    liquid_asof = constant_volume_prices.index[-1]
    thin_asof = thin_symbol_prices.index[-1]
    records = [
        compute_liquidity_features(
            constant_volume_prices, symbol="ZZZ", asof=liquid_asof, window=20
        ),
        compute_liquidity_features(
            thin_symbol_prices, symbol="MMM", asof=thin_asof, window=20
        ),
        compute_liquidity_features(
            thin_symbol_prices, symbol="AAA", asof=thin_asof, window=20
        ),
    ]
    thin = flag_thin_symbols(records, min_dollar_volume=1.0e6, min_adv=1.0e6)
    assert thin == ["AAA", "MMM"]


def test_flag_thin_symbols_validates_floors():
    with pytest.raises(ValueError):
        flag_thin_symbols([], min_dollar_volume=-1.0, min_adv=0.0)
    with pytest.raises(ValueError):
        flag_thin_symbols([], min_dollar_volume=0.0, min_adv=-1.0)


# ---------------------------------------------------------------------------
# LiquidityValidationGate tests
# ---------------------------------------------------------------------------


def test_gate_refuses_when_order_size_exceeds_capacity(constant_volume_prices):
    asof = constant_volume_prices.index[-1]
    rec = compute_liquidity_features(
        constant_volume_prices,
        symbol="AAA",
        asof=asof,
        window=20,
        participation_cap=0.05,
    )
    gate = LiquidityValidationGate()
    allowed, reason = gate(rec, avg_order_size_usd=rec.capacity_usd * 2.0)
    assert allowed is False
    assert "capacity band" in reason


def test_gate_explains_reason_in_plain_language(constant_volume_prices):
    asof = constant_volume_prices.index[-1]
    rec = compute_liquidity_features(
        constant_volume_prices, symbol="AAA", asof=asof, window=20
    )
    gate = LiquidityValidationGate()
    allowed, reason = gate(rec, avg_order_size_usd=rec.capacity_usd * 5.0)
    assert allowed is False
    # Reason should mention symbol and capacity
    assert "AAA" in reason
    assert "$" in reason  # currency formatting visible


def test_gate_allows_within_capacity(constant_volume_prices):
    asof = constant_volume_prices.index[-1]
    rec = compute_liquidity_features(
        constant_volume_prices, symbol="AAA", asof=asof, window=20
    )
    gate = LiquidityValidationGate()
    allowed, reason = gate(rec, avg_order_size_usd=rec.capacity_usd * 0.1)
    assert allowed is True
    assert "AAA" in reason


def test_gate_refuses_when_capacity_adjusted_sharpe_collapses(
    constant_volume_prices,
):
    asof = constant_volume_prices.index[-1]
    rec = compute_liquidity_features(
        constant_volume_prices, symbol="AAA", asof=asof, window=20
    )
    gate = LiquidityValidationGate(sharpe_floor_pct=0.5)
    allowed, reason = gate(
        rec,
        avg_order_size_usd=rec.capacity_usd * 0.1,
        clean_sharpe=2.0,
        capacity_adjusted_sharpe=0.5,  # 25% of clean, below 50% floor
    )
    assert allowed is False
    assert "Sharpe" in reason


def test_gate_refuses_low_volume_flag(thin_symbol_prices):
    asof = thin_symbol_prices.index[-1]
    rec = compute_liquidity_features(
        thin_symbol_prices,
        symbol="THIN",
        asof=asof,
        window=20,
        low_volume_floor=1.0e6,
    )
    gate = LiquidityValidationGate()
    allowed, reason = gate(rec, avg_order_size_usd=1.0)
    assert allowed is False
    assert "low-volume" in reason


def test_record_to_dict_serialises_asof():
    asof = pd.Timestamp("2024-06-15")
    rec = LiquidityRecord(
        symbol="AAA",
        asof_date=asof,
        rolling_adv=1_000_000.0,
        dollar_volume=2_000_000.0,
        volatility_annualised=0.20,
        turnover=0.0,
        estimated_spread_bps=5.0,
        estimated_slippage_bps=1.0,
        capacity_usd=50_000.0,
        low_volume_flag=False,
        observed_or_estimated="estimated",
        source="test",
    )
    d = rec.to_dict()
    assert d["asof_date"] == "2024-06-15T00:00:00"
    assert d["observed_or_estimated"] == "estimated"
