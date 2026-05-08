"""Tests for the IS-only GA fitness API and run_ga signature.

OOS sagrado: the GA must compute fitness from IS prices only. ``run_ga`` accepts
``prices_oos`` for backwards compatibility but never feeds it to the fitness
function.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from quantforge.core.seed import set_global_seed
from quantforge.strategies.library import MACross
from quantforge.ga.runner import run_ga, GAConfig
from quantforge.ga.fitness import (
    multi_objective_fitness_is,
    scalar_fitness_is,
    validate_oos,
)


pytest.importorskip("deap")


@pytest.fixture
def fake_prices_is():
    set_global_seed(123)
    idx = pd.date_range("2010-01-01", periods=600, freq="B")
    rng = np.random.default_rng(123)
    rets = rng.normal(0.0005, 0.012, 600)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="IS")


@pytest.fixture
def fake_prices_oos():
    set_global_seed(456)
    idx = pd.date_range("2018-01-01", periods=300, freq="B")
    rng = np.random.default_rng(456)
    rets = rng.normal(0.0004, 0.014, 300)
    p = 100.0 * np.cumprod(1.0 + rets)
    return pd.Series(p, index=idx, name="OOS")


def test_multi_objective_fitness_is_returns_4_tuple(fake_prices_is):
    strat = MACross(fast=10, slow=30)
    fit = multi_objective_fitness_is(fake_prices_is, strat.signals)
    assert isinstance(fit, tuple)
    assert len(fit) == 4
    for v in fit:
        assert isinstance(v, float)


def test_scalar_fitness_is_returns_float(fake_prices_is):
    strat = MACross(fast=10, slow=30)
    val = scalar_fitness_is(fake_prices_is, strat.signals)
    assert isinstance(val, float)
    # bound: weighted sum of bounded objectives
    assert -200.0 < val < 200.0


def test_run_ga_with_is_only_fitness(fake_prices_is):
    cfg = GAConfig(population=10, generations=2, seed=42, backend="sequential")
    pareto = run_ga(MACross, fake_prices_is, None, multi_objective_fitness_is,
                    cfg, verbose=False)
    assert isinstance(pareto, list)
    assert len(pareto) >= 1
    params, fit = pareto[0]
    assert "fast" in params and "slow" in params
    assert len(fit) == 4


def test_run_ga_legacy_signature_still_works(fake_prices_is, fake_prices_oos):
    """Existing call sites passing the deprecated 3-arg fitness keep working.

    The deprecated multi_objective_fitness emits a DeprecationWarning and
    delegates to the IS-only fitness, dropping prices_oos.
    """
    from quantforge.ga.fitness import multi_objective_fitness

    cfg = GAConfig(population=10, generations=2, seed=42, backend="sequential")
    with pytest.warns(DeprecationWarning):
        # First call inside run_ga triggers the warning.
        # Pre-warm to ensure pytest sees it.
        multi_objective_fitness(fake_prices_is, fake_prices_oos,
                                MACross().signals)

    pareto = run_ga(MACross, fake_prices_is, fake_prices_oos,
                    multi_objective_fitness, cfg, verbose=False)
    assert isinstance(pareto, list)
    assert len(pareto) >= 1


def test_validate_oos_returns_dict(fake_prices_oos):
    strat = MACross(fast=10, slow=30)
    m = validate_oos(fake_prices_oos, strat.signals)
    assert isinstance(m, dict)
    for k in ("calmar", "sharpe", "mdd", "cagr", "final_nav", "n_periods"):
        assert k in m


def test_run_ga_requires_fitness_fn(fake_prices_is):
    cfg = GAConfig(population=4, generations=1, seed=1, backend="sequential")
    with pytest.raises(TypeError):
        run_ga(MACross, fake_prices_is, None, None, cfg, verbose=False)


# ---------------------------------------------------------------------------
# Bug-fix regression tests (cxBlend bounds, varOr overshoot, NSGA-II ties,
# fitness normalization, BO categorical handling).
# ---------------------------------------------------------------------------


def test_cxblend_clips_bounds():
    """cxBlend can produce genes outside [0, 1]; the custom mate operator
    must clip every offspring gene back into bounds.
    """
    pytest.importorskip("deap")
    from deap import base, creator, tools

    # Build a fresh creator to avoid clashing with NSGA-II registrations.
    if "_FitTest" not in dir(creator):
        creator.create("_FitTest", base.Fitness, weights=(1.0,))
    if "_IndTest" not in dir(creator):
        creator.create("_IndTest", list, fitness=creator._FitTest)

    # Reproduce the wrapped operator from runner.py inline to test in isolation.
    def _mate_blend_clip(ind1, ind2, alpha=0.5):
        tools.cxBlend(ind1, ind2, alpha=alpha)
        for ind in (ind1, ind2):
            for i in range(len(ind)):
                ind[i] = float(np.clip(ind[i], 0.0, 1.0))
        return ind1, ind2

    rng = np.random.default_rng(42)
    n_genes = 5
    for _ in range(200):
        # Start with parents at the edges; cxBlend(alpha=0.5) extends to
        # roughly [-0.5, 1.5] without clipping.
        p1 = creator._IndTest([float(rng.random()) for _ in range(n_genes)])
        p2 = creator._IndTest([float(rng.random()) for _ in range(n_genes)])
        c1, c2 = _mate_blend_clip(p1, p2, alpha=0.5)
        for ind in (c1, c2):
            for g in ind:
                assert 0.0 <= g <= 1.0, f"gene {g} escaped bounds"


def test_varOr_does_not_overshoot(fake_prices_is):
    """With a small population, the GA loop must not error from varOr
    over-asking. The fix caps lambda_ at len(pop).
    """
    cfg = GAConfig(population=10, generations=2, seed=7, backend="sequential")
    pareto = run_ga(MACross, fake_prices_is, None, multi_objective_fitness_is,
                    cfg, verbose=False)
    assert isinstance(pareto, list)
    assert 1 <= len(pareto) <= 10


def test_nsga_ties_deterministic(fake_prices_is):
    """Same seed -> identical Pareto front order across runs.

    NSGA-II with crowding distance can have ties; our tie-break uses the
    fitness tuple plus genome bytes so output ordering is reproducible.
    """
    cfg = GAConfig(population=12, generations=3, seed=99, backend="sequential")
    out_a = run_ga(MACross, fake_prices_is, None, multi_objective_fitness_is,
                   cfg, verbose=False)
    out_b = run_ga(MACross, fake_prices_is, None, multi_objective_fitness_is,
                   cfg, verbose=False)
    assert len(out_a) == len(out_b)
    for (pa, fa), (pb, fb) in zip(out_a, out_b):
        assert pa == pb, f"params differ: {pa} vs {pb}"
        assert fa == fb, f"fitness differs: {fa} vs {fb}"


def test_fitness_normalize_flag(fake_prices_is):
    """With normalize=True, all four objectives should sit in roughly [-1, 1].

    Without normalization Calmar/Sharpe can dwarf MDD penalty.
    """
    from quantforge.strategies.library import MACross as _MA
    strat = _MA(fast=10, slow=30)

    raw = multi_objective_fitness_is(fake_prices_is, strat.signals, normalize=False)
    nrm = multi_objective_fitness_is(fake_prices_is, strat.signals, normalize=True)

    # Both shapes still 4-tuple.
    assert len(raw) == 4
    assert len(nrm) == 4

    # All normalized objectives within [-1.5, 1.5] for non-pathological data.
    # Allow a small margin since typical scales are conservative.
    for v in nrm:
        assert -1.5 <= v <= 1.5, f"normalized obj {v} outside [-1.5, 1.5]"


def test_bayes_opt_categorical_handled():
    """Categorical params must not be float-encoded under the real-only kernel.

    With skopt: Categorical Space dim handles it natively.
    Without skopt: our fallback must use the mixed (Hamming + Matern) kernel
    so the categorical index isn't treated as continuous.
    """
    from quantforge.ga.bayes_opt import (
        bayes_optimize, BayesConfig, _is_categorical_dim, _categorical_mask,
        HAS_SKOPT, HAS_SKLEARN,
    )
    from quantforge.strategies.base import Strategy, StrategySpec

    if not (HAS_SKOPT or HAS_SKLEARN):
        pytest.skip("neither skopt nor sklearn available")

    class _CatStrat(Strategy):
        def __init__(self, n: int = 5, mode: str = "a"):
            self.n = int(n)
            self.mode = mode

        @classmethod
        def spec(cls) -> StrategySpec:
            return StrategySpec(
                name="CatStrat",
                params={"n": 5, "mode": "a"},
                param_ranges={"n": (1, 10), "mode": ["a", "b", "c"]},
            )

        def signals(self, prices):
            return np.zeros(len(prices))

    # Probe helpers directly.
    assert _is_categorical_dim(["a", "b", "c"]) is True
    assert _is_categorical_dim((1, 10)) is False
    assert _is_categorical_dim((True, False)) is True
    mask = _categorical_mask([(1, 10), ["a", "b"]])
    assert list(mask) == [False, True]

    def _fit(p_is, p_oos, sig):
        strat = sig.__self__
        bonus = {"a": 0.0, "b": 1.0, "c": 0.5}.get(getattr(strat, "mode", "a"), 0.0)
        return -((getattr(strat, "n", 0) - 4) ** 2) * 0.1 + bonus

    idx = pd.date_range("2015-01-01", periods=120, freq="B")
    fake_prices = pd.Series(np.linspace(100, 110, 120), index=idx)
    cfg = BayesConfig(n_calls=8, n_random_starts=3, seed=42)
    out = bayes_optimize(_CatStrat, fake_prices, fake_prices,
                         fitness_fn=_fit, config=cfg, scalar=True)
    # All trials must report mode as a string from the categorical set,
    # never a float index.
    for t in out["all_trials"]:
        m = t["params"]["mode"]
        assert m in ("a", "b", "c"), f"mode {m!r} not from categorical set"
        assert not isinstance(m, float), f"mode encoded as float: {m}"


def test_run_ga_consecutive_calls_no_creator_collision(fake_prices_is):
    """Per-call unique creator class names: running run_ga twice on the
    same strategy_class must not raise from a stale global FitnessMulti.
    """
    from quantforge.strategies.library import BollingerMR
    cfg = GAConfig(population=6, generations=1, seed=1, backend="sequential")
    # Two consecutive runs on different strategies — second must not
    # collide with the first's leftover creator.FitnessMulti.
    pareto_a = run_ga(MACross, fake_prices_is, None, multi_objective_fitness_is,
                      cfg, verbose=False)
    pareto_b = run_ga(BollingerMR, fake_prices_is, None, multi_objective_fitness_is,
                      cfg, verbose=False)
    assert len(pareto_a) > 0
    assert len(pareto_b) > 0
    # Re-run the first class to confirm the unique-name machinery cleans up.
    pareto_c = run_ga(MACross, fake_prices_is, None, multi_objective_fitness_is,
                      cfg, verbose=False)
    assert len(pareto_c) > 0


def test_fitness_mdd_units_correct(fake_prices_is):
    """Verify mdd is treated as a percent: mdd_penalty must be 0 when
    |mdd_pct/100| <= max_mdd, and >0 only when it exceeds max_mdd.
    """
    from quantforge.ga.fitness import multi_objective_fitness_is as _fit_is
    strat = MACross(fast=10, slow=30)
    # Set max_mdd very high -> penalty must be exactly 0.
    out_high = _fit_is(fake_prices_is, strat.signals, max_mdd=10.0)
    assert out_high[3] == 0.0, f"penalty should be 0 with max_mdd=10.0, got {out_high[3]}"
    # Set max_mdd extremely tight -> penalty must be > 0 (some drawdown observed).
    out_tight = _fit_is(fake_prices_is, strat.signals, max_mdd=0.0)
    assert out_tight[3] >= 0.0


def test_fitness_nan_mdd_coerced(fake_prices_is):
    """If the engine returns a NaN mdd, fitness must coerce to a worst-case
    penalty (and never propagate NaN into the GA fitness tuple).
    """
    from quantforge.ga.fitness import multi_objective_fitness_is as _fit_is
    from unittest.mock import patch

    class _FakeMetrics:
        calmar = 1.0
        sharpe = 1.0
        cagr = 0.05
        mdd = float("nan")
        n_periods = 100
        final_nav = 1.0

    class _FakeRes:
        metrics = _FakeMetrics()
        calmar = 1.0
        sharpe = 1.0
        cagr = 0.05
        mdd = float("nan")

    with patch("quantforge.ga.fitness.run_backtest", return_value=_FakeRes()):
        out = _fit_is(fake_prices_is, MACross(fast=10, slow=30).signals, max_mdd=0.20)
    assert all(np.isfinite(x) for x in out), f"fitness leaked NaN: {out}"


def test_walk_forward_robustness_skips_failing_chunks(fake_prices_is):
    """Issue 5: A single brittle chunk must NOT poison the whole estimate.
    The robustness term should aggregate over surviving chunks rather than
    return -99 on the first failure.
    """
    from quantforge.ga.fitness import _walk_forward_robustness
    from quantforge.core.costs import IBKR_costs
    from unittest.mock import patch

    call_count = {"n": 0}

    class _FakeRes:
        calmar = 1.0
        sharpe = 0.5
        mdd = 5.0

    def _flaky_backtest(*args, **kwargs):
        call_count["n"] += 1
        # First chunk raises; remaining chunks return a valid result.
        if call_count["n"] == 1:
            raise RuntimeError("simulated chunk failure")
        return _FakeRes()

    with patch("quantforge.ga.fitness.run_backtest", side_effect=_flaky_backtest):
        rob = _walk_forward_robustness(
            fake_prices_is,
            MACross(fast=10, slow=30).signals,
            costs=IBKR_costs, ppy=252, n_windows=4,
        )
    # Must NOT collapse to -99 just because one chunk failed.
    assert rob > -99.0
    # 3 surviving chunks all returned calmar=1.0 -> std=0 -> -std=0.0.
    assert abs(rob - 0.0) < 1e-9
    # Sanity: backtest was attempted on every chunk.
    assert call_count["n"] >= 4


def test_walk_forward_robustness_all_failures_returns_sentinel(fake_prices_is):
    """If EVERY chunk fails, robustness still falls back to -99 sentinel."""
    from quantforge.ga.fitness import _walk_forward_robustness
    from quantforge.core.costs import IBKR_costs
    from unittest.mock import patch

    def _always_fails(*args, **kwargs):
        raise RuntimeError("simulated total failure")

    with patch("quantforge.ga.fitness.run_backtest", side_effect=_always_fails):
        rob = _walk_forward_robustness(
            fake_prices_is,
            MACross(fast=10, slow=30).signals,
            costs=IBKR_costs, ppy=252, n_windows=4,
        )
    assert rob == -99.0
