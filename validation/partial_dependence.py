"""Partial dependence: per-parameter sensitivity holding others at median.

For each strategy parameter, vary it across a grid while pinning all other
parameters to their median value. Re-run the backtest at every grid point
and report Calmar (or any user-supplied metric) as a function of the swept
parameter. Reveals monotonic trends, ridges, or knife-edge sensitivities.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Sequence
import numpy as np
import pandas as pd

from aurora.core.engine import run_backtest
from aurora.core.costs import CostModel, ZERO_costs


@dataclass
class PartialDependenceAnalysis:
    n_grid: int = 7
    ppy: int = 252
    # results[param_name] = dict with keys 'grid' (np.ndarray), 'calmars' (np.ndarray)
    results: Dict[str, Dict[str, np.ndarray]] = field(default_factory=dict)
    pinned_values: Dict[str, float] = field(default_factory=dict)

    def _build_grid(self, lo: float, hi: float, is_int: bool) -> np.ndarray:
        if is_int:
            grid = np.unique(
                np.linspace(int(lo), int(hi), self.n_grid).round().astype(int)
            )
            return grid
        return np.linspace(lo, hi, self.n_grid)

    def run(self, strategy_factory: Callable, prices: pd.Series,
            param_ranges: Dict[str, tuple],
            costs: CostModel = ZERO_costs) -> "PartialDependenceAnalysis":
        """Run partial dependence sweep.

        Args:
            strategy_factory: callable(**params) -> Strategy. Must accept the
                parameters listed in param_ranges as keyword arguments.
            prices: pd.Series with DatetimeIndex.
            param_ranges: dict[param_name -> (lo, hi)]. If lo and hi are
                ints, the grid is integer; otherwise float.
            costs: CostModel.
        """
        if not isinstance(prices, pd.Series):
            raise TypeError("prices must be pd.Series")
        if not isinstance(prices.index, pd.DatetimeIndex):
            raise TypeError("prices index must be DatetimeIndex")
        if not param_ranges:
            raise ValueError("param_ranges must be non-empty")
        if self.n_grid < 2:
            raise ValueError("n_grid must be >= 2")

        # Pin every param to its median value
        for name, (lo, hi) in param_ranges.items():
            if isinstance(lo, int) and isinstance(hi, int):
                self.pinned_values[name] = int(round(0.5 * (lo + hi)))
            else:
                self.pinned_values[name] = float(0.5 * (lo + hi))

        for name, (lo, hi) in param_ranges.items():
            is_int = isinstance(lo, int) and isinstance(hi, int)
            grid = self._build_grid(lo, hi, is_int)
            cals = np.zeros(len(grid))
            for i, v in enumerate(grid):
                kw = dict(self.pinned_values)
                kw[name] = int(v) if is_int else float(v)
                strat = strategy_factory(**kw)
                res = run_backtest(prices, strat.signals, costs=costs, ppy=self.ppy)
                cals[i] = float(res.calmar)
            self.results[name] = {"grid": grid, "calmars": cals}
        return self
