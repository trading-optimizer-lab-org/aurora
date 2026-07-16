"""Purged walk-forward, statistical robustness and true Pareto contracts."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest

from aurora.research.stock_protocol.pareto import pareto_frontier, pareto_frontiers_by
from aurora.research.stock_protocol.robustness import (
    benjamini_hochberg,
    block_bootstrap_records,
    cscv_probability_of_backtest_overfitting,
    deflated_sharpe_ratio,
    leave_one_group_out,
)
from aurora.research.stock_protocol.validation import (
    final_holdout_contract,
    generate_purged_walk_forward,
)


def _dates() -> pd.DatetimeIndex:
    return pd.bdate_range("1995-01-02", "2020-12-31")


def test_expanding_walk_forward_has_temporal_roles_and_no_overlap():
    folds = generate_purged_walk_forward(
        _dates(),
        train_years=10,
        validation_years=3,
        test_years=1,
        horizon_sessions=21,
        mode="expanding",
    )
    first = folds[0]
    assert first.train_start == pd.Timestamp("1995-01-02")
    assert first.validation_start == pd.Timestamp("2005-01-03")
    assert first.test_start == pd.Timestamp("2008-01-01")
    assert first.test_end == pd.Timestamp("2008-12-31")
    assert first.train_purged_end < first.validation_start
    assert first.validation_purged_end < first.test_start
    assert all(fold.test_end < pd.Timestamp("2016-01-01") for fold in folds)
    assert all(fold.role == "walk_forward_test" for fold in folds)


def test_walk_forward_purge_removes_labels_crossing_boundaries():
    dates = _dates()
    fold = generate_purged_walk_forward(
        dates,
        train_years=10,
        validation_years=3,
        test_years=1,
        horizon_sessions=252,
    )[0]
    train_end_index = dates.get_indexer([fold.train_purged_end])[0]
    assert dates[train_end_index + 252] < fold.validation_start
    valid_end_index = dates.get_indexer([fold.validation_purged_end])[0]
    assert dates[valid_end_index + 252] < fold.test_start


def test_rolling_robustness_window_is_fifteen_years():
    folds = generate_purged_walk_forward(
        _dates(),
        train_years=15,
        validation_years=3,
        test_years=1,
        horizon_sessions=21,
        mode="rolling",
    )
    second = folds[1]
    assert second.train_start.year == 1996
    assert second.validation_start.year == 2011


def test_final_holdout_is_one_shot_and_never_used_for_optimization():
    holdout = final_holdout_contract(_dates())
    assert holdout["start"] == "2016-01-01"
    assert holdout["end"] == "2020-12-31"
    assert holdout["evaluation_count"] == 1
    assert holdout["optimization_allowed"] is False
    assert holdout["selection_allowed"] is False
    assert holdout["locked_opened"] is False


def test_validation_rejects_locked_dates():
    dates = pd.bdate_range("2010-01-01", "2021-01-04")
    with pytest.raises(ValueError, match="locked"):
        generate_purged_walk_forward(dates)


def _pareto_input() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "candidate_id": ["balanced", "fast", "dominated", "invalid"],
            "cagr": [0.15, 0.12, 0.10, np.nan],
            "sortino": [1.5, 1.2, 0.8, 2.0],
            "calmar": [1.0, 0.9, 0.5, 1.5],
            "return_per_capital_day": [0.0010, 0.0020, 0.0005, 0.0030],
            "drawdown_abs": [0.15, 0.10, 0.25, 0.05],
            "expected_shortfall_abs": [0.03, 0.02, 0.05, 0.01],
            "turnover": [2.0, 5.0, 7.0, 1.0],
            "average_duration": [80.0, 20.0, 100.0, 10.0],
            "costs": [100.0, 250.0, 400.0, 50.0],
            "horizon": [252, 63, 252, 20],
            "cost_bps": [10, 10, 10, 10],
        }
    )


def test_pareto_is_true_non_dominated_front_and_excludes_non_finite():
    front = pareto_frontier(
        _pareto_input(),
        maximize=["cagr", "sortino", "calmar", "return_per_capital_day"],
        minimize=["drawdown_abs", "expected_shortfall_abs", "turnover", "average_duration", "costs"],
    )
    assert set(front["candidate_id"]) == {"balanced", "fast"}
    assert "invalid" not in set(front["candidate_id"])


def test_pareto_fronts_can_be_grouped_by_horizon_and_cost():
    fronts = pareto_frontiers_by(
        _pareto_input().dropna(),
        group_columns=["horizon", "cost_bps"],
        maximize=["cagr", "sortino", "calmar", "return_per_capital_day"],
        minimize=["drawdown_abs", "expected_shortfall_abs", "turnover", "average_duration", "costs"],
    )
    assert {"horizon", "cost_bps", "pareto_rank"} <= set(fronts.columns)
    assert set(fronts["candidate_id"]) == {"balanced", "fast"}


def test_block_bootstrap_is_reproducible_and_records_real_work():
    returns = pd.Series(np.linspace(-0.02, 0.03, 100), name="candidate_a")
    first = block_bootstrap_records(
        returns,
        n_samples=20,
        block_size=10,
        seed=123,
        variant="candidate_a",
    )
    second = block_bootstrap_records(
        returns,
        n_samples=20,
        block_size=10,
        seed=123,
        variant="candidate_a",
    )
    pd.testing.assert_frame_equal(first, second)
    assert len(first) == 20
    assert set(first["method"]) == {"circular_block_bootstrap"}
    assert set(first["seed"]) == {123}
    assert set(first["variant"]) == {"candidate_a"}
    assert set(first["n_observations"]) == {100}
    expected_hash = hashlib.sha256(returns.to_numpy(dtype=float).tobytes()).hexdigest()
    assert set(first["input_hash"]) == {expected_hash}
    assert first["sample_hash"].nunique() > 1


def test_bootstrap_changes_when_seed_changes():
    returns = pd.Series(np.linspace(-0.02, 0.03, 100))
    first = block_bootstrap_records(returns, 5, 10, 1, "candidate")
    second = block_bootstrap_records(returns, 5, 10, 2, "candidate")
    assert first["sample_hash"].tolist() != second["sample_hash"].tolist()


def test_benjamini_hochberg_controls_multiple_tests():
    adjusted = benjamini_hochberg(pd.Series([0.001, 0.01, 0.04, 0.20]))
    assert adjusted.tolist() == pytest.approx([0.004, 0.02, 0.0533333333, 0.20])
    assert adjusted.is_monotonic_increasing


def test_leave_one_group_out_really_removes_each_group():
    frame = pd.DataFrame(
        {
            "return": [0.01, 0.02, -0.01, 0.03, 0.01, -0.02],
            "decade": [1990, 1990, 2000, 2000, 2010, 2010],
        }
    )
    result = leave_one_group_out(frame, "decade", "return")
    assert set(result["left_out_group"]) == {1990, 2000, 2010}
    assert set(result["remaining_observations"]) == {4}
    assert result["left_out_observations"].eq(2).all()


def test_deflated_sharpe_penalizes_multiple_trials_and_is_finite():
    rng = np.random.default_rng(42)
    returns = pd.Series(rng.normal(0.001, 0.01, 500))
    few = deflated_sharpe_ratio(returns, n_trials=5)
    many = deflated_sharpe_ratio(returns, n_trials=500)
    assert 0.0 <= many["probability"] <= few["probability"] <= 1.0
    assert many["expected_max_sharpe"] > few["expected_max_sharpe"]
    assert all(np.isfinite(float(value)) for value in many.values())


def test_cscv_pbo_uses_real_complementary_train_test_partitions():
    rng = np.random.default_rng(7)
    observations = 240
    matrix = pd.DataFrame(
        {
            "persistent": rng.normal(0.002, 0.01, observations),
            "noise_a": rng.normal(0.0, 0.02, observations),
            "noise_b": rng.normal(-0.0002, 0.02, observations),
        }
    )
    result = cscv_probability_of_backtest_overfitting(matrix, partitions=8)
    assert result["combinations_evaluated"] > 1
    assert 0.0 <= result["pbo"] <= 1.0
    assert result["input_hash"]
    assert result == cscv_probability_of_backtest_overfitting(matrix, partitions=8)
