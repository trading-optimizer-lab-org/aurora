"""DEX aggregator — Uniswap / SushiSwap / Curve price aggregation.

Aggregates quotes across multiple constant-product mock pools and
returns the best execution route for a given size. Pure stdlib + numpy.
No real chain calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class _MockPool:
    name: str
    reserve_in: float
    reserve_out: float
    fee_bps: int = 30  # 0.3%

    def quote(self, amount_in: float) -> float:
        """Constant-product pricing with fee."""
        if amount_in <= 0:
            return 0.0
        fee = self.fee_bps / 10_000.0
        x_in = amount_in * (1 - fee)
        # x*y = k formula
        return (x_in * self.reserve_out) / (self.reserve_in + x_in)


def _default_pools() -> list[_MockPool]:
    return [
        _MockPool("Uniswap", reserve_in=1_000_000.0, reserve_out=2_000_000.0, fee_bps=30),
        _MockPool("SushiSwap", reserve_in=600_000.0, reserve_out=1_180_000.0, fee_bps=30),
        _MockPool("Curve", reserve_in=2_500_000.0, reserve_out=5_050_000.0, fee_bps=4),
    ]


@dataclass
class DEXAggregator:
    """Aggregate prices across DEX pools and find the best route.

    Parameters
    ----------
    pools : list[_MockPool], optional
        Custom pool configuration. Defaults to a 3-pool mock universe.
    """

    pools: list[_MockPool] = field(default_factory=_default_pools)

    def __post_init__(self) -> None:
        if not self.pools:
            raise ValueError("at least one pool is required")

    def quotes(self, amount_in: float) -> list[dict]:
        """Per-pool quotes."""
        if amount_in <= 0:
            raise ValueError("amount_in must be positive")
        out = []
        for p in self.pools:
            amt_out = p.quote(amount_in)
            out.append(
                {
                    "pool": p.name,
                    "amount_out": amt_out,
                    "price": amt_out / amount_in if amount_in else 0.0,
                }
            )
        return out

    def best_route(self, amount_in: float) -> dict:
        """Return the single pool with the best output."""
        qs = self.quotes(amount_in)
        best = max(qs, key=lambda q: q["amount_out"])
        return {**best, "amount_in": amount_in}
