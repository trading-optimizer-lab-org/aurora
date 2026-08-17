"""The three non-weighted objectives used by the static Atlas reducer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class AtlasObjectiveResult:
    positive_weeks: int
    total_weeks: int
    positive_week_fraction: float
    positive_months: int
    total_months: int
    positive_month_fraction: float
    joint_positive_above_spy_years: int
    total_years: int
    joint_positive_above_spy_fraction: float
    annual_rows: tuple[dict[str, float | int | bool], ...]


def _compound(values: Sequence[float]) -> float:
    values_array = np.asarray(values, dtype=np.float64)
    if values_array.size == 0:
        return 0.0
    if np.any(values_array <= -1.0) or not np.isfinite(values_array).all():
        raise ValueError("ATLAS_OBJECTIVE_RETURN_INVALID")
    return float(np.expm1(np.log1p(values_array).sum()))


def _complete_period_rows(
    dates: pd.DatetimeIndex,
    returns: np.ndarray,
    *,
    frequency: str,
) -> list[tuple[object, float]]:
    periods = dates.to_period(frequency)
    groups: list[tuple[object, float]] = []
    for period in pd.unique(periods):
        values = returns[periods == period]
        groups.append((period, _compound(values)))
    # The first and last calendar buckets may be partial at the train
    # boundary.  Do not count either unless there is only one bucket; in that
    # case there is no complete period to claim.
    if len(groups) <= 2:
        return []
    return groups[1:-1]


def score_atlas_decisions(
    decisions: np.ndarray,
    spy_returns: np.ndarray,
    dates: np.ndarray,
    *,
    train_end: str = "2010-12-31",
) -> AtlasObjectiveResult:
    """Score daily positions against aligned SPY returns, train-only.

    ``decisions`` contains positions in ``{-1, 0, +1}``.  A zero is a valid
    flat position; missing values are rejected rather than silently filled.
    """

    positions = np.asarray(decisions, dtype=np.float64)
    spy = np.asarray(spy_returns, dtype=np.float64)
    index = pd.DatetimeIndex(pd.to_datetime(np.asarray(dates))).normalize()
    if positions.ndim != 1 or spy.ndim != 1 or len(index) != len(positions) or len(spy) != len(positions):
        raise ValueError("ATLAS_OBJECTIVE_ALIGNED_INPUTS_REQUIRED")
    if index.empty or index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError("ATLAS_OBJECTIVE_DATES_INVALID")
    if index.max() > pd.Timestamp(train_end).normalize():
        raise ValueError("ATLAS_OBJECTIVE_DATE_AFTER_TRAIN_END")
    if not np.isfinite(positions).all() or not np.isin(positions, (-1.0, 0.0, 1.0)).all():
        raise ValueError("ATLAS_OBJECTIVE_DECISIONS_INVALID")
    if not np.isfinite(spy).all() or np.any(spy <= -1.0):
        raise ValueError("ATLAS_OBJECTIVE_SPY_RETURNS_INVALID")
    strategy = positions * spy
    weekly_strategy = _complete_period_rows(index, strategy, frequency="W-FRI")
    weekly_spy = _complete_period_rows(index, spy, frequency="W-FRI")
    monthly_strategy = _complete_period_rows(index, strategy, frequency="M")
    annual_periods = index.to_period("Y")
    annual_rows: list[dict[str, float | int | bool]] = []
    for year in pd.unique(annual_periods):
        mask = annual_periods == year
        strategy_return = _compound(strategy[mask])
        spy_return = _compound(spy[mask])
        annual_rows.append(
            {
                "year": int(year.year),
                "strategy_return": strategy_return,
                "spy_return": spy_return,
                "joint_positive_above_spy": bool(
                    strategy_return > 0.0 and strategy_return > spy_return
                ),
            }
        )
    positive_weeks = sum(value > 0.0 for _, value in weekly_strategy)
    positive_months = sum(value > 0.0 for _, value in monthly_strategy)
    joint_years = sum(bool(row["joint_positive_above_spy"]) for row in annual_rows)
    return AtlasObjectiveResult(
        positive_weeks=positive_weeks,
        total_weeks=len(weekly_strategy),
        positive_week_fraction=positive_weeks / len(weekly_strategy) if weekly_strategy else 0.0,
        positive_months=positive_months,
        total_months=len(monthly_strategy),
        positive_month_fraction=positive_months / len(monthly_strategy) if monthly_strategy else 0.0,
        joint_positive_above_spy_years=joint_years,
        total_years=len(annual_rows),
        joint_positive_above_spy_fraction=joint_years / len(annual_rows) if annual_rows else 0.0,
        annual_rows=tuple(annual_rows),
    )


def dominates_atlas(a: AtlasObjectiveResult, b: AtlasObjectiveResult) -> bool:
    """Return true when ``a`` is no worse on every objective and better on one."""

    left = (
        a.positive_week_fraction,
        a.positive_month_fraction,
        a.joint_positive_above_spy_fraction,
    )
    right = (
        b.positive_week_fraction,
        b.positive_month_fraction,
        b.joint_positive_above_spy_fraction,
    )
    return all(x >= y for x, y in zip(left, right, strict=True)) and any(
        x > y for x, y in zip(left, right, strict=True)
    )


def _row_values(row: Mapping[str, object]) -> tuple[float, float, float]:
    return (
        float(row["positive_week_fraction"]),
        float(row["positive_month_fraction"]),
        float(row["joint_positive_above_spy_fraction"]),
    )


def pareto_frontier(rows: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    """Keep non-dominated rows in deterministic strategy-id order."""

    result: list[Mapping[str, object]] = []
    for index, row in enumerate(rows):
        values = _row_values(row)
        dominated = False
        for other_index, other in enumerate(rows):
            if index == other_index:
                continue
            other_values = _row_values(other)
            if all(x >= y for x, y in zip(other_values, values, strict=True)) and any(
                x > y for x, y in zip(other_values, values, strict=True)
            ):
                dominated = True
                break
        if not dominated:
            result.append(row)
    return sorted(result, key=lambda row: str(row.get("strategy_id", "")))


__all__ = [
    "AtlasObjectiveResult",
    "dominates_atlas",
    "pareto_frontier",
    "score_atlas_decisions",
]
