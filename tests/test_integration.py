"""End-to-end integration tests for Aurora (Task 6.1).

Covers full pipeline:
    data -> strategy -> validate_pipeline -> marker -> preflight -> tearsheet
    GA search -> validate
    multi-strategy allocator
    PairTrade -> MultiAssetEngine

All tests use synthetic prices (no network). Each is self-contained.
File outputs (markers, tearsheets) live under pytest's tmp_path.
"""
from __future__ import annotations

import functools
import os
import time
import warnings

import matplotlib
# Force non-interactive backend before pyplot import (Windows-safe, headless-CI-safe)
matplotlib.use("Agg", force=True)

import numpy as np
import pandas as pd
import pytest

from aurora.core.costs import ZERO_costs
from aurora.core.engine import run_backtest
from aurora.core.engine_multi import MultiAssetEngine
from aurora.core.seed import set_global_seed
from aurora.deployment.allocator import StrategyAllocator
from aurora.deployment.preflight import (
    check_validation_marker,
    run_preflight,
)
from aurora.reporting.tearsheet import generate_tearsheet
from aurora.strategies.library import (
    MACross,
    PairTrade,
    RSIMeanRev,
    TSMomentum,
)
from aurora.validation.pipeline import validate_pipeline
from aurora.validation.walk_forward import WFWindow


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
SLOW_TEST_THRESHOLD_SEC = 30.0


def slow_warning(fn):
    """Decorator: emit warning if test runtime exceeds SLOW_TEST_THRESHOLD_SEC."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - t0
            if elapsed > SLOW_TEST_THRESHOLD_SEC:
                warnings.warn(
                    f"slow integration test: {fn.__name__} took {elapsed:.1f}s "
                    f"(>{SLOW_TEST_THRESHOLD_SEC}s)",
                    RuntimeWarning,
                    stacklevel=2,
                )
    return wrapper


def make_synthetic_prices(n: int = 2000, seed: int = 42,
                          start: str = "2010-01-01") -> pd.Series:
    """Geometric-Brownian synthetic price series."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.012, n)
    p = 100.0 * np.cumprod(1.0 + rets)
    idx = pd.date_range(start, periods=n, freq="B")
    return pd.Series(p, index=idx, name="SYNTH")


def make_is_oos_prices(seed: int = 42) -> pd.Series:
    """Synthetic series spanning IS (pre-2013) and OOS (2013+)."""
    set_global_seed(seed)
    # 6000 business days from 2000-01-03 -> ~2023, gives both IS and OOS coverage
    return make_synthetic_prices(n=6000, seed=seed, start="2000-01-03")


# Compact WF windows: faster than DEFAULT_WF, still exercise the pipeline
_FAST_WF = [
    WFWindow("WF1", "2000-01-03", "2005-12-31", "2006-01-01", "2008-12-31"),
    WFWindow("WF2", "2000-01-03", "2007-12-31", "2008-01-01", "2010-12-31"),
    WFWindow("WF3", "2000-01-03", "2009-12-31", "2010-01-01", "2012-12-31"),
]


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #
@slow_warning
def test_e2e_macross_validation(tmp_path, monkeypatch):
    """Load synthetic SPY -> MACross -> validate_pipeline -> result has all fields."""
    # chdir so any marker side-effect lands in tmp_path
    monkeypatch.chdir(tmp_path)

    prices = make_is_oos_prices()

    def factory():
        return MACross(fast=10, slow=50)

    rep = validate_pipeline(
        factory, prices, "e2e-macross",
        costs=ZERO_costs, wf_windows=_FAST_WF,
        mc_n_paths=30, min_wf_pass=0, mc_min_pct=0.0, mc_max_pct=1.0,
    )

    # All expected fields present
    assert rep.strategy_name == "e2e-macross"
    assert isinstance(rep.is_metrics, dict)
    assert isinstance(rep.oos_metrics, dict)
    for key in ("calmar", "sharpe", "cagr", "mdd"):
        assert key in rep.is_metrics
        assert key in rep.oos_metrics
    assert rep.wf_total == len(_FAST_WF)
    assert 0 <= rep.wf_pass <= rep.wf_total
    assert isinstance(rep.lookahead_passed, bool)
    assert isinstance(rep.overall_passed, bool)
    assert isinstance(rep.failures, list)
    # report() renders without error
    s = rep.report()
    assert "VALIDATION REPORT" in s
    assert "e2e-macross" in s


@slow_warning
def test_e2e_strategy_to_paper_marker(tmp_path, monkeypatch):
    """validate_pipeline writes marker on overall_passed -> preflight finds it."""
    monkeypatch.chdir(tmp_path)
    prices = make_is_oos_prices()

    def factory():
        return MACross(fast=10, slow=50)

    rep = validate_pipeline(
        factory, prices, "MACross",  # use class name so preflight matches
        costs=ZERO_costs, wf_windows=_FAST_WF,
        mc_n_paths=30, min_wf_pass=0, mc_min_pct=0.0, mc_max_pct=1.0,
    )

    if rep.overall_passed:
        # Marker must exist
        marker_path = tmp_path / "aurora" / "data_cache_qf" / ".validation_passed_MACross.json"
        assert marker_path.exists(), f"marker not written at {marker_path}"
        # Preflight finds it
        check = check_validation_marker("MACross", project_dir=str(tmp_path))
        assert check.passed, f"preflight marker check failed: {check.detail}"
    else:
        # If validation didn't pass (random data), force-write marker to test the read path
        from aurora.deployment.preflight import write_validation_marker
        path = write_validation_marker(
            strategy_name="MACross",
            metrics={"is": rep.is_metrics, "oos": rep.oos_metrics},
            project_dir=str(tmp_path),
        )
        assert os.path.exists(path)
        check = check_validation_marker("MACross", project_dir=str(tmp_path))
        assert check.passed


@slow_warning
def test_e2e_ga_search_then_validate(tmp_path, monkeypatch):
    """GA search returns Pareto -> take best -> run validate_pipeline -> result."""
    pytest.importorskip("deap")
    from aurora.ga.fitness import multi_objective_fitness
    from aurora.ga.runner import GAConfig, run_ga

    monkeypatch.chdir(tmp_path)
    prices = make_is_oos_prices()
    is_p = prices[prices.index < pd.Timestamp("2013-01-01")]
    oos_p = prices[prices.index >= pd.Timestamp("2013-01-01")]

    cfg = GAConfig(population=8, generations=2, seed=42, backend="sequential")
    pareto = run_ga(MACross, is_p, oos_p, multi_objective_fitness,
                   cfg, verbose=False)

    assert isinstance(pareto, list) and len(pareto) >= 1
    best_params, best_fit = pareto[0]
    assert "fast" in best_params and "slow" in best_params

    # Coerce ints; GA may return floats for nominal-int params
    fast = int(best_params["fast"])
    slow = int(best_params["slow"])
    if fast >= slow:
        fast, slow = 10, 50  # safe fallback if GA picked degenerate combo

    def factory():
        return MACross(fast=fast, slow=slow,
                       allow_short=bool(best_params.get("allow_short", True)))

    rep = validate_pipeline(
        factory, prices, "ga-best",
        costs=ZERO_costs, wf_windows=_FAST_WF,
        mc_n_paths=30, min_wf_pass=0, mc_min_pct=0.0, mc_max_pct=1.0,
    )
    assert rep.strategy_name == "ga-best"
    assert "calmar" in rep.oos_metrics


@slow_warning
def test_e2e_multi_strategy_allocator(tmp_path):
    """3 strategies (MA, RSI, TSMom) -> allocator -> meta-portfolio NAV positive growth."""
    p1 = make_synthetic_prices(n=1500, seed=1, start="2010-01-04")
    p2 = make_synthetic_prices(n=1500, seed=2, start="2010-01-04")
    p3 = make_synthetic_prices(n=1500, seed=3, start="2010-01-04")

    strategies = {
        "ma": MACross(fast=10, slow=50),
        "rsi": RSIMeanRev(period=2),
        "tsmom": TSMomentum(lookback=100),
    }
    prices = {"ma": p1, "rsi": p2, "tsmom": p3}

    alloc = StrategyAllocator(strategies, prices,
                              method="equal_vol", rebalance="monthly",
                              lookback=60)
    res = alloc.run(ppy=252)

    # Shape sanity
    T = len(p1)
    assert res.nav.shape == (T,)
    assert res.weights.shape[1] == 3
    assert set(res.strategy_names) == {"ma", "rsi", "tsmom"}
    # Weights at each rebalance approximately sum to 1
    w_at_rb = res.weights[res.rebalance_mask]
    sums = w_at_rb.sum(axis=1)
    assert np.allclose(sums, 1.0, atol=1e-6), f"weight sums off: {sums[:5]}"
    # NAV is finite and starts at 1.0
    assert np.isfinite(res.nav).all()
    assert res.nav[0] == pytest.approx(1.0, abs=1e-9)
    # Per-strategy attribution sums to ~ portfolio total return
    total_attrib = sum(res.per_strategy_attribution.values())
    total_port = res.rets.sum()
    assert abs(total_attrib - total_port) < 1e-8


@slow_warning
def test_e2e_pair_trade_multi_asset(tmp_path):
    """PairTrade SPY+QQQ -> MultiAssetEngine -> metrics computed."""
    # Two synthetic but correlated price series
    rng = np.random.default_rng(7)
    n = 1500
    common = rng.normal(0.0005, 0.012, n)
    idio_a = rng.normal(0.0, 0.004, n)
    idio_b = rng.normal(0.0, 0.004, n)
    pa = 100.0 * np.cumprod(1.0 + common + idio_a)
    pb = 100.0 * np.cumprod(1.0 + common + idio_b)
    idx = pd.date_range("2010-01-04", periods=n, freq="B")
    spy = pd.Series(pa, index=idx, name="SPY")
    qqq = pd.Series(pb, index=idx, name="QQQ")

    pt = PairTrade(sym_a="SPY", sym_b="QQQ", lookback=60,
                   entry_z=2.0, exit_z=0.5, hedge_ratio=1.0)
    weights = pt.weights({"SPY": spy, "QQQ": qqq})
    assert "SPY" in weights and "QQQ" in weights

    engine = MultiAssetEngine(gross_leverage_cap=1.0, net_leverage_cap=2.0)
    res = engine.run({"SPY": spy, "QQQ": qqq}, weights, ppy=252)

    # Metrics computed and finite
    m = res.metrics
    assert hasattr(m, "calmar")
    assert hasattr(m, "sharpe")
    assert np.isfinite(res.nav).all()
    assert res.nav.shape == (n,)
    # PairTrade legs are opposite-signed -> net leverage stays bounded
    assert np.all(np.abs(res.net_leverage) <= 2.0 + 1e-9)
    # Two symbols tracked
    assert set(res.symbols) == {"SPY", "QQQ"}


@slow_warning
def test_e2e_tearsheet_generation(tmp_path):
    """Run backtest -> generate tearsheet HTML -> file exists with content."""
    prices = make_synthetic_prices(n=1200, seed=11)
    s = MACross(fast=10, slow=50)
    res = run_backtest(prices, s.signals, costs=ZERO_costs)

    out_path = tmp_path / "tearsheet.html"
    written = generate_tearsheet(res, str(out_path),
                                 title="Integration Tearsheet")
    assert os.path.exists(written)
    size = os.path.getsize(written)
    assert size > 5000, f"tearsheet too small: {size} bytes"
    with open(written, "r", encoding="utf-8") as f:
        html = f.read()
    # Required sections present
    assert "<html" in html.lower()
    assert "Equity Curve" in html
    assert "Drawdown" in html
    assert "Integration Tearsheet" in html
    # base64 image data embedded
    assert "data:image/png;base64," in html


@slow_warning
def test_e2e_full_workflow(tmp_path, monkeypatch):
    """Full chain: data -> GA -> validate -> marker -> preflight -> tearsheet."""
    pytest.importorskip("deap")
    from aurora.ga.fitness import multi_objective_fitness
    from aurora.ga.runner import GAConfig, run_ga
    from aurora.core import data_layer as _dl

    monkeypatch.chdir(tmp_path)
    # Redirect QF_CACHE so preflight's data-availability check (which calls
    # load_asset under the hood) reads/writes inside tmp_path instead of the
    # real project cache. Avoids network and avoids polluting the repo.
    fake_cache = tmp_path / "aurora" / "data_cache_qf"
    fake_cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_dl, "QF_CACHE", str(fake_cache))
    # Also patch the symbol QF_CACHE imported into preflight
    from aurora.deployment import preflight as _pf
    monkeypatch.setattr(_pf, "QF_CACHE", str(fake_cache))

    # 1. Data
    prices = make_is_oos_prices(seed=99)
    is_p = prices[prices.index < pd.Timestamp("2013-01-01")]
    oos_p = prices[prices.index >= pd.Timestamp("2013-01-01")]

    # Pre-seed cache so preflight's check_data_availability finds the symbol
    # without any network call. Use the strategy class name as the "ticker".
    prices.to_frame("Close").to_parquet(fake_cache / "MACross.parquet")

    # 2. GA search
    cfg = GAConfig(population=8, generations=2, seed=99, backend="sequential")
    pareto = run_ga(MACross, is_p, oos_p, multi_objective_fitness,
                   cfg, verbose=False)
    assert len(pareto) >= 1
    best_params = pareto[0][0]
    fast = int(best_params["fast"])
    slow = int(best_params["slow"])
    if fast >= slow:
        fast, slow = 10, 50

    def factory():
        return MACross(fast=fast, slow=slow,
                       allow_short=bool(best_params.get("allow_short", True)))

    # 3. Validate
    rep = validate_pipeline(
        factory, prices, "MACross",
        costs=ZERO_costs, wf_windows=_FAST_WF,
        mc_n_paths=30, min_wf_pass=0, mc_min_pct=0.0, mc_max_pct=1.0,
    )

    # 4. Marker (force-write if pipeline didn't pass; we still want to test the chain)
    if not rep.overall_passed:
        from aurora.deployment.preflight import write_validation_marker
        write_validation_marker(
            strategy_name="MACross",
            metrics={"is": rep.is_metrics, "oos": rep.oos_metrics},
            project_dir=str(tmp_path),
        )

    # 5. Preflight (skip data_availability check by passing prices directly)
    strat = factory()
    pf = run_preflight(
        strat, symbol="MACross",   # symbol unused for marker check; marker keyed by class name
        broker=None,
        min_data_bars=50,
        prices=prices,
        recent_weights=strat.signals(prices),
        project_dir=str(tmp_path),
        check_ntp=False,
    )

    # Marker check must pass; data_availability may fail because no SPY cache in tmp_path
    marker_check = next(c for c in pf.checks if c.name == "validation_marker")
    assert marker_check.passed, f"marker check failed: {marker_check.detail}"
    sizing_check = next(c for c in pf.checks if c.name == "position_sizing")
    assert sizing_check.passed, f"sizing failed: {sizing_check.detail}"
    la_check = next(c for c in pf.checks if c.name == "anti_lookahead")
    assert la_check.passed, f"lookahead failed: {la_check.detail}"

    # 6. Tearsheet
    res = run_backtest(prices, strat.signals, costs=ZERO_costs)
    ts_path = tmp_path / "full_workflow_tearsheet.html"
    generate_tearsheet(res, str(ts_path), title="Full Workflow")
    assert ts_path.exists()
    assert ts_path.stat().st_size > 5000
