# ruff: noqa: N806
"""Tests for the canonical PortfolioProblem / PortfolioSolution shapes
(R171). These cover:

- Equal weight, inverse vol and min-variance return valid solutions.
- Constraint violations raise by default and surface as data in
  warn-only mode.
- Solution carries weights + expected/realised risk + turnover + costs
  + warnings.
- Determinism with a fixed seed.
"""
from __future__ import annotations

import numpy as np
import pytest
from aurora.portfolio import (
    ConstraintViolation,
    EqualWeightAllocator,
    InverseVolAllocator,
    MeanRiskOptimizer,
    PortfolioConstraints,
    PortfolioProblem,
    PortfolioSolution,
    optimise_cost_aware,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #
def _synth_returns(seed: int = 0, T: int = 250, N: int = 4) -> np.ndarray:
    """Synthetic positive-drift returns (deterministic)."""
    rng = np.random.default_rng(seed)
    base = rng.normal(0.0008, 0.012, size=(T, N))
    base[:, -1] *= 2.5  # last column extra-volatile
    return base


# --------------------------------------------------------------------------- #
# PortfolioProblem construction                                               #
# --------------------------------------------------------------------------- #
def test_problem_construction_defaults_assets_and_sectors():
    R = _synth_returns(seed=11, T=80, N=3)
    p = PortfolioProblem(returns=R)
    assert p.n_assets == 3
    assert p.n_periods == 80
    assert p.asset_ids == ("asset_0", "asset_1", "asset_2")
    assert isinstance(p.constraints, PortfolioConstraints)


def test_problem_validates_asset_id_count_mismatch():
    R = _synth_returns(seed=12, T=20, N=3)
    with pytest.raises(ValueError, match="asset_ids"):
        PortfolioProblem(returns=R, asset_ids=("a", "b"))


def test_problem_validates_previous_weights_size():
    R = _synth_returns(seed=13, T=20, N=4)
    with pytest.raises(ValueError, match="previous_weights"):
        PortfolioProblem(
            returns=R,
            previous_weights=np.array([0.5, 0.5]),
        )


# --------------------------------------------------------------------------- #
# Equal weight, inverse vol, min variance return valid PortfolioSolution     #
# --------------------------------------------------------------------------- #
def test_equal_weight_solution_is_valid():
    R = _synth_returns(seed=21, T=200, N=4)
    p = PortfolioProblem(returns=R)
    sol = optimise_cost_aware(EqualWeightAllocator(), p)
    assert isinstance(sol, PortfolioSolution)
    assert sol.weights.shape == (4,)
    assert np.isclose(sol.weights.sum(), 1.0)
    assert sol.is_admissible
    # Expected and realised risk both populated and non-negative.
    assert sol.expected_risk >= 0.0
    assert sol.realised_risk >= 0.0


def test_inverse_vol_solution_carries_full_payload():
    R = _synth_returns(seed=22, T=300, N=4)
    p = PortfolioProblem(returns=R)
    sol = optimise_cost_aware(
        InverseVolAllocator(), p, risk_measure="variance",
    )
    # Sanity: high-vol asset got the smallest weight.
    assert sol.weights[-1] < sol.weights[0]
    # Payload completeness.
    assert sol.expected_risk >= 0.0
    assert sol.realised_risk >= 0.0
    assert sol.turnover >= 0.0
    assert sol.costs == 0.0  # no cost passed
    assert isinstance(sol.warnings, tuple)
    assert isinstance(sol.constraint_violations, tuple)


def test_min_variance_solution_respects_long_only():
    R = _synth_returns(seed=23, T=300, N=4)
    p = PortfolioProblem(
        returns=R,
        constraints=PortfolioConstraints(
            min_weight=0.0,
            max_weight=1.0,
            long_only=True,
        ),
    )
    opt = MeanRiskOptimizer(risk_measure="variance")
    sol = optimise_cost_aware(opt, p)
    assert sol.is_admissible
    assert (sol.weights >= -1e-9).all()
    assert np.isclose(sol.weights.sum(), 1.0, atol=1e-6)


# --------------------------------------------------------------------------- #
# Constraint violation: raises by default, surfaces in warn-only mode         #
# --------------------------------------------------------------------------- #
def test_constraint_violation_raises_by_default():
    R = _synth_returns(seed=31, T=120, N=3)
    # Force a violation: equal weight gives 1/3 ~ 0.333, set max=0.2.
    p = PortfolioProblem(
        returns=R,
        constraints=PortfolioConstraints(
            min_weight=0.0, max_weight=0.2, long_only=True,
        ),
    )
    with pytest.raises(ConstraintViolation) as exc_info:
        optimise_cost_aware(EqualWeightAllocator(), p)
    assert exc_info.value.violations  # non-empty


def test_constraint_violation_warn_only_mode_returns_solution():
    R = _synth_returns(seed=32, T=120, N=3)
    p = PortfolioProblem(
        returns=R,
        constraints=PortfolioConstraints(
            min_weight=0.0, max_weight=0.2, long_only=True,
        ),
    )
    sol = optimise_cost_aware(
        EqualWeightAllocator(), p, warn_only=True,
    )
    assert isinstance(sol, PortfolioSolution)
    assert not sol.is_admissible
    assert len(sol.constraint_violations) > 0


# --------------------------------------------------------------------------- #
# Determinism                                                                 #
# --------------------------------------------------------------------------- #
def test_solution_deterministic_with_seed():
    R1 = _synth_returns(seed=99, T=200, N=4)
    R2 = _synth_returns(seed=99, T=200, N=4)
    p1 = PortfolioProblem(returns=R1)
    p2 = PortfolioProblem(returns=R2)
    s1 = optimise_cost_aware(InverseVolAllocator(), p1)
    s2 = optimise_cost_aware(InverseVolAllocator(), p2)
    assert np.array_equal(s1.weights, s2.weights)
    assert s1.realised_risk == s2.realised_risk
    assert s1.expected_return == s2.expected_return


# --------------------------------------------------------------------------- #
# Solution serialisation                                                      #
# --------------------------------------------------------------------------- #
def test_solution_to_dict_contains_all_fields():
    R = _synth_returns(seed=41, T=120, N=3)
    p = PortfolioProblem(returns=R)
    sol = optimise_cost_aware(EqualWeightAllocator(), p)
    d = sol.to_dict()
    expected_keys = {
        "weights", "expected_risk", "realised_risk",
        "expected_return", "realised_return",
        "turnover", "costs",
        "warnings", "constraint_violations",
        "risk_measure", "metadata",
    }
    assert expected_keys.issubset(d.keys())
    assert isinstance(d["weights"], list)
