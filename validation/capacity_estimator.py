"""Capacity estimator: stress strategy with increasing AUM until alpha is eroded.

For each candidate notional AUM:
  1. Estimate per-trade slippage as a function of order size relative to ADV.
  2. Apply slippage to base returns -> degraded NAV.
  3. Compute degraded Calmar.
Find the break-point where degraded Calmar drops below `alpha_floor` of the
zero-AUM baseline.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, List, Optional
import numpy as np
import pandas as pd

from quantforge.core.engine import run_backtest
from quantforge.core.costs import CostModel, ZERO_costs


@dataclass
class CapacityEstimator:
    aum_grid: tuple = (1e5, 1e6, 1e7, 1e8, 1e9, 1e10)
    avg_daily_volume: float = 1e7  # $ ADV in same units as AUM
    slippage_coef: float = 0.1  # bps per unit (size/ADV) ratio
    alpha_floor_pct: float = 0.5  # break-point at 50% of baseline Calmar
    ppy: int = 252
    base_calmar: float = 0.0
    base_sharpe: float = 0.0
    capacity_curve_calmars: List[float] = field(default_factory=list)
    capacity_curve_sharpes: List[float] = field(default_factory=list)
    breakpoint_aum: Optional[float] = None  # None if no break in grid

    def _apply_size_slippage(self, returns: np.ndarray, signals: np.ndarray,
                             aum: float) -> np.ndarray:
        """Apply size-dependent slippage as bps subtracted from each return.

        Slippage_bps_per_trade = slippage_coef * (order_size/ADV) * 1e4 (bps).
        Order size at bar t ~ |signal[t]| * AUM (notional).
        """
        if self.avg_daily_volume <= 0:
            return returns
        size_ratio = np.abs(signals) * aum / self.avg_daily_volume
        slip_bps = self.slippage_coef * size_ratio  # bps per bar
        slip_frac = slip_bps / 1e4
        # Apply: subtract from returns when there is exposure
        return returns - slip_frac * np.abs(signals)

    def run(self, strategy_factory: Callable, prices: pd.Series,
            costs: CostModel = ZERO_costs) -> "CapacityEstimator":
        if not isinstance(prices, pd.Series):
            raise TypeError("prices must be pd.Series")
        if not isinstance(prices.index, pd.DatetimeIndex):
            raise TypeError("prices index must be DatetimeIndex")
        if self.avg_daily_volume <= 0:
            raise ValueError("avg_daily_volume must be > 0")
        if self.slippage_coef < 0:
            raise ValueError("slippage_coef must be >= 0")
        if not (0.0 < self.alpha_floor_pct <= 1.0):
            raise ValueError("alpha_floor_pct must be in (0, 1]")
        if len(self.aum_grid) < 1:
            raise ValueError("aum_grid must be non-empty")

        # Baseline run
        base_strat = strategy_factory()
        base_res = run_backtest(prices, base_strat.signals, costs=costs, ppy=self.ppy)
        self.base_calmar = float(base_res.calmar)
        self.base_sharpe = float(base_res.sharpe)
        base_rets = np.asarray(base_res.rets, dtype=float)
        base_signals = np.asarray(base_res.weights, dtype=float)

        from quantforge.core.metrics import compute_metrics

        floor = self.base_calmar * self.alpha_floor_pct \
            if self.base_calmar > 0 else self.base_calmar / self.alpha_floor_pct
        for aum in self.aum_grid:
            stressed = self._apply_size_slippage(base_rets, base_signals, float(aum))
            m = compute_metrics(stressed, ppy=self.ppy)
            cal = float(m.calmar)
            shr = float(m.sharpe)
            self.capacity_curve_calmars.append(cal)
            self.capacity_curve_sharpes.append(shr)
            if self.breakpoint_aum is None and self.base_calmar > 0 and cal < floor:
                self.breakpoint_aum = float(aum)

        return self
