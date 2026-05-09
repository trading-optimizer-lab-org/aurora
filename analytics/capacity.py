"""Strategy capacity estimator (R132).

Capacity = the AUM at which the strategy's realised Sharpe drops by Y%
relative to the small-AUM baseline. Combines:

- the existing ADV haircut model in ``deployment/liquidity.py``
- the spread / slippage cost components in ``core/costs.py``
- the optional vol-driven spread model in ``core/spread_model.py``
  (R128)
- the optional borrow availability model in ``core/borrow_model.py``
  (R129) for short-side strategies

The estimator runs the cost-deducted Sharpe at multiple AUM levels and
returns the AUM where Sharpe degrades past a configured loss threshold.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

import numpy as np

from aurora.core.costs import CostModel, apply_costs
from aurora.core.metrics import compute_metrics


@dataclass(frozen=True)
class CapacityPoint:
    """Sharpe at a single AUM level."""

    aum_usd: float
    sharpe: float
    pct_adv: float


@dataclass(frozen=True)
class CapacityEstimate:
    """Capacity curve + headline AUM."""

    curve: List[CapacityPoint]
    baseline_sharpe: float
    capacity_aum_usd: Optional[float]
    sharpe_drop_pct: float


def _scale_costs_with_size(
    base_costs: CostModel,
    *,
    pct_adv: float,
    impact_coef_bps_per_pct_adv: float,
) -> CostModel:
    """Inflate slippage_bps using a linear impact-vs-size model.

    Slippage scales linearly with order size as a fraction of ADV, an
    approximation good enough for capacity ranking even though the true
    relationship is concave in real microstructure data.
    """
    extra = impact_coef_bps_per_pct_adv * max(pct_adv, 0.0)
    return CostModel(
        commission_bps=base_costs.commission_bps,
        spread_bps=base_costs.spread_bps,
        slippage_bps=base_costs.slippage_bps + extra,
        borrow_rate_annual=base_costs.borrow_rate_annual,
        min_commission_usd=base_costs.min_commission_usd,
        fixed_per_trade_usd=base_costs.fixed_per_trade_usd,
    )


def estimate_capacity(
    weights: np.ndarray,
    asset_returns: np.ndarray,
    *,
    base_costs: CostModel,
    daily_dollar_volume: float,
    aum_grid_usd: Sequence[float],
    impact_coef_bps_per_pct_adv: float = 5.0,
    max_sharpe_drop_pct: float = 0.20,
    ppy: int = 252,
) -> CapacityEstimate:
    """Sweep AUM levels, recompute net Sharpe, return capacity AUM.

    Args:
        weights: per-period weight series.
        asset_returns: per-period asset return series (aligned with weights).
        base_costs: small-size cost model (spread + commission + base
            slippage + borrow). Slippage is the only component we scale
            with order size.
        daily_dollar_volume: typical daily dollar volume of the traded
            asset (median of the recent ADV is fine).
        aum_grid_usd: list of AUM levels to evaluate. Pass an ascending
            grid; the first is the small-size baseline.
        impact_coef_bps_per_pct_adv: extra slippage in bps per 1% of ADV
            traded. Default 5.0 = 5bp per 1% of ADV (conservative).
        max_sharpe_drop_pct: capacity is the largest AUM where realised
            Sharpe stays within (1 - drop) * baseline_sharpe.
        ppy: periods per year.

    Returns:
        :class:`CapacityEstimate` with the per-AUM curve and the
        capacity headline (the largest AUM that respects the Sharpe-drop
        threshold; ``None`` if every level violates).
    """
    if not aum_grid_usd:
        raise ValueError("aum_grid_usd is empty")
    if daily_dollar_volume <= 0:
        raise ValueError("daily_dollar_volume must be > 0")
    grid = sorted(float(x) for x in aum_grid_usd)
    weights = np.asarray(weights, dtype=float)
    asset_returns = np.asarray(asset_returns, dtype=float)
    turnover = float(np.abs(np.diff(weights, prepend=0.0)).mean())

    curve: List[CapacityPoint] = []
    for aum in grid:
        notional_per_bar = aum * turnover
        pct_adv = notional_per_bar / daily_dollar_volume * 100.0
        scaled = _scale_costs_with_size(
            base_costs,
            pct_adv=pct_adv,
            impact_coef_bps_per_pct_adv=impact_coef_bps_per_pct_adv,
        )
        net = apply_costs(weights, asset_returns, scaled)
        sharpe = float(compute_metrics(net, ppy=ppy).sharpe)
        curve.append(CapacityPoint(aum_usd=aum, sharpe=sharpe, pct_adv=pct_adv))

    baseline = curve[0].sharpe
    threshold = baseline * (1.0 - max_sharpe_drop_pct) if baseline > 0 else baseline
    capacity_aum: Optional[float] = None
    for point in curve:
        if point.sharpe >= threshold:
            capacity_aum = point.aum_usd
        else:
            break
    return CapacityEstimate(
        curve=curve,
        baseline_sharpe=baseline,
        capacity_aum_usd=capacity_aum,
        sharpe_drop_pct=max_sharpe_drop_pct,
    )


__all__ = [
    "CapacityPoint",
    "CapacityEstimate",
    "estimate_capacity",
]
