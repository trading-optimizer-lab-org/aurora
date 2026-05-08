"""Tax-loss harvesting awareness (R114).

Surface tax implications during rebalance: when the allocator wants to
close a long-held lot, return the realised-gain estimate and a
tax_drag_bps so the operator can decide whether the rebalance is
worth the tax bill.

Off-by-default and U.S.-tax-specific (long-term vs short-term holds).
Operators outside the U.S. supply their own tax-bracket lookup.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import List, Optional


LONG_TERM_THRESHOLD = timedelta(days=365)


class HoldingPeriod(str, Enum):
    LONG_TERM = "long_term"
    SHORT_TERM = "short_term"


@dataclass(frozen=True)
class Lot:
    """One purchase lot for tax-lot accounting."""

    quantity: float
    cost_basis_per_share: float
    acquired_on: date


@dataclass(frozen=True)
class CloseLotEstimate:
    """Estimated tax impact of closing a lot at a given price."""

    quantity: float
    realised_pnl: float
    holding_period: HoldingPeriod
    estimated_tax: float
    tax_drag_bps: float


def estimate_close_impact(
    lot: Lot,
    *,
    sell_price_per_share: float,
    sell_date: date,
    long_term_rate: float = 0.20,
    short_term_rate: float = 0.37,
    portfolio_nav: float = 1.0,
) -> CloseLotEstimate:
    """Estimate the realised PnL + tax impact of closing ``lot``.

    Args:
        lot: tax lot being closed.
        sell_price_per_share: price the allocator wants to sell at.
        sell_date: date of the close.
        long_term_rate: U.S. long-term cap-gains rate (default 20%).
        short_term_rate: U.S. short-term rate (default 37%).
        portfolio_nav: nav anchor for the bps calculation.

    Returns:
        :class:`CloseLotEstimate` with realised pnl, holding period,
        estimated tax, and ``tax_drag_bps`` relative to NAV.
    """
    age = sell_date - lot.acquired_on
    period = (
        HoldingPeriod.LONG_TERM if age >= LONG_TERM_THRESHOLD
        else HoldingPeriod.SHORT_TERM
    )
    realised = (sell_price_per_share - lot.cost_basis_per_share) * lot.quantity
    if realised <= 0:
        tax = 0.0
    else:
        rate = long_term_rate if period is HoldingPeriod.LONG_TERM else short_term_rate
        tax = realised * rate
    bps = (tax / portfolio_nav) * 10_000.0 if portfolio_nav > 0 else 0.0
    return CloseLotEstimate(
        quantity=lot.quantity,
        realised_pnl=realised,
        holding_period=period,
        estimated_tax=tax,
        tax_drag_bps=bps,
    )


def estimate_basket_close(
    lots: List[Lot],
    sell_prices: List[float],
    sell_date: date,
    **kwargs,
) -> List[CloseLotEstimate]:
    if len(lots) != len(sell_prices):
        raise ValueError("lots and sell_prices must align")
    return [
        estimate_close_impact(lot, sell_price_per_share=p,
                              sell_date=sell_date, **kwargs)
        for lot, p in zip(lots, sell_prices)
    ]


__all__ = [
    "HoldingPeriod",
    "Lot",
    "CloseLotEstimate",
    "estimate_close_impact",
    "estimate_basket_close",
    "LONG_TERM_THRESHOLD",
]
