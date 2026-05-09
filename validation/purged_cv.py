"""Purged K-Fold cross-validation with embargo.

Source: Lopez de Prado 'Advances in Financial Machine Learning' (AFML), Ch.7,
adapted from mlfinlab/cross_validation.py
(https://github.com/hudson-and-thames/mlfinlab).

Why purging matters:
- In classic KFold the train and test sets share information whenever a sample's
  label horizon overlaps a sample in the test fold. That gives leakage and an
  inflated OOS metric.
- Purging drops every train sample whose label period [t0, t1] overlaps the
  test fold's [test_start, test_end].
- Embargo additionally drops a buffer of train samples that fall *just after*
  the test fold, so any short-term serial correlation does not leak.

This module is the canonical CV layer for ML strategies in QuantForge. For
non-ML strategies the metrics are still meaningful: each fold becomes an OOS
slice with the train slice already optimized away (caller provides a factory).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional
import numpy as np
import pandas as pd

from aurora.core.engine import run_backtest
from aurora.core.costs import CostModel, ZERO_costs


@dataclass
class PurgedKFoldResult:
    """Result of cv_score: per-fold metrics + aggregates."""
    n_splits: int
    embargo_pct: float
    fold_metrics: list[dict]  # one dict per fold: {'fold','train_idx','test_idx','metrics'}
    mean_calmar: float
    median_calmar: float
    std_calmar: float
    mean_sharpe: float
    median_sharpe: float
    std_sharpe: float
    mean_mdd: float


class PurgedKFold:
    """Time-series K-Fold with overlap purging + embargo.

    Source: Lopez de Prado 'Advances in Financial Machine Learning' Ch.7.

    Args:
        n_splits: number of folds (default 5)
        embargo_pct: fraction of total samples for embargo zone after each test
            (default 0.01 = 1%). Set 0.0 to disable embargo.
        t1: pd.Series mapping sample index -> end-of-label-period timestamp.
            For purging: training samples whose label period overlaps test set
            are dropped. If None, defaults to next-bar (no overlap), in which
            case purging is a no-op.
        lookback_bars: when set, the *effective* embargo for each split is
            ``round(embargo_pct * n) + lookback_bars``. The percentage portion
            buffers short-term serial correlation; the lookback portion
            buffers feature staleness for rolling-window or long-memory
            indicators. Defaults to None (legacy behaviour: pure
            ``embargo_pct``).
    """

    def __init__(self, n_splits: int = 5, embargo_pct: float = 0.01,
                 t1: Optional[pd.Series] = None,
                 lookback_bars: Optional[int] = None):
        if n_splits < 2:
            raise ValueError(f"n_splits must be >= 2, got {n_splits}")
        if not (0.0 <= embargo_pct < 1.0):
            raise ValueError(f"embargo_pct must be in [0, 1), got {embargo_pct}")
        if lookback_bars is not None and lookback_bars < 0:
            raise ValueError(f"lookback_bars must be >= 0, got {lookback_bars}")
        self.n_splits = int(n_splits)
        self.embargo_pct = float(embargo_pct)
        self.t1 = t1
        self.lookback_bars = (
            int(lookback_bars) if lookback_bars is not None else None
        )

    def _build_default_t1(self, X: pd.DataFrame) -> pd.Series:
        """Default: each sample's t1 = next bar timestamp (no overlap)."""
        idx = X.index
        # last sample t1 = its own timestamp (no future bar)
        next_idx = idx[1:].append(pd.DatetimeIndex([idx[-1]]))
        return pd.Series(next_idx, index=idx)

    def split(self, X: pd.DataFrame):
        """Yield (train_idx, test_idx) tuples of positional integer indices.

        Args:
            X: DataFrame or Series with a sortable index used to align t1.

        Yields:
            (train_idx, test_idx) where each is a np.ndarray of integer
            positions into X.
        """
        n = len(X)
        if n < self.n_splits:
            raise ValueError(f"len(X)={n} < n_splits={self.n_splits}")

        if self.t1 is None:
            t1 = self._build_default_t1(X)
        else:
            t1 = self.t1.reindex(X.index)
            if t1.isna().any():
                raise ValueError("t1 must cover every index in X")

        # Effective embargo = round(embargo_pct * n) PLUS the feature lookback
        # (rather than max of the two). The percentage portion buffers serial
        # correlation; the lookback portion buffers feature staleness. Adding
        # them avoids the case where a small embargo_pct on autocorrelated
        # features still permits leakage at the train/test boundary.
        embargo = int(round(n * self.embargo_pct))
        if self.lookback_bars is not None:
            embargo = embargo + int(self.lookback_bars)

        # contiguous test ranges
        fold_size = n // self.n_splits
        if fold_size < 2:
            # n // n_splits is integer division; a value < 2 means at least one
            # fold would carry a single bar of test content. Warn so callers
            # see why folds will have negligible statistical content; cv_score
            # additionally enforces a per-fold ``min_test_bars`` floor.
            import warnings
            warnings.warn(
                f"PurgedKFold fold_size={fold_size} (n={n}, n_splits={self.n_splits});"
                " statistical content per test slice is negligible.",
                UserWarning,
                stacklevel=2,
            )
            if fold_size < 1:
                return
        ranges = []
        cursor = 0
        for k in range(self.n_splits):
            test_lo = cursor
            test_hi = cursor + fold_size - 1
            if k == self.n_splits - 1:
                test_hi = n - 1  # last fold absorbs remainder
            ranges.append((test_lo, test_hi))
            cursor = test_hi + 1

        positions = np.arange(n)
        idx_array = X.index.to_numpy()
        t1_all = t1.to_numpy()

        for fold_k, (test_lo, test_hi) in enumerate(ranges):
            test_idx = positions[test_lo:test_hi + 1]

            # Test span = the test sample timestamps only.
            test_start_ts = idx_array[test_lo]
            test_end_ts = idx_array[test_hi]

            # candidate train mask: everything outside test
            train_mask: np.ndarray = np.ones(n, dtype=bool)
            train_mask[test_lo:test_hi + 1] = False

            # PURGE: drop train samples whose label period [idx, t1] strictly
            # overlaps the *interior* of the test span.
            # Convention: a label ending exactly at test_start_ts does not
            # overlap (open interval). This makes the default t1=next-bar a
            # no-op (no purging).
            overlap = (t1_all > test_start_ts) & (idx_array <= test_end_ts)
            train_mask &= ~overlap

            # EMBARGO: drop next `embargo` train samples after test_hi
            if embargo > 0:
                emb_lo = test_hi + 1
                emb_hi = min(test_hi + embargo, n - 1)
                if emb_lo <= emb_hi:
                    train_mask[emb_lo:emb_hi + 1] = False

            # SYMMETRIC PURGE: also drop train samples that fall within
            # ``embargo`` bars of ANY OTHER fold's test boundary. This closes
            # the leakage path where train_k could include rows tightly
            # adjacent to test_j (j != k), letting strategy fits leak across
            # folds via short-term serial correlation.
            if embargo > 0:
                for j_lo, j_hi in ranges:
                    if (j_lo, j_hi) == (test_lo, test_hi):
                        continue
                    # Both sides of fold j: pre-test and post-test buffer
                    pre_lo = max(0, j_lo - embargo)
                    pre_hi = max(-1, j_lo - 1)
                    if pre_lo <= pre_hi:
                        train_mask[pre_lo:pre_hi + 1] = False
                    post_lo = j_hi + 1
                    post_hi = min(n - 1, j_hi + embargo)
                    if post_lo <= post_hi:
                        train_mask[post_lo:post_hi + 1] = False

            train_idx = positions[train_mask]
            yield train_idx, test_idx


def cv_score(strategy_factory: Callable,
             prices: pd.Series,
             labels: Optional[pd.Series] = None,
             n_splits: int = 5,
             embargo_pct: float = 0.01,
             ppy: int = 252,
             costs: Optional[CostModel] = None,
             t1: Optional[pd.Series] = None,
             seed_name: str = "purged_cv",
             lookback_bars: Optional[int] = None) -> PurgedKFoldResult:
    """Run strategy across purged folds, return metrics distribution.

    For each fold the strategy is instantiated fresh (via factory). The
    test slice is backtested via `run_backtest`. Train slice is provided so
    ML strategies can fit on it; non-ML stateless strategies can ignore it.

    Args:
        strategy_factory: callable(train_prices=..., train_labels=...) -> Strategy
            Also accepts a no-arg callable for stateless strategies; the
            wrapper introspects the signature.
        prices: pd.Series with DatetimeIndex.
        labels: optional pd.Series of ML labels aligned with prices.
        n_splits: K (default 5).
        embargo_pct: zone after test set excluded from train.
        ppy: periods per year (default 252).
        costs: CostModel (defaults to ZERO_costs).
        t1: optional label-end Series; default = next-bar (no overlap).
        seed_name: namespace for child_rng (kept stable for reproducibility).
        lookback_bars: when set, the embargo applied is
            ``round(embargo_pct * n) + lookback_bars`` so autocorrelated
            features (rolling means, long-memory indicators) cannot bleed
            across adjacent train/test slices.

    Returns:
        PurgedKFoldResult with per-fold metrics + aggregated mean/median/std
        of Calmar, Sharpe, MDD.
    """
    if not isinstance(prices, pd.Series):
        raise TypeError("prices must be pd.Series with DatetimeIndex")
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise TypeError("prices index must be DatetimeIndex")
    if costs is None:
        costs = ZERO_costs

    X = pd.DataFrame({"price": prices.values}, index=prices.index)
    pkf = PurgedKFold(n_splits=n_splits, embargo_pct=embargo_pct, t1=t1,
                      lookback_bars=lookback_bars)

    fold_metrics: list[dict] = []
    calmars: list[float] = []
    sharpes: list[float] = []
    mdds: list[float] = []

    for fold_i, (train_idx, test_idx) in enumerate(pkf.split(X)):
        train_prices = prices.iloc[train_idx]
        test_prices = prices.iloc[test_idx]
        train_labels = labels.iloc[train_idx] if labels is not None else None

        # Per-fold minimum size: a 5-bar test slice has no statistical content
        # for autocorrelated daily strategies. Require at least one quarter-of-
        # a-year (ppy // 4) bars or 60 bars (whichever is larger). This keeps
        # the fold floor proportional to the calendar frequency of the data.
        # Check this BEFORE building the strategy so we don't waste a fit on a
        # fold whose test slice will be discarded.
        min_test_bars = max(60, int(ppy) // 4 if ppy and ppy > 0 else 60)
        if len(test_prices) < min_test_bars:
            fold_metrics.append({
                "fold": fold_i,
                "train_idx": train_idx,
                "test_idx": test_idx,
                "metrics": None,
                "ok": False,
                "reason": f"test slice too short ({len(test_prices)} < {min_test_bars})",
            })
            continue

        # build strategy: try keyword fit-style call, fall back to no-arg
        strat = _build_strategy(strategy_factory, train_prices, train_labels)

        res = run_backtest(test_prices, strat.signals, costs=costs, ppy=ppy)
        m = res.metrics
        fold_metrics.append({
            "fold": fold_i,
            "train_idx": train_idx,
            "test_idx": test_idx,
            "metrics": m.to_dict(),
            "ok": True,
        })
        calmars.append(m.calmar)
        sharpes.append(m.sharpe)
        mdds.append(m.mdd)

    if calmars:
        mean_c = float(np.mean(calmars))
        med_c = float(np.median(calmars))
        std_c = float(np.std(calmars, ddof=0))
        mean_s = float(np.mean(sharpes))
        med_s = float(np.median(sharpes))
        std_s = float(np.std(sharpes, ddof=0))
        mean_mdd = float(np.mean(mdds))
    else:
        mean_c = med_c = std_c = 0.0
        mean_s = med_s = std_s = 0.0
        mean_mdd = 0.0

    return PurgedKFoldResult(
        n_splits=n_splits,
        embargo_pct=embargo_pct,
        fold_metrics=fold_metrics,
        mean_calmar=mean_c,
        median_calmar=med_c,
        std_calmar=std_c,
        mean_sharpe=mean_s,
        median_sharpe=med_s,
        std_sharpe=std_s,
        mean_mdd=mean_mdd,
    )


def _build_strategy(factory: Callable, train_prices: pd.Series,
                    train_labels: Optional[pd.Series]):
    """Try fit-style factory call, fall back to no-arg factory.

    Order:
      1) factory(train_prices=..., train_labels=...)
      2) factory(train_prices=...)
      3) factory()
    """
    import inspect
    try:
        sig = inspect.signature(factory)
        params = dict(sig.parameters)
    except (TypeError, ValueError):
        params = {}

    if "train_prices" in params and "train_labels" in params:
        return factory(train_prices=train_prices, train_labels=train_labels)
    if "train_prices" in params:
        return factory(train_prices=train_prices)
    return factory()
