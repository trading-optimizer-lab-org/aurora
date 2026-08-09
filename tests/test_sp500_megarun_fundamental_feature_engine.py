from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest


def _engine_api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.fundamental_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"fundamental feature engine is missing: {exc}")


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
    monthly_dates = dates[20::21]
    monthly_phase = np.arange(len(monthly_dates), dtype=float)
    weekly_dates = dates[9::10]
    weekly_phase = np.arange(len(weekly_dates), dtype=float)
    quarterly_dates = dates[40::42]
    quarterly_phase = np.arange(len(quarterly_dates), dtype=float)

    valuation = _dated_panel(
        monthly_dates,
        aggregate_earnings=70.0
        * np.exp(0.008 * monthly_phase + 0.03 * np.sin(monthly_phase / 5.0)),
        aggregate_dividends=30.0
        * np.exp(0.006 * monthly_phase + 0.02 * np.cos(monthly_phase / 6.0)),
        market_index=800.0
        * np.exp(0.009 * monthly_phase + 0.04 * np.sin(monthly_phase / 7.0)),
        earnings_yield=0.06 + 0.008 * np.sin(monthly_phase / 8.0),
        dividend_yield=0.025 + 0.004 * np.cos(monthly_phase / 9.0),
        payout_ratio=0.42 + 0.03 * np.sin(monthly_phase / 10.0),
        net_equity_issuance=0.02 * np.sin(monthly_phase / 11.0),
    )
    calendar = _dated_panel(
        dates,
        month=dates.month,
        quarter=dates.quarter,
        session_of_month=(pd.Series(dates).groupby(dates.to_period("M")).cumcount() + 1).to_numpy(),
    )
    issuance = _dated_panel(
        quarterly_dates,
        corporate_equity_net_issuance=120.0
        + 25.0 * np.sin(quarterly_phase / 4.0),
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
    financial = _dated_panel(
        dates,
        financial_conditions_score=0.5 * np.sin(phase / 37.0),
        rate_level=4.0 + 0.6 * np.cos(phase / 101.0),
        volatility_level=20.0 + 4.0 * np.sin(phase / 31.0),
    )
    credit = _dated_panel(
        dates,
        baa_aaa_spread=0.9 + 0.2 * np.sin(phase / 53.0),
    )
    uncertainty = _dated_panel(
        dates,
        uncertainty_score=0.3 + 0.15 * np.sin(phase / 47.0),
        volatility_level=20.0 + 4.0 * np.sin(phase / 31.0),
        absolute_rate_change=0.03 + 0.02 * np.abs(np.cos(phase / 29.0)),
    )
    cycle = _dated_panel(
        quarterly_dates,
        realtime_output_growth=2.5 + 1.2 * np.sin(quarterly_phase / 5.0),
        realtime_unemployment=5.2 + 0.8 * np.cos(quarterly_phase / 7.0),
        unemployment_change=0.15 * np.sin(quarterly_phase / 3.0),
    )
    rates = _dated_panel(
        dates,
        yield_3m=3.7 + 0.5 * np.sin(phase / 103.0),
        yield_2y=3.9 + 0.5 * np.sin(phase / 103.0 + 0.1),
        yield_10y=4.3 + 0.5 * np.sin(phase / 103.0 + 0.2),
    )
    macro = _dated_panel(
        monthly_dates,
        payroll_first=140.0 + 55.0 * np.sin(monthly_phase / 5.0),
        industrial_production_first=2.0 + 1.1 * np.sin(monthly_phase / 7.0),
        housing_starts_first=1_500.0 + 100.0 * np.cos(monthly_phase / 8.0),
        output_first=2.8 + 1.0 * np.sin(monthly_phase / 9.0),
        consumption_first=2.4 + 0.8 * np.cos(monthly_phase / 10.0),
    )
    balance = _dated_panel(
        quarterly_dates,
        household_equity_share=0.28 + 0.04 * np.sin(quarterly_phase / 6.0),
        mutual_fund_equity_share=0.55 + 0.05 * np.cos(quarterly_phase / 8.0),
    )
    cftc = _dated_panel(
        weekly_dates,
        noncommercial_net_pct_oi=0.08 * np.sin(weekly_phase / 11.0),
        noncommercial_net_pct_oi_combined=0.11
        * np.sin(weekly_phase / 11.0 + 0.2),
    )
    vol = _dated_panel(
        dates,
        vix_close=20.0 + 4.0 * np.sin(phase / 31.0),
        vxo_close=19.0 + 3.0 * np.sin(phase / 31.0 + 0.2),
    )
    commodities = _dated_panel(
        monthly_dates,
        oil=35.0 * np.exp(0.004 * monthly_phase + 0.08 * np.sin(monthly_phase / 5.0)),
        gold=350.0 * np.exp(0.003 * monthly_phase + 0.04 * np.cos(monthly_phase / 7.0)),
    )
    return {
        "valuation": valuation,
        "market_issuance": valuation.loc[
            :, ["date", "observed_at", "available_at", "net_equity_issuance"]
        ].copy(),
        "calendar": calendar,
        "issuance": issuance,
        "credit_money": credit_money,
        "financial": financial,
        "credit": credit,
        "uncertainty": uncertainty,
        "cycle": cycle,
        "rates": rates,
        "macro": macro,
        "balance": balance,
        "cftc": cftc,
        "vol": vol,
        "commodities": commodities,
    }


def _parameters(lane_id: str) -> dict[str, object]:
    parameters: dict[str, dict[str, object]] = {
        "F101": {"statistic": "news_seasonality", "window": 24, "seasonal_window": 3},
        "F102": {"statistic": "composite", "window": 24, "momentum_lag": 6},
        "F103": {"statistic": "decomposition", "window": 24, "growth_lag": 12},
        "F104": {"statistic": "agreement", "window": 12, "change_lag": 4},
        "F105": {"statistic": "balance_sheet_capacity", "window": 26, "growth_lag": 13},
        "F106": {"statistic": "stress_composite", "window": 63, "persistence_window": 20},
        "F107": {"statistic": "recession_pressure", "window": 12},
        "F108": {"statistic": "disagreement", "window": 12, "trend_window": 6},
        "F109": {"statistic": "sentiment_composite", "window": 12},
        "F110": {"statistic": "relative_momentum", "window": 24, "momentum_lag": 6},
    }
    return parameters[lane_id].copy()


@pytest.mark.parametrize("lane_id", [f"F{index:03d}" for index in range(101, 111)])
def test_f101_f110_produce_finite_train_only_values(lane_id: str) -> None:
    api = _engine_api()

    result = api.evaluate_fundamental_lane(lane_id, _panels(), _parameters(lane_id))

    assert result["value"].notna().any(), lane_id
    valid = result["value"].notna()
    assert result.loc[valid, "observed_at"].le(
        result.loc[valid, "available_at"]
    ).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane_id", [f"F{index:03d}" for index in range(101, 111)])
def test_f101_f110_are_stable_when_future_rows_are_appended(lane_id: str) -> None:
    api = _engine_api()
    panels = _panels()
    cutoff = pd.Timestamp("2007-12-31")
    before_panels = {
        name: panel.loc[panel["date"].le(cutoff)].copy()
        for name, panel in panels.items()
    }

    before = api.evaluate_fundamental_lane(
        lane_id, before_panels, _parameters(lane_id)
    )
    after = api.evaluate_fundamental_lane(lane_id, panels, _parameters(lane_id))

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True),
        after.loc[after["date"].le(cutoff)].reset_index(drop=True),
    )


@pytest.mark.parametrize(
    ("lane_id", "statistics"),
    [
        ("F101", ["news_seasonality", "earnings_news", "dividend_news", "quarterly_cycle"]),
        ("F102", ["earnings_momentum", "earnings_yield_change", "acceleration", "composite"]),
        ("F103", ["earnings_growth", "dividend_growth", "payout_change", "decomposition"]),
        ("F104", ["market_issuance", "z1_issuance", "agreement", "retirement_pressure"]),
        ("F105", ["balance_sheet_capacity", "credit_impulse", "funding_stress", "capacity_disagreement"]),
        ("F106", ["uncertainty_level", "stress_composite", "disagreement", "persistence"]),
        ("F107", ["recession_pressure", "growth_state", "labor_state", "curve_state"]),
        ("F108", ["expectation_proxy", "activity_state", "deterioration", "disagreement"]),
        ("F109", ["sentiment_composite", "allocation_state", "positioning_state", "disagreement"]),
        ("F110", ["oil_gold_ratio", "relative_momentum", "inflation_impulse", "shock_divergence"]),
    ],
)
def test_f101_f110_support_each_frozen_statistic(
    lane_id: str, statistics: list[str]
) -> None:
    api = _engine_api()
    panels = _panels()
    for statistic in statistics:
        parameters = _parameters(lane_id)
        parameters["statistic"] = statistic

        result = api.evaluate_fundamental_lane(lane_id, panels, parameters)

        assert result["value"].notna().any(), (lane_id, statistic)


def test_fundamental_engine_rejects_validation_rows() -> None:
    api = _engine_api()
    panels = _panels(100)
    panels["valuation"].loc[
        panels["valuation"].index[-1], ["date", "available_at"]
    ] = pd.Timestamp("2011-01-03")

    with pytest.raises(
        api.FundamentalFeatureEngineError,
        match="NON_TRAIN_PANEL_ROW:valuation",
    ):
        api.evaluate_fundamental_lane("F101", panels, {"window": 6})


def test_fundamental_batch_contains_exactly_f101_f110() -> None:
    api = _engine_api()

    outputs = api.evaluate_fundamental_family_batch(_panels())

    assert tuple(outputs) == tuple(f"F{index:03d}" for index in range(101, 111))
    assert all(output["value"].notna().any() for output in outputs.values())
