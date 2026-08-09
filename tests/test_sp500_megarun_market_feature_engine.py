from __future__ import annotations

import importlib

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
