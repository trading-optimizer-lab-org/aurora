from __future__ import annotations

import importlib
from typing import Mapping

import numpy as np
import pandas as pd
import pytest


def _api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.volatility_positioning_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"volatility-positioning feature engine is missing: {exc}")


def _timed(dates: pd.DatetimeIndex, values: Mapping[str, object]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            **values,
        }
    )


def _inputs() -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    dates = pd.bdate_range("2000-01-03", "2010-12-31")
    phase = np.arange(len(dates), dtype=float)
    returns = 0.0002 + 0.007 * np.sin(phase / 29.0) + 0.003 * np.cos(phase / 11.0)
    market = _timed(dates, {"close": 100.0 * np.exp(np.cumsum(returns))})
    vix = 18.0 + 5.0 * np.sin(phase / 37.0) + 2.0 * np.cos(phase / 13.0)
    vol = _timed(
        dates,
        {
            "vix_close": vix,
            "vxo_close": vix + 0.7 * np.sin(phase / 17.0),
        },
    )
    weekly = dates[4::5]
    w = np.arange(len(weekly), dtype=float)
    cftc = _timed(
        weekly,
        {
            "open_interest": 1_000_000.0 + 4_000.0 * w + 80_000.0 * np.sin(w / 9.0),
            "noncommercial_net_pct_oi": 0.12 * np.sin(w / 11.0),
            "commercial_net_pct_oi": -0.10 * np.sin((w + 2.0) / 12.0),
            "noncommercial_short_pct_oi": 0.28 + 0.05 * np.cos(w / 10.0),
            "noncommercial_spreading_pct_oi": 0.08 + 0.03 * np.sin(w / 8.0),
            "reportable_short_pct_oi": 0.55 + 0.04 * np.sin(w / 7.0),
            "trader_count": 80.0 + 10.0 * np.sin(w / 13.0) + 0.03 * w,
            "top4_net_concentration": 0.04 * np.sin(w / 15.0),
            "top8_net_concentration": 0.07 * np.sin((w + 1.0) / 16.0),
            "open_interest_combined": 1_150_000.0
            + 4_500.0 * w
            + 90_000.0 * np.sin((w + 1.0) / 9.5),
            "noncommercial_net_pct_oi_combined": 0.10 * np.sin((w + 1.0) / 11.5),
            "commercial_net_pct_oi_combined": -0.08 * np.sin((w + 3.0) / 12.5),
            "noncommercial_spreading_pct_oi_combined": 0.11
            + 0.025 * np.sin((w + 2.0) / 8.5),
            "trader_count_combined": 92.0 + 9.0 * np.sin((w + 1.0) / 13.5),
            "top4_net_concentration_combined": 0.035 * np.sin((w + 1.0) / 15.5),
            "top8_net_concentration_combined": 0.065 * np.sin((w + 2.0) / 16.5),
        },
    )
    fallback = _timed(
        weekly,
        {
            "commercial_breadth": 0.35 * np.sin(w / 14.0),
            "noncommercial_breadth": -0.3 * np.sin((w + 2.0) / 13.0),
            "breadth_gap": 0.35 * np.sin(w / 14.0)
            + 0.3 * np.sin((w + 2.0) / 13.0),
            "positioning_disagreement": 0.12 + 0.05 * np.sin(w / 10.0),
            "commercial_dispersion": 0.08 + 0.03 * np.cos(w / 9.0),
            "market_count": 70,
        },
    )
    return market, {"vol": vol, "cftc": cftc, "fallback": fallback}


_DEFAULTS = {
    "F211": "vix_percentile",
    "F212": "vol_of_vol",
    "F213": "variance_spread",
    "F214": "shock_duration",
    "F215": "commercial_breadth",
    "F216": "disagreement_zscore",
    "F217": "commercial_net",
    "F218": "speculative_pressure",
    "F219": "commercial_mode_difference",
    "F220": "crowding_composite",
}


def _parameters(lane: str) -> dict[str, object]:
    return {
        "statistic": _DEFAULTS[lane],
        "window": 20 if lane <= "F214" else 13,
        "realized_window": 20,
        "lag": 5,
        "tail": 0.9,
        "change_lag": 1,
        "normalization": "raw",
        "direction": "continuation",
    }


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(211, 221)])
def test_f211_f220_produce_finite_train_only_values(lane: str) -> None:
    market, panels = _inputs()

    result = _api().evaluate_volatility_positioning_lane(
        lane, market, panels, _parameters(lane)
    )

    valid = result["value"].notna()
    assert valid.any(), lane
    assert result.loc[valid, "observed_at"].le(result.loc[valid, "available_at"]).all()
    assert result.loc[valid, "available_at"].le(result.loc[valid, "date"]).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(211, 221)])
def test_f211_f220_do_not_change_when_future_train_rows_are_appended(lane: str) -> None:
    api = _api()
    market, panels = _inputs()
    cutoff = market.loc[1900, "date"]
    before_market = market.loc[market["date"].le(cutoff)].copy()
    before_panels = {
        name: panel.loc[panel["date"].le(cutoff)].copy()
        for name, panel in panels.items()
    }

    before = api.evaluate_volatility_positioning_lane(
        lane, before_market, before_panels, _parameters(lane)
    )
    after = api.evaluate_volatility_positioning_lane(
        lane, market, panels, _parameters(lane)
    )

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True),
        after.loc[after["date"].le(cutoff)].reset_index(drop=True),
    )


@pytest.mark.parametrize(
    ("lane", "variants"),
    [
        ("F211", ("vix_level", "vix_log_level", "vix_trend", "vix_zscore", "vix_percentile", "vix_vxo_spread")),
        ("F212", ("vol_of_vol", "mean_abs_change", "positive_shock_vol", "negative_shock_vol", "vol_of_vol_zscore")),
        ("F213", ("implied_variance", "realized_variance", "variance_spread", "variance_ratio", "log_variance_ratio", "spread_zscore")),
        ("F214", ("shock_magnitude", "shock_indicator", "shock_duration", "distance_from_peak", "normalization_speed", "tail_percentile")),
        ("F215", ("commercial_breadth", "noncommercial_breadth", "breadth_gap", "breadth_trend", "breadth_zscore")),
        ("F216", ("positioning_disagreement", "disagreement_change", "disagreement_zscore", "commercial_dispersion", "dispersion_zscore", "reversal_pressure")),
        ("F217", ("commercial_net", "commercial_change", "commercial_zscore", "commercial_percentile", "commercial_open_interest_interaction")),
        ("F218", ("noncommercial_net", "noncommercial_short", "spreading_share", "noncommercial_change", "speculative_pressure")),
        ("F219", ("commercial_mode_difference", "noncommercial_mode_difference", "option_open_interest_share", "spreading_mode_difference", "concentration_mode_difference")),
        ("F220", ("open_interest", "open_interest_growth", "trader_count", "trader_count_growth", "top4_net_concentration", "top8_net_concentration", "concentration_gap", "crowding_composite")),
    ],
)
def test_f211_f220_frozen_statistics_are_executable(
    lane: str, variants: tuple[str, ...]
) -> None:
    market, panels = _inputs()
    for statistic in variants:
        result = _api().evaluate_volatility_positioning_lane(
            lane,
            market,
            panels,
            {**_parameters(lane), "statistic": statistic},
        )
        assert result["value"].notna().any(), f"{lane}:{statistic}"


def test_volatility_positioning_engine_fails_closed() -> None:
    api = _api()
    market, panels = _inputs()
    with pytest.raises(api.VolatilityPositioningFeatureEngineError, match="UNKNOWN_LANE"):
        api.evaluate_volatility_positioning_lane("F221", market, panels, {})
    with pytest.raises(api.VolatilityPositioningFeatureEngineError, match="UNKNOWN_PARAMETER"):
        api.evaluate_volatility_positioning_lane(
            "F211", market, panels, {**_parameters("F211"), "statistic": "invented"}
        )
    future = market.copy()
    future.loc[len(future)] = future.iloc[-1]
    future.loc[len(future) - 1, ["date", "observed_at", "available_at"]] = pd.Timestamp(
        "2011-01-03"
    )
    with pytest.raises(
        api.VolatilityPositioningFeatureEngineError, match="NON_TRAIN_MARKET_ROW"
    ):
        api.evaluate_volatility_positioning_lane(
            "F211", future, panels, _parameters("F211")
        )
