"""Tests for aurora.core.costs (CostModel parameters and apply_costs).

Run: uv run pytest aurora/tests/test_costs.py -v
"""
from __future__ import annotations

import numpy as np
import pytest

from aurora.core.costs import (
    CONSERVATIVE_costs,
    CostModel,
    IBKR_costs,
    ZERO_costs,
    apply_costs,
)


# ---------------------------------------------------------------------------
# per_trade_bps + partial_fill_factor
# ---------------------------------------------------------------------------

def test_per_trade_bps_default_full_fill():
    """Default factor 1.0 reproduces commission + 2*spread + 2*slippage."""
    m = CostModel(commission_bps=0.5, spread_bps=1.0, slippage_bps=2.0)
    expected = 0.5 + 2 * 1.0 + 2 * 2.0  # = 6.5
    assert m.per_trade_bps() == pytest.approx(expected)
    assert m.per_trade_bps(partial_fill_factor=1.0) == pytest.approx(expected)


def test_partial_fill_factor_scales_cost():
    """Lower partial_fill_factor inflates slippage continuously as 2/factor.

    With factor=1.0: slippage_mult = 2.0 (full fill).
    With factor=0.5: slippage_mult = 4.0 (cost ~doubles).
    """
    m = CostModel(commission_bps=0.5, spread_bps=1.0, slippage_bps=2.0)
    full = m.per_trade_bps(partial_fill_factor=1.0)
    half = m.per_trade_bps(partial_fill_factor=0.5)
    quarter = m.per_trade_bps(partial_fill_factor=0.25)

    # full-fill: slippage_mult = 2/1.0 = 2 -> 0.5 + 2 + 4 = 6.5
    expected_full = 0.5 + 2 * 1.0 + 2.0 * 2.0
    # half-fill: slippage_mult = 2/0.5 = 4 -> 0.5 + 2 + 8 = 10.5
    expected_half = 0.5 + 2 * 1.0 + 4.0 * 2.0
    # quarter-fill: slippage_mult = 2/0.25 = 8 -> 0.5 + 2 + 16 = 18.5
    expected_quarter = 0.5 + 2 * 1.0 + 8.0 * 2.0

    assert full == pytest.approx(expected_full)
    assert half == pytest.approx(expected_half)
    assert quarter == pytest.approx(expected_quarter)
    # monotonic: lower factor -> higher cost
    assert quarter > half > full


def test_partial_fill_factor_invalid():
    m = CostModel(spread_bps=1.0, slippage_bps=2.0)
    with pytest.raises(ValueError):
        m.per_trade_bps(partial_fill_factor=0.0)
    with pytest.raises(ValueError):
        m.per_trade_bps(partial_fill_factor=-0.1)
    with pytest.raises(ValueError):
        m.per_trade_bps(partial_fill_factor=1.5)


# ---------------------------------------------------------------------------
# daily_borrow_cost + settlement_days + availability_haircut
# ---------------------------------------------------------------------------

def test_daily_borrow_default_unchanged():
    """Default args preserve original behavior."""
    m = CostModel(borrow_rate_annual=0.01)
    assert m.daily_borrow_cost(0.5) == pytest.approx(0.5 * 0.01 / 252.0)


def test_borrow_settlement_days():
    """settlement_days > 0 -> 0.0 (caller skips charge during settlement window)."""
    m = CostModel(borrow_rate_annual=0.05)
    # standard charge with no settlement
    assert m.daily_borrow_cost(1.0, settlement_days=0) == pytest.approx(0.05 / 252.0)
    # T+1: returns 0 (caller responsibility to defer)
    assert m.daily_borrow_cost(1.0, settlement_days=1) == 0.0
    # T+2: same -> 0
    assert m.daily_borrow_cost(0.5, settlement_days=2) == 0.0


def test_borrow_availability_haircut():
    """HTB haircut multiplies the borrow rate."""
    m = CostModel(borrow_rate_annual=0.01)
    base = m.daily_borrow_cost(1.0)
    htb = m.daily_borrow_cost(1.0, availability_haircut=0.5)
    # 0.5 haircut = 50% surcharge -> 1.5x base
    assert htb == pytest.approx(base * 1.5)

    htb2 = m.daily_borrow_cost(1.0, availability_haircut=1.0)
    assert htb2 == pytest.approx(base * 2.0)


def test_borrow_invalid_args():
    m = CostModel(borrow_rate_annual=0.01)
    with pytest.raises(ValueError):
        m.daily_borrow_cost(1.0, settlement_days=-1)
    with pytest.raises(ValueError):
        m.daily_borrow_cost(1.0, availability_haircut=-0.1)


# ---------------------------------------------------------------------------
# apply_costs sanity (no regression)
# ---------------------------------------------------------------------------

def test_apply_costs_zero_costs_returns_gross():
    """ZERO_costs -> net == w[t-1] * r[t]."""
    w = np.array([0, 1, 1, 0])
    r = np.array([0, 0.01, -0.005, 0.02])
    net = apply_costs(w, r, ZERO_costs)
    # net[0]=0, net[1]=w[0]*r[1]=0, net[2]=w[1]*r[2]=-0.005, net[3]=w[2]*r[3]=0.02
    assert net[0] == 0
    assert net[1] == 0
    assert net[2] == pytest.approx(-0.005)
    assert net[3] == pytest.approx(0.02)


def test_apply_costs_with_turnover():
    """Non-zero costs reduce return on turnover bars."""
    w = np.array([0, 1, 1, 0])
    r = np.array([0, 0.01, 0.0, 0.0])
    gross = apply_costs(w, r, ZERO_costs)
    net = apply_costs(w, r, IBKR_costs)
    # turnover at bar 1 (0->1) and bar 3 (1->0) -> both bars cost more
    assert net[1] < gross[1]
    assert net[3] < gross[3]


def test_apply_costs_short_borrow():
    """Short position pays daily borrow."""
    w = np.array([-1.0, -1.0, -1.0])
    r = np.array([0.0, 0.0, 0.0])
    cm = CostModel(borrow_rate_annual=0.252)  # 0.001/day
    net = apply_costs(w, r, cm)
    # bars 1 and 2: short notional 1.0, borrow ~0.001/day
    # (bar 0 zero: apply_costs returns 0 there because of the [1:] slice)
    assert net[1] == pytest.approx(-0.001, abs=1e-9)
    assert net[2] == pytest.approx(-0.001, abs=1e-9)


def test_borrow_uses_carried_position():
    """Borrow charge applies to the position CARRIED INTO each bar (weights[t-1]),
    not the position established at end of bar t. A bar that switches from long
    to short must NOT be charged borrow on the in-bar short — the position was
    long during that bar, only short for the next.
    """
    cm = CostModel(borrow_rate_annual=0.252)  # 0.001/day
    # Bar 0: flat. Bar 1: long (carried = flat -> no borrow).
    # Bar 2: short (carried = long -> no borrow).
    # Bar 3: short (carried = short -> borrow charged).
    w = np.array([0.0, 1.0, -1.0, -1.0])
    r = np.array([0.0, 0.0, 0.0, 0.0])
    net = apply_costs(w, r, cm)
    # Borrow should be charged ONLY on bar 3 (carried = short -1.0).
    assert net[1] == pytest.approx(0.0, abs=1e-12)
    assert net[2] == pytest.approx(0.0, abs=1e-12)
    assert net[3] == pytest.approx(-0.001, abs=1e-9)


# ---------------------------------------------------------------------------
# realistic cost-model smoke
# ---------------------------------------------------------------------------

def test_cost_model_constants_present():
    """Sanity: pre-built models have reasonable values."""
    assert ZERO_costs.commission_bps == 0.0
    assert IBKR_costs.commission_bps > 0
    assert CONSERVATIVE_costs.commission_bps > IBKR_costs.commission_bps
    assert CONSERVATIVE_costs.slippage_bps > IBKR_costs.slippage_bps
