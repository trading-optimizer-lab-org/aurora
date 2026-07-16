"""Purged temporal validation contracts for the stock research protocol."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


LOCKED_START = pd.Timestamp("2021-01-01")
HOLDOUT_START = pd.Timestamp("2016-01-01")
HOLDOUT_END = pd.Timestamp("2020-12-31")


@dataclass(frozen=True)
class PurgedFold:
    fold_id: int
    mode: str
    role: str
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    train_purged_end: pd.Timestamp
    validation_start: pd.Timestamp
    validation_end: pd.Timestamp
    validation_purged_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    horizon_sessions: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _validated_dates(dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(pd.to_datetime(dates, errors="raise")).normalize()
    index = index.sort_values().unique()
    if len(index) == 0:
        raise ValueError("validation dates are empty")
    if index[-1] >= LOCKED_START:
        raise ValueError("validation dates cross locked boundary 2021-01-01")
    return index


def _first_on_or_after(dates: pd.DatetimeIndex, boundary: pd.Timestamp) -> pd.Timestamp:
    position = dates.searchsorted(boundary, side="left")
    if position >= len(dates):
        raise ValueError(f"no observation on or after {boundary.date()}")
    return pd.Timestamp(dates[position])


def _last_before(dates: pd.DatetimeIndex, boundary: pd.Timestamp) -> pd.Timestamp:
    position = dates.searchsorted(boundary, side="left") - 1
    if position < 0:
        raise ValueError(f"no observation before {boundary.date()}")
    return pd.Timestamp(dates[position])


def _purged_end(
    dates: pd.DatetimeIndex, next_period_start: pd.Timestamp, horizon_sessions: int
) -> pd.Timestamp:
    next_position = int(dates.searchsorted(next_period_start, side="left"))
    position = next_position - horizon_sessions - 1
    if position < 0:
        raise ValueError("not enough observations for requested purge horizon")
    return pd.Timestamp(dates[position])


def generate_purged_walk_forward(
    dates: pd.DatetimeIndex,
    train_years: int = 10,
    validation_years: int = 3,
    test_years: int = 1,
    horizon_sessions: int = 252,
    mode: str = "expanding",
    holdout_start: str = "2016-01-01",
) -> list[PurgedFold]:
    """Generate annual-step folds that never observe the final holdout."""

    index = _validated_dates(dates)
    if train_years < 1 or validation_years < 1 or test_years < 1:
        raise ValueError("walk-forward periods must be positive")
    if horizon_sessions < 1:
        raise ValueError("horizon_sessions must be positive")
    if mode not in {"expanding", "rolling"}:
        raise ValueError("mode must be expanding or rolling")
    holdout = pd.Timestamp(holdout_start).normalize()
    if holdout != HOLDOUT_START:
        raise ValueError("final holdout must start at 2016-01-01")
    first_year = int(index[0].year)
    first_validation_year = first_year + train_years
    folds: list[PurgedFold] = []
    fold_id = 0

    for validation_year in range(first_validation_year, holdout.year):
        validation_start_boundary = pd.Timestamp(f"{validation_year}-01-01")
        test_start_boundary = pd.Timestamp(
            f"{validation_year + validation_years}-01-01"
        )
        test_end_boundary = pd.Timestamp(
            f"{validation_year + validation_years + test_years}-01-01"
        )
        if test_end_boundary > holdout:
            break
        validation_start = _first_on_or_after(index, validation_start_boundary)
        test_start = _first_on_or_after(index, test_start_boundary)
        test_end = _last_before(index, test_end_boundary)
        train_start_boundary = (
            pd.Timestamp(f"{first_year}-01-01")
            if mode == "expanding"
            else pd.Timestamp(f"{validation_year - train_years}-01-01")
        )
        train_start = _first_on_or_after(index, train_start_boundary)
        train_end = _last_before(index, validation_start_boundary)
        validation_end = _last_before(index, test_start_boundary)
        train_purged_end = _purged_end(index, validation_start, horizon_sessions)
        validation_purged_end = _purged_end(index, test_start, horizon_sessions)
        if not (
            train_start <= train_purged_end < validation_start
            <= validation_purged_end < test_start <= test_end < holdout
        ):
            raise ValueError("walk-forward fold overlaps after purging")
        folds.append(
            PurgedFold(
                fold_id=fold_id,
                mode=mode,
                role="walk_forward_test",
                train_start=train_start,
                train_end=train_end,
                train_purged_end=train_purged_end,
                validation_start=validation_start,
                validation_end=validation_end,
                validation_purged_end=validation_purged_end,
                test_start=test_start,
                test_end=test_end,
                horizon_sessions=horizon_sessions,
            )
        )
        fold_id += 1
    if not folds:
        raise ValueError("no complete pre-holdout walk-forward folds")
    return folds


def final_holdout_contract(dates: pd.DatetimeIndex) -> dict[str, object]:
    """Describe the one permitted, post-freeze pre-locked evaluation."""

    index = _validated_dates(dates)
    observed = index[(index >= HOLDOUT_START) & (index <= HOLDOUT_END)]
    if observed.empty:
        raise ValueError("final holdout observations are unavailable")
    return {
        "role": "final_pre_locked_holdout",
        "start": HOLDOUT_START.date().isoformat(),
        "end": HOLDOUT_END.date().isoformat(),
        "observations": int(len(observed)),
        "evaluation_count": 1,
        "optimization_allowed": False,
        "selection_allowed": False,
        "locked_opened": False,
    }
