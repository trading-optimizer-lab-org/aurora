"""Self-modifying strategy via online bandit-style param search.

Wraps a base signal function and, at each step, evaluates a small slate of
neighbour parameter perturbations on a rolling recent-returns window. The
perturbation with the best recent Sharpe is adopted. This is essentially
an epsilon-greedy bandit over a continuous arm space, with the arms being
local jitters around the current operating point.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable

import numpy as np


SignalFn = Callable[[np.ndarray, dict], float]


def _sharpe(returns: np.ndarray) -> float:
    if returns.size == 0:
        return 0.0
    sd = float(returns.std(ddof=0))
    if sd == 0.0:
        return 0.0
    return float(returns.mean() / sd) * np.sqrt(252.0)


@dataclass
class SelfModifyingStrategy:
    """Online self-tuning wrapper around a parametric signal function.

    Parameters
    ----------
    signal_fn : SignalFn
        ``signal_fn(window, params) -> position`` in [-1, 1].
    init_params : dict
        Starting point in parameter space (numeric values only).
    window_size : int
        Number of recent prices passed to the signal function.
    eval_window : int
        Number of recent strategy returns scored per arm.
    n_arms : int
        Number of perturbed parameter sets evaluated per step.
    jitter : float
        Per-step relative perturbation magnitude.
    epsilon : float
        Probability of an exploratory random restart (in [0, 1]).
    seed : int
        RNG seed.
    """

    signal_fn: SignalFn
    init_params: dict
    window_size: int = 64
    eval_window: int = 32
    n_arms: int = 5
    jitter: float = 0.1
    epsilon: float = 0.05
    seed: int = 42
    params: dict = field(init=False)
    history: list = field(init=False, default_factory=list)
    _rng: random.Random = field(init=False, repr=False)
    _np_rng: np.random.Generator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not (0.0 <= self.epsilon <= 1.0):
            raise ValueError("epsilon must be in [0, 1]")
        self.params = dict(self.init_params)
        self._rng = random.Random(self.seed)
        self._np_rng = np.random.default_rng(self.seed)

    def _perturb(self, base: dict) -> dict:
        out: dict = {}
        for k, v in base.items():
            if isinstance(v, (int, float)):
                noise = self._rng.gauss(0.0, self.jitter * (abs(v) or 1.0))
                new = float(v) + noise
                out[k] = type(v)(new) if isinstance(v, int) else new
            else:
                out[k] = v
        return out

    def step(self, recent_prices: np.ndarray) -> float:
        """Run one online tuning step against the latest price window.

        Returns the position selected by the (possibly updated) params.
        """
        recent_prices = np.asarray(recent_prices, dtype=float)
        if recent_prices.size < self.eval_window + 1:
            # Not enough data yet; evaluate the current params and skip search.
            window = recent_prices[-self.window_size :]
            return float(self.signal_fn(window, self.params))

        # Build candidate arms: incumbent + perturbations (+ optional restart).
        arms: list[dict] = [dict(self.params)]
        for _ in range(self.n_arms):
            arms.append(self._perturb(self.params))
        if self._rng.random() < self.epsilon:
            arms.append({k: self._rng.uniform(-1.0, 1.0) for k in self.params})

        # Score each arm by the Sharpe of its positions on the eval window.
        rets_window = np.diff(recent_prices) / recent_prices[:-1]
        eval_rets = rets_window[-self.eval_window :]
        scores = []
        for arm in arms:
            positions = np.array(
                [
                    self.signal_fn(
                        recent_prices[: -self.eval_window + i + 1][-self.window_size :],
                        arm,
                    )
                    for i in range(self.eval_window)
                ]
            )
            scores.append(_sharpe(positions * eval_rets))
        best = int(np.argmax(scores))
        self.params = arms[best]
        self.history.append({"params": dict(self.params), "sharpe": scores[best]})

        window = recent_prices[-self.window_size :]
        return float(self.signal_fn(window, self.params))
