"""Tests for R125, R126, R127, R128, R129, R130, R135, R136, R137, R138, R139."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pytest

from aurora.analytics.cost_breakdown import CostBreakdown, decompose_cost
from aurora.analytics.decay_attribution import (
    AttributionInput,
    DecayAttribution,
    attribute_decay,
)
from aurora.core.borrow_model import (
    BorrowAvailability,
    BorrowConfig,
    apply_borrow_constraint,
)
from aurora.core.costs import CostModel, ZERO_costs
from aurora.core.slippage_calibration import (
    CalibrationResult,
    FillObservation,
    calibrate_slippage,
)
from aurora.core.spread_model import (
    ConstantSpreadModel,
    VolDrivenSpreadModel,
    realised_vol_zscore,
)
from aurora.deployment.live_modes import (
    DataQualityMonitor,
    DryRunMode,
    LiveAnomalyDetector,
    ShadowMode,
    pre_deploy_freshness_check,
)


# --------------------------------------------------------------------------
# R125 + R126 decay attribution
# --------------------------------------------------------------------------


def _make_attribution_inputs(seed_returns: float, seed_costs: float):
    rng = np.random.default_rng(0)
    rets = rng.normal(seed_returns, 0.01, size=252)
    weights = np.ones_like(rets) * 0.5
    costs = CostModel(spread_bps=seed_costs, slippage_bps=seed_costs)
    return AttributionInput(
        weights=weights,
        asset_returns=rets,
        cost_model=costs,
    )


def test_decay_attribution_returns_decomposition():
    base = _make_attribution_inputs(0.0008, 1.0)
    curr = _make_attribution_inputs(0.0001, 5.0)
    d = attribute_decay(base, curr)
    assert isinstance(d, DecayAttribution)
    # Sharpe gap should be approximately the sum of components.
    components = (
        d.alpha_component
        + d.cost_component
        + d.regime_component
        + d.residual_component
    )
    assert abs(d.sharpe_gap - components) < 1e-9


def test_decay_attribution_zero_gap_explained_fraction_one():
    base = _make_attribution_inputs(0.0005, 2.0)
    d = attribute_decay(base, base)
    assert d.sharpe_gap == 0
    assert d.explained_fraction == 1.0


def test_decay_attribution_cost_component_dominates_when_only_costs_change():
    base = _make_attribution_inputs(0.0005, 1.0)
    # Use the same return seed so alpha component is zero.
    higher_costs = AttributionInput(
        weights=base.weights,
        asset_returns=base.asset_returns,
        cost_model=CostModel(spread_bps=20.0, slippage_bps=20.0),
    )
    d = attribute_decay(base, higher_costs)
    assert d.cost_component < 0
    assert abs(d.alpha_component) < 1e-9


# --------------------------------------------------------------------------
# R127 cost breakdown
# --------------------------------------------------------------------------


def test_decompose_cost_returns_components_in_bps():
    weights = np.array([0.0, 0.5, 0.5, 0.0])
    costs = CostModel(
        spread_bps=2.0,
        commission_bps=1.0,
        slippage_bps=3.0,
        borrow_rate_annual=0.0,
    )
    b = decompose_cost(weights, costs=costs, n_periods=4)
    assert isinstance(b, CostBreakdown)
    assert b.spread_drag_bps > 0
    assert b.commission_drag_bps > 0
    assert b.slippage_drag_bps > 0
    assert b.borrow_drag_bps == 0.0
    assert b.total_drag_bps == pytest.approx(
        b.spread_drag_bps
        + b.commission_drag_bps
        + b.slippage_drag_bps
        + b.borrow_drag_bps
    )


def test_decompose_cost_borrow_drag_only_when_short():
    long_only = np.array([0.0, 0.5, 0.5, 0.0])
    long_short = np.array([0.0, -0.5, -0.5, 0.0])
    costs = CostModel(borrow_rate_annual=0.05)
    b_long = decompose_cost(long_only, costs=costs, n_periods=4)
    b_short = decompose_cost(long_short, costs=costs, n_periods=4)
    assert b_long.borrow_drag_bps == 0.0
    assert b_short.borrow_drag_bps > 0.0


def test_decompose_cost_zero_periods_raises():
    with pytest.raises(ValueError):
        decompose_cost(np.array([0.0, 0.5]), costs=ZERO_costs, n_periods=0)


def test_decompose_cost_as_dict_has_all_keys():
    b = decompose_cost(np.array([0.0, 0.5]), costs=ZERO_costs, n_periods=2)
    d = b.as_dict()
    assert set(d) == {
        "spread_bps",
        "commission_bps",
        "slippage_bps",
        "borrow_bps",
        "total_bps",
    }


# --------------------------------------------------------------------------
# R128 spread model
# --------------------------------------------------------------------------


def test_constant_spread_model_independent_of_state():
    m = ConstantSpreadModel(spread_bps=3.0)
    assert m.spread_for(vol_z=0.0) == 3.0
    assert m.spread_for(vol_z=5.0) == 3.0


def test_vol_driven_spread_model_widens_with_z():
    m = VolDrivenSpreadModel(base_bps=2.0, sensitivity=0.5)
    s_low = m.spread_for(vol_z=0.0)
    s_high = m.spread_for(vol_z=2.0)
    assert s_high > s_low


def test_vol_driven_spread_model_floors_below_zero():
    m = VolDrivenSpreadModel(base_bps=2.0, sensitivity=10.0, floor_multiplier=0.25)
    s = m.spread_for(vol_z=-100.0)
    # floor_multiplier=0.25 => spread = 2.0 * 0.25 = 0.5
    assert s == pytest.approx(2.0 * 0.25)


def test_realised_vol_zscore_zero_for_short_series():
    z = realised_vol_zscore(np.array([0.01, 0.0, -0.01]))
    assert z == 0.0


def test_realised_vol_zscore_positive_when_recent_window_is_louder():
    rng = np.random.default_rng(0)
    calm = rng.normal(0, 0.005, size=240)
    storm = rng.normal(0, 0.05, size=20)
    series = np.concatenate([calm, storm])
    z = realised_vol_zscore(series, window=20, long_window=252)
    assert z > 0


# --------------------------------------------------------------------------
# R129 borrow availability
# --------------------------------------------------------------------------


def test_borrow_availability_simulate_returns_boolean_array():
    av = BorrowAvailability(BorrowConfig())
    arr = av.simulate(50)
    assert arr.dtype == bool
    assert len(arr) == 50


def test_borrow_availability_some_unavailable_when_rate_low():
    av = BorrowAvailability(
        BorrowConfig(availability_rate=0.0, htb_duration_bars=5),
        seed=1,
    )
    arr = av.simulate(100)
    # All bars should fall into the HTB block since availability_rate=0.
    assert (~arr).sum() > 0


def test_apply_borrow_constraint_zeros_short_when_unavailable():
    weights = np.array([-0.5, -0.3, 0.4, -0.2])
    available = np.array([True, False, True, False])
    out = apply_borrow_constraint(weights, borrow_available=available)
    assert out[0] == -0.5  # short OK because available
    assert out[1] == 0.0   # short blocked
    assert out[2] == 0.4   # long never blocked
    assert out[3] == 0.0   # short blocked


def test_apply_borrow_constraint_length_mismatch_raises():
    with pytest.raises(ValueError):
        apply_borrow_constraint(
            np.array([-0.5, 0.5]), borrow_available=np.array([True])
        )


# --------------------------------------------------------------------------
# R130 slippage calibration
# --------------------------------------------------------------------------


def test_calibrate_slippage_recovers_intercept_and_slope():
    rng = np.random.default_rng(0)
    obs = []
    for _ in range(200):
        notional = float(rng.uniform(1e3, 5e5))
        adv = 1e7
        pct_adv = notional / adv * 100.0
        realised = 1.5 + 0.4 * pct_adv + rng.normal(0, 0.01)
        obs.append(FillObservation(
            expected_bps=1.0,
            realised_bps=realised,
            notional_dollars=notional,
            daily_volume_dollars=adv,
        ))
    r = calibrate_slippage(obs)
    assert isinstance(r, CalibrationResult)
    assert r.fitted_intercept_bps == pytest.approx(1.5, abs=0.05)
    assert r.fitted_size_coef_bps_per_pct_adv == pytest.approx(0.4, abs=0.05)
    assert r.advised_slippage_bps > 0


def test_calibrate_slippage_empty_raises():
    with pytest.raises(ValueError):
        calibrate_slippage([])


def test_calibrate_slippage_single_observation_returns_mean():
    o = FillObservation(
        expected_bps=1.0,
        realised_bps=2.5,
        notional_dollars=1e3,
        daily_volume_dollars=1e7,
    )
    r = calibrate_slippage([o])
    assert r.fitted_intercept_bps == 2.5
    assert r.advised_slippage_bps == 2.5


# --------------------------------------------------------------------------
# R135 shadow mode
# --------------------------------------------------------------------------


def test_shadow_mode_records_intended_orders():
    s = ShadowMode(strategy_id="alpha")
    s.record_intended_order(
        symbol="SPY", side="buy", quantity=10,
        timestamp=datetime(2026, 1, 1, 9, 30),
    )
    assert len(s.journal) == 1
    e = s.journal[0]
    assert e["symbol"] == "SPY"
    assert e["executed"] is False


def test_shadow_mode_diff_against_real_orders():
    s = ShadowMode(strategy_id="alpha")
    ts = datetime(2026, 1, 1, 9, 30)
    s.record_intended_order(symbol="SPY", side="buy", quantity=1, timestamp=ts)
    real = [{"symbol": "SPY", "side": "buy", "timestamp": ts.isoformat()}]
    diff = s.diff_against(real)
    assert diff["matched"] == 1
    assert diff["shadow_only"] == 0
    assert diff["live_only"] == 0


# --------------------------------------------------------------------------
# R136 dry-run mode
# --------------------------------------------------------------------------


def test_dry_run_mode_intercepts_calls():
    d = DryRunMode()
    d.record_call("place_order", symbol="SPY", quantity=10)
    assert len(d.journal) == 1
    assert d.journal[0]["intercepted"] is True
    assert d.assert_gate_fired("place_order")
    assert not d.assert_gate_fired("cancel_order")


# --------------------------------------------------------------------------
# R137 pre-deploy freshness
# --------------------------------------------------------------------------


def test_freshness_check_passes_for_recent_marker():
    today = date(2026, 5, 8)
    r = pre_deploy_freshness_check(date(2026, 5, 1), today=today)
    assert r.fresh
    assert r.age_days == 7


def test_freshness_check_fails_for_old_marker():
    today = date(2026, 5, 8)
    r = pre_deploy_freshness_check(date(2026, 4, 1), today=today, max_age_days=14)
    assert not r.fresh
    assert r.age_days == 37


def test_freshness_check_fails_when_marker_missing():
    r = pre_deploy_freshness_check(None)
    assert not r.fresh
    assert r.age_days is None


# --------------------------------------------------------------------------
# R138 data quality monitor
# --------------------------------------------------------------------------


def test_data_quality_monitor_flags_gap():
    dq = DataQualityMonitor(max_gap_seconds=60.0)
    t0 = datetime(2026, 1, 1, 9, 30, 0)
    assert dq.observe("SPY", t0, 100.0) is None
    t1 = t0 + timedelta(seconds=120)
    msg = dq.observe("SPY", t1, 100.5)
    assert msg is not None
    assert "gap" in msg


def test_data_quality_monitor_flags_repeated_price():
    dq = DataQualityMonitor(repeated_bar_threshold=3, max_gap_seconds=10000.0)
    t = datetime(2026, 1, 1, 9, 30, 0)
    out = []
    for i in range(5):
        out.append(dq.observe("SPY", t + timedelta(seconds=i), 100.0))
    # First bar -> no problem; subsequent identical prices accumulate.
    flagged = [o for o in out if o is not None]
    assert any("repeated price" in m for m in flagged)


def test_data_quality_monitor_resets_repeat_count_on_change():
    dq = DataQualityMonitor(repeated_bar_threshold=3, max_gap_seconds=10000.0)
    t = datetime(2026, 1, 1, 9, 30, 0)
    dq.observe("SPY", t, 100.0)
    dq.observe("SPY", t + timedelta(seconds=1), 100.0)
    dq.observe("SPY", t + timedelta(seconds=2), 101.0)  # reset
    assert dq.repeat_count["SPY"] == 0


# --------------------------------------------------------------------------
# R139 live anomaly detector
# --------------------------------------------------------------------------


def test_live_anomaly_detector_no_alert_inside_bands():
    d = LiveAnomalyDetector(
        expected_sharpe_low=0.5,
        expected_sharpe_high=2.0,
        expected_win_rate_low=0.45,
        expected_win_rate_high=0.65,
    )
    assert d.evaluate(realised_sharpe=1.0, realised_win_rate=0.55) is None


def test_live_anomaly_detector_alerts_on_sharpe_below_band():
    d = LiveAnomalyDetector(
        expected_sharpe_low=0.5,
        expected_sharpe_high=2.0,
        expected_win_rate_low=0.45,
        expected_win_rate_high=0.65,
    )
    msg = d.evaluate(realised_sharpe=0.1, realised_win_rate=0.55)
    assert msg is not None
    assert "sharpe" in msg


def test_live_anomaly_detector_alerts_on_win_rate_above_band():
    d = LiveAnomalyDetector(
        expected_sharpe_low=0.5,
        expected_sharpe_high=2.0,
        expected_win_rate_low=0.45,
        expected_win_rate_high=0.65,
    )
    msg = d.evaluate(realised_sharpe=1.0, realised_win_rate=0.95)
    assert msg is not None
    assert "win-rate" in msg
