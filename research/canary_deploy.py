"""Canary deployer.

Allocate a small slice of capital (default 1%) to a new strategy. Track
its realized return; if it clears a Sharpe / drawdown gate over a
``promotion_window`` of observations, scale the allocation up in
discrete steps. If it breaches a drawdown floor at any time, retire it.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from typing import Literal
import math
import numpy as np


CanaryStatus = Literal["canary", "scaling", "promoted", "retired"]


@dataclass
class CanaryReport:
    name: str
    status: CanaryStatus
    allocation: float
    n_observations: int
    sharpe: float
    max_drawdown: float
    promoted_at: int | None = None


class CanaryDeployer:
    """Stage a new strategy from 1% to full allocation."""

    def __init__(self, name: str, initial_alloc: float = 0.01,
                 step_alloc: float = 0.05, max_alloc: float = 0.5,
                 sharpe_gate: float = 1.0, dd_floor: float = -0.10,
                 promotion_window: int = 30, min_observations: int = 20):
        if not name:
            raise ValueError("name must be non-empty")
        if not (0.0 < initial_alloc <= max_alloc < 1.0):
            raise ValueError("require 0 < initial_alloc <= max_alloc < 1")
        if step_alloc <= 0:
            raise ValueError("step_alloc must be > 0")
        if dd_floor >= 0:
            raise ValueError("dd_floor must be negative (e.g. -0.10)")
        if promotion_window < 1:
            raise ValueError("promotion_window must be >= 1")
        if min_observations < 2:
            raise ValueError("min_observations must be >= 2")
        self.name = name
        self.initial_alloc = float(initial_alloc)
        self.step_alloc = float(step_alloc)
        self.max_alloc = float(max_alloc)
        self.sharpe_gate = float(sharpe_gate)
        self.dd_floor = float(dd_floor)
        self.promotion_window = int(promotion_window)
        self.min_observations = int(min_observations)
        self._allocation = self.initial_alloc
        self._status: CanaryStatus = "canary"
        self._rets: deque[float] = deque(maxlen=4096)
        self._gate_streak = 0
        self._promoted_at: int | None = None

    @property
    def allocation(self) -> float:
        return self._allocation

    @property
    def status(self) -> CanaryStatus:
        return self._status

    def update(self, ret: float) -> CanaryReport:
        if self._status == "retired":
            return self._build_report()
        self._rets.append(float(ret))
        sharpe, dd = self._compute_stats()
        if dd <= self.dd_floor:
            self._status = "retired"
            self._allocation = 0.0
            return self._build_report()
        if len(self._rets) < self.min_observations:
            return self._build_report()
        if sharpe >= self.sharpe_gate:
            self._gate_streak += 1
        else:
            self._gate_streak = 0
        if self._gate_streak >= self.promotion_window:
            new_alloc = min(self.max_alloc, self._allocation + self.step_alloc)
            if new_alloc >= self.max_alloc:
                self._status = "promoted"
                self._allocation = self.max_alloc
                if self._promoted_at is None:
                    self._promoted_at = len(self._rets)
            else:
                self._status = "scaling"
                self._allocation = new_alloc
            self._gate_streak = 0
        return self._build_report()

    def _compute_stats(self) -> tuple[float, float]:
        if len(self._rets) < 2:
            return 0.0, 0.0
        arr = np.asarray(list(self._rets), dtype=float)
        m = float(arr.mean())
        s = float(arr.std(ddof=1))
        sharpe = (m / s) * math.sqrt(252) if s > 0 else 0.0
        eq = np.cumprod(1.0 + arr)
        peak = np.maximum.accumulate(eq)
        dd = float((eq / peak - 1.0).min())
        return sharpe, dd

    def _build_report(self) -> CanaryReport:
        sharpe, dd = self._compute_stats()
        return CanaryReport(
            name=self.name, status=self._status,
            allocation=float(self._allocation),
            n_observations=len(self._rets),
            sharpe=sharpe, max_drawdown=dd,
            promoted_at=self._promoted_at,
        )
