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
analytics
    Rolling-window portfolio analytics (volatility, Sharpe, max drawdown,
    correlation).
attribution
    Per-asset return and risk attribution helpers.
"""
from __future__ import annotations

from aurora.portfolio.allocation import (
    BenchmarkTrackerAllocator,
    CashAllocator,
    EqualWeightAllocator,
    InverseVolAllocator,
    PortfolioOptimizer,
)
from aurora.portfolio.analytics import (
    rolling_correlation,
    rolling_max_drawdown,
    rolling_sharpe,
    rolling_volatility,
)
from aurora.portfolio.attribution import (
    contribution_to_return,
    contribution_to_risk,
    decompose_return,
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
    # analytics
    "rolling_volatility",
    "rolling_sharpe",
    "rolling_max_drawdown",
    "rolling_correlation",
    # attribution
    "contribution_to_return",
    "contribution_to_risk",
    "decompose_return",
]
