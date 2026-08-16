"""Point-in-time cross-sectional ranking and sparse long-short weights."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PointInTimePortfolioV1:
    weights: np.ndarray
    active_asset_count: np.ndarray
    max_active_assets: int
    validation_opened: bool = False
    locked_opened: bool = False


def build_point_in_time_portfolio(
    signals: np.ndarray,
    membership: np.ndarray,
    *,
    top_count: int,
    bottom_count: int,
) -> PointInTimePortfolioV1:
    values = np.asarray(signals, dtype=np.float64)
    active = np.asarray(membership, dtype=bool)
    if values.ndim != 2 or active.shape != values.shape or not np.isfinite(values).all():
        raise ValueError("CROSS_SECTIONAL_INPUT_INVALID")
    if top_count < 1 or bottom_count < 1:
        raise ValueError("CROSS_SECTIONAL_SELECTION_INVALID")
    weights = np.zeros_like(values)
    counts = active.sum(axis=1)
    for date_index in range(values.shape[0]):
        eligible = np.flatnonzero(active[date_index])
        required = top_count + bottom_count
        if eligible.size < required:
            continue
        ordered = eligible[
            np.argsort(values[date_index, eligible], kind="stable")
        ]
        bottom = ordered[:bottom_count]
        top = ordered[-top_count:]
        weights[date_index, bottom] = -1.0 / bottom_count
        weights[date_index, top] = 1.0 / top_count
    return PointInTimePortfolioV1(
        weights=weights,
        active_asset_count=counts,
        max_active_assets=int(counts.max(initial=0)),
    )


__all__ = ["PointInTimePortfolioV1", "build_point_in_time_portfolio"]
