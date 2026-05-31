"""Tests for Bayesian optimization (aurora.ga.bayes_opt)."""
from __future__ import annotations
import numpy as np
import pandas as pd
import pytest

from aurora.strategies.base import Strategy, StrategySpec
from aurora.ga.bayes_opt import (
    bayes_optimize,
    BayesConfig,
    _build_skopt_space,
    _decode_skopt,
    _scalarize,
    HAS_SKOPT,
)


# ---------------- helper toy strategies ----------------

class _ToyQuad(Strategy):
    """Toy strategy whose fitness is a deterministic quadratic of params.

    Avoids hitting the backtest engine. Optimum at fast=15, slow=80.
    """
    def __init__(self, fast: int = 10, slow: int = 100):
        self.fast = int(fast)
        self.slow = int(slow)

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="ToyQuad",
            params={"fast": 10, "slow": 100},
            param_ranges={"fast": (5, 30), "slow": (50, 150)},
        )

    def signals(self, prices):
        # not used by fitness_fn below
        return np.zeros(len(prices))


class _ToyMixed(Strategy):
    """Mixed types: int range + float range + categorical list."""
    def __init__(self, n: int = 5, alpha: float = 0.5, mode: str = "a"):
        self.n = int(n)
        self.alpha = float(alpha)
        self.mode = mode

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="ToyMixed",
            params={"n": 5, "alpha": 0.5, "mode": "a"},
            param_ranges={
                "n": (1, 10),
                "alpha": (0.0, 1.0),
                "mode": ["a", "b", "c"],
            },
        )

    def signals(self, prices):
        return np.zeros(len(prices))


class _BadSpec(Strategy):
    """Spec with invalid range → must fail loudly."""
    def __init__(self, x: int = 1):
        self.x = x

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="BadSpec",
            params={"x": 1},
            param_ranges={"x": "not-a-tuple"},
        )

    def signals(self, prices):
        return np.zeros(len(prices))


def _quadratic_fitness(prices_is, prices_oos, signal_fn):
    """Deterministic scalar fitness on the bound strategy attrs.

    signal_fn is bound to a strategy instance; we can recover params from its __self__.
    """
    strat = signal_fn.__self__
    fast = getattr(strat, "fast", None)
    slow = getattr(strat, "slow", None)
    if fast is None or slow is None:
        # ToyMixed branch
        n = getattr(strat, "n", 0)
        alpha = getattr(strat, "alpha", 0.0)
        mode = getattr(strat, "mode", "a")
        mode_bonus = {"a": 0.0, "b": 1.0, "c": 0.5}.get(mode, 0.0)
        return -((n - 4) ** 2) * 0.1 - (alpha - 0.7) ** 2 + mode_bonus
    return -((fast - 15) ** 2) * 0.05 - ((slow - 80) ** 2) * 0.01


@pytest.fixture
def fake_prices():
    idx = pd.date_range("2015-01-01", periods=300, freq="B")
    return pd.Series(np.linspace(100, 110, 300), index=idx)


# ---------------- tests ----------------

def test_basic(fake_prices):
    cfg = BayesConfig(n_calls=15, n_random_starts=5, seed=42)
    out = bayes_optimize(
        _ToyQuad, fake_prices, fake_prices,
        fitness_fn=_quadratic_fitness, config=cfg, scalar=True,
    )
    assert isinstance(out, dict)
    for k in ("best_params", "best_score", "all_trials", "convergence"):
        assert k in out
    assert isinstance(out["best_params"], dict)
    assert "fast" in out["best_params"] and "slow" in out["best_params"]
    assert len(out["all_trials"]) == 15
    assert len(out["convergence"]) == 15
    # convergence must be non-decreasing (best-so-far)
    for a, b in zip(out["convergence"], out["convergence"][1:]):
        assert b >= a - 1e-9


@pytest.mark.skipif(not HAS_SKOPT, reason="skopt required for direct space-decode test")
def test_decode_params():
    spec = _ToyMixed.spec()
    keys, dims = _build_skopt_space(spec.param_ranges)
    assert keys == ["alpha", "mode", "n"]

    from skopt.space import Real, Integer, Categorical
    name_to_dim = {d.name: d for d in dims}
    assert isinstance(name_to_dim["n"], Integer)
    assert isinstance(name_to_dim["alpha"], Real)
    assert isinstance(name_to_dim["mode"], Categorical)

    decoded = _decode_skopt([0.7, "b", 5], keys, spec.param_ranges)
    assert decoded == {"alpha": 0.7, "mode": "b", "n": 5}
    assert isinstance(decoded["n"], int)
    assert isinstance(decoded["alpha"], float)


def test_invalid_space(fake_prices):
    cfg = BayesConfig(n_calls=5, n_random_starts=2, seed=42)
    with pytest.raises((ValueError, TypeError)):
        bayes_optimize(
            _BadSpec, fake_prices, fake_prices,
            fitness_fn=_quadratic_fitness, config=cfg, scalar=True,
        )


def test_reproducibility(fake_prices):
    cfg1 = BayesConfig(n_calls=12, n_random_starts=4, seed=7)
    cfg2 = BayesConfig(n_calls=12, n_random_starts=4, seed=7)
    a = bayes_optimize(_ToyQuad, fake_prices, fake_prices,
                       fitness_fn=_quadratic_fitness, config=cfg1, scalar=True)
    b = bayes_optimize(_ToyQuad, fake_prices, fake_prices,
                       fitness_fn=_quadratic_fitness, config=cfg2, scalar=True)
    assert a["best_params"] == b["best_params"]
    assert pytest.approx(a["best_score"], rel=1e-9) == b["best_score"]


def test_scalarize_helper():
    # Backwards-compat: 3-element weights default w_mdd to 0.5 so the mdd
    # penalty is on the same order as the other three weighted objectives.
    # Previously w_mdd was implicitly 1.0 which let the MDD term dominate
    # whenever all four objectives were on similar scales.
    s = _scalarize((1.0, 2.0, -0.5, 0.1), weights=(0.5, 0.3, 0.2))
    assert pytest.approx(s, rel=1e-9) == 0.5 * 1.0 + 0.3 * 2.0 + 0.2 * (-0.5) - 0.5 * 0.1
    # Explicit 4-tuple weights override the default w_mdd.
    s2 = _scalarize((1.0, 2.0, -0.5, 0.1), weights=(0.5, 0.3, 0.2, 1.0))
    assert pytest.approx(s2, rel=1e-9) == 0.5 * 1.0 + 0.3 * 2.0 + 0.2 * (-0.5) - 1.0 * 0.1


def test_multi_objective_scalarized(fake_prices):
    """Pass a tuple-returning fitness with scalar=False → BO scalarizes internally."""
    def tuple_fit(p_is, p_oos, sig):
        s = _quadratic_fitness(p_is, p_oos, sig)
        # fake (calmar, sharpe, robust, mdd_pen) where calmar=s
        return (s, 0.0, 0.0, 0.0)

    cfg = BayesConfig(n_calls=10, n_random_starts=4, seed=42)
    out = bayes_optimize(_ToyQuad, fake_prices, fake_prices,
                         fitness_fn=tuple_fit, config=cfg, scalar=False)
    assert "best_score" in out
    assert len(out["all_trials"]) == 10


def test_oos_never_passed_to_legacy_fitness(fake_prices):
    """OOS-sagrado: legacy 3-arg fitness must receive None for prices_oos.

    Even though the call site originally passed prices_oos, the new
    bayes_optimize forwards None to mirror runner.run_ga and stop the
    deprecated 3-arg implementations from leaking OOS into selection.
    """
    seen_oos = []

    def legacy_fit(p_is, p_oos, sig):
        seen_oos.append(p_oos)
        # quadratic fallback so optimization is well-defined
        strat = sig.__self__
        fast = getattr(strat, "fast", 15)
        slow = getattr(strat, "slow", 80)
        return -((fast - 15) ** 2) * 0.05 - ((slow - 80) ** 2) * 0.01

    # Build a distinct OOS series so we can detect any leak unambiguously.
    idx = pd.date_range("2017-01-01", periods=80, freq="B")
    prices_oos = pd.Series(np.linspace(200, 220, 80), index=idx)
    cfg = BayesConfig(n_calls=8, n_random_starts=3, seed=42)
    out = bayes_optimize(_ToyQuad, fake_prices, prices_oos,
                         fitness_fn=legacy_fit, config=cfg, scalar=True)
    assert len(out["all_trials"]) == 8
    # Every observed prices_oos must be None — the legacy series must not leak.
    assert seen_oos, "fitness_fn was never called"
    for o in seen_oos:
        assert o is None, "legacy fitness saw non-None prices_oos -> OOS leak"


def test_is_wrapper_guard_raises():
    """bayes_optimize must refuse strategies marked is_wrapper=True."""
    class _Wrap(Strategy):
        is_wrapper = True

        @classmethod
        def spec(cls) -> StrategySpec:
            return StrategySpec(name="Wrap", params={"x": 1},
                                param_ranges={"x": (1, 10)})

        def signals(self, prices):
            return np.zeros(len(prices))

    idx = pd.date_range("2015-01-01", periods=80, freq="B")
    p = pd.Series(np.linspace(100, 110, 80), index=idx)
    cfg = BayesConfig(n_calls=4, n_random_starts=2, seed=1)
    with pytest.raises(TypeError, match="is_wrapper"):
        bayes_optimize(_Wrap, p, p,
                       fitness_fn=lambda *_a, **_kw: 0.0, config=cfg, scalar=True)


def test_fallback_space_rejects_bad_tuple_length():
    """_build_fallback_space must raise on tuple length != 2 with a clear msg."""
    from aurora.ga.bayes_opt import _build_fallback_space
    with pytest.raises(ValueError, match="must be \\(lo, hi\\)"):
        _build_fallback_space({"x": (1, 2, 3)})
    with pytest.raises(ValueError, match="must be a list"):
        _build_fallback_space({"x": "not-a-tuple"})


def test_fitness_fn_required(fake_prices):
    """bayes_optimize without fitness_fn must raise TypeError loudly."""
    cfg = BayesConfig(n_calls=4, n_random_starts=2, seed=1)
    with pytest.raises(TypeError, match="fitness_fn"):
        bayes_optimize(_ToyQuad, fake_prices, fake_prices,
                       fitness_fn=None, config=cfg, scalar=True)
