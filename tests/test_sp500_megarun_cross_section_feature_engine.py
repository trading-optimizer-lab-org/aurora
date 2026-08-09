from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest


def _api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.cross_section_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover
        pytest.fail(f"cross-section feature engine is missing: {exc}")


def _panel(dates: pd.DatetimeIndex, **values: object) -> pd.DataFrame:
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
    returns = 0.0002 + 0.004 * np.sin(phase / 17.0) + 0.001 * np.cos(phase / 41.0)
    close = 100.0 * np.exp(np.cumsum(returns))
    spy = _panel(dates, close=close)
    names = [
        "Autos", "BldMt", "Cnstr", "Steel", "Mach", "Rtail",
        "Food", "Beer", "Smoke", "Hshld", "Drugs", "Util",
    ]
    industries = _panel(
        dates,
        **{
            name: 0.004 * np.sin(phase / (11.0 + index) + index / 5.0)
            + 0.001 * np.cos(phase / (29.0 + index))
            for index, name in enumerate(names)
        },
    )
    factors = _panel(
        dates,
        market_excess=0.004 * np.sin(phase / 19.0),
        smb=0.003 * np.cos(phase / 23.0),
        hml=0.0035 * np.sin(phase / 31.0 + 0.3),
    )
    rates = _panel(
        dates,
        yield_3m=3.5 + 0.5 * np.sin(phase / 101.0),
        yield_10y=4.2 + 0.6 * np.sin(phase / 113.0 + 0.2),
        aaa_yield=5.0 + 0.3 * np.sin(phase / 79.0),
        baa_yield=5.9 + 0.4 * np.sin(phase / 83.0 + 0.2),
        effective_fed_funds=3.3 + 0.7 * np.sin(phase / 127.0),
    )
    fx = _panel(
        dates,
        broad_dollar=100.0 * np.exp(0.0002 * phase + 0.02 * np.sin(phase / 37.0)),
        fx_cad=1.2 * np.exp(0.01 * np.sin(phase / 41.0)),
        fx_jpy=100.0 * np.exp(0.015 * np.cos(phase / 43.0)),
        fx_chf=1.1 * np.exp(0.012 * np.sin(phase / 47.0)),
        fx_gbp=1.6 * np.exp(0.014 * np.cos(phase / 53.0)),
    )
    financial = _panel(
        dates,
        financial_conditions_score=0.5 * np.sin(phase / 37.0),
    )
    vol = _panel(dates, vix_close=20.0 + 4.0 * np.sin(phase / 31.0))
    monthly = dates[20::21]
    monthly_phase = np.arange(len(monthly), dtype=float)
    macro = _panel(
        monthly,
        industrial_production_first=2.0 + np.sin(monthly_phase / 7.0),
        output_first=3.0 + np.cos(monthly_phase / 9.0),
        consumption_first=2.5 + 0.8 * np.sin(monthly_phase / 11.0),
    )
    valuation = _panel(
        monthly,
        aggregate_earnings=70.0
        * np.exp(0.008 * monthly_phase + 0.03 * np.sin(monthly_phase / 5.0)),
    )
    return {
        "spy": spy,
        "industries": industries,
        "factors": factors,
        "rates": rates,
        "fx": fx,
        "financial": financial,
        "vol": vol,
        "macro": macro,
        "valuation": valuation,
    }


def _parameters(lane: str) -> dict[str, object]:
    return {
        "F111": {"statistic": "cyclical_defensive_spread", "window": 40},
        "F112": {"statistic": "factor_rotation", "window": 40},
        "F113": {"statistic": "stock_bond_correlation", "window": 40, "momentum_lag": 10},
        "F114": {"statistic": "stress_composite", "window": 40},
        "F115": {"statistic": "dollar_momentum", "window": 40, "momentum_lag": 10},
        "F116": {"statistic": "common_share", "window": 40},
        "F117": {"statistic": "divergence", "window": 40, "change_lag": 10},
        "F118": {"statistic": "alignment", "window": 24, "growth_lag": 12},
        "F119": {"statistic": "mean_forecast", "window": 40},
        "F120": {"statistic": "neighbor_mean", "state_window": 40, "neighbors": 10, "features": 5, "embargo": 10, "horizon": 5},
    }[lane].copy()


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(111, 121)])
def test_f111_f120_produce_finite_train_only_values(lane: str) -> None:
    api = _api()
    result = api.evaluate_cross_section_lane(lane, _panels(), _parameters(lane))
    assert result["value"].notna().any(), lane
    valid = result["value"].notna()
    assert result.loc[valid, "observed_at"].le(result.loc[valid, "available_at"]).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(111, 121)])
def test_f111_f120_are_stable_when_future_rows_are_appended(lane: str) -> None:
    api = _api()
    panels = _panels()
    cutoff = pd.Timestamp("2007-12-31")
    before_panels = {name: panel.loc[panel["date"].le(cutoff)].copy() for name, panel in panels.items()}
    before = api.evaluate_cross_section_lane(lane, before_panels, _parameters(lane))
    after = api.evaluate_cross_section_lane(lane, panels, _parameters(lane))
    pd.testing.assert_frame_equal(
        before.reset_index(drop=True),
        after.loc[after["date"].le(cutoff)].reset_index(drop=True),
    )


@pytest.mark.parametrize(
    ("lane", "statistics"),
    [
        ("F111", ["cyclical_defensive_spread", "leadership_breadth", "rotation", "dispersion_gap"]),
        ("F112", ["size_leadership", "value_leadership", "factor_rotation", "market_confirmation"]),
        ("F113", ["stock_bond_correlation", "curve_momentum", "duration_momentum", "joint_shock"]),
        ("F114", ["credit_stress", "funding_stress", "policy_pressure", "stress_composite"]),
        ("F115", ["dollar_momentum", "safe_haven_rotation", "cyclical_rotation", "dispersion"]),
        ("F116", ["common_mode", "common_share", "average_correlation", "dispersion"]),
        ("F117", ["breadth", "acceleration", "divergence", "failure_pressure"]),
        ("F118", ["earnings_state", "industry_state", "alignment", "leadership_gap"]),
        ("F119", ["mean_forecast", "median_forecast", "consensus", "disagreement"]),
        ("F120", ["neighbor_mean", "neighbor_median", "up_probability", "neighbor_dispersion"]),
    ],
)
def test_f111_f120_support_each_frozen_statistic(lane: str, statistics: list[str]) -> None:
    api = _api()
    panels = _panels()
    for statistic in statistics:
        parameters = _parameters(lane)
        parameters["statistic"] = statistic
        result = api.evaluate_cross_section_lane(lane, panels, parameters)
        assert result["value"].notna().any(), (lane, statistic)


def test_cross_section_engine_rejects_validation_rows() -> None:
    api = _api()
    panels = _panels(100)
    panels["industries"].loc[99, ["date", "available_at"]] = pd.Timestamp("2011-01-03")
    with pytest.raises(api.CrossSectionFeatureEngineError, match="NON_TRAIN_PANEL_ROW:industries"):
        api.evaluate_cross_section_lane("F111", panels, {"window": 20})


def test_cross_section_batch_contains_exactly_f111_f120() -> None:
    api = _api()
    outputs = api.evaluate_cross_section_family_batch(_panels())
    assert tuple(outputs) == tuple(f"F{i:03d}" for i in range(111, 121))
    assert all(output["value"].notna().any() for output in outputs.values())
