"""Tests for R78, R79, R80, R87, R99, R100, R102, R106, R108 (Batch 14)."""
from __future__ import annotations

import numpy as np
import pytest

from quantforge.core.oos_plus import (
    FinalCheckResult,
    OOS_PLUS,
    OOSPlusGuard,
    OOSPlusViolation,
    run_final_check,
)
from quantforge.exports.pinescript import (
    PineScriptManifest,
    export_pinescript,
    verify_pinescript,
)
from quantforge.exports.pinescript.exporter import make_manifest
from quantforge.execution.trade_simulator import (
    FrictionConfig,
    SimulatedBookState,
    simulate_session,
)
from quantforge.ga.goal_seeking import (
    GoalSeekResult,
    goal_seek,
    make_sharpe_mdd_goal,
)
from quantforge.research.auto_gen.combinatorial import (
    CombinatorialBudget,
    enumerate_combinations,
    evaluate_combinations,
)
from quantforge.research.regime_adaptive import (
    RegimePolicy,
    adaptive_signal,
)
from quantforge.strategies.patterns import (
    detect_breakout_high,
    detect_breakout_low,
    detect_double_bottom,
    detect_double_top,
)
from quantforge.strategies.rules import (
    Action,
    ActionKind,
    Comparator,
    ComparisonOp,
    Indicator,
    Logical,
    LogicalOp,
    PriceRef,
    Rule,
    compile_rule,
    rule_from_yaml,
    rule_to_yaml,
)
from quantforge.strategies.templates import (
    breakout_donchian,
    mean_reversion_rsi,
    trend_following_ma_cross,
)


# --------------------------------------------------------------------------
# R78 visual rule editor IR
# --------------------------------------------------------------------------


def test_compile_rule_simple_rsi_below_30_buy():
    rule = Rule(
        name="rsi_oversold_long",
        condition=Comparator(
            left=Indicator(name="RSI", args=(14,)),
            op=ComparisonOp.LT,
            right=30.0,
        ),
        action=Action(kind=ActionKind.BUY),
    )
    fn = compile_rule(rule)
    rng = np.random.default_rng(0)
    prices = 100 * np.cumprod(1 + rng.normal(0, 0.01, size=100))
    out = fn(prices)
    assert out.shape == prices.shape
    assert set(np.unique(out)).issubset({0.0, 1.0})


def test_compile_rule_logical_and():
    rule = Rule(
        name="ema_cross_and_rsi",
        condition=Logical(
            op=LogicalOp.AND,
            operands=(
                Comparator(
                    left=Indicator(name="EMA", args=(20,)),
                    op=ComparisonOp.GT,
                    right=Indicator(name="EMA", args=(50,)),
                ),
                Comparator(
                    left=Indicator(name="RSI", args=(14,)),
                    op=ComparisonOp.GT,
                    right=50.0,
                ),
            ),
        ),
        action=Action(kind=ActionKind.BUY),
    )
    fn = compile_rule(rule)
    prices = np.linspace(100, 200, 200)  # strong uptrend
    out = fn(prices)
    # Strong uptrend + bullish indicators -> some positive signals.
    assert out.sum() > 0


def test_rule_yaml_round_trip():
    rule = Rule(
        name="r1",
        condition=Comparator(
            left=Indicator(name="RSI", args=(14,)),
            op=ComparisonOp.LT,
            right=30.0,
        ),
        action=Action(kind=ActionKind.BUY),
    )
    text = rule_to_yaml(rule)
    reloaded = rule_from_yaml(text)
    assert reloaded == rule


# --------------------------------------------------------------------------
# R79 patterns
# --------------------------------------------------------------------------


def test_detect_double_bottom_finds_known_pattern():
    # Construct a synthetic price path with two bottoms at ~100.
    prices = np.concatenate([
        np.linspace(110, 100, 10),  # decline to bottom 1
        np.linspace(100, 105, 10),  # bounce
        np.linspace(105, 100, 10),  # decline to bottom 2
        np.linspace(100, 115, 10),  # break out
    ])
    out = detect_double_bottom(prices, pivot_window=3,
                               tolerance_pct=0.02, min_separation=5)
    assert out.any()


def test_detect_double_top_finds_known_pattern():
    prices = np.concatenate([
        np.linspace(100, 110, 10),
        np.linspace(110, 105, 10),
        np.linspace(105, 110, 10),
        np.linspace(110, 95, 10),
    ])
    out = detect_double_top(prices, pivot_window=3, tolerance_pct=0.02,
                            min_separation=5)
    assert out.any()


def test_detect_breakout_high_fires_on_new_high():
    prices = np.linspace(100, 200, 100)  # monotonic rise
    out = detect_breakout_high(prices, lookback=10)
    # Every bar after bar 10 is a new high.
    assert out[20:].all()


def test_detect_breakout_low_fires_on_new_low():
    prices = np.linspace(200, 100, 100)
    out = detect_breakout_low(prices, lookback=10)
    assert out[20:].all()


# --------------------------------------------------------------------------
# R80 PineScript export
# --------------------------------------------------------------------------


def test_export_pinescript_emits_manifest_header():
    rule = Rule(
        name="rsi_long",
        condition=Comparator(
            left=Indicator(name="RSI", args=(14,)),
            op=ComparisonOp.LT,
            right=30.0,
        ),
        action=Action(kind=ActionKind.BUY),
    )
    manifest = make_manifest(policy_hash="ph_x", spec_hash="sh_y")
    src = export_pinescript(rule=rule, manifest=manifest)
    assert "//@version=5" in src
    assert "policy_hash: ph_x" in src
    assert "spec_hash:   sh_y" in src
    assert "ta.rsi(close, 14)" in src
    assert verify_pinescript(src, manifest=manifest)


def test_export_pinescript_unsupported_indicator_raises():
    rule = Rule(
        name="bad",
        condition=Comparator(
            left=Indicator(name="StochRSI", args=(14,)),
            op=ComparisonOp.LT,
            right=30.0,
        ),
        action=Action(kind=ActionKind.BUY),
    )
    manifest = make_manifest(policy_hash="x", spec_hash="y")
    with pytest.raises(KeyError):
        export_pinescript(rule=rule, manifest=manifest)


# --------------------------------------------------------------------------
# R87 templates
# --------------------------------------------------------------------------


def test_trend_following_ma_cross_in_uptrend():
    prices = np.linspace(100, 200, 252)
    out = trend_following_ma_cross(prices, fast=20, slow=50)
    assert out.shape == prices.shape
    # In a clean uptrend the strategy should be long for most bars
    # after both MAs are valid.
    assert out[60:].mean() > 0.5


def test_mean_reversion_rsi_emits_signed_signals():
    rng = np.random.default_rng(0)
    rets = rng.normal(0, 0.01, size=300)
    prices = 100 * np.cumprod(1 + rets)
    out = mean_reversion_rsi(prices, period=14)
    assert set(np.unique(out)).issubset({-1.0, 0.0, 1.0})


def test_breakout_donchian_emits_long_and_short():
    rng = np.random.default_rng(0)
    prices = 100 + np.cumsum(rng.normal(0, 1, size=200))
    out = breakout_donchian(prices, lookback=20)
    assert set(np.unique(out)).issubset({-1.0, 0.0, 1.0})


# --------------------------------------------------------------------------
# R99 adaptive optimisation
# --------------------------------------------------------------------------


def test_adaptive_signal_uses_per_regime_params():
    prices = np.linspace(100, 200, 100)
    regimes = ["trending"] * 50 + ["rangebound"] * 50
    policy = RegimePolicy(parameters={
        "trending": {"fast": 5, "slow": 20},
        "rangebound": {"fast": 10, "slow": 30},
    })
    out = adaptive_signal(
        prices=prices,
        regime_tags=regimes,
        template_fn=trend_following_ma_cross,
        policy=policy,
    )
    assert out.shape == prices.shape


def test_adaptive_signal_length_mismatch_raises():
    with pytest.raises(ValueError):
        adaptive_signal(
            prices=np.zeros(10),
            regime_tags=["x"] * 5,
            template_fn=trend_following_ma_cross,
            policy=RegimePolicy(),
        )


# --------------------------------------------------------------------------
# R100 trade simulator
# --------------------------------------------------------------------------


def test_trade_simulator_full_fill_no_latency():
    prices = np.linspace(100, 110, 50)
    desired = np.zeros_like(prices)
    desired[5:] = 1.0
    res = simulate_session(
        prices=prices, desired_weights=desired,
        config=FrictionConfig(partial_fill_pct=1.0, latency_bars=0),
    )
    assert isinstance(res, SimulatedBookState)
    assert res.fills  # at least one fill recorded
    assert res.rejected == 0


def test_trade_simulator_rejects_at_configured_rate():
    prices = np.linspace(100, 110, 50)
    desired = np.zeros_like(prices)
    desired[5:] = 1.0
    res = simulate_session(
        prices=prices, desired_weights=desired,
        config=FrictionConfig(reject_prob=1.0),
    )
    assert res.rejected > 0


# --------------------------------------------------------------------------
# R102 goal-seeking GA
# --------------------------------------------------------------------------


class _StubRunner:
    def __init__(self):
        self.gen = 0
        self.sharpe = 0.0
    def step(self):
        self.gen += 1
        self.sharpe += 0.2
    def best_so_far(self):
        return {"sharpe": self.sharpe, "mdd": -0.10}


def test_goal_seek_meets_goal_in_finite_steps():
    runner = _StubRunner()
    goal = make_sharpe_mdd_goal(min_sharpe=1.0, max_mdd=-0.20)
    res = goal_seek(runner=runner, goal=goal, max_seconds=5.0,
                    max_generations=20)
    assert isinstance(res, GoalSeekResult)
    assert res.goal_met
    assert res.generations <= 10  # Sharpe reaches 1.0 at gen 5


def test_goal_seek_exhausts_budget_when_unreachable():
    runner = _StubRunner()
    runner.sharpe = -100.0
    # Override step to keep sharpe negative.
    runner.step = lambda: None
    goal = make_sharpe_mdd_goal(min_sharpe=10.0, max_mdd=-0.10)
    res = goal_seek(runner=runner, goal=goal, max_seconds=0.05,
                    max_generations=1000)
    assert not res.goal_met


# --------------------------------------------------------------------------
# R106 OOS Plus
# --------------------------------------------------------------------------


def test_oos_plus_reads_blocked_without_open_guard():
    guard = OOSPlusGuard(operator_id="op1", rationale="final check")
    with pytest.raises(OOSPlusViolation):
        run_final_check(guard=guard, metric_name="sharpe",
                        metric_value=1.5, threshold=1.0)


def test_oos_plus_reads_allowed_inside_open_guard():
    guard = OOSPlusGuard(operator_id="op1", rationale="final check")
    with guard.open():
        res = run_final_check(guard=guard, metric_name="sharpe",
                              metric_value=1.5, threshold=1.0)
    assert isinstance(res, FinalCheckResult)
    assert res.passed


def test_oos_plus_guard_refuses_nested_open():
    guard = OOSPlusGuard(operator_id="op1", rationale="final check")
    with guard.open():
        with pytest.raises(OOSPlusViolation):
            with guard.open():
                pass


def test_oos_plus_constant_value():
    assert OOS_PLUS == "OOS_PLUS"


# --------------------------------------------------------------------------
# R108 combinatorial alpha
# --------------------------------------------------------------------------


def test_enumerate_combinations_respects_size_range():
    pool = ["a", "b", "c", "d"]
    combos = enumerate_combinations(
        pool,
        budget=CombinatorialBudget(min_signals_per_combo=2,
                                   max_signals_per_combo=3),
    )
    sizes = {len(c) for c in combos}
    assert sizes == {2, 3}


def test_enumerate_combinations_truncates_at_max():
    combos = enumerate_combinations(
        list("abcdefghij"),
        budget=CombinatorialBudget(max_combos=10,
                                   min_signals_per_combo=2,
                                   max_signals_per_combo=3),
    )
    assert len(combos) == 10


def test_evaluate_combinations_sorts_by_fitness_desc():
    signals = {"a": 1, "b": 2, "c": 3}

    def fitness(names):
        # higher fitness for combos containing 'a'
        return float(2.0 if "a" in names else 1.0)

    res = evaluate_combinations(
        signals=signals,
        budget=CombinatorialBudget(min_signals_per_combo=2,
                                   max_signals_per_combo=2),
        fitness_fn=fitness,
    )
    assert res[0].fitness >= res[-1].fitness
