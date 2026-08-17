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


@dataclass(frozen=True)
class SparsePointInTimePortfolioV1:
    row_offsets: np.ndarray
    asset_indices: np.ndarray
    nonzero_weights: np.ndarray
    active_asset_count: np.ndarray
    date_count: int
    asset_count: int
    max_active_assets: int
    validation_opened: bool = False
    locked_opened: bool = False

    @property
    def nonzero_weight_count(self) -> int:
        return int(self.nonzero_weights.size)

    @property
    def storage_bytes(self) -> int:
        return int(
            self.row_offsets.nbytes
            + self.asset_indices.nbytes
            + self.nonzero_weights.nbytes
            + self.active_asset_count.nbytes
        )

    def to_dense(self) -> np.ndarray:
        dense = np.zeros((self.date_count, self.asset_count), dtype=np.float64)
        for date_index in range(self.date_count):
            start = int(self.row_offsets[date_index])
            end = int(self.row_offsets[date_index + 1])
            dense[date_index, self.asset_indices[start:end]] = self.nonzero_weights[
                start:end
            ]
        return dense


def build_sparse_point_in_time_portfolio(
    signals: np.ndarray,
    membership: np.ndarray,
    *,
    top_count: int,
    bottom_count: int,
) -> SparsePointInTimePortfolioV1:
    """Rank only contemporaneous members and retain date-major sparse weights."""

    values = np.asarray(signals, dtype=np.float64)
    active = np.asarray(membership, dtype=bool)
    if (
        values.ndim != 2
        or active.shape != values.shape
        or not np.isfinite(values[active]).all()
    ):
        raise ValueError("CROSS_SECTIONAL_INPUT_INVALID")
    if top_count < 1 or bottom_count < 1:
        raise ValueError("CROSS_SECTIONAL_SELECTION_INVALID")

    counts = active.sum(axis=1).astype(np.int32, copy=False)
    row_offsets = np.zeros(values.shape[0] + 1, dtype=np.int64)
    selected_indices: list[np.ndarray] = []
    selected_weights: list[np.ndarray] = []
    required = top_count + bottom_count
    for date_index in range(values.shape[0]):
        eligible = np.flatnonzero(active[date_index])
        if eligible.size >= required:
            ordered = eligible[
                np.argsort(values[date_index, eligible], kind="stable")
            ]
            bottom = ordered[:bottom_count]
            top = ordered[-top_count:]
            selected_indices.append(np.concatenate((bottom, top)))
            selected_weights.append(
                np.concatenate(
                    (
                        np.full(bottom_count, -1.0 / bottom_count),
                        np.full(top_count, 1.0 / top_count),
                    )
                )
            )
        row_offsets[date_index + 1] = row_offsets[date_index] + (
            required if eligible.size >= required else 0
        )

    index_dtype = np.uint16 if values.shape[1] <= np.iinfo(np.uint16).max else np.uint32
    asset_indices = (
        np.concatenate(selected_indices).astype(index_dtype, copy=False)
        if selected_indices
        else np.empty(0, dtype=index_dtype)
    )
    nonzero_weights = (
        np.concatenate(selected_weights).astype(np.float64, copy=False)
        if selected_weights
        else np.empty(0, dtype=np.float64)
    )
    return SparsePointInTimePortfolioV1(
        row_offsets=row_offsets,
        asset_indices=asset_indices,
        nonzero_weights=nonzero_weights,
        active_asset_count=counts,
        date_count=values.shape[0],
        asset_count=values.shape[1],
        max_active_assets=int(counts.max(initial=0)),
    )


def build_point_in_time_portfolio(
    signals: np.ndarray,
    membership: np.ndarray,
    *,
    top_count: int,
    bottom_count: int,
) -> PointInTimePortfolioV1:
    sparse = build_sparse_point_in_time_portfolio(
        signals,
        membership,
        top_count=top_count,
        bottom_count=bottom_count,
    )
    return PointInTimePortfolioV1(
        weights=sparse.to_dense(),
        active_asset_count=sparse.active_asset_count,
        max_active_assets=sparse.max_active_assets,
    )


__all__ = [
    "PointInTimePortfolioV1",
    "SparsePointInTimePortfolioV1",
    "build_point_in_time_portfolio",
    "build_sparse_point_in_time_portfolio",
]
