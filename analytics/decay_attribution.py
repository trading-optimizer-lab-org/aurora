"""Causal-inference + decay attribution (R125 + R126).

When a strategy's realised Sharpe drops, attribute the gap to alpha
shrink, cost growth, regime change, or data drift. Pure-data
counterfactual replay isolating each component.

R125 = causal-inference for strategy degradation (one-shot triage).
R126 = monthly automated decay attribution (live operational view).

Both share the same primitives. The live wrapper schedules R126 on
cadence; R125 is invoked ad-hoc when a Sharpe drop is detected.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from aurora.core.costs import CostModel, ZERO_costs, apply_costs
from aurora.core.metrics import compute_metrics


@dataclass(frozen=True)
class AttributionInput:
    """Per-period observed inputs for one window."""

    weights: np.ndarray
    asset_returns: np.ndarray
    cost_model: CostModel
    regime_tag: Optional[str] = None


@dataclass(frozen=True)
class DecayAttribution:
    """Decomposition of the Sharpe gap between baseline and current."""

    baseline_sharpe: float
    current_sharpe: float
    sharpe_gap: float
    alpha_component: float
    cost_component: float
    regime_component: float
    residual_component: float

    @property
    def explained_fraction(self) -> float:
        if self.sharpe_gap == 0:
            return 1.0
        explained = (
            self.alpha_component
            + self.cost_component
            + self.regime_component
        )
        return float(explained / self.sharpe_gap) if self.sharpe_gap else 1.0


def _sharpe(weights: np.ndarray, rets: np.ndarray, costs: CostModel,
            ppy: int = 252) -> float:
    net = apply_costs(weights, rets, costs)
    return float(compute_metrics(net, ppy=ppy).sharpe)


def attribute_decay(
    baseline: AttributionInput,
    current: AttributionInput,
    *,
    ppy: int = 252,
) -> DecayAttribution:
    """Compute the Sharpe-gap decomposition between two windows.

    Counterfactuals (Sharpe held in each replay):

    1. baseline weights + baseline returns + baseline costs -> Sb (baseline)
    2. baseline weights + current returns + baseline costs -> S_alpha
    3. baseline weights + current returns + current costs  -> S_cost
    4. current  weights + current returns + current costs  -> Sc (current)

    Each step's delta is attributed to that component:

    - alpha_component = S_alpha - Sb (return-environment / regime change)
    - cost_component  = S_cost - S_alpha (cost-environment change)
    - residual = Sc - S_cost (anything not captured: weight rule changes)

    The current implementation collapses regime change inside
    ``alpha_component`` because we don't have an independent regime
    counterfactual; if the operator supplies a regime-stratified
    replay later, the regime field becomes the difference between
    same-regime and cross-regime alpha components.
    """
    sb = _sharpe(baseline.weights, baseline.asset_returns, baseline.cost_model, ppy)
    s_alpha = _sharpe(baseline.weights, current.asset_returns, baseline.cost_model, ppy)
    s_cost = _sharpe(baseline.weights, current.asset_returns, current.cost_model, ppy)
    sc = _sharpe(current.weights, current.asset_returns, current.cost_model, ppy)

    alpha_component = s_alpha - sb
    cost_component = s_cost - s_alpha
    regime_component = 0.0  # placeholder until per-regime replay arrives
    residual = sc - s_cost
    return DecayAttribution(
        baseline_sharpe=sb,
        current_sharpe=sc,
        sharpe_gap=sc - sb,
        alpha_component=alpha_component,
        cost_component=cost_component,
        regime_component=regime_component,
        residual_component=residual,
    )


__all__ = [
    "AttributionInput",
    "DecayAttribution",
    "attribute_decay",
]
