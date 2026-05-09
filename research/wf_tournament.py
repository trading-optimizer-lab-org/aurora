"""Walk-Forward Tournament.

Runs N strategies head-to-head in each WF window. Records per-window
winner (by ranking metric) and aggregates a long-run win/loss tally.

Window scheme:
    train_size: number of bars in each training segment (informational - we
        don't fit anything here, since each strategy is parameter-fixed).
    test_size: number of bars per test window.
    step: bars between consecutive window starts; defaults to test_size for
        a non-overlapping rolling-out-of-sample sweep.

Per window we:
    * compute each strategy's metric on the test segment
    * award the winner a +1 score, others +0
    * optionally award all strategies above a relative threshold a +1

The aggregated leaderboard contains wins, losses, ties, and avg_metric.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable
import numpy as np
import pandas as pd

from aurora.core.engine import run_backtest
from aurora.core.costs import ZERO_costs


@dataclass
class TournamentEntry:
    name: str
    signal_fn: Callable[[pd.Series], np.ndarray]


@dataclass
class WindowResult:
    window_idx: int
    start: int  # bar index
    end: int    # bar index (exclusive)
    metrics: dict[str, float]  # name -> metric value
    winner: str
    losers: list[str] = field(default_factory=list)


@dataclass
class TournamentReport:
    """Aggregated record for a finished tournament."""
    n_windows: int
    metric: str
    standings: dict[str, dict[str, float]]  # name -> {wins, losses, ties, avg_metric}
    per_window: list[WindowResult] = field(default_factory=list)

    def leader(self) -> str:
        """Return the name with the most wins (deterministic tie-break)."""
        if not self.standings:
            return ""
        return max(
            self.standings.items(),
            key=lambda kv: (kv[1]["wins"], kv[1]["avg_metric"], kv[0]),
        )[0]


class WalkForwardTournament:
    """Run a multi-strategy head-to-head tournament across WF windows."""

    def __init__(self, train_size: int = 252, test_size: int = 60,
                 step: int | None = None, metric: str = "sharpe",
                 ppy: int = 252):
        if train_size < 1 or test_size < 1:
            raise ValueError("train_size and test_size must be >= 1")
        if metric not in ("sharpe", "calmar", "cagr", "sortino"):
            raise ValueError(f"unsupported metric: {metric!r}")
        self.train_size = int(train_size)
        self.test_size = int(test_size)
        self.step = int(step) if step is not None else int(test_size)
        if self.step < 1:
            raise ValueError("step must be >= 1")
        self.metric = metric
        self.ppy = int(ppy)

    def _eval_metric(self, prices: pd.Series, signal_fn: Callable) -> float:
        result = run_backtest(prices, signal_fn, costs=ZERO_costs, ppy=self.ppy)
        m = result.metrics
        v = getattr(m, self.metric)
        if v is None or np.isnan(v) or np.isinf(v):
            return -np.inf
        return float(v)

    def run(self, prices: pd.Series, entries: list[TournamentEntry]
            ) -> TournamentReport:
        if not entries:
            raise ValueError("entries must not be empty")
        if not isinstance(prices, pd.Series):
            raise TypeError("prices must be a pandas Series")
        n = len(prices)
        if n < self.train_size + self.test_size:
            raise ValueError(
                f"need at least train_size + test_size = "
                f"{self.train_size + self.test_size} bars; got {n}"
            )
        standings = {
            e.name: {"wins": 0.0, "losses": 0.0, "ties": 0.0, "avg_metric": 0.0}
            for e in entries
        }
        per_window: list[WindowResult] = []
        windows: list[tuple[int, int]] = []
        start = self.train_size
        idx = 0
        while start + self.test_size <= n:
            test_start = start
            test_end = start + self.test_size
            windows.append((test_start, test_end))
            start += self.step
            idx += 1
        if not windows:
            raise ValueError("no walk-forward windows could be constructed")

        metric_sums: dict[str, float] = {e.name: 0.0 for e in entries}
        for wi, (s, e) in enumerate(windows):
            test_prices = prices.iloc[s:e]
            window_metrics: dict[str, float] = {}
            for entry in entries:
                window_metrics[entry.name] = self._eval_metric(test_prices, entry.signal_fn)
                metric_sums[entry.name] += window_metrics[entry.name]
            best = max(window_metrics.values())
            winners = [name for name, v in window_metrics.items()
                       if v >= best - 1e-12]
            losers = [name for name in window_metrics if name not in winners]
            for name in window_metrics:
                if name in winners:
                    if len(winners) > 1:
                        standings[name]["ties"] += 1
                    standings[name]["wins"] += 1
                else:
                    standings[name]["losses"] += 1
            # store deterministic single winner alphabetically among ties
            winner = sorted(winners)[0]
            per_window.append(WindowResult(
                window_idx=wi, start=s, end=e,
                metrics=window_metrics, winner=winner, losers=losers,
            ))
        for name in standings:
            standings[name]["avg_metric"] = metric_sums[name] / len(windows)
        return TournamentReport(
            n_windows=len(windows),
            metric=self.metric,
            standings=standings,
            per_window=per_window,
        )
