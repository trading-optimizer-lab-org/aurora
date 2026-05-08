"""Champion / Challenger framework.

Runs a current "champion" strategy and one or more "challengers" side by
side on the same return stream. A challenger is promoted to champion when
its rolling metric (Sharpe or mean return) beats the champion's metric by
at least ``min_edge`` for ``promotion_window`` consecutive checks.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from typing import Literal
import math
import numpy as np


Metric = Literal["sharpe", "mean", "median"]


@dataclass
class StrategyState:
    name: str
    rets: deque[float] = field(default_factory=lambda: deque(maxlen=2048))
    wins_streak: int = 0
    promotions: int = 0


@dataclass
class ChampionDecision:
    champion: str
    previous_champion: str
    promoted: bool
    metrics: dict[str, float]


class ChampionChallengerFramework:
    """Maintain a champion + challengers; promote when challenger wins consistently."""

    def __init__(self, champion: str, challengers: list[str],
                 metric: Metric = "sharpe", min_edge: float = 0.05,
                 promotion_window: int = 5, min_observations: int = 20):
        if not champion:
            raise ValueError("champion must be non-empty")
        if not challengers:
            raise ValueError("challengers must be non-empty")
        if champion in challengers:
            raise ValueError("champion cannot also be a challenger")
        if metric not in ("sharpe", "mean", "median"):
            raise ValueError(f"unknown metric: {metric!r}")
        if min_edge < 0:
            raise ValueError("min_edge must be >= 0")
        if promotion_window < 1:
            raise ValueError("promotion_window must be >= 1")
        if min_observations < 2:
            raise ValueError("min_observations must be >= 2")
        self.metric = metric
        self.min_edge = float(min_edge)
        self.promotion_window = int(promotion_window)
        self.min_observations = int(min_observations)
        self.champion = champion
        self._states: dict[str, StrategyState] = {
            champion: StrategyState(name=champion),
        }
        for c in challengers:
            self._states[c] = StrategyState(name=c)

    @property
    def names(self) -> list[str]:
        return list(self._states)

    def update(self, returns: dict[str, float]) -> ChampionDecision:
        for name, r in returns.items():
            if name not in self._states:
                raise KeyError(f"unknown strategy: {name!r}")
            self._states[name].rets.append(float(r))
        metrics = self._compute_metrics()
        return self._maybe_promote(metrics)

    def _compute_metrics(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for name, st in self._states.items():
            if len(st.rets) < self.min_observations:
                out[name] = float("nan")
                continue
            arr = np.asarray(list(st.rets), dtype=float)
            if self.metric == "sharpe":
                m = float(arr.mean())
                s = float(arr.std(ddof=1))
                out[name] = (m / s) * math.sqrt(252) if s > 0 else 0.0
            elif self.metric == "mean":
                out[name] = float(arr.mean())
            else:  # median
                out[name] = float(np.median(arr))
        return out

    def _maybe_promote(self, metrics: dict[str, float]) -> ChampionDecision:
        previous = self.champion
        promoted = False
        champ_score = metrics.get(self.champion, float("nan"))
        if math.isnan(champ_score):
            return ChampionDecision(champion=self.champion,
                                    previous_champion=previous,
                                    promoted=False, metrics=metrics)
        # find best challenger
        best_name = self.champion
        best_score = champ_score
        for name, score in metrics.items():
            if name == self.champion or math.isnan(score):
                continue
            edge = score - champ_score
            if edge >= self.min_edge and score > best_score:
                best_name = name
                best_score = score
        # update streaks
        for name, st in self._states.items():
            if name == self.champion:
                st.wins_streak = 0
                continue
            score = metrics.get(name, float("nan"))
            if math.isnan(score):
                st.wins_streak = 0
                continue
            edge = score - champ_score
            if edge >= self.min_edge:
                st.wins_streak += 1
            else:
                st.wins_streak = 0
        # promote leader if streak met
        if best_name != self.champion:
            if self._states[best_name].wins_streak >= self.promotion_window:
                self.champion = best_name
                self._states[best_name].promotions += 1
                self._states[best_name].wins_streak = 0
                promoted = True
        return ChampionDecision(champion=self.champion,
                                previous_champion=previous,
                                promoted=promoted, metrics=metrics)

    def state(self, name: str) -> StrategyState:
        if name not in self._states:
            raise KeyError(f"unknown strategy: {name!r}")
        return self._states[name]
