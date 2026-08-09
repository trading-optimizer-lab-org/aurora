from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest


def _engine_api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.tail_macro_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"tail/macro feature engine is missing: {exc}")


def _dated_panel(dates: pd.DatetimeIndex, **values: object) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            **values,
        }
    )


def _panels(periods: int = 1_500) -> dict[str, pd.DataFrame]:
    dates = pd.bdate_range("2004-01-02", periods=periods)
    phase = np.arange(periods, dtype=float)
    returns = 0.0002 + 0.004 * np.sin(phase / 17.0) + 0.001 * np.cos(
        phase / 41.0
    )
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]] * (1.0 + 0.0006 * np.sin(phase / 9.0))
    daily_range = 0.003 + 0.002 * (1.0 + np.cos(phase / 23.0))
    spy = _dated_panel(
        dates,
        open=open_,
        high=np.maximum(open_, close) * (1.0 + daily_range),
        low=np.minimum(open_, close) * (1.0 - daily_range),
        close=close,
        volume=1_000_000.0 * np.exp(0.2 * np.sin(phase / 29.0)),
    )
    vol = _dated_panel(
        dates,
        vix_close=20.0 + 4.0 * np.sin(phase / 31.0),
        vxo_close=19.0 + 3.0 * np.sin(phase / 31.0 + 0.2),
    )
    rate_level = 4.0 + 0.7 * np.sin(phase / 101.0)
    rates = _dated_panel(
        dates,
        yield_3m=rate_level - 0.4 + 0.1 * np.sin(phase / 19.0),
        yield_2y=rate_level - 0.2 + 0.15 * np.sin(phase / 29.0),
        yield_5y=rate_level + 0.1 + 0.2 * np.sin(phase / 37.0),
        yield_10y=rate_level + 0.3 + 0.25 * np.sin(phase / 43.0),
        yield_30y=rate_level + 0.5 + 0.3 * np.sin(phase / 53.0),
    )
    policy = _dated_panel(
        dates,
        effective_fed_funds=3.5 + 0.8 * np.sin(phase / 127.0),
    )
    calendar = _dated_panel(
        dates,
        is_standard_expiry=(phase.astype(int) % 21 == 20).astype(int),
        is_quarterly_expiry=(phase.astype(int) % 63 == 62).astype(int),
        sessions_until_standard_expiry=(20 - phase.astype(int) % 21),
    )
    cftc_dates = dates[4::5]
    cftc_phase = np.arange(len(cftc_dates), dtype=float)
    cftc = _dated_panel(
        cftc_dates,
        noncommercial_net_pct_oi=0.08 * np.sin(cftc_phase / 11.0),
        noncommercial_net_pct_oi_combined=0.11
        * np.sin(cftc_phase / 11.0 + 0.2),
        open_interest=1_000_000.0 * (1.0 + 0.001 * cftc_phase),
        open_interest_combined=1_200_000.0 * (1.0 + 0.001 * cftc_phase),
    )
    weekly_dates = dates[9::10]
    weekly_phase = np.arange(len(weekly_dates), dtype=float)
    liquidity = _dated_panel(
        weekly_dates,
        monetary_base=500.0
        * np.exp(0.004 * weekly_phase + 0.02 * np.sin(weekly_phase / 9.0)),
        total_reserves=60.0
        * np.exp(0.006 * weekly_phase + 0.08 * np.sin(weekly_phase / 7.0)),
        m2=4_000.0
        * np.exp(0.003 * weekly_phase + 0.01 * np.cos(weekly_phase / 13.0)),
    )
    credit_money = _dated_panel(
        weekly_dates,
        bank_credit=4_000.0
        * np.exp(0.003 * weekly_phase + 0.02 * np.sin(weekly_phase / 8.0)),
        loans_and_leases=3_000.0
        * np.exp(0.0035 * weekly_phase + 0.02 * np.cos(weekly_phase / 9.0)),
        m2=4_500.0
        * np.exp(0.0025 * weekly_phase + 0.01 * np.sin(weekly_phase / 11.0)),
        commercial_paper=900.0
        * np.exp(0.004 * weekly_phase + 0.04 * np.cos(weekly_phase / 6.0)),
    )
    release_dates = dates[20::21]
    release_phase = np.arange(len(release_dates), dtype=float)
    macro = _dated_panel(
        release_dates,
        payroll_first=150.0 + 60.0 * np.sin(release_phase / 5.0),
        industrial_production_first=2.0 + 1.5 * np.sin(release_phase / 7.0),
        housing_starts_first=1_500.0 + 120.0 * np.cos(release_phase / 8.0),
        output_first=3.0 + 1.2 * np.sin(release_phase / 9.0),
        consumption_first=2.5 + 0.9 * np.cos(release_phase / 10.0),
        cpi_first=2.0 + 0.5 * np.sin(release_phase / 11.0),
        core_cpi_first=2.1 + 0.4 * np.cos(release_phase / 12.0),
        core_pce_first=1.9 + 0.3 * np.sin(release_phase / 13.0),
    )
    fomc_dates = dates[40::42]
    fomc = _dated_panel(
        fomc_dates,
        meeting_count=np.ones(len(fomc_dates), dtype=int),
        statement_count=(np.arange(len(fomc_dates)) % 2).astype(int),
        conference_call=(np.arange(len(fomc_dates)) % 7 == 0).astype(int),
    )
    return {
        "spy": spy,
        "vol": vol,
        "cftc": cftc,
        "rates": rates,
        "policy": policy,
        "calendar": calendar,
        "liquidity": liquidity,
        "credit_money": credit_money,
        "macro": macro,
        "fomc": fomc,
    }


def _parameters(lane_id: str) -> dict[str, object]:
    if lane_id == "F091":
        return {"statistic": "convexity_interaction", "window": 40, "tail_quantile": 0.1}
    if lane_id == "F092":
        return {"statistic": "risk_compensation", "window": 40}
    if lane_id == "F093":
        return {"statistic": "insurance_interaction", "window": 40, "positioning_window": 13}
    if lane_id == "F094":
        return {"statistic": "expiry_pinning", "window": 40, "event_window": 5}
    if lane_id == "F095":
        return {"statistic": "divergence", "window": 40, "change_lag": 5}
    if lane_id == "F096":
        return {"statistic": "policy_adjusted", "window": 13, "growth_lag": 13}
    if lane_id == "F097":
        return {"statistic": "growth_breadth", "window": 13, "growth_lag": 13}
    if lane_id == "F098":
        return {"statistic": "surprise_breadth", "forecast_window": 6, "scale_window": 12}
    if lane_id == "F099":
        return {"statistic": "inflation_trend", "forecast_window": 6, "scale_window": 12}
    if lane_id == "F100":
        return {"statistic": "event_interaction", "normalization_window": 12, "inflation_target": 2.0}
    raise AssertionError(lane_id)


@pytest.mark.parametrize("lane_id", [f"F{index:03d}" for index in range(91, 101)])
def test_f091_f100_produce_finite_train_only_values(lane_id: str) -> None:
    api = _engine_api()

    result = api.evaluate_tail_macro_lane(lane_id, _panels(), _parameters(lane_id))

    assert result["value"].notna().any(), lane_id
    valid = result["value"].notna()
    assert result.loc[valid, "observed_at"].le(
        result.loc[valid, "available_at"]
    ).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane_id", [f"F{index:03d}" for index in range(91, 101)])
def test_f091_f100_are_stable_when_future_rows_are_appended(lane_id: str) -> None:
    api = _engine_api()
    panels = _panels()
    cutoff = panels["spy"].loc[999, "date"]
    before_panels = {
        name: panel.loc[panel["date"].le(cutoff)].copy()
        for name, panel in panels.items()
    }

    before = api.evaluate_tail_macro_lane(
        lane_id, before_panels, _parameters(lane_id)
    )
    after = api.evaluate_tail_macro_lane(lane_id, panels, _parameters(lane_id))

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True),
        after.loc[after["date"].le(cutoff)].reset_index(drop=True),
    )


@pytest.mark.parametrize(
    ("lane_id", "statistics"),
    [
        ("F091", ["vol_of_vol", "methodology_disagreement", "realized_tail", "convexity_interaction"]),
        ("F092", ["variance_premium", "continuous_premium", "jump_share", "risk_compensation"]),
        ("F093", ["implied_downside_gap", "positioning_pressure", "tail_realization", "insurance_interaction"]),
        ("F094", ["expiry_pinning", "convexity_pressure", "quarterly_pressure", "reversal_pressure"]),
        ("F095", ["rate_volatility", "volatility_ratio", "divergence", "shock"]),
        ("F096", ["net_liquidity", "reserve_impulse", "money_impulse", "policy_adjusted"]),
        ("F097", ["growth_breadth", "credit_impulse", "contraction_pressure", "money_credit_gap"]),
        ("F098", ["surprise_breadth", "surprise_magnitude", "growth_surprise", "dispersion"]),
        ("F099", ["inflation_level", "inflation_surprise", "inflation_trend", "inflation_acceleration"]),
        ("F100", ["policy_change", "real_rate", "rule_gap", "event_interaction"]),
    ],
)
def test_f091_f100_support_each_frozen_statistic(
    lane_id: str, statistics: list[str]
) -> None:
    api = _engine_api()
    for statistic in statistics:
        parameters = _parameters(lane_id)
        parameters["statistic"] = statistic

        result = api.evaluate_tail_macro_lane(lane_id, _panels(), parameters)

        assert result["value"].notna().any(), (lane_id, statistic)


def test_f092_daily_jump_proxy_is_nonnegative() -> None:
    api = _engine_api()

    result = api.evaluate_tail_macro_lane(
        "F092", _panels(), {"statistic": "jump_share", "window": 40}
    )

    assert result.loc[result["value"].notna(), "value"].between(0.0, 1.0).all()


def test_f100_outputs_only_public_policy_events() -> None:
    api = _engine_api()
    panels = _panels()

    result = api.evaluate_tail_macro_lane("F100", panels, _parameters("F100"))

    assert set(result["date"]) == set(panels["fomc"]["date"])


def test_tail_macro_engine_rejects_validation_rows() -> None:
    api = _engine_api()
    panels = _panels(40)
    panels["spy"].loc[
        panels["spy"].index[-1], ["date", "available_at"]
    ] = pd.Timestamp("2011-01-03")

    with pytest.raises(api.TailMacroFeatureEngineError, match="NON_TRAIN_PANEL_ROW:spy"):
        api.evaluate_tail_macro_lane("F091", panels, {"window": 20})


def test_tail_macro_batch_contains_exactly_f091_f100() -> None:
    api = _engine_api()

    outputs = api.evaluate_tail_macro_family_batch(_panels())

    assert tuple(outputs) == tuple(f"F{index:03d}" for index in range(91, 101))
    assert all(output["value"].notna().any() for output in outputs.values())
