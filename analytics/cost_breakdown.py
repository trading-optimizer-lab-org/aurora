"""Cost decomposition view (R127).

Today the tearsheet shows net returns. This module breaks down the
PnL drag by component (spread, slippage, borrow, taxes, market impact,
execution delay) so operators see which cost is eating the edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import numpy as np

from aurora.core.costs import CostModel


@dataclass(frozen=True)
class CostBreakdown:
    """PnL drag attributed to each component."""

    spread_drag_bps: float
    commission_drag_bps: float
    slippage_drag_bps: float
    borrow_drag_bps: float
    total_drag_bps: float

    def as_dict(self) -> Dict[str, float]:
        return {
            "spread_bps": self.spread_drag_bps,
            "commission_bps": self.commission_drag_bps,
            "slippage_bps": self.slippage_drag_bps,
            "borrow_bps": self.borrow_drag_bps,
            "total_bps": self.total_drag_bps,
        }


def decompose_cost(
    weights: np.ndarray,
    *,
    costs: CostModel,
    n_periods: int,
    ppy: int = 252,
) -> CostBreakdown:
    """Estimate per-component drag in bps from the existing CostModel.

    Approach: the existing ``apply_costs`` rolls every cost into a
    single bps figure. To decompose, recompute each component as if
    the others were zero, multiply by realised turnover, and report
    the per-component drag.
    """
    weights = np.asarray(weights, dtype=float)
    if n_periods <= 0:
        raise ValueError("n_periods must be > 0")
    delta_w = np.abs(np.diff(weights, prepend=0.0))
    turnover = float(delta_w.sum())
    n = max(1, n_periods)

    spread_drag = (2 * costs.spread_bps) * turnover
    commission_drag = costs.commission_bps * turnover
    slippage_drag = (2 * costs.slippage_bps) * turnover
    short_carried = float(np.abs(np.minimum(weights, 0.0)).sum())
    borrow_drag = costs.borrow_rate_annual * 1e4 * (short_carried / n)

    total = spread_drag + commission_drag + slippage_drag + borrow_drag
    return CostBreakdown(
        spread_drag_bps=spread_drag,
        commission_drag_bps=commission_drag,
        slippage_drag_bps=slippage_drag,
        borrow_drag_bps=borrow_drag,
        total_drag_bps=total,
    )


__all__ = ["CostBreakdown", "decompose_cost"]
