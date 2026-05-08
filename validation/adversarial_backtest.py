"""Adversarial backtest: gradient ascent worst-case scenario generator.

Given a strategy and a base price series, perturb prices in directions that
*hurt* strategy returns (gradient ascent on negative-return objective).
Returns a set of adversarial scenarios with deteriorated metrics.

The strategy's pnl is treated as a (non-differentiable) black-box; we use
finite-difference gradient estimates against a low-dimensional perturbation
parameterization (block-wise multiplicative shocks).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, List
import numpy as np
import pandas as pd

from quantforge.core.engine import run_backtest
from quantforge.core.costs import CostModel, ZERO_costs
from quantforge.core.seed import child_rng


@dataclass
class AdversarialBacktester:
    n_scenarios: int = 5
    n_blocks: int = 10
    max_shock_pct: float = 0.05
    n_iterations: int = 20
    learning_rate: float = 0.01
    fd_step: float = 1e-3
    ppy: int = 252
    seed_name: str = "adversarial_backtest"
    base_calmar: float = 0.0
    base_sharpe: float = 0.0
    base_total_return: float = 0.0
    adversarial_calmars: List[float] = field(default_factory=list)
    adversarial_sharpes: List[float] = field(default_factory=list)
    adversarial_total_returns: List[float] = field(default_factory=list)
    adversarial_shocks: List[np.ndarray] = field(default_factory=list)
    n_blocks_actual: int = 0

    def _apply_shocks(self, prices: np.ndarray, shocks: np.ndarray) -> np.ndarray:
        n = len(prices)
        b = len(shocks)
        block_size = max(1, n // b)
        per_bar = np.zeros(n)
        for i in range(b):
            lo = i * block_size
            hi = (i + 1) * block_size if i < b - 1 else n
            per_bar[lo:hi] = shocks[i]
        out = prices * (1.0 + per_bar)
        return np.maximum(out, 1e-9)

    def _objective(self, strategy_factory: Callable, prices: pd.Series,
                   shocks: np.ndarray, costs: CostModel) -> float:
        """Return value to MAXIMIZE under gradient ascent (negative pnl)."""
        new_p = self._apply_shocks(prices.values.astype(float), shocks)
        s = pd.Series(new_p, index=prices.index, name=prices.name)
        strat = strategy_factory()
        res = run_backtest(s, strat.signals, costs=costs, ppy=self.ppy)
        # Maximize negative return == minimize return
        total_ret = float(res.nav[-1] / res.nav[0] - 1.0) if len(res.nav) > 1 else 0.0
        return -total_ret

    def _estimate_gradient(self, strategy_factory: Callable, prices: pd.Series,
                           shocks: np.ndarray, costs: CostModel) -> np.ndarray:
        """Central-difference gradient of objective wrt shocks."""
        n = len(shocks)
        grad = np.zeros(n)
        h = self.fd_step
        f0 = self._objective(strategy_factory, prices, shocks, costs)
        for i in range(n):
            up = shocks.copy(); up[i] += h
            f_up = self._objective(strategy_factory, prices, up, costs)
            grad[i] = (f_up - f0) / h
        return grad

    def run(self, strategy_factory: Callable, prices: pd.Series,
            costs: CostModel = ZERO_costs) -> "AdversarialBacktester":
        if not isinstance(prices, pd.Series):
            raise TypeError("prices must be pd.Series")
        if not isinstance(prices.index, pd.DatetimeIndex):
            raise TypeError("prices index must be DatetimeIndex")
        if self.n_scenarios < 1:
            raise ValueError("n_scenarios must be >= 1")
        if self.n_blocks < 1:
            raise ValueError("n_blocks must be >= 1")
        if self.max_shock_pct <= 0:
            raise ValueError("max_shock_pct must be > 0")

        n = len(prices)
        n_blocks = min(self.n_blocks, max(1, n))
        self.n_blocks_actual = n_blocks
        rng = child_rng(self.seed_name)

        # Baseline
        base_strat = strategy_factory()
        base_res = run_backtest(prices, base_strat.signals, costs=costs, ppy=self.ppy)
        self.base_calmar = float(base_res.calmar)
        self.base_sharpe = float(base_res.sharpe)
        self.base_total_return = float(base_res.nav[-1] / base_res.nav[0] - 1.0) if len(base_res.nav) > 1 else 0.0

        for k in range(self.n_scenarios):
            shocks = rng.uniform(-self.max_shock_pct * 0.1,
                                 self.max_shock_pct * 0.1, n_blocks)
            for _ in range(self.n_iterations):
                g = self._estimate_gradient(strategy_factory, prices, shocks, costs)
                shocks = shocks + self.learning_rate * np.sign(g) * self.max_shock_pct * 0.1
                shocks = np.clip(shocks, -self.max_shock_pct, self.max_shock_pct)

            new_p = self._apply_shocks(prices.values.astype(float), shocks)
            s = pd.Series(new_p, index=prices.index, name=prices.name)
            strat = strategy_factory()
            res = run_backtest(s, strat.signals, costs=costs, ppy=self.ppy)
            self.adversarial_calmars.append(float(res.calmar))
            self.adversarial_sharpes.append(float(res.sharpe))
            tr = float(res.nav[-1] / res.nav[0] - 1.0) if len(res.nav) > 1 else 0.0
            self.adversarial_total_returns.append(tr)
            self.adversarial_shocks.append(shocks.copy())

        return self
