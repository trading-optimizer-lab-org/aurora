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
    fit_rule_params_train_only,
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
