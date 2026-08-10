from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest


def _api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.characteristic_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"characteristic feature engine is missing: {exc}")


def _standard_panel(
    dates: pd.DatetimeIndex,
    phase: np.ndarray,
    *,
    positive_high: bool,
) -> pd.DataFrame:
    direction = 1.0 if positive_high else -1.0
    base = 0.001 * np.sin(phase / 11.0)
    premium = 0.002 + 0.001 * np.cos(phase / 17.0)
    low = base - direction * premium
    high = base + direction * premium
    return pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "Lo 30": low * 0.8,
            "Med 40": base,
            "Hi 30": high * 0.8,
            "Lo 20": low * 0.9,
            "Qnt 2": low * 0.4,
            "Qnt 3": base,
            "Qnt 4": high * 0.4,
            "Hi 20": high * 0.9,
            "Lo 10": low,
            "Dec 2": low * 0.7,
            "Dec 3": low * 0.5,
            "Dec 4": low * 0.2,
            "Dec 5": base,
            "Dec 6": base,
            "Dec 7": high * 0.2,
            "Dec 8": high * 0.5,
            "Dec 9": high * 0.7,
            "Hi 10": high,
        }
    )


def _prior_panel(
    dates: pd.DatetimeIndex,
    phase: np.ndarray,
    *,
    winners_positive: bool,
) -> pd.DataFrame:
    direction = 1.0 if winners_positive else -1.0
    base = 0.001 * np.sin(phase / 13.0)
    premium = 0.002 + 0.001 * np.cos(phase / 19.0)
    loser = base - direction * premium
    winner = base + direction * premium
    data: dict[str, object] = {
        "date": dates,
        "observed_at": dates - pd.offsets.BDay(1),
        "available_at": dates,
        "Lo PRIOR": loser,
    }
    for index in range(2, 10):
        weight = (index - 1) / 9.0
        data[f"PRIOR {index}"] = loser * (1.0 - weight) + winner * weight
    data["Hi PRIOR"] = winner
    return pd.DataFrame(data)


def _inputs(periods: int = 900) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    dates = pd.bdate_range("2007-01-02", periods=periods)
    phase = np.arange(periods, dtype=float)
    market = pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
        }
    )
    panels = {
        "size_daily": _standard_panel(dates, phase, positive_high=False),
        "book_to_market_daily": _standard_panel(dates, phase, positive_high=True),
        "profitability_daily": _standard_panel(dates, phase, positive_high=True),
        "investment_daily": _standard_panel(dates, phase, positive_high=False),
        "momentum_10_daily": _prior_panel(dates, phase, winners_positive=True),
        "short_reversal_10_daily": _prior_panel(
            dates, phase, winners_positive=False
        ),
        "long_reversal_10_daily": _prior_panel(
            dates, phase, winners_positive=False
        ),
    }
    monthly_indexes = np.arange(20, periods, 21)
    monthly_dates = dates.take(monthly_indexes)
    monthly_phase = phase[monthly_indexes]
    panels.update(
        {
            "beta_monthly": _standard_panel(
                monthly_dates, monthly_phase, positive_high=True
            ),
            "variance_monthly": _standard_panel(
                monthly_dates, monthly_phase, positive_high=True
            ),
            "residual_variance_monthly": _standard_panel(
                monthly_dates, monthly_phase + 3.0, positive_high=True
            ),
            "accruals_monthly": _standard_panel(
                monthly_dates, monthly_phase, positive_high=False
            ),
            "net_share_issues_monthly": _standard_panel(
                monthly_dates, monthly_phase + 5.0, positive_high=False
            ),
        }
    )
    return market, panels


def _parameters(lane: str) -> dict[str, object]:
    common: dict[str, object] = {
        "statistic": "t_stat",
        "window": 21,
        "bins": 10,
    }
    if lane == "F158":
        common["window"] = 12
    elif lane == "F159":
        common.update(window=12, component="mean")
    elif lane == "F160":
        common.update(window=12, component="mean")
    return common


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(151, 161)])
def test_f151_f160_produce_finite_train_only_values(lane: str) -> None:
    market, panels = _inputs()

    result = _api().evaluate_characteristic_lane(
        lane, market, panels, _parameters(lane)
    )

    valid = result["value"].notna()
    assert valid.any(), lane
    assert result.loc[valid, "observed_at"].le(result.loc[valid, "available_at"]).all()
    assert result.loc[valid, "available_at"].le(result.loc[valid, "date"]).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(151, 161)])
def test_f151_f160_do_not_change_when_future_rows_are_appended(lane: str) -> None:
    api = _api()
    market, panels = _inputs()
    cutoff = market.loc[699, "date"]
    prior_market = market.loc[market["date"].le(cutoff)].copy()
    prior_panels = {
        name: panel.loc[panel["date"].le(cutoff)].copy()
        for name, panel in panels.items()
    }

    before = api.evaluate_characteristic_lane(
        lane, prior_market, prior_panels, _parameters(lane)
    )
    after = api.evaluate_characteristic_lane(
        lane, market, panels, _parameters(lane)
    )

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True),
        after.loc[after["date"].le(cutoff)].reset_index(drop=True),
    )


@pytest.mark.parametrize(
    ("lane", "parameter", "variants"),
    [
        ("F151", "bins", (3, 5, 10)),
        (
            "F152",
            "statistic",
            ("mean_spread", "t_stat", "cumulative_log_spread", "win_rate"),
        ),
        ("F153", "bins", (3, 5, 10)),
        ("F154", "bins", (3, 5, 10)),
        (
            "F155",
            "statistic",
            ("mean_spread", "t_stat", "cumulative_log_spread", "win_rate"),
        ),
        (
            "F156",
            "statistic",
            ("mean_spread", "t_stat", "cumulative_log_spread", "win_rate"),
        ),
        (
            "F157",
            "statistic",
            ("mean_spread", "t_stat", "cumulative_log_spread", "win_rate"),
        ),
        ("F158", "bins", (5, 10)),
        ("F159", "component", ("total", "residual", "mean", "disagreement")),
        (
            "F160",
            "component",
            ("accruals", "net_share_issues", "mean", "disagreement"),
        ),
    ],
)
def test_f151_f160_support_every_frozen_variant(
    lane: str, parameter: str, variants: tuple[object, ...]
) -> None:
    api = _api()
    market, panels = _inputs()
    for variant in variants:
        parameters = _parameters(lane)
        parameters[parameter] = variant
        result = api.evaluate_characteristic_lane(lane, market, panels, parameters)
        assert result["value"].notna().any(), (lane, parameter, variant)


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(151, 161)])
def test_f151_f160_frozen_long_short_orientation_is_positive(lane: str) -> None:
    market, panels = _inputs(180)
    parameters = _parameters(lane)
    parameters["statistic"] = "mean_spread"
    parameters["window"] = 3

    result = _api().evaluate_characteristic_lane(lane, market, panels, parameters)

    assert result["value"].dropna().median() > 0.0, lane


def test_characteristic_engine_rejects_a_panel_available_after_decision() -> None:
    api = _api()
    market, panels = _inputs(120)
    panels["size_daily"].loc[50, "available_at"] += pd.offsets.BDay(1)

    with pytest.raises(
        api.CharacteristicFeatureEngineError,
        match="AVAILABLE_AFTER_PANEL_DATE:size_daily",
    ):
        api.evaluate_characteristic_lane(
            "F151", market, panels, _parameters("F151")
        )


def test_characteristic_engine_rejects_validation_rows() -> None:
    api = _api()
    market, panels = _inputs(120)
    market.loc[119, ["date", "available_at"]] = pd.Timestamp("2011-01-03")

    with pytest.raises(
        api.CharacteristicFeatureEngineError,
        match="NON_TRAIN_MARKET_ROW",
    ):
        api.evaluate_characteristic_lane(
            "F151", market, panels, _parameters("F151")
        )


def test_characteristic_batch_contains_exactly_f151_f160() -> None:
    market, panels = _inputs()

    outputs = _api().evaluate_characteristic_family_batch(market, panels)

    assert tuple(outputs) == tuple(f"F{i:03d}" for i in range(151, 161))
    assert all(output["value"].notna().any() for output in outputs.values())
