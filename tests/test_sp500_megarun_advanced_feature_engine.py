from __future__ import annotations

import importlib
import warnings

import numpy as np
import pandas as pd
import pytest


def _engine_api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.advanced_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"advanced feature engine is missing: {exc}")


def _spy_inputs(periods: int = 620) -> pd.DataFrame:
    dates = pd.bdate_range("2007-01-03", periods=periods)
    phase = np.arange(periods, dtype=float)
    returns = (
        0.00035
        + 0.0035 * np.sin(2.0 * np.pi * phase / 20.0)
        + 0.0015 * np.cos(2.0 * np.pi * phase / 63.0)
        + np.where((phase // 90).astype(int) % 2 == 0, 0.0008, -0.0008)
    )
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]] * (1.0 + 0.0005 * np.sin(phase / 7.0))
    intraday_range = 0.004 + 0.002 * (1.0 + np.sin(phase / 11.0))
    return pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "open": open_,
            "high": np.maximum(open_, close) * (1.0 + intraday_range),
            "low": np.minimum(open_, close) * (1.0 - intraday_range),
            "close": close,
            "volume": 1_000_000.0 + 10_000.0 * np.sin(phase / 9.0),
        }
    )


def _parameters(lane_id: str) -> dict[str, object]:
    if lane_id == "F061":
        return {"kind": "kama", "window": 20, "threshold": 0.25}
    if lane_id == "F062":
        return {"kind": "local_trend", "window": 80, "noise_ratio": 0.01}
    if lane_id == "F063":
        return {"kind": "haar", "scales": 3, "window": 63, "statistic": "sign"}
    if lane_id == "F064":
        return {
            "period": 20,
            "window": 80,
            "detrend": "mean",
            "phase_stability": 0.25,
        }
    if lane_id == "F065":
        return {
            "statistic": "lempel_ziv",
            "window": 80,
            "lag": 1,
            "direction": "continuation",
        }
    if lane_id == "F066":
        return {"order": 3, "window": 80, "smoothing": 0.5}
    if lane_id == "F067":
        return {"order": 2, "window": 80, "bins": 5, "smoothing": 0.5}
    if lane_id == "F068":
        return {"p": 2, "q": 1, "window": 126, "refit": "monthly"}
    if lane_id == "F069":
        return {
            "kind": "garch",
            "p": 1,
            "q": 1,
            "distribution": "normal",
            "student_df": 8,
            "window": 126,
            "refit": "quarterly",
        }
    if lane_id == "F070":
        return {
            "estimator": "rogers_satchell",
            "horizons": "1_5_22",
            "window": 126,
            "refit": "quarterly",
            "transform": "log",
        }
    raise AssertionError(lane_id)


@pytest.mark.parametrize("lane_id", [f"F{index:03d}" for index in range(61, 71)])
def test_f061_f070_produce_finite_train_only_values(lane_id: str) -> None:
    api = _engine_api()
    spy = _spy_inputs()

    result = api.evaluate_advanced_lane(lane_id, spy, _parameters(lane_id))

    assert result["value"].notna().any(), lane_id
    valid = result["value"].notna()
    assert result.loc[valid, "observed_at"].le(
        result.loc[valid, "available_at"]
    ).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane_id", [f"F{index:03d}" for index in range(61, 71)])
def test_f061_f070_are_stable_when_future_rows_are_appended(lane_id: str) -> None:
    api = _engine_api()
    spy = _spy_inputs()
    cutoff = spy.loc[419, "date"]
    before_spy = spy.loc[spy["date"].le(cutoff)].copy()

    before = api.evaluate_advanced_lane(lane_id, before_spy, _parameters(lane_id))
    after = api.evaluate_advanced_lane(lane_id, spy, _parameters(lane_id))
    after = after.loc[after["date"].le(cutoff)]

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True), after.reset_index(drop=True)
    )


@pytest.mark.parametrize("kind", ["kama", "vidya", "frama"])
def test_f061_supports_each_frozen_adaptive_average(kind: str) -> None:
    api = _engine_api()

    result = api.evaluate_advanced_lane(
        "F061",
        _spy_inputs(180),
        {"kind": kind, "window": 20, "threshold": 0.0},
    )

    assert result["value"].notna().any()


@pytest.mark.parametrize("kind", ["local_level", "local_trend", "kalman_slope"])
def test_f062_supports_each_frozen_causal_state_model(kind: str) -> None:
    api = _engine_api()

    result = api.evaluate_advanced_lane(
        "F062",
        _spy_inputs(180),
        {"kind": kind, "window": 40, "noise_ratio": 0.1},
    )

    assert result["value"].notna().any()


@pytest.mark.parametrize("kind", ["haar", "db2", "db4", "causal_modwt"])
@pytest.mark.parametrize("statistic", ["energy", "sign", "slope", "reconstruction"])
def test_f063_supports_each_frozen_wavelet_kernel(kind: str, statistic: str) -> None:
    api = _engine_api()

    result = api.evaluate_advanced_lane(
        "F063",
        _spy_inputs(180),
        {"kind": kind, "scales": 2, "window": 40, "statistic": statistic},
    )

    assert result["value"].notna().any()


def test_f064_goertzel_forecast_recovers_a_stable_causal_cycle() -> None:
    api = _engine_api()
    spy = _spy_inputs(180)

    result = api.evaluate_advanced_lane(
        "F064",
        spy,
        {
            "period": 20,
            "window": 80,
            "detrend": "mean",
            "phase_stability": 0.75,
        },
    )

    assert result["value"].iloc[-1] != pytest.approx(0.0)


def test_f064_supports_one_sided_linear_detrending() -> None:
    api = _engine_api()

    result = api.evaluate_advanced_lane(
        "F064",
        _spy_inputs(180),
        {
            "period": 20,
            "window": 80,
            "detrend": "linear",
            "phase_stability": 0.25,
        },
    )

    assert result["value"].notna().any()


@pytest.mark.parametrize("statistic", ["binary_entropy", "lempel_ziv"])
def test_f065_supports_entropy_and_lz_complexity(statistic: str) -> None:
    api = _engine_api()

    result = api.evaluate_advanced_lane(
        "F065",
        _spy_inputs(180),
        {
            "statistic": statistic,
            "window": 63,
            "lag": 2,
            "direction": "reversal",
        },
    )

    finite = result["value"].dropna()
    assert not finite.empty
    assert finite.abs().le(1.0 + 1e-12).all()


def test_f066_sign_words_forecast_the_next_sign_from_known_transitions() -> None:
    api = _engine_api()
    returns = np.array([0.01, -0.01] * 30 + [0.01], dtype=float)
    close = 100.0 * np.cumprod(1.0 + returns)
    spy = _spy_inputs(len(close))
    spy.loc[:, "close"] = close
    spy.loc[:, "open"] = np.r_[close[0], close[:-1]]
    spy.loc[:, "high"] = spy[["open", "close"]].max(axis=1) * 1.001
    spy.loc[:, "low"] = spy[["open", "close"]].min(axis=1) * 0.999

    result = api.evaluate_advanced_lane(
        "F066",
        spy,
        {"order": 2, "window": 40, "smoothing": 0.5},
    )

    assert result["value"].iloc[-1] < -0.8


def test_f067_quantile_words_emit_a_bounded_expected_rank() -> None:
    api = _engine_api()

    result = api.evaluate_advanced_lane(
        "F067",
        _spy_inputs(180),
        {"order": 2, "window": 63, "bins": 3, "smoothing": 0.5},
    )

    finite = result["value"].dropna()
    assert not finite.empty
    assert finite.between(-1.0, 1.0).all()


@pytest.mark.parametrize("q", [0, 1, 2])
def test_f068_supports_ar_and_conditional_arma_forecasts(q: int) -> None:
    api = _engine_api()

    result = api.evaluate_advanced_lane(
        "F068",
        _spy_inputs(260),
        {"p": 2, "q": q, "window": 80, "refit": "monthly"},
    )

    assert result["value"].notna().any()


def test_f068_remains_finite_after_a_large_known_return_shock() -> None:
    api = _engine_api()
    spy = _spy_inputs(620)
    returns = 0.0003 + 0.002 * np.sin(np.arange(len(spy), dtype=float) / 13.0)
    returns[200] = -0.5
    returns[400] = 0.25
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    spy.loc[:, "open"] = open_
    spy.loc[:, "high"] = np.maximum(open_, close) * 1.001
    spy.loc[:, "low"] = np.minimum(open_, close) * 0.999
    spy.loc[:, "close"] = close

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = api.evaluate_advanced_lane(
            "F068",
            spy,
            {"p": 2, "q": 1, "window": 504, "refit": "monthly"},
        )

    finite = result["value"].dropna()
    assert not finite.empty
    assert np.isfinite(finite).all()


@pytest.mark.parametrize("kind", ["garch", "gjr", "egarch"])
@pytest.mark.parametrize("distribution", ["normal", "student_t"])
def test_f069_supports_each_likelihood_and_variance_recursion(
    kind: str,
    distribution: str,
) -> None:
    api = _engine_api()

    result = api.evaluate_advanced_lane(
        "F069",
        _spy_inputs(220),
        {
            "kind": kind,
            "p": 1,
            "q": 1,
            "distribution": distribution,
            "student_df": 8,
            "window": 80,
            "refit": "quarterly",
        },
    )

    assert result["value"].notna().any()


def test_f069_supports_second_order_shock_and_variance_terms() -> None:
    api = _engine_api()

    result = api.evaluate_advanced_lane(
        "F069",
        _spy_inputs(220),
        {
            "kind": "garch",
            "p": 2,
            "q": 2,
            "distribution": "normal",
            "student_df": 8,
            "window": 80,
            "refit": "quarterly",
        },
    )

    assert result["value"].notna().any()


@pytest.mark.parametrize(
    "estimator",
    ["close", "parkinson", "garman_klass", "rogers_satchell"],
)
def test_f070_supports_each_daily_variance_estimator(estimator: str) -> None:
    api = _engine_api()

    result = api.evaluate_advanced_lane(
        "F070",
        _spy_inputs(260),
        {
            "estimator": estimator,
            "horizons": "1_5_22_63",
            "window": 80,
            "refit": "quarterly",
            "transform": "log",
        },
    )

    assert result["value"].notna().any()


def test_f070_supports_level_har_forecasts() -> None:
    api = _engine_api()

    result = api.evaluate_advanced_lane(
        "F070",
        _spy_inputs(260),
        {
            "estimator": "close",
            "horizons": "1_5_22",
            "window": 80,
            "refit": "quarterly",
            "transform": "level",
        },
    )

    assert result["value"].notna().any()


@pytest.mark.parametrize("lane_id", ["F062", "F068", "F069", "F070"])
def test_rolling_estimators_wait_for_a_complete_declared_window(lane_id: str) -> None:
    api = _engine_api()
    parameters = _parameters(lane_id)
    parameters["window"] = 80

    result = api.evaluate_advanced_lane(lane_id, _spy_inputs(120), parameters)

    assert result["value"].iloc[:80].isna().all()


def test_advanced_engine_rejects_validation_rows_and_future_availability() -> None:
    api = _engine_api()
    validation = _spy_inputs(80)
    validation.loc[79, "date"] = pd.Timestamp("2011-01-03")
    validation.loc[79, "available_at"] = pd.Timestamp("2011-01-03")

    with pytest.raises(api.AdvancedFeatureEngineError, match="NON_TRAIN_SPY_ROW"):
        api.evaluate_advanced_lane("F061", validation, _parameters("F061"))

    future = _spy_inputs(80)
    future.loc[20, "available_at"] = future.loc[21, "date"]

    with pytest.raises(
        api.AdvancedFeatureEngineError,
        match="SPY_NOT_AVAILABLE_AT_DECISION",
    ):
        api.evaluate_advanced_lane("F061", future, _parameters("F061"))
