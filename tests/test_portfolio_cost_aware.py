# ruff: noqa: N806
"""Tests for the cost-aware optimisation wrapper (R171).

Covers:
- Turnover penalty reduces churn vs no-cost baseline.
- Transaction-cost rate scales with notional.
- Refusal when costs exceed the gross edge.
- Determinism with a fixed seed.
"""
from __future__ import annotations

import numpy as np
import pytest
from aurora.portfolio import (
    ConstraintViolation,
    EqualWeightAllocator,
    InverseVolAllocator,
    PortfolioConstraints,
    PortfolioProblem,
    PortfolioSolution,
    optimise_cost_aware,
)


def _synth_returns(seed: int = 0, T: int = 200, N: int = 4) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0008, 0.012, size=(T, N))


def _flat_loss_returns(seed: int, T: int = 60, N: int = 3) -> np.ndarray:
    """Returns where every asset has slightly negative drift -- so the
    optimiser will *want* to trade but trading produces no edge."""
    rng = np.random.default_rng(seed)
    return rng.normal(-0.0005, 0.005, size=(T, N))


# --------------------------------------------------------------------------- #
# Turnover & cost basics                                                      #
# --------------------------------------------------------------------------- #
def test_turnover_zero_when_previous_equals_target():
    R = _synth_returns(seed=51, T=120, N=4)
    target = np.array([0.25, 0.25, 0.25, 0.25])
    p = PortfolioProblem(returns=R, previous_weights=target)
    sol = optimise_cost_aware(
        EqualWeightAllocator(), p, cost_rate=0.001,
    )
    assert sol.turnover == pytest.approx(0.0, abs=1e-12)
    assert sol.costs == pytest.approx(0.0, abs=1e-12)


def test_cost_scales_linearly_with_rate():
    R = _synth_returns(seed=52, T=120, N=4)
    prev = np.array([1.0, 0.0, 0.0, 0.0])
    p = PortfolioProblem(returns=R, previous_weights=prev)
    # Disable the cost-vs-edge refusal so we can test pure cost mechanics.
    s_low = optimise_cost_aware(
        EqualWeightAllocator(),
        p,
        cost_rate=0.0001,
        max_cost_to_edge_ratio=float("inf"),
    )
    s_high = optimise_cost_aware(
        EqualWeightAllocator(),
        p,
        cost_rate=0.001,
        max_cost_to_edge_ratio=float("inf"),
    )
    # Same turnover (target unchanged), 10x rate -> 10x cost.
    assert s_low.turnover == pytest.approx(s_high.turnover, abs=1e-12)
    assert s_low.turnover > 0
    assert s_high.costs == pytest.approx(10.0 * s_low.costs, rel=1e-9)


def test_high_cost_reduces_churn_vs_low_cost():
    """When the same allocator runs against the same problem with a
    high cost-to-edge ratio enforced, churn (turnover) is reduced
    relative to the no-refusal regime."""
    R = _flat_loss_returns(seed=58, T=80, N=3)
    prev = np.array([1.0, 0.0, 0.0])
    p = PortfolioProblem(returns=R, previous_weights=prev)
    s_no_refuse = optimise_cost_aware(
        EqualWeightAllocator(), p,
        cost_rate=0.05,
        max_cost_to_edge_ratio=float("inf"),
    )
    s_refuse = optimise_cost_aware(
        EqualWeightAllocator(), p,
        cost_rate=0.05,
        max_cost_to_edge_ratio=0.5,
    )
    # Refusal path keeps turnover at zero; no-refuse pays full turnover.
    assert s_no_refuse.turnover > s_refuse.turnover


def test_refusal_when_cost_exceeds_edge():
    R = _flat_loss_returns(seed=53, T=80, N=3)
    prev = np.array([1.0, 0.0, 0.0])  # all in asset 0
    p = PortfolioProblem(returns=R, previous_weights=prev)
    sol = optimise_cost_aware(
        EqualWeightAllocator(),
        p,
        cost_rate=0.05,  # very expensive
        max_cost_to_edge_ratio=0.5,
    )
    # Refused: weights stay at prev, costs zero, warnings non-empty.
    assert np.allclose(sol.weights, prev)
    assert sol.costs == 0.0
    assert sol.turnover == 0.0
    assert any("refused" in w for w in sol.warnings)


# --------------------------------------------------------------------------- #
# Constraint validation paths                                                 #
# --------------------------------------------------------------------------- #
def test_violation_raises_by_default_with_costs():
    R = _synth_returns(seed=54, T=120, N=3)
    p = PortfolioProblem(
        returns=R,
        constraints=PortfolioConstraints(
            min_weight=0.0, max_weight=0.2,  # 1/3 violates this
        ),
    )
    # Disable refusal so the violating equal-weight target is what gets
    # validated (otherwise refusal returns prev=0 which would NOT
    # violate max_weight=0.2).
    with pytest.raises(ConstraintViolation):
        optimise_cost_aware(
            EqualWeightAllocator(),
            p,
            cost_rate=0.001,
            max_cost_to_edge_ratio=float("inf"),
        )


def test_violation_warn_only_returns_solution():
    R = _synth_returns(seed=55, T=120, N=3)
    p = PortfolioProblem(
        returns=R,
        constraints=PortfolioConstraints(
            min_weight=0.0, max_weight=0.2,
        ),
    )
    sol = optimise_cost_aware(
        EqualWeightAllocator(),
        p,
        cost_rate=0.001,
        warn_only=True,
        max_cost_to_edge_ratio=float("inf"),
    )
    assert isinstance(sol, PortfolioSolution)
    assert sol.constraint_violations  # non-empty tuple


# --------------------------------------------------------------------------- #
# Determinism                                                                 #
# --------------------------------------------------------------------------- #
def test_cost_aware_deterministic_with_seed():
    R1 = _synth_returns(seed=66, T=200, N=4)
    R2 = _synth_returns(seed=66, T=200, N=4)
    p1 = PortfolioProblem(
        returns=R1,
        previous_weights=np.array([0.4, 0.3, 0.2, 0.1]),
    )
    p2 = PortfolioProblem(
        returns=R2,
        previous_weights=np.array([0.4, 0.3, 0.2, 0.1]),
    )
    s1 = optimise_cost_aware(InverseVolAllocator(), p1, cost_rate=0.0005)
    s2 = optimise_cost_aware(InverseVolAllocator(), p2, cost_rate=0.0005)
    assert np.array_equal(s1.weights, s2.weights)
    assert s1.costs == s2.costs
    assert s1.turnover == s2.turnover


# --------------------------------------------------------------------------- #
# Cost model integration (optional CostModel object)                          #
# --------------------------------------------------------------------------- #
def test_cost_model_path_uses_per_trade_bps():
    """When a CostModel is passed and exposes per_trade_bps(), the wrapper
    derives the rate from it. Without an explicit cost_rate, the bps
    figure should produce strictly positive cost."""
    from aurora.core.costs import CostModel

    cm = CostModel(commission_bps=2.0, spread_bps=1.0, slippage_bps=0.5)
    R = _synth_returns(seed=77, T=120, N=4)
    prev = np.array([1.0, 0.0, 0.0, 0.0])
    p = PortfolioProblem(returns=R, previous_weights=prev)
    sol = optimise_cost_aware(
        EqualWeightAllocator(),
        p,
        cost_model=cm,
        max_cost_to_edge_ratio=float("inf"),
    )
    assert sol.costs > 0.0
    # Sanity: cost should be ~ turnover * (per_trade_bps / 1e4).
    expected = sol.turnover * cm.per_trade_bps() / 1e4
    assert sol.costs == pytest.approx(expected, rel=1e-9)
