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
            "aurora.infra.sp500_megarun.macro_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"macro feature engine is missing: {exc}")


def _f032_frozen_space() -> dict[str, list[object]]:
    path = Path(__file__).parents[1] / "config" / "sp500_megarun_feature_contract_240.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return next(
        row["parameter_space"]
        for row in payload["lanes"]
        if row["lane_id"] == "F032"
    )


def _credit_panel(periods: int = 500) -> pd.DataFrame:
    dates = pd.bdate_range("2009-01-02", periods=periods)
    phase = np.arange(periods, dtype=float)
    spread = 1.5 + 0.2 * np.sin(phase / 17.0) + 0.0002 * phase
    return pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "aaa_yield": 4.0 + 0.1 * np.sin(phase / 40.0),
            "baa_yield": 4.0 + 0.1 * np.sin(phase / 40.0) + spread,
            "baa_aaa_spread": spread,
        }
    )


def test_f032_is_trailing_credit_spread_change_acceleration() -> None:
    api = _engine_api()
    panel = _credit_panel(80)

    result = api.evaluate_macro_lane(
        "F032",
        {"credit": panel},
        {"window": 20, "change_lag": 5},
    )

    spread = panel["baa_aaa_spread"]
    change = spread.diff(5)
    acceleration = change.diff(5)
    raw = change + acceleration
    expected = (raw.iloc[-1] - raw.iloc[-20:].mean()) / raw.iloc[-20:].std(ddof=0)
    assert result.loc[79, "value"] == pytest.approx(expected)


def test_f032_is_causal_under_future_append() -> None:
    api = _engine_api()
    panel = _credit_panel(100)

    before = api.evaluate_macro_lane(
        "F032", {"credit": panel.iloc[:80]}, {"window": 20, "change_lag": 5}
    )
    after = api.evaluate_macro_lane(
        "F032", {"credit": panel}, {"window": 20, "change_lag": 5}
    ).iloc[:80]

    pd.testing.assert_frame_equal(before.reset_index(drop=True), after.reset_index(drop=True))


def test_f032_executes_every_frozen_parameter_choice() -> None:
    api = _engine_api()
    panel = _credit_panel(500)
    baseline: dict[str, object] = {"window": 63, "change_lag": 5}
    for name, choices in _f032_frozen_space().items():
        signatures: set[int] = set()
        for choice in choices:
            parameters = dict(baseline)
            parameters[name] = choice
            result = api.evaluate_macro_lane("F032", {"credit": panel}, parameters)
            assert result["value"].notna().any(), (name, choice)
            signatures.add(
                int(
                    pd.util.hash_pandas_object(
                        result["value"].round(12), index=False
                    ).sum()
                )
            )
        assert len(signatures) > 1, f"ignored frozen dimension: F032.{name}"


def test_macro_engine_rejects_validation_rows() -> None:
    api = _engine_api()
    panel = _credit_panel(20)
    panel.loc[len(panel)] = {
        "date": pd.Timestamp("2011-01-03"),
        "observed_at": pd.Timestamp("2010-12-31"),
        "available_at": pd.Timestamp("2011-01-03"),
        "aaa_yield": 4.0,
        "baa_yield": 5.5,
        "baa_aaa_spread": 1.5,
    }

    with pytest.raises(api.MacroFeatureEngineError, match="NON_TRAIN_PANEL_ROW:credit"):
        api.evaluate_macro_lane("F032", {"credit": panel}, {"window": 20})


def _decision_panel(dates: pd.DatetimeIndex, **columns: object) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
        }
    )
    for name, values in columns.items():
        frame[name] = values
    return frame


def _macro_panels(periods: int = 120) -> dict[str, pd.DataFrame]:
    dates = pd.bdate_range("2010-01-04", periods=periods)
    phase = np.arange(periods, dtype=float)
    financial = _decision_panel(
        dates,
        financial_conditions_score=np.sin(phase / 9.0),
        rate_level=2.0 + phase / 1000.0,
        volatility_level=20.0 + np.cos(phase / 7.0),
    )
    rates = _decision_panel(
        dates,
        yield_10y=3.0 + 0.2 * np.sin(phase / 13.0),
    )
    event_dates = dates[::5]
    event_phase = np.arange(len(event_dates), dtype=float)
    macro = _decision_panel(
        event_dates,
        cpi_first=2.0 + 0.1 * np.sin(event_phase / 3.0),
        output_first=2.0 + np.sin(event_phase / 4.0),
        consumption_first=2.5 + np.cos(event_phase / 5.0),
        payroll_first=100.0 + 5.0 * event_phase,
        payroll_revision=-10.0 + event_phase,
        industrial_production_first=1.0 + np.sin(event_phase / 2.0),
        housing_starts_first=800.0 + 10.0 * event_phase,
    )
    realtime_dates = dates[::10]
    realtime_phase = np.arange(len(realtime_dates), dtype=float)
    realtime = _decision_panel(
        realtime_dates,
        realtime_output_growth=2.0 + np.sin(realtime_phase / 2.0),
    )
    fomc_dates = dates[::20]
    fomc = _decision_panel(
        fomc_dates,
        fomc_event_count=np.ones(len(fomc_dates)),
    )
    valuation_dates = dates[::5]
    valuation_phase = np.arange(len(valuation_dates), dtype=float)
    valuation = _decision_panel(
        valuation_dates,
        dividend_yield=0.02 + valuation_phase / 10000.0,
        earnings_yield=0.04 + valuation_phase / 5000.0,
        book_to_market=0.4 + valuation_phase / 100.0,
        inverse_cape=0.05 + np.sin(valuation_phase / 4.0) / 100.0,
        net_equity_issuance=0.03 - valuation_phase / 1000.0,
        payout_ratio=0.4 + np.cos(valuation_phase / 5.0) / 20.0,
        aggregate_earnings=50.0 + valuation_phase**1.2,
    )
    calendar = _decision_panel(dates)
    return {
        "financial": financial,
        "rates": rates,
        "macro": macro,
        "realtime": realtime,
        "fomc": fomc,
        "calendar": calendar,
        "valuation": valuation,
    }


@pytest.mark.parametrize(
    "lane_id", ["F033", "F034", "F035", "F036", "F037", "F038", "F039", "F040"]
)
def test_f033_f040_produce_finite_causal_states(lane_id: str) -> None:
    api = _engine_api()
    result = api.evaluate_macro_lane(
        lane_id,
        _macro_panels(),
        {"window": 5, "change_lag": 2, "event_window": 5, "normalization_window": 10},
    )

    finite = result["value"].replace([np.inf, -np.inf], np.nan).dropna()
    assert not finite.empty
    assert result["date"].max() <= pd.Timestamp("2010-12-31")
    assert result.loc[finite.index, "observed_at"].le(
        result.loc[finite.index, "available_at"]
    ).all()


def test_f036_combines_payroll_level_and_known_revision() -> None:
    api = _engine_api()
    panels = _macro_panels()
    result = api.evaluate_macro_lane("F036", panels, {"window": 5})
    payroll = panels["macro"]["payroll_first"]
    revision = panels["macro"]["payroll_revision"]

    def rolling_z(values: pd.Series) -> pd.Series:
        return (values - values.rolling(5).mean()) / values.rolling(5).std(ddof=0)

    expected = rolling_z(payroll) + 0.5 * rolling_z(revision)
    assert result.iloc[-1]["value"] == pytest.approx(expected.iloc[-1])


def test_f033_is_stable_when_future_rows_are_appended() -> None:
    api = _engine_api()
    panels = _macro_panels()
    before_panels = {
        name: panel.loc[panel["date"].le(pd.Timestamp("2010-04-30"))].copy()
        for name, panel in panels.items()
    }
    before = api.evaluate_macro_lane(
        "F033", before_panels, {"window": 10, "change_lag": 2}
    )
    after = api.evaluate_macro_lane(
        "F033", panels, {"window": 10, "change_lag": 2}
    )
    after = after.loc[after["date"].le(pd.Timestamp("2010-04-30"))]

    pd.testing.assert_frame_equal(before.reset_index(drop=True), after.reset_index(drop=True))


def _cross_asset_panels(periods: int = 180) -> dict[str, pd.DataFrame]:
    dates = pd.bdate_range("2010-01-04", periods=periods)
    phase = np.arange(periods, dtype=float)
    market = _decision_panel(
        dates,
        close=100.0 * np.exp(np.cumsum(0.0004 + 0.002 * np.sin(phase / 11.0))),
    )
    rates = _decision_panel(
        dates,
        yield_10y=3.0 + 0.3 * np.sin(phase / 17.0),
    )
    fx = _decision_panel(
        dates,
        broad_dollar=100.0 + 0.03 * phase + np.sin(phase / 13.0),
        fx_cad=1.0 + 0.001 * np.sin(phase / 5.0),
        fx_jpy=100.0 + np.sin(phase / 7.0),
        fx_chf=1.1 + 0.002 * np.cos(phase / 8.0),
        fx_gbp=1.6 + 0.003 * np.sin(phase / 9.0),
    )
    commodities = _decision_panel(
        dates[::20],
        gold=1000.0 + 2.0 * np.arange(len(dates[::20])),
        oil=60.0 + np.sin(np.arange(len(dates[::20]), dtype=float)),
    )
    factors = _decision_panel(
        dates,
        market_excess=0.001 * np.sin(phase / 4.0),
        smb=0.001 * np.cos(phase / 5.0),
        hml=0.001 * np.sin(phase / 6.0),
    )
    industries = _decision_panel(
        dates,
        Autos=0.003 * np.sin(phase / 3.0),
        Cnstr=0.002 * np.cos(phase / 4.0),
        Food=0.001 * np.sin(phase / 5.0),
        Drugs=0.0015 * np.cos(phase / 7.0),
        Util=0.0008 * np.sin(phase / 8.0),
    )
    calendar = _decision_panel(
        dates,
        weekday=dates.weekday,
        month=dates.month,
        quarter=dates.quarter,
        session_of_month=pd.Series(dates).groupby([dates.year, dates.month]).cumcount().to_numpy() + 1,
        sessions_remaining_month=pd.Series(dates[::-1]).groupby(
            [dates[::-1].year, dates[::-1].month]
        ).cumcount().to_numpy()[::-1],
    )
    balance_dates = dates[::30]
    balance_phase = np.arange(len(balance_dates), dtype=float)
    balance = _decision_panel(
        balance_dates,
        household_equity_share=0.3 + balance_phase / 100.0,
        mutual_fund_equity_share=0.4 + np.sin(balance_phase) / 100.0,
    )
    margin_dates = dates[::20]
    margin_phase = np.arange(len(margin_dates), dtype=float)
    margin = _decision_panel(
        margin_dates,
        margin_debit=100.0 + margin_phase * 3.0,
        margin_credit=80.0 + margin_phase,
        margin_debit_to_credit=(100.0 + margin_phase * 3.0) / (80.0 + margin_phase),
    )
    positioning_dates = dates[::5]
    positioning_phase = np.arange(len(positioning_dates), dtype=float)
    positioning = _decision_panel(
        positioning_dates,
        open_interest=1000.0 + positioning_phase * 10.0,
        noncommercial_net_pct_oi=0.1 * np.sin(positioning_phase / 3.0),
        commercial_net_pct_oi=-0.08 * np.sin(positioning_phase / 3.0),
    )
    return {
        "market": market,
        "rates": rates,
        "fx": fx,
        "commodities": commodities,
        "factors": factors,
        "industries": industries,
        "calendar": calendar,
        "balance": balance,
        "margin": margin,
        "positioning": positioning,
    }


@pytest.mark.parametrize("lane_id", [f"F{index:03d}" for index in range(41, 51)])
def test_f041_f050_produce_causal_train_only_values(lane_id: str) -> None:
    api = _engine_api()
    panels = _cross_asset_panels()
    parameters = {
        "window": 20,
        "slow_window": 3,
        "margin_window": 4,
        "positioning_window": 8,
        "duration": 7,
        "threshold": 0.0,
        "calendar_rule": "turn_of_month",
        "hold": 3,
    }

    result = api.evaluate_macro_lane(lane_id, panels, parameters)

    assert result["value"].notna().any(), lane_id
    finite = result["value"].dropna()
    assert result.loc[finite.index, "observed_at"].le(
        result.loc[finite.index, "available_at"]
    ).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


def test_f042_is_stable_when_future_cross_asset_rows_are_appended() -> None:
    api = _engine_api()
    panels = _cross_asset_panels()
    cutoff = pd.Timestamp("2010-05-31")
    before_panels = {
        name: panel.loc[panel["date"].le(cutoff)].copy()
        for name, panel in panels.items()
    }
    parameters = {"window": 20, "duration": 7}

    before = api.evaluate_macro_lane("F042", before_panels, parameters)
    after = api.evaluate_macro_lane("F042", panels, parameters)
    after = after.loc[after["date"].le(cutoff)]

    pd.testing.assert_frame_equal(before.reset_index(drop=True), after.reset_index(drop=True))


def test_f050_supports_each_frozen_calendar_rule() -> None:
    api = _engine_api()
    panels = _cross_asset_panels()
    rules = {
        "turn_of_month",
        "month_end",
        "quarter_end",
        "weekday",
        "month",
        "sell_in_may",
    }

    for rule in rules:
        result = api.evaluate_macro_lane(
            "F050",
            panels,
            {
                "calendar_rule": rule,
                "hold": 3,
                "target_weekday": 0,
                "target_month": 1,
            },
        )
        assert result["value"].notna().all(), rule
