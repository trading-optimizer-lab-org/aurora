from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from scripts.run_spy_daily_direction_accuracy import (
    LOCKED_START,
    build_dataset,
    build_ensemble_rows,
    build_funnel_context,
    build_scores,
    candidate_selection_score,
    choose_threshold_train_only,
    feature_groups,
    fit_candidate_scores_train_only,
    fit_conditional_table_scores_train_only,
    fit_rule_params_train_only,
    maybe_add_ensemble_pool,
    parse_cboe_daily_stats_html,
    parse_cboe_put_call_csv,
    predict_from_scores,
    sample_funnel_params,
    select_top,
    train_internal_cv_accuracy,
    write_shard_outputs,
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
    assert data[True]["workflow_dispatch"]["inputs"]["search_plan"]["default"] == "random"
    assert "random, funnel, funnel_top, funnel_robust, funnel_ensemble, funnel_down_override, or funnel_conditional" in text
    assert data[True]["workflow_dispatch"]["inputs"]["job_timeout_minutes"]["default"] == "65"
    assert "--target-accuracy" in text
    assert "--search-plan" in text
    assert "if: always()" in text
    assert "if-no-files-found: warn" in text


def test_daily_dataset_predicts_next_day_and_excludes_locked() -> None:
    idx = pd.date_range("2020-12-24", periods=8, freq="B")
    close = pd.DataFrame(
        {
            "SPY": [100.0, 101.0, 99.0, 100.0, 103.0, 102.0, 104.0, 105.0],
            "^VIX": [20.0, 19.0, 21.0, 20.0, 18.0, 19.0, 17.0, 16.0],
            "^TNX": [1.0] * 8,
            "^IRX": [0.1] * 8,
            "^N225": [20000.0, 20100.0, 19900.0, 20050.0, 20300.0, 20200.0, 20400.0, 20500.0],
            "^FTSE": [7000.0, 7010.0, 6990.0, 7020.0, 7030.0, 7015.0, 7040.0, 7050.0],
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
    for feature in [
        "spy_rsi_14d",
        "spy_macd_hist",
        "spy_ma_gap_50d",
        "spy_ret_lag_3d",
        "spy_atr_pct_14d",
        "cal_turn_of_month",
        "cal_is_monthly_opex_week",
        "cal_pre_holiday_3d",
        "global_cash_mean_ret_1d",
        "N225_ret_1d",
        "spy_sr_dist_prior_high_20d",
        "spy_sr_failed_breakdown_20d",
        "spy_lower_wick_pct",
    ]:
        assert feature in data.columns


def test_cboe_put_call_features_are_causal_lagged() -> None:
    idx = pd.date_range("2020-12-21", periods=8, freq="B")
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
    cboe = pd.DataFrame({"cboe_total_pc": np.arange(8, dtype=float) + 0.5}, index=idx)
    data = build_dataset(close, ohlcv, cboe)
    assert "cboe_total_pc" in data.columns
    assert data.loc[idx[1], "cboe_total_pc"] == cboe.loc[idx[0], "cboe_total_pc"]
    assert data.index.max() < LOCKED_START


def test_fred_stress_features_use_conservative_publication_lag() -> None:
    idx = pd.date_range("2020-12-01", periods=12, freq="B")
    close = pd.DataFrame(
        {
            "SPY": np.linspace(100.0, 112.0, len(idx)),
            "^VIX": np.linspace(20.0, 18.0, len(idx)),
            "^TNX": [1.0] * len(idx),
            "^IRX": [0.1] * len(idx),
        },
        index=idx,
    )
    ohlcv = pd.DataFrame(
        {
            "SPY_OPEN": close["SPY"].shift(1).fillna(close["SPY"].iloc[0]),
            "SPY_HIGH": close["SPY"] * 1.01,
            "SPY_LOW": close["SPY"] * 0.99,
            "SPY_CLOSE": close["SPY"],
            "SPY_VOLUME": np.arange(1_000, 1_000 + len(idx)),
        },
        index=idx,
    )
    fred = pd.DataFrame({"fred_nfci": np.arange(len(idx), dtype=float)}, index=idx)
    data = build_dataset(close, ohlcv, fred=fred)
    assert "fred_nfci" in data.columns
    assert data.loc[idx[5], "fred_nfci"] == fred.loc[idx[0], "fred_nfci"]
    assert data.index.max() < LOCKED_START


def test_cboe_public_csv_and_daily_html_parse_ratios() -> None:
    csv_text = """
Cboe Volume and Put/Call Ratio data,,,,
Total Volume,,,,
Trade_date,Call,Put,Total,P/C Ratio
10/17/2003,1152086,733258,1885344,0.64
"""
    parsed_csv = parse_cboe_put_call_csv(csv_text, source_name="total_archive")
    assert parsed_csv.loc[pd.Timestamp("2003-10-17"), "cboe_total_pc"] == 0.64

    html = r'<script>{\"name\":\"TOTAL PUT/CALL RATIO\",\"value\":\"0.86\"},{\"name\":\"INDEX PUT/CALL RATIO\",\"value\":\"1.28\"}</script>'
    parsed_html = parse_cboe_daily_stats_html(html, date=pd.Timestamp("2020-12-31"))
    assert parsed_html.loc[pd.Timestamp("2020-12-31"), "cboe_total_pc"] == 0.86
    assert parsed_html.loc[pd.Timestamp("2020-12-31"), "cboe_index_pc"] == 1.28


def test_cboe_features_have_dedicated_group() -> None:
    groups = feature_groups(
        [
            "cboe_total_pc",
            "spy_ret_5d",
            "vix_level",
            "fred_nfci",
            "cal_turn_of_month",
            "global_cash_mean_ret_1d",
            "N225_ret_1d",
            "spy_sr_dist_prior_high_20d",
            "spy_lower_wick_pct",
        ]
    )
    assert groups["cboe_options"] == [0]
    assert groups["fred_stress"] == [3]
    assert groups["calendar"] == [4]
    assert groups["global_cash"] == [5, 6]
    assert groups["support_resistance"] == [7, 8]


def test_funnel_context_uses_train_representatives_and_groups_correlated_features() -> None:
    idx = pd.date_range("1995-01-01", periods=260, freq="B")
    base = np.linspace(-1.0, 1.0, len(idx))
    x = pd.DataFrame(
        {
            "spy_ret_1d": base,
            "spy_mean_1d": base * 1.001,
            "spy_sr_dist_prior_high_20d": -base,
            "cboe_total_pc": np.sin(np.arange(len(idx)) / 7.0),
            "cal_month_01": (idx.month == 1).astype(float),
        },
        index=idx,
    )
    train_mask = np.ones(len(idx), dtype=bool)
    context = build_funnel_context(x, list(x.columns), train_mask)
    assert context["effective_groups"] < len(x.columns)
    grouped = {name: len(cols) for name, cols in context["groups"].items()}
    assert grouped["spy_momentum"] >= 1
    assert grouped["support_resistance"] >= 1
    assert grouped["cboe_options"] >= 1


def test_shard_checkpoint_writes_partial_outputs(tmp_path: Path) -> None:
    shard_dir = tmp_path / "stage_000"
    write_shard_outputs(
        shard_dir,
        [
            {
                "strategy_id": "candidate_a",
                "accepted": False,
                "close_to_pass": False,
                "score": 1.0,
                "train_accuracy": 0.55,
                "validation_accuracy": 0.54,
                "rule_type": "linear",
            }
        ],
        10,
        stage=0,
        target_accuracy=0.60,
        configs_evaluated=123,
        search_plan="funnel",
        funnel_context={"effective_groups": 7, "representatives": list(range(7))},
        validation_examined=5,
        elapsed_seconds=12.5,
        final=False,
    )
    assert (shard_dir / "top_candidates.csv").exists()
    summary = json.loads((shard_dir / "shard_summary.json").read_text(encoding="utf-8"))
    assert summary["configs_evaluated"] == 123
    assert summary["search_plan"] == "funnel"
    assert summary["checkpoint_final"] is False


def test_funnel_top_uses_simple_fast_rules() -> None:
    context = {
        "groups": {
            "spy_momentum": [0, 1, 2],
            "support_resistance": [3, 4],
            "cboe_options": [5, 6],
        },
        "representatives": list(range(7)),
        "effective_groups": 7,
    }
    rng = np.random.default_rng(123)
    seen = [
        sample_funnel_params(
            rng,
            [f"feature_{i}" for i in range(7)],
            stage=0,
            config_index=i,
            context=context,
            top_only=True,
        )
        for i in range(24)
    ]
    assert all(not params["rule_type"].startswith("ml_") for params in seen)
    assert max(len(params["feature_indices"]) for params in seen) <= 10


def test_funnel_robust_uses_low_capacity_candidates() -> None:
    context = {
        "groups": {
            "support_resistance": [0, 1, 2, 3],
            "relative_assets": [4, 5, 6],
            "cboe_options": [7, 8, 9],
            "spy_momentum": [10, 11],
        },
        "representatives": list(range(12)),
        "effective_groups": 12,
    }
    rng = np.random.default_rng(456)
    seen = [
        sample_funnel_params(
            rng,
            [f"feature_{i}" for i in range(12)],
            stage=0,
            config_index=i,
            context=context,
            robust_only=True,
        )
        for i in range(32)
    ]
    assert max(len(params["feature_indices"]) for params in seen) <= 12
    assert "ml_hist_gradient" not in {params["rule_type"] for params in seen}
    for params in seen:
        if params["rule_type"].startswith("ml_"):
            assert params["model_depth"] <= 4
            assert params["model_leaf"] >= 40


def test_funnel_down_override_uses_fallback_down_policies() -> None:
    context = {
        "groups": {
            "support_resistance": [0, 1, 2, 3],
            "cboe_options": [4, 5],
            "spy_volatility": [6, 7],
            "relative_assets": [8, 9, 10],
        },
        "representatives": list(range(11)),
        "effective_groups": 11,
    }
    rng = np.random.default_rng(789)
    seen = [
        sample_funnel_params(
            rng,
            [f"feature_{i}" for i in range(11)],
            stage=0,
            config_index=i,
            context=context,
            down_override_only=True,
        )
        for i in range(36)
    ]
    assert {params["threshold_policy"] for params in seen}.issubset({"fallback_up", "down_focus"})
    assert max(len(params["feature_indices"]) for params in seen) <= 14
    assert "ml_hist_gradient" not in {params["rule_type"] for params in seen}


def test_funnel_conditional_uses_small_train_only_tables() -> None:
    context = {
        "groups": {
            "calendar": [0, 1, 2],
            "support_resistance": [3, 4, 5],
            "spy_intraday": [6, 7],
            "cboe_options": [8, 9],
        },
        "representatives": list(range(10)),
        "effective_groups": 10,
    }
    rng = np.random.default_rng(890)
    seen = [
        sample_funnel_params(
            rng,
            [f"feature_{i}" for i in range(10)],
            stage=0,
            config_index=i,
            context=context,
            conditional_only=True,
        )
        for i in range(28)
    ]
    assert {params["rule_type"] for params in seen} == {"conditional_table"}
    assert max(len(params["feature_indices"]) for params in seen) <= 5
    assert {params["conditional_bins"] for params in seen}.issubset({2, 3, 4})


def test_robust_selection_score_penalizes_train_cv_gap() -> None:
    train_years = {"min_accuracy": 0.54}
    sub_train = {"min_accuracy": 0.55}
    stable_train = {"accuracy": 0.58, "up_accuracy": 0.58, "down_accuracy": 0.58}
    stable_cv = {"accuracy": 0.56, "min_split_accuracy": 0.54, "up_accuracy": 0.55, "down_accuracy": 0.54}
    overfit_train = {"accuracy": 0.82, "up_accuracy": 0.82, "down_accuracy": 0.82}
    overfit_cv = {"accuracy": 0.52, "min_split_accuracy": 0.51, "up_accuracy": 0.53, "down_accuracy": 0.50}
    stable_score = candidate_selection_score(
        stable_train,
        stable_cv,
        train_years,
        sub_train,
        feature_count=6,
        robust=True,
    )
    overfit_score = candidate_selection_score(
        overfit_train,
        overfit_cv,
        train_years,
        sub_train,
        feature_count=6,
        robust=True,
    )
    assert stable_score > overfit_score


def test_conditional_table_scores_are_fit_on_train_only() -> None:
    base_matrix = np.array(
        [
            [0.0],
            [0.1],
            [0.2],
            [0.3],
            [0.8],
            [0.9],
            [1.0],
            [1.1],
            [0.05],
            [1.05],
        ],
        dtype=float,
    )
    base_target = np.array([-1, -1, -1, -1, 1, 1, 1, 1, 1, -1], dtype=float)
    base_train_mask = np.array([True, True, True, True, True, True, True, True, False, False])
    matrix = np.tile(base_matrix, (80, 1))
    target = np.tile(base_target, 80)
    train_mask = np.tile(base_train_mask, 80)
    params = {
        "rule_type": "conditional_table",
        "feature_indices": [0],
        "conditional_bins": 2,
        "conditional_min_count": 2,
        "conditional_smooth": 1.0,
    }
    fitted, scores = fit_conditional_table_scores_train_only(matrix, target, train_mask, params)
    assert fitted["fitted_on_train_only"] is True
    assert fitted["conditional_state_count"] == 2
    assert scores[8] < 0.0
    assert scores[9] > 0.0


def test_down_override_score_rewards_down_precision() -> None:
    train_years = {"min_accuracy": 0.53}
    sub_train = {"min_accuracy": 0.54}
    train_cv = {"accuracy": 0.55, "min_split_accuracy": 0.53, "up_accuracy": 0.90, "down_accuracy": 0.20}
    low_precision = {
        "accuracy": 0.56,
        "up_accuracy": 0.90,
        "down_accuracy": 0.18,
        "precision_down": 0.45,
    }
    high_precision = {
        "accuracy": 0.56,
        "up_accuracy": 0.90,
        "down_accuracy": 0.18,
        "precision_down": 0.70,
    }
    assert candidate_selection_score(
        high_precision,
        train_cv,
        train_years,
        sub_train,
        feature_count=4,
        robust=False,
        down_override=True,
    ) > candidate_selection_score(
        low_precision,
        train_cv,
        train_years,
        sub_train,
        feature_count=4,
        robust=False,
        down_override=True,
    )


def test_funnel_ensemble_rows_are_train_only_and_audited() -> None:
    idx = pd.date_range("1995-01-01", periods=2200, freq="B")
    target = np.where(np.arange(len(idx)) % 3 == 0, -1.0, 1.0)
    dataset = pd.DataFrame({"target_direction": target}, index=idx)
    train_mask = np.zeros(len(idx), dtype=bool)
    validation_mask = np.zeros(len(idx), dtype=bool)
    train_mask[:1600] = True
    validation_mask[1600:2100] = True
    pool = []
    for i in range(3):
        scores = np.where(target > 0, 1.0 + i * 0.01, -1.0 - i * 0.01)
        row = {
            "strategy_id": f"component_{i}",
            "score": 1000.0 - i,
            "train_accuracy": 0.61,
            "validation_accuracy": 0.50,
        }
        maybe_add_ensemble_pool(
            pool,
            row=row,
            scores=scores,
            params={"rule_type": "linear"},
            train_cv={
                "accuracy": 0.56,
                "min_split_accuracy": 0.54,
                "up_accuracy": 0.55,
                "down_accuracy": 0.54,
            },
            train_mask=train_mask,
            max_size=5,
        )
    rows = build_ensemble_rows(
        pool,
        dataset=dataset,
        feature_cols=[],
        target=target,
        train_mask=train_mask,
        validation_mask=validation_mask,
        stage=7,
        target_accuracy=0.60,
    )
    assert rows
    assert rows[0]["rule_type"] == "ensemble_mean_score"
    assert rows[0]["locked_opened"] is False
    assert rows[0]["validation_used_for_selection"] is False
    assert rows[0]["features"].startswith("component_")


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


def test_fallback_up_policy_predicts_down_only_on_extreme_risk() -> None:
    scores = np.tile(np.linspace(0.0, 1.0, 100), 11)
    target = np.ones(len(scores))
    target[scores >= 0.9] = -1.0
    target[-100:] *= -1.0
    train_mask = np.array([True] * 1000 + [False] * 100)
    threshold, invert, metrics = choose_threshold_train_only(scores, target, train_mask, policy="fallback_up")
    preds = predict_from_scores(scores, threshold, invert, "fallback_up")
    assert threshold > 0.85
    assert metrics["accuracy"] > 0.95
    assert 0.80 < np.mean(preds[train_mask] > 0.0) < 0.95


def test_down_focus_and_class_balance_threshold_policies_are_train_only() -> None:
    scores = np.tile(np.linspace(0.0, 1.0, 100), 12)
    target = np.ones(len(scores))
    target[(scores >= 0.72) & (scores <= 0.92)] = -1.0
    train_mask = np.array([True] * 1000 + [False] * 200)

    threshold, invert, metrics = choose_threshold_train_only(scores, target, train_mask, policy="down_focus")
    preds = predict_from_scores(scores, threshold, invert, "down_focus")
    assert threshold < 0.95
    assert metrics["down_accuracy"] > 0.70
    assert 0.45 < np.mean(preds[train_mask] > 0.0) < 0.95

    balanced_target = np.where(scores >= 0.50, 1.0, -1.0)
    threshold, invert, metrics = choose_threshold_train_only(scores, balanced_target, train_mask, policy="class_balance")
    preds = predict_from_scores(scores, threshold, invert, "class_balance")
    assert np.isfinite(metrics["accuracy"])
    assert min(metrics["up_accuracy"], metrics["down_accuracy"]) > 0.90
    assert 0.35 < np.mean(preds[train_mask] > 0.0) < 0.65


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
