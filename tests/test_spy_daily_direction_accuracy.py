from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from scripts.run_spy_daily_direction_accuracy import (
    LOCKED_START,
    build_dataset,
    build_scores,
    choose_threshold_train_only,
    fit_candidate_scores_train_only,
    fit_rule_params_train_only,
    select_top,
    train_internal_cv_accuracy,
)


def test_spy_daily_direction_workflow_is_manual_355_jobs() -> None:
    path = Path(".github/workflows/spy-daily-direction-accuracy-355jobs.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "SPY Daily Direction Accuracy 355 Jobs"
    assert "workflow_dispatch" in data[True]
    assert "push" not in data[True]
    text = path.read_text(encoding="utf-8")
    assert "range(355)" in text
    assert "max-parallel: 178" in text
    assert "max-parallel: 177" in text
    assert data[True]["workflow_dispatch"]["inputs"]["target_accuracy"]["default"] == "0.60"
    assert "--target-accuracy" in text


def test_daily_dataset_predicts_next_day_and_excludes_locked() -> None:
    idx = pd.date_range("2020-12-24", periods=8, freq="B")
    close = pd.DataFrame(
        {
            "SPY": [100.0, 101.0, 99.0, 100.0, 103.0, 102.0, 104.0, 105.0],
            "^VIX": [20.0, 19.0, 21.0, 20.0, 18.0, 19.0, 17.0, 16.0],
            "^TNX": [1.0] * 8,
            "^IRX": [0.1] * 8,
        },
        index=idx,
    )
    ohlcv = pd.DataFrame(
        {
            "SPY_OPEN": close["SPY"].shift(1).fillna(close["SPY"].iloc[0]),
            "SPY_HIGH": close["SPY"] * 1.01,
            "SPY_LOW": close["SPY"] * 0.99,
            "SPY_CLOSE": close["SPY"],
            "SPY_VOLUME": np.arange(1_000, 1_008),
        },
        index=idx,
    )
    data = build_dataset(close, ohlcv)
    assert data.index.max() < LOCKED_START
    first = data.index[0]
    expected = np.sign(close["SPY"].pct_change(fill_method=None).shift(-1).loc[first])
    assert data.loc[first, "target_direction"] == expected
    for feature in ["spy_rsi_14d", "spy_macd_hist", "spy_ma_gap_50d", "spy_ret_lag_3d", "spy_atr_pct_14d"]:
        assert feature in data.columns


def test_rule_thresholds_are_fit_on_train_only() -> None:
    matrix = np.array(
        [
            [0.0],
            [1.0],
            [2.0],
            [100.0],
            [200.0],
        ]
    )
    train_mask = np.array([True, True, True, False, False])
    params = {
        "rule_type": "threshold_vote",
        "feature_indices": [0],
        "weights": [1.0],
        "quantiles": [0.5],
        "directions": [1.0],
    }
    fitted = fit_rule_params_train_only(matrix, train_mask, params)
    assert fitted["split_thresholds"] == [1.0]
    scores = build_scores(matrix, fitted)
    assert set(np.unique(scores)).issubset({-1.0, 1.0})


def test_train_only_direction_threshold_selector_ignores_validation() -> None:
    train_scores = np.linspace(-2.0, 2.0, 120)
    validation_scores = np.array([100.0, 200.0, 300.0, 400.0])
    scores = np.concatenate([train_scores, validation_scores])
    target = np.concatenate([np.where(train_scores >= 0.0, 1.0, -1.0), np.full(4, -1.0)])
    train_mask = np.array([True] * len(train_scores) + [False] * len(validation_scores))
    threshold, invert, metrics = choose_threshold_train_only(scores, target, train_mask)
    assert invert == 0
    assert threshold < 100.0
    assert metrics["accuracy"] == 1.0


def test_ml_candidate_fits_only_train_rows() -> None:
    train_x = np.linspace(-2.0, 2.0, 640)
    validation_x = np.linspace(-2.0, 2.0, 40)
    matrix = np.concatenate([train_x, validation_x])[:, None]
    target = np.concatenate([np.where(train_x >= 0.0, 1.0, -1.0), np.where(validation_x >= 0.0, -1.0, 1.0)])
    train_mask = np.array([True] * len(train_x) + [False] * len(validation_x))
    params = {
        "rule_type": "ml_logistic",
        "feature_indices": [0],
        "model_c": 1.0,
        "class_weight": "none",
        "random_state": 7,
    }
    fitted, scores = fit_candidate_scores_train_only(matrix, target, train_mask, params)
    threshold, invert, metrics = choose_threshold_train_only(scores, target, train_mask)
    assert fitted["fitted_on_train_only"] is True
    assert fitted["train_rows_fit"] == len(train_x)
    assert invert == 0
    assert threshold < np.nanmax(scores[train_mask])
    assert metrics["accuracy"] > 0.95


def test_train_internal_cv_uses_only_train_rows() -> None:
    train_x = np.linspace(-3.0, 3.0, 1800)
    validation_x = np.linspace(-3.0, 3.0, 80)
    matrix = np.concatenate([train_x, validation_x])[:, None]
    target = np.concatenate(
        [
            np.where(train_x >= 0.0, 1.0, -1.0),
            np.where(validation_x >= 0.0, -1.0, 1.0),
        ]
    )
    train_mask = np.array([True] * len(train_x) + [False] * len(validation_x))
    params = {
        "rule_type": "train_corr_linear",
        "feature_indices": [0],
        "weights": [1.0],
        "quantiles": [0.5],
        "directions": [1.0],
    }
    metrics = train_internal_cv_accuracy(matrix, target, train_mask, params)
    assert metrics["accuracy"] > 0.95
    assert metrics["min_split_accuracy"] > 0.95


def test_select_top_does_not_use_validation_for_retention() -> None:
    frame = pd.DataFrame(
        [
            {
                "strategy_id": "train_winner",
                "score": 2.0,
                "train_accuracy": 0.61,
                "validation_accuracy": 0.51,
            },
            {
                "strategy_id": "validation_winner",
                "score": 1.0,
                "train_accuracy": 0.52,
                "validation_accuracy": 0.99,
            },
        ]
    )
    top = select_top(frame, top_per_stage=1)
    assert top["strategy_id"].tolist() == ["train_winner"]
