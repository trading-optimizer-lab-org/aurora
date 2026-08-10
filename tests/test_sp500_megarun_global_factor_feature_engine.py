from __future__ import annotations

import importlib
from typing import Mapping

import numpy as np
import pandas as pd
import pytest


def _api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.global_factor_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"global factor feature engine is missing: {exc}")


def _timed(dates: pd.DatetimeIndex, values: Mapping[str, object]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            **values,
        }
    )


def _inputs(
    periods: int = 900,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    dates = pd.bdate_range("2007-01-02", periods=periods)
    phase = np.arange(periods, dtype=float)
    market = _timed(dates, {})
    industries = {
        f"Industry{index:02d}": (
            0.00015 * (index - 7)
            + 0.003 * np.sin(phase / (7.0 + index / 3.0))
            + 0.0015 * np.cos((phase + index) / 19.0)
        )
        for index in range(16)
    }
    us_factors = {
        "market_excess": 0.0004 + 0.004 * np.sin(phase / 17.0),
        "smb": 0.0001 + 0.003 * np.cos(phase / 23.0),
        "hml": -0.0001 + 0.0025 * np.sin((phase + 7.0) / 29.0),
    }
    panels: dict[str, pd.DataFrame] = {
        "industries": _timed(dates, industries),
        "us_factors": _timed(dates, us_factors),
    }
    factor_resources = (
        "developed_five_factors",
        "developed_ex_us",
        "europe",
        "japan",
        "asia_pacific_ex_japan",
    )
    for offset, resource_id in enumerate(factor_resources, start=1):
        panels[resource_id] = _timed(
            dates,
            {
                "market_excess": 0.00015 * offset
                + 0.0035 * np.sin((phase + offset) / (13.0 + offset)),
                "size": 0.00008 * offset
                + 0.0028 * np.cos((phase + offset) / (17.0 + offset)),
                "value": -0.00004 * offset
                + 0.0024 * np.sin((phase + 3.0 * offset) / (23.0 + offset)),
                "profitability": 0.00006 * offset
                + 0.0021 * np.cos((phase + 5.0 * offset) / (29.0 + offset)),
                "investment": 0.00003 * offset
                + 0.0019 * np.sin((phase + 2.0 * offset) / (31.0 + offset)),
            },
        )
    momentum_resources = (
        "developed_momentum",
        "developed_ex_us_momentum",
        "europe_momentum",
        "japan_momentum",
        "asia_pacific_ex_japan_momentum",
    )
    for offset, resource_id in enumerate(momentum_resources, start=1):
        panels[resource_id] = _timed(
            dates,
            {
                "momentum": 0.00012 * offset
                + 0.003 * np.cos((phase + 4.0 * offset) / (15.0 + offset))
            },
        )
    return market, panels


def _parameters(lane: str) -> dict[str, object]:
    parameters: dict[str, object] = {
        "window": 20,
        "direction": "continuation",
    }
    if lane in {"F161", "F170"}:
        parameters.update(threshold=0.5, mode="level", change_lag=5)
    elif lane in {"F162", "F169"}:
        parameters.update(
            skip=5,
            aggregation="mean",
            selection_fraction=0.25,
            universe="regions_only",
        )
    elif lane == "F163":
        parameters["statistic"] = "std"
    elif lane == "F164":
        parameters["component"] = "equal_weight"
    elif lane == "F165":
        parameters.update(statistic="dispersion", short_window=5)
    elif lane == "F166":
        parameters["component"] = "equal_weight"
    elif lane == "F167":
        parameters["aggregation"] = "spread"
    elif lane == "F168":
        parameters.update(component="equal_weight", weighting="equal")
    return parameters


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(161, 171)])
def test_f161_f170_produce_finite_train_only_values(lane: str) -> None:
    market, panels = _inputs()

    result = _api().evaluate_global_factor_lane(
        lane, market, panels, _parameters(lane)
    )

    valid = result["value"].notna()
    assert valid.any(), lane
    assert result.loc[valid, "observed_at"].le(
        result.loc[valid, "available_at"]
    ).all()
    assert result.loc[valid, "available_at"].le(result.loc[valid, "date"]).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(161, 171)])
def test_f161_f170_do_not_change_when_future_rows_are_appended(lane: str) -> None:
    api = _api()
    market, panels = _inputs()
    cutoff = market.loc[699, "date"]
    prior_market = market.loc[market["date"].le(cutoff)].copy()
    prior_panels = {
        name: panel.loc[panel["date"].le(cutoff)].copy()
        for name, panel in panels.items()
    }

    before = api.evaluate_global_factor_lane(
        lane, prior_market, prior_panels, _parameters(lane)
    )
    after = api.evaluate_global_factor_lane(lane, market, panels, _parameters(lane))

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True),
        after.loc[after["date"].le(cutoff)].reset_index(drop=True),
    )


@pytest.mark.parametrize(
    ("lane", "parameter", "variants"),
    [
        ("F161", "mode", ("level", "change", "divergence")),
        ("F162", "aggregation", ("mean", "median", "breadth", "rank")),
        ("F162", "direction", ("continuation", "reversal")),
        ("F163", "statistic", ("std", "iqr", "mad", "hhi", "mean_correlation")),
        ("F164", "component", ("market_excess", "size", "value", "equal_weight", "breadth")),
        ("F165", "statistic", ("dispersion", "sign_disagreement", "regime_change", "mean_correlation")),
        ("F166", "component", ("market_excess", "size", "value", "equal_weight", "breadth")),
        ("F167", "aggregation", ("spread", "breadth", "rank", "weighted_vote")),
        ("F168", "component", ("equal_weight", "size_value", "quality_investment", "quality_minus_speculation")),
        ("F168", "weighting", ("equal", "inverse_vol", "sign_vote")),
        ("F169", "aggregation", ("mean", "median", "breadth", "rank")),
        ("F169", "universe", ("regions_only", "developed_ex_us_plus_regions", "all_available")),
        ("F170", "mode", ("level", "change", "divergence")),
        ("F170", "universe", ("regions_only", "developed_ex_us_plus_regions", "all_available")),
    ],
)
def test_f161_f170_support_every_frozen_variant(
    lane: str, parameter: str, variants: tuple[object, ...]
) -> None:
    api = _api()
    market, panels = _inputs()
    for variant in variants:
        parameters = _parameters(lane)
        parameters[parameter] = variant
        result = api.evaluate_global_factor_lane(lane, market, panels, parameters)
        assert result["value"].notna().any(), (lane, parameter, variant)


@pytest.mark.parametrize("lane", ("F162", "F163", "F166", "F167", "F169"))
def test_direction_reversal_is_exact_negative(lane: str) -> None:
    api = _api()
    market, panels = _inputs(300)
    continuation = _parameters(lane)
    reversal = dict(continuation, direction="reversal")

    left = api.evaluate_global_factor_lane(lane, market, panels, continuation)
    right = api.evaluate_global_factor_lane(lane, market, panels, reversal)

    np.testing.assert_allclose(
        left["value"].to_numpy(),
        -right["value"].to_numpy(),
        equal_nan=True,
    )


def test_f161_level_matches_frozen_industry_breadth_formula() -> None:
    market, panels = _inputs(80)
    parameters = dict(_parameters("F161"), window=10, threshold=0.6)

    result = _api().evaluate_global_factor_lane(
        "F161", market, panels, parameters
    )

    industries = panels["industries"].filter(like="Industry")
    trailing = np.log1p(industries).rolling(10, min_periods=10).sum()
    expected = pd.to_numeric(
        trailing.gt(0.0).where(trailing.notna()).mean(axis=1) - 0.6
    )
    pd.testing.assert_series_equal(result["value"], expected, check_names=False)


def test_global_factor_engine_rejects_validation_rows() -> None:
    api = _api()
    market, panels = _inputs(120)
    market.loc[119, ["date", "available_at"]] = pd.Timestamp("2011-01-03")

    with pytest.raises(
        api.GlobalFactorFeatureEngineError,
        match="NON_TRAIN_MARKET_ROW",
    ):
        api.evaluate_global_factor_lane(
            "F161", market, panels, _parameters("F161")
        )


def test_global_factor_engine_rejects_missing_physical_panel() -> None:
    api = _api()
    market, panels = _inputs(120)
    del panels["japan_momentum"]

    with pytest.raises(
        api.GlobalFactorFeatureEngineError,
        match="MISSING_GLOBAL_FACTOR_PANEL:F169:japan_momentum",
    ):
        api.evaluate_global_factor_lane(
            "F169", market, panels, _parameters("F169")
        )


def test_global_factor_batch_contains_exactly_f161_f170() -> None:
    market, panels = _inputs()

    outputs = _api().evaluate_global_factor_family_batch(market, panels)

    assert tuple(outputs) == tuple(f"F{i:03d}" for i in range(161, 171))
    assert all(output["value"].notna().any() for output in outputs.values())
