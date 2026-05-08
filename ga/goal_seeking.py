"""Goal-seeking GA driver (R102).

"Find me a strategy with Sharpe >= 1.2 and MDD <= 15% in under 2 hours
of compute" -- the build runs until the goal is met or the budget
expires. Today GA runs for a fixed number of generations.

This driver wraps any GA-style runner with a goal predicate + budget
check. The runner only needs to expose:

- ``best_so_far()`` -> dict of metric -> value
- ``step()`` -> advance one generation

The driver loops until the goal predicate fires or the wall budget
expires, whichever comes first.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, Mapping, Optional, Protocol


class _GARunner(Protocol):
    def step(self) -> None: ...
    def best_so_far(self) -> Dict[str, float]: ...


@dataclass(frozen=True)
class Goal:
    """Goal predicate over the best-so-far metric dict."""

    name: str
    predicate: Callable[[Mapping[str, float]], bool]


@dataclass(frozen=True)
class GoalSeekResult:
    """Outcome of a goal-seeking run."""

    goal_met: bool
    elapsed_seconds: float
    generations: int
    final_metrics: Dict[str, float]
    rationale: str


def goal_seek(
    *,
    runner: _GARunner,
    goal: Goal,
    max_seconds: float = 60.0,
    max_generations: Optional[int] = None,
) -> GoalSeekResult:
    """Loop the runner until the goal fires or the budget expires."""
    t0 = time.perf_counter()
    n = 0
    while True:
        runner.step()
        n += 1
        elapsed = time.perf_counter() - t0
        best = runner.best_so_far()
        if goal.predicate(best):
            return GoalSeekResult(
                goal_met=True,
                elapsed_seconds=elapsed,
                generations=n,
                final_metrics=dict(best),
                rationale=f"goal '{goal.name}' met after {n} generations / {elapsed:.2f}s",
            )
        if elapsed >= max_seconds:
            return GoalSeekResult(
                goal_met=False,
                elapsed_seconds=elapsed,
                generations=n,
                final_metrics=dict(best),
                rationale=(
                    f"budget {max_seconds:.1f}s exhausted; "
                    f"best so far does not meet '{goal.name}'"
                ),
            )
        if max_generations is not None and n >= max_generations:
            return GoalSeekResult(
                goal_met=False,
                elapsed_seconds=elapsed,
                generations=n,
                final_metrics=dict(best),
                rationale=(
                    f"max generations {max_generations} reached; "
                    f"best so far does not meet '{goal.name}'"
                ),
            )


def make_sharpe_mdd_goal(
    *,
    min_sharpe: float,
    max_mdd: float,  # negative number, e.g. -0.15
) -> Goal:
    """Convenience constructor for the canonical ``Sharpe >= X AND MDD >= Y`` goal."""
    def predicate(metrics: Mapping[str, float]) -> bool:
        sharpe = float(metrics.get("sharpe", float("-inf")))
        mdd = float(metrics.get("mdd", float("-inf")))
        return sharpe >= min_sharpe and mdd >= max_mdd
    return Goal(
        name=f"sharpe>={min_sharpe} AND mdd>={max_mdd}",
        predicate=predicate,
    )


__all__ = [
    "Goal",
    "GoalSeekResult",
    "goal_seek",
    "make_sharpe_mdd_goal",
]
