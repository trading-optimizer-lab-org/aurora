from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest


def _engine_api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.positioning_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"positioning feature engine is missing: {exc}")


def _panels(periods: int = 900) -> dict[str, pd.DataFrame]:
    dates = pd.bdate_range("2006-01-03", periods=periods)
    phase = np.arange(periods, dtype=float)
    returns = 0.0003 + 0.003 * np.sin(phase / 11.0) + 0.001 * np.cos(phase / 31.0)
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]] * (1.0 + 0.0005 * np.sin(phase / 7.0))
    bar_range = 0.003 + 0.002 * (1.0 + np.cos(phase / 19.0))
    volume = 1_000_000.0 * np.exp(0.2 * np.sin(phase / 17.0))
    spy = pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "open": open_,
            "high": np.maximum(open_, close) * (1.0 + bar_range),
            "low": np.minimum(open_, close) * (1.0 - bar_range),
            "close": close,
            "volume": volume,
        }
    )
    balance_dates = dates[20::63]
    balance_phase = np.arange(len(balance_dates), dtype=float)
    balance = pd.DataFrame(
        {
            "date": balance_dates,
            "observed_at": balance_dates - pd.Timedelta(days=395),
            "available_at": balance_dates,
            "household_equity_share": 0.2 + 0.02 * np.sin(balance_phase / 2.0),
            "mutual_fund_equity_share": 0.5 + 0.03 * np.cos(balance_phase / 3.0),
        }
    )
    margin_dates = dates[10::21]
    margin_phase = np.arange(len(margin_dates), dtype=float)
    debit = 100.0 * np.exp(0.015 * margin_phase + 0.05 * np.sin(margin_phase / 4.0))
    credit = 80.0 * np.exp(0.01 * margin_phase + 0.03 * np.cos(margin_phase / 5.0))
    margin = pd.DataFrame(
        {
            "date": margin_dates,
            "observed_at": margin_dates - pd.Timedelta(days=45),
            "available_at": margin_dates,
            "margin_debit": debit,
            "margin_credit": credit,
            "margin_debit_to_credit": debit / credit,
        }
    )
    cftc_dates = dates[5::5]
    cftc_phase = np.arange(len(cftc_dates), dtype=float)
    open_interest = 1_000_000.0 * (1.0 + 0.001 * cftc_phase)
    cftc = pd.DataFrame(
        {
            "date": cftc_dates,
            "observed_at": cftc_dates - pd.Timedelta(days=3),
            "available_at": cftc_dates,
            "open_interest": open_interest,
            "noncommercial_net_pct_oi": 0.1 * np.sin(cftc_phase / 6.0),
            "commercial_net_pct_oi": -0.08 * np.sin(cftc_phase / 6.0),
            "noncommercial_short_pct_oi": 0.3 + 0.04 * np.cos(cftc_phase / 7.0),
            "reportable_short_pct_oi": 0.65 + 0.03 * np.sin(cftc_phase / 8.0),
            "top4_net_concentration": 0.05 * np.sin(cftc_phase / 9.0),
            "top8_net_concentration": 0.09 * np.sin(cftc_phase / 9.0),
            "open_interest_combined": open_interest * (
                1.2 + 0.05 * np.sin(cftc_phase / 10.0)
            ),
            "noncommercial_net_pct_oi_combined": 0.12
            * np.sin(cftc_phase / 6.0 + 0.2),
            "commercial_net_pct_oi_combined": -0.09
            * np.sin(cftc_phase / 6.0 + 0.1),
            "noncommercial_short_pct_oi_combined": 0.32
            + 0.03 * np.cos(cftc_phase / 7.0),
            "reportable_short_pct_oi_combined": 0.66
            + 0.02 * np.sin(cftc_phase / 8.0),
            "top4_net_concentration_combined": 0.06
            * np.sin(cftc_phase / 9.0 + 0.1),
            "top8_net_concentration_combined": 0.1
            * np.sin(cftc_phase / 9.0 + 0.1),
        }
    )
    vol = pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "vix_close": 20.0 + 3.0 * np.sin(phase / 23.0),
            "vxo_close": 19.0 + 2.5 * np.sin(phase / 23.0 + 0.2),
        }
    )
    market_factor = 0.002 * np.sin(phase / 13.0)
    industries = pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            **{
                f"industry_{index}": market_factor
                + 0.0015 * np.sin(phase / (5.0 + index) + index)
                for index in range(8)
            },
        }
    )
    return {
        "spy": spy,
        "balance": balance,
        "margin": margin,
        "finra_margin": margin.copy(),
        "cftc": cftc,
        "legacy_cftc": cftc.copy(),
        "vol": vol,
        "industries": industries,
    }


def _parameters(lane_id: str) -> dict[str, object]:
    if lane_id == "F081":
        return {
            "daily_window": 40,
            "balance_lag": 1,
            "balance_window": 4,
            "margin_lag": 1,
            "margin_window": 6,
            "aggregation": "equal",
        }
    if lane_id == "F082":
        return {"statistic": "change", "window": 6, "lag": 1, "direction": "continuation"}
    if lane_id == "F083":
        return {
            "statistic": "short_pressure",
            "window": 13,
            "lag": 1,
            "direction": "contrarian",
        }
    if lane_id == "F084":
        return {
            "statistic": "aggregate_flow",
            "balance_window": 4,
            "margin_window": 6,
            "positioning_window": 13,
        }
    if lane_id == "F085":
        return {"statistic": "signed_volume_shock", "window": 40}
    if lane_id == "F086":
        return {"statistic": "volume_scaled", "window": 13, "lag": 1}
    if lane_id == "F087":
        return {
            "statistic": "noncommercial_gap",
            "window": 13,
            "lag": 1,
            "direction": "continuation",
        }
    if lane_id == "F088":
        return {"statistic": "top4_top8_share", "window": 13, "lag": 1}
    if lane_id == "F089":
        return {
            "statistic": "composite",
            "window": 40,
            "change_lag": 5,
            "direction": "contrarian",
        }
    if lane_id == "F090":
        return {"statistic": "interaction", "window": 40}
    raise AssertionError(lane_id)


@pytest.mark.parametrize("lane_id", [f"F{index:03d}" for index in range(81, 91)])
def test_f081_f090_produce_finite_train_only_values(lane_id: str) -> None:
    api = _engine_api()

    result = api.evaluate_positioning_lane(lane_id, _panels(), _parameters(lane_id))

    assert result["value"].notna().any(), lane_id
    valid = result["value"].notna()
    assert result.loc[valid, "observed_at"].le(
        result.loc[valid, "available_at"]
    ).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane_id", [f"F{index:03d}" for index in range(81, 91)])
def test_f081_f090_are_stable_when_future_rows_are_appended(lane_id: str) -> None:
    api = _engine_api()
    panels = _panels()
    cutoff = panels["spy"].loc[599, "date"]
    before_panels = {
        name: panel.loc[panel["date"].le(cutoff)].copy()
        for name, panel in panels.items()
    }

    before = api.evaluate_positioning_lane(
        lane_id, before_panels, _parameters(lane_id)
    )
    after = api.evaluate_positioning_lane(lane_id, panels, _parameters(lane_id))

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True),
        after.loc[after["date"].le(cutoff)].reset_index(drop=True),
    )


@pytest.mark.parametrize("aggregation", ["equal", "financing", "allocation"])
def test_f081_supports_each_frozen_aggregate_flow_weighting(aggregation: str) -> None:
    api = _engine_api()
    parameters = _parameters("F081")
    parameters["aggregation"] = aggregation

    result = api.evaluate_positioning_lane("F081", _panels(), parameters)

    assert result["value"].notna().any()


@pytest.mark.parametrize(
    "statistic", ["level", "change", "debit_growth", "percentile"]
)
def test_f082_supports_each_finra_margin_state(statistic: str) -> None:
    api = _engine_api()

    result = api.evaluate_positioning_lane(
        "F082",
        _panels(),
        {"statistic": statistic, "window": 6, "lag": 1, "direction": "continuation"},
    )

    assert result["value"].notna().any()


@pytest.mark.parametrize(
    "statistic", ["noncommercial_short", "reportable_short", "short_pressure"]
)
def test_f083_supports_each_declared_futures_short_proxy(statistic: str) -> None:
    api = _engine_api()

    result = api.evaluate_positioning_lane(
        "F083",
        _panels(),
        {"statistic": statistic, "window": 13, "lag": 1, "direction": "contrarian"},
    )

    assert result["value"].notna().any()


@pytest.mark.parametrize(
    "statistic", ["aggregate_flow", "financing_pressure", "allocation_pressure", "disagreement"]
)
def test_f084_supports_each_frozen_cross_source_flow_proxy(statistic: str) -> None:
    api = _engine_api()
    parameters = _parameters("F084")
    parameters["statistic"] = statistic

    result = api.evaluate_positioning_lane("F084", _panels(), parameters)

    assert result["value"].notna().any()


@pytest.mark.parametrize(
    "statistic", ["close_location", "range_volume_pressure", "signed_volume_shock", "persistence"]
)
def test_f085_supports_each_explicit_eod_pressure_redesign(statistic: str) -> None:
    api = _engine_api()

    result = api.evaluate_positioning_lane(
        "F085", _panels(), {"statistic": statistic, "window": 40}
    )

    assert result["value"].notna().any()


@pytest.mark.parametrize("statistic", ["participation_gap", "change", "volume_scaled"])
def test_f086_supports_each_combined_minus_futures_participation_proxy(
    statistic: str,
) -> None:
    api = _engine_api()

    result = api.evaluate_positioning_lane(
        "F086", _panels(), {"statistic": statistic, "window": 13, "lag": 1}
    )

    assert result["value"].notna().any()


def test_f086_raw_participation_gap_is_available_on_first_cftc_release() -> None:
    api = _engine_api()

    result = api.evaluate_positioning_lane(
        "F086",
        _panels(),
        {"statistic": "participation_gap", "window": 13, "lag": 1},
    )

    assert result["value"].first_valid_index() == 0


@pytest.mark.parametrize(
    "statistic", ["noncommercial_gap", "commercial_gap", "gap_change", "open_interest_share"]
)
def test_f087_supports_each_futures_combined_positioning_gap(statistic: str) -> None:
    api = _engine_api()

    result = api.evaluate_positioning_lane(
        "F087",
        _panels(),
        {"statistic": statistic, "window": 13, "lag": 1, "direction": "continuation"},
    )

    assert result["value"].notna().any()


def test_f087_raw_noncommercial_gap_is_available_on_first_cftc_release() -> None:
    api = _engine_api()

    result = api.evaluate_positioning_lane(
        "F087",
        _panels(),
        {
            "statistic": "noncommercial_gap",
            "window": 13,
            "lag": 1,
            "direction": "continuation",
        },
    )

    assert result["value"].first_valid_index() == 0


@pytest.mark.parametrize(
    "statistic", ["top4_level", "top8_level", "top4_top8_share", "combined_gap", "change"]
)
def test_f088_supports_each_observable_cftc_concentration_state(
    statistic: str,
) -> None:
    api = _engine_api()

    result = api.evaluate_positioning_lane(
        "F088", _panels(), {"statistic": statistic, "window": 13, "lag": 1}
    )

    assert result["value"].notna().any()


@pytest.mark.parametrize(
    "statistic", ["vix_vxo_disagreement", "realized_asymmetry", "composite", "divergence"]
)
def test_f089_supports_each_non_surface_volatility_asymmetry(statistic: str) -> None:
    api = _engine_api()

    result = api.evaluate_positioning_lane(
        "F089",
        _panels(),
        {"statistic": statistic, "window": 40, "change_lag": 5, "direction": "contrarian"},
    )

    assert result["value"].notna().any()


@pytest.mark.parametrize(
    "statistic", ["common_correlation", "variance_gap", "correlation_gap", "interaction"]
)
def test_f090_supports_each_realized_correlation_proxy(statistic: str) -> None:
    api = _engine_api()

    result = api.evaluate_positioning_lane(
        "F090", _panels(), {"statistic": statistic, "window": 40}
    )

    assert result["value"].notna().any()


def test_f090_common_correlation_waits_for_both_complete_windows() -> None:
    api = _engine_api()

    result = api.evaluate_positioning_lane(
        "F090", _panels(180), {"statistic": "common_correlation", "window": 40}
    )

    assert result["value"].first_valid_index() == 78


def test_f090_uses_the_available_industry_subset_during_isolated_gaps() -> None:
    api = _engine_api()
    panels = _panels(220)
    panels["industries"].loc[150:170, "industry_0"] = np.nan

    result = api.evaluate_positioning_lane(
        "F090", panels, {"statistic": "common_correlation", "window": 40}
    )

    assert result["value"].iloc[-40:].notna().all()


def test_f090_rejects_dates_below_the_frozen_industry_coverage_floor() -> None:
    api = _engine_api()
    panels = _panels(260)
    panels["industries"].loc[150:, ["industry_0", "industry_1"]] = np.nan

    result = api.evaluate_positioning_lane(
        "F090", panels, {"statistic": "common_correlation", "window": 40}
    )

    assert result["value"].iloc[-1:].isna().all()


def test_positioning_batch_contains_exactly_f081_f090() -> None:
    api = _engine_api()

    outputs = api.evaluate_positioning_family_batch(_panels())

    assert tuple(outputs) == tuple(f"F{index:03d}" for index in range(81, 91))
    assert all(output["value"].notna().any() for output in outputs.values())


def test_positioning_engine_rejects_validation_rows() -> None:
    api = _engine_api()
    panels = _panels(40)
    panels["spy"].loc[
        panels["spy"].index[-1], ["date", "available_at"]
    ] = pd.Timestamp("2011-01-03")

    with pytest.raises(api.PositioningFeatureEngineError, match="NON_TRAIN_PANEL_ROW:spy"):
        api.evaluate_positioning_lane("F085", panels, {"window": 20})
