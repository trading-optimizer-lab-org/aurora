"""Tests for quantforge.analytics.attribution.

Run: pytest quantforge/tests/test_attribution.py -v
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd
import pytest

from quantforge.analytics.attribution import (
    AttributionResult,
    attribution_by_strategy,
    attribution_by_factor,
    attribution_by_time,
    brinson_attribution,
    annualized_attribution,
)


# --------------------------------------------------------------------------- #
# Stub AllocatorResult (duck-type, no actual import)                          #
# --------------------------------------------------------------------------- #
@dataclass
class _StubAllocatorResult:
    per_strategy_attribution: dict
    per_strategy_returns: dict
    weights: Optional[np.ndarray] = None
    strategy_names: Optional[list] = None


# --------------------------------------------------------------------------- #
# 1. attribution_by_strategy                                                  #
# --------------------------------------------------------------------------- #
def test_strategy_attribution_basic():
    """contributions DataFrame has expected rows + cols and matches inputs."""
    rng = np.random.default_rng(0)
    a_rets = rng.normal(0.001, 0.01, 200)
    b_rets = rng.normal(0.0005, 0.02, 200)
    stub = _StubAllocatorResult(
        per_strategy_attribution={"A": float(a_rets.sum()), "B": float(b_rets.sum())},
        per_strategy_returns={"A": a_rets, "B": b_rets},
    )

    res = attribution_by_strategy(stub, ppy=252)
    assert isinstance(res, AttributionResult)
    assert res.method == "by_strategy"
    assert set(res.contributions.index) == {"A", "B"}
    assert set(res.contributions.columns) == {"total_return", "sharpe", "mdd", "weight_avg"}
    # Total contribution columns must match inputs
    assert res.contributions.loc["A", "total_return"] == pytest.approx(a_rets.sum())
    assert res.contributions.loc["B", "total_return"] == pytest.approx(b_rets.sum())
    # Sum check
    assert res.total == pytest.approx(a_rets.sum() + b_rets.sum())
    # weight_avg should be NaN when no weights are provided
    assert np.isnan(res.contributions.loc["A", "weight_avg"])


def test_strategy_attribution_with_weights():
    """When weights + strategy_names provided, weight_avg is populated."""
    rng = np.random.default_rng(1)
    a_rets = rng.normal(0.001, 0.01, 100)
    b_rets = rng.normal(0.0005, 0.02, 100)
    weights = np.column_stack([np.full(100, 0.6), np.full(100, 0.4)])
    stub = _StubAllocatorResult(
        per_strategy_attribution={"A": float(a_rets.sum()), "B": float(b_rets.sum())},
        per_strategy_returns={"A": a_rets, "B": b_rets},
        weights=weights,
        strategy_names=["A", "B"],
    )
    res = attribution_by_strategy(stub)
    assert res.contributions.loc["A", "weight_avg"] == pytest.approx(0.6)
    assert res.contributions.loc["B", "weight_avg"] == pytest.approx(0.4)


# --------------------------------------------------------------------------- #
# 2. attribution_by_factor                                                    #
# --------------------------------------------------------------------------- #
def test_factor_attribution_ols_known_beta():
    """Strategy = 1.0 * factor + tiny noise -> recovered beta close to 1.0."""
    rng = np.random.default_rng(42)
    T = 500
    idx = pd.date_range("2020-01-01", periods=T, freq="B")
    f = pd.Series(rng.normal(0.0, 0.01, T), index=idx)
    eps = pd.Series(rng.normal(0.0, 0.0001, T), index=idx)  # tiny noise
    y = pd.Series(1.0 * f.values + eps.values, index=idx)

    res = attribution_by_factor(y, {"factor1": f}, method="ols")
    assert res.method == "factor_ols"
    beta = res.contributions.loc["factor1", "beta"]
    assert beta == pytest.approx(1.0, abs=0.05)
    # Partial R^2 should be close to 1 since factor explains everything
    assert res.contributions.loc["factor1", "r_squared_partial"] > 0.95


def test_factor_attribution_zero_alpha():
    """When y is exact linear combination of factors, total alpha ~ 0."""
    rng = np.random.default_rng(7)
    T = 400
    idx = pd.date_range("2020-01-01", periods=T, freq="B")
    f1 = pd.Series(rng.normal(0.0, 0.01, T), index=idx)
    f2 = pd.Series(rng.normal(0.0, 0.015, T), index=idx)
    y = pd.Series(0.5 * f1.values + 0.3 * f2.values, index=idx)

    res = attribution_by_factor(y, {"f1": f1, "f2": f2}, method="ols")
    # alpha total should be ~0 (no residual unexplained)
    assert res.total == pytest.approx(0.0, abs=1e-6)
    # betas should match generators
    assert res.contributions.loc["f1", "beta"] == pytest.approx(0.5, abs=0.01)
    assert res.contributions.loc["f2", "beta"] == pytest.approx(0.3, abs=0.01)


def test_factor_attribution_constrained_no_negative_beta():
    """Constrained NNLS must return beta >= 0."""
    rng = np.random.default_rng(13)
    T = 300
    idx = pd.date_range("2020-01-01", periods=T, freq="B")
    f1 = pd.Series(rng.normal(0.0, 0.01, T), index=idx)
    f2 = pd.Series(rng.normal(0.0, 0.01, T), index=idx)
    # y has negative correlation with f2 -> OLS would give negative beta
    y = pd.Series(0.7 * f1.values - 0.5 * f2.values + rng.normal(0, 0.001, T), index=idx)

    res = attribution_by_factor(y, {"f1": f1, "f2": f2}, method="constrained")
    assert res.method == "factor_constrained"
    assert (res.contributions["beta"] >= 0.0).all()


# --------------------------------------------------------------------------- #
# 3. attribution_by_time                                                      #
# --------------------------------------------------------------------------- #
def test_time_attribution_two_regimes():
    """bull vs bear regimes should produce different stats."""
    rng = np.random.default_rng(99)
    T = 400
    idx = pd.date_range("2020-01-01", periods=T, freq="B")
    # First 200 bars = bull (positive drift), last 200 = bear (negative drift)
    bull_rets = rng.normal(0.002, 0.01, 200)
    bear_rets = rng.normal(-0.002, 0.015, 200)
    rets = pd.Series(np.concatenate([bull_rets, bear_rets]), index=idx)
    labels = pd.Series(["bull"] * 200 + ["bear"] * 200, index=idx)

    res = attribution_by_time(rets, labels)
    assert res.method == "by_time"
    assert set(res.contributions.index) == {"bull", "bear"}
    bull_total = res.contributions.loc["bull", "total_return"]
    bear_total = res.contributions.loc["bear", "total_return"]
    # Bull should be positive, bear negative
    assert bull_total > 0.0
    assert bear_total < 0.0
    # Sum of regime totals equals grand total
    assert res.total == pytest.approx(bull_total + bear_total)
    # n column sums to T
    assert res.contributions["n"].sum() == T


# --------------------------------------------------------------------------- #
# 4. brinson_attribution                                                      #
# --------------------------------------------------------------------------- #
def test_brinson_decomposition_sums_to_total():
    """allocation + selection + interaction == total per category and overall."""
    rng = np.random.default_rng(123)
    T, K = 50, 3
    idx = pd.date_range("2020-01-01", periods=T, freq="B")
    cats = ["X", "Y", "Z"]

    # Random portfolio weights summing to 1 per row
    w_p_raw = rng.uniform(0, 1, (T, K))
    w_p_raw = w_p_raw / w_p_raw.sum(axis=1, keepdims=True)
    # Benchmark weights different per row
    w_b_raw = rng.uniform(0, 1, (T, K))
    w_b_raw = w_b_raw / w_b_raw.sum(axis=1, keepdims=True)
    rets_raw = rng.normal(0.0005, 0.01, (T, K))

    w_p = pd.DataFrame(w_p_raw, index=idx, columns=cats)
    w_b = pd.DataFrame(w_b_raw, index=idx, columns=cats)
    r = pd.DataFrame(rets_raw, index=idx, columns=cats)

    res = brinson_attribution(w_p, w_b, r)
    # Without explicit portfolio_returns, the decomposition is allocation-only;
    # selection and interaction columns exist but are zero by construction.
    assert res.method in ("brinson", "brinson_allocation_only")
    assert set(res.contributions.columns) == {"allocation", "selection", "interaction", "total"}
    # alloc + sel + inter == total per row (within float tolerance)
    parts = (
        res.contributions["allocation"]
        + res.contributions["selection"]
        + res.contributions["interaction"]
    )
    np.testing.assert_allclose(parts.values, res.contributions["total"].values, atol=1e-12)
    # res.total == sum of total per category
    assert res.total == pytest.approx(res.contributions["total"].sum())


def test_brinson_returns_nonzero_selection_when_portfolio_differs():
    """When ``portfolio_returns`` is provided and differs from benchmark
    returns, the selection / interaction effects must be non-zero.
    """
    rng = np.random.default_rng(7)
    T, K = 60, 3
    idx = pd.date_range("2021-01-01", periods=T, freq="B")
    cats = ["X", "Y", "Z"]

    w_p_raw = rng.uniform(0.1, 1.0, (T, K))
    w_p_raw = w_p_raw / w_p_raw.sum(axis=1, keepdims=True)
    w_b_raw = rng.uniform(0.1, 1.0, (T, K))
    w_b_raw = w_b_raw / w_b_raw.sum(axis=1, keepdims=True)

    bench_rets = rng.normal(0.001, 0.012, (T, K))
    # Portfolio realised returns deliberately differ from benchmark by 1%/bar.
    port_rets = bench_rets + 0.01

    w_p = pd.DataFrame(w_p_raw, index=idx, columns=cats)
    w_b = pd.DataFrame(w_b_raw, index=idx, columns=cats)
    r_b = pd.DataFrame(bench_rets, index=idx, columns=cats)
    r_p = pd.DataFrame(port_rets, index=idx, columns=cats)

    res = brinson_attribution(w_p, w_b, r_b, portfolio_returns=r_p)
    assert res.method == "brinson"
    sel_col = res.contributions["selection"].abs().sum()
    inter_col = res.contributions["interaction"].abs().sum()
    assert sel_col > 0.0, "selection must be non-zero when portfolio differs"
    assert inter_col > 0.0, "interaction must be non-zero when portfolio differs"


# --------------------------------------------------------------------------- #
# 5. annualized_attribution                                                   #
# --------------------------------------------------------------------------- #
def test_annualized_conversion():
    """daily mean of 0.001 * 252 = 0.252."""
    s = pd.Series(np.full(252, 0.001))
    out = annualized_attribution(s, ppy=252)
    assert out == pytest.approx(0.252, abs=1e-9)


def test_annualized_empty_series():
    """Empty series -> 0.0, no crash."""
    s = pd.Series([], dtype=float)
    out = annualized_attribution(s)
    assert out == 0.0


# --------------------------------------------------------------------------- #
# Defensive validation                                                        #
# --------------------------------------------------------------------------- #
def test_factor_attribution_invalid_method():
    f = pd.Series(np.zeros(10))
    y = pd.Series(np.zeros(10))
    with pytest.raises(ValueError):
        attribution_by_factor(y, {"f": f}, method="bogus")


def test_factor_attribution_too_few_bars():
    idx = pd.date_range("2020-01-01", periods=3, freq="B")
    f = pd.Series([0.0, 0.0, 0.0], index=idx)
    y = pd.Series([0.0, 0.0, 0.0], index=idx)
    with pytest.raises(ValueError):
        attribution_by_factor(y, {"f": f})


def test_brinson_no_shared_categories():
    idx = pd.date_range("2020-01-01", periods=5, freq="B")
    w_p = pd.DataFrame(np.ones((5, 1)), index=idx, columns=["A"])
    w_b = pd.DataFrame(np.ones((5, 1)), index=idx, columns=["B"])
    r = pd.DataFrame(np.ones((5, 1)), index=idx, columns=["A"])
    with pytest.raises(ValueError):
        brinson_attribution(w_p, w_b, r)


# --------------------------------------------------------------------------- #
# Runtime duck-type validation                                                #
# --------------------------------------------------------------------------- #
def test_attribution_runtime_check_rejects_invalid():
    """attribution_by_strategy must raise TypeError if the input lacks the
    AllocatorResult duck-type attributes, with a helpful interface message."""

    class _Invalid:
        # missing per_strategy_attribution and per_strategy_returns
        pass

    with pytest.raises(TypeError) as excinfo:
        attribution_by_strategy(_Invalid())
    msg = str(excinfo.value)
    assert "per_strategy_attribution" in msg
    assert "per_strategy_returns" in msg

    # Partial-match: only one attribute present should also fail
    class _Partial:
        per_strategy_attribution = {"A": 1.0}
        # per_strategy_returns missing

    with pytest.raises(TypeError) as excinfo2:
        attribution_by_strategy(_Partial())
    assert "per_strategy_returns" in str(excinfo2.value)


def test_brinson_allocation_unbiased_by_uniform_benchmark_shift():
    """Round V regression: a uniform shift in benchmark returns must NOT
    contaminate the allocation effect.

    The allocation term is now computed against ``r_b - r_b_total`` so
    a constant added to every category return only changes ``r_b_total``
    by the same amount, leaving ``r_b - r_b_total`` invariant. The
    pre-fix formula multiplied ``r_b`` directly by active weights, so a
    uniform +1% shift in benchmark returns leaked into the allocation
    column for any portfolio whose active weights summed to nonzero.
    """
    rng = np.random.default_rng(0)
    T, K = 30, 4
    idx = pd.date_range("2022-01-01", periods=T, freq="B")
    cats = ["A", "B", "C", "D"]

    w_p_raw = rng.uniform(0.1, 1.0, (T, K))
    w_p_raw = w_p_raw / w_p_raw.sum(axis=1, keepdims=True)
    w_b_raw = rng.uniform(0.1, 1.0, (T, K))
    w_b_raw = w_b_raw / w_b_raw.sum(axis=1, keepdims=True)
    rets_raw = rng.normal(0.0005, 0.01, (T, K))

    w_p = pd.DataFrame(w_p_raw, index=idx, columns=cats)
    w_b = pd.DataFrame(w_b_raw, index=idx, columns=cats)
    r_b = pd.DataFrame(rets_raw, index=idx, columns=cats)
    # Uniform shift: every category benchmark return is bumped by the same
    # constant per period.
    r_b_shift = r_b + 0.05

    res = brinson_attribution(w_p, w_b, r_b)
    res_shift = brinson_attribution(w_p, w_b, r_b_shift)

    # The allocation effect must be invariant to a uniform shift in r_b.
    np.testing.assert_allclose(
        res.contributions["allocation"].values,
        res_shift.contributions["allocation"].values,
        atol=1e-12,
    )
