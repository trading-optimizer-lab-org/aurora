"""Portfolio optimisation and risk validation (Phase 4 / Candidate F).

Modules
-------
allocation
    PortfolioOptimizer base class plus simple baselines: equal weight,
    inverse volatility, cash and benchmark tracker.
constraints
    PortfolioConstraints frozen dataclass + validation helpers.
risk_measures
    Pure functions: variance, semi-variance, CVaR, max drawdown,
    average drawdown, turnover-aware net return.
optimizers
    Internal mean-risk and risk-budgeting optimisers (scipy-based).
    Optional SkfolioAdapter stub: lazy import, skips cleanly if missing.
stress
    Allocator stress testing (noise, costs, asset removal, correlation).
"""
from __future__ import annotations

from aurora.portfolio.allocation import (
    BenchmarkTrackerAllocator,
    CashAllocator,
    EqualWeightAllocator,
    InverseVolAllocator,
    PortfolioOptimizer,
)
from aurora.portfolio.constraints import PortfolioConstraints
from aurora.portfolio.optimizers import (
    MeanRiskOptimizer,
    RiskBudgetingOptimizer,
    SkfolioAdapter,
)
from aurora.portfolio.risk_measures import (
    avg_drawdown,
    cvar,
    max_drawdown,
    semi_variance,
    turnover_aware_net_return,
    variance,
)
from aurora.portfolio.stress import (
    StressResult,
    StressScenario,
    stress_test,
)

__all__ = [
    # allocation
    "PortfolioOptimizer",
    "EqualWeightAllocator",
    "InverseVolAllocator",
    "CashAllocator",
    "BenchmarkTrackerAllocator",
    # constraints
    "PortfolioConstraints",
    # risk measures
    "variance",
    "semi_variance",
    "cvar",
    "max_drawdown",
    "avg_drawdown",
    "turnover_aware_net_return",
    # optimizers
    "MeanRiskOptimizer",
    "RiskBudgetingOptimizer",
    "SkfolioAdapter",
    # stress
    "StressScenario",
    "StressResult",
    "stress_test",
]
