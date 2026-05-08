"""Tests for quantforge.core.costs_intraday (Batch M.3)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from quantforge.core.costs_intraday import (
    IntradayCostModel,
    default_crypto_curve,
    default_us_equity_curve,
    estimate_spread_from_high_low,
)


def _ts(time_str: str) -> pd.Timestamp:
    return pd.Timestamp(f"2024-06-03 {time_str}")


def test_base_cost():
    """No bid-ask data, no participation curve, no ADV -> returns base_bps."""
    model = IntradayCostModel(base_bps=1.0)
    cost = model.cost_bps(price=100.0, qty=10.0, timestamp=_ts("12:00"))
    assert cost == pytest.approx(1.0)


def test_bid_ask_scaling():
    """bid_ask of 5 bps overrides base of 1 bps."""
    idx = pd.DatetimeIndex([_ts("09:30"), _ts("12:00"), _ts("15:30")])
    spread = pd.Series([5.0, 5.0, 5.0], index=idx)
    model = IntradayCostModel(base_bps=1.0, bid_ask_bps=spread)
    cost = model.cost_bps(price=100.0, qty=10.0, timestamp=_ts("12:00"))
    assert cost == pytest.approx(5.0)


def test_bid_ask_floor():
    """When bid_ask < base, base wins (floor)."""
    idx = pd.DatetimeIndex([_ts("12:00")])
    spread = pd.Series([0.2], index=idx)
    model = IntradayCostModel(base_bps=1.0, bid_ask_bps=spread)
    cost = model.cost_bps(price=100.0, qty=10.0, timestamp=_ts("12:00"))
    assert cost == pytest.approx(1.0)


def test_participation_curve():
    """U-shape: cost at 09:30 > cost at midday."""
    curve = default_us_equity_curve()
    model = IntradayCostModel(base_bps=2.0, participation_curve=curve)
    cost_open = model.cost_bps(price=100.0, qty=10.0, timestamp=_ts("09:30"))
    cost_noon = model.cost_bps(price=100.0, qty=10.0, timestamp=_ts("12:45"))
    cost_close = model.cost_bps(price=100.0, qty=10.0, timestamp=_ts("16:00"))
    assert cost_open > cost_noon
    assert cost_close > cost_noon
    # Curve range: 0.8 to 2.5 -> noon ~ 0.8*base, open ~ 2.5*base
    assert cost_noon == pytest.approx(2.0 * 0.8, abs=0.05)
    assert cost_open == pytest.approx(2.0 * 2.5, abs=1e-9)


def test_impact_sqrt():
    """Doubling qty increases impact by sqrt(2)."""
    model = IntradayCostModel(base_bps=0.0, impact_coef=0.1, adv=1_000_000.0)
    c1 = model.cost_bps(price=100.0, qty=1000.0, timestamp=_ts("12:00"))
    c2 = model.cost_bps(price=100.0, qty=2000.0, timestamp=_ts("12:00"))
    assert c2 / c1 == pytest.approx(math.sqrt(2.0), rel=1e-9)


def test_no_adv_no_impact():
    """When adv is None, impact_bps == 0; cost_bps reduces to spread*mult."""
    model = IntradayCostModel(base_bps=2.0, impact_coef=0.5, adv=None)
    cost = model.cost_bps(price=100.0, qty=1_000_000.0, timestamp=_ts("12:00"))
    assert cost == pytest.approx(2.0)


def test_corwin_schultz():
    """Hand-computed 2-bar example. Bar 1 has zero high-low (H=L=100),
    bar 2 has H=102, L=100. Verify the spread estimate matches the
    Corwin-Schultz formula directly.
    """
    df = pd.DataFrame(
        {"high": [100.0, 102.0], "low": [100.0, 100.0]},
        index=pd.DatetimeIndex([_ts("09:30"), _ts("09:31")]),
    )
    out = estimate_spread_from_high_low(df)
    # First value is NaN by construction.
    assert math.isnan(out.iloc[0])

    # Recompute closed-form for bar idx=1:
    log_hl_sq_1 = math.log(102.0 / 100.0) ** 2  # bar 2
    log_hl_sq_0 = math.log(100.0 / 100.0) ** 2  # bar 1 = 0
    beta = log_hl_sq_0 + log_hl_sq_1
    h2 = max(102.0, 100.0)
    l2 = min(100.0, 100.0)
    gamma = math.log(h2 / l2) ** 2
    denom = 3.0 - 2.0 * math.sqrt(2.0)
    alpha = (math.sqrt(2.0 * beta) - math.sqrt(beta)) / denom - math.sqrt(gamma / denom)
    spread_prop = 2.0 * (math.exp(alpha) - 1.0) / (1.0 + math.exp(alpha))
    if spread_prop < 0.0:
        spread_prop = 0.0
    expected_bps = spread_prop * 1e4 / 2.0
    assert out.iloc[1] == pytest.approx(expected_bps, rel=1e-9, abs=1e-9)


def test_zero_qty():
    """qty=0 -> cost=0 regardless of other components."""
    idx = pd.DatetimeIndex([_ts("12:00")])
    spread = pd.Series([100.0], index=idx)  # huge spread should not matter
    model = IntradayCostModel(
        base_bps=10.0,
        bid_ask_bps=spread,
        participation_curve=default_us_equity_curve(),
        impact_coef=1.0,
        adv=10.0,
    )
    cost = model.cost_bps(price=100.0, qty=0.0, timestamp=_ts("12:00"))
    assert cost == 0.0


def test_default_crypto_curve_flat():
    """Crypto curve returns 1.0 for any time-of-day."""
    curve = default_crypto_curve()
    for x in (0.0, 0.25, 0.5, 0.75, 1.0):
        assert curve(x) == 1.0


def test_corwin_schultz_requires_columns():
    df = pd.DataFrame({"open": [1.0], "close": [1.0]})
    with pytest.raises(ValueError):
        estimate_spread_from_high_low(df)


def test_corwin_schultz_short_input():
    """Single-row frame -> all NaN, no error."""
    df = pd.DataFrame(
        {"high": [101.0], "low": [99.0]},
        index=pd.DatetimeIndex([_ts("09:30")]),
    )
    out = estimate_spread_from_high_low(df)
    assert len(out) == 1
    assert math.isnan(out.iloc[0])


def test_combined_spread_and_impact():
    """Cost = spread*mult + impact when all components are active."""
    idx = pd.DatetimeIndex([_ts("12:00")])
    spread = pd.Series([3.0], index=idx)
    curve = default_us_equity_curve()
    model = IntradayCostModel(
        base_bps=1.0,
        bid_ask_bps=spread,
        participation_curve=curve,
        impact_coef=0.1,
        adv=1_000_000.0,
    )
    # qty=10000, adv=1e6 -> participation 0.01, impact = 0.1*sqrt(0.01)*100 = 1.0 bps
    # Use 12:45 -> exact midpoint of 09:30-16:00 -> multiplier = 0.8 exactly.
    cost = model.cost_bps(price=100.0, qty=10_000.0, timestamp=_ts("12:45"))
    expected = 3.0 * 0.8 + 1.0
    assert cost == pytest.approx(expected, rel=1e-9)


def test_us_equity_curve_endpoints():
    """Curve is exactly 2.5 at 0 and 1, exactly 0.8 at 0.5."""
    curve = default_us_equity_curve()
    assert curve(0.0) == pytest.approx(2.5)
    assert curve(1.0) == pytest.approx(2.5)
    assert curve(0.5) == pytest.approx(0.8)


def test_bid_ask_lookup_uses_prior_bar():
    """Timestamp not in index uses nearest prior value."""
    idx = pd.DatetimeIndex([_ts("09:30"), _ts("10:00")])
    spread = pd.Series([3.0, 7.0], index=idx)
    model = IntradayCostModel(base_bps=1.0, bid_ask_bps=spread)
    # 09:45 is between bars -> should use 09:30 value (3.0)
    cost = model.cost_bps(price=100.0, qty=1.0, timestamp=_ts("09:45"))
    assert cost == pytest.approx(3.0)
    # 10:30 is after last bar -> uses 10:00 value (7.0)
    cost2 = model.cost_bps(price=100.0, qty=1.0, timestamp=_ts("10:30"))
    assert cost2 == pytest.approx(7.0)


def test_bid_ask_lookup_before_first_bar_falls_back():
    """Timestamp before first index -> fall back to base_bps."""
    idx = pd.DatetimeIndex([_ts("10:00")])
    spread = pd.Series([7.0], index=idx)
    model = IntradayCostModel(base_bps=1.5, bid_ask_bps=spread)
    cost = model.cost_bps(price=100.0, qty=1.0, timestamp=_ts("09:30"))
    assert cost == pytest.approx(1.5)


def test_corwin_schultz_three_bar_handcomputed():
    """3-bar hand-computed example: H=[100,101,100], L=[99,100,99].

    Verifies the closed-form Corwin-Schultz spread for each pairwise
    (t-1, t) bar against the analytical formula within 1e-4 absolute.
    """
    high = [100.0, 101.0, 100.0]
    low = [99.0, 100.0, 99.0]
    df = pd.DataFrame(
        {"high": high, "low": low},
        index=pd.DatetimeIndex([_ts("09:30"), _ts("09:31"), _ts("09:32")]),
    )
    out = estimate_spread_from_high_low(df)

    # First entry must be NaN
    assert math.isnan(out.iloc[0])

    denom = 3.0 - 2.0 * math.sqrt(2.0)
    for t in (1, 2):
        log_hl_sq_curr = math.log(high[t] / low[t]) ** 2
        log_hl_sq_prev = math.log(high[t - 1] / low[t - 1]) ** 2
        beta = log_hl_sq_curr + log_hl_sq_prev
        h2 = max(high[t], high[t - 1])
        l2 = min(low[t], low[t - 1])
        gamma = math.log(h2 / l2) ** 2
        alpha = (
            (math.sqrt(2.0 * beta) - math.sqrt(beta)) / denom
            - math.sqrt(gamma / denom)
        )
        spread_prop = 2.0 * (math.exp(alpha) - 1.0) / (1.0 + math.exp(alpha))
        if spread_prop < 0.0:
            spread_prop = 0.0
        expected_bps = spread_prop * 1e4 / 2.0
        assert out.iloc[t] == pytest.approx(expected_bps, abs=1e-4)
