"""Causal, lexicographic objective for the SP500 official DEHB campaign."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from aurora.infra.sp500_long_short_daily.ledger import apply_positions


STRICT_GATE_MARGIN = 1e-12
TRADING_DAYS_PER_YEAR = 252.0


class ObjectiveContractError(ValueError):
    """Raised when a candidate cannot be scored causally and exactly."""


@dataclass(frozen=True)
class AnnualReturn:
    year: int
    strategy_return: float
    spy_return: float
    active_return: float
    passed: bool


@dataclass(frozen=True)
class CandidateScore:
    feasible: bool
    failed_years: tuple[int, ...]
    annual_returns: Mapping[int, AnnualReturn]
    annualized_strategy_return: float
    annualized_spy_return: float
    annualized_alpha: float
    week_count: int
    weeks_beating_spy: int
    weekly_spy_beat_rate: float
    constraint_shortfall: float
    dehb_fitness: float


@dataclass(frozen=True)
class LedgerObjectiveResult:
    score: CandidateScore
    positions: pd.Series
    strategy_returns: pd.Series
    spy_returns: pd.Series
    realized_at: pd.DatetimeIndex


def build_adjusted_open_total_return_ledger(
    prices: pd.DataFrame,
    *,
    allowed_end: str,
) -> pd.DataFrame:
    """Build SPY open-to-open total returns from the provider adjustment factor.

    ``adj_close / close`` carries the dividend and split adjustment. Applying
    the same factor to the raw open produces an adjusted-open series whose
    consecutive ratios include corporate actions without applying split events
    a second time. Event files remain a separate audit input and never enter a
    feature calculation.
    """

    required = {"date", "open", "high", "low", "close", "adj_close", "volume"}
    missing = sorted(required - set(prices.columns))
    if missing:
        if "adj_close" in missing:
            raise ObjectiveContractError("MISSING_SPY_ADJ_CLOSE")
        raise ObjectiveContractError(f"MISSING_SPY_LEDGER_COLUMNS:{','.join(missing)}")
    frame = prices.loc[:, sorted(required)].copy()
    try:
        frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    except (TypeError, ValueError) as exc:
        raise ObjectiveContractError("INVALID_SPY_LEDGER_DATE") from exc
    frame = frame.sort_values("date", kind="mergesort").set_index("date")
    if frame.empty or frame.index.has_duplicates:
        raise ObjectiveContractError("INVALID_SPY_LEDGER_DATES")
    if frame.index.max() > pd.Timestamp(allowed_end).normalize():
        raise ObjectiveContractError("SPY_LEDGER_DATE_AFTER_ALLOWED_END")
    numeric_columns = ("open", "high", "low", "close", "adj_close", "volume")
    try:
        for column in numeric_columns:
            frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
    except (TypeError, ValueError) as exc:
        raise ObjectiveContractError("NONNUMERIC_SPY_LEDGER_VALUE") from exc
    if not np.isfinite(frame.loc[:, numeric_columns].to_numpy()).all():
        raise ObjectiveContractError("NONFINITE_SPY_LEDGER_VALUE")
    if (frame.loc[:, ("open", "high", "low", "close", "adj_close")] <= 0).any().any():
        raise ObjectiveContractError("NONPOSITIVE_SPY_LEDGER_PRICE")
    if (frame["volume"] < 0).any():
        raise ObjectiveContractError("NEGATIVE_SPY_LEDGER_VOLUME")
    if (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any():
        raise ObjectiveContractError("INVALID_SPY_LEDGER_HIGH")
    if (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any():
        raise ObjectiveContractError("INVALID_SPY_LEDGER_LOW")

    adjustment_factor = frame["adj_close"] / frame["close"]
    adjusted_open = frame["open"] * adjustment_factor
    long_return = adjusted_open.shift(-1) / adjusted_open - 1.0
    finite_returns = long_return.dropna()
    if not np.isfinite(finite_returns.to_numpy()).all() or (finite_returns <= -1.0).any():
        raise ObjectiveContractError("INVALID_SPY_TOTAL_RETURN")
    frame["adjustment_factor"] = adjustment_factor
    frame["adjusted_open"] = adjusted_open
    frame["long_return"] = long_return
    frame["short_return"] = -long_return
    frame["tr_open"] = (
        (1.0 + long_return.fillna(0.0)).cumprod().shift(1).fillna(1.0)
    )
    frame["tr_close"] = frame["tr_open"] * frame["close"] / frame["open"]
    return frame


def _normalize_return_series(series: pd.Series, label: str) -> pd.Series:
    values = series.copy()
    try:
        values.index = pd.DatetimeIndex(pd.to_datetime(values.index)).normalize()
    except (TypeError, ValueError) as exc:
        raise ObjectiveContractError(f"INVALID_RETURN_INDEX:{label}") from exc
    if values.index.has_duplicates:
        raise ObjectiveContractError(f"DUPLICATE_RETURN_DATE:{label}")
    if not values.index.is_monotonic_increasing:
        raise ObjectiveContractError(f"UNSORTED_RETURN_DATE:{label}")
    try:
        numeric = pd.to_numeric(values, errors="raise").astype(float)
    except (TypeError, ValueError) as exc:
        raise ObjectiveContractError(f"NONNUMERIC_RETURN:{label}") from exc
    if not np.isfinite(numeric.to_numpy()).all():
        raise ObjectiveContractError(f"NONFINITE_RETURN:{label}")
    if (numeric <= -1.0).any():
        raise ObjectiveContractError(f"RETURN_LE_MINUS_ONE:{label}")
    return numeric


def _compounded_return(values: pd.Series) -> float:
    log_total = float(np.log1p(values.to_numpy()).sum())
    try:
        result = math.expm1(log_total)
    except OverflowError as exc:
        raise ObjectiveContractError("NONFINITE_COMPOUNDED_RETURN") from exc
    if not math.isfinite(result):
        raise ObjectiveContractError("NONFINITE_COMPOUNDED_RETURN")
    return result


def _annualized_return(values: pd.Series) -> float:
    if values.empty:
        raise ObjectiveContractError("EMPTY_RETURN_SERIES")
    annualized_log = float(np.log1p(values.to_numpy()).sum()) * (
        TRADING_DAYS_PER_YEAR / len(values)
    )
    try:
        result = math.expm1(annualized_log)
    except OverflowError as exc:
        raise ObjectiveContractError("NONFINITE_ANNUALIZED_RETURN") from exc
    if not math.isfinite(result):
        raise ObjectiveContractError("NONFINITE_ANNUALIZED_RETURN")
    return result


def _target_years(values: Sequence[int]) -> tuple[int, ...]:
    years = tuple(int(value) for value in values)
    if not years or len(set(years)) != len(years) or tuple(sorted(years)) != years:
        raise ObjectiveContractError("INVALID_TARGET_YEARS")
    return years


def score_realized_returns(
    strategy_returns: pd.Series,
    spy_returns: pd.Series,
    *,
    target_years: Sequence[int],
) -> CandidateScore:
    """Score returns timestamped at the opening where each result is realized."""

    strategy = _normalize_return_series(strategy_returns, "strategy")
    spy = _normalize_return_series(spy_returns, "spy")
    if not strategy.index.equals(spy.index):
        raise ObjectiveContractError("RETURN_INDEX_MISMATCH")
    years = _target_years(target_years)
    selected = strategy.index.year.astype(int)
    for year in years:
        if not bool((selected == year).any()):
            raise ObjectiveContractError(f"MISSING_TARGET_YEAR:{year}")
    mask = np.isin(selected, years)
    strategy = strategy.loc[mask]
    spy = spy.loc[mask]

    annual_returns: dict[int, AnnualReturn] = {}
    failed_years: list[int] = []
    shortfall = 0.0
    for year in years:
        year_mask = strategy.index.year == year
        strategy_year = _compounded_return(strategy.loc[year_mask])
        spy_year = _compounded_return(spy.loc[year_mask])
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

    strategy_annualized = _annualized_return(strategy)
    spy_annualized = _annualized_return(spy)
    weekly = pd.DataFrame({"strategy": strategy, "spy": spy})
    weekly["week"] = weekly.index.to_period("W-FRI")
    weekly_compounded = weekly.groupby("week", sort=True)[["strategy", "spy"]].agg(
        _compounded_return
    )
    weekly_wins = weekly_compounded["strategy"] > weekly_compounded["spy"]
    week_count = len(weekly_wins)
    weeks_beating = int(weekly_wins.sum())
    weekly_rate = weeks_beating / week_count

    feasible = not failed_years
    if feasible:
        dehb_fitness = -strategy_annualized
    else:
        normalized_shortfall = shortfall / (1.0 + shortfall)
        dehb_fitness = 1.0 + len(failed_years) + normalized_shortfall
    return CandidateScore(
        feasible=feasible,
        failed_years=tuple(failed_years),
        annual_returns=annual_returns,
        annualized_strategy_return=strategy_annualized,
        annualized_spy_return=spy_annualized,
        annualized_alpha=strategy_annualized - spy_annualized,
        week_count=week_count,
        weeks_beating_spy=weeks_beating,
        weekly_spy_beat_rate=weekly_rate,
        constraint_shortfall=shortfall,
        dehb_fitness=dehb_fitness,
    )


def candidate_rank_key(score: CandidateScore) -> tuple[float, ...]:
    """Exact archive order; smaller is better and annualized return stays primary."""

    if score.feasible:
        return (
            0.0,
            -score.annualized_strategy_return,
            -score.weekly_spy_beat_rate,
            -score.annualized_alpha,
        )
    return (
        1.0,
        float(len(score.failed_years)),
        score.constraint_shortfall,
        -score.annualized_strategy_return,
        -score.weekly_spy_beat_rate,
    )


def score_ledger_decisions(
    ledger: pd.DataFrame,
    decisions: pd.Series,
    *,
    target_years: Sequence[int],
    allowed_end: str,
) -> LedgerObjectiveResult:
    """Apply close decisions at the next open and score train-only realizations."""

    if "long_return" not in ledger:
        raise ObjectiveContractError("MISSING_LEDGER_LONG_RETURN")
    frame = ledger.copy()
    try:
        frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index)).normalize()
    except (TypeError, ValueError) as exc:
        raise ObjectiveContractError("INVALID_LEDGER_INDEX") from exc
    if frame.index.empty or frame.index.has_duplicates:
        raise ObjectiveContractError("INVALID_LEDGER_DATES")
    if not frame.index.is_monotonic_increasing:
        raise ObjectiveContractError("UNSORTED_LEDGER_DATES")
    boundary = pd.Timestamp(allowed_end).normalize()
    if frame.index.max() > boundary:
        raise ObjectiveContractError("OBJECTIVE_DATE_AFTER_ALLOWED_END")
    decision_dates = pd.DatetimeIndex(pd.to_datetime(decisions.index)).normalize()
    if len(decision_dates) and decision_dates.max() > boundary:
        raise ObjectiveContractError("OBJECTIVE_DATE_AFTER_ALLOWED_END")

    applied = apply_positions(frame, decisions)
    next_session = pd.Series(frame.index, index=frame.index).shift(-1)
    valid = applied["strategy_return"].notna() & next_session.notna()
    realized_at = pd.DatetimeIndex(next_session.loc[valid])
    strategy = pd.Series(
        applied.loc[valid, "strategy_return"].to_numpy(dtype=float),
        index=realized_at,
        name="strategy_return",
    )
    spy = pd.Series(
        applied.loc[valid, "long_return"].to_numpy(dtype=float),
        index=realized_at,
        name="spy_return",
    )
    score = score_realized_returns(strategy, spy, target_years=target_years)
    return LedgerObjectiveResult(
        score=score,
        positions=applied["position"].copy(),
        strategy_returns=strategy,
        spy_returns=spy,
        realized_at=realized_at,
    )


__all__ = [
    "AnnualReturn",
    "CandidateScore",
    "LedgerObjectiveResult",
    "ObjectiveContractError",
    "build_adjusted_open_total_return_ledger",
    "candidate_rank_key",
    "score_ledger_decisions",
    "score_realized_returns",
]
