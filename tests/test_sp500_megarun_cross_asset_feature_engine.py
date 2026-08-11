from __future__ import annotations

import importlib
from typing import Mapping

import numpy as np
import pandas as pd
import pytest


def _api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.cross_asset_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"cross-asset feature engine is missing: {exc}")


def _timed(dates: pd.DatetimeIndex, values: Mapping[str, object]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            **values,
        }
    )


def _inputs(periods: int = 1500) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    dates = pd.bdate_range("2005-01-03", periods=periods)
    phase = np.arange(periods, dtype=float)
    close = 100.0 * np.exp(np.cumsum(0.0003 + 0.004 * np.sin(phase / 31.0)))
    market = _timed(dates, {"close": close})
    weekly = dates[4::5]
    wp = np.arange(len(weekly), dtype=float)
    fx_values: dict[str, object] = {
        "broad_dollar": 100.0 * np.exp(0.001 * wp + 0.03 * np.sin(wp / 13.0))
    }
    for offset, name in enumerate(
        ("cad", "jpy", "chf", "gbp", "aud", "nzd", "dkk", "nok", "sek"),
        start=1,
    ):
        fx_values[f"fx_{name}"] = np.exp(
            0.0005 * offset * wp + 0.02 * np.sin((wp + offset) / (7.0 + offset))
        )
    rates = _timed(
        dates,
        {
            "yield_3m": 2.5 + 0.6 * np.sin(phase / 127.0),
            "treasury_3m": 2.5 + 0.6 * np.sin(phase / 127.0),
            "eurodollar_3m": 2.8 + 0.7 * np.sin((phase + 9.0) / 131.0),
            "offshore_basis": 0.3 + 0.1 * np.sin(phase / 79.0),
            "yield_2y": 3.0 + 0.5 * np.sin(phase / 137.0),
            "yield_5y": 3.5 + 0.45 * np.sin(phase / 149.0),
            "yield_10y": 4.0 + 0.4 * np.sin(phase / 163.0),
            "yield_20y": 4.4 + 0.35 * np.sin(phase / 173.0),
        },
    )
    monthly = dates[20::21]
    mp = np.arange(len(monthly), dtype=float)
    commodity_values: dict[str, object] = {}
    names = (
        "crude_oil", "coal", "natural_gas", "aluminum", "copper", "lead",
        "tin", "nickel", "zinc", "gold", "platinum", "silver", "cocoa",
        "coffee_arabica", "coffee_robusta", "palm_oil", "soybeans", "maize",
        "rice", "wheat", "beef", "sugar", "cotton", "phosphate_rock",
        "dap", "urea", "potash",
    )
    for offset, name in enumerate(names, start=1):
        commodity_values[name] = 50.0 * np.exp(
            0.002 * offset * mp + 0.06 * np.sin((mp + offset) / (5.0 + offset / 5.0))
        )
    panels = {
        "fx": _timed(weekly, fx_values),
        "rates": rates,
        "commodities": _timed(monthly, commodity_values),
    }
    return market, panels


def _parameters(lane: str) -> dict[str, object]:
    return {
        "F171": {"window": 13, "statistic": "official_broad", "threshold": 0.5, "direction": "continuation"},
        "F172": {"window": 63, "long_window": 252, "statistic": "carry_pressure", "direction": "continuation"},
        "F173": {"window": 13, "skip": 1, "aggregation": "mean", "selection_fraction": 0.25, "direction": "continuation"},
        "F174": {"window": 12, "normalization_window": 36, "statistic": "momentum", "threshold": 0.5, "direction": "continuation"},
        "F175": {"window": 12, "statistic": "industrial_minus_precious", "direction": "continuation"},
        "F176": {"window": 12, "normalization_window": 36, "statistic": "breadth", "threshold": 0.5, "direction": "continuation"},
        "F177": {"window": 12, "statistic": "dispersion", "threshold": 0.5, "direction": "continuation"},
        "F178": {"window": 63, "normalization_window": 252, "statistic": "sign_breadth", "direction": "continuation"},
        "F179": {"window": 63, "maturity": "10y", "statistic": "total", "normalization": "raw", "z_window": 252, "direction": "continuation"},
        "F180": {"window": 63, "long_window": 252, "maturity": "10y", "statistic": "correlation", "direction": "continuation"},
    }[lane].copy()


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(171, 181)])
def test_f171_f180_produce_finite_train_only_values(lane: str) -> None:
    market, panels = _inputs()

    result = _api().evaluate_cross_asset_lane(lane, market, panels, _parameters(lane))

    valid = result["value"].notna()
    assert valid.any(), lane
    assert result.loc[valid, "observed_at"].le(result.loc[valid, "available_at"]).all()
    assert result.loc[valid, "available_at"].le(result.loc[valid, "date"]).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(171, 181)])
def test_f171_f180_do_not_change_when_future_rows_are_appended(lane: str) -> None:
    api = _api()
    market, panels = _inputs()
    cutoff = market.loc[999, "date"]
    before_market = market.loc[market["date"].le(cutoff)].copy()
    before_panels = {
        name: panel.loc[panel["date"].le(cutoff)].copy()
        for name, panel in panels.items()
    }

    before = api.evaluate_cross_asset_lane(lane, before_market, before_panels, _parameters(lane))
    after = api.evaluate_cross_asset_lane(lane, market, panels, _parameters(lane))

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True),
        after.loc[after["date"].le(cutoff)].reset_index(drop=True),
    )


@pytest.mark.parametrize(
    ("lane", "parameter", "variants"),
    [
        ("F171", "statistic", ("official_broad", "cross_mean", "breadth", "divergence", "dispersion")),
        ("F172", "statistic", ("cash_level", "offshore_basis", "carry_pressure", "fx_adjusted_pressure")),
        ("F173", "aggregation", ("mean", "median", "breadth", "rank")),
        ("F174", "statistic", ("level", "momentum", "breadth")),
        ("F175", "statistic", ("industrial_momentum", "precious_momentum", "industrial_minus_precious", "breadth", "dispersion")),
        ("F176", "statistic", ("level", "momentum", "breadth")),
        ("F177", "statistic", ("breadth", "dispersion", "inflation_pressure", "concentration")),
        ("F178", "statistic", ("sign_breadth", "volatility_scaled_mean", "dispersion", "stock_minus_defensive")),
        ("F179", "statistic", ("carry", "roll", "momentum", "total")),
        ("F179", "normalization", ("raw", "rolling_zscore")),
        ("F180", "statistic", ("correlation", "decoupling", "sign_change", "beta")),
    ],
)
def test_f171_f180_support_every_frozen_variant(
    lane: str, parameter: str, variants: tuple[object, ...]
) -> None:
    api = _api()
    market, panels = _inputs()
    for variant in variants:
        parameters = _parameters(lane)
        parameters[parameter] = variant
        result = api.evaluate_cross_asset_lane(lane, market, panels, parameters)
        assert result["value"].notna().any(), (lane, parameter, variant)


def test_f172_is_usd_funding_proxy_not_foreign_rate_differential() -> None:
    market, panels = _inputs()
    result = _api().evaluate_cross_asset_lane(
        "F172", market, panels, _parameters("F172")
    )

    assert result["value"].notna().any()
    assert "foreign_rate" not in panels["rates"]


def test_cross_asset_engine_rejects_validation_rows() -> None:
    api = _api()
    market, panels = _inputs(120)
    market.loc[119, ["date", "available_at"]] = pd.Timestamp("2011-01-03")

    with pytest.raises(api.CrossAssetFeatureEngineError, match="NON_TRAIN_MARKET_ROW"):
        api.evaluate_cross_asset_lane("F171", market, panels, _parameters("F171"))


def test_cross_asset_batch_contains_exactly_f171_f180() -> None:
    market, panels = _inputs()

    outputs = _api().evaluate_cross_asset_family_batch(market, panels)

    assert tuple(outputs) == tuple(f"F{i:03d}" for i in range(171, 181))
    assert all(output["value"].notna().any() for output in outputs.values())
