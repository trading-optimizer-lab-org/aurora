from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest


def _api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.technical_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"technical feature engine is missing: {exc}")


def _spy(periods: int = 1_700) -> pd.DataFrame:
    dates = pd.bdate_range("2003-01-02", periods=periods)
    phase = np.arange(periods, dtype=float)
    close_return = 0.00025 + 0.005 * np.sin(phase / 17.0) + 0.002 * np.cos(
        phase / 43.0
    )
    close = 100.0 * np.exp(np.cumsum(close_return))
    prior_close = np.r_[close[0], close[:-1]]
    open_ = prior_close * np.exp(0.0015 * np.sin(phase / 11.0))
    high = np.maximum(open_, close) * (1.0 + 0.004 + 0.002 * np.sin(phase / 7.0) ** 2)
    low = np.minimum(open_, close) * (1.0 - 0.004 - 0.002 * np.cos(phase / 9.0) ** 2)
    volume = 1_000_000.0 * (
        1.1 + 0.25 * np.sin(phase / 13.0) + 0.1 * np.cos(phase / 37.0)
    )
    return pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def _parameters(lane: str) -> dict[str, object]:
    return {
        "F121": {
            "statistic": "range_position",
            "window": 252,
            "buffer_fraction": 0.0,
            "confirmation": 2,
        },
        "F122": {"statistic": "directional_strength", "window": 14},
        "F123": {
            "statistic": "ppo",
            "fast": 12,
            "slow": 26,
            "signal": 9,
        },
        "F124": {
            "statistic": "cloud_position",
            "conversion_window": 9,
            "base_window": 26,
            "span_b_window": 52,
            "atr_window": 14,
        },
        "F125": {
            "statistic": "consensus",
            "window": 22,
            "atr_window": 14,
            "atr_multiplier": 3.0,
            "acceleration_step": 0.02,
            "acceleration_max": 0.2,
        },
        "F126": {"statistic": "fibonacci_position", "window": 20},
        "F127": {
            "statistic": "consensus",
            "window": 14,
            "box_atr": 1.0,
            "reversal_boxes": 3,
        },
        "F128": {
            "statistic": "triangle",
            "window": 63,
            "tolerance": 0.03,
            "head_margin": 0.05,
            "breakout_buffer": 0.0,
        },
        "F129": {"statistic": "continuation", "window": 20},
        "F130": {
            "statistic": "consensus",
            "window": 20,
            "klinger_fast": 34,
            "klinger_slow": 55,
            "klinger_signal": 13,
        },
    }[lane].copy()


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(121, 131)])
def test_f121_f130_produce_finite_train_only_values(lane: str) -> None:
    result = _api().evaluate_technical_lane(lane, _spy(), _parameters(lane))

    valid = result["value"].notna()
    assert valid.any(), lane
    assert result.loc[valid, "observed_at"].le(result.loc[valid, "available_at"]).all()
    assert result.loc[valid, "available_at"].eq(result.loc[valid, "date"]).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(121, 131)])
def test_f121_f130_do_not_change_when_future_rows_are_appended(lane: str) -> None:
    api = _api()
    spy = _spy()
    cutoff = pd.Timestamp("2007-12-31")
    before = api.evaluate_technical_lane(
        lane,
        spy.loc[spy["date"].le(cutoff)].copy(),
        _parameters(lane),
    )
    after = api.evaluate_technical_lane(lane, spy, _parameters(lane))

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True),
        after.loc[after["date"].le(cutoff)].reset_index(drop=True),
    )


@pytest.mark.parametrize(
    ("lane", "statistics"),
    [
        ("F121", ["high_distance", "low_distance", "range_position", "confirmed_breakout"]),
        ("F122", ["adx", "dmi_spread", "aroon_oscillator", "directional_strength"]),
        ("F123", ["macd", "ppo", "trix", "tsi"]),
        ("F124", ["conversion_base_spread", "cloud_position", "cloud_width", "cloud_breakout"]),
        ("F125", ["parabolic_sar", "supertrend", "chandelier", "consensus"]),
        ("F126", ["pivot_distance", "support_resistance_position", "fibonacci_position", "nearest_level_distance"]),
        ("F127", ["heikin_ashi", "renko", "point_figure", "consensus"]),
        ("F128", ["triangle", "wedge", "double_extreme", "shoulders"]),
        ("F129", ["overnight_momentum", "intraday_momentum", "continuation", "gap_fill"]),
        ("F130", ["chaikin_money_flow", "money_flow_index", "force_index", "ease_of_movement", "klinger_oscillator", "consensus"]),
    ],
)
def test_f121_f130_support_every_frozen_statistic(
    lane: str, statistics: list[str]
) -> None:
    api = _api()
    spy = _spy()
    for statistic in statistics:
        parameters = _parameters(lane)
        parameters["statistic"] = statistic
        result = api.evaluate_technical_lane(lane, spy, parameters)
        assert result["value"].notna().any(), (lane, statistic)


def test_f121_uses_the_completed_prior_range_not_the_current_record() -> None:
    api = _api()
    dates = pd.bdate_range("2010-01-04", periods=4)
    spy = pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "open": [8.0, 9.0, 10.0, 18.0],
            "high": [10.0, 11.0, 12.0, 20.0],
            "low": [5.0, 6.0, 7.0, 8.0],
            "close": [9.0, 10.0, 11.0, 18.0],
            "volume": [100.0] * 4,
        }
    )

    result = api.evaluate_technical_lane(
        "F121", spy, {"statistic": "high_distance", "window": 3}
    )

    assert result["value"].iloc[-1] == pytest.approx(0.5)


def test_f126_reference_levels_ignore_the_current_high_and_low() -> None:
    api = _api()
    spy = _spy(40)
    parameters = {"statistic": "pivot_distance", "window": 20}
    original = api.evaluate_technical_lane("F126", spy, parameters)
    changed = spy.copy()
    changed.loc[changed.index[-1], "high"] *= 5.0
    changed.loc[changed.index[-1], "low"] *= 0.2

    mutated = api.evaluate_technical_lane("F126", changed, parameters)

    assert mutated["value"].iloc[-1] == pytest.approx(original["value"].iloc[-1])


def test_f129_uses_log_overnight_and_intraday_returns() -> None:
    api = _api()
    dates = pd.bdate_range("2010-01-04", periods=2)
    spy = pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "open": [100.0, 110.0],
            "high": [101.0, 112.0],
            "low": [99.0, 107.0],
            "close": [100.0, 108.0],
            "volume": [100.0, 100.0],
        }
    )

    overnight = api.evaluate_technical_lane(
        "F129", spy, {"statistic": "overnight_momentum", "window": 1}
    )
    intraday = api.evaluate_technical_lane(
        "F129", spy, {"statistic": "intraday_momentum", "window": 1}
    )

    assert overnight["value"].iloc[-1] == pytest.approx(np.log(1.1))
    assert intraday["value"].iloc[-1] == pytest.approx(np.log(108.0 / 110.0))


def test_f130_chaikin_money_flow_uses_range_location_and_volume() -> None:
    api = _api()
    dates = pd.bdate_range("2010-01-04", periods=2)
    spy = pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "open": [6.0, 6.0],
            "high": [11.0, 13.0],
            "low": [1.0, 3.0],
            "close": [8.5, 8.0],
            "volume": [100.0, 300.0],
        }
    )

    result = api.evaluate_technical_lane(
        "F130",
        spy,
        {"statistic": "chaikin_money_flow", "window": 2},
    )

    assert result["value"].iloc[-1] == pytest.approx(0.125)


def test_technical_engine_rejects_validation_rows() -> None:
    api = _api()
    spy = _spy(20)
    spy.loc[spy.index[-1], ["date", "available_at"]] = pd.Timestamp("2011-01-03")

    with pytest.raises(api.TechnicalFeatureEngineError, match="NON_TRAIN_PRICE_ROW"):
        api.evaluate_technical_lane("F129", spy, {"window": 5})


def test_technical_batch_contains_exactly_f121_f130() -> None:
    outputs = _api().evaluate_technical_family_batch(_spy())

    assert tuple(outputs) == tuple(f"F{i:03d}" for i in range(121, 131))
    assert all(output["value"].notna().any() for output in outputs.values())
