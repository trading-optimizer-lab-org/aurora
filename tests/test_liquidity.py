"""Tests for quantforge.deployment.liquidity (Task L.2)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.deployment.liquidity import (
    LiquidityAwarePortfolio,
    LiquidityProfile,
    adv_constrained_position,
    compute_liquidity_profile,
    liquidity_adjusted_size,
    liquidity_haircut,
    participation_rate_warning,
    _DEFAULT_ADV_THRESHOLDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _series_for_adv(target_adv_usd: float, price: float = 100.0,
                    n_days: int = 60) -> tuple[pd.Series, pd.Series]:
    """Build (prices, volumes) so price*volume mean ≈ target ADV."""
    idx = pd.date_range("2024-01-01", periods=n_days, freq="B")
    prices = pd.Series(np.full(n_days, price), index=idx, name="TEST")
    shares_per_day = target_adv_usd / price
    volume = pd.Series(np.full(n_days, shares_per_day), index=idx)
    return prices, volume


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_high_liquidity_classification():
    # ADV 500M -> high
    prices, volume = _series_for_adv(500_000_000.0)
    prof = compute_liquidity_profile(prices, volume)
    assert prof.classification == "high"
    assert prof.avg_daily_volume_usd == pytest.approx(500_000_000.0, rel=1e-6)
    assert prof.liquidity_score > 60.0


def test_medium_liquidity_classification():
    prices, volume = _series_for_adv(50_000_000.0)
    prof = compute_liquidity_profile(prices, volume)
    assert prof.classification == "medium"


def test_low_liquidity_classification():
    # ADV 5M -> low
    prices, volume = _series_for_adv(5_000_000.0)
    prof = compute_liquidity_profile(prices, volume)
    assert prof.classification == "low"
    assert prof.avg_daily_volume_usd == pytest.approx(5_000_000.0, rel=1e-6)


def test_illiquid_classification():
    # ADV 500K -> illiquid
    prices, volume = _series_for_adv(500_000.0)
    prof = compute_liquidity_profile(prices, volume)
    assert prof.classification == "illiquid"


# ---------------------------------------------------------------------------
# Haircuts
# ---------------------------------------------------------------------------


def test_haircut_factors():
    assert liquidity_haircut(1.0, "high") == pytest.approx(1.0)
    assert liquidity_haircut(1.0, "medium") == pytest.approx(0.7)
    assert liquidity_haircut(1.0, "low") == pytest.approx(0.4)
    assert liquidity_haircut(1.0, "illiquid") == pytest.approx(0.0)
    assert liquidity_haircut(0.5, "medium") == pytest.approx(0.35)


def test_illiquid_blocks():
    prof = LiquidityProfile(
        symbol="X",
        avg_daily_volume_usd=500_000.0,
        avg_spread_bps=80.0,
        days_above_threshold_pct=0.0,
        classification="illiquid",
        liquidity_score=5.0,
    )
    # Even with a $1M target and $500K ADV, illiquid haircut zeroes.
    sized = liquidity_adjusted_size(1_000_000.0, prof, max_pct_adv=0.5)
    assert sized == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# ADV cap
# ---------------------------------------------------------------------------


def test_adv_constrained_size_caps():
    # target $10M with ADV $100M and 5% cap -> max $5M, but high haircut=1.0
    prof = LiquidityProfile(
        symbol="X",
        avg_daily_volume_usd=100_000_000.0,
        avg_spread_bps=2.0,
        days_above_threshold_pct=100.0,
        classification="high",
        liquidity_score=80.0,
    )
    sized = liquidity_adjusted_size(10_000_000.0, prof, max_pct_adv=0.05)
    assert sized == pytest.approx(5_000_000.0, rel=1e-9)


def test_adv_constrained_position_caps_weight():
    # target weight 0.5 of $10M NAV = $5M; ADV $50M, 5% cap = $2.5M; price $100.
    adj_w, n_shares = adv_constrained_position(
        target_weight=0.5,
        nav=10_000_000.0,
        price=100.0,
        daily_volume_usd=50_000_000.0,
        max_pct_adv=0.05,
    )
    # Notional should be capped at $2.5M -> 25k shares -> weight 0.25.
    assert n_shares == 25_000
    assert adj_w == pytest.approx(0.25, rel=1e-9)


def test_adv_constrained_position_below_cap():
    # target 0.01 of $10M = $100K; ADV 100M, 5% cap = $5M -> not capped.
    adj_w, n_shares = adv_constrained_position(
        target_weight=0.01,
        nav=10_000_000.0,
        price=50.0,
        daily_volume_usd=100_000_000.0,
        max_pct_adv=0.05,
    )
    # 100K notional / $50 = 2000 shares.
    assert n_shares == 2000
    assert adj_w == pytest.approx(0.01, rel=1e-9)


def test_adv_constrained_position_zero_inputs():
    assert adv_constrained_position(0.0, 1e6, 100.0, 1e7) == (0.0, 0)
    assert adv_constrained_position(0.1, 0.0, 100.0, 1e7) == (0.0, 0)
    assert adv_constrained_position(0.1, 1e6, 0.0, 1e7) == (0.0, 0)
    assert adv_constrained_position(0.1, 1e6, 100.0, 0.0) == (0.0, 0)


# ---------------------------------------------------------------------------
# Participation warning
# ---------------------------------------------------------------------------


def test_participation_warning():
    # 15% of ADV crosses the 10% default threshold.
    msg = participation_rate_warning(15_000_000.0, 100_000_000.0)
    assert msg is not None
    assert "15.00%" in msg


def test_participation_no_warning_below_threshold():
    msg = participation_rate_warning(5_000_000.0, 100_000_000.0)
    assert msg is None


def test_participation_zero_adv():
    msg = participation_rate_warning(1_000_000.0, 0.0)
    assert msg is not None


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


def _profile(symbol: str, adv_usd: float, classification: str) -> LiquidityProfile:
    return LiquidityProfile(
        symbol=symbol,
        avg_daily_volume_usd=adv_usd,
        avg_spread_bps=5.0,
        days_above_threshold_pct=100.0,
        classification=classification,
        liquidity_score=75.0,
    )


def test_liquidity_aware_portfolio_redistributes():
    # NAV $10M, max_pct_adv=5%.
    # A: high, ADV 1B -> cap 5% * 1B = $50M -> > NAV, weight cap = 5.0 (no bind).
    # B: low, ADV 4M  -> cap 5% * 4M  = $200K, haircut 0.4 -> $80K -> 0.008 weight.
    # C: high, ADV 1B -> same as A.
    nav = 10_000_000.0
    profiles = {
        "A": _profile("A", 1_000_000_000.0, "high"),
        "B": _profile("B", 4_000_000.0, "low"),
        "C": _profile("C", 1_000_000_000.0, "high"),
    }
    port = LiquidityAwarePortfolio(profiles, nav=nav, max_pct_adv=0.05)
    raw = {"A": 0.4, "B": 0.4, "C": 0.2}
    adj = port.adjust_weights(raw)

    # B is severely capped.
    assert adj["B"] == pytest.approx(0.008, abs=1e-9)
    # Total adjusted weight equals raw total (slack redistributed).
    assert sum(adj.values()) == pytest.approx(sum(raw.values()), abs=1e-9)
    # Slack went to A and C in proportion to their raw weights (2:1).
    extra = (sum(raw.values()) - sum(adj.values())) + (adj["A"] + adj["C"]) - (raw["A"] + raw["C"])
    # A receives twice as much extra as C.
    a_extra = adj["A"] - raw["A"]
    c_extra = adj["C"] - raw["C"]
    assert a_extra > 0
    assert c_extra > 0
    assert a_extra == pytest.approx(2.0 * c_extra, rel=1e-6)


def test_liquidity_aware_portfolio_illiquid_blocked():
    nav = 1_000_000.0
    profiles = {
        "A": _profile("A", 1_000_000_000.0, "high"),
        "Z": _profile("Z", 200_000.0, "illiquid"),
    }
    port = LiquidityAwarePortfolio(profiles, nav=nav, max_pct_adv=0.05)
    adj = port.adjust_weights({"A": 0.5, "Z": 0.5})
    assert adj["Z"] == pytest.approx(0.0)
    # Slack from Z flows to A (its cap is huge).
    assert adj["A"] == pytest.approx(1.0, abs=1e-9)


def test_liquidity_aware_portfolio_unknown_symbol_blocked():
    nav = 1_000_000.0
    profiles = {"A": _profile("A", 1_000_000_000.0, "high")}
    port = LiquidityAwarePortfolio(profiles, nav=nav, max_pct_adv=0.05)
    adj = port.adjust_weights({"A": 0.5, "MISSING": 0.5})
    assert adj["MISSING"] == pytest.approx(0.0)
    assert adj["A"] == pytest.approx(1.0, abs=1e-9)


def test_liquidity_aware_portfolio_empty():
    profiles: dict[str, LiquidityProfile] = {}
    port = LiquidityAwarePortfolio(profiles, nav=1_000_000.0)
    assert port.adjust_weights({}) == {}


def test_liquidity_aware_portfolio_invalid_args():
    with pytest.raises(ValueError):
        LiquidityAwarePortfolio({}, nav=0.0)
    with pytest.raises(ValueError):
        LiquidityAwarePortfolio({}, nav=1_000_000.0, max_pct_adv=0.0)


# ---------------------------------------------------------------------------
# Profile edge cases
# ---------------------------------------------------------------------------


def test_compute_profile_disjoint_index_raises():
    p = pd.Series([100.0, 101.0], index=pd.date_range("2024-01-01", periods=2))
    v = pd.Series([1000.0, 1100.0], index=pd.date_range("2024-06-01", periods=2))
    with pytest.raises(ValueError):
        compute_liquidity_profile(p, v)


def test_compute_profile_with_spread_history():
    prices, volume = _series_for_adv(50_000_000.0)
    spreads = pd.Series(np.full(len(prices), 3.0), index=prices.index)
    prof = compute_liquidity_profile(prices, volume, spread_history=spreads)
    assert prof.avg_spread_bps == pytest.approx(3.0, rel=1e-9)


def test_score_monotonic_in_adv():
    p1, v1 = _series_for_adv(2_000_000.0)
    p2, v2 = _series_for_adv(200_000_000.0)
    s1 = compute_liquidity_profile(p1, v1).liquidity_score
    s2 = compute_liquidity_profile(p2, v2).liquidity_score
    assert s2 > s1


# ---------------------------------------------------------------------------
# Custom ADV thresholds (item 2)
# ---------------------------------------------------------------------------


def test_default_adv_thresholds_constants_exposed():
    """Module-level defaults expose the high/medium/low cutoffs."""
    assert set(_DEFAULT_ADV_THRESHOLDS.keys()) == {"high", "medium", "low"}
    # Default cutoffs match documented schedule (100M / 10M / 1M).
    assert _DEFAULT_ADV_THRESHOLDS["high"] == pytest.approx(100_000_000.0)
    assert _DEFAULT_ADV_THRESHOLDS["medium"] == pytest.approx(10_000_000.0)
    assert _DEFAULT_ADV_THRESHOLDS["low"] == pytest.approx(1_000_000.0)


def test_liquidity_custom_thresholds_respected():
    """Custom ADV_THRESHOLDS override default classification cutoffs.

    A 5M ADV is 'low' under the defaults but should be reclassified to
    'medium' when the medium cutoff is dropped to 1M. With higher cutoffs the
    same ADV becomes 'illiquid'.
    """
    prices, volume = _series_for_adv(5_000_000.0)

    # Sanity: under defaults, 5M -> low.
    default_prof = compute_liquidity_profile(prices, volume)
    assert default_prof.classification == "low"

    # Override -> 5M sits above the new medium cutoff (1M) and below high (50M)
    # -> classified as medium.
    custom = {"high": 50_000_000.0, "medium": 1_000_000.0, "low": 100_000.0}
    medium_prof = compute_liquidity_profile(
        prices, volume, ADV_THRESHOLDS=custom,
    )
    assert medium_prof.classification == "medium"
    assert medium_prof.avg_daily_volume_usd == pytest.approx(
        5_000_000.0, rel=1e-6,
    )

    # Override with very high cutoffs -> 5M too small even for 'low'.
    strict = {"high": 1e9, "medium": 1e8, "low": 1e7}
    illiquid_prof = compute_liquidity_profile(
        prices, volume, ADV_THRESHOLDS=strict,
    )
    assert illiquid_prof.classification == "illiquid"


def test_liquidity_custom_thresholds_partial_override():
    """Missing keys in ADV_THRESHOLDS fall back to defaults."""
    prices, volume = _series_for_adv(5_000_000.0)
    # Only override 'medium' -> medium cutoff = 1M, others default.
    prof = compute_liquidity_profile(
        prices, volume, ADV_THRESHOLDS={"medium": 1_000_000.0},
    )
    # 5M >= 1M (custom medium) and <= 100M (default high) -> medium.
    assert prof.classification == "medium"


# ---------------------------------------------------------------------------
# Redistribution residual slack (item 3)
# ---------------------------------------------------------------------------


def test_liquidity_redistribution_no_residual_slack():
    """When total ADV capacity exceeds raw weight sum, no residual is left."""
    nav = 10_000_000.0
    profiles = {
        "A": _profile("A", 1_000_000_000.0, "high"),
        "B": _profile("B", 4_000_000.0, "low"),
        "C": _profile("C", 1_000_000_000.0, "high"),
    }
    port = LiquidityAwarePortfolio(profiles, nav=nav, max_pct_adv=0.05)
    raw = {"A": 0.4, "B": 0.4, "C": 0.2}
    adj, residual = port.adjust_weights(raw, return_residual=True)
    # B is severely capped, but A and C have huge headroom; slack is
    # absorbed completely.
    assert residual == pytest.approx(0.0, abs=1e-9)
    assert sum(adj.values()) == pytest.approx(sum(raw.values()), abs=1e-9)


def test_liquidity_returns_residual_when_capped():
    """When total capacity < raw weight sum, leftover slack is reported."""
    # Tiny portfolio caps: every symbol is 'low' with small ADV. Their joint
    # capacity at 5%*ADV*haircut(0.4)/NAV totals < 1.0 so a fully-invested
    # request must leak.
    nav = 10_000_000.0
    profiles = {
        "X": _profile("X", 4_000_000.0, "low"),
        "Y": _profile("Y", 4_000_000.0, "low"),
        "Z": _profile("Z", 4_000_000.0, "low"),
    }
    port = LiquidityAwarePortfolio(profiles, nav=nav, max_pct_adv=0.05)
    # Per-symbol cap = 5% * 4M * 0.4 / 10M = 0.008. Three of them -> 0.024 max.
    raw = {"X": 0.4, "Y": 0.4, "Z": 0.2}  # total raw = 1.0
    adj, residual = port.adjust_weights(raw, return_residual=True)

    # Each symbol must be at its cap of 0.008.
    for sym in ("X", "Y", "Z"):
        assert adj[sym] == pytest.approx(0.008, abs=1e-9)

    # Total assigned ~= 0.024, residual ~= 1.0 - 0.024 = 0.976.
    assigned = sum(adj.values())
    assert assigned == pytest.approx(0.024, abs=1e-9)
    assert residual == pytest.approx(1.0 - assigned, abs=1e-9)


def test_liquidity_adjust_weights_back_compat():
    """Default call (no return_residual) still returns just the dict."""
    profiles = {"A": _profile("A", 1_000_000_000.0, "high")}
    port = LiquidityAwarePortfolio(profiles, nav=1_000_000.0, max_pct_adv=0.05)
    out = port.adjust_weights({"A": 0.5})
    assert isinstance(out, dict)
    assert out["A"] == pytest.approx(0.5, abs=1e-9)


def test_liquidity_residual_zero_when_empty():
    """Empty raw weights -> empty result, zero residual."""
    port = LiquidityAwarePortfolio({}, nav=1_000_000.0)
    out, residual = port.adjust_weights({}, return_residual=True)
    assert out == {}
    assert residual == 0.0
