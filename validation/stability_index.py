"""Consolidated stability index (R98).

Aggregate the existing scattered stability signals into one 0..1
score so an operator can rank-order candidates by a single number.
Components:

- SPP CV (lower is better).
- Walk-forward Calmar variance (lower is better).
- Monte Carlo trade-reorder spread (lower is better).
- Scenario-stress breadth (more passing scenarios is better).
- CSCV / PBO probability of backtest overfitting (lower is better).

Each component contributes a normalised sub-score in [0, 1]. The
composite is the geometric mean of the sub-scores, so a single very
weak component drags the total down faster than the arithmetic mean
would.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class StabilityComponents:
    """Raw per-component inputs to the stability index.

    Each field is optional; missing components contribute neutrally
    (sub-score = 0.5) so a partial input still yields a usable score.
    """

    spp_cv: Optional[float] = None
    wf_calmar_std: Optional[float] = None
    mc_trade_reorder_spread: Optional[float] = None
    scenarios_pass_rate: Optional[float] = None
    pbo_probability: Optional[float] = None


@dataclass(frozen=True)
class StabilityIndex:
    """Composite 0..1 stability score plus per-component sub-scores."""

    composite: float
    spp_subscore: float
    wf_subscore: float
    mc_subscore: float
    scenario_subscore: float
    pbo_subscore: float
    components: StabilityComponents


def _saturating_inverse(value: float, scale: float) -> float:
    """Map a non-negative metric (lower is better) into [0, 1].

    ``scale`` is the value at which the sub-score drops to ~0.5.
    Higher value -> sub-score asymptotes to 0.
    """
    if not np.isfinite(value) or value < 0 or scale <= 0:
        return 0.5
    return float(scale / (scale + value))


def _clip01(value: float) -> float:
    if not np.isfinite(value):
        return 0.5
    return float(min(1.0, max(0.0, value)))


def stability_index(components: StabilityComponents) -> StabilityIndex:
    """Aggregate ``components`` into a 0..1 composite stability score."""

    # Lower-is-better components -> saturating inverse with scale set
    # to "the value above which the gate would have failed".
    spp_sub = (
        _saturating_inverse(components.spp_cv, 0.30)
        if components.spp_cv is not None else 0.5
    )
    wf_sub = (
        _saturating_inverse(components.wf_calmar_std, 0.40)
        if components.wf_calmar_std is not None else 0.5
    )
    mc_sub = (
        _saturating_inverse(components.mc_trade_reorder_spread, 0.20)
        if components.mc_trade_reorder_spread is not None else 0.5
    )
    pbo_sub = (
        _saturating_inverse(components.pbo_probability, 0.40)
        if components.pbo_probability is not None else 0.5
    )

    # Scenario pass rate: higher is better; already in [0, 1].
    scenario_sub = (
        _clip01(components.scenarios_pass_rate)
        if components.scenarios_pass_rate is not None else 0.5
    )

    # Geometric mean -- single weak component drags the composite down.
    sub_scores = np.array(
        [spp_sub, wf_sub, mc_sub, scenario_sub, pbo_sub], dtype=float
    )
    sub_scores = np.clip(sub_scores, 1e-6, 1.0)
    composite = float(np.exp(np.log(sub_scores).mean()))

    return StabilityIndex(
        composite=composite,
        spp_subscore=spp_sub,
        wf_subscore=wf_sub,
        mc_subscore=mc_sub,
        scenario_subscore=scenario_sub,
        pbo_subscore=pbo_sub,
        components=components,
    )


__all__ = [
    "StabilityComponents",
    "StabilityIndex",
    "stability_index",
]
