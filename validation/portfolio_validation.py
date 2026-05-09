# ruff: noqa: N806
"""Walk-forward validation for portfolio allocators.

- ``walk_forward_portfolio``: rolling train/test split, no embargo.
- ``purged_walk_forward_portfolio``: adds an embargo gap between train
  and test to handle overlapping labels (Lopez de Prado AFML Ch.7).

Each fold:
1. Fit the allocator on the train slice
2. Apply the resulting weights to the test slice
3. Record per-fold gross/net returns, variance, max drawdown.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from quantforge.portfolio.allocation import PortfolioOptimizer
from quantforge.portfolio.risk_measures import (
    max_drawdown,
    turnover_aware_net_return,
    variance,
)


@dataclass
class FoldResult:
    """Result of a single walk-forward fold."""
    fold: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    weights: np.ndarray
    metrics: dict[str, float] = field(default_factory=dict)


def walk_forward_portfolio(
    allocator: PortfolioOptimizer,
    returns: np.ndarray,
    train_bars: int,
    test_bars: int,
    step_bars: int | None = None,
    costs_bps: float = 0.0,
) -> list[FoldResult]:
    """Walk-forward portfolio fitting.

    Parameters
    ----------
    allocator
        A ``PortfolioOptimizer`` instance. Re-fit on each train slice.
    returns
        (T, N) return matrix.
    train_bars, test_bars
        Length of train and test windows.
    step_bars
        Step between fold starts. Defaults to ``test_bars``.
    costs_bps
        Round-trip transaction cost in bps for the net-return metric.

    Returns
    -------
    list[FoldResult]
    """
    R = _check_2d(returns)
    T, _ = R.shape
    if train_bars < 2:
        raise ValueError("train_bars must be >= 2")
    if test_bars < 1:
        raise ValueError("test_bars must be >= 1")
    step = int(step_bars) if step_bars is not None else int(test_bars)
    if step < 1:
        raise ValueError("step_bars must be >= 1")

    folds: list[FoldResult] = []
    fold = 0
    train_start = 0
    while True:
        train_end = train_start + train_bars
        test_start = train_end
        test_end = test_start + test_bars
        if test_end > T:
            break
        train = R[train_start:train_end]
        test = R[test_start:test_end]
        allocator.fit(train)
        w = allocator.predict()
        metrics = _fold_metrics(w, test, costs_bps)
        folds.append(
            FoldResult(
                fold=fold,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                weights=w,
                metrics=metrics,
            )
        )
        fold += 1
        train_start += step
    return folds


def purged_walk_forward_portfolio(
    allocator: PortfolioOptimizer,
    returns: np.ndarray,
    train_bars: int,
    test_bars: int,
    embargo_bars: int = 0,
    step_bars: int | None = None,
    costs_bps: float = 0.0,
) -> list[FoldResult]:
    """Walk-forward with an embargo gap between train and test.

    Use when labels overlap (e.g. multi-bar return targets) and the last
    ``embargo_bars`` of the train window leak information into the test
    window.
    """
    if embargo_bars < 0:
        raise ValueError("embargo_bars must be >= 0")
    R = _check_2d(returns)
    T, _ = R.shape
    if train_bars < 2:
        raise ValueError("train_bars must be >= 2")
    if test_bars < 1:
        raise ValueError("test_bars must be >= 1")
    step = int(step_bars) if step_bars is not None else int(test_bars)

    folds: list[FoldResult] = []
    fold = 0
    train_start = 0
    while True:
        train_end = train_start + train_bars
        # Embargo gap is BETWEEN train and test, so train is unchanged
        # and test starts ``embargo_bars`` later.
        test_start = train_end + embargo_bars
        test_end = test_start + test_bars
        if test_end > T:
            break
        train = R[train_start:train_end]
        test = R[test_start:test_end]
        allocator.fit(train)
        w = allocator.predict()
        metrics = _fold_metrics(w, test, costs_bps)
        folds.append(
            FoldResult(
                fold=fold,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                weights=w,
                metrics=metrics,
            )
        )
        fold += 1
        train_start += step
    return folds


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _check_2d(returns) -> np.ndarray:
    R = np.asarray(returns, dtype=float)
    if R.ndim == 1:
        R = R.reshape(-1, 1)
    if R.ndim != 2:
        raise ValueError(f"returns must be 1-D or 2-D, got {R.ndim}-D")
    return R


def _fold_metrics(
    weights: np.ndarray,
    test: np.ndarray,
    costs_bps: float,
) -> dict[str, float]:
    """Apply weights to the test window and compute metrics."""
    if weights.size == 0 or test.size == 0:
        return {
            "gross_return": 0.0,
            "net_return": 0.0,
            "variance": 0.0,
            "max_drawdown": 0.0,
        }
    if weights.shape[0] != test.shape[1]:
        raise ValueError(
            f"weights size {weights.shape[0]} != test cols {test.shape[1]}"
        )
    W = np.tile(weights, (test.shape[0], 1))
    summary = turnover_aware_net_return(W, test, costs_bps)
    port_gross = test @ weights
    return {
        "gross_return": summary["gross_return"],
        "net_return": summary["net_return"],
        "variance": variance(port_gross),
        "max_drawdown": max_drawdown(port_gross),
    }
