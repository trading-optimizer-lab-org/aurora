"""Dynamic position-size cap based on realtime liquidity (R133).

Static position caps fail in two regimes:

1. The market thins (holidays, post-earnings, vol shocks) and the
   strategy keeps placing orders sized for normal liquidity. Cost
   blows up.
2. The market deepens (high-volume open) and the static cap leaves
   capacity on the table.

This module recomputes the per-symbol cap from realtime ADV / depth
each bar and refuses oversized orders at the gateway.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np


@dataclass(frozen=True)
class DynamicCapConfig:
    """Knobs for dynamic-cap computation.

    Attributes:
        max_pct_adv: hard upper bound on order notional as a percentage
            of trailing ADV. 1.0 = 1% of ADV, the typical conservative
            ceiling for impact-sensitive strategies.
        adv_window_bars: lookback for the trailing ADV.
        thin_market_haircut: extra multiplicative haircut applied when
            current bar's volume is below the median of the trailing
            window. 0.5 = halve the cap during thin sessions.
        absolute_floor_usd: minimum order size (in USD) the gateway is
            still willing to place; below this, route the trade to a
            cancel queue instead.
    """

    max_pct_adv: float = 1.0
    adv_window_bars: int = 20
    thin_market_haircut: float = 0.5
    absolute_floor_usd: float = 1_000.0


@dataclass(frozen=True)
class DynamicCapResult:
    """Outcome of one dynamic-cap evaluation."""

    cap_notional_usd: float
    rationale: str
    adv_usd: float
    is_thin: bool


def compute_dynamic_cap(
    *,
    config: DynamicCapConfig,
    recent_dollar_volume: np.ndarray,
    current_dollar_volume: float,
) -> DynamicCapResult:
    """Compute the per-bar order cap from realtime liquidity.

    Args:
        config: tunable thresholds.
        recent_dollar_volume: trailing dollar-volume series. Most recent
            entry is interpreted as the just-closed bar.
        current_dollar_volume: this bar's dollar volume so far.

    Returns:
        :class:`DynamicCapResult` with the computed cap and rationale.
    """
    arr = np.asarray(recent_dollar_volume, dtype=float)
    if len(arr) < 5:
        # Not enough data: fall back to a tight default.
        return DynamicCapResult(
            cap_notional_usd=config.absolute_floor_usd,
            rationale="insufficient ADV history; falling back to absolute floor",
            adv_usd=float(arr.mean()) if len(arr) else 0.0,
            is_thin=True,
        )
    adv = float(arr[-config.adv_window_bars:].mean())
    median = float(np.median(arr[-config.adv_window_bars:]))
    is_thin = current_dollar_volume < median

    base_cap = adv * (config.max_pct_adv / 100.0)
    if is_thin:
        cap = base_cap * config.thin_market_haircut
        rationale = (
            f"thin market detected (current ${current_dollar_volume:,.0f} "
            f"< median ${median:,.0f}); applying {config.thin_market_haircut}x haircut"
        )
    else:
        cap = base_cap
        rationale = (
            f"normal liquidity; cap = {config.max_pct_adv}% of ADV "
            f"${adv:,.0f}"
        )
    if cap < config.absolute_floor_usd:
        return DynamicCapResult(
            cap_notional_usd=0.0,
            rationale=(
                f"cap below absolute floor ${config.absolute_floor_usd:,.0f}; "
                "routing to cancel queue"
            ),
            adv_usd=adv,
            is_thin=is_thin,
        )
    return DynamicCapResult(
        cap_notional_usd=cap,
        rationale=rationale,
        adv_usd=adv,
        is_thin=is_thin,
    )


def reject_oversized_order(
    *,
    requested_notional_usd: float,
    cap: DynamicCapResult,
) -> Optional[str]:
    """Return a rejection reason or None if order is within the cap."""
    if cap.cap_notional_usd <= 0.0:
        return f"order refused: {cap.rationale}"
    if requested_notional_usd > cap.cap_notional_usd:
        return (
            f"order refused: requested ${requested_notional_usd:,.0f} "
            f"exceeds dynamic cap ${cap.cap_notional_usd:,.0f}"
            f" ({cap.rationale})"
        )
    return None


__all__ = [
    "DynamicCapConfig",
    "DynamicCapResult",
    "compute_dynamic_cap",
    "reject_oversized_order",
]
