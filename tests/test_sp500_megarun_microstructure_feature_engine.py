from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest


def _engine_api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.microstructure_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"microstructure feature engine is missing: {exc}")


def _spy_inputs(periods: int = 620) -> pd.DataFrame:
    dates = pd.bdate_range("2007-01-03", periods=periods)
    phase = np.arange(periods, dtype=float)
    returns = (
        0.0004
        + 0.004 * np.sin(phase / 8.0)
        + 0.0015 * np.cos(phase / 23.0)
    )
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]] * (1.0 + 0.0007 * np.sin(phase / 5.0))
    half_range = 0.003 + 0.002 * (1.0 + np.sin(phase / 13.0))
    volume = 1_000_000.0 * np.exp(0.15 * np.sin(phase / 17.0) + 0.04 * returns)
    return pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "open": open_,
            "high": np.maximum(open_, close) * (1.0 + half_range),
            "low": np.minimum(open_, close) * (1.0 - half_range),
            "close": close,
            "volume": volume,
        }
    )


def _parameters(lane_id: str) -> dict[str, object]:
    if lane_id == "F071":
        return {"statistic": "jump_proxy", "window": 63}
    if lane_id == "F072":
        return {"statistic": "dispersion", "window": 63}
    if lane_id == "F073":
        return {
            "pattern": "direction_run",
            "length": 3,
            "tolerance": 0.1,
            "direction": "continuation",
        }
    if lane_id == "F074":
        return {
            "statistic": "nearest_balance",
            "window": 126,
            "pivot_span": 3,
            "tolerance": 0.01,
        }
    if lane_id == "F075":
        return {"statistic": "acceleration", "window": 63, "degree": 2}
    if lane_id == "F076":
        return {
            "direction": "volume_leads_return",
            "statistic": "predictive_score",
            "window": 126,
            "lag": 2,
        }
    if lane_id == "F077":
        return {"statistic": "imbalance", "window": 63}
    if lane_id == "F078":
        return {"estimator": "corwin_schultz", "window": 63}
    if lane_id == "F079":
        return {
            "statistic": "volume_drought",
            "window": 63,
            "zero_tolerance_bps": 1.0,
        }
    if lane_id == "F080":
        return {
            "base": "trend",
            "base_window": 20,
            "liquidity": "volume_drought",
            "liquidity_window": 63,
            "stress_quantile": 0.75,
            "confirmation": 2,
            "logic": "gate",
        }
    raise AssertionError(lane_id)


@pytest.mark.parametrize("lane_id", [f"F{index:03d}" for index in range(71, 81)])
def test_f071_f080_produce_finite_train_only_values(lane_id: str) -> None:
    api = _engine_api()

    result = api.evaluate_microstructure_lane(
        lane_id, _spy_inputs(), _parameters(lane_id)
    )

    assert result["value"].notna().any(), lane_id
    valid = result["value"].notna()
    assert result.loc[valid, "observed_at"].le(
        result.loc[valid, "available_at"]
    ).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane_id", [f"F{index:03d}" for index in range(71, 81)])
def test_f071_f080_are_stable_when_future_rows_are_appended(lane_id: str) -> None:
    api = _engine_api()
    spy = _spy_inputs()
    cutoff = spy.loc[419, "date"]

    before = api.evaluate_microstructure_lane(
        lane_id, spy.loc[spy["date"].le(cutoff)].copy(), _parameters(lane_id)
    )
    after = api.evaluate_microstructure_lane(lane_id, spy, _parameters(lane_id))

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True),
        after.loc[after["date"].le(cutoff)].reset_index(drop=True),
    )


@pytest.mark.parametrize(
    "statistic", ["semivariance_imbalance", "bipower_share", "jump_proxy"]
)
def test_f071_supports_each_frozen_daily_variance_proxy(statistic: str) -> None:
    api = _engine_api()

    result = api.evaluate_microstructure_lane(
        "F071", _spy_inputs(180), {"statistic": statistic, "window": 40}
    )

    assert result["value"].notna().any()


def test_f071_semivariance_imbalance_has_the_known_return_direction() -> None:
    api = _engine_api()
    spy = _spy_inputs(100)
    close = 100.0 * np.exp(np.cumsum(np.full(len(spy), 0.002)))
    open_ = np.r_[close[0], close[:-1]]
    spy.loc[:, "open"] = open_
    spy.loc[:, "high"] = np.maximum(open_, close) * 1.002
    spy.loc[:, "low"] = np.minimum(open_, close) * 0.998
    spy.loc[:, "close"] = close

    result = api.evaluate_microstructure_lane(
        "F071",
        spy,
        {"statistic": "semivariance_imbalance", "window": 20},
    )

    assert result["value"].dropna().iloc[-1] > 0.99


def test_f071_waits_for_the_frozen_number_of_known_returns() -> None:
    api = _engine_api()

    result = api.evaluate_microstructure_lane(
        "F071",
        _spy_inputs(60),
        {"statistic": "semivariance_imbalance", "window": 20},
    )

    assert result["value"].first_valid_index() == 20


@pytest.mark.parametrize(
    "statistic", ["dispersion", "max_min_ratio", "close_vs_range"]
)
def test_f072_supports_each_frozen_estimator_disagreement(statistic: str) -> None:
    api = _engine_api()

    result = api.evaluate_microstructure_lane(
        "F072", _spy_inputs(180), {"statistic": statistic, "window": 40}
    )

    finite = result["value"].dropna()
    assert not finite.empty
    assert np.isfinite(finite).all()


@pytest.mark.parametrize(
    "pattern", ["direction_run", "engulfing", "wick_reversal", "range_breakout"]
)
def test_f073_supports_each_frozen_bar_sequence(pattern: str) -> None:
    api = _engine_api()

    result = api.evaluate_microstructure_lane(
        "F073",
        _spy_inputs(180),
        {
            "pattern": pattern,
            "length": 3,
            "tolerance": 0.1,
            "direction": "continuation",
        },
    )

    assert result["value"].notna().any()


def test_f073_reversal_orientation_is_the_negative_of_continuation() -> None:
    api = _engine_api()
    parameters = {
        "pattern": "wick_reversal",
        "length": 3,
        "tolerance": 0.1,
        "direction": "continuation",
    }

    continuation = api.evaluate_microstructure_lane(
        "F073", _spy_inputs(100), parameters
    )["value"]
    reversal = api.evaluate_microstructure_lane(
        "F073", _spy_inputs(100), {**parameters, "direction": "reversal"}
    )["value"]

    np.testing.assert_allclose(
        continuation.dropna().to_numpy(),
        -reversal.dropna().to_numpy(),
    )


def test_f073_wick_sequence_waits_for_its_full_length() -> None:
    api = _engine_api()

    result = api.evaluate_microstructure_lane(
        "F073",
        _spy_inputs(20),
        {
            "pattern": "wick_reversal",
            "length": 5,
            "tolerance": 0.1,
            "direction": "continuation",
        },
    )

    assert result["value"].first_valid_index() == 4


@pytest.mark.parametrize(
    "statistic", ["nearest_balance", "touch_imbalance", "breakout_pressure"]
)
def test_f074_supports_each_frozen_support_resistance_state(statistic: str) -> None:
    api = _engine_api()

    result = api.evaluate_microstructure_lane(
        "F074",
        _spy_inputs(220),
        {
            "statistic": statistic,
            "window": 80,
            "pivot_span": 3,
            "tolerance": 0.01,
        },
    )

    assert result["value"].notna().any()


@pytest.mark.parametrize(
    "statistic", ["slope", "acceleration", "convexity", "exhaustion"]
)
def test_f075_supports_each_frozen_polynomial_state(statistic: str) -> None:
    api = _engine_api()

    result = api.evaluate_microstructure_lane(
        "F075",
        _spy_inputs(180),
        {"statistic": statistic, "window": 40, "degree": 3},
    )

    assert result["value"].notna().any()


def test_f075_detects_positive_known_quadratic_acceleration() -> None:
    api = _engine_api()
    spy = _spy_inputs(100)
    time = np.arange(len(spy), dtype=float)
    close = 100.0 * np.exp(0.000002 * time**2)
    open_ = np.r_[close[0], close[:-1]]
    spy.loc[:, "open"] = open_
    spy.loc[:, "high"] = np.maximum(open_, close) * 1.001
    spy.loc[:, "low"] = np.minimum(open_, close) * 0.999
    spy.loc[:, "close"] = close

    result = api.evaluate_microstructure_lane(
        "F075",
        spy,
        {"statistic": "acceleration", "window": 40, "degree": 2},
    )

    assert result["value"].dropna().iloc[-1] > 0.0


@pytest.mark.parametrize("direction", ["volume_leads_return", "return_leads_volume"])
@pytest.mark.parametrize("statistic", ["correlation", "predictive_score"])
def test_f076_supports_each_frozen_lead_lag_relation(
    direction: str, statistic: str
) -> None:
    api = _engine_api()

    result = api.evaluate_microstructure_lane(
        "F076",
        _spy_inputs(220),
        {"direction": direction, "statistic": statistic, "window": 80, "lag": 2},
    )

    assert result["value"].notna().any()


@pytest.mark.parametrize("statistic", ["imbalance", "obv_slope", "pressure"])
def test_f077_supports_each_explicit_bar_volume_proxy(statistic: str) -> None:
    api = _engine_api()

    result = api.evaluate_microstructure_lane(
        "F077", _spy_inputs(180), {"statistic": statistic, "window": 40}
    )

    finite = result["value"].dropna()
    assert not finite.empty
    assert np.isfinite(finite).all()


def test_f077_imbalance_is_positive_when_every_known_return_is_positive() -> None:
    api = _engine_api()
    spy = _spy_inputs(80)
    close = 100.0 * np.exp(np.cumsum(np.full(len(spy), 0.001)))
    open_ = np.r_[close[0], close[:-1]]
    spy.loc[:, "open"] = open_
    spy.loc[:, "high"] = np.maximum(open_, close) * 1.001
    spy.loc[:, "low"] = np.minimum(open_, close) * 0.999
    spy.loc[:, "close"] = close

    result = api.evaluate_microstructure_lane(
        "F077", spy, {"statistic": "imbalance", "window": 20}
    )

    assert result["value"].dropna().iloc[-1] > 0.99


@pytest.mark.parametrize("estimator", ["roll", "corwin_schultz", "amihud"])
def test_f078_supports_each_frozen_daily_liquidity_estimator(estimator: str) -> None:
    api = _engine_api()

    result = api.evaluate_microstructure_lane(
        "F078", _spy_inputs(180), {"estimator": estimator, "window": 40}
    )

    finite = result["value"].dropna()
    assert not finite.empty
    assert finite.ge(0.0).all()


def test_f078_roll_detects_negative_price_change_covariance() -> None:
    api = _engine_api()
    spy = _spy_inputs(100)
    changes = np.resize(np.array([0.2, -0.2]), len(spy))
    close = 100.0 + np.cumsum(changes)
    open_ = np.r_[close[0], close[:-1]]
    spy.loc[:, "open"] = open_
    spy.loc[:, "high"] = np.maximum(open_, close) + 0.05
    spy.loc[:, "low"] = np.minimum(open_, close) - 0.05
    spy.loc[:, "close"] = close

    result = api.evaluate_microstructure_lane(
        "F078", spy, {"estimator": "roll", "window": 20}
    )

    assert result["value"].dropna().iloc[-1] > 0.0


@pytest.mark.parametrize(
    "statistic", ["zero_return_rate", "volume_drought", "volume_shock"]
)
def test_f079_supports_each_observable_daily_liquidity_state(statistic: str) -> None:
    api = _engine_api()

    result = api.evaluate_microstructure_lane(
        "F079",
        _spy_inputs(180),
        {"statistic": statistic, "window": 40, "zero_tolerance_bps": 1.0},
    )

    assert result["value"].notna().any()


def test_f079_zero_return_rate_is_one_for_a_flat_known_path() -> None:
    api = _engine_api()
    spy = _spy_inputs(80)
    spy.loc[:, "open"] = 100.0
    spy.loc[:, "high"] = 100.1
    spy.loc[:, "low"] = 99.9
    spy.loc[:, "close"] = 100.0

    result = api.evaluate_microstructure_lane(
        "F079",
        spy,
        {"statistic": "zero_return_rate", "window": 20, "zero_tolerance_bps": 0.0},
    )

    assert result["value"].dropna().iloc[-1] == pytest.approx(1.0)


def test_f079_zero_return_rate_waits_for_known_returns_not_price_rows() -> None:
    api = _engine_api()

    result = api.evaluate_microstructure_lane(
        "F079",
        _spy_inputs(60),
        {"statistic": "zero_return_rate", "window": 20, "zero_tolerance_bps": 0.5},
    )

    assert result["value"].first_valid_index() == 20


@pytest.mark.parametrize("base", ["trend", "reversal"])
@pytest.mark.parametrize("liquidity", ["roll", "corwin_schultz", "volume_drought"])
@pytest.mark.parametrize("logic", ["gate", "attenuate"])
def test_f080_supports_each_frozen_price_liquidity_gate(
    base: str, liquidity: str, logic: str
) -> None:
    api = _engine_api()

    result = api.evaluate_microstructure_lane(
        "F080",
        _spy_inputs(260),
        {
            "base": base,
            "base_window": 20,
            "liquidity": liquidity,
            "liquidity_window": 63,
            "stress_quantile": 0.75,
            "confirmation": 2,
            "logic": logic,
        },
    )

    finite = result["value"].dropna()
    assert not finite.empty
    assert finite.abs().le(1.0 + 1e-12).all()


def test_f080_constant_low_stress_is_not_misclassified_as_maximum_stress() -> None:
    api = _engine_api()
    spy = _spy_inputs(180)
    close = 100.0 + 0.1 * np.arange(len(spy), dtype=float)
    open_ = np.r_[close[0], close[:-1]]
    spy.loc[:, "open"] = open_
    spy.loc[:, "high"] = np.maximum(open_, close) + 0.05
    spy.loc[:, "low"] = np.minimum(open_, close) - 0.05
    spy.loc[:, "close"] = close
    result = api.evaluate_microstructure_lane(
        "F080",
        spy,
        {
            "base": "trend",
            "base_window": 20,
            "liquidity": "roll",
            "liquidity_window": 40,
            "stress_quantile": 0.75,
            "confirmation": 2,
            "logic": "gate",
        },
    )

    finite = result["value"].dropna()
    assert not finite.empty
    assert finite.abs().gt(0.0).any()


def test_f080_causal_stress_percentile_uses_midrank_for_ties() -> None:
    api = _engine_api()

    percentile = api._causal_percentile(pd.Series(np.zeros(10)), 5)

    assert percentile.dropna().eq(0.5).all()


def test_microstructure_batch_contains_exactly_f071_f080() -> None:
    api = _engine_api()

    outputs = api.evaluate_microstructure_family_batch(_spy_inputs())

    assert tuple(outputs) == tuple(f"F{index:03d}" for index in range(71, 81))
    assert all(output["value"].notna().any() for output in outputs.values())


def test_microstructure_engine_rejects_validation_rows() -> None:
    api = _engine_api()
    spy = _spy_inputs(40)
    spy.loc[spy.index[-1], ["date", "available_at"]] = pd.Timestamp("2011-01-03")

    with pytest.raises(api.MicrostructureFeatureEngineError, match="NON_TRAIN_SPY_ROW"):
        api.evaluate_microstructure_lane("F071", spy, {"window": 20})
