"""Almgren-Chriss optimal liquidation.

Closed-form trading trajectory for a parent order liquidated over
``T`` bars with linear permanent + temporary impact and risk aversion
``lambda``. The standard solution (Almgren & Chriss 2000) is::

    x_k = X * sinh(kappa * (T - k)) / sinh(kappa * T)

where ``kappa = arcsinh(0.5 * sqrt(lambda * sigma^2 / eta * (1 - 0.5*tau*gamma/eta)) * tau)``
in the continuous-time limit. We use a discretized form: optimal trade
list ``n_k = x_{k-1} - x_k``.

For risk_aversion=0 the trajectory degenerates to a TWAP straight line.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

import numpy as np


@dataclass(frozen=True)
class AlmgrenChrissConfig:
    """Configuration for the Almgren-Chriss executor."""
    n_steps: int = 10                 # T
    sigma: float = 0.01               # per-bar vol (price units)
    eta: float = 1e-3                 # temporary impact (price per share)
    gamma: float = 1e-4               # permanent impact (price per share)
    risk_aversion: float = 1.0        # lambda
    tau: float = 1.0                  # bar length (no time-rescaling here)
    side: str = "sell"                # "sell" liquidates, "buy" accumulates

    def __post_init__(self):
        if self.n_steps < 1:
            raise ValueError("n_steps must be >= 1")
        for name in ("sigma", "eta", "gamma", "risk_aversion", "tau"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.eta == 0:
            raise ValueError("eta must be > 0")
        if self.side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'")


@dataclass
class AlmgrenChrissSchedule:
    """One time-step of an Almgren-Chriss trajectory."""
    step: int
    timestamp: datetime
    holdings_after: float
    trade_qty: float
    side: str


class AlmgrenChrissExecutor:
    """Optimal liquidation under linear impact + risk aversion."""

    def __init__(self, config: Optional[AlmgrenChrissConfig] = None):
        self.config = config or AlmgrenChrissConfig()

    def _kappa(self) -> float:
        cfg = self.config
        if cfg.risk_aversion == 0:
            return 0.0
        eta_hat = cfg.eta * (1.0 - 0.5 * cfg.tau * cfg.gamma / cfg.eta)
        eta_hat = max(eta_hat, 1e-12)
        kappa_sq = cfg.risk_aversion * (cfg.sigma ** 2) / eta_hat
        kappa = np.arcsinh(0.5 * np.sqrt(kappa_sq) * cfg.tau)
        return float(kappa)

    def trajectory(self, parent_qty: float) -> np.ndarray:
        """Return remaining holdings ``x_0 ... x_T`` (length ``T + 1``)."""
        if parent_qty <= 0:
            raise ValueError("parent_qty must be > 0")
        cfg = self.config
        T = cfg.n_steps
        kappa = self._kappa()
        ks = np.arange(T + 1)
        if kappa == 0.0 or T == 0:
            x = parent_qty * (1.0 - ks / T) if T > 0 else np.array([parent_qty])
        else:
            num = np.sinh(kappa * (T - ks))
            den = np.sinh(kappa * T)
            x = parent_qty * num / den
        x[0] = parent_qty
        x[-1] = 0.0
        return x

    def schedule(
        self,
        parent_qty: float,
        start: datetime,
    ) -> List[AlmgrenChrissSchedule]:
        """Return a list of trades realizing the optimal trajectory."""
        cfg = self.config
        x = self.trajectory(parent_qty)
        out: List[AlmgrenChrissSchedule] = []
        for k in range(1, len(x)):
            trade = float(x[k - 1] - x[k])
            ts = start + timedelta(seconds=cfg.tau * k)
            out.append(
                AlmgrenChrissSchedule(
                    step=k,
                    timestamp=ts,
                    holdings_after=float(x[k]),
                    trade_qty=trade,
                    side=cfg.side,
                )
            )
        return out

    def expected_cost(self, parent_qty: float) -> dict:
        """Expected impact cost and variance of the optimal trajectory."""
        cfg = self.config
        x = self.trajectory(parent_qty)
        n = np.diff(x) * -1.0  # trades per step (positive for sell)
        # absolute trade quantity for cost (sign-agnostic)
        n_abs = np.abs(n)
        impact = float(
            np.sum(cfg.eta * n_abs ** 2 + cfg.gamma * x[:-1] * n_abs)
        )
        var = float((cfg.sigma ** 2) * np.sum(x[:-1] ** 2) * cfg.tau)
        return {
            "impact_cost": impact,
            "trajectory_variance": var,
            "objective": impact + cfg.risk_aversion * var,
        }

    def execute(
        self,
        schedule: List[AlmgrenChrissSchedule],
        broker,
    ) -> List[dict]:
        """Submit trades sequentially via ``broker.submit_order``."""
        results = []
        for s in schedule:
            order = {
                "symbol": getattr(broker, "symbol", "TEST"),
                "qty": s.trade_qty,
                "side": s.side,
                "order_type": "market",
                "step": s.step,
                "timestamp": s.timestamp,
            }
            results.append(broker.submit_order(order))
        return results
