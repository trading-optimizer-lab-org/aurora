"""Tests for CVaR/CDaR optimization (Task H.2). Run:

    pytest quantforge/tests/test_risk_optim.py -v
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.deployment.risk_optim import (
    OptimResult,
    min_cvar,
    min_cdar,
    efficient_cvar_frontier,
    max_sharpe_cvar,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #
@pytest.fixture
def two_asset_returns():
    """Simple 2-asset case: 250 days, asset A low-vol mild drift,
    asset B higher-vol stronger drift."""
    rng = np.random.default_rng(7)
    n = 250
    a = rng.normal(0.0004, 0.008, n)
    b = rng.normal(0.0010, 0.020, n)
    idx = pd.date_range("2022-01-01", periods=n, freq="B")
    return pd.DataFrame({"A": a, "B": b}, index=idx)


@pytest.fixture
def four_asset_returns():
    """Diverse 4-asset universe for frontier tests."""
    rng = np.random.default_rng(13)
    n = 300
    cols = ["X", "Y", "Z", "W"]
    drifts = [0.0002, 0.0006, 0.0010, 0.0014]
    vols = [0.006, 0.012, 0.018, 0.025]
    data = {c: rng.normal(d, v, n) for c, d, v in zip(cols, drifts, vols)}
    idx = pd.date_range("2022-01-01", periods=n, freq="B")
    return pd.DataFrame(data, index=idx)


@pytest.fixture
def negative_only_returns():
    """All assets have strictly negative-mean returns."""
    rng = np.random.default_rng(3)
    n = 200
    a = rng.normal(-0.0010, 0.015, n)
    b = rng.normal(-0.0005, 0.010, n)
    idx = pd.date_range("2022-01-01", periods=n, freq="B")
    return pd.DataFrame({"A": a, "B": b}, index=idx)


# --------------------------------------------------------------------------- #
# CVaR basics                                                                 #
# --------------------------------------------------------------------------- #
def test_min_cvar_2_assets(two_asset_returns):
    res = min_cvar(two_asset_returns, alpha=0.05)
    assert isinstance(res, OptimResult)
    assert res.n_assets == 2
    assert set(res.weights.index) == {"A", "B"}
    assert res.weights.sum() == pytest.approx(1.0, abs=1e-6)
    assert (res.weights >= -1e-8).all()
    assert (res.weights <= 1.0 + 1e-8).all()
    assert "min_cvar" in res.method
    assert isinstance(res.objective_value, float)


def test_min_cvar_with_target_return(four_asset_returns):
    mu = four_asset_returns.mean()
    target = float(mu.median())  # achievable target
    res = min_cvar(four_asset_returns, alpha=0.05, target_return=target)
    achieved_mu = float((four_asset_returns.mean() * res.weights).sum())
    assert achieved_mu >= target - 1e-6
    assert res.weights.sum() == pytest.approx(1.0, abs=1e-6)


def test_weight_bounds_respected(four_asset_returns):
    res = min_cvar(four_asset_returns, alpha=0.05, weight_bounds=(0.05, 0.5))
    w = res.weights.values
    assert (w >= 0.05 - 1e-6).all()
    assert (w <= 0.5 + 1e-6).all()
    assert w.sum() == pytest.approx(1.0, abs=1e-6)


def test_negative_only_returns_handled(negative_only_returns):
    """Optimizer must still produce valid weights even when all means < 0."""
    res = min_cvar(negative_only_returns, alpha=0.05)
    assert res.weights.sum() == pytest.approx(1.0, abs=1e-6)
    assert (res.weights >= -1e-8).all()
    assert np.isfinite(res.objective_value)


# --------------------------------------------------------------------------- #
# CDaR                                                                        #
# --------------------------------------------------------------------------- #
def test_min_cdar_basic(two_asset_returns):
    res = min_cdar(two_asset_returns, alpha=0.05)
    assert isinstance(res, OptimResult)
    assert res.weights.sum() == pytest.approx(1.0, abs=1e-6)
    assert (res.weights >= -1e-8).all()
    assert "min_cdar" in res.method
    assert np.isfinite(res.objective_value)


def test_min_cdar_with_target_return(four_asset_returns):
    mu = four_asset_returns.mean()
    target = float(mu.iloc[1])  # mid-range target
    res = min_cdar(four_asset_returns, alpha=0.05, target_return=target)
    achieved = float((four_asset_returns.mean() * res.weights).sum())
    assert achieved >= target - 1e-6


# --------------------------------------------------------------------------- #
# Efficient frontier                                                          #
# --------------------------------------------------------------------------- #
def test_efficient_frontier_monotone(four_asset_returns):
    """Higher target_return should require higher CVaR (risk-return tradeoff).

    CVaR should be non-decreasing along the frontier (allow tiny numerical slack).
    """
    fr = efficient_cvar_frontier(four_asset_returns, n_points=8, alpha=0.05)
    assert isinstance(fr, pd.DataFrame)
    assert {"target_return", "cvar", "weights"}.issubset(fr.columns)
    assert len(fr) == 8
    valid = fr.dropna(subset=["cvar"])
    assert len(valid) >= 4
    # target_return should be strictly increasing by construction
    assert (np.diff(valid["target_return"].values) >= -1e-12).all()
    # CVaR should be non-decreasing along the frontier (with numerical slack)
    diffs = np.diff(valid["cvar"].values)
    assert (diffs >= -1e-4).all(), f"non-monotone CVaR: diffs={diffs}"


def test_efficient_frontier_weights_valid(four_asset_returns):
    fr = efficient_cvar_frontier(four_asset_returns, n_points=5, alpha=0.05)
    for _, row in fr.iterrows():
        if not row["weights"]:
            continue
        w = np.array(list(row["weights"].values()))
        assert w.sum() == pytest.approx(1.0, abs=1e-5)
        assert (w >= -1e-6).all()


# --------------------------------------------------------------------------- #
# Max Sharpe-CVaR                                                             #
# --------------------------------------------------------------------------- #
def test_max_sharpe_cvar(four_asset_returns):
    res = max_sharpe_cvar(four_asset_returns, alpha=0.05, risk_free_rate=0.0)
    assert isinstance(res, OptimResult)
    assert res.weights.sum() == pytest.approx(1.0, abs=1e-5)
    assert (res.weights >= -1e-6).all()
    assert "max_sharpe_cvar" in res.method
    # Final ratio embedded in constraints_active
    ratio_str = [s for s in res.constraints_active if s.startswith("max_ratio=")]
    assert len(ratio_str) == 1


def test_max_sharpe_cvar_higher_than_min_cvar(four_asset_returns):
    """Max-Sharpe-CVaR portfolio should have higher mean return than min-CVaR
    portfolio (it is willing to take more risk for return)."""
    minc = min_cvar(four_asset_returns, alpha=0.05)
    maxs = max_sharpe_cvar(four_asset_returns, alpha=0.05)
    mu = four_asset_returns.mean()
    mu_minc = float((mu * minc.weights).sum())
    mu_maxs = float((mu * maxs.weights).sum())
    assert mu_maxs >= mu_minc - 1e-9


# --------------------------------------------------------------------------- #
# Validation / errors                                                         #
# --------------------------------------------------------------------------- #
def test_min_cvar_rejects_invalid_alpha(two_asset_returns):
    with pytest.raises(ValueError):
        min_cvar(two_asset_returns, alpha=0.0)
    with pytest.raises(ValueError):
        min_cvar(two_asset_returns, alpha=1.5)


def test_min_cvar_rejects_nan(two_asset_returns):
    bad = two_asset_returns.copy()
    bad.iloc[0, 0] = np.nan
    with pytest.raises(ValueError):
        min_cvar(bad, alpha=0.05)


def test_min_cvar_rejects_infeasible_bounds(two_asset_returns):
    # lo_sum = 0.7+0.7 = 1.4 > 1 -> infeasible
    with pytest.raises(ValueError):
        min_cvar(two_asset_returns, weight_bounds=(0.7, 1.0))


def test_optimresult_to_dict(two_asset_returns):
    res = min_cvar(two_asset_returns, alpha=0.05)
    d = res.to_dict()
    assert set(d.keys()) == {"weights", "objective_value",
                             "constraints_active", "n_assets", "method"}
    assert isinstance(d["weights"], dict)


# --------------------------------------------------------------------------- #
# Asset-level feasibility check (Issue #5)                                    #
# --------------------------------------------------------------------------- #
def test_risk_optim_feasibility_check_min_w_exceeds_gross():
    """min_w * N > 1.0 should fail fast with ValueError."""
    rng = np.random.default_rng(0)
    N = 10
    T = 100
    R = rng.standard_normal((T, N)) * 0.01
    cols = [f"A{i}" for i in range(N)]
    idx = pd.date_range("2022-01-01", periods=T, freq="B")
    df = pd.DataFrame(R, index=idx, columns=cols)

    # min_w = 0.15, N = 10 -> 1.5 > gross_cap 1 -> infeasible.
    with pytest.raises(ValueError, match="infeasible"):
        min_cvar(df, alpha=0.05, weight_bounds=(0.15, 1.0))

    # Sanity: the boundary case (min_w * N = 1) should still work.
    # min_w = 0.1, N = 10 -> exactly 1.0
    res = min_cvar(df, alpha=0.05, weight_bounds=(0.1, 1.0))
    assert res.weights.sum() == pytest.approx(1.0, abs=1e-6)
    assert (res.weights >= 0.1 - 1e-6).all()


def test_risk_optim_feasibility_check_max_w_below_gross():
    """max_w * N < 1.0 should also fail fast."""
    rng = np.random.default_rng(0)
    N = 10
    T = 100
    R = rng.standard_normal((T, N)) * 0.01
    cols = [f"A{i}" for i in range(N)]
    idx = pd.date_range("2022-01-01", periods=T, freq="B")
    df = pd.DataFrame(R, index=idx, columns=cols)

    # max_w = 0.05 -> N*max_w = 0.5 < 1 -> infeasible.
    with pytest.raises(ValueError, match="infeasible"):
        min_cvar(df, alpha=0.05, weight_bounds=(0.0, 0.05))


# --------------------------------------------------------------------------- #
# Large-problem benchmark (Issue #4)                                          #
# --------------------------------------------------------------------------- #
def test_risk_optim_large_problem_memory():
    """min_cvar must solve T=1500, N=50 without MemoryError."""
    import time
    rng = np.random.default_rng(42)
    T, N = 1500, 50
    R = rng.standard_normal((T, N)) * 0.01
    cols = [f"A{i}" for i in range(N)]
    idx = pd.date_range("2018-01-01", periods=T, freq="B")
    df = pd.DataFrame(R, index=idx, columns=cols)

    t0 = time.perf_counter()
    res = min_cvar(df, alpha=0.05)
    elapsed = time.perf_counter() - t0
    assert res.weights.sum() == pytest.approx(1.0, abs=1e-5)
    assert (res.weights >= -1e-6).all()
    assert (res.weights <= 1.0 + 1e-6).all()
    assert np.isfinite(res.objective_value)
    # Should complete in well under 60s with sparse formulation.
    assert elapsed < 60.0, f"min_cvar large problem took {elapsed:.1f}s"


def test_risk_optim_cdar_large_problem_memory():
    """min_cdar at T=1500, N=20 must not blow up the cumsum substitution."""
    import time
    rng = np.random.default_rng(11)
    T, N = 1500, 20
    R = rng.standard_normal((T, N)) * 0.01
    cols = [f"A{i}" for i in range(N)]
    idx = pd.date_range("2018-01-01", periods=T, freq="B")
    df = pd.DataFrame(R, index=idx, columns=cols)

    t0 = time.perf_counter()
    res = min_cdar(df, alpha=0.05)
    elapsed = time.perf_counter() - t0
    assert res.weights.sum() == pytest.approx(1.0, abs=1e-5)
    assert np.isfinite(res.objective_value)
    assert elapsed < 120.0, f"min_cdar large problem took {elapsed:.1f}s"
