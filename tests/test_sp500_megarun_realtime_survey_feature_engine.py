from __future__ import annotations

import importlib
from typing import Mapping

import numpy as np
import pandas as pd
import pytest


def _api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.realtime_survey_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"realtime-survey feature engine is missing: {exc}")


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
    dates = pd.bdate_range("2003-01-02", "2010-12-31")
    phase = np.arange(len(dates), dtype=float)
    market = _timed(
        dates,
        {"close": 100.0 * np.exp(np.cumsum(0.0002 + 0.003 * np.sin(phase / 31.0)))},
    )
    quarterly_dates = dates[60::63]
    qp = np.arange(len(quarterly_dates), dtype=float)
    realtime = _timed(
        quarterly_dates,
        {
            "output_growth": 2.5 + 1.5 * np.sin(qp / 4.0),
            "gdi_growth": 2.2 + 1.3 * np.sin((qp + 1.0) / 4.5),
            "output_revision": 0.2 * np.sin(qp / 3.0),
            "gdi_revision": 0.25 * np.cos(qp / 3.5),
            "nominal_consumption_growth": 3.5 + np.sin(qp / 5.0),
            "nominal_disposable_income_growth": 3.7 + np.cos(qp / 5.5),
            "saving_rate": 5.0 + 0.7 * np.sin(qp / 6.0),
            "saving_rate_change": 0.15 * np.cos(qp / 4.0),
        },
    )
    monthly_dates = dates[20::21]
    mp = np.arange(len(monthly_dates), dtype=float)
    macro_release = _timed(
        monthly_dates,
        {
            "nonresidential_investment_first": 3.0 + 2.0 * np.sin(mp / 7.0),
            "nonresidential_investment_revision": 0.2 * np.cos(mp / 5.0),
            "residential_investment_first": 2.0 + 2.5 * np.sin((mp + 2.0) / 8.0),
            "residential_investment_revision": 0.25 * np.cos(mp / 6.0),
            "housing_starts_first": 1_400.0 + 180.0 * np.sin(mp / 9.0),
            "housing_starts_revision": 20.0 * np.cos(mp / 8.0),
            "cpi_first": 2.3 + 0.8 * np.sin(mp / 11.0),
            "cpi_revision": 0.05 * np.cos(mp / 8.0),
            "core_cpi_first": 2.1 + 0.5 * np.sin((mp + 1.0) / 12.0),
            "core_cpi_revision": 0.04 * np.cos(mp / 9.0),
            "core_pce_first": 1.9 + 0.4 * np.sin((mp + 2.0) / 13.0),
            "core_pce_revision": 0.03 * np.cos(mp / 10.0),
            "payroll_first": 150.0 + 80.0 * np.sin(mp / 6.0),
            "payroll_revision": 15.0 * np.cos(mp / 5.0),
            "industrial_production_first": 2.0 + 1.5 * np.sin(mp / 7.0),
            "industrial_production_revision": 0.2 * np.cos(mp / 6.0),
            "manufacturing_production_first": 1.8 + 1.7 * np.sin((mp + 1.0) / 7.5),
            "manufacturing_production_revision": 0.25 * np.cos(mp / 6.5),
            "capacity_utilization_first": 77.0 + 2.0 * np.sin(mp / 10.0),
            "capacity_utilization_revision": 0.1 * np.cos(mp / 8.0),
            "manufacturing_capacity_first": 75.0 + 2.2 * np.sin((mp + 1.0) / 10.5),
            "manufacturing_capacity_revision": 0.1 * np.cos(mp / 8.5),
        },
    )
    cycle = _timed(
        quarterly_dates,
        {
            "realtime_output_growth": 2.4 + np.sin(qp / 5.0),
            "realtime_unemployment": 5.5 + 0.8 * np.cos(qp / 7.0),
            "unemployment_change": 0.12 * np.sin(qp / 3.0),
        },
    )
    spf_central = _timed(
        quarterly_dates,
        {
            "target_period": quarterly_dates - pd.offsets.QuarterBegin(),
            "output_nowcast": 2.6 + np.sin(qp / 4.0),
            "output_next_forecast": 2.8 + np.cos(qp / 5.0),
            "output_prior_forecast": 2.7 + np.cos((qp - 1.0) / 5.0),
            "output_forecast_revision": 0.2 * np.sin(qp / 3.0),
            "unemployment_nowcast": 5.4 + 0.7 * np.cos(qp / 6.0),
            "cpi_nowcast": 2.2 + 0.5 * np.sin(qp / 7.0),
            "housing_nowcast": 3.0 + 1.5 * np.sin(qp / 5.5),
            "tbill_nowcast": 2.0 + 0.8 * np.cos(qp / 8.0),
        },
    )
    spf_disagreement = _timed(
        quarterly_dates,
        {
            "target_period": quarterly_dates - pd.offsets.QuarterBegin(),
            "ngdp_iqr": 0.5 + 0.2 * np.sin(qp / 4.0),
            "unemployment_iqr": 0.3 + 0.1 * np.cos(qp / 4.5),
            "cpi_iqr": 0.6 + 0.2 * np.sin(qp / 5.0),
            "housing_iqr": 0.12 + 0.04 * np.cos(qp / 5.5),
            "tbill_iqr": 0.4 + 0.15 * np.sin(qp / 6.0),
        },
    )
    error_dates = quarterly_dates[2:]
    ep = np.arange(len(error_dates), dtype=float)
    spf_error = _timed(
        error_dates,
        {
            "target_period": error_dates - pd.offsets.QuarterBegin(),
            "output_first": 2.5 + np.sin(ep / 4.0),
            "output_nowcast": 2.4 + np.sin((ep + 0.5) / 4.0),
            "output_prior_forecast": 2.3 + np.cos(ep / 5.0),
            "output_forecast_revision": 0.2 * np.sin(ep / 3.0),
            "nowcast_signed_error": 0.4 * np.sin(ep / 3.5),
            "nowcast_absolute_error": np.abs(0.4 * np.sin(ep / 3.5)),
            "prior_signed_error": 0.6 * np.cos(ep / 4.0),
            "prior_absolute_error": np.abs(0.6 * np.cos(ep / 4.0)),
        },
    )
    sloos = _timed(
        quarterly_dates,
        {
            "standards_large_mid": 10.0 + 15.0 * np.sin(qp / 5.0),
            "demand_large_mid": 5.0 + 20.0 * np.cos(qp / 6.0),
            "standards_small": 8.0 + 13.0 * np.sin((qp + 1.0) / 5.5),
            "demand_small": 4.0 + 18.0 * np.cos((qp + 1.0) / 6.5),
            "term_credit_line_cost": 6.0 + 10.0 * np.sin(qp / 7.0),
            "term_covenants": 7.0 + 9.0 * np.sin((qp + 1.0) / 7.5),
            "term_maximum_size": 5.0 + 8.0 * np.sin((qp + 2.0) / 8.0),
            "term_collateral": 4.0 + 7.0 * np.sin((qp + 3.0) / 8.5),
            "term_spreads": 9.0 + 11.0 * np.sin((qp + 4.0) / 9.0),
        },
    )
    return market, {
        "realtime": realtime,
        "macro_release": macro_release,
        "cycle": cycle,
        "spf_central": spf_central,
        "spf_disagreement": spf_disagreement,
        "spf_error": spf_error,
        "sloos": sloos,
    }


def _parameters(lane: str) -> dict[str, object]:
    defaults = {
        "F191": {"statistic": "average_growth", "window": 8},
        "F192": {"statistic": "household_breadth", "window": 8},
        "F193": {"statistic": "housing_investment_composite", "window": 24, "lag": 3},
        "F194": {"statistic": "inflation_breadth", "window": 24},
        "F195": {"statistic": "labor_composite", "window": 126},
        "F196": {"statistic": "production_breadth", "window": 24, "lag": 3},
        "F197": {"statistic": "macro_outlook_composite", "window": 8},
        "F198": {"statistic": "macro_disagreement", "window": 8},
        "F199": {"statistic": "rolling_absolute_error", "window": 8},
        "F200": {"statistic": "supply_demand_gap", "window": 8},
    }
    return {
        **defaults[lane],
        "normalization": "raw",
        "change_lag": 1,
        "direction": "continuation",
    }


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(191, 201)])
def test_f191_f200_produce_finite_train_only_values(lane: str) -> None:
    market, panels = _inputs()

    result = _api().evaluate_realtime_survey_lane(lane, market, panels, _parameters(lane))

    valid = result["value"].notna()
    assert valid.any(), lane
    assert result.loc[valid, "observed_at"].le(result.loc[valid, "available_at"]).all()
    assert result.loc[valid, "available_at"].le(result.loc[valid, "date"]).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(191, 201)])
def test_f191_f200_do_not_change_when_future_rows_are_appended(lane: str) -> None:
    api = _api()
    market, panels = _inputs()
    cutoff = market.loc[1300, "date"]
    before_market = market.loc[market["date"].le(cutoff)].copy()
    before_panels = {
        name: panel.loc[panel["date"].le(cutoff)].copy() for name, panel in panels.items()
    }

    before = api.evaluate_realtime_survey_lane(
        lane, before_market, before_panels, _parameters(lane)
    )
    after = api.evaluate_realtime_survey_lane(lane, market, panels, _parameters(lane))

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True),
        after.loc[after["date"].le(cutoff)].reset_index(drop=True),
    )


@pytest.mark.parametrize(
    ("lane", "variants"),
    [
        (
            "F191",
            (
                "output_growth",
                "gdi_growth",
                "average_growth",
                "growth_spread",
                "revision_breadth",
                "growth_breadth",
            ),
        ),
        (
            "F192",
            (
                "consumption_growth",
                "income_growth",
                "consumption_income_gap",
                "saving_rate",
                "saving_rate_change",
                "household_breadth",
            ),
        ),
        (
            "F193",
            (
                "nonresidential_investment",
                "residential_investment",
                "housing_starts",
                "housing_starts_change",
                "investment_breadth",
                "housing_investment_composite",
                "revision_composite",
            ),
        ),
        (
            "F194",
            (
                "headline_cpi",
                "core_cpi",
                "core_pce",
                "headline_core_gap",
                "inflation_breadth",
                "revision_pressure",
            ),
        ),
        (
            "F195",
            (
                "payroll_first",
                "payroll_revision",
                "unemployment_level",
                "unemployment_change",
                "labor_breadth",
                "labor_composite",
            ),
        ),
        (
            "F196",
            (
                "industrial_production",
                "manufacturing_production",
                "capacity_utilization",
                "manufacturing_capacity",
                "utilization_spread",
                "production_breadth",
                "production_capacity_composite",
                "revision_composite",
            ),
        ),
        (
            "F197",
            (
                "output_nowcast",
                "output_next_forecast",
                "unemployment_nowcast",
                "cpi_nowcast",
                "housing_nowcast",
                "tbill_nowcast",
                "macro_outlook_composite",
            ),
        ),
        (
            "F198",
            (
                "ngdp_iqr",
                "unemployment_iqr",
                "cpi_iqr",
                "housing_iqr",
                "tbill_iqr",
                "macro_disagreement",
                "disagreement_breadth",
            ),
        ),
        (
            "F199",
            (
                "forecast_revision",
                "nowcast_signed_error",
                "nowcast_absolute_error",
                "prior_signed_error",
                "prior_absolute_error",
                "rolling_bias",
                "rolling_absolute_error",
            ),
        ),
        (
            "F200",
            (
                "standards_large_mid",
                "demand_large_mid",
                "standards_small",
                "demand_small",
                "term_tightness",
                "supply_breadth",
                "demand_breadth",
                "supply_demand_gap",
                "composite_tightness",
            ),
        ),
    ],
)
def test_f191_f200_support_every_frozen_variant(lane: str, variants: tuple[str, ...]) -> None:
    api = _api()
    market, panels = _inputs()
    for variant in variants:
        parameters = _parameters(lane)
        parameters["statistic"] = variant
        result = api.evaluate_realtime_survey_lane(lane, market, panels, parameters)
        assert result["value"].notna().any(), (lane, variant)


def test_realtime_survey_engine_rejects_validation_rows() -> None:
    api = _api()
    market, panels = _inputs()
    market.loc[market.index[-1], ["date", "available_at"]] = pd.Timestamp("2011-01-03")

    with pytest.raises(api.RealtimeSurveyFeatureEngineError, match="NON_TRAIN_MARKET_ROW"):
        api.evaluate_realtime_survey_lane("F191", market, panels, _parameters("F191"))


def test_f194_uses_core_pce_revision_when_cpi_revisions_do_not_exist() -> None:
    api = _api()
    market, panels = _inputs()
    macro = panels["macro_release"].drop(
        columns=["cpi_revision", "core_cpi_revision"]
    )
    panels = {**panels, "macro_release": macro}

    default = api.evaluate_realtime_survey_lane(
        "F194", market, panels, _parameters("F194")
    )
    revision = api.evaluate_realtime_survey_lane(
        "F194",
        market,
        panels,
        {**_parameters("F194"), "statistic": "revision_pressure"},
    )

    assert default["value"].notna().any()
    assert revision["value"].notna().any()


def test_realtime_survey_batch_contains_exactly_f191_f200() -> None:
    market, panels = _inputs()

    outputs = _api().evaluate_realtime_survey_family_batch(market, panels)

    assert tuple(outputs) == tuple(f"F{i:03d}" for i in range(191, 201))
    assert all(output["value"].notna().any() for output in outputs.values())
