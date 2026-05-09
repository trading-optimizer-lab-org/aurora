"""What-if scenario replay (R117).

Replay an approved strategy under hypothetical perturbations. Differs
from R76 stress scenarios (canonical historical periods) by being
arbitrary user-defined overlays.

Examples:
- "if VIX had been 50 on every day"
- "if costs had been 2x"
- "if the 2008 crash had happened in 2024"

The implementation is a thin wrapper: the operator supplies a
returns / weights / costs perturbation function; the module returns
a side-by-side metrics comparison.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from aurora.core.costs import CostModel, ZERO_costs, apply_costs
from aurora.core.metrics import Metrics, compute_metrics


# --------------------------------------------------------------------------
# Types
# --------------------------------------------------------------------------


WeightPerturber = Callable[[np.ndarray], np.ndarray]
ReturnPerturber = Callable[[np.ndarray], np.ndarray]
CostPerturber = Callable[[CostModel], CostModel]


@dataclass(frozen=True)
class WhatIfReport:
    """Side-by-side baseline vs perturbed metrics."""

    label: str
    baseline: Metrics
    perturbed: Metrics

    @property
    def sharpe_delta(self) -> float:
        return self.perturbed.sharpe - self.baseline.sharpe

    @property
    def calmar_delta(self) -> float:
        return self.perturbed.calmar - self.baseline.calmar


# --------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------


def what_if(
    weights: np.ndarray,
    asset_returns: np.ndarray,
    *,
    label: str,
    costs: CostModel = ZERO_costs,
    weight_perturber: Optional[WeightPerturber] = None,
    return_perturber: Optional[ReturnPerturber] = None,
    cost_perturber: Optional[CostPerturber] = None,
    ppy: int = 252,
) -> WhatIfReport:
    """Run baseline + one perturbed variant and return a side-by-side report."""
    weights = np.asarray(weights, dtype=float)
    asset_returns = np.asarray(asset_returns, dtype=float)
    if len(weights) != len(asset_returns):
        raise ValueError("weights and returns length mismatch")
    base_net = apply_costs(weights, asset_returns, costs)
    base_metrics = compute_metrics(base_net, ppy=ppy)

    pert_w = weight_perturber(weights) if weight_perturber else weights
    pert_r = return_perturber(asset_returns) if return_perturber else asset_returns
    pert_c = cost_perturber(costs) if cost_perturber else costs
    pert_net = apply_costs(pert_w, pert_r, pert_c)
    pert_metrics = compute_metrics(pert_net, ppy=ppy)

    return WhatIfReport(
        label=label,
        baseline=base_metrics,
        perturbed=pert_metrics,
    )


__all__ = [
    "WhatIfReport",
    "what_if",
]
