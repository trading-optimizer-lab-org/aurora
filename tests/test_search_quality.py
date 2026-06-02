from __future__ import annotations

import numpy as np
import pandas as pd

from aurora.research.search_quality import (
    SearchQualityConfig,
    SearchQualityState,
    SearchWaveMemory,
    allocate_adaptive_budget,
    assign_feature_family,
    early_prune_reason,
    filter_features_by_history,
    robust_train_score,
    select_diverse_portfolio,
    simple_soft_robustness,
    split_features_by_family,
)


def test_live_dedup_rejects_same_rule_and_near_identical_returns() -> None:
    state = SearchQualityState(SearchQualityConfig(near_duplicate_corr_threshold=0.98))
    ret_a = pd.Series([0.01, -0.005, 0.02, 0.003, -0.002])
    ret_b = ret_a * 1.01

    assert state.accept({"candidate_id": "a", "rules": "rsi > 50"}, ret_a).accepted is True
    same_rule = state.accept({"candidate_id": "b", "rules": "rsi > 50"}, ret_a)
    near_return = state.accept({"candidate_id": "c", "rules": "rsi > 55"}, ret_b)

    assert same_rule.accepted is False
    assert same_rule.reason == "duplicate_rule"
    assert near_return.accepted is False
    assert near_return.reason == "near_duplicate_returns"


def test_filter_features_by_history_requires_coverage_from_1995() -> None:
    idx = pd.date_range("1995-01-06", "1997-12-26", freq="W-FRI")
    availability = pd.DataFrame(
        {
            "SPY__ret_1w": True,
            "TLT__ret_26w": idx.year >= 1997,
        },
        index=idx,
    )

    kept, rejected = filter_features_by_history(
        ["SPY__ret_1w", "TLT__ret_26w"],
        availability,
        start_year=1995,
        min_weeks_per_year=26,
    )

    assert kept == ["SPY__ret_1w"]
    assert rejected == ["TLT__ret_26w"]


def test_feature_family_split_groups_momentum_trend_vol_credit_and_vix() -> None:
    features = [
        "SPY__ret_13w",
        "SPY__ma_gap_30w",
        "SPY__vol_13w",
        "HYG_LQD__ret_13w",
        "macro__VIXCLS__chg_4w",
        "calendar__month",
    ]

    groups = split_features_by_family(features)

    assert assign_feature_family("SPY__ret_13w") == "momentum"
    assert groups["momentum"] == ["SPY__ret_13w"]
    assert groups["trend"] == ["SPY__ma_gap_30w"]
    assert groups["volatility"] == ["SPY__vol_13w"]
    assert groups["credit"] == ["HYG_LQD__ret_13w"]
    assert groups["vix"] == ["macro__VIXCLS__chg_4w"]
    assert groups["other"] == ["calendar__month"]


def test_wave_memory_stores_train_only_and_rejects_validation_leakage() -> None:
    memory = SearchWaveMemory()
    memory.add_candidate(
        method="beam",
        candidate={
            "candidate_id": "a",
            "train_score": 1.2,
            "features": "SPY__ret_13w",
            "validation_score": 99.0,
            "locked_score": 100.0,
        },
    )

    payload = memory.to_dict()

    assert payload["beam"][0]["candidate_id"] == "a"
    assert payload["beam"][0]["train_score"] == 1.2
    assert "validation_score" not in payload["beam"][0]
    assert "locked_score" not in payload["beam"][0]


def test_robust_train_score_penalizes_drawdown_complexity_and_low_diversity() -> None:
    config = SearchQualityConfig()
    simple = {
        "train_sharpe": 1.0,
        "train_calmar": 1.2,
        "train_cagr": 0.12,
        "train_mdd": -0.10,
        "train_positive_years_pct": 0.70,
        "feature_count": 2,
        "diversity_score": 1.0,
    }
    complex_clone = {**simple, "feature_count": 12, "diversity_score": 0.1, "train_mdd": -0.35}

    assert robust_train_score(simple, config) > robust_train_score(complex_clone, config)


def test_early_pruning_cuts_bad_train_candidates_quickly() -> None:
    config = SearchQualityConfig(min_partial_periods=20)

    assert early_prune_reason({"periods": 10}, config) == ""
    assert early_prune_reason({"periods": 30, "train_cagr": -0.10}, config) == "negative_train_cagr"
    assert early_prune_reason({"periods": 30, "train_mdd": -0.80}, config) == "drawdown_too_deep"
    assert early_prune_reason({"periods": 30, "train_down_positive_pct": 0.10}, config) == "downside_hit_rate_too_low"


def test_adaptive_budget_rewards_unique_robust_per_hour_but_keeps_floor() -> None:
    stats = pd.DataFrame(
        [
            {"bucket": "beam/momentum", "unique_robust": 10, "hours": 2.0},
            {"bucket": "genetic/vix", "unique_robust": 1, "hours": 2.0},
            {"bucket": "dehb/credit", "unique_robust": 0, "hours": 2.0},
        ]
    )

    allocation = allocate_adaptive_budget(stats, total_jobs=30, min_jobs_per_bucket=3)

    assert sum(allocation.values()) == 30
    assert allocation["beam/momentum"] > allocation["genetic/vix"]
    assert allocation["dehb/credit"] >= 3


def test_simple_soft_robustness_is_fast_and_loose() -> None:
    idx = pd.date_range("2020-01-03", periods=80, freq="W-FRI")
    returns = pd.Series(np.full(len(idx), 0.002), index=idx)

    result = simple_soft_robustness(returns, SearchQualityConfig())

    assert result["soft_robust_pass"] is True
    assert result["soft_robust_fail_reason"] == ""
    assert result["soft_robust_periods"] == 80


def test_simple_soft_robustness_requires_positive_cagr_and_sharpe_but_not_mdd_gate() -> None:
    config = SearchQualityConfig()
    assert config.soft_robust_min_cagr == 0.0
    assert config.soft_robust_min_sharpe == 0.0
    assert config.soft_robust_max_mdd is None

    idx = pd.date_range("2020-01-03", periods=80, freq="W-FRI")
    negative = pd.Series(np.resize(np.array([-0.003, 0.001]), len(idx)), index=idx)

    result = simple_soft_robustness(negative, config)

    assert result["soft_robust_pass"] is False
    assert "cagr_too_low" in result["soft_robust_fail_reason"]
    assert "sharpe_too_low" in result["soft_robust_fail_reason"]
    assert "mdd_too_deep" not in result["soft_robust_fail_reason"]


def test_diverse_portfolio_keeps_best_non_clone_candidates() -> None:
    idx = pd.date_range("2020-01-03", periods=8, freq="W-FRI")
    returns = {
        "a": pd.Series([0.01, 0.02, -0.01, 0.01, 0.0, 0.02, -0.01, 0.01], index=idx),
        "b": pd.Series([0.011, 0.021, -0.011, 0.011, 0.0, 0.021, -0.011, 0.011], index=idx),
        "c": pd.Series([-0.01, 0.01, 0.02, -0.02, 0.01, -0.01, 0.02, 0.0], index=idx),
    }
    candidates = pd.DataFrame(
        [
            {"candidate_id": "a", "score": 10.0},
            {"candidate_id": "b", "score": 9.0},
            {"candidate_id": "c", "score": 8.0},
        ]
    )

    selected = select_diverse_portfolio(candidates, returns, max_size=3, max_corr=0.98)

    assert list(selected["candidate_id"]) == ["a", "c"]
