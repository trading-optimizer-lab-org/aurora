from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from scripts.run_spy_weekly_longshort_sharpe2 import (
    LOCKED_START,
    build_positions_train_only,
    build_feature_frame,
    build_bagged_leaf_ensemble_positions,
    build_spy_daily_weekly_features,
    build_score,
    choose_train_only_threshold,
    metrics,
    position_audit,
    sample_params,
    train_only_stability,
)


def test_spy_weekly_longshort_workflow_is_manual_355_jobs() -> None:
    path = Path(".github/workflows/spy-weekly-longshort-sharpe2-355jobs.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "SPY Weekly LongShort Sharpe2 355 Jobs"
    assert "workflow_dispatch" in data[True]
    assert "push" not in data[True]
    text = path.read_text(encoding="utf-8")
    assert "range(355)" in text
    assert "max-parallel: 178" in text
    assert "max-parallel: 177" in text


def test_position_policy_is_always_long_or_short() -> None:
    positions = np.array([1.0, -1.0, 1.0, -1.0])
    audit = position_audit(positions)
    assert audit["always_invested"] is True
    assert audit["cash_weeks"] == 0
    assert audit["min_position"] == -1.0
    assert audit["max_position"] == 1.0
    assert audit["min_abs_position"] == 1.0
    assert audit["max_abs_position"] == 1.0


def test_feature_frame_uses_lagged_features_and_no_locked() -> None:
    idx = pd.date_range("2000-01-07", periods=170, freq="W-FRI")
    wiggle = np.sin(np.arange(len(idx)) / 5.0) * 2.0
    spy = pd.Series(np.linspace(100.0, 140.0, len(idx)) + wiggle, index=idx)
    prices = pd.DataFrame(
        {
            "SPY": spy,
            "^VIX": np.linspace(20.0, 15.0, len(idx)),
            "^TNX": np.linspace(5.0, 3.0, len(idx)),
        },
        index=idx,
    )
    returns = prices.pct_change(fill_method=None).dropna()
    features = build_feature_frame(prices, returns)
    assert not features.empty
    assert features.index.max() < LOCKED_START
    # The first feature row must appear only after enough prior data exists.
    assert features.index.min() > returns.index.min()


def test_spy_daily_weekly_features_are_lagged_into_feature_frame() -> None:
    rng = np.random.default_rng(17)
    idx = pd.date_range("2000-01-03", periods=900, freq="B")
    close = pd.Series(
        100.0 + np.cumsum(np.sin(np.arange(len(idx)) / 6.0) * 0.2 + rng.normal(0.0, 0.35, len(idx)) + 0.03),
        index=idx,
    )
    raw = pd.DataFrame(
        {
            "Open": close.shift(1).fillna(close.iloc[0]) * 1.001,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": np.linspace(1_000_000, 2_000_000, len(idx)),
        },
        index=idx,
    )
    daily_weekly = build_spy_daily_weekly_features(raw)
    weekly_prices = pd.DataFrame(
        {
            "SPY": raw["Close"].resample("W-FRI").last(),
            "^VIX": 20.0 + np.sin(np.arange(len(daily_weekly)) / 4.0) * 2.0,
            "^TNX": 5.0 + np.cos(np.arange(len(daily_weekly)) / 5.0) * 0.5,
        },
        index=daily_weekly.index,
    ).join(daily_weekly)
    weekly_prices = weekly_prices.dropna(how="any")
    returns = weekly_prices[["SPY", "^VIX", "^TNX"]].pct_change(fill_method=None).dropna()
    features = build_feature_frame(weekly_prices, returns)
    assert "spy_daily_vol_z_13w" in features.columns
    assert "spy_daily_up_down_balance" in features.columns
    assert features.index.min() > returns.index.min()


def test_sampled_rule_produces_only_plus_or_minus_one_positions() -> None:
    rng = np.random.default_rng(1)
    feature_cols = [f"f{i}" for i in range(12)]
    matrix = rng.normal(size=(100, len(feature_cols)))
    params = sample_params(rng, feature_cols, stage=4)
    score = build_score(matrix, params)
    if int(params["invert"]) == 1:
        score = -score
    positions = np.where(score >= float(params["threshold"]), 1.0, -1.0)
    assert set(np.unique(positions)).issubset({-1.0, 1.0})
    assert position_audit(positions)["always_invested"] is True


def test_non_linear_rule_types_produce_finite_scores() -> None:
    rng = np.random.default_rng(2)
    matrix = rng.normal(size=(80, 5))
    base = {
        "feature_indices": [0, 1, 2],
        "weights": [0.2, -0.5, 0.3],
        "thresholds": [0.0, 0.5, -0.5],
        "band_widths": [0.5, 1.0, 1.5],
        "directions": [1.0, -1.0, 1.0],
    }
    for rule_type in ["linear", "threshold_vote", "band_vote", "signed_stump_vote"]:
        params = {**base, "rule_type": rule_type}
        score = build_score(matrix, params)
        assert score.shape == (80,)
        assert np.isfinite(score).all()


def test_train_only_threshold_selector_returns_valid_policy() -> None:
    score = np.linspace(-2.0, 2.0, 100)
    spy_returns = np.where(score > 0.0, 0.01, -0.01)
    train_mask = np.array([True] * 80 + [False] * 20)
    threshold, invert, selected = choose_train_only_threshold(score, spy_returns, train_mask)
    oriented = -score if invert == 1 else score
    positions = np.where(oriented >= threshold, 1.0, -1.0)
    assert position_audit(positions[train_mask])["always_invested"] is True
    assert selected["sharpe"] > 0.0


def test_train_leaf_tree_returns_valid_policy() -> None:
    rng = np.random.default_rng(3)
    matrix = rng.normal(size=(120, 6))
    train_mask = np.array([True] * 90 + [False] * 30)
    spy_returns = np.where(matrix[:, 0] + matrix[:, 1] > 0.0, 0.01, -0.01)
    params = {
        "rule_type": "train_leaf_tree",
        "feature_indices": [0, 1, 2, 3],
        "thresholds": [0.0, 0.2, -0.3, 0.4],
        "directions": [1.0, -1.0, 1.0, -1.0],
    }
    positions, selected = build_positions_train_only(matrix, spy_returns, train_mask, params)
    assert position_audit(positions)["always_invested"] is True
    assert set(np.unique(positions)).issubset({-1.0, 1.0})
    assert selected["sharpe"] > 0.0
    assert "leaf_signs" in params


def test_ridge_model_returns_valid_policy() -> None:
    rng = np.random.default_rng(4)
    matrix = rng.normal(size=(180, 8))
    train_mask = np.array([True] * 120 + [False] * 60)
    spy_returns = np.where(matrix[:, 0] * 0.7 - matrix[:, 2] * 0.4 > 0.0, 0.01, -0.01)
    params = {
        "rule_type": "ridge_model",
        "feature_indices": [0, 1, 2, 3, 4],
        "weights": [0.2] * 5,
        "ridge_alpha": 0.1,
    }
    positions, selected = build_positions_train_only(matrix, spy_returns, train_mask, params)
    assert position_audit(positions)["always_invested"] is True
    assert set(np.unique(positions)).issubset({-1.0, 1.0})
    assert np.isfinite(selected["sharpe"])
    assert "intercept" in params


def test_era_leaf_tree_returns_valid_policy() -> None:
    rng = np.random.default_rng(5)
    matrix = rng.normal(size=(160, 6))
    train_mask = np.array([True] * 120 + [False] * 40)
    spy_returns = np.where(matrix[:, 0] - matrix[:, 1] > 0.0, 0.012, -0.008)
    params = {
        "rule_type": "era_leaf_tree",
        "feature_indices": [0, 1, 2, 3],
        "thresholds": [0.0, 0.2, -0.3, 0.4],
        "directions": [1.0, -1.0, 1.0, -1.0],
    }
    positions, selected = build_positions_train_only(matrix, spy_returns, train_mask, params)
    assert position_audit(positions)["always_invested"] is True
    assert set(np.unique(positions)).issubset({-1.0, 1.0})
    assert np.isfinite(selected["sharpe"])
    assert "leaf_era_agreement_mean" in params


def test_cv_era_leaf_tree_returns_valid_policy_and_cv_metrics() -> None:
    rng = np.random.default_rng(6)
    matrix = rng.normal(size=(220, 7))
    train_mask = np.array([True] * 160 + [False] * 60)
    spy_returns = np.where(matrix[:, 0] + matrix[:, 3] * 0.4 > 0.0, 0.01, -0.007)
    params = {
        "rule_type": "cv_era_leaf_tree",
        "feature_indices": [0, 1, 2, 3],
        "thresholds": [0.0, 0.1, -0.1, 0.2],
        "directions": [1.0, 1.0, -1.0, 1.0],
    }
    positions, selected = build_positions_train_only(matrix, spy_returns, train_mask, params)
    assert position_audit(positions)["always_invested"] is True
    assert set(np.unique(positions)).issubset({-1.0, 1.0})
    assert np.isfinite(selected["sharpe"])
    assert np.isfinite(params["cv_train_sharpe"])
    assert "leaf_era_agreement_mean" in params


def test_cv_bagged_leaf_ensemble_returns_valid_policy_and_cv_metrics() -> None:
    rng = np.random.default_rng(7)
    matrix = rng.normal(size=(260, 10))
    train_mask = np.array([True] * 190 + [False] * 70)
    spy_returns = np.where(matrix[:, 0] - matrix[:, 4] * 0.5 > 0.0, 0.009, -0.006)
    params = {
        "rule_type": "cv_bagged_leaf_ensemble",
        "feature_indices": [0, 1, 2, 3, 4, 5],
        "weights": [1.0 / 6.0] * 6,
        "ensemble_members": [
            {
                "feature_indices": [0, 1, 2],
                "thresholds": [0.0, 0.2, -0.1],
                "directions": [1.0, -1.0, 1.0],
            },
            {
                "feature_indices": [3, 4, 5],
                "thresholds": [0.1, -0.2, 0.3],
                "directions": [1.0, 1.0, -1.0],
            },
            {
                "feature_indices": [0, 4],
                "thresholds": [0.0, 0.0],
                "directions": [1.0, -1.0],
            },
        ],
    }
    positions = build_bagged_leaf_ensemble_positions(matrix, spy_returns, train_mask, params, cv=True)
    assert position_audit(positions)["always_invested"] is True
    assert set(np.unique(positions)).issubset({-1.0, 1.0})
    assert np.isfinite(params["cv_train_sharpe"])


def test_train_only_stability_penalizes_split_fragility() -> None:
    dates = pd.date_range("1995-01-06", periods=520, freq="W-FRI")
    wiggle = np.sin(np.arange(520) / 3.0) * 0.002
    good_then_bad = np.r_[np.full(260, 0.01), np.full(260, -0.004)] + wiggle
    stable = train_only_stability(good_then_bad, dates)
    assert stable["first_half_sharpe"] > 0.0
    assert stable["second_half_sharpe"] < 0.0
    assert stable["min_half_sharpe"] < 0.0


def test_metrics_reports_sharpe_and_mdd() -> None:
    rets = np.array([0.02, -0.01, 0.03, -0.005, 0.01] * 20)
    out = metrics(rets)
    assert np.isfinite(out["sharpe"])
    assert np.isfinite(out["cagr"])
    assert out["mdd"] <= 0.0
