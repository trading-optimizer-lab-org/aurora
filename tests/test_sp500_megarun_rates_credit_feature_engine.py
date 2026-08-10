from __future__ import annotations

import importlib
from typing import Mapping

import numpy as np
import pandas as pd
import pytest


def _api():
    try:
        return importlib.import_module("aurora.infra.sp500_megarun.rates_credit_feature_engine")
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"rates-credit feature engine is missing: {exc}")


def _timed(dates: pd.DatetimeIndex, values: Mapping[str, object]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            **values,
        }
    )


def _inputs(periods: int = 1750) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    dates = pd.bdate_range("2004-01-02", periods=periods)
    phase = np.arange(periods, dtype=float)
    market = _timed(
        dates,
        {"close": 100.0 * np.exp(np.cumsum(0.0002 + 0.003 * np.sin(phase / 31.0)))},
    )
    rates = _timed(
        dates,
        {
            "yield_3m": 2.2 + 0.5 * np.sin(phase / 101.0),
            "yield_2y": 2.8 + 0.45 * np.sin(phase / 113.0),
            "yield_5y": 3.4 + 0.4 * np.sin(phase / 127.0),
            "yield_10y": 4.0 + 0.35 * np.sin(phase / 139.0),
            "yield_20y": 4.5 + 0.3 * np.sin(phase / 151.0),
        },
    )
    credit = _timed(
        dates,
        {
            "aaa_yield": 5.0 + 0.3 * np.sin(phase / 109.0),
            "baa_yield": 6.1 + 0.5 * np.sin((phase + 7.0) / 97.0),
            "baa_aaa_spread": 1.1 + 0.2 * np.sin(phase / 83.0),
        },
    )
    quarter_dates = dates[60::63]
    qp = np.arange(len(quarter_dates), dtype=float)
    spf = _timed(
        quarter_dates,
        {
            "real_rate_cpi": 1.4 + 0.4 * np.sin(qp / 5.0),
            "real_rate_pce": 1.6 + 0.35 * np.sin((qp + 1.0) / 5.5),
            "real_rate_pgdp": 1.5 + 0.3 * np.sin((qp + 2.0) / 6.0),
        },
    )
    cp = _timed(
        dates,
        {
            "aa_nonfinancial_90d": 3.4 + 0.4 * np.sin(phase / 73.0),
            "a2p2_nonfinancial_90d": 3.9 + 0.6 * np.sin((phase + 5.0) / 67.0),
            "aa_financial_90d": 3.6 + 0.45 * np.sin((phase + 3.0) / 71.0),
            "cp_outstanding": 900_000.0 * np.exp(0.00015 * phase + 0.02 * np.sin(phase / 91.0)),
            "issuance_amount": 50_000.0 + 8_000.0 * (1.0 + np.sin(phase / 17.0)),
        },
    )
    bank = _timed(
        dates,
        {
            "bank_credit": 3_000_000.0 * np.exp(0.00025 * phase),
            "securities": 800_000.0 * np.exp(0.00018 * phase),
            "loans": 2_200_000.0 * np.exp(0.00027 * phase),
            "ci_loans": 600_000.0 * np.exp(0.00022 * phase + 0.01 * np.sin(phase / 43.0)),
            "real_estate_loans": 900_000.0 * np.exp(0.00029 * phase),
            "consumer_loans": 350_000.0 * np.exp(0.0002 * phase + 0.01 * np.cos(phase / 47.0)),
        },
    )
    money = _timed(
        dates,
        {
            "m1": 1_100.0 * np.exp(0.00012 * phase),
            "m2": 4_000.0 * np.exp(0.00017 * phase),
            "monetary_base": 500_000.0 * np.exp(0.00015 * phase),
            "total_reserves": 45_000.0 * np.exp(0.0001 * phase + 0.02 * np.sin(phase / 79.0)),
            "fed_borrowings": 1_000.0 * np.exp(0.0002 * phase + 0.05 * np.sin(phase / 53.0)),
            "bank_credit": 3_000_000.0 * np.exp(0.00025 * phase),
        },
    )
    consumer = _timed(
        dates,
        {
            "consumer_total": 900_000.0 * np.exp(0.00018 * phase),
            "consumer_revolving": 300_000.0 * np.exp(0.0002 * phase + 0.01 * np.sin(phase / 61.0)),
            "consumer_nonrevolving": 600_000.0 * np.exp(0.00017 * phase),
        },
    )
    vol = _timed(
        dates,
        {
            "vix_close": 18.0 + 3.0 * np.sin(phase / 37.0),
            "vxo_close": 18.5 + 2.8 * np.sin(phase / 39.0),
        },
    )
    return market, {
        "rates": rates,
        "credit": credit,
        "spf_real_rate": spf,
        "cp": cp,
        "bank": bank,
        "money": money,
        "consumer": consumer,
        "vol": vol,
    }


def _parameters(lane: str) -> dict[str, object]:
    return {
        "F181": {
            "statistic": "slope_10y_3m",
            "window": 126,
            "normalization": "rolling_zscore",
            "direction": "continuation",
        },
        "F182": {
            "statistic": "forward_slope",
            "window": 126,
            "shock_lag": 20,
            "normalization": "rolling_zscore",
            "direction": "continuation",
        },
        "F183": {
            "statistic": "level",
            "inflation_basis": "pce",
            "window": 8,
            "direction": "continuation",
        },
        "F184": {
            "statistic": "baa_aaa",
            "window": 126,
            "normalization": "rolling_zscore",
            "direction": "continuation",
        },
        "F185": {
            "statistic": "quality_spread",
            "window": 126,
            "lag": 20,
            "normalization": "rolling_zscore",
            "direction": "continuation",
        },
        "F186": {
            "statistic": "credit_breadth",
            "window": 126,
            "lag": 63,
            "direction": "continuation",
        },
        "F187": {
            "statistic": "money_growth",
            "window": 126,
            "lag": 63,
            "direction": "continuation",
        },
        "F188": {
            "statistic": "revolving_share",
            "window": 126,
            "lag": 63,
            "direction": "continuation",
        },
        "F189": {
            "statistic": "composite",
            "window": 126,
            "change_lag": 20,
            "direction": "continuation",
        },
        "F190": {
            "statistic": "joint_mean",
            "window": 63,
            "shock_lag": 5,
            "threshold": 1.0,
            "direction": "continuation",
        },
    }[lane].copy()


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(181, 191)])
def test_f181_f190_produce_finite_train_only_values(lane: str) -> None:
    market, panels = _inputs()

    result = _api().evaluate_rates_credit_lane(lane, market, panels, _parameters(lane))

    valid = result["value"].notna()
    assert valid.any(), lane
    assert result.loc[valid, "observed_at"].le(result.loc[valid, "available_at"]).all()
    assert result.loc[valid, "available_at"].le(result.loc[valid, "date"]).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(181, 191)])
def test_f181_f190_do_not_change_when_future_rows_are_appended(lane: str) -> None:
    api = _api()
    market, panels = _inputs()
    cutoff = market.loc[1100, "date"]
    before_market = market.loc[market["date"].le(cutoff)].copy()
    before_panels = {
        name: panel.loc[panel["date"].le(cutoff)].copy() for name, panel in panels.items()
    }

    before = api.evaluate_rates_credit_lane(lane, before_market, before_panels, _parameters(lane))
    after = api.evaluate_rates_credit_lane(lane, market, panels, _parameters(lane))

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True),
        after.loc[after["date"].le(cutoff)].reset_index(drop=True),
    )


@pytest.mark.parametrize(
    ("lane", "parameter", "variants"),
    [
        (
            "F181",
            "statistic",
            ("level", "slope_10y_3m", "curvature_2_5_10", "long_curvature_5_10_20"),
        ),
        (
            "F182",
            "statistic",
            ("forward_2y5y", "forward_5y10y", "forward_slope", "butterfly", "slope_shock"),
        ),
        ("F183", "inflation_basis", ("cpi", "pce", "pgdp")),
        ("F183", "statistic", ("level", "change", "dispersion", "tightness")),
        (
            "F184",
            "statistic",
            ("baa_aaa", "aaa_treasury", "baa_treasury", "credit_stress_composite"),
        ),
        (
            "F185",
            "statistic",
            (
                "quality_spread",
                "financial_spread",
                "outstanding_contraction",
                "issuance_intensity",
                "spread_volume_composite",
            ),
        ),
        (
            "F186",
            "statistic",
            (
                "bank_credit_growth",
                "loan_growth",
                "loan_share",
                "credit_breadth",
                "composition_dispersion",
            ),
        ),
        (
            "F187",
            "statistic",
            (
                "money_growth",
                "liquid_share",
                "reserve_growth",
                "borrowing_pressure",
                "credit_money_ratio",
            ),
        ),
        (
            "F188",
            "statistic",
            (
                "total_growth",
                "revolving_growth",
                "revolving_share",
                "revolving_relative_growth",
                "consumer_credit_stress",
            ),
        ),
        ("F189", "statistic", ("composite", "breadth", "max_stress", "dispersion")),
        (
            "F190",
            "statistic",
            ("joint_mean", "joint_max", "shock_breadth", "triple_interaction", "persistence"),
        ),
    ],
)
def test_f181_f190_support_every_frozen_variant(
    lane: str, parameter: str, variants: tuple[object, ...]
) -> None:
    api = _api()
    market, panels = _inputs()
    for variant in variants:
        parameters = _parameters(lane)
        parameters[parameter] = variant
        result = api.evaluate_rates_credit_lane(lane, market, panels, parameters)
        assert result["value"].notna().any(), (lane, parameter, variant)


def test_rates_credit_engine_rejects_validation_rows() -> None:
    api = _api()
    market, panels = _inputs(120)
    market.loc[119, ["date", "available_at"]] = pd.Timestamp("2011-01-03")

    with pytest.raises(api.RatesCreditFeatureEngineError, match="NON_TRAIN_MARKET_ROW"):
        api.evaluate_rates_credit_lane("F181", market, panels, _parameters("F181"))


def test_rates_credit_batch_contains_exactly_f181_f190() -> None:
    market, panels = _inputs()

    outputs = _api().evaluate_rates_credit_family_batch(market, panels)

    assert tuple(outputs) == tuple(f"F{i:03d}" for i in range(181, 191))
    assert all(output["value"].notna().any() for output in outputs.values())


def test_f185_batch_default_uses_full_history_outstanding_contraction() -> None:
    api = _api()
    market, panels = _inputs()

    batch = api.evaluate_rates_credit_family_batch(market, panels)["F185"]
    explicit = api.evaluate_rates_credit_lane(
        "F185",
        market,
        panels,
        {
            "statistic": "outstanding_contraction",
            "window": 126,
            "lag": 20,
            "normalization": "raw",
            "direction": "continuation",
        },
    )

    pd.testing.assert_frame_equal(batch, explicit)
