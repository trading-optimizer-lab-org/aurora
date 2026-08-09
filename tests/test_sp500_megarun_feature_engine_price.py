from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest


def _engine_api():
    try:
        return importlib.import_module("aurora.infra.sp500_megarun.feature_engine")
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"feature engine implementation is missing: {exc}")


def _spy_frame(periods: int = 700) -> pd.DataFrame:
    dates = pd.bdate_range("2007-01-02", periods=periods)
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
            "available_at": dates,
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
        "available_at": pd.Timestamp("2011-01-03"),
    }

    with pytest.raises(api.FeatureEngineError, match="NON_TRAIN_PRICE_ROW"):
        api.evaluate_price_family_batch(spy)
