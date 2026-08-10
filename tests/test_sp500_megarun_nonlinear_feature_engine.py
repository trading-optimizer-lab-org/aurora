from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest


def _api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.nonlinear_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"nonlinear feature engine is missing: {exc}")


def _panels(periods: int = 900) -> dict[str, pd.DataFrame]:
    dates = pd.bdate_range("2006-01-03", periods=periods)
    phase = np.arange(periods, dtype=float)
    log_return = (
        0.00025
        + 0.005 * np.sin(phase / 13.0)
        + 0.002 * np.cos(phase / 37.0)
        + 0.001 * np.sin(phase / 3.0)
    )
    close = 100.0 * np.exp(np.cumsum(log_return))
    prior = np.r_[close[0], close[:-1]]
    open_ = prior * np.exp(0.001 * np.sin(phase / 9.0))
    high = np.maximum(open_, close) * (1.005 + 0.001 * np.sin(phase / 7.0) ** 2)
    low = np.minimum(open_, close) * (0.995 - 0.001 * np.cos(phase / 11.0) ** 2)
    spy = pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1_000_000.0 * (1.2 + 0.2 * np.sin(phase / 17.0)),
        }
    )
    calendar = pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates,
            "available_at": dates,
            "weekday": dates.weekday,
            "month": dates.month,
            "session_of_month": pd.Series(dates, index=dates).groupby(
                [dates.year, dates.month]
            ).cumcount().to_numpy()
            + 1,
        }
    )
    calendar["sessions_remaining_month"] = (
        calendar.groupby([calendar["date"].dt.year, calendar["date"].dt.month])[
            "date"
        ].transform("size")
        - calendar["session_of_month"]
    )
    return {"spy": spy, "calendar": calendar}


def _parameters(lane: str) -> dict[str, object]:
    return {
        "F131": {"statistic": "energy_entropy", "kind": "haar", "scales": 3, "window": 63},
        "F132": {"statistic": "oscillation_share", "kind": "emd", "window": 63, "components": 2, "sift_iterations": 3, "ensembles": 4, "noise_scale": 0.05},
        "F133": {"statistic": "trend_component", "window": 63, "embedding": 10, "components": 3},
        "F134": {"statistic": "combined", "window": 252, "trend_window": 63, "min_occurrences": 3},
        "F135": {"statistic": "motif_follow_through", "window": 126, "subsequence": 10, "exclusion": 10, "neighbors": 5, "radius": 1.0, "normalization": "z"},
        "F136": {"statistic": "determinism", "window": 63, "embedding": 3, "delay": 1, "radius": 1.0, "minimum_line": 2},
        "F137": {"statistic": "hurst", "window": 126, "q_low": 0.5, "q_high": 2.0, "direction": "continuation"},
        "F138": {"statistic": "tail_magnitude", "window": 126, "tail": 0.05, "direction": "reversal"},
        "F139": {"statistic": "variance_gap", "kind": "asymmetric_ewma", "window": 63, "shock_decay": 0.94, "asymmetry": 1.0},
        "F140": {"statistic": "forecast", "kind": "setar", "window": 126, "threshold_quantile": 0.5, "regimes": 2, "lag": 1},
    }[lane].copy()


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(131, 141)])
def test_f131_f140_produce_finite_train_only_values(lane: str) -> None:
    result = _api().evaluate_nonlinear_lane(lane, _panels(), _parameters(lane))

    valid = result["value"].notna()
    assert valid.any(), lane
    assert result.loc[valid, "observed_at"].le(result.loc[valid, "available_at"]).all()
    assert result.loc[valid, "available_at"].le(result.loc[valid, "date"]).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(131, 141)])
def test_f131_f140_do_not_change_when_future_rows_are_appended(lane: str) -> None:
    api = _api()
    panels = _panels()
    cutoff = pd.Timestamp("2008-12-31")
    before_panels = {
        name: panel.loc[panel["date"].le(cutoff)].copy()
        for name, panel in panels.items()
    }
    before = api.evaluate_nonlinear_lane(lane, before_panels, _parameters(lane))
    after = api.evaluate_nonlinear_lane(lane, panels, _parameters(lane))

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True),
        after.loc[after["date"].le(cutoff)].reset_index(drop=True),
    )


@pytest.mark.parametrize(
    ("lane", "statistics"),
    [
        ("F131", ["high_frequency_share", "low_frequency_share", "energy_entropy", "scale_concentration"]),
        ("F132", ["imf1", "imf2", "residual", "oscillation_share"]),
        ("F133", ["trend_component", "oscillatory_component", "residual", "singular_concentration"]),
        ("F134", ["trend", "weekday_seasonality", "month_seasonality", "turn_of_month", "combined"]),
        ("F135", ["discord_score", "motif_density", "motif_follow_through", "neighbor_dispersion"]),
        ("F136", ["recurrence_rate", "recurrence_entropy", "determinism", "laminarity"]),
        ("F137", ["hurst", "roughness", "fractal_dimension", "multifractal_width"]),
        ("F138", ["tail_frequency", "tail_magnitude", "stress_duration", "hill_tail_index"]),
        ("F139", ["filtered_volatility", "volatility_innovation", "asymmetry_ratio", "variance_gap"]),
        ("F140", ["forecast", "regime_state", "transition_probability", "regime_spread"]),
    ],
)
def test_f131_f140_support_every_frozen_statistic(
    lane: str, statistics: list[str]
) -> None:
    api = _api()
    panels = _panels()
    for statistic in statistics:
        parameters = _parameters(lane)
        parameters["statistic"] = statistic
        result = api.evaluate_nonlinear_lane(lane, panels, parameters)
        assert result["value"].notna().any(), (lane, statistic)


def test_f132_eemd_is_deterministic_for_the_same_past() -> None:
    api = _api()
    parameters = _parameters("F132")
    parameters["kind"] = "eemd"

    first = api.evaluate_nonlinear_lane("F132", _panels(300), parameters)
    second = api.evaluate_nonlinear_lane("F132", _panels(300), parameters)

    pd.testing.assert_frame_equal(first, second)


def test_f131_scale_concentration_is_not_an_endpoint_share() -> None:
    api = _api()
    panels = _panels()
    parameters = _parameters("F131")
    parameters["scales"] = 4
    parameters["statistic"] = "low_frequency_share"
    low = api.evaluate_nonlinear_lane("F131", panels, parameters)
    parameters["statistic"] = "scale_concentration"
    concentration = api.evaluate_nonlinear_lane("F131", panels, parameters)

    valid = low["value"].notna() & concentration["value"].notna()
    assert valid.any()
    assert not low.loc[valid, "value"].equals(
        concentration.loc[valid, "value"]
    )


def test_f134_seasonal_estimate_excludes_the_current_return() -> None:
    api = _api()
    panels = _panels(300)
    parameters = _parameters("F134")
    parameters["statistic"] = "weekday_seasonality"
    original = api.evaluate_nonlinear_lane("F134", panels, parameters)
    changed = {name: panel.copy() for name, panel in panels.items()}
    changed["spy"].loc[changed["spy"].index[-1], "close"] *= 2.0
    changed["spy"].loc[changed["spy"].index[-1], "high"] *= 2.0

    mutated = api.evaluate_nonlinear_lane("F134", changed, parameters)

    assert mutated["value"].iloc[-1] == pytest.approx(original["value"].iloc[-1])


def test_f135_motif_follow_through_never_uses_the_query_future() -> None:
    api = _api()
    panels = _panels(300)
    parameters = _parameters("F135")
    baseline = api.evaluate_nonlinear_lane("F135", panels, parameters)
    extended = _panels(301)
    rerun = api.evaluate_nonlinear_lane("F135", extended, parameters)

    pd.testing.assert_series_equal(
        baseline["value"], rerun["value"].iloc[:-1].reset_index(drop=True)
    )


def test_nonlinear_engine_rejects_validation_rows() -> None:
    api = _api()
    panels = _panels(100)
    panels["spy"].loc[99, ["date", "available_at"]] = pd.Timestamp("2011-01-03")

    with pytest.raises(api.NonlinearFeatureEngineError, match="NON_TRAIN_PANEL_ROW:spy"):
        api.evaluate_nonlinear_lane("F131", panels, {"window": 20})


def test_nonlinear_batch_contains_exactly_f131_f140() -> None:
    outputs = _api().evaluate_nonlinear_family_batch(_panels())

    assert tuple(outputs) == tuple(f"F{i:03d}" for i in range(131, 141))
    assert all(output["value"].notna().any() for output in outputs.values())
