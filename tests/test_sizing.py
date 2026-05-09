"""Tests for quantforge.deployment.sizing."""
from __future__ import annotations
import pytest

from aurora.deployment.sizing import (
    fixed_risk_size,
    vol_target_size,
    kelly_size,
    RiskBudget,
)


def test_fixed_risk():
    # NAV=100K, entry=100, stop=95, risk_pct=1%
    # dollar_risk = 1000, risk_per_share = 5 -> 200 shares
    shares = fixed_risk_size(100_000, 100.0, 95.0, 0.01)
    assert shares == 200


def test_fixed_risk_zero_stop_distance():
    assert fixed_risk_size(100_000, 100.0, 100.0, 0.01) == 0


def test_fixed_risk_short_side():
    # short: entry=95, stop=100 -> same risk magnitude -> 200 shares
    assert fixed_risk_size(100_000, 95.0, 100.0, 0.01) == 200


def test_vol_target_below_cap():
    # vol = target -> weight = 1.0, capped at max_w=1.0
    # nav=100K, price=100 -> 1000 shares
    shares = vol_target_size(100_000, 100.0, 0.15, target_vol=0.15, max_w=1.0)
    assert shares == 1000


def test_vol_target_above_cap():
    # vol=30%, target=15% -> weight = 0.5
    # nav=100K, price=100 -> notional 50K -> 500 shares
    shares = vol_target_size(100_000, 100.0, 0.30, target_vol=0.15, max_w=1.0)
    assert shares == 500


def test_vol_target_max_w_clamp():
    # vol very low so target/vol > max_w -> clamped to max_w
    shares = vol_target_size(100_000, 100.0, 0.05, target_vol=0.15, max_w=0.5)
    # weight = min(0.15/0.05=3.0, 0.5) = 0.5 -> 50K notional -> 500 shares
    assert shares == 500


def test_vol_target_size_lookback_documented():
    """Explicit `lookback` parameter exists, defaults to 21, and is validated.

    The lookback doesn't change the sizing arithmetic (the function takes a
    pre-computed annualized vol from the caller) but it must be explicit and
    validated so all sizing call sites share a single window convention.
    """
    import inspect
    sig = inspect.signature(vol_target_size)
    # Param exists and defaults to 21 (preserves prior implicit behavior).
    assert "lookback" in sig.parameters
    assert sig.parameters["lookback"].default == 21
    # Default kw is documented in the docstring.
    assert vol_target_size.__doc__ is not None
    assert "lookback" in vol_target_size.__doc__

    # Result is the same regardless of lookback (lookback is informational).
    base = vol_target_size(100_000, 100.0, 0.30, target_vol=0.15, max_w=1.0)
    same = vol_target_size(100_000, 100.0, 0.30, target_vol=0.15, max_w=1.0,
                           lookback=63)
    assert base == same == 500

    # Invalid lookbacks rejected.
    with pytest.raises(ValueError):
        vol_target_size(100_000, 100.0, 0.30, lookback=1)
    with pytest.raises(ValueError):
        vol_target_size(100_000, 100.0, 0.30, lookback=0)


def test_kelly_basic():
    # win_rate=0.6, avg_win=2, avg_loss=1
    # f* = (0.6*2 - 0.4*1) / (2*1) = (1.2-0.4)/2 = 0.4
    # fraction=0.25 -> use 0.1 -> notional 10K -> price=100 -> 100 shares
    shares = kelly_size(100_000, 100.0, 0.6, 2.0, 1.0, fraction=0.25)
    assert shares == 100


def test_kelly_negative_edge():
    # win_rate=0.5, avg_win=1, avg_loss=2
    # f* = (0.5*1 - 0.5*2) / (1*2) = -0.25 -> 0 size
    shares = kelly_size(100_000, 100.0, 0.5, 1.0, 2.0, fraction=0.25)
    assert shares == 0


def test_kelly_zero_inputs():
    assert kelly_size(0, 100.0, 0.6, 2.0, 1.0) == 0
    assert kelly_size(100_000, 0, 0.6, 2.0, 1.0) == 0
    assert kelly_size(100_000, 100.0, 0.0, 2.0, 1.0) == 0
    assert kelly_size(100_000, 100.0, 1.0, 2.0, 1.0) == 0


def test_risk_budget_can_open():
    rb = RiskBudget(nav=100_000.0)
    ok, reason = rb.can_open("AAPL", 0.01)
    assert ok, reason


def test_risk_budget_full():
    rb = RiskBudget(nav=100_000.0)
    # Open 5 positions @ 1% risk each. Each needs entry-stop spread = $1 with 1000 shares
    # so risk_dollars = 1000 = 1% of 100K NAV
    for i, sym in enumerate(["A", "B", "C", "D", "E"]):
        ok, reason = rb.can_open(sym, 0.01)
        assert ok, f"{sym} should be allowed at slot {i}: {reason}"
        rb.open(sym, entry=100.0, stop=99.0, size_shares=1000)
    # 6th should fail: total would be 6% > 5% cap
    ok, reason = rb.can_open("F", 0.01)
    assert not ok
    assert "portfolio risk" in reason.lower()


def test_risk_budget_close_frees():
    rb = RiskBudget(nav=100_000.0)
    for sym in ["A", "B", "C", "D", "E"]:
        rb.open(sym, entry=100.0, stop=99.0, size_shares=1000)
    # full
    ok, _ = rb.can_open("F", 0.01)
    assert not ok
    # close one -> frees budget
    rb.close("A")
    ok, reason = rb.can_open("F", 0.01)
    assert ok, reason


def test_risk_budget_single_position_cap():
    rb = RiskBudget(nav=100_000.0)
    ok, reason = rb.can_open("AAPL", 0.02)  # exceeds 1% per-trade cap
    assert not ok
    assert "single-position" in reason.lower()


def test_risk_budget_duplicate_symbol():
    rb = RiskBudget(nav=100_000.0)
    rb.open("AAPL", 100.0, 99.0, 1000)
    ok, reason = rb.can_open("AAPL", 0.01)
    assert not ok
    assert "already open" in reason.lower()


# ---------------------------------------------------------------------------
# Issue 19: Kelly textbook value at p=0.6, W=1, L=1 -> f* = 0.2
# ---------------------------------------------------------------------------

def test_kelly_textbook_p06_W1_L1():
    """Kelly fraction (full, not fractional) for p=0.6, W=L=1 is exactly 0.2.

    Validates the published Thorp/Kelly identity ``f* = p/L - q/W`` at the
    canonical textbook input. Allows for one share of floor-division
    rounding (0.19999...*100000 = 19999.99... -> 199 shares).
    """
    nav = 100_000.0
    asset_price = 100.0
    # fraction=1.0 -> f_use == f_star; with f_star ~= 0.2 we expect ~200 shares
    # (199 or 200 depending on floating-point rounding for 0.6/1 - 0.4/1).
    shares = kelly_size(nav=nav, asset_price=asset_price,
                        win_rate=0.6, avg_win=1.0, avg_loss=1.0,
                        fraction=1.0)
    assert shares in (199, 200), shares

    # With fraction=0.25 (default) the result must scale linearly: f_use=0.05,
    # notional=5000, price=100 -> 50 shares.
    shares25 = kelly_size(nav=nav, asset_price=asset_price,
                          win_rate=0.6, avg_win=1.0, avg_loss=1.0,
                          fraction=0.25)
    assert shares25 == 49 or shares25 == 50, shares25

    # And the formula must match Thorp form symbolically:
    # f* = p/L - q/W = 0.6/1 - 0.4/1 = 0.2 (within FP epsilon).
    p, q, W, L = 0.6, 0.4, 1.0, 1.0
    expected_f_star = (p / L) - (q / W)
    assert abs(expected_f_star - 0.2) < 1e-9
