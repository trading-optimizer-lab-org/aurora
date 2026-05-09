# ruff: noqa: N806, N803
"""Tests for the Phase 4 portfolio package (Candidate F)."""
from __future__ import annotations

import numpy as np
import pytest
from aurora.portfolio import (
    BenchmarkTrackerAllocator,
    CashAllocator,
    EqualWeightAllocator,
    InverseVolAllocator,
    MeanRiskOptimizer,
    PortfolioConstraints,
    RiskBudgetingOptimizer,
    SkfolioAdapter,
    StressResult,
    StressScenario,
    avg_drawdown,
    cvar,
    max_drawdown,
    semi_variance,
    stress_test,
    turnover_aware_net_return,
    variance,
)
from aurora.validation.portfolio_validation import (
    purged_walk_forward_portfolio,
    walk_forward_portfolio,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #
def _synth_returns(seed: int = 0, T: int = 400, N: int = 4) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = rng.normal(0.0005, 0.01, size=(T, N))
    # Make the last column visibly more volatile.
    base[:, -1] *= 3.0
    return base


# --------------------------------------------------------------------------- #
# Allocators                                                                  #
# --------------------------------------------------------------------------- #
def test_equal_weight_sum_one_and_uniform():
    R = _synth_returns(seed=1, T=200, N=5)
    alloc = EqualWeightAllocator().fit(R)
    w = alloc.predict()
    assert w.shape == (5,)
    assert np.allclose(w, 0.2)
    assert pytest.approx(w.sum(), abs=1e-12) == 1.0


def test_inverse_vol_high_vol_gets_lower_weight():
    R = _synth_returns(seed=2, T=400, N=4)  # last col is 3x vol
    alloc = InverseVolAllocator().fit(R)
    w = alloc.predict()
    assert pytest.approx(w.sum(), abs=1e-9) == 1.0
    # Last (highest-vol) asset must get the smallest weight.
    assert w[-1] < w[0]
    assert w[-1] < w[1]
    assert w[-1] < w[2]


def test_cash_allocator_zero_weights():
    R = _synth_returns(seed=3, T=100, N=3)
    alloc = CashAllocator().fit(R)
    w = alloc.predict()
    assert w.shape == (3,)
    assert np.allclose(w, 0.0)


def test_benchmark_tracker_matches_input():
    R = _synth_returns(seed=4, T=120, N=4)
    bench = np.array([0.4, 0.3, 0.2, 0.1])
    alloc = BenchmarkTrackerAllocator(bench).fit(R)
    w = alloc.predict()
    assert np.allclose(w, bench)


def test_benchmark_tracker_size_mismatch_raises():
    R = _synth_returns(seed=5, T=50, N=3)
    bench = np.array([0.5, 0.5])
    with pytest.raises(ValueError):
        BenchmarkTrackerAllocator(bench).fit(R)


# --------------------------------------------------------------------------- #
# Constraints                                                                 #
# --------------------------------------------------------------------------- #
def test_constraints_min_max_bounds():
    c = PortfolioConstraints(min_weight=0.05, max_weight=0.5, long_only=True)
    bad_low = np.array([0.0, 0.5, 0.5])  # 0.0 below 0.05
    bad_high = np.array([0.6, 0.3, 0.1])  # 0.6 above 0.5
    good = np.array([0.4, 0.3, 0.3])
    assert c.validate(bad_low)
    assert c.validate(bad_high)
    assert not c.validate(good)


def test_constraints_long_only_rejects_negative():
    c = PortfolioConstraints(long_only=True)
    w = np.array([-0.1, 0.6, 0.5])
    violations = c.validate(w)
    assert any("long_only" in v for v in violations)


def test_constraints_group_max():
    c = PortfolioConstraints(
        group_max={"tech": 0.4},
    )
    weights = np.array([0.3, 0.3, 0.2, 0.2])
    labels = ["tech", "tech", "fin", "energy"]
    violations = c.validate(weights, group_labels=labels)
    assert any("group_max" in v for v in violations)
    # Lower the tech weight: passes.
    weights2 = np.array([0.2, 0.15, 0.4, 0.25])
    assert not c.validate(weights2, group_labels=labels)


def test_constraints_turnover_max():
    c = PortfolioConstraints(turnover_max=0.5)
    prev = np.array([0.5, 0.5, 0.0])
    new = np.array([0.0, 0.0, 1.0])  # turnover = 2.0
    violations = c.validate(new, previous_weights=prev)
    assert any("turnover" in v for v in violations)


def test_constraints_invalid_construction():
    with pytest.raises(ValueError):
        PortfolioConstraints(min_weight=0.6, max_weight=0.5)
    with pytest.raises(ValueError):
        PortfolioConstraints(cash_floor=1.5)


# --------------------------------------------------------------------------- #
# Risk measures                                                               #
# --------------------------------------------------------------------------- #
def test_variance_finite_and_nonneg():
    rng = np.random.default_rng(10)
    r = rng.normal(0.0, 0.01, 500)
    v = variance(r)
    assert np.isfinite(v)
    assert v >= 0.0


def test_semi_variance_only_downside():
    r = np.array([0.01, 0.02, -0.03, -0.01, 0.0])
    sv = semi_variance(r, threshold=0.0)
    expected = float(np.mean(np.array([(-0.03) ** 2, (-0.01) ** 2])))
    assert pytest.approx(sv, rel=1e-9) == expected
    # Pure-positive series should have zero semi-variance.
    assert semi_variance(np.array([0.01, 0.02, 0.03])) == 0.0


def test_cvar_positive_loss():
    rng = np.random.default_rng(11)
    r = rng.normal(0.0, 0.01, 1000)
    val = cvar(r, alpha=0.05)
    assert np.isfinite(val)
    assert val > 0.0


def test_cvar_invalid_alpha():
    with pytest.raises(ValueError):
        cvar(np.array([0.01, 0.02]), alpha=1.5)


def test_max_drawdown_known_path():
    # +10% then -20% then +5% -- mdd happens at the trough.
    r = np.array([0.10, -0.20, 0.05])
    mdd = max_drawdown(r)
    # Equity: 1.10, 0.88, 0.924; peak=1.10; trough=0.88; mdd=(1.10-0.88)/1.10
    assert pytest.approx(mdd, rel=1e-9) == (1.10 - 0.88) / 1.10


def test_avg_drawdown_nonneg_and_le_max():
    r = np.array([0.05, -0.10, -0.05, 0.02, -0.03])
    a = avg_drawdown(r)
    m = max_drawdown(r)
    assert 0.0 <= a <= m + 1e-12


def test_turnover_aware_net_return_costs_only_hurt():
    rng = np.random.default_rng(12)
    R = rng.normal(0.0005, 0.01, size=(50, 3))
    # Vary weights every period to ensure turnover > 0.
    W = rng.uniform(0.0, 1.0, size=(50, 3))
    W = W / W.sum(axis=1, keepdims=True)

    no_cost = turnover_aware_net_return(W, R, costs_bps=0.0)
    high_cost = turnover_aware_net_return(W, R, costs_bps=20.0)

    assert pytest.approx(no_cost["net_return"], abs=1e-12) == no_cost["gross_return"]
    # With positive costs the net return must be <= gross.
    assert high_cost["net_return"] <= high_cost["gross_return"] + 1e-12
    assert high_cost["cost"] >= 0.0
    assert high_cost["turnover"] > 0.0


# --------------------------------------------------------------------------- #
# Optimizers                                                                  #
# --------------------------------------------------------------------------- #
def test_mean_risk_variance_respects_constraints():
    R = _synth_returns(seed=21, T=300, N=4)
    constraints = PortfolioConstraints(
        min_weight=0.05, max_weight=0.5, long_only=True
    )
    opt = MeanRiskOptimizer(
        risk_measure="variance",
        constraints=constraints,
    ).fit(R)
    w = opt.predict()
    violations = constraints.validate(w)
    assert violations == [], f"violations: {violations}"
    assert pytest.approx(w.sum(), abs=1e-6) == 1.0
    assert opt.summary()["n_assets"] == 4.0


def test_mean_risk_target_return_feasible():
    R = _synth_returns(seed=22, T=300, N=4)
    mu = R.mean(axis=0)
    target = float(mu.mean())  # achievable
    opt = MeanRiskOptimizer(
        risk_measure="variance",
        target_return=target,
    ).fit(R)
    w = opt.predict()
    achieved = float(np.dot(w, mu))
    # SLSQP can leave a tiny inequality slack -- allow modest tolerance.
    assert achieved >= target - 1e-4


def test_mean_risk_invalid_measure():
    with pytest.raises(ValueError):
        MeanRiskOptimizer(risk_measure="not_a_measure")


def test_risk_budgeting_converges_equal_rc():
    R = _synth_returns(seed=23, T=600, N=4)
    opt = RiskBudgetingOptimizer(max_iter=2000, tol=1e-9).fit(R)
    w = opt.predict()
    assert pytest.approx(w.sum(), abs=1e-6) == 1.0
    # Risk contributions should be roughly equal.
    Sigma = np.cov(R, rowvar=False, ddof=1)
    sw = Sigma @ w
    rc = w * sw
    rc_share = rc / rc.sum()
    # Equal RC target = 1/N. Tolerance is loose because SLSQP-free solver
    # uses a fixed-point iteration.
    assert np.max(np.abs(rc_share - 1.0 / R.shape[1])) < 0.05
    summary = opt.summary()
    assert summary["iterations"] >= 1.0


def test_risk_budgeting_custom_budgets_size_check():
    R = _synth_returns(seed=24, T=200, N=4)
    with pytest.raises(ValueError):
        RiskBudgetingOptimizer(risk_budgets=[0.5, 0.5]).fit(R)


# --------------------------------------------------------------------------- #
# Walk-forward                                                                #
# --------------------------------------------------------------------------- #
def test_walk_forward_split_no_overlap():
    R = _synth_returns(seed=31, T=400, N=3)
    folds = walk_forward_portfolio(
        EqualWeightAllocator(),
        R,
        train_bars=100,
        test_bars=50,
    )
    assert len(folds) >= 2
    for f in folds:
        # Train and test ranges must not overlap.
        assert f.train_end <= f.test_start
        assert f.test_end - f.test_start == 50
        assert f.train_end - f.train_start == 100
        # Metrics finite
        for v in f.metrics.values():
            assert np.isfinite(v)


def test_purged_walk_forward_embargo():
    R = _synth_returns(seed=32, T=500, N=3)
    folds = purged_walk_forward_portfolio(
        EqualWeightAllocator(),
        R,
        train_bars=120,
        test_bars=40,
        embargo_bars=10,
    )
    assert folds, "expected at least one fold"
    for f in folds:
        assert f.test_start - f.train_end == 10
        assert f.test_end - f.test_start == 40


# --------------------------------------------------------------------------- #
# Stress tests                                                                #
# --------------------------------------------------------------------------- #
def test_stress_test_higher_cost_reduces_net_return():
    R = _synth_returns(seed=41, T=300, N=4)
    scenarios = [
        StressScenario(name="baseline", cost_bps_multiplier=1.0),
        StressScenario(name="high_cost", cost_bps_multiplier=10.0),
    ]
    results = stress_test(
        EqualWeightAllocator(),
        R,
        scenarios=scenarios,
        base_costs_bps=5.0,
    )
    assert len(results) == 2
    base = next(r for r in results if r.scenario.name == "baseline")
    high = next(r for r in results if r.scenario.name == "high_cost")
    assert isinstance(base, StressResult)
    # Higher costs -> net_return should be <= baseline net_return.
    assert (
        high.metric_stressed["net_return"]
        <= base.metric_stressed["net_return"] + 1e-12
    )


def test_stress_test_drop_assets_has_zero_weight_effect():
    R = _synth_returns(seed=42, T=200, N=3)
    scenarios = [
        StressScenario(name="drop_first", drop_assets=(0,)),
    ]
    results = stress_test(
        EqualWeightAllocator(),
        R,
        scenarios=scenarios,
        base_costs_bps=0.0,
    )
    res = results[0]
    # Equal-weight allocator returns the same shape weights regardless
    # of perturbation; weight delta should therefore be 0.
    assert res.weight_delta_l1 == pytest.approx(0.0, abs=1e-12)
    # Test path metrics finite.
    for v in res.metric_stressed.values():
        assert np.isfinite(v)


# --------------------------------------------------------------------------- #
# Optional adapter                                                            #
# --------------------------------------------------------------------------- #
def test_skfolio_adapter_construct_or_skip():
    """Construction is always allowed; fit() may skip if skfolio missing."""
    adapter = SkfolioAdapter(estimator_name="MeanRisk")
    R = _synth_returns(seed=51, T=80, N=3)
    skfolio = pytest.importorskip("skfolio")
    assert skfolio is not None
    adapter.fit(R)
    w = adapter.predict()
    assert w.size == 3
