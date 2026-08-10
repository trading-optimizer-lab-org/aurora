from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.infra.sp500_megarun.data_contract import load_and_validate_contract
from aurora.infra.sp500_megarun.feature_contract import (
    load_and_validate_feature_contract,
)


def _engine_api():
    try:
        return importlib.import_module("aurora.infra.sp500_megarun.feature_engine")
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"feature engine implementation is missing: {exc}")


def _spy_frame(periods: int = 700) -> pd.DataFrame:
    dates = pd.bdate_range("2007-01-02", periods=periods)
    available_at = dates + pd.offsets.BDay(1)
    close = pd.Series(np.linspace(100.0, 180.0, periods), index=dates)
    open_ = close.shift(1).fillna(close.iloc[0]) * 1.001
    return pd.DataFrame(
        {
            "date": dates,
            "open": open_.to_numpy(),
            "high": np.maximum(open_.to_numpy(), close.to_numpy()) + 1.0,
            "low": np.minimum(open_.to_numpy(), close.to_numpy()) - 1.0,
            "close": close.to_numpy(),
            "volume": np.linspace(1_000_000.0, 2_000_000.0, periods),
            "available_at": available_at,
        }
    )


def test_price_family_f001_uses_only_the_trailing_window() -> None:
    api = _engine_api()
    spy = _spy_frame(10)

    result = api.evaluate_price_lane(
        "F001",
        spy,
        {"kind": "sma", "window": 5, "normalization": "price_ratio", "threshold": 0.0},
    )

    expected = spy.loc[4, "close"] / spy.loc[:4, "close"].mean() - 1.0
    assert result.loc[4, "value"] == pytest.approx(expected)
    assert result.loc[:3, "value"].isna().all()
    assert result.loc[4, "available_at"] == result.loc[4, "date"]


def test_price_family_f003_momentum_has_no_future_dependency() -> None:
    api = _engine_api()
    spy = _spy_frame(30)

    result = api.evaluate_price_lane(
        "F003",
        spy,
        {"window": 5, "skip": 0, "return_kind": "simple", "threshold": 0.0},
    )

    expected = spy.loc[5, "close"] / spy.loc[0, "close"] - 1.0
    assert result.loc[5, "value"] == pytest.approx(expected)
    assert result.loc[:4, "value"].isna().all()


def test_appending_future_prices_cannot_change_a_past_feature() -> None:
    api = _engine_api()
    spy = _spy_frame(40)
    parameters = {
        "kind": "sma",
        "window": 10,
        "normalization": "price_ratio",
        "threshold": 0.0,
    }

    before = api.evaluate_price_lane("F001", spy.iloc[:30], parameters)
    after = api.evaluate_price_lane("F001", spy, parameters).iloc[:30]

    pd.testing.assert_frame_equal(before.reset_index(drop=True), after.reset_index(drop=True))


def test_all_first_twenty_price_lanes_return_bounded_causal_outputs() -> None:
    api = _engine_api()
    spy = _spy_frame()

    outputs = api.evaluate_price_family_batch(spy)

    assert set(outputs) == {f"F{index:03d}" for index in range(1, 21)}
    for lane_id, frame in outputs.items():
        assert frame["value"].notna().any(), lane_id
        assert frame["available_at"].le(frame["date"]).all(), lane_id
        assert frame["observed_at"].lt(frame["available_at"]).all(), lane_id
        assert frame["date"].max() <= pd.Timestamp("2010-12-31"), lane_id


def test_price_engine_rejects_validation_rows_instead_of_trimming_them() -> None:
    api = _engine_api()
    spy = _spy_frame()
    spy.loc[len(spy)] = {
        "date": pd.Timestamp("2011-01-03"),
        "open": 181.0,
        "high": 182.0,
        "low": 180.0,
        "close": 181.5,
        "volume": 2_100_000.0,
        "available_at": pd.Timestamp("2011-01-04"),
    }

    with pytest.raises(api.FeatureEngineError, match="NON_TRAIN_PRICE_ROW"):
        api.evaluate_price_family_batch(spy)


def test_every_frozen_f001_f020_parameter_choice_is_executable() -> None:
    root = Path(__file__).resolve().parents[1]
    data = load_and_validate_contract(root / "config" / "sp500_megarun_free_data_240.json")
    contract = load_and_validate_feature_contract(
        root / "config" / "sp500_megarun_feature_contract_240.json",
        data,
    )
    api = _engine_api()
    spy = _spy_frame(1_000)

    for lane in contract.lanes[:20]:
        baseline = {name: choices[0] for name, choices in lane.parameter_space.items()}
        for name, choices in lane.parameter_space.items():
            for choice in choices:
                parameters = {**baseline, name: choice}
                if lane.lane_id == "F002" and int(parameters["fast"]) >= int(parameters["slow"]):
                    parameters["slow"] = next(
                        value
                        for value in lane.parameter_space["slow"]
                        if int(value) > int(parameters["fast"])
                    )
                result = api.evaluate_price_lane(lane.lane_id, spy, parameters)
                assert result["value"].notna().any(), (lane.lane_id, name, choice)


@pytest.mark.parametrize(
    ("lane", "left", "right"),
    [
        ("F001", {"kind": "sma", "window": 63, "normalization": "price_ratio", "threshold": 0.0}, {"kind": "sma", "window": 63, "normalization": "price_ratio", "threshold": 1.0}),
        ("F002", {"kind": "sma", "fast": 10, "slow": 126, "confirmation": 1}, {"kind": "macd", "fast": 10, "slow": 126, "confirmation": 5}),
        ("F004", {"components": 2, "short_window": 5, "long_window": 126, "aggregation": "majority"}, {"components": 5, "short_window": 20, "long_window": 504, "aggregation": "acceleration"}),
        ("F005", {"estimator": "ols", "window": 63, "minimum_r2": 0.0}, {"estimator": "kaufman_efficiency", "window": 252, "minimum_r2": 0.75}),
        ("F006", {"window": 20, "kind": "donchian", "buffer": 0.0, "confirmation": 1}, {"window": 63, "kind": "atr_channel", "buffer": 1.0, "confirmation": 3}),
        ("F007", {"kind": "bollinger", "window": 20, "width": 1.0, "mode": "breakout"}, {"kind": "ichimoku", "window": 63, "width": 2.5, "mode": "reversal"}),
        ("F008", {"window": 63, "statistic": "autocorrelation", "lag": 1}, {"window": 126, "statistic": "entropy", "lag": 5}),
        ("F009", {"window": 2, "threshold": 0.0, "confirmation": 1, "hold": 1}, {"window": 10, "threshold": 0.01, "confirmation": 3, "hold": 5}),
        ("F010", {"kind": "rsi", "window": 14, "lower": 20, "upper": 80}, {"kind": "aroon", "window": 40, "lower": 30, "upper": 70}),
        ("F015", {"kind": "close", "window": 20, "statistic": "level"}, {"kind": "rogers_satchell", "window": 63, "statistic": "percentile"}),
    ],
)
def test_previously_ignored_price_parameters_change_the_feature(
    lane: str,
    left: dict[str, object],
    right: dict[str, object],
) -> None:
    api = _engine_api()
    spy = _spy_frame(1_000)

    first = api.evaluate_price_lane(lane, spy, left)["value"]
    second = api.evaluate_price_lane(lane, spy, right)["value"]

    overlap = first.notna() & second.notna()
    assert overlap.any()
    assert not np.allclose(first.loc[overlap], second.loc[overlap])
