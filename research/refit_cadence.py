"""Per-strategy walk-forward refit cadence optimiser (R141).

Re-running walk-forward at multiple cadences (weekly, monthly,
quarterly) and picking the cadence whose stability is highest. The
cadence with the lowest variance in OOS Sharpe across folds is the
most stable choice for the operator's lifecycle scheduler.

The output is consumed by R93 (re-optimisation scheduler) which fires
the actual refit job at that cadence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Sequence

import numpy as np


@dataclass(frozen=True)
class CadenceCandidate:
    """A candidate refit cadence + its observed OOS Sharpe path."""

    name: str
    interval_bars: int
    oos_sharpes: List[float]

    @property
    def mean_sharpe(self) -> float:
        if not self.oos_sharpes:
            return float("nan")
        return float(np.mean(self.oos_sharpes))

    @property
    def std_sharpe(self) -> float:
        if not self.oos_sharpes:
            return float("nan")
        return float(np.std(self.oos_sharpes, ddof=0))

    @property
    def stability_score(self) -> float:
        """Mean / std as a Sharpe-of-Sharpes. Higher = more stable."""
        s = self.std_sharpe
        if not np.isfinite(s) or s <= 1e-9:
            return float(self.mean_sharpe)
        return float(self.mean_sharpe / s)


@dataclass(frozen=True)
class CadenceRecommendation:
    """The optimiser's chosen cadence + scoreboard."""

    candidates: List[CadenceCandidate]
    chosen: CadenceCandidate
    rationale: str


def optimise_refit_cadence(
    candidates: Sequence[CadenceCandidate],
    *,
    min_folds: int = 3,
) -> CadenceRecommendation:
    """Pick the cadence with the highest stability score.

    Args:
        candidates: list of pre-computed candidates. The caller runs the
            walk-forward at each cadence and supplies the OOS sharpes.
        min_folds: cadence must have at least this many folds to be
            considered. Cadences below the threshold are dropped.

    Returns:
        :class:`CadenceRecommendation` with the chosen cadence and the
        full scoreboard.
    """
    eligible = [c for c in candidates if len(c.oos_sharpes) >= min_folds]
    if not eligible:
        raise ValueError(
            f"no cadence has >= {min_folds} folds; supply more data"
        )
    chosen = max(eligible, key=lambda c: c.stability_score)
    rationale = (
        f"{chosen.name} chosen with stability_score={chosen.stability_score:.3f} "
        f"(mean Sharpe {chosen.mean_sharpe:.3f} +/- {chosen.std_sharpe:.3f})"
    )
    return CadenceRecommendation(
        candidates=list(candidates),
        chosen=chosen,
        rationale=rationale,
    )


def standard_cadence_grid(
    *,
    weekly_bars: int = 5,
    monthly_bars: int = 21,
    quarterly_bars: int = 63,
    yearly_bars: int = 252,
) -> List[Dict[str, Any]]:
    """Default cadence grid: weekly / monthly / quarterly / yearly."""
    return [
        {"name": "weekly", "interval_bars": weekly_bars},
        {"name": "monthly", "interval_bars": monthly_bars},
        {"name": "quarterly", "interval_bars": quarterly_bars},
        {"name": "yearly", "interval_bars": yearly_bars},
    ]


__all__ = [
    "CadenceCandidate",
    "CadenceRecommendation",
    "optimise_refit_cadence",
    "standard_cadence_grid",
]
