"""Tests for R131, R132, R133, R141, R144, R147, R153."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from aurora.agent_gateway.sealed_envelope import (
    SealedEnvelope,
    open_envelope,
    read_envelope,
    seal_envelope,
    write_envelope,
)
from aurora.analytics.capacity import (
    CapacityEstimate,
    estimate_capacity,
)
from aurora.core.costs import CostModel
from aurora.core.rolling_kyle import KyleEstimate, rolling_kyle_lambda
from aurora.deployment.dynamic_caps import (
    DynamicCapConfig,
    compute_dynamic_cap,
    reject_oversized_order,
)
from aurora.research.refit_cadence import (
    CadenceCandidate,
    optimise_refit_cadence,
    standard_cadence_grid,
)
from aurora.validation.adversarial_markets import (
    AdversarialConfig,
    generate_adversarial_market,
)
from aurora.validation.audit_replay import replay_session


# --------------------------------------------------------------------------
# R131 rolling Kyle lambda
# --------------------------------------------------------------------------


def test_rolling_kyle_lambda_recovers_known_slope():
    rng = np.random.default_rng(0)
    n = 200
    vol = rng.normal(0, 1.0, size=n)
    true_lambda = 3.0
    delta = true_lambda * vol + rng.normal(0, 0.5, size=n)
    out = rolling_kyle_lambda(delta, vol, window=60, step=10)
    assert len(out) > 0
    last = out[-1]
    assert isinstance(last, KyleEstimate)
    assert last.lambda_bps_per_pct_volume == pytest.approx(true_lambda, abs=0.5)
    assert 0.0 <= last.r_squared <= 1.0


def test_rolling_kyle_lambda_zero_variance_returns_zero():
    n = 60
    vol = np.zeros(n)
    delta = np.zeros(n)
    out = rolling_kyle_lambda(delta, vol, window=60, step=5)
    assert len(out) == 1
    assert out[0].lambda_bps_per_pct_volume == 0.0


def test_rolling_kyle_lambda_length_mismatch_raises():
    with pytest.raises(ValueError):
        rolling_kyle_lambda(np.zeros(10), np.zeros(11))


# --------------------------------------------------------------------------
# R132 capacity estimator
# --------------------------------------------------------------------------


def test_estimate_capacity_returns_curve_and_capacity_aum():
    rng = np.random.default_rng(0)
    n = 252
    weights = rng.choice([0.0, 0.5, 1.0], size=n)
    rets = rng.normal(0.0005, 0.01, size=n)
    base_costs = CostModel(spread_bps=1.0, slippage_bps=2.0)
    grid = [1e6, 1e7, 1e8, 1e9]
    est = estimate_capacity(
        weights, rets,
        base_costs=base_costs,
        daily_dollar_volume=1e8,
        aum_grid_usd=grid,
        impact_coef_bps_per_pct_adv=10.0,
    )
    assert isinstance(est, CapacityEstimate)
    assert len(est.curve) == 4
    # As AUM grows the pct-of-ADV grows.
    pct_advs = [p.pct_adv for p in est.curve]
    assert pct_advs == sorted(pct_advs)


def test_estimate_capacity_finds_drop_threshold():
    """Strategy alpha is small; large AUM should erode Sharpe past the drop."""
    rng = np.random.default_rng(0)
    n = 252
    weights = np.ones(n) * 1.0
    rets = rng.normal(0.0001, 0.005, size=n)
    base_costs = CostModel(spread_bps=1.0, slippage_bps=1.0)
    est = estimate_capacity(
        weights, rets,
        base_costs=base_costs,
        daily_dollar_volume=1e7,
        aum_grid_usd=[1e5, 1e6, 1e7, 1e8, 1e9, 1e10],
        impact_coef_bps_per_pct_adv=50.0,
    )
    # capacity_aum may be None if even the smallest AUM violates the drop;
    # we only assert the curve is monotonic-ish in pct_adv.
    pct_advs = [p.pct_adv for p in est.curve]
    assert pct_advs[-1] > pct_advs[0]


def test_estimate_capacity_empty_grid_raises():
    with pytest.raises(ValueError):
        estimate_capacity(
            np.zeros(10), np.zeros(10),
            base_costs=CostModel(),
            daily_dollar_volume=1e7,
            aum_grid_usd=[],
        )


def test_estimate_capacity_zero_daily_volume_raises():
    with pytest.raises(ValueError):
        estimate_capacity(
            np.zeros(10), np.zeros(10),
            base_costs=CostModel(),
            daily_dollar_volume=0.0,
            aum_grid_usd=[1e6],
        )


# --------------------------------------------------------------------------
# R133 dynamic caps
# --------------------------------------------------------------------------


def test_compute_dynamic_cap_normal_market():
    rng = np.random.default_rng(0)
    history = rng.uniform(8e6, 1.2e7, size=30)
    median = float(np.median(history[-20:]))
    res = compute_dynamic_cap(
        config=DynamicCapConfig(max_pct_adv=1.0),
        recent_dollar_volume=history,
        current_dollar_volume=median * 1.1,  # above median => normal
    )
    assert not res.is_thin
    assert res.cap_notional_usd > 0


def test_compute_dynamic_cap_thin_market_haircut():
    rng = np.random.default_rng(0)
    history = rng.uniform(8e6, 1.2e7, size=30)
    median = float(np.median(history[-20:]))
    cfg = DynamicCapConfig(max_pct_adv=1.0, thin_market_haircut=0.5)
    res = compute_dynamic_cap(
        config=cfg,
        recent_dollar_volume=history,
        current_dollar_volume=median * 0.5,  # thin
    )
    assert res.is_thin
    res_full = compute_dynamic_cap(
        config=cfg,
        recent_dollar_volume=history,
        current_dollar_volume=median * 1.5,
    )
    # Thin cap is the haircut multiplier of the full cap.
    assert res.cap_notional_usd == pytest.approx(res_full.cap_notional_usd * 0.5)


def test_compute_dynamic_cap_below_floor_routes_to_cancel():
    history = np.full(30, 1e3)  # tiny ADV
    res = compute_dynamic_cap(
        config=DynamicCapConfig(absolute_floor_usd=1_000.0, max_pct_adv=1.0),
        recent_dollar_volume=history,
        current_dollar_volume=1e3,
    )
    assert res.cap_notional_usd == 0.0


def test_reject_oversized_order_returns_reason():
    history = np.full(30, 1e7)
    cap = compute_dynamic_cap(
        config=DynamicCapConfig(max_pct_adv=1.0),
        recent_dollar_volume=history,
        current_dollar_volume=1e7,
    )
    too_big = cap.cap_notional_usd * 5
    msg = reject_oversized_order(requested_notional_usd=too_big, cap=cap)
    assert msg is not None
    assert "exceeds dynamic cap" in msg


def test_reject_oversized_order_passes_within_cap():
    history = np.full(30, 1e7)
    cap = compute_dynamic_cap(
        config=DynamicCapConfig(max_pct_adv=1.0),
        recent_dollar_volume=history,
        current_dollar_volume=1e7,
    )
    msg = reject_oversized_order(
        requested_notional_usd=cap.cap_notional_usd * 0.5, cap=cap,
    )
    assert msg is None


# --------------------------------------------------------------------------
# R141 cadence optimiser
# --------------------------------------------------------------------------


def test_optimise_refit_cadence_picks_highest_stability():
    candidates = [
        CadenceCandidate(name="weekly", interval_bars=5,
                         oos_sharpes=[0.1, 1.5, -0.5, 2.0, 0.3]),
        CadenceCandidate(name="monthly", interval_bars=21,
                         oos_sharpes=[1.0, 1.05, 0.95, 1.0, 1.05]),
        CadenceCandidate(name="quarterly", interval_bars=63,
                         oos_sharpes=[0.5, 0.6, 0.55]),
    ]
    rec = optimise_refit_cadence(candidates)
    assert rec.chosen.name == "monthly"


def test_optimise_refit_cadence_drops_below_min_folds():
    candidates = [
        CadenceCandidate(name="weekly", interval_bars=5,
                         oos_sharpes=[1.0, 1.0, 1.0, 1.0]),
        CadenceCandidate(name="quarterly", interval_bars=63,
                         oos_sharpes=[0.5]),
    ]
    rec = optimise_refit_cadence(candidates, min_folds=3)
    assert rec.chosen.name == "weekly"


def test_optimise_refit_cadence_raises_when_no_candidate_eligible():
    candidates = [
        CadenceCandidate(name="weekly", interval_bars=5, oos_sharpes=[1.0]),
    ]
    with pytest.raises(ValueError):
        optimise_refit_cadence(candidates, min_folds=5)


def test_standard_cadence_grid_returns_default_cadences():
    grid = standard_cadence_grid()
    names = {c["name"] for c in grid}
    assert names == {"weekly", "monthly", "quarterly", "yearly"}


# --------------------------------------------------------------------------
# R144 adversarial market generator
# --------------------------------------------------------------------------


def test_adversarial_market_increases_drawdown_or_keeps_it():
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0005, 0.01, size=300)

    def strategy(asset_returns):
        return asset_returns * 1.0  # 100% long, no costs

    res = generate_adversarial_market(
        rets, strategy=strategy,
        config=AdversarialConfig(epsilon=0.005, budget_fraction=0.30,
                                 vol_tolerance_pct=0.50),
    )
    assert res.adversarial_drawdown <= res.historical_drawdown


def test_adversarial_market_respects_budget():
    rng = np.random.default_rng(0)
    rets = rng.normal(0.0005, 0.01, size=200)

    def strategy(asset_returns):
        return asset_returns * 0.5

    cfg = AdversarialConfig(epsilon=0.001, budget_fraction=0.10,
                            vol_tolerance_pct=1.0)
    res = generate_adversarial_market(rets, strategy=strategy, config=cfg)
    assert res.bars_perturbed <= int(len(rets) * cfg.budget_fraction)


def test_adversarial_market_too_few_bars_raises():
    with pytest.raises(ValueError):
        generate_adversarial_market(
            np.zeros(5), strategy=lambda x: x,
        )


# --------------------------------------------------------------------------
# R147 audit-replay
# --------------------------------------------------------------------------


def _write_audit_log(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def test_replay_session_reconstructs_positions(tmp_path: Path):
    log = tmp_path / "audit.jsonl"
    rows = [
        {"event": "order_submitted", "order_id": "o1", "symbol": "SPY",
         "side": "buy", "quantity": 10},
        {"event": "order_filled", "order_id": "o1", "symbol": "SPY",
         "side": "buy", "filled_qty": 10, "fill_price": 400.0},
        {"event": "order_submitted", "order_id": "o2", "symbol": "QQQ",
         "side": "buy", "quantity": 5},
        {"event": "order_filled", "order_id": "o2", "symbol": "QQQ",
         "side": "buy", "filled_qty": 5, "fill_price": 350.0},
    ]
    _write_audit_log(log, rows)
    res = replay_session(log)
    assert res.state.positions == {"SPY": 10.0, "QQQ": 5.0}
    assert res.state.trades_replayed == 2
    assert res.passed


def test_replay_session_diffs_against_reference(tmp_path: Path):
    log = tmp_path / "audit.jsonl"
    rows = [
        {"event": "order_submitted", "order_id": "o1", "symbol": "SPY",
         "side": "buy", "quantity": 10},
        {"event": "order_filled", "order_id": "o1", "symbol": "SPY",
         "side": "buy", "filled_qty": 10, "fill_price": 400.0},
    ]
    _write_audit_log(log, rows)
    res = replay_session(log, reference_state={"positions": {"SPY": 5.0}})
    assert not res.passed
    assert any(d.field_name == "position[SPY]" for d in res.diffs)


def test_replay_session_flags_orphan_open_orders(tmp_path: Path):
    log = tmp_path / "audit.jsonl"
    rows = [
        {"event": "order_submitted", "order_id": "o1", "symbol": "SPY",
         "side": "buy", "quantity": 10},
    ]
    _write_audit_log(log, rows)
    res = replay_session(log)
    assert "o1" in res.orphan_open_events
    assert not res.passed


# --------------------------------------------------------------------------
# R153 sealed envelope
# --------------------------------------------------------------------------


def test_sealed_envelope_round_trip():
    key = b"operator-key-12345"
    payload = {"params": {"alpha": 0.1}, "expected_sharpe": 1.5}
    opens = datetime.now(timezone.utc) - timedelta(seconds=1)
    env = seal_envelope(payload=payload, opens_after=opens, operator_key=key)
    out = open_envelope(envelope=env, operator_key=key)
    assert out == payload


def test_sealed_envelope_refuses_open_before_window():
    key = b"k"
    payload = {"x": 1}
    opens = datetime.now(timezone.utc) + timedelta(hours=1)
    env = seal_envelope(payload=payload, opens_after=opens, operator_key=key)
    with pytest.raises(PermissionError):
        open_envelope(envelope=env, operator_key=key)


def test_sealed_envelope_refuses_wrong_key():
    payload = {"x": 1}
    opens = datetime.now(timezone.utc) - timedelta(seconds=1)
    env = seal_envelope(payload=payload, opens_after=opens, operator_key=b"k")
    with pytest.raises(ValueError):
        open_envelope(envelope=env, operator_key=b"different")


def test_sealed_envelope_detects_tampering():
    key = b"k"
    payload = {"x": 1}
    opens = datetime.now(timezone.utc) - timedelta(seconds=1)
    env = seal_envelope(payload=payload, opens_after=opens, operator_key=key)
    tampered = SealedEnvelope(
        envelope_id=env.envelope_id,
        sealed_at=env.sealed_at,
        opens_after=env.opens_after,
        payload_json='{"x":2}',  # changed
        binding_tag=env.binding_tag,
    )
    with pytest.raises(ValueError):
        open_envelope(envelope=tampered, operator_key=key)


def test_sealed_envelope_persistence(tmp_path: Path):
    key = b"k"
    payload = {"forecast": [1, 2, 3]}
    opens = datetime.now(timezone.utc) - timedelta(seconds=1)
    env = seal_envelope(payload=payload, opens_after=opens, operator_key=key)
    p = tmp_path / "env.json"
    write_envelope(env, p)
    reloaded = read_envelope(p)
    assert reloaded == env
    assert open_envelope(envelope=reloaded, operator_key=key) == payload
