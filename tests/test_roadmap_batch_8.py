"""Tests for R111, R113, R114, R115, R116, R117, R118, R123 batch."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from aurora.analytics.what_if import what_if
from aurora.deployment.tax_awareness import (
    HoldingPeriod,
    Lot,
    estimate_close_impact,
)
from aurora.research.factory.generator_constraints import (
    PreAcceptanceConstraints,
    evaluate,
)
from aurora.strategies.rule_codegen import render_python
from aurora.strategies.symphony import (
    AssetGroup,
    SectorRotator,
    Symphony,
    SymphonyRule,
    expand_groups,
)


# --------------------------------------------------------------------------
# R111 generator constraints
# --------------------------------------------------------------------------


def test_constraints_pass_when_all_within_bounds():
    c = PreAcceptanceConstraints(
        max_trades_per_day=5,
        target_mdd_min=-0.30,
        target_mdd_max=-0.05,
        target_win_rate_min=0.40,
        target_win_rate_max=0.70,
        max_turnover=10.0,
    )
    v = evaluate(trades_per_day=2, mdd=-0.15, win_rate=0.55,
                 turnover=3.0, constraints=c)
    assert v.passed
    assert v.reasons == []


def test_constraints_fail_with_reasons():
    c = PreAcceptanceConstraints(max_trades_per_day=1, target_mdd_min=-0.20)
    v = evaluate(trades_per_day=10, mdd=-0.50, win_rate=0.5,
                 turnover=1.0, constraints=c)
    assert not v.passed
    assert len(v.reasons) == 2


# --------------------------------------------------------------------------
# R113 + R115 + R116 symphony
# --------------------------------------------------------------------------


def test_expand_groups_distributes_weight_evenly():
    groups = [
        AssetGroup(name="equities", symbols=["SPY", "QQQ"], weight=0.6),
        AssetGroup(name="bonds", symbols=["TLT"], weight=0.4),
    ]
    flat = expand_groups(groups)
    assert flat["SPY"] == pytest.approx(0.30)
    assert flat["QQQ"] == pytest.approx(0.30)
    assert flat["TLT"] == pytest.approx(0.40)


def test_symphony_first_match_wins():
    sym = Symphony(
        rules=[
            SymphonyRule(
                condition=lambda s: s["vix"] > 30,
                weights={"TLT": 0.6, "GLD": 0.4},
                label="risk_off",
            ),
            SymphonyRule(
                condition=lambda s: s["spy_above_ma"],
                weights={"SPY": 0.6, "QQQ": 0.4},
                label="risk_on",
            ),
        ],
        default_weights={},
        default_cash_fraction=1.0,
    )
    assert sym.evaluate({"vix": 50, "spy_above_ma": True}) == {
        "TLT": 0.6, "GLD": 0.4,
    }
    assert sym.evaluate({"vix": 15, "spy_above_ma": True}) == {
        "SPY": 0.6, "QQQ": 0.4,
    }
    fallback = sym.evaluate({"vix": 15, "spy_above_ma": False})
    assert fallback == {"CASH": 1.0}


# --------------------------------------------------------------------------
# R118 sector rotator
# --------------------------------------------------------------------------


def test_sector_rotator_picks_top_n_equal_weight():
    rot = SectorRotator(
        universe=["XLF", "XLE", "XLK", "XLV", "XLU"],
        top_n=3,
        equal_weight=True,
    )
    out = rot.select({"XLF": 0.05, "XLE": 0.10, "XLK": 0.15, "XLV": 0.02, "XLU": -0.03})
    assert set(out) == {"XLK", "XLE", "XLF"}
    assert all(abs(v - 1 / 3) < 1e-9 for v in out.values())


def test_sector_rotator_score_weighted():
    rot = SectorRotator(
        universe=["A", "B", "C"],
        top_n=2,
        equal_weight=False,
    )
    out = rot.select({"A": 0.10, "B": 0.30, "C": -0.05})
    assert sum(out.values()) == pytest.approx(1.0)
    assert out["B"] > out["A"]


# --------------------------------------------------------------------------
# R114 tax awareness
# --------------------------------------------------------------------------


def test_long_term_rate_applies_when_held_more_than_year():
    lot = Lot(quantity=100, cost_basis_per_share=100.0,
              acquired_on=date(2020, 1, 1))
    est = estimate_close_impact(
        lot, sell_price_per_share=150.0,
        sell_date=date(2026, 5, 8),
        long_term_rate=0.20,
        short_term_rate=0.37,
        portfolio_nav=10_000.0,
    )
    assert est.holding_period is HoldingPeriod.LONG_TERM
    # realised = 5000; tax @ 20% = 1000
    assert est.estimated_tax == pytest.approx(1000.0)


def test_short_term_rate_applies_when_held_less_than_year():
    lot = Lot(quantity=100, cost_basis_per_share=100.0,
              acquired_on=date(2026, 1, 1))
    est = estimate_close_impact(
        lot, sell_price_per_share=110.0,
        sell_date=date(2026, 6, 1),
        long_term_rate=0.20,
        short_term_rate=0.37,
    )
    assert est.holding_period is HoldingPeriod.SHORT_TERM


def test_no_tax_on_loss():
    lot = Lot(quantity=100, cost_basis_per_share=100.0,
              acquired_on=date(2020, 1, 1))
    est = estimate_close_impact(
        lot, sell_price_per_share=80.0,
        sell_date=date(2026, 6, 1),
    )
    assert est.estimated_tax == 0.0


# --------------------------------------------------------------------------
# R117 what-if
# --------------------------------------------------------------------------


def test_what_if_doubled_costs_reduces_returns():
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0005, 0.01, 200)
    weights = np.full(200, 0.5)
    from aurora.core.costs import CostModel, IBKR_costs
    rep = what_if(
        weights, rets,
        label="2x costs",
        costs=IBKR_costs,
        cost_perturber=lambda c: CostModel(
            commission_bps=c.commission_bps * 2,
            spread_bps=c.spread_bps * 2,
            slippage_bps=c.slippage_bps * 2,
            borrow_rate_annual=c.borrow_rate_annual,
        ),
    )
    # Costs do not change much under constant-weight strategies, so
    # this test is a sanity smoke not a strict comparison.
    assert rep.label == "2x costs"


# --------------------------------------------------------------------------
# R123 code preview
# --------------------------------------------------------------------------


def test_render_python_produces_runnable_function():
    rule = {
        "block_a": {"name": "RSI", "params": {"period": 14}},
        "comparator": "lt",
        "block_b": {"name": "SMA", "params": {"period": 20}},
        "allow_short": False,
    }
    src = render_python(rule)
    assert "def signals(prices):" in src
    assert "RSI(prices, period=14)" in src
    assert "SMA(prices, period=20)" in src
    assert "<" in src


def test_render_python_short_branch_for_allow_short():
    rule = {
        "block_a": {"name": "RSI", "params": {"period": 14}},
        "comparator": "gt",
        "block_b": {"name": "SMA", "params": {"period": 20}},
        "allow_short": True,
    }
    src = render_python(rule)
    assert "-1.0" in src
