"""Paper Replicator.

Given a structured spec describing a research paper's strategy
(signal_def, asset_universe, lookback), replicates the strategy and reports
how well the local backtest matches the paper's reported metrics.

Spec form (PaperSpec):
    title: str -- paper title
    signal_def: callable(prices: pd.Series) -> np.ndarray -- the signal
    asset_universe: list[str] -- asset tickers used (informational)
    lookback: int -- declared lookback (informational, may be used by signal)
    reported_metrics: dict -- e.g. {"sharpe": 1.2, "calmar": 0.8, "cagr": 0.15}
    tolerance: dict -- per-metric absolute tolerance for "match" decision

The replicator runs the signal over a supplied price series, computes
metrics, and returns a ReplicationReport that scores the match per metric.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Any
import numpy as np
import pandas as pd

from quantforge.core.engine import run_backtest
from quantforge.core.costs import ZERO_costs


@dataclass
class PaperSpec:
    """Structured spec for a paper to replicate."""
    title: str
    signal_def: Callable[[pd.Series], np.ndarray]
    asset_universe: list[str] = field(default_factory=list)
    lookback: int = 252
    reported_metrics: dict[str, float] = field(default_factory=dict)
    tolerance: dict[str, float] = field(default_factory=dict)
    ppy: int = 252


@dataclass
class ReplicationReport:
    """Output of PaperReplicator.replicate().

    matched: bool -- True iff every reported metric is within tolerance.
    per_metric: dict[name -> dict] with keys reported, observed, abs_diff,
                tolerance, within.
    observed_metrics: dict mirroring the metric values from the backtest.
    """
    title: str
    matched: bool
    per_metric: dict[str, dict[str, float]]
    observed_metrics: dict[str, float]
    n_periods: int


class PaperReplicator:
    """Replicate a paper's strategy and score the match.

    Usage:
        rep = PaperReplicator()
        report = rep.replicate(spec, prices)
        assert report.matched
    """

    DEFAULT_TOLERANCE = {
        "sharpe": 0.5,
        "calmar": 0.5,
        "cagr": 0.05,
        "mdd": 0.10,
    }

    def replicate(self, spec: PaperSpec, prices: pd.Series) -> ReplicationReport:
        """Run the spec's signal over prices and score the match."""
        if not isinstance(prices, pd.Series):
            raise TypeError("prices must be a pandas Series with DatetimeIndex")

        result = run_backtest(prices, spec.signal_def, costs=ZERO_costs, ppy=spec.ppy)
        m = result.metrics
        observed = {
            "sharpe": float(m.sharpe),
            "calmar": float(m.calmar),
            "cagr": float(m.cagr),
            "mdd": float(m.mdd),
            "sortino": float(m.sortino),
        }
        per_metric: dict[str, dict[str, float]] = {}
        all_within = True
        for name, reported in spec.reported_metrics.items():
            tol = spec.tolerance.get(name, self.DEFAULT_TOLERANCE.get(name, 0.25))
            obs = observed.get(name, float("nan"))
            if np.isnan(obs) or np.isinf(obs):
                within = False
                diff = float("inf")
            else:
                diff = abs(obs - reported)
                within = diff <= tol
            per_metric[name] = {
                "reported": float(reported),
                "observed": float(obs),
                "abs_diff": float(diff),
                "tolerance": float(tol),
                "within": bool(within),
            }
            if not within:
                all_within = False
        if not spec.reported_metrics:
            all_within = False
        return ReplicationReport(
            title=spec.title,
            matched=all_within,
            per_metric=per_metric,
            observed_metrics=observed,
            n_periods=int(m.n_periods_raw or m.n_periods),
        )
