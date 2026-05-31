"""Hypothesis Framework.

Standardized H0/H1 test bench for strategies.

A Hypothesis defines:
    name -- short identifier
    description -- the H0/H1 statement, e.g. "Sharpe == 0 vs Sharpe > 0"
    metric -- "sharpe", "calmar", "cagr", "mar"
    threshold -- benchmark value (typically 0.0 or another strategy's metric)
    alternative -- "greater" | "less" | "two-sided"

The HypothesisTester runs a strategy through the Aurora engine, then
applies a bootstrap test on bar-level returns to compute a p-value for the
metric being above/below the threshold.

Bootstrap method: stationary block bootstrap with default block_len=10.
For Sharpe and CAGR the test statistic is the metric of the bootstrapped
return path. For Calmar and MAR the same applies.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Literal
import numpy as np
import pandas as pd

from aurora.core.engine import run_backtest
from aurora.core.metrics import compute_metrics
from aurora.core.costs import ZERO_costs


Alternative = Literal["greater", "less", "two-sided"]


@dataclass
class Hypothesis:
    name: str
    description: str
    metric: str  # 'sharpe', 'calmar', 'cagr', 'sortino', 'mar'
    threshold: float
    alternative: Alternative = "greater"


@dataclass
class HypothesisResult:
    hypothesis: Hypothesis
    observed: float
    threshold: float
    p_value: float
    n_bootstrap: int
    rejected_h0: bool
    alpha: float


def _block_bootstrap(rets: np.ndarray, block_len: int, n: int,
                     rng: np.random.Generator) -> np.ndarray:
    """Generate one block-bootstrap path of length n from rets."""
    if len(rets) == 0:
        return np.zeros(n)
    n_blocks = (n // block_len) + 1
    starts = rng.integers(0, max(1, len(rets) - block_len + 1), size=n_blocks)
    pieces = [rets[s:s + block_len] for s in starts]
    arr = np.concatenate(pieces)
    return arr[:n]


def _metric_value(rets: np.ndarray, metric: str, ppy: int) -> float:
    m = compute_metrics(rets, ppy=ppy)
    if metric == "sharpe":
        return float(m.sharpe)
    if metric == "sortino":
        return float(m.sortino)
    if metric == "calmar":
        return float(m.calmar)
    if metric == "cagr":
        return float(m.cagr)
    if metric == "mar":
        return float(m.mar)
    raise ValueError(f"unknown metric: {metric!r}")


class HypothesisTester:
    """Run a Hypothesis test against a strategy's backtest returns."""

    def __init__(self, n_bootstrap: int = 200, block_len: int = 10,
                 alpha: float = 0.05, seed: int = 42):
        if n_bootstrap < 10:
            raise ValueError("n_bootstrap must be >= 10")
        if block_len < 1:
            raise ValueError("block_len must be >= 1")
        if not (0.0 < alpha < 1.0):
            raise ValueError("alpha must be in (0, 1)")
        self.n_bootstrap = int(n_bootstrap)
        self.block_len = int(block_len)
        self.alpha = float(alpha)
        self.seed = int(seed)

    def test(self, hypothesis: Hypothesis, prices: pd.Series,
             signal_fn: Callable, ppy: int = 252) -> HypothesisResult:
        """Run the strategy via run_backtest and bootstrap-test the metric."""
        result = run_backtest(prices, signal_fn, costs=ZERO_costs, ppy=ppy)
        rets = result.rets[~np.isnan(result.rets)]
        observed = _metric_value(rets, hypothesis.metric, ppy)
        rng = np.random.default_rng(self.seed)
        boot_metrics = np.empty(self.n_bootstrap)
        for b in range(self.n_bootstrap):
            sample = _block_bootstrap(rets, self.block_len, len(rets), rng)
            boot_metrics[b] = _metric_value(sample, hypothesis.metric, ppy)
        # p-value relative to threshold (under H0 the metric equals threshold)
        # so we shift the bootstrap distribution by (threshold - observed)
        # to estimate the null distribution centered at threshold.
        shifted = boot_metrics - observed + hypothesis.threshold
        if hypothesis.alternative == "greater":
            p = float(np.mean(shifted >= observed))
        elif hypothesis.alternative == "less":
            p = float(np.mean(shifted <= observed))
        else:  # two-sided
            p = float(np.mean(np.abs(shifted - hypothesis.threshold)
                              >= abs(observed - hypothesis.threshold)))
        # Avoid zero p-values from finite Monte Carlo: bound below by 1/n.
        p = max(p, 1.0 / self.n_bootstrap)
        rejected = p < self.alpha
        return HypothesisResult(
            hypothesis=hypothesis,
            observed=float(observed),
            threshold=float(hypothesis.threshold),
            p_value=p,
            n_bootstrap=self.n_bootstrap,
            rejected_h0=bool(rejected),
            alpha=self.alpha,
        )

    def test_battery(self, hypotheses: list[Hypothesis], prices: pd.Series,
                     signal_fn: Callable, ppy: int = 252
                     ) -> list[HypothesisResult]:
        """Run a list of hypotheses; return results in order."""
        return [self.test(h, prices, signal_fn, ppy) for h in hypotheses]
