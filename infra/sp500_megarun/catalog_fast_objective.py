"""Precomputed train-only objective that preserves the frozen pandas result."""

from __future__ import annotations

from dataclasses import dataclass
import math
from collections.abc import Sequence

import numpy as np
import pandas as pd

from aurora.infra.sp500_megarun.dehb_objective import (
    AnnualReturn,
    CandidateScore,
    STRICT_GATE_MARGIN,
    TRADING_DAYS_PER_YEAR,
)


def _compounded(values: np.ndarray) -> float:
    return math.expm1(float(np.log1p(values).sum()))


def _annualized(values: np.ndarray) -> float:
    return math.expm1(
        float(np.log1p(values).sum()) * (TRADING_DAYS_PER_YEAR / len(values))
    )


@dataclass(frozen=True)
class FastObjectiveResult:
    score: CandidateScore
    positions: pd.Series
    strategy_returns: pd.Series
    spy_returns: pd.Series
    realized_at: pd.DatetimeIndex
    weekly_calendar_metrics: dict[str, int | float]


class FastTrainObjective:
    """Validate immutable ledger state once and score many decision paths."""

    def __init__(
        self,
        ledger: pd.DataFrame,
        *,
        target_years: Sequence[int],
        allowed_end: str,
    ) -> None:
        if "long_return" not in ledger:
            raise ValueError("MISSING_LEDGER_LONG_RETURN")
        index = pd.DatetimeIndex(pd.to_datetime(ledger.index)).normalize()
        if (
            index.empty
            or index.has_duplicates
            or not index.is_monotonic_increasing
            or index.max() > pd.Timestamp(allowed_end).normalize()
        ):
            raise ValueError("CATALOG_FAST_OBJECTIVE_LEDGER_INVALID")
        years = tuple(int(value) for value in target_years)
        if not years or tuple(sorted(set(years))) != years:
            raise ValueError("INVALID_TARGET_YEARS")
        long_returns = pd.to_numeric(ledger["long_return"], errors="raise").to_numpy(
            dtype=np.float64
        )
        valid_indices = np.flatnonzero(
            np.isfinite(long_returns) & (np.arange(len(index)) < len(index) - 1)
        )
        if not valid_indices.size:
            raise ValueError("CATALOG_FAST_OBJECTIVE_EMPTY")
        realized_at = pd.DatetimeIndex(index[valid_indices + 1])
        realized_years = realized_at.year.astype(int)
        score_selector = np.isin(realized_years, years)
        score_years = realized_years[score_selector]
        year_masks = tuple(score_years == year for year in years)
        if any(not bool(mask.any()) for mask in year_masks):
            raise ValueError("CATALOG_FAST_OBJECTIVE_YEAR_MISSING")
        spy_returns = long_returns[valid_indices]
        score_spy_returns = spy_returns[score_selector]
        score_periods = realized_at[score_selector].to_period("W-FRI").asi8
        score_week_starts = np.r_[
            0,
            np.flatnonzero(score_periods[1:] != score_periods[:-1]) + 1,
        ]
        calendar_periods = realized_at.to_period("W-FRI").asi8
        calendar_week_starts = np.r_[
            0,
            np.flatnonzero(calendar_periods[1:] != calendar_periods[:-1]) + 1,
        ]
        self._ledger_index = index
        self._allowed_end = pd.Timestamp(allowed_end).normalize()
        self._long_returns = long_returns
        self._valid_indices = valid_indices
        self._realized_at = realized_at
        self._years = years
        self._score_selector = score_selector
        self._year_masks = year_masks
        self._spy_returns = spy_returns
        self._score_spy_returns = score_spy_returns
        self._spy_annual = tuple(
            _compounded(score_spy_returns[mask]) for mask in year_masks
        )
        self._spy_annualized = _annualized(score_spy_returns)
        self._score_week_starts = score_week_starts
        self._score_spy_weekly = np.expm1(
            np.add.reduceat(np.log1p(score_spy_returns), score_week_starts)
        )
        self._calendar_week_starts = calendar_week_starts
        self._calendar_spy_weekly = np.expm1(
            np.add.reduceat(np.log1p(spy_returns), calendar_week_starts)
        )

    def score(self, decisions: pd.Series) -> FastObjectiveResult:
        decision_dates = pd.DatetimeIndex(pd.to_datetime(decisions.index)).normalize()
        if len(decision_dates) and decision_dates.max() > self._allowed_end:
            raise ValueError("OBJECTIVE_DATE_AFTER_ALLOWED_END")
        aligned = decisions.reindex(self._ledger_index).to_numpy(dtype=np.float64)
        finite = np.isfinite(aligned)
        if not np.isin(aligned[finite], (-1.0, 1.0)).all():
            raise ValueError("CATALOG_FAST_OBJECTIVE_DECISION_INVALID")
        signals = np.nan_to_num(aligned, nan=0.0)
        source = np.maximum.accumulate(
            np.where(signals != 0.0, np.arange(signals.size), -1)
        )
        positions = np.ones(signals.size, dtype=np.int8)
        previous_source = source[:-1]
        available = previous_source >= 0
        positions[1:][available] = signals[previous_source[available]].astype(np.int8)
        strategy_values = (
            positions[self._valid_indices].astype(np.float64) * self._spy_returns
        )
        score_strategy_values = strategy_values[self._score_selector]

        annual_returns: dict[int, AnnualReturn] = {}
        failed_years: list[int] = []
        shortfall = 0.0
        for year, mask, spy_year in zip(
            self._years,
            self._year_masks,
            self._spy_annual,
            strict=True,
        ):
            strategy_year = _compounded(score_strategy_values[mask])
            active_year = strategy_year - spy_year
            passed = strategy_year > 0.0 and active_year > 0.0
            if not passed:
                failed_years.append(year)
                shortfall += max(0.0, STRICT_GATE_MARGIN - strategy_year)
                shortfall += max(0.0, STRICT_GATE_MARGIN - active_year)
            annual_returns[year] = AnnualReturn(
                year=year,
                strategy_return=strategy_year,
                spy_return=spy_year,
                active_return=active_year,
                passed=passed,
            )

        strategy_annualized = _annualized(score_strategy_values)
        score_strategy_weekly = np.expm1(
            np.add.reduceat(
                np.log1p(score_strategy_values),
                self._score_week_starts,
            )
        )
        weekly_wins = score_strategy_weekly > self._score_spy_weekly
        week_count = int(score_strategy_weekly.size)
        weeks_beating = int(weekly_wins.sum())
        feasible = not failed_years
        if feasible:
            dehb_fitness = -strategy_annualized
        else:
            normalized_shortfall = shortfall / (1.0 + shortfall)
            dehb_fitness = 1.0 + len(failed_years) + normalized_shortfall
        score = CandidateScore(
            feasible=feasible,
            failed_years=tuple(failed_years),
            annual_returns=annual_returns,
            annualized_strategy_return=strategy_annualized,
            annualized_spy_return=self._spy_annualized,
            annualized_alpha=strategy_annualized - self._spy_annualized,
            week_count=week_count,
            weeks_beating_spy=weeks_beating,
            weekly_spy_beat_rate=weeks_beating / week_count,
            constraint_shortfall=shortfall,
            dehb_fitness=dehb_fitness,
        )
        strategy_returns = pd.Series(
            strategy_values,
            index=self._realized_at,
            name="strategy_return",
        )
        spy_returns = pd.Series(
            self._spy_returns,
            index=self._realized_at,
            name="spy_return",
        )
        calendar_strategy_weekly = np.expm1(
            np.add.reduceat(
                np.log1p(strategy_values),
                self._calendar_week_starts,
            )
        )
        positive_weeks = calendar_strategy_weekly > 0.0
        calendar_wins = calendar_strategy_weekly > self._calendar_spy_weekly
        winning_or_positive = calendar_wins | positive_weeks
        calendar_week_count = int(calendar_strategy_weekly.size)
        return FastObjectiveResult(
            score=score,
            positions=pd.Series(
                positions,
                index=self._ledger_index,
                name="position",
            ),
            strategy_returns=strategy_returns,
            spy_returns=spy_returns,
            realized_at=self._realized_at,
            weekly_calendar_metrics={
                "week_count": calendar_week_count,
                "positive_weeks": int(positive_weeks.sum()),
                "weeks_beating_spy": int(calendar_wins.sum()),
                "winning_or_positive_weeks": int(winning_or_positive.sum()),
                "weekly_winning_or_positive_rate": float(
                    winning_or_positive.sum() / calendar_week_count
                ),
            },
        )


__all__ = ["FastObjectiveResult", "FastTrainObjective"]
