"""Realistic slippage models for backtest (Task I.5).

Adds size-dependent market impact on top of the constant-bps slippage already
handled by ``CostModel``. ``CostModel.slippage_bps`` is a flat per-fill cost.
``SlippageModel`` here turns order size + ADV into incremental bps so a big
order pays more than a small one.

Models implemented:
    FixedBasisPointsSlippage - constant bps (parity check vs CostModel).
    VolumeShareSlippage      - Zipline-style quadratic in participation rate.
    SquareRootSlippage       - Almgren-Chriss sqrt(participation) impact.
    LinearSlippage           - linear in participation rate.

Sign convention (``side``):
    +1 buy  -> realized fill > mid  (paying impact)
    -1 sell -> realized fill < mid

References:
    Zipline ``zipline/finance/slippage.py``
    Almgren-Chriss (2000) "Optimal execution of portfolio transactions"
    Kissell-Glantz (2003) "Optimal trading strategies"
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional


_BPS = 1e4  # 1.0 = 10000 bps


def _participation(order_size_dollars: float, daily_volume_dollars: float) -> float:
    """Order size as fraction of ADV (in dollars). Uses |order|. Returns 0 on zero ADV."""
    if daily_volume_dollars <= 0.0:
        return 0.0
    return abs(order_size_dollars) / daily_volume_dollars


class SlippageModel(ABC):
    """Abstract base. ``fill_price`` returns realized price for a given order.

    Subclasses must also implement ``impact_bps`` so callers (e.g. engine) can
    convert size-dependent impact into a bps-adjustment for ``apply_costs``.
    """

    @abstractmethod
    def impact_bps(self, order_size_dollars: float, daily_volume_dollars: float) -> float:
        """One-sided impact in bps for a given order size vs ADV.

        Returns ``math.nan`` to signal the order would breach a hard cap and
        cannot be filled at any reasonable price.
        """

    def fill_price(self, order_size_dollars: float, mid_price: float,
                   daily_volume_dollars: float, side: int) -> float:
        """Realized fill price.

        Args:
            order_size_dollars: notional being executed (sign ignored, |.| used).
            mid_price: fair mid at decision time.
            daily_volume_dollars: ADV in dollars.
            side: +1 for buy, -1 for sell. Other values raise.

        Returns:
            Fill price, or ``math.nan`` if the model rejects the order.
        """
        if side not in (1, -1):
            raise ValueError(f"side must be +1 or -1, got {side}")
        bps = self.impact_bps(order_size_dollars, daily_volume_dollars)
        if math.isnan(bps):
            return math.nan
        adj = side * bps / _BPS
        return mid_price * (1.0 + adj)


@dataclass(frozen=True)
class FixedBasisPointsSlippage(SlippageModel):
    """Constant bps slippage regardless of size. Parity with ``CostModel.slippage_bps``."""

    basis_points: float = 5.0

    def impact_bps(self, order_size_dollars: float, daily_volume_dollars: float) -> float:
        return float(self.basis_points)


@dataclass(frozen=True)
class VolumeShareSlippage(SlippageModel):
    """Zipline-style volume-share slippage.

    Impact in bps:
        impact_bps = price_impact * 1e4 * (participation ** 2)

    Hard cap: orders with participation > ``volume_limit`` cannot be filled and
    return ``nan``. ``price_impact`` of 0.1 means 1% of ADV costs ~1 bp
    (0.1 * 0.01**2 = 1e-5 = 0.1 bp; full volume_limit=2.5% costs ~0.625 bp).

    Args:
        volume_limit: max order share of ADV before reject (default 0.025).
        price_impact: impact coefficient in absolute units (default 0.1).
        intraday_curve: optional callable ``f(time_of_day) -> multiplier`` used
            to scale ``volume_limit`` per call. ``time_of_day`` is whatever the
            caller passes via ``impact_bps(..., time_of_day=...)`` (typically a
            fraction in [0, 1] over the trading session, or any wall-clock-like
            scalar that the curve interprets). Default ``None`` keeps the
            original flat 2.5% cap. Returning a non-positive multiplier rejects
            the order (NaN). The curve does NOT change the quadratic-impact
            cost, only the participation cap.
    """

    volume_limit: float = 0.025
    price_impact: float = 0.1
    intraday_curve: Optional[Callable[[float], float]] = None

    def impact_bps(
        self,
        order_size_dollars: float,
        daily_volume_dollars: float,
        time_of_day: Optional[float] = None,
    ) -> float:
        part = _participation(order_size_dollars, daily_volume_dollars)
        effective_limit = self.volume_limit
        if self.intraday_curve is not None and time_of_day is not None:
            mult = float(self.intraday_curve(time_of_day))
            if mult <= 0.0:
                return math.nan
            effective_limit = self.volume_limit * mult
        if part > effective_limit:
            return math.nan
        return float(self.price_impact * _BPS * part * part)


@dataclass(frozen=True)
class SquareRootSlippage(SlippageModel):
    """Almgren-Chriss square-root market impact.

        impact_bps = coefficient_bps * sigma_daily * sqrt(participation)

    ``sigma_daily`` is dimensionless daily volatility (e.g. 0.01 = 1%/day).
    ``coefficient_bps`` rescales the canonical sqrt-law to bps.
    """

    coefficient_bps: float = 100.0
    sigma_daily: float = 0.01

    def impact_bps(self, order_size_dollars: float, daily_volume_dollars: float) -> float:
        part = _participation(order_size_dollars, daily_volume_dollars)
        return float(self.coefficient_bps * self.sigma_daily * math.sqrt(part))


@dataclass(frozen=True)
class LinearSlippage(SlippageModel):
    """Linear price impact: ``impact_bps = coefficient_bps * participation``."""

    coefficient_bps: float = 100.0

    def impact_bps(self, order_size_dollars: float, daily_volume_dollars: float) -> float:
        part = _participation(order_size_dollars, daily_volume_dollars)
        return float(self.coefficient_bps * part)


def apply_slippage_to_costs(cost_model, slippage_model: SlippageModel,
                            order_size_dollars: float, mid_price: float,
                            daily_volume: float, side: int) -> float:
    """Extra bps to add on top of ``CostModel.slippage_bps`` for one fill.

    Returns ``math.nan`` if the slippage model rejects the order. The engine
    treats a NaN as "skip / scale-down trade".

    Args:
        cost_model: existing ``CostModel`` (kept for API symmetry; values not
            mutated, callers can sum the result with ``cost_model.slippage_bps``
            if they want a combined number).
        slippage_model: the size-dependent model.
        order_size_dollars: notional traded.
        mid_price: decision-time mid (for parity with ``fill_price``).
        daily_volume: ADV in dollars.
        side: +1 buy, -1 sell.
    """
    if side not in (1, -1):
        raise ValueError(f"side must be +1 or -1, got {side}")
    return slippage_model.impact_bps(order_size_dollars, daily_volume)


__all__ = [
    "SlippageModel",
    "FixedBasisPointsSlippage",
    "VolumeShareSlippage",
    "SquareRootSlippage",
    "LinearSlippage",
    "apply_slippage_to_costs",
]
