"""Realistic cost model for backtest.

Components:
- commission: per-share or per-trade fixed
- spread: half-spread bps applied on every fill
- slippage: extra bps on top, scales with volume
- borrow_rate: short borrow cost (annual %, applied to short notional)

Default ZERO_costs only for sanity checks. Live runs MUST use realistic costs.
"""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CostModel:
    """All costs in basis points (1 bp = 0.0001) unless stated otherwise."""
    commission_bps: float = 0.0     # round-trip commission
    spread_bps: float = 0.0         # half-spread paid each fill
    slippage_bps: float = 0.0       # market impact / slippage
    borrow_rate_annual: float = 0.0 # short borrow rate (e.g. 0.005 = 50bp/yr)
    min_commission_usd: float = 0.0 # floor per trade
    fixed_per_trade_usd: float = 0.0

    def per_trade_bps(self, partial_fill_factor: float = 1.0) -> float:
        """Round-trip cost in bps for one position change of 100% NAV.

        Args:
            partial_fill_factor: fraction of the order assumed to fill instantly
                at the quoted half-spread (1.0 = full instant fill — current
                behavior). Values < 1.0 model fills that work through the queue
                or get partially executed: slippage scales as 2/factor so the
                cost grows continuously and unbounded as the fill rate drops
                (a factor of 0.5 doubles slippage vs full fill, factor 0.25
                quadruples it). The previous 2*(1 + (1 - factor)) formulation
                capped extra slippage at 2x, which is discontinuous and
                understates the cost of very partial fills.

        Trade-off: the constant-bps formulation cannot capture true queue
        priority or order book depth. partial_fill_factor=1.0 keeps default
        behavior; lower values inflate slippage to crudely approximate the
        cost of working larger orders.
        """
        if partial_fill_factor <= 0.0 or partial_fill_factor > 1.0:
            raise ValueError(
                f"partial_fill_factor must be in (0, 1], got {partial_fill_factor}"
            )
        # base round-trip: commission + 2x spread + slippage scaled by 2/factor.
        # factor = 1.0 -> 2x slippage (current default behavior).
        # factor < 1.0 -> slippage grows as 2/factor (continuous, monotonic).
        slippage_mult = 2.0 / max(partial_fill_factor, 1e-3)
        return (
            self.commission_bps
            + 2 * self.spread_bps
            + slippage_mult * self.slippage_bps
        )

    def daily_borrow_cost(
        self,
        short_notional_pct: float,
        settlement_days: int = 0,
        availability_haircut: float = 0.0,
    ) -> float:
        """Daily cost for holding short position. short_notional_pct in [0,1].

        Args:
            short_notional_pct: short notional as a fraction of NAV in [0, 1].
            settlement_days: T+N settlement convention. The borrow leg only
                begins accruing settlement_days after the trade. Setting > 0
                returns 0.0 here (caller is expected to skip the first
                settlement_days bars when applying daily borrow). Default 0
                preserves current behavior.
            availability_haircut: extra multiplier for hard-to-borrow names
                in [0, infty). 0.0 = HTB-neutral (default, current behavior).
                E.g. 0.5 = 50% surcharge, 1.0 = double the borrow cost.

        Returns:
            daily borrow cost as a fraction of NAV.
        """
        if settlement_days < 0:
            raise ValueError(f"settlement_days must be >= 0, got {settlement_days}")
        if availability_haircut < 0.0:
            raise ValueError(
                f"availability_haircut must be >= 0, got {availability_haircut}"
            )
        if settlement_days > 0:
            # caller should not charge borrow until trade+settlement_days
            return 0.0
        rate = self.borrow_rate_annual * (1.0 + availability_haircut)
        return short_notional_pct * rate / 252.0


# Standard cost models
ZERO_costs = CostModel()

# Approximate realistic IBKR retail (SPY-like liquid stocks)
IBKR_costs = CostModel(
    commission_bps=0.5,        # ~0.005% per side
    spread_bps=1.0,            # 1 bp half-spread liquid
    slippage_bps=2.0,          # 2 bp slippage retail size
    borrow_rate_annual=0.01,   # 1% annual short borrow (HTB rate)
    min_commission_usd=1.0,
)

# Conservative for less liquid assets
CONSERVATIVE_costs = CostModel(
    commission_bps=2.0,
    spread_bps=5.0,
    slippage_bps=10.0,
    borrow_rate_annual=0.03,
    min_commission_usd=2.0,
)


def apply_costs(weights, returns, costs: CostModel,
                partial_fill_factor: float = 1.0):
    """Apply cost model to weight series + asset returns. Returns net returns array.

    Args:
        weights: np.array shape (T,) target weight each bar
        returns: np.array shape (T,) raw asset returns each bar
        costs: CostModel
        partial_fill_factor: forwarded to ``costs.per_trade_bps``. Default
            1.0 (full instant fill). Lower values inflate the slippage
            component for partial-fill regimes.

    Returns:
        np.array shape (T,) net strategy returns (cost-deducted)
    """
    weights = np.asarray(weights, dtype=float)
    returns = np.asarray(returns, dtype=float)
    T = len(weights)
    net = np.zeros(T)
    if T < 2:
        return net

    # gross strategy return: weight[t-1] * return[t]
    net[1:] = weights[:-1] * returns[1:]

    # turnover-based costs: |delta_weight| * per_trade_bps
    delta_w = np.abs(np.diff(weights, prepend=0.0))
    cost_per_bar = delta_w * (costs.per_trade_bps(partial_fill_factor) / 1e4)
    net = net - cost_per_bar

    # daily borrow on short side: charge applies to the position CARRIED INTO
    # each bar (weights[t-1]) so it lines up with the gross return formula
    # net[1:] = weights[:-1] * returns[1:]. Bar 0 has no carried position.
    short_carried = np.zeros(T)
    short_carried[1:] = np.abs(np.minimum(weights[:-1], 0.0))
    net = net - short_carried * (costs.borrow_rate_annual / 252.0)

    return net
