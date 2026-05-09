"""Money management library (R88).

Extension of `deployment/sizing.py`. New sizing primitives:

- :func:`anti_martingale_sizing` -- scale up after wins, down after losses.
- :func:`fractional_kelly_with_shrinkage` -- shrink Kelly fraction when
  realised volatility is unusually high.
- :func:`fixed_ratio_sizing` -- Larry Williams fixed-ratio money mgmt.
- :func:`profit_step_pyramid` -- add to winners at fixed profit steps.
- :func:`drawdown_scaled_sizing` -- reduce size after consecutive losses.

Each callable returns a position-size scalar in the [0, max_leverage]
range, derived from the active ProtocolPolicy. Callers feed the
output into the existing engine weight pipeline.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _clip(value: float, max_leverage: float) -> float:
    return float(max(0.0, min(value, float(max_leverage))))


# --------------------------------------------------------------------------
# Anti-martingale
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AntiMartingaleConfig:
    base_size: float = 1.0
    win_step: float = 0.10
    loss_reset: bool = True
    max_size: float = 2.0


def anti_martingale_sizing(
    consecutive_wins: int,
    *,
    config: Optional[AntiMartingaleConfig] = None,
    max_leverage: float = 1.0,
) -> float:
    """Scale up after wins; reset on a loss when ``loss_reset`` is True."""
    if config is None:
        config = AntiMartingaleConfig()
    if consecutive_wins < 0:
        raise ValueError("consecutive_wins must be >= 0")
    raw = config.base_size + config.win_step * consecutive_wins
    raw = min(raw, config.max_size)
    return _clip(raw, max_leverage)


# --------------------------------------------------------------------------
# Fractional Kelly with shrinkage
# --------------------------------------------------------------------------


def fractional_kelly_with_shrinkage(
    edge: float,
    variance: float,
    *,
    fraction: float = 0.25,
    realised_vol: Optional[float] = None,
    expected_vol: Optional[float] = None,
    max_leverage: float = 1.0,
) -> float:
    """Fractional Kelly. Shrinks when realised vol exceeds expected.

    Args:
        edge: expected per-period excess return.
        variance: per-period variance.
        fraction: Kelly fraction (0.25 = quarter-Kelly).
        realised_vol: optional realised volatility for shrinkage.
        expected_vol: optional reference volatility used for shrinkage.
            When realised exceeds expected by ``r``, size is divided
            by ``r``.

    Returns:
        Position size in [0, max_leverage].
    """
    if variance <= 0 or edge <= 0:
        return 0.0
    kelly = edge / variance
    size = fraction * kelly
    if realised_vol is not None and expected_vol and expected_vol > 0:
        if realised_vol > expected_vol:
            size = size / (realised_vol / expected_vol)
    return _clip(size, max_leverage)


# --------------------------------------------------------------------------
# Fixed ratio (Larry Williams)
# --------------------------------------------------------------------------


def fixed_ratio_sizing(
    cumulative_pnl: float,
    *,
    delta: float = 5_000.0,
    starting_units: float = 1.0,
    max_leverage: float = 1.0,
) -> float:
    """Larry Williams fixed-ratio sizing.

    units = floor((-1 + sqrt(1 + 8 * cumulative_pnl / delta)) / 2)
    """
    if cumulative_pnl < 0:
        return _clip(starting_units, max_leverage)
    units = (-1 + math.sqrt(1 + 8 * cumulative_pnl / delta)) / 2
    return _clip(starting_units + units, max_leverage)


# --------------------------------------------------------------------------
# Profit-step pyramiding
# --------------------------------------------------------------------------


def profit_step_pyramid(
    open_pnl: float,
    *,
    step_size: float = 0.02,
    add_per_step: float = 0.25,
    base_size: float = 1.0,
    max_size: float = 2.0,
    max_leverage: float = 1.0,
) -> float:
    """Add to winners every ``step_size`` of unrealised gain."""
    if open_pnl <= 0:
        return _clip(base_size, max_leverage)
    steps = int(open_pnl // step_size)
    raw = base_size + steps * add_per_step
    raw = min(raw, max_size)
    return _clip(raw, max_leverage)


# --------------------------------------------------------------------------
# Drawdown-scaled
# --------------------------------------------------------------------------


def drawdown_scaled_sizing(
    consecutive_losses: int,
    *,
    base_size: float = 1.0,
    loss_step: float = 0.10,
    floor: float = 0.25,
    max_leverage: float = 1.0,
) -> float:
    """Reduce size after consecutive losses; floor at ``floor``."""
    if consecutive_losses < 0:
        raise ValueError("consecutive_losses must be >= 0")
    raw = base_size - loss_step * consecutive_losses
    raw = max(raw, floor)
    return _clip(raw, max_leverage)


__all__ = [
    "AntiMartingaleConfig",
    "anti_martingale_sizing",
    "fractional_kelly_with_shrinkage",
    "fixed_ratio_sizing",
    "profit_step_pyramid",
    "drawdown_scaled_sizing",
]
