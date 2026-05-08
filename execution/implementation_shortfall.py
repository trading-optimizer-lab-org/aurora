"""Implementation Shortfall (Perold) framework.

Implementation shortfall = (paper portfolio return) - (real portfolio return).
Decomposes total cost into:

* Delay cost: arrival_price - decision_price
* Trading cost: avg_exec_price - arrival_price (signed by side)
* Opportunity cost: residual unfilled quantity priced at end_price - decision

The optimizer simply chooses an execution horizon ``n`` (number of
slices) that minimizes expected total cost given a linear+sqrt impact
model and a volatility risk term. Closed-form for the chosen impact
parameterization.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class ISConfig:
    """Configuration for the IS optimizer.

    Cost model::

        impact_per_slice(qty) = eta * qty + gamma * sqrt(qty)
        risk(n)               = lambda * sigma**2 * (parent_qty / n)
    """
    eta: float = 1e-4         # linear impact coefficient
    gamma: float = 5e-4       # square-root impact coefficient
    sigma: float = 0.01       # short-horizon vol (per bar)
    risk_aversion: float = 1.0  # lambda
    n_min: int = 1
    n_max: int = 200

    def __post_init__(self):
        for name in ("eta", "gamma", "sigma", "risk_aversion"):
            v = getattr(self, name)
            if v < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.n_min < 1 or self.n_max < self.n_min:
            raise ValueError("must have 1 <= n_min <= n_max")


@dataclass
class ISResult:
    """Output of :meth:`ImplementationShortfallOptimizer.optimize`."""
    optimal_n: int
    expected_cost: float
    delay_cost: float
    trading_cost: float
    opportunity_cost: float
    decomposition: dict


class ImplementationShortfallOptimizer:
    """Perold IS framework with simple closed-form n* search."""

    def __init__(self, config: Optional[ISConfig] = None):
        self.config = config or ISConfig()

    def expected_cost(self, parent_qty: float, n: int) -> float:
        """Expected total cost (impact + risk) of executing in ``n`` slices."""
        if parent_qty <= 0:
            raise ValueError("parent_qty must be > 0")
        if n < 1:
            raise ValueError("n must be >= 1")
        cfg = self.config
        slice_qty = parent_qty / n
        impact = n * (cfg.eta * slice_qty + cfg.gamma * np.sqrt(slice_qty))
        risk = cfg.risk_aversion * (cfg.sigma ** 2) * slice_qty
        return float(impact + risk)

    def optimize(self, parent_qty: float) -> ISResult:
        """Find the slice count that minimizes expected total cost."""
        cfg = self.config
        if parent_qty <= 0:
            raise ValueError("parent_qty must be > 0")
        ns = np.arange(cfg.n_min, cfg.n_max + 1)
        costs = np.array([self.expected_cost(parent_qty, int(n)) for n in ns])
        idx = int(np.argmin(costs))
        n_star = int(ns[idx])
        slice_qty = parent_qty / n_star
        delay = 0.0  # arrival = decision in our discretization
        trading = float(
            n_star * (cfg.eta * slice_qty + cfg.gamma * np.sqrt(slice_qty))
        )
        opportunity = float(
            cfg.risk_aversion * (cfg.sigma ** 2) * slice_qty
        )
        return ISResult(
            optimal_n=n_star,
            expected_cost=float(costs[idx]),
            delay_cost=delay,
            trading_cost=trading,
            opportunity_cost=opportunity,
            decomposition={
                "delay": delay,
                "trading": trading,
                "opportunity": opportunity,
            },
        )

    def realized_shortfall(
        self,
        decision_price: float,
        arrival_price: float,
        avg_exec_price: float,
        end_price: float,
        parent_qty: float,
        executed_qty: float,
        side: str = "buy",
    ) -> dict:
        """Compute realized IS decomposition for a completed parent order.

        Sign convention: positive = adverse (cost). For a buy, paying
        more than the decision price is a cost.
        """
        if parent_qty <= 0:
            raise ValueError("parent_qty must be > 0")
        if executed_qty < 0 or executed_qty > parent_qty:
            raise ValueError("executed_qty must be in [0, parent_qty]")
        sign = 1.0 if side == "buy" else -1.0
        residual = parent_qty - executed_qty
        delay = sign * (arrival_price - decision_price) * parent_qty
        trading = sign * (avg_exec_price - arrival_price) * executed_qty
        opportunity = sign * (end_price - decision_price) * residual
        total = delay + trading + opportunity
        return {
            "delay": float(delay),
            "trading": float(trading),
            "opportunity": float(opportunity),
            "total": float(total),
        }
