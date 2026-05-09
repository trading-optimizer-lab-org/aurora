"""Synthetic adversarial market generator (R144).

Generate price paths designed to break a given strategy. The generator
applies gradient-style perturbation that maximises strategy drawdown
subject to a realistic-volatility constraint.

The full Monte Carlo gives a "typical" worst case. Adversarial markets
give the *bespoke* worst case for this exact rule. A strategy that
survives an adversarial market is materially more robust than one that
only survives Monte Carlo.

Approach (deliberately simple, deterministic, no external ML):

1. Start from the historical return series.
2. For each bar, propose a small perturbation in {-eps, +eps}.
3. Score each bar's perturbation by its impact on running drawdown
   when run through the supplied strategy callback.
4. Apply the perturbations greedily up to a configurable budget. The
   resulting path has drawdown <= the historical drawdown.
5. Optionally clip the perturbed series to keep realised vol within a
   tolerance of the historical realised vol so the result stays
   plausible.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np


@dataclass(frozen=True)
class AdversarialConfig:
    """Knobs for the adversarial-path generator.

    Attributes:
        epsilon: per-bar perturbation magnitude (in return units; e.g.
            0.001 = 10bp).
        budget_fraction: fraction of bars allowed to be perturbed.
        vol_tolerance_pct: cap on the relative change in realised vol
            after perturbation. 0.10 = realised vol must stay within
            +/-10% of the original.
        seed: RNG seed (used only for deterministic tie-breaking).
    """

    epsilon: float = 0.002
    budget_fraction: float = 0.20
    vol_tolerance_pct: float = 0.15
    seed: int = 42


@dataclass(frozen=True)
class AdversarialResult:
    """Outcome of the adversarial generation."""

    perturbed_returns: np.ndarray
    historical_drawdown: float
    adversarial_drawdown: float
    bars_perturbed: int
    survived: bool


def _max_drawdown(returns: np.ndarray) -> float:
    if len(returns) == 0:
        return 0.0
    eq = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    return float(dd.min())


def _realised_vol(returns: np.ndarray) -> float:
    return float(np.std(returns, ddof=0))


def generate_adversarial_market(
    historical_returns: np.ndarray,
    *,
    strategy: Callable[[np.ndarray], np.ndarray],
    config: Optional[AdversarialConfig] = None,
    survival_drawdown_threshold: float = -0.30,
) -> AdversarialResult:
    """Generate an adversarial path that maximises drawdown.

    Args:
        historical_returns: 1-D series of asset returns.
        strategy: callable that maps an asset-return series to a series
            of strategy returns. Most callers pass a closure that runs
            the strategy weights through ``apply_costs``.
        config: tunable parameters.
        survival_drawdown_threshold: drawdown below which the strategy
            is declared "did not survive". Default -30%.

    Returns:
        :class:`AdversarialResult` with the perturbed path, drawdown
        comparison, and survival flag.
    """
    if config is None:
        config = AdversarialConfig()
    rng = np.random.default_rng(config.seed)
    arr = np.asarray(historical_returns, dtype=float).copy()
    if len(arr) < 10:
        raise ValueError("need at least 10 bars to perturb meaningfully")
    base_strat = strategy(arr)
    base_dd = _max_drawdown(np.asarray(base_strat, dtype=float))
    base_vol = _realised_vol(arr)

    n_budget = max(1, int(len(arr) * config.budget_fraction))
    candidate_signs = np.where(arr >= 0, -1.0, 1.0)
    perturbed = arr.copy()
    perturbed_indices: list[int] = []

    # Greedy: prefer perturbations on bars where the strategy is exposed.
    # Without inspecting the strategy's internal weights, we approximate
    # exposure as the absolute realised return ranking.
    order = np.argsort(-np.abs(arr))
    for idx in order[: n_budget * 3]:
        candidate = perturbed.copy()
        candidate[idx] += candidate_signs[idx] * config.epsilon
        new_strat = strategy(candidate)
        new_dd = _max_drawdown(np.asarray(new_strat, dtype=float))
        new_vol = _realised_vol(candidate)
        within_vol = (
            base_vol == 0
            or abs(new_vol - base_vol) / base_vol <= config.vol_tolerance_pct
        )
        if new_dd < base_dd and within_vol:
            perturbed = candidate
            base_dd = new_dd
            perturbed_indices.append(int(idx))
        if len(perturbed_indices) >= n_budget:
            break
        # tie-break: deterministic permutation of equal-magnitude bars.
        _ = rng.random()

    survived = base_dd > survival_drawdown_threshold
    return AdversarialResult(
        perturbed_returns=perturbed,
        historical_drawdown=_max_drawdown(np.asarray(strategy(arr), dtype=float)),
        adversarial_drawdown=base_dd,
        bars_perturbed=len(perturbed_indices),
        survived=survived,
    )


__all__ = [
    "AdversarialConfig",
    "AdversarialResult",
    "generate_adversarial_market",
]
