from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest


def _engine_api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.model_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"model feature engine is missing: {exc}")


def _decision_panel(dates: pd.DatetimeIndex, values: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "value": values,
        }
    )


def _model_inputs(
    periods: int = 520,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    dates = pd.bdate_range("2008-01-02", periods=periods)
    phase = np.arange(periods, dtype=float)
    returns = (
        0.0004
        + 0.003 * np.sin(phase / 13.0)
        - 0.002 * np.cos(phase / 31.0)
        + np.where((phase // 80).astype(int) % 2 == 0, 0.001, -0.001)
    )
    close = 100.0 * np.exp(np.cumsum(returns))
    market = pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "close": close,
        }
    )
    raw = {
        "F001": np.sin(phase / 17.0),
        "F003": np.sin(phase / 13.0) + 0.2 * np.cos(phase / 31.0),
        "F006": np.sin(phase / 23.0),
        "F009": -np.sin(phase / 5.0),
        "F010": -np.cos(phase / 7.0),
        "F015": 0.5 + 0.2 * np.cos(phase / 19.0),
        "F020": 0.3 * np.sin(phase / 29.0),
        "F021": 0.8 * np.cos(phase / 19.0),
        "F022": np.cos(phase / 11.0) - np.sin(phase / 13.0),
        "F032": 0.7 * np.cos(phase / 37.0),
        "F033": 0.5 * np.sin(phase / 41.0),
        "F035": np.sin(phase / 47.0),
        "F039": -0.4 * np.cos(phase / 53.0),
        "F044": np.sin(phase / 9.0),
        "F046": np.sin(phase / 13.0) - 0.1 * np.cos(phase / 5.0),
        "F048": np.cos(phase / 17.0),
        "F049": np.sin(phase / 43.0),
    }
    return market, {
        lane_id: _decision_panel(dates, values) for lane_id, values in raw.items()
    }


def _parameters(lane_id: str) -> dict[str, object]:
    common: dict[str, object] = {
        "feature_set": "diversified_3",
        "window": 80,
        "refit": "monthly",
    }
    if lane_id == "F051":
        return {
            "component_set": "diversified",
            "components": 3,
            "aggregation": "majority",
            "normalization_window": 20,
        }
    if lane_id == "F052":
        return {
            "base": "trend",
            "gate": "credit",
            "logic": "switch",
            "confirmation": 2,
        }
    if lane_id == "F053":
        return {**common, "clusters": 2}
    if lane_id == "F054":
        return {
            "states": 2,
            "ar_order": 1,
            "window": 80,
            "refit": "monthly",
            "probability": 0.5,
        }
    if lane_id == "F055":
        return {"kind": "cusum", "window": 40, "penalty": 1.0, "reset": True}
    if lane_id == "F056":
        return {**common, "model": "logit", "threshold": 0.5, "ridge": 1.0}
    if lane_id == "F057":
        return {
            **common,
            "model": "pls",
            "threshold": 0.5,
            "components": 2,
            "ridge": 1.0,
            "knots": 3,
        }
    if lane_id == "F058":
        return {
            **common,
            "model": "boosted_stumps",
            "threshold": 0.5,
            "depth": 1,
            "estimators": 10,
            "learning_rate": 0.5,
        }
    if lane_id == "F059":
        return {
            **common,
            "depth": 2,
            "logic": "and",
            "threshold_quantile": 0.5,
        }
    if lane_id == "F060":
        return {"rule": "sma200", "hold": 5, "seed": 17}
    raise AssertionError(lane_id)


def test_f051_majority_uses_frozen_bullish_orientations() -> None:
    api = _engine_api()
    market, panels = _model_inputs(20)
    panels["F003"]["value"] = 1.0
    panels["F021"]["value"] = 2.0
    panels["F032"]["value"] = -3.0

    result = api.evaluate_model_lane(
        "F051", market, panels, _parameters("F051")
    )

    # F003 is bullish-positive; VIX and credit stress are bullish-negative.
    assert result["value"].iloc[-1] == pytest.approx(1.0 / 3.0)


@pytest.mark.parametrize("lane_id", [f"F{index:03d}" for index in range(51, 61)])
def test_f051_f060_produce_finite_train_only_values(lane_id: str) -> None:
    api = _engine_api()
    market, panels = _model_inputs()

    result = api.evaluate_model_lane(
        lane_id, market, panels, _parameters(lane_id)
    )

    assert result["value"].notna().any(), lane_id
    valid = result["value"].notna()
    assert result.loc[valid, "observed_at"].le(
        result.loc[valid, "available_at"]
    ).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane_id", [f"F{index:03d}" for index in range(51, 61)])
def test_f051_f060_are_stable_when_future_rows_are_appended(lane_id: str) -> None:
    api = _engine_api()
    market, panels = _model_inputs()
    cutoff = market.loc[379, "date"]
    before_market = market.loc[market["date"].le(cutoff)].copy()
    before_panels = {
        name: panel.loc[panel["date"].le(cutoff)].copy()
        for name, panel in panels.items()
    }

    before = api.evaluate_model_lane(
        lane_id, before_market, before_panels, _parameters(lane_id)
    )
    after = api.evaluate_model_lane(
        lane_id, market, panels, _parameters(lane_id)
    )
    after = after.loc[after["date"].le(cutoff)]

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True), after.reset_index(drop=True)
    )


@pytest.mark.parametrize("kind", ["cusum", "page_hinkley", "causal_pelt"])
def test_f055_supports_every_frozen_change_point_algorithm(kind: str) -> None:
    api = _engine_api()
    market, panels = _model_inputs(260)

    result = api.evaluate_model_lane(
        "F055",
        market,
        panels,
        {"kind": kind, "window": 40, "penalty": 1.0, "reset": True},
    )

    assert result["value"].notna().any()


@pytest.mark.parametrize("model", ["logit", "probit"])
def test_f056_supports_logit_and_probit(model: str) -> None:
    api = _engine_api()
    market, panels = _model_inputs(260)
    parameters = _parameters("F056")
    parameters["model"] = model

    result = api.evaluate_model_lane("F056", market, panels, parameters)

    assert result["value"].notna().any()


@pytest.mark.parametrize("model", ["gam", "pls"])
def test_f057_supports_gam_and_pls(model: str) -> None:
    api = _engine_api()
    market, panels = _model_inputs(260)
    parameters = _parameters("F057")
    parameters["model"] = model

    result = api.evaluate_model_lane("F057", market, panels, parameters)

    assert result["value"].notna().any()


@pytest.mark.parametrize("model", ["tree", "boosted_stumps"])
def test_f058_supports_tree_and_boosting(model: str) -> None:
    api = _engine_api()
    market, panels = _model_inputs(260)
    parameters = _parameters("F058")
    parameters["model"] = model

    result = api.evaluate_model_lane("F058", market, panels, parameters)

    assert result["value"].notna().any()


@pytest.mark.parametrize(
    "rule",
    [
        "always_long",
        "always_short",
        "sma200",
        "momentum252",
        "rev2",
        "inverse",
        "block_placebo",
    ],
)
def test_f060_supports_every_frozen_control(rule: str) -> None:
    api = _engine_api()
    market, panels = _model_inputs(300)

    result = api.evaluate_model_lane(
        "F060", market, panels, {"rule": rule, "hold": 5, "seed": 17}
    )

    assert result["value"].notna().any()


def test_f060_block_placebo_seeds_create_distinct_sequences() -> None:
    api = _engine_api()
    market, panels = _model_inputs(300)

    sequences = {
        tuple(
            api.evaluate_model_lane(
                "F060",
                market,
                panels,
                {"rule": "block_placebo", "hold": 5, "seed": seed},
            )["value"]
        )
        for seed in (17, 29, 43)
    }

    assert len(sequences) == 3


def test_model_engine_rejects_validation_rows() -> None:
    api = _engine_api()
    market, panels = _model_inputs(20)
    future = market.iloc[-1].copy()
    future[["date", "observed_at", "available_at"]] = pd.Timestamp("2011-01-03")
    market.loc[len(market)] = future

    with pytest.raises(api.ModelFeatureEngineError, match="NON_TRAIN_MARKET_ROW"):
        api.evaluate_model_lane("F060", market, panels, _parameters("F060"))


def test_supervised_model_waits_for_a_complete_valid_window() -> None:
    api = _engine_api()
    market, panels = _model_inputs(220)
    panels["F032"].loc[:19, "value"] = np.nan

    result = api.evaluate_model_lane("F056", market, panels, _parameters("F056"))

    assert result.loc[:99, "value"].isna().all()
    assert result.loc[100:, "value"].notna().any()
