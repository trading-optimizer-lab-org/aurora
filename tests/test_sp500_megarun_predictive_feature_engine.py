from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest


APPROVED_FEATURES = ("F003", "F015", "F021", "F032", "F039")


def _api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.predictive_feature_engine"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"predictive feature engine is missing: {exc}")


def _inputs(
    periods: int = 720,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    dates = pd.bdate_range("2006-01-03", periods=periods)
    phase = np.arange(periods, dtype=float)
    returns = (
        0.00025
        + 0.005 * np.sin(phase / 13.0)
        + 0.002 * np.cos(phase / 37.0)
        + 0.001 * np.sin(phase / 3.0)
    )
    close = 100.0 * np.exp(np.cumsum(returns))
    prior = np.r_[close[0], close[:-1]]
    market = pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "open": prior * (1.0 + 0.001 * np.sin(phase / 7.0)),
            "high": np.maximum(prior, close) * 1.005,
            "low": np.minimum(prior, close) * 0.995,
            "close": close,
            "volume": 1_000_000.0
            * (1.2 + 0.2 * np.sin(phase / 17.0) + 0.05 * np.cos(phase / 5.0)),
        }
    )
    cboe = pd.DataFrame(
        {
            "date": dates,
            "observed_at": dates - pd.offsets.BDay(1),
            "available_at": dates,
            "vix_close": 20.0
            + 4.0 * np.sin(phase / 23.0)
            + 150.0 * np.maximum(-returns, 0.0),
        }
    )
    features: dict[str, pd.DataFrame] = {}
    for offset, lane in enumerate(APPROVED_FEATURES, start=1):
        values = (
            np.sin(phase / (5.0 + offset * 2.0))
            + 0.4 * np.cos(phase / (11.0 + offset))
            + offset * returns * 30.0
        )
        features[lane] = pd.DataFrame(
            {
                "date": dates,
                "observed_at": dates - pd.offsets.BDay(1),
                "available_at": dates,
                "value": values,
            }
        )
    return {"spy": market, "cboe": cboe}, features


def _parameters(lane: str) -> dict[str, object]:
    common = {"window": 126, "refit": "quarterly"}
    return {
        "F141": {
            **common,
            "kind": "arma",
            "statistic": "forecast_z",
            "ar_order": 2,
            "ma_order": 1,
            "volume_lags": 1,
            "ridge": 0.1,
        },
        "F142": {
            **common,
            "kind": "var",
            "statistic": "forecast_z",
            "lags": 2,
            "ridge": 0.1,
        },
        "F143": {
            **common,
            "statistic": "factor_score",
            "components": 2,
            "sign_rule": "return_correlation",
        },
        "F144": {
            **common,
            "statistic": "median_skew",
            "lags": 5,
            "tail_quantile": 0.1,
            "forecast_quantile": 0.5,
            "ridge": 0.1,
        },
        "F145": {
            **common,
            "kind": "rbf",
            "statistic": "direction_score",
            "support_vectors": 24,
            "gamma": 0.5,
            "degree": 2,
            "ridge": 0.1,
        },
        "F146": {
            **common,
            "kind": "extra_trees",
            "statistic": "tree_dispersion",
            "estimators": 12,
            "depth": 3,
            "max_features": 3,
            "min_leaf": 8,
            "seed": 146,
        },
        "F147": {
            **common,
            "activation": "tanh",
            "statistic": "direction_probability",
            "hidden_units": 8,
            "epochs": 40,
            "learning_rate": 0.02,
            "ridge": 0.1,
            "seed": 147,
        },
        "F148": {
            **common,
            "statistic": "forecast_z",
            "sequence": 20,
            "kernel": 3,
            "dilation": 2,
            "filters": 4,
            "ridge": 0.1,
            "seed": 148,
        },
        "F149": {
            **common,
            "kind": "reservoir",
            "statistic": "state_energy",
            "sequence": 20,
            "units": 12,
            "spectral_radius": 0.6,
            "leak": 0.5,
            "ridge": 0.1,
            "seed": 149,
        },
        "F150": {
            **common,
            "kind": "attention",
            "statistic": "attention_entropy",
            "lookback": 10,
            "temperature": 1.0,
            "experts": 3,
            "gate": "hybrid",
            "ridge": 0.1,
        },
    }[lane].copy()


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(141, 151)])
def test_f141_f150_produce_finite_train_only_values(lane: str) -> None:
    panels, features = _inputs()

    result = _api().evaluate_predictive_lane(
        lane, panels, features, _parameters(lane)
    )

    valid = result["value"].notna()
    assert valid.any(), lane
    assert result.loc[valid, "observed_at"].le(result.loc[valid, "available_at"]).all()
    assert result.loc[valid, "available_at"].le(result.loc[valid, "date"]).all()
    assert result["date"].max() <= pd.Timestamp("2010-12-31")


@pytest.mark.parametrize("lane", [f"F{i:03d}" for i in range(141, 151)])
def test_f141_f150_do_not_change_when_future_rows_are_appended(lane: str) -> None:
    api = _api()
    panels, features = _inputs()
    cutoff = panels["spy"].loc[499, "date"]
    prior_panels = {
        name: panel.loc[panel["date"].le(cutoff)].copy()
        for name, panel in panels.items()
    }
    prior_features = {
        name: panel.loc[panel["date"].le(cutoff)].copy()
        for name, panel in features.items()
    }

    before = api.evaluate_predictive_lane(
        lane, prior_panels, prior_features, _parameters(lane)
    )
    after = api.evaluate_predictive_lane(lane, panels, features, _parameters(lane))

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True),
        after.loc[after["date"].le(cutoff)].reset_index(drop=True),
    )


@pytest.mark.parametrize(
    ("lane", "parameter", "variants"),
    [
        ("F141", "kind", ("ar", "arma", "distributed_regression")),
        ("F142", "kind", ("var", "vecm")),
        (
            "F143",
            "statistic",
            ("factor_score", "explained_share", "common_direction", "idiosyncratic_dispersion"),
        ),
        (
            "F144",
            "statistic",
            ("quantile_forecast", "tail_probability", "interquantile_range", "median_skew"),
        ),
        ("F145", "kind", ("linear", "rbf", "polynomial")),
        ("F146", "kind", ("random_forest", "extra_trees")),
        ("F147", "activation", ("tanh", "relu")),
        (
            "F148",
            "statistic",
            ("forecast_z", "direction_probability", "filter_dispersion", "temporal_concentration"),
        ),
        ("F149", "kind", ("reservoir", "small_rnn")),
        ("F150", "kind", ("attention", "moe")),
    ],
)
def test_f141_f150_support_every_frozen_model_variant(
    lane: str, parameter: str, variants: tuple[str, ...]
) -> None:
    api = _api()
    panels, features = _inputs(360)
    for variant in variants:
        parameters = _parameters(lane)
        parameters[parameter] = variant
        result = api.evaluate_predictive_lane(lane, panels, features, parameters)
        assert result["value"].notna().any(), (lane, variant)


def test_derived_models_inherit_the_slowest_feature_observation() -> None:
    panels, features = _inputs(320)
    features["F039"]["observed_at"] = features["F039"]["date"]

    result = _api().evaluate_predictive_lane(
        "F143", panels, features, _parameters("F143")
    )

    valid = result["value"].notna()
    assert result.loc[valid, "observed_at"].eq(result.loc[valid, "date"]).all()


def test_f142_vecm_does_not_reestimate_the_past_with_future_levels() -> None:
    api = _api()
    panels, features = _inputs()
    cutoff = panels["spy"].loc[499, "date"]
    prior_panels = {
        name: panel.loc[panel["date"].le(cutoff)].copy()
        for name, panel in panels.items()
    }
    parameters = _parameters("F142")
    parameters["kind"] = "vecm"

    before = api.evaluate_predictive_lane("F142", prior_panels, features, parameters)
    after = api.evaluate_predictive_lane("F142", panels, features, parameters)

    pd.testing.assert_frame_equal(
        before.reset_index(drop=True),
        after.loc[after["date"].le(cutoff)].reset_index(drop=True),
    )


def test_f144_requires_only_spy_and_not_the_derived_feature_ledger() -> None:
    panels, _ = _inputs(320)

    result = _api().evaluate_predictive_lane(
        "F144", panels, {}, _parameters("F144")
    )

    assert result["value"].notna().any()


def test_temporal_models_do_not_claim_the_unused_f039_observation() -> None:
    panels, features = _inputs(320)
    features["F039"]["observed_at"] = features["F039"]["date"]

    result = _api().evaluate_predictive_lane(
        "F148", panels, features, _parameters("F148")
    )

    valid = result["value"].notna()
    assert result.loc[valid, "observed_at"].lt(result.loc[valid, "date"]).all()


def test_predictive_engine_rejects_a_feature_available_after_decision() -> None:
    api = _api()
    panels, features = _inputs(220)
    features["F039"].loc[100, "available_at"] += pd.offsets.BDay(1)

    with pytest.raises(api.PredictiveFeatureEngineError, match="NON_CAUSAL_FEATURE:F039"):
        api.evaluate_predictive_lane("F143", panels, features, _parameters("F143"))


def test_predictive_engine_rejects_validation_rows() -> None:
    api = _api()
    panels, features = _inputs(220)
    panels["spy"].loc[219, ["date", "available_at"]] = pd.Timestamp("2011-01-03")

    with pytest.raises(api.PredictiveFeatureEngineError, match="NON_TRAIN_PANEL:spy"):
        api.evaluate_predictive_lane("F141", panels, features, _parameters("F141"))


def test_predictive_batch_contains_exactly_f141_f150() -> None:
    panels, features = _inputs()

    outputs = _api().evaluate_predictive_family_batch(panels, features)

    assert tuple(outputs) == tuple(f"F{i:03d}" for i in range(141, 151))
    assert all(output["value"].notna().any() for output in outputs.values())
