"""Retraining cadence simulator.

Simulates periodic strategy re-optimization. At each checkpoint:
  1. Fit strategy on rolling training window of `train_window_days` past bars.
  2. Run fitted strategy live OOS for next `retrain_cadence_days` bars.
  3. Move forward by cadence; refit; repeat.

Concatenated OOS returns approximate the realized track record of a
periodically-retrained quant. Per-fold metrics expose decay across folds via
a linear regression of Calmar over time.
"""
from __future__ import annotations
import warnings
from dataclasses import dataclass, field
from typing import Callable
import numpy as np
import pandas as pd

from aurora.core.engine import run_backtest
from aurora.core.costs import CostModel, ZERO_costs
from aurora.core.metrics import compute_metrics


@dataclass
class RetrainResult:
    cadence_days: int
    n_retrains: int
    fold_metrics: list = field(default_factory=list)
    # each entry: (start_date_str, end_date_str, calmar, sharpe, mdd)
    avg_calmar: float = 0.0
    median_calmar: float = 0.0
    calmar_decay_per_year: float = 0.0  # slope of Calmar vs fold time (per year)
    # ``overall_*`` fields below treat the concatenated OOS chunks as a single
    # contiguous return stream. This is a CONVENTION CHOICE: between two
    # consecutive folds the strategy is refit, so the bar-to-bar transition
    # at fold boundaries does NOT correspond to a real overnight return —
    # there is a discontinuity injected by the refit. Aggregated MDD in
    # particular can be optimistic because drawdowns are reset at the fold
    # boundary in the underlying paths but not in the concatenation. Use
    # ``avg_*`` / ``median_*`` (per-fold) when fold-level fidelity matters
    # and use ``overall_*`` only as a coarse "live track record" proxy.
    overall_calmar: float = 0.0
    overall_sharpe: float = 0.0
    overall_mdd: float = 0.0
    # Aggregates computed per-fold then averaged. These avoid treating the
    # boundary jumps as real returns and are the recommended cross-fold
    # summary statistic for cadence-tuning decisions.
    avg_sharpe: float = 0.0
    avg_mdd: float = 0.0


def simulate_retraining(strategy_optimizer: Callable,
                        prices: pd.Series,
                        costs: CostModel = ZERO_costs,
                        train_window_days: int = 504,
                        retrain_cadence_days: int = 63,
                        ppy: int = 252,
                        seed_name: str = "retrain",
                        allow_overlap: bool = False) -> RetrainResult:
    """Simulate periodic strategy re-optimization.

    Args:
        strategy_optimizer: callable(train_prices: pd.Series) -> Strategy.
                            Optimizes on train_prices, returns fitted Strategy
                            whose .signals(prices) is causal.
        prices: pd.Series full price history with DatetimeIndex.
        costs: CostModel applied during OOS evaluation.
        train_window_days: rolling training window length (bars).
        retrain_cadence_days: interval between refits and OOS slice length.
        ppy: periods per year for metric annualization.
        seed_name: cosmetic label for downstream consumers.
        allow_overlap: if False (default) raise ValueError when
            ``retrain_cadence_days < train_window_days`` (consecutive train
            windows would overlap, biasing the decay estimator). If True,
            keep the legacy sliding-window behavior and emit a
            DeprecationWarning.

    Returns:
        RetrainResult with per-fold metrics and aggregate statistics.

    Raises:
        TypeError: if prices not a pd.Series with DatetimeIndex.
        ValueError: if prices length < train_window_days + retrain_cadence_days
                    (cannot run a single fold), or if cadence < window and
                    ``allow_overlap=False``.
    """
    if not isinstance(prices, pd.Series):
        raise TypeError("prices must be pd.Series with DatetimeIndex")
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise TypeError("prices index must be DatetimeIndex")
    if train_window_days < 2:
        raise ValueError(f"train_window_days must be >= 2, got {train_window_days}")
    if retrain_cadence_days < 1:
        raise ValueError(f"retrain_cadence_days must be >= 1, got {retrain_cadence_days}")

    if retrain_cadence_days < train_window_days:
        if not allow_overlap:
            raise ValueError(
                f"retrain_cadence_days={retrain_cadence_days} < "
                f"train_window_days={train_window_days}: consecutive train "
                f"windows would overlap. Pass allow_overlap=True to keep the "
                f"legacy sliding-window behavior."
            )
        warnings.warn(
            f"allow_overlap=True with cadence ({retrain_cadence_days}) < "
            f"window ({train_window_days}); train windows overlap, biasing the "
            f"calmar_decay estimator.",
            DeprecationWarning,
            stacklevel=2,
        )

    n = len(prices)
    if n < train_window_days + retrain_cadence_days:
        raise ValueError(
            f"insufficient bars: need at least train_window_days + retrain_cadence_days"
            f" = {train_window_days + retrain_cadence_days}, got {n}"
        )

    fold_rows: list = []
    oos_returns_chunks: list[np.ndarray] = []

    start_idx = train_window_days
    while start_idx + retrain_cadence_days <= n:
        train_data = prices.iloc[start_idx - train_window_days:start_idx]
        fitted = strategy_optimizer(train_data)
        oos_data = prices.iloc[start_idx:start_idx + retrain_cadence_days]

        res = run_backtest(oos_data, fitted.signals, costs=costs, ppy=ppy)

        # exclude first net return (always 0 due to weight-shift convention)
        oos_returns_chunks.append(res.rets[1:].copy())

        fold_rows.append((
            oos_data.index[0].strftime("%Y-%m-%d"),
            oos_data.index[-1].strftime("%Y-%m-%d"),
            float(res.metrics.calmar),
            float(res.metrics.sharpe),
            float(res.metrics.mdd),
        ))

        start_idx += retrain_cadence_days

    n_retrains = len(fold_rows)
    if n_retrains == 0:
        # Should not occur given precondition above, but defensive.
        return RetrainResult(
            cadence_days=retrain_cadence_days,
            n_retrains=0,
            fold_metrics=[],
        )

    calmars = np.array([row[2] for row in fold_rows], dtype=float)
    sharpes_per_fold = np.array([row[3] for row in fold_rows], dtype=float)
    mdds_per_fold = np.array([row[4] for row in fold_rows], dtype=float)
    avg_calmar = float(np.mean(calmars))
    median_calmar = float(np.median(calmars))
    avg_sharpe = float(np.mean(sharpes_per_fold))
    avg_mdd = float(np.mean(mdds_per_fold))

    # Decay slope: linear regression of Calmar vs fold time in years.
    # x = fold midpoint in years from first fold.
    if n_retrains >= 2:
        years_per_fold = retrain_cadence_days / float(ppy)
        x = np.arange(n_retrains, dtype=float) * years_per_fold
        # least squares slope (covariance/variance form)
        x_mean = x.mean()
        c_mean = calmars.mean()
        denom = float(((x - x_mean) ** 2).sum())
        if denom > 1e-12:
            slope = float(((x - x_mean) * (calmars - c_mean)).sum() / denom)
        else:
            slope = 0.0
    else:
        slope = 0.0

    # Aggregate concatenated OOS metrics
    all_oos = np.concatenate(oos_returns_chunks) if oos_returns_chunks else np.array([])
    if len(all_oos) >= 2:
        agg = compute_metrics(all_oos, ppy=ppy)
        overall_calmar = float(agg.calmar)
        overall_sharpe = float(agg.sharpe)
        overall_mdd = float(agg.mdd)
    else:
        overall_calmar = 0.0
        overall_sharpe = 0.0
        overall_mdd = 0.0

    return RetrainResult(
        cadence_days=retrain_cadence_days,
        n_retrains=n_retrains,
        fold_metrics=fold_rows,
        avg_calmar=avg_calmar,
        median_calmar=median_calmar,
        calmar_decay_per_year=slope,
        overall_calmar=overall_calmar,
        overall_sharpe=overall_sharpe,
        overall_mdd=overall_mdd,
        avg_sharpe=avg_sharpe,
        avg_mdd=avg_mdd,
    )
