"""Strategy Combiner.

Search over weighted combinations of N strategies for the best
risk-adjusted return on an in-sample (IS) segment, then validate the
discovered weights on an out-of-sample (OOS) segment.

The combined signal is the weighted sum of each strategy's signals,
clipped to [-1, 1]:

    combined[t] = clip(sum_i w_i * sig_i[t], -1, 1)

Search method: random simplex sampling. Each candidate weight vector is
drawn from a Dirichlet(alpha=1) distribution so the components are
non-negative and sum to one. This reflects a long-only convex
combination -- the most common interpretation of "ensemble of
strategies". An equal-weight baseline is always evaluated as a sanity
check.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable
import numpy as np
import pandas as pd

from quantforge.core.engine import run_backtest
from quantforge.core.costs import ZERO_costs


@dataclass
class CombinerEntry:
    """One named strategy participating in the combination search."""
    name: str
    signal_fn: Callable[[pd.Series], np.ndarray]


@dataclass
class CombinerReport:
    best_weights: dict[str, float]
    is_metric: float
    oos_metric: float
    n_candidates: int
    metric_name: str
    equal_weight_is: float
    equal_weight_oos: float


class StrategyCombiner:
    """Search weighted combinations of strategies for best IS metric."""

    def __init__(self, n_candidates: int = 100, metric: str = "calmar",
                 seed: int = 42, ppy: int = 252):
        if n_candidates < 1:
            raise ValueError("n_candidates must be >= 1")
        if metric not in ("sharpe", "calmar", "cagr", "sortino", "mar"):
            raise ValueError(f"unsupported metric: {metric!r}")
        self.n_candidates = int(n_candidates)
        self.metric = metric
        self.seed = int(seed)
        self.ppy = int(ppy)

    def _combined_signal(self, prices: pd.Series,
                         entries: list[CombinerEntry],
                         weights: np.ndarray) -> np.ndarray:
        sigs = [e.signal_fn(prices) for e in entries]
        agg = np.zeros(len(prices))
        for w, s in zip(weights, sigs):
            agg = agg + w * s
        return np.clip(agg, -1.0, 1.0)

    def _eval(self, prices: pd.Series, entries: list[CombinerEntry],
              weights: np.ndarray) -> float:
        sig = self._combined_signal(prices, entries, weights)

        def signal_fn(p: pd.Series) -> np.ndarray:
            return sig

        result = run_backtest(prices, signal_fn, costs=ZERO_costs, ppy=self.ppy)
        v = getattr(result.metrics, self.metric)
        if v is None or np.isnan(v) or np.isinf(v):
            return -np.inf
        return float(v)

    def search(self, prices: pd.Series, entries: list[CombinerEntry],
               is_end: int) -> CombinerReport:
        """Search weights on prices[:is_end], validate on prices[is_end:]."""
        if not entries:
            raise ValueError("entries must not be empty")
        if not isinstance(prices, pd.Series):
            raise TypeError("prices must be a pandas Series")
        n = len(prices)
        if not (0 < is_end < n):
            raise ValueError(f"is_end must be in (0, {n}); got {is_end}")
        is_prices = prices.iloc[:is_end]
        oos_prices = prices.iloc[is_end:]
        N = len(entries)
        rng = np.random.default_rng(self.seed)
        best_w = np.full(N, 1.0 / N)
        best_v = self._eval(is_prices, entries, best_w)
        equal_w_is = best_v
        for _ in range(self.n_candidates):
            w = rng.dirichlet(np.ones(N))
            v = self._eval(is_prices, entries, w)
            if v > best_v:
                best_v = v
                best_w = w
        oos_v = self._eval(oos_prices, entries, best_w)
        equal_w_oos = self._eval(oos_prices, entries, np.full(N, 1.0 / N))
        return CombinerReport(
            best_weights={e.name: float(w) for e, w in zip(entries, best_w)},
            is_metric=float(best_v),
            oos_metric=float(oos_v),
            n_candidates=self.n_candidates + 1,  # +1 for equal-weight baseline
            metric_name=self.metric,
            equal_weight_is=float(equal_w_is),
            equal_weight_oos=float(equal_w_oos),
        )
