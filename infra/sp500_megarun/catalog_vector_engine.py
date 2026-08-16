"""Block-vectorized exact position, return and annual-metric evaluation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class VectorEvaluationV1:
    annualized_return: np.ndarray
    annual_returns: np.ndarray
    years: tuple[int, ...]
    position_hashes: tuple[str, ...]
    unique_position_count: int
    behavior_equivalence_hits: int
    validation_opened: bool = False
    locked_opened: bool = False


def _validate(
    decisions: np.ndarray,
    spy_returns: np.ndarray,
    years: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    checked = np.ascontiguousarray(decisions, dtype=np.int8)
    returns = np.asarray(spy_returns, dtype=np.float64)
    checked_years = np.asarray(years, dtype=np.int32)
    if checked.ndim != 2 or checked.shape[1] != returns.size:
        raise ValueError("CATALOG_VECTOR_SHAPE_INVALID")
    if checked_years.shape != returns.shape or not np.isfinite(returns).all():
        raise ValueError("CATALOG_VECTOR_INPUT_INVALID")
    if not np.isin(checked, (-1, 0, 1)).all():
        raise ValueError("CATALOG_VECTOR_DECISION_INVALID")
    if checked_years.size and int(checked_years.max()) > 2010:
        raise ValueError("CATALOG_PROTECTED_PERIOD_OPENED")
    return checked, returns, checked_years


def _positions_vectorized(decisions: np.ndarray) -> np.ndarray:
    column = np.arange(decisions.shape[1], dtype=np.int64)[None, :]
    nonzero_indices = np.where(decisions != 0, column, -1)
    source_indices = np.maximum.accumulate(nonzero_indices, axis=1)
    padded = np.concatenate(
        [np.zeros((decisions.shape[0], 1), dtype=np.int8), decisions],
        axis=1,
    )
    positions = np.take_along_axis(padded, source_indices + 1, axis=1)
    lagged = np.zeros_like(positions)
    lagged[:, 1:] = positions[:, :-1]
    return lagged


def _position_hashes(positions: np.ndarray) -> tuple[str, ...]:
    return tuple(
        hashlib.sha256(b"catalog-position-v1\0" + row.tobytes()).hexdigest()
        for row in positions
    )


def _metrics(
    positions: np.ndarray,
    spy_returns: np.ndarray,
    years: np.ndarray,
) -> VectorEvaluationV1:
    strategy_returns = positions * spy_returns[None, :]
    unique_years = tuple(int(value) for value in np.unique(years))
    annual = np.column_stack(
        [
            np.prod(1.0 + strategy_returns[:, years == year], axis=1) - 1.0
            for year in unique_years
        ]
    )
    total_growth = np.prod(1.0 + strategy_returns, axis=1)
    annualized = np.power(total_growth, 252.0 / strategy_returns.shape[1]) - 1.0
    hashes = _position_hashes(positions)
    unique_count = len(set(hashes))
    return VectorEvaluationV1(
        annualized_return=annualized,
        annual_returns=annual,
        years=unique_years,
        position_hashes=hashes,
        unique_position_count=unique_count,
        behavior_equivalence_hits=len(hashes) - unique_count,
    )


def evaluate_signal_block(
    decisions: np.ndarray,
    spy_returns: np.ndarray,
    years: np.ndarray,
) -> VectorEvaluationV1:
    checked, returns, checked_years = _validate(decisions, spy_returns, years)
    return _metrics(_positions_vectorized(checked), returns, checked_years)


def scalar_reference(
    decisions: np.ndarray,
    spy_returns: np.ndarray,
    years: np.ndarray,
) -> VectorEvaluationV1:
    checked, returns, checked_years = _validate(decisions, spy_returns, years)
    positions = np.zeros_like(checked)
    for row_index, row in enumerate(checked):
        current = np.int8(0)
        for column_index, decision in enumerate(row):
            positions[row_index, column_index] = current
            if decision != 0:
                current = decision
    return _metrics(positions, returns, checked_years)


__all__ = ["VectorEvaluationV1", "evaluate_signal_block", "scalar_reference"]
