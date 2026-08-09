from __future__ import annotations

import importlib

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
