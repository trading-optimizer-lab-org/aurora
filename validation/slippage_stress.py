"""Slippage stress: re-run backtest with multiplied slippage cost.

Reports which strategies still produce positive Calmar with slippage scaled
by 2x, 3x, 5x. Useful to flag fragile high-frequency strategies whose alpha
exists only at the (often optimistic) base slippage assumption.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, List
import numpy as np
import pandas as pd

from quantforge.core.engine import run_backtest
from quantforge.core.costs import CostModel, ZERO_costs


def _scale_costs(c: CostModel, mult: float) -> CostModel:
    """Return a new CostModel with slippage-related fields multiplied."""
    # CostModel is a frozen-ish dataclass; reconstruct via dataclasses.replace.
    import dataclasses
    fields = {f.name: getattr(c, f.name) for f in dataclasses.fields(c)}
    # Heuristic: bump bps-style fields by mult, keep ratios fixed
    for key in ("slippage_bps", "spread_bps", "commission_bps"):
        if key in fields and fields[key] is not None:
            fields[key] = float(fields[key]) * float(mult)
    return type(c)(**fields)


@dataclass
class SlippageStressTest:
    multipliers: tuple = (1.0, 2.0, 3.0, 5.0)
    ppy: int = 252
    base_calmar: float = 0.0
    base_sharpe: float = 0.0
    stressed_calmars: List[float] = field(default_factory=list)
    stressed_sharpes: List[float] = field(default_factory=list)
    survives: List[bool] = field(default_factory=list)

    def run(self, strategy_factory: Callable, prices: pd.Series,
            costs: CostModel) -> "SlippageStressTest":
        if not isinstance(prices, pd.Series):
            raise TypeError("prices must be pd.Series")
        if not isinstance(prices.index, pd.DatetimeIndex):
            raise TypeError("prices index must be DatetimeIndex")
        if costs is None:
            raise ValueError("costs must not be None")
        if len(self.multipliers) < 1:
            raise ValueError("multipliers must be non-empty")
        if any(m < 0 for m in self.multipliers):
            raise ValueError("multipliers must be >= 0")

        # Baseline (multiplier 1) is the user-provided costs
        base_strat = strategy_factory()
        base_res = run_backtest(prices, base_strat.signals, costs=costs, ppy=self.ppy)
        self.base_calmar = float(base_res.calmar)
        self.base_sharpe = float(base_res.sharpe)

        for mult in self.multipliers:
            scaled = _scale_costs(costs, float(mult))
            strat = strategy_factory()
            res = run_backtest(prices, strat.signals, costs=scaled, ppy=self.ppy)
            cal = float(res.calmar)
            shr = float(res.sharpe)
            self.stressed_calmars.append(cal)
            self.stressed_sharpes.append(shr)
            self.survives.append(cal > 0.0)
        return self
