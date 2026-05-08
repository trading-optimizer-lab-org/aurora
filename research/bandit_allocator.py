"""Multi-armed bandit allocator for live strategies.

Two algorithms are exposed:

    UCB1     -- deterministic upper confidence bound
    Thompson -- Thompson sampling against a Normal-Inverse-Gamma posterior
                (returns are assumed Gaussian; conjugate prior).

Each "arm" is a strategy. After each round the caller calls ``update``
with the observed reward (typically a Sharpe-like or return-based score).
``allocate`` returns capital weights. A small uniform floor is enforced
so no arm is fully starved while we are still learning.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from math import log, sqrt
from typing import Literal
import numpy as np


Algorithm = Literal["ucb1", "thompson"]


@dataclass
class ArmState:
    name: str
    n_pulls: int = 0
    sum_reward: float = 0.0
    sum_sq_reward: float = 0.0

    @property
    def mean(self) -> float:
        if self.n_pulls == 0:
            return 0.0
        return self.sum_reward / self.n_pulls

    @property
    def variance(self) -> float:
        if self.n_pulls < 2:
            return 1.0
        m = self.mean
        return max(1e-9, self.sum_sq_reward / self.n_pulls - m * m)


@dataclass
class AllocationReport:
    weights: dict[str, float]
    algorithm: str
    total_pulls: int
    arm_means: dict[str, float] = field(default_factory=dict)


class LiveBanditAllocator:
    """Multi-armed bandit capital allocator across strategies."""

    def __init__(self, arms: list[str], algorithm: Algorithm = "ucb1",
                 floor: float = 0.05, c: float = 2.0, seed: int = 0):
        if not arms:
            raise ValueError("arms must be non-empty")
        if len(set(arms)) != len(arms):
            raise ValueError("arm names must be unique")
        if algorithm not in ("ucb1", "thompson"):
            raise ValueError(f"unknown algorithm: {algorithm!r}")
        if not (0.0 <= floor < 1.0 / len(arms)):
            raise ValueError(
                f"floor must be in [0, 1/n_arms) where n_arms={len(arms)}"
            )
        if c <= 0:
            raise ValueError("c must be > 0")
        self.algorithm = algorithm
        self.floor = float(floor)
        self.c = float(c)
        self._rng = np.random.default_rng(int(seed))
        self._arms: dict[str, ArmState] = {a: ArmState(name=a) for a in arms}

    @property
    def arm_names(self) -> list[str]:
        return list(self._arms)

    def update(self, arm: str, reward: float) -> None:
        if arm not in self._arms:
            raise KeyError(f"unknown arm: {arm!r}")
        st = self._arms[arm]
        st.n_pulls += 1
        st.sum_reward += float(reward)
        st.sum_sq_reward += float(reward) ** 2

    def allocate(self) -> AllocationReport:
        if self.algorithm == "ucb1":
            scores = self._ucb1_scores()
        else:
            scores = self._thompson_scores()
        weights = self._softmax_with_floor(scores)
        total = sum(a.n_pulls for a in self._arms.values())
        return AllocationReport(
            weights=weights, algorithm=self.algorithm,
            total_pulls=total,
            arm_means={a.name: a.mean for a in self._arms.values()},
        )

    def select(self) -> str:
        """Pick the single best arm under the current scores."""
        if self.algorithm == "ucb1":
            scores = self._ucb1_scores()
        else:
            scores = self._thompson_scores()
        return max(scores, key=lambda k: scores[k])

    # -- internals ---------------------------------------------------------

    def _ucb1_scores(self) -> dict[str, float]:
        total = sum(a.n_pulls for a in self._arms.values())
        scores: dict[str, float] = {}
        for name, st in self._arms.items():
            if st.n_pulls == 0:
                # Force exploration of unpulled arms
                scores[name] = float("inf")
            else:
                bonus = self.c * sqrt(log(max(1, total)) / st.n_pulls)
                scores[name] = st.mean + bonus
        return scores

    def _thompson_scores(self) -> dict[str, float]:
        scores: dict[str, float] = {}
        for name, st in self._arms.items():
            if st.n_pulls < 2:
                # broad prior
                scores[name] = float(self._rng.normal(0.0, 1.0))
            else:
                m = st.mean
                v = st.variance
                se = sqrt(v / st.n_pulls)
                scores[name] = float(self._rng.normal(m, se))
        return scores

    def _softmax_with_floor(self, scores: dict[str, float]
                            ) -> dict[str, float]:
        n = len(scores)
        # if any inf, everyone with inf splits the non-floor mass equally
        infs = [k for k, v in scores.items() if np.isinf(v)]
        if infs:
            mass = 1.0 - n * self.floor
            share = mass / len(infs)
            return {k: (self.floor + share if k in infs else self.floor)
                    for k in scores}
        # otherwise a stable softmax of the scores, then apply floor
        vals = np.array([scores[k] for k in self._arms])
        vals = vals - vals.max()
        exp = np.exp(vals)
        sm = exp / exp.sum()
        # floor + redistribute
        excess = sm - self.floor
        excess = np.maximum(excess, 0.0)
        if excess.sum() == 0:
            # everyone collapsed to floor: uniform
            wts = np.full(n, 1.0 / n)
        else:
            wts = self.floor + (1.0 - n * self.floor) * (excess / excess.sum())
        return {k: float(w) for k, w in zip(self._arms, wts)}
