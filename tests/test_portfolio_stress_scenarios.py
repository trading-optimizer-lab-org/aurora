# ruff: noqa: N806
"""Tests for the stress-scenario extensions (R172).

Each scenario:
- runs deterministically given a fixed seed
- finishes in well under 5 seconds for typical problem sizes
- surfaces a worst-case drawdown (max_drawdown >= 0)
- does not silently NaN out the portfolio metrics
"""
from __future__ import annotations

import time

import numpy as np
import pytest
from aurora.portfolio import (
    EqualWeightAllocator,
    InverseVolAllocator,
    StressScenario,
    concentration_shock_scenario,
    correlated_drawdown_scenario,
    higher_cost_scenario,
    liquidity_shock_scenario,
    missing_asset_scenario,
    noisy_covariance_scenario,
    stress_test,
)


def _synth_returns(seed: int = 0, T: int = 250, N: int = 4) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = rng.normal(0.0008, 0.012, size=(T, N))
    base[:, -1] *= 2.0
    return base


def _assert_metric_set_clean(m: dict[str, float]) -> None:
    """Each metric is finite and ``max_drawdown`` >= 0."""
    for k, v in m.items():
        assert np.isfinite(v), f"metric {k}={v} is not finite"
    assert m["max_drawdown"] >= 0.0


# --------------------------------------------------------------------------- #
# Deterministic execution & runtime budget                                    #
# --------------------------------------------------------------------------- #
def test_noisy_covariance_deterministic_and_fast():
    R = _synth_returns(seed=101, T=300, N=5)
    sc = noisy_covariance_scenario(noise_std=0.005, seed=42)
    t0 = time.perf_counter()
    r1 = stress_test(EqualWeightAllocator(), R, [sc], base_costs_bps=2.0)
    r2 = stress_test(EqualWeightAllocator(), R, [sc], base_costs_bps=2.0)
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0
    assert np.array_equal(r1[0].weights, r2[0].weights)
    _assert_metric_set_clean(r1[0].metric_stressed)


def test_higher_cost_scenario_lowers_net_return():
    R = _synth_returns(seed=102, T=200, N=4)
    sc = higher_cost_scenario(multiplier=10.0, seed=7)
    results = stress_test(
        EqualWeightAllocator(), R, [sc], base_costs_bps=10.0,
    )
    res = results[0]
    # Cost multiplier > 1 must hurt net return strictly.
    assert (
        res.metric_stressed["net_return"] <
        res.metric_baseline["net_return"]
    )
    _assert_metric_set_clean(res.metric_stressed)


def test_missing_asset_scenario_drops_target_column_and_runs():
    R = _synth_returns(seed=103, T=200, N=5)
    sc = missing_asset_scenario(drop_assets=(2,), seed=11)
    results = stress_test(InverseVolAllocator(), R, [sc])
    res = results[0]
    # Asset 2 was zeroed out -> its inverse-vol contribution becomes 0.
    # Check via column-sum on the stressed matrix path (we just verify
    # weight allocation isn't NaN and metrics are clean).
    assert np.isfinite(res.weights).all()
    _assert_metric_set_clean(res.metric_stressed)


def test_correlated_drawdown_scenario_creates_drawdown():
    R = _synth_returns(seed=104, T=250, N=4)
    sc = correlated_drawdown_scenario(
        shock=0.20, window_frac=0.05, seed=13,
    )
    results = stress_test(EqualWeightAllocator(), R, [sc])
    res = results[0]
    # The injected shock should at least equal the baseline mdd.
    assert (
        res.metric_stressed["max_drawdown"] >=
        res.metric_baseline["max_drawdown"]
    )
    _assert_metric_set_clean(res.metric_stressed)


def test_liquidity_shock_scenario_shrinks_returns():
    R = _synth_returns(seed=105, T=200, N=4)
    sc = liquidity_shock_scenario(haircut=0.5, seed=17)
    results = stress_test(
        EqualWeightAllocator(), R, [sc], base_costs_bps=1.0,
    )
    res = results[0]
    # haircut 0.5 must lower the variance of the path (smaller returns
    # in absolute value -> smaller spread).
    assert (
        res.metric_stressed["variance"] <=
        res.metric_baseline["variance"] + 1e-12
    )
    _assert_metric_set_clean(res.metric_stressed)


def test_concentration_shock_scenario_runs_and_gives_clean_metrics():
    R = _synth_returns(seed=106, T=300, N=5)
    sc = concentration_shock_scenario(floor=0.6, seed=19)
    results = stress_test(InverseVolAllocator(), R, [sc])
    res = results[0]
    # Allocator should still produce a valid weight vector summing to 1.
    assert np.isclose(res.weights.sum(), 1.0, atol=1e-9)
    _assert_metric_set_clean(res.metric_stressed)


# --------------------------------------------------------------------------- #
# Determinism comparison + invalid-input guards                               #
# --------------------------------------------------------------------------- #
def test_all_scenarios_deterministic_with_same_seed():
    R = _synth_returns(seed=107, T=200, N=4)
    scenarios = [
        noisy_covariance_scenario(noise_std=0.003, seed=1),
        correlated_drawdown_scenario(shock=0.1, seed=1),
        liquidity_shock_scenario(haircut=0.3, seed=1),
        concentration_shock_scenario(floor=0.4, seed=1),
    ]
    r_a = stress_test(EqualWeightAllocator(), R, scenarios)
    r_b = stress_test(EqualWeightAllocator(), R, scenarios)
    for a, b in zip(r_a, r_b):
        assert np.array_equal(a.weights, b.weights)
        for k in a.metric_stressed:
            assert a.metric_stressed[k] == b.metric_stressed[k]


def test_invalid_drawdown_window_frac_rejected():
    with pytest.raises(ValueError, match="drawdown_window_frac"):
        StressScenario(name="bad", drawdown_shock=0.1, drawdown_window_frac=0.0)


def test_invalid_liquidity_haircut_rejected():
    with pytest.raises(ValueError, match="liquidity_haircut"):
        StressScenario(name="bad", liquidity_haircut=1.5)


def test_invalid_concentration_floor_rejected():
    with pytest.raises(ValueError, match="concentration_floor"):
        StressScenario(name="bad", concentration_floor=-0.1)


# --------------------------------------------------------------------------- #
# Runtime budget covering the full scenario suite                             #
# --------------------------------------------------------------------------- #
def test_full_scenario_suite_under_5_seconds():
    R = _synth_returns(seed=108, T=400, N=6)
    scenarios = [
        noisy_covariance_scenario(noise_std=0.004, seed=2),
        higher_cost_scenario(multiplier=5.0, seed=2),
        missing_asset_scenario(drop_assets=(0, 1), seed=2),
        correlated_drawdown_scenario(shock=0.15, seed=2),
        liquidity_shock_scenario(haircut=0.4, seed=2),
        concentration_shock_scenario(floor=0.5, seed=2),
    ]
    t0 = time.perf_counter()
    results = stress_test(
        EqualWeightAllocator(), R, scenarios, base_costs_bps=5.0,
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0
    for res in results:
        _assert_metric_set_clean(res.metric_stressed)
