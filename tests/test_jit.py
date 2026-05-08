"""Equivalence + speedup tests for JIT-accelerated kernels.

Run:
    uv run --with numba --with vectorbt --with scipy --with pyarrow --with pytest \
        python -m pytest quantforge/tests/test_jit.py -v
"""
from __future__ import annotations
import time
import numpy as np
import pandas as pd
import pytest

from quantforge.core.seed import set_global_seed
from quantforge.core.costs import ZERO_costs, IBKR_costs, apply_costs
from quantforge.core.engine import run_backtest
from quantforge.core.engine_jit import (
    NUMBA_AVAILABLE,
    apply_costs_fast,
    apply_costs_np,
    sma_fast,
    rsi_fast,
    max_min_fast,
    realized_vol_fast,
    run_backtest_jit,
)
from quantforge.strategies.library.rsi_meanrev import _rsi as _rsi_py
from quantforge.strategies.library import MACross, RSIMeanRev


TOL = 1e-9


@pytest.fixture
def fake_prices():
    set_global_seed(42)
    idx = pd.date_range("2010-01-01", periods=2000, freq="B")
    rets = np.random.default_rng(42).normal(0.0005, 0.012, 2000)
    p = 100 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="FAKE")


# ---------- equivalence tests -------------------------------------------------


def test_apply_costs_equivalence():
    """1000 bars random weights/returns, JIT vs numpy must match within 1e-9."""
    rng = np.random.default_rng(7)
    T = 1000
    weights = rng.uniform(-1.0, 1.0, T)
    returns = rng.normal(0.0, 0.01, T)

    for costs in (ZERO_costs, IBKR_costs):
        ref = apply_costs(weights, returns, costs)
        jit = apply_costs_fast(weights, returns, costs)
        assert jit.shape == ref.shape
        max_err = float(np.max(np.abs(jit - ref)))
        assert max_err < TOL, f"costs={costs} max_err={max_err}"


def test_apply_costs_np_equivalence():
    """apply_costs_np (numpy reference path) must match costs.apply_costs."""
    rng = np.random.default_rng(23)
    T = 1000
    weights = rng.uniform(-1.0, 1.0, T)
    returns = rng.normal(0.0, 0.01, T)

    for costs in (ZERO_costs, IBKR_costs):
        ref = apply_costs(weights, returns, costs)
        np_ref = apply_costs_np(weights, returns, costs)
        assert np_ref.shape == ref.shape
        max_err = float(np.max(np.abs(np_ref - ref)))
        assert max_err < TOL, f"costs={costs} max_err={max_err}"


def test_sma_equivalence():
    """SMA from cumsum (numpy reference) vs sma_fast must match."""
    rng = np.random.default_rng(3)
    p = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, 1000))

    for n in (5, 20, 100):
        # reference: same cumsum logic as ma_cross.MACross.signals
        cs = np.empty(len(p) + 1); cs[0] = 0.0; np.cumsum(p, out=cs[1:])
        ref = np.full(len(p), np.nan)
        for i in range(n - 1, len(p)):
            ref[i] = (cs[i + 1] - cs[i + 1 - n]) / n

        out = sma_fast(p, n)
        # ignore leading NaNs
        valid = ~np.isnan(ref)
        max_err = float(np.max(np.abs(out[valid] - ref[valid])))
        assert max_err < 1e-9, f"n={n} max_err={max_err}"


def test_rsi_equivalence():
    """Wilder RSI: pure-python reference (rsi_meanrev._rsi) vs rsi_fast."""
    rng = np.random.default_rng(11)
    p = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, 1000))
    for n in (2, 5, 14):
        ref = _rsi_py(p, n)
        out = rsi_fast(p, n)
        valid = ~np.isnan(ref)
        if not valid.any():
            continue
        max_err = float(np.max(np.abs(out[valid] - ref[valid])))
        assert max_err < 1e-9, f"n={n} max_err={max_err}"


def test_max_min_equivalence():
    """Donchian rolling window max/min."""
    rng = np.random.default_rng(13)
    p = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.012, 800))
    for n in (10, 55, 200):
        rmax, rmin = max_min_fast(p, n)
        for i in range(n, len(p)):
            ref_max = float(p[i - n:i].max())
            ref_min = float(p[i - n:i].min())
            assert abs(rmax[i] - ref_max) < 1e-9
            assert abs(rmin[i] - ref_min) < 1e-9


def test_realized_vol_equivalence():
    """Rolling std (population, ddof=0)."""
    rng = np.random.default_rng(17)
    r = rng.normal(0.0, 0.01, 600)
    w = 30
    out = realized_vol_fast(r, w)
    ref = pd.Series(r).rolling(w).std(ddof=0).values
    valid = ~np.isnan(ref)
    max_err = float(np.max(np.abs(out[valid] - ref[valid])))
    assert max_err < 1e-9, f"max_err={max_err}"


def test_run_backtest_equivalence(fake_prices):
    """run_backtest vs run_backtest_jit on identical inputs must match within 1e-9."""
    s = MACross(fast=10, slow=50)
    a = run_backtest(fake_prices, s.signals, costs=IBKR_costs)
    b = run_backtest_jit(fake_prices, s.signals, costs=IBKR_costs)

    assert np.max(np.abs(a.rets - b.rets)) < TOL
    assert np.max(np.abs(a.nav - b.nav)) < TOL
    assert np.max(np.abs(a.weights - b.weights)) < TOL


def test_run_backtest_equivalence_rsi(fake_prices):
    s = RSIMeanRev(period=2)
    a = run_backtest(fake_prices, s.signals, costs=IBKR_costs)
    b = run_backtest_jit(fake_prices, s.signals, costs=IBKR_costs)
    assert np.max(np.abs(a.rets - b.rets)) < TOL
    assert np.max(np.abs(a.nav - b.nav)) < TOL


# ---------- speedup test ------------------------------------------------------


@pytest.mark.skipif(not NUMBA_AVAILABLE, reason="numba not installed")
def test_speedup():
    """JIT cost loop must be >3x faster than numpy on 100k bars.

    Excludes JIT compile cost: apply_costs_fast is invoked once before timing.
    """
    rng = np.random.default_rng(31)
    T = 100_000
    weights = rng.uniform(-1.0, 1.0, T)
    returns = rng.normal(0.0, 0.01, T)

    # warm up JIT
    apply_costs_fast(weights[:10], returns[:10], IBKR_costs)

    # numpy
    t0 = time.perf_counter()
    for _ in range(10):
        apply_costs(weights, returns, IBKR_costs)
    t_np = time.perf_counter() - t0

    # JIT
    t0 = time.perf_counter()
    for _ in range(10):
        apply_costs_fast(weights, returns, IBKR_costs)
    t_jit = time.perf_counter() - t0

    speedup = t_np / max(t_jit, 1e-9)
    print(f"\napply_costs speedup: {speedup:.2f}x  (numpy={t_np:.4f}s, jit={t_jit:.4f}s)")
    assert speedup > 3.0, f"expected >3x speedup, got {speedup:.2f}x"
