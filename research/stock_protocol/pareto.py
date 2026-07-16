"""Authentic multi-objective Pareto fronts for finite portfolio metrics."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


def _validated_objectives(
    frame: pd.DataFrame,
    maximize: Sequence[str],
    minimize: Sequence[str],
) -> tuple[pd.DataFrame, list[str]]:
    objectives = list(maximize) + list(minimize)
    if not objectives:
        raise ValueError("at least one Pareto objective is required")
    missing = set(objectives) - set(frame.columns)
    if missing:
        raise ValueError(f"missing Pareto objectives: {sorted(missing)}")
    result = frame.copy()
    for column in objectives:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    finite = np.isfinite(result[objectives].to_numpy(dtype=float)).all(axis=1)
    return result.loc[finite].reset_index(drop=True), objectives


def pareto_frontier(
    frame: pd.DataFrame,
    *,
    maximize: Sequence[str],
    minimize: Sequence[str],
) -> pd.DataFrame:
    """Return rows not dominated across every declared objective."""

    valid, _ = _validated_objectives(frame, maximize, minimize)
    if valid.empty:
        return valid.assign(pareto_rank=pd.Series(dtype=int))
    values = valid[list(maximize) + list(minimize)].to_numpy(dtype=float)
    directions = np.array([1.0] * len(maximize) + [-1.0] * len(minimize))
    utility = values * directions
    keep = np.ones(len(valid), dtype=bool)
    for index in range(len(valid)):
        others = np.arange(len(valid)) != index
        no_worse = np.all(utility[others] >= utility[index], axis=1)
        strictly_better = np.any(utility[others] > utility[index], axis=1)
        if np.any(no_worse & strictly_better):
            keep[index] = False
    front = valid.loc[keep].copy()
    front["pareto_rank"] = 1
    return front.reset_index(drop=True)


def pareto_frontiers_by(
    frame: pd.DataFrame,
    *,
    group_columns: Sequence[str],
    maximize: Sequence[str],
    minimize: Sequence[str],
) -> pd.DataFrame:
    """Compute independent non-dominated fronts inside each requested group."""

    missing = set(group_columns) - set(frame.columns)
    if missing:
        raise ValueError(f"missing Pareto group columns: {sorted(missing)}")
    fronts = [
        pareto_frontier(group, maximize=maximize, minimize=minimize)
        for _, group in frame.groupby(list(group_columns), dropna=False, sort=True)
    ]
    non_empty = [front for front in fronts if not front.empty]
    if not non_empty:
        return pd.DataFrame(columns=[*frame.columns, "pareto_rank"])
    return pd.concat(non_empty, ignore_index=True)
