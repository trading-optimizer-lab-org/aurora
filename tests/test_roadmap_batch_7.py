"""Tests for roadmap items R77, R88, R89, R97, R110, R122, R124, R149,
R150, R151, R154 batch."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from aurora.analytics.replay_debugger import render_frame, replay
from aurora.deployment.money_management import (
    AntiMartingaleConfig,
    anti_martingale_sizing,
    drawdown_scaled_sizing,
    fixed_ratio_sizing,
    fractional_kelly_with_shrinkage,
    profit_step_pyramid,
)
from aurora.monitoring.cross_strategy_correlation import (
    StrategySnapshot,
    find_common_cause,
)
from aurora.monitoring.multi_channel_alerts import (
    AlertEvent,
    ChannelRoute,
    MultiChannelAlerter,
    PushoverProvider,
)
from aurora.research.auto_gen import (
    AtomicBlockGenerator,
    Comparator,
    combinatorial_pairs,
)
from aurora.strategies.blocks import STANDARD_REGISTRY
from aurora.strategies.library.grid import GridStrategy
from aurora.validation.corporate_actions_audit import (
    ActionKind,
    CorporateAction,
    verify_cash_dividend,
    verify_split,
)
from aurora.validation.cv_matrices import build_matrix
from aurora.validation.holiday_calendar_audit import (
    audit_orders,
    is_market_open,
)
from aurora.validation.robustness_suite import (
    GateResult,
    PRESET_FAST,
    run_robustness_suite,
)
from aurora.validation.survivorship_audit import audit_survivorship


# --------------------------------------------------------------------------
# R77 atomic-block generator
# --------------------------------------------------------------------------


def test_generator_yields_n_specs():
    gen = AtomicBlockGenerator()
    specs = gen.generate(n=8, seed=42)
    assert len(specs) == 8
    for s in specs:
        assert s.name.startswith("AutoGen_")


def test_generator_is_reproducible_under_seed():
    gen = AtomicBlockGenerator()
    a = gen.generate(n=5, seed=42)
    b = gen.generate(n=5, seed=42)
    assert [s.spec_hash for s in a] == [s.spec_hash for s in b]


def test_combinatorial_pairs_enumerates_pool():
    pairs = list(combinatorial_pairs(
        STANDARD_REGISTRY, ["SMA", "EMA", "RSI"],
        comparators=[Comparator.GT],
    ))
    # 3-choose-2 = 3 pairs, 1 comparator -> 3 rules.
    assert len(pairs) == 3


# --------------------------------------------------------------------------
# R88 money management
# --------------------------------------------------------------------------


def test_anti_martingale_scales_up_with_wins():
    a = anti_martingale_sizing(0, max_leverage=5.0)
    b = anti_martingale_sizing(5, max_leverage=5.0)
    assert b > a


def test_drawdown_scaled_floor():
    s = drawdown_scaled_sizing(50, base_size=1.0, loss_step=0.05, floor=0.30)
    assert s == 0.30


def test_fixed_ratio_grows_with_pnl():
    a = fixed_ratio_sizing(cumulative_pnl=0.0, max_leverage=5.0)
    b = fixed_ratio_sizing(cumulative_pnl=50_000.0, max_leverage=5.0)
    assert b > a


def test_kelly_shrinks_when_realised_vol_high():
    base = fractional_kelly_with_shrinkage(edge=0.05, variance=0.04, fraction=0.5)
    shrunk = fractional_kelly_with_shrinkage(
        edge=0.05, variance=0.04, fraction=0.5,
        realised_vol=0.30, expected_vol=0.15,
    )
    assert shrunk < base


def test_profit_step_pyramid_caps_at_max_size():
    s = profit_step_pyramid(open_pnl=10.0, step_size=0.01,
                             add_per_step=1.0, base_size=1.0,
                             max_size=2.5, max_leverage=5.0)
    assert s == 2.5


# --------------------------------------------------------------------------
# R89 robustness preset
# --------------------------------------------------------------------------


def test_robustness_suite_default_runners_pass():
    rep = run_robustness_suite(preset="fast")
    assert rep.preset == "fast"
    assert rep.overall_passed is True
    assert {g.name for g in rep.gates} == set(PRESET_FAST)


def test_robustness_suite_failed_runner_fails_overall():
    runners = {
        "spp_cv": lambda: GateResult("spp_cv", False, 0.5, "above threshold"),
    }
    rep = run_robustness_suite(preset="fast", gate_runners=runners)
    assert rep.overall_passed is False
    assert "spp_cv" in rep.fail_summary()[0]


# --------------------------------------------------------------------------
# R97 cross-validation matrix
# --------------------------------------------------------------------------


def test_cv_matrix_summary_lists_worst_fold():
    m = build_matrix(
        fold_labels=["f1", "f2", "f3"],
        train_metrics=[1.5, 1.6, 1.4],
        test_metrics=[1.4, 0.4, 1.3],
    )
    assert m.worst_fold_index == 1
    assert "f2" in m.summary()


# --------------------------------------------------------------------------
# R110 replay debugger
# --------------------------------------------------------------------------


def test_replay_yields_one_frame_per_bar():
    idx = pd.date_range("2026-01-01", periods=5, freq="B")
    prices = pd.Series([100, 101, 100, 102, 101], index=idx, dtype=float)
    weights = np.array([0.0, 0.5, 0.5, 1.0, 1.0])
    frames = list(replay(prices, weights))
    assert len(frames) == 5
    assert frames[0].weight_before == 0.0
    assert frames[1].weight_after == 0.5
    rendered = render_frame(frames[2])
    assert "bar" in rendered


# --------------------------------------------------------------------------
# R122 multi-channel alerts
# --------------------------------------------------------------------------


def test_pushover_returns_error_when_env_unset(monkeypatch):
    monkeypatch.delenv("PUSHOVER_TOKEN", raising=False)
    monkeypatch.delenv("PUSHOVER_USER", raising=False)
    p = PushoverProvider()
    res = p.send(AlertEvent(title="x", body="y", severity="warn"))
    assert res["ok"] is False


def test_multi_channel_alerter_routes_by_severity():
    fake_warn = MagicMock()
    fake_warn.name = "warn-provider"
    fake_warn.send.return_value = {"ok": True}
    fake_error = MagicMock()
    fake_error.name = "error-provider"
    fake_error.send.return_value = {"ok": True}
    alerter = MultiChannelAlerter(routes=[
        ChannelRoute(severity="warn", providers=[fake_warn]),
        ChannelRoute(severity="error", providers=[fake_error]),
    ])
    out = alerter.send(AlertEvent("t", "b", severity="warn"))
    assert out and out[0]["provider"] == "warn-provider"
    fake_warn.send.assert_called_once()
    fake_error.send.assert_not_called()


# --------------------------------------------------------------------------
# R124 grid strategy
# --------------------------------------------------------------------------


def test_grid_signals_within_position_cap():
    rng = np.random.default_rng(0)
    rets = rng.normal(0, 0.005, 200)
    prices = pd.Series(
        100.0 * np.cumprod(1.0 + rets),
        index=pd.date_range("2026-01-01", periods=200, freq="B"),
    )
    sig = GridStrategy(lookback=20, max_position=0.6).signals(prices)
    assert np.all(np.abs(sig) <= 0.6 + 1e-9)


def test_grid_validates_params():
    with pytest.raises(ValueError):
        GridStrategy(step_pct=0)
    with pytest.raises(ValueError):
        GridStrategy(max_depth=0)
    with pytest.raises(ValueError):
        GridStrategy(max_position=1.5)


# --------------------------------------------------------------------------
# R149 survivorship audit
# --------------------------------------------------------------------------


def test_survivorship_flags_not_listed_yet():
    findings = audit_survivorship(
        backtest_universe={"NEW", "OLD"},
        backtest_window=(date(2020, 1, 1), date(2026, 1, 1)),
        historical_listings={
            "NEW": (date(2024, 1, 1), None),  # listed after start
            "OLD": (date(2010, 1, 1), None),  # ok
        },
    )
    assert any(f.ticker == "NEW" and f.reason == "not_listed_yet" for f in findings)
    assert all(f.ticker != "OLD" for f in findings)


def test_survivorship_flags_delisted():
    findings = audit_survivorship(
        backtest_universe={"GONE"},
        backtest_window=(date(2010, 1, 1), date(2026, 1, 1)),
        historical_listings={"GONE": (date(2010, 1, 1), date(2018, 6, 30))},
    )
    assert findings[0].reason == "delisted"


# --------------------------------------------------------------------------
# R150 corporate actions
# --------------------------------------------------------------------------


def test_split_verifier_passes_correct_adjustment():
    action = CorporateAction(
        ticker="SPY", when=date(2026, 5, 8), kind=ActionKind.SPLIT, ratio=2.0,
    )
    v = verify_split(action, pre_price=400.0, pre_position=10,
                     post_price=200.0, post_position=20)
    assert v.price_correct and v.position_correct


def test_dividend_verifier_catches_wrong_cash():
    action = CorporateAction(
        ticker="SPY", when=date(2026, 5, 8),
        kind=ActionKind.DIVIDEND_CASH, cash_amount=2.0,
    )
    v = verify_cash_dividend(
        action, pre_price=400.0, pre_position=10,
        post_price=398.0, cash_balance_delta=15.0,  # wrong (expected 20)
    )
    assert v.price_correct
    assert v.position_correct is False


# --------------------------------------------------------------------------
# R151 holiday calendar
# --------------------------------------------------------------------------


def test_market_closed_on_christmas():
    assert is_market_open(date(2026, 12, 25), exchange="NYSE") is False


def test_audit_orders_flags_weekend_and_holiday():
    orders = [
        datetime(2026, 5, 9, 14, 0),   # Saturday
        datetime(2026, 12, 25, 14, 0),  # Christmas
        datetime(2026, 5, 11, 14, 0),  # Monday
    ]
    violations = audit_orders(orders, exchange="NYSE")
    reasons = {v.reason for v in violations}
    assert reasons == {"weekend", "holiday"}


# --------------------------------------------------------------------------
# R154 cross-strategy correlation alert
# --------------------------------------------------------------------------


def test_cross_strategy_alert_fires_when_multiple_underperform():
    snaps = [
        StrategySnapshot(
            strategy_id="alpha",
            recent_returns=np.array([-0.01, -0.02]),
            factor_tags=["momentum"],
            regime_tag="risk_off",
        ),
        StrategySnapshot(
            strategy_id="beta",
            recent_returns=np.array([-0.015, -0.02]),
            factor_tags=["momentum"],
            regime_tag="risk_off",
        ),
        StrategySnapshot(
            strategy_id="ok",
            recent_returns=np.array([0.001, 0.002]),
            factor_tags=["meanrev"],
        ),
    ]
    rep = find_common_cause(snaps, underperform_threshold=-0.02, min_count=2)
    assert rep is not None
    assert set(rep.underperformers) == {"alpha", "beta"}
    assert "momentum" in rep.common_factor_tags
    assert rep.common_regime == "risk_off"


def test_cross_strategy_alert_silent_when_below_min_count():
    snaps = [
        StrategySnapshot(
            strategy_id="alpha",
            recent_returns=np.array([-0.05]),
        ),
    ]
    assert find_common_cause(snaps, min_count=2) is None
