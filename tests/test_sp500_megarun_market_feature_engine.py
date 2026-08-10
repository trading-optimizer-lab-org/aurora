from __future__ import annotations

import importlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def _engine_api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.market_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"market feature engine is missing: {exc}")


def _frozen_space(lane_id: str) -> dict[str, list[object]]:
    path = Path(__file__).parents[1] / "config" / "sp500_megarun_feature_contract_240.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    lane = next(row for row in payload["lanes"] if row["lane_id"] == lane_id)
    return lane.get("parameter_space") or payload["operator_spaces"].get(
        lane["operator"], payload["operator_spaces"]["*"]
    )


def _baseline_parameters(lane_id: str) -> dict[str, object]:
    space = _frozen_space(lane_id)
    baseline = {name: values[0] for name, values in space.items()}
    if "window" in baseline:
        windows = [int(value) for value in space["window"]]
        baseline["window"] = min(
            (value for value in windows if value >= 20), default=max(windows)
        )
    if "normalization" in baseline:
        baseline["normalization"] = "none"
    return baseline


def _value_signature(frame: pd.DataFrame) -> int:
    values = frame["value"].replace([np.inf, -np.inf], np.nan).round(12)
    return int(pd.util.hash_pandas_object(values, index=False).sum())


def _panels(periods: int = 900) -> dict[str, pd.DataFrame]:
    dates = pd.bdate_range("2007-01-02", periods=periods)
    phase = np.arange(periods, dtype=float)
    spy = pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "close": 100.0 + 0.03 * phase + 2.0 * np.sin(phase / 17.0),
        }
    )
    cboe = pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "vix_close": 20.0 + 3.0 * np.sin(phase / 13.0),
            "vxo_close": 19.0 + 2.5 * np.sin(phase / 15.0),
        }
    )
    weekly_dates = dates[::5]
    weekly_phase = np.arange(len(weekly_dates), dtype=float)
    cftc = pd.DataFrame(
        {
            "date": weekly_dates,
            "observed_at": weekly_dates - pd.Timedelta(days=3),
            "available_at": weekly_dates,
            "open_interest": 1_000_000.0 + 1_000.0 * weekly_phase,
            "noncommercial_net_pct_oi": 0.1 * np.sin(weekly_phase / 4.0),
            "commercial_net_pct_oi": -0.08 * np.sin(weekly_phase / 5.0),
            "top4_net_concentration": 0.03 * np.cos(weekly_phase / 7.0),
            "noncommercial_net_pct_oi_combined": 0.09 * np.sin(weekly_phase / 4.5),
        }
    )
    rates = pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "yield_3m": 1.0 + 0.1 * np.sin(phase / 30.0),
            "yield_2y": 2.0 + 0.2 * np.sin(phase / 40.0),
            "yield_10y": 4.0 + 0.3 * np.sin(phase / 50.0),
        }
    )
    return {"spy": spy, "cboe": cboe, "cftc": cftc, "rates": rates}


def test_f021_is_the_trailing_vix_zscore() -> None:
    api = _engine_api()
    panels = _panels(40)

    result = api.evaluate_market_lane("F021", panels, {"window": 20})

    values = panels["cboe"]["vix_close"].iloc[:20]
    expected = (values.iloc[-1] - values.mean()) / values.std(ddof=0)
    assert result.loc[19, "value"] == pytest.approx(expected)
    assert result.loc[:18, "value"].isna().all()


def test_appending_future_market_inputs_does_not_change_past_features() -> None:
    api = _engine_api()
    panels = _panels(80)
    before_panels = {name: frame.loc[frame["date"] <= panels["spy"].loc[59, "date"]] for name, frame in panels.items()}

    before = api.evaluate_market_lane("F026", before_panels, {"window": 20})
    after = api.evaluate_market_lane("F026", panels, {"window": 20}).iloc[:60]

    pd.testing.assert_frame_equal(before.reset_index(drop=True), after.reset_index(drop=True))


def test_all_f021_f031_smoke_outputs_are_nonempty_and_causal() -> None:
    api = _engine_api()

    outputs = api.evaluate_market_family_batch(_panels())

    assert set(outputs) == {f"F{index:03d}" for index in range(21, 32)}
    for lane_id, frame in outputs.items():
        assert frame["value"].notna().any(), lane_id
        assert frame["available_at"].le(frame["date"]).all(), lane_id
        assert frame["observed_at"].le(frame["available_at"]).all(), lane_id
        assert frame["date"].max() <= pd.Timestamp("2010-12-31"), lane_id


@pytest.mark.parametrize("lane_id", [f"F{index:03d}" for index in range(21, 32)])
def test_f021_f031_execute_every_frozen_parameter_choice(lane_id: str) -> None:
    api = _engine_api()
    panels = _panels()
    for name, choices in _frozen_space(lane_id).items():
        signatures: set[int] = set()
        for choice in choices:
            parameters = _baseline_parameters(lane_id)
            parameters[name] = choice
            if name == "normalization":
                parameters["window"] = 63
            output = api.evaluate_market_lane(lane_id, panels, parameters)
            assert output["value"].notna().any(), (lane_id, name, choice)
            signatures.add(_value_signature(output))
        if len(choices) > 1:
            assert len(signatures) > 1, f"ignored frozen dimension: {lane_id}.{name}"


def test_market_engine_rejects_parameters_outside_the_frozen_lane_space() -> None:
    api = _engine_api()
    with pytest.raises(api.MarketFeatureEngineError, match="UNKNOWN_PARAMETER:F021:invented"):
        api.evaluate_market_lane("F021", _panels(), {"window": 20, "invented": 1})


def test_market_engine_rejects_validation_rows() -> None:
    api = _engine_api()
    panels = _panels(20)
    panels["rates"].loc[len(panels["rates"])] = {
        "date": pd.Timestamp("2011-01-03"),
        "observed_at": pd.Timestamp("2010-12-31"),
        "available_at": pd.Timestamp("2011-01-03"),
        "yield_3m": 1.0,
        "yield_2y": 2.0,
        "yield_10y": 4.0,
    }

    with pytest.raises(api.MarketFeatureEngineError, match="NON_TRAIN_PANEL_ROW:rates"):
        api.evaluate_market_family_batch(panels)
