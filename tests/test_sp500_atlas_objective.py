from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aurora.infra.sp500_megarun.catalog_atlas_objective import (
    dominates_atlas,
    pareto_frontier,
    score_atlas_decisions,
)


def _sample() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    dates = pd.date_range("2009-01-01", periods=520, freq="B").to_numpy()
    spy = np.full(len(dates), -0.001, dtype=float)
    decisions = np.full(len(dates), -1.0, dtype=float)
    return decisions, spy, dates


def test_objective_counts_strictly_positive_complete_periods() -> None:
    decisions, spy, dates = _sample()
    result = score_atlas_decisions(decisions, spy, dates)
    assert result.total_weeks > 0
    assert result.total_months > 0
    assert result.positive_week_fraction == 1.0
    assert result.positive_month_fraction == 1.0
    assert result.joint_positive_above_spy_years == result.total_years


def test_zero_is_not_positive() -> None:
    decisions, spy, dates = _sample()
    decisions[:] = 0.0
    result = score_atlas_decisions(decisions, spy, dates)
    assert result.positive_weeks == 0
    assert result.positive_months == 0
    assert result.joint_positive_above_spy_years == 0


def test_dates_after_train_end_are_rejected() -> None:
    decisions, spy, dates = _sample()
    dates = dates.copy()
    dates[-1] = np.datetime64("2011-01-03")
    with pytest.raises(ValueError, match="TRAIN_END"):
        score_atlas_decisions(decisions, spy, dates)


def test_pareto_frontier_is_not_a_weighted_single_score() -> None:
    rows = [
        {"strategy_id": "b", "positive_week_fraction": 1.0, "positive_month_fraction": 0.5, "joint_positive_above_spy_fraction": 0.5},
        {"strategy_id": "a", "positive_week_fraction": 0.5, "positive_month_fraction": 1.0, "joint_positive_above_spy_fraction": 0.5},
        {"strategy_id": "c", "positive_week_fraction": 0.4, "positive_month_fraction": 0.4, "joint_positive_above_spy_fraction": 0.4},
    ]
    frontier = pareto_frontier(rows)
    assert [row["strategy_id"] for row in frontier] == ["a", "b"]
    assert dominates_atlas(
        score_atlas_decisions(*_sample()),
        score_atlas_decisions(np.ones(520), np.full(520, 0.001), _sample()[2]),
    )
