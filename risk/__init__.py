"""Advanced Risk modules (QuantForge v3.0 Batch C).

Modules:
- expected_shortfall  : Coherent ES (CVaR) at multiple confidence levels.
- spectral_risk       : Spectral risk with user-defined risk aversion phi(p).
- conditional_dd      : CDaR (Chekhlov-Uryasev).
- risk_parity_factor  : Risk parity by PCA factor exposure.
- herc                : Hierarchical Equal Risk Contribution (Raffinot 2018).
- max_diversification : Choueifaty's MDP (max diversification ratio).
- most_diversified    : Diversification ratio maximizer (alternate parameterization).
- equal_marginal_vol  : EMV allocator (equal marginal volatility contributions).
- risk_budgeting      : Bucketed risk budgeting (sector/region/style).
- stress_var          : Basel III SVaR on historical stress windows.
"""
from __future__ import annotations

from aurora.risk.expected_shortfall import ExpectedShortfall
from aurora.risk.spectral_risk import SpectralRiskMeasure
from aurora.risk.conditional_dd import ConditionalDrawdownAtRisk
from aurora.risk.risk_parity_factor import FactorRiskParity
from aurora.risk.herc import HierarchicalEqualRiskContribution
from aurora.risk.max_diversification import MaxDiversificationPortfolio
from aurora.risk.most_diversified import MostDiversifiedAlloc
from aurora.risk.equal_marginal_vol import EqualMarginalVolPortfolio
from aurora.risk.risk_budgeting import RiskBudgetingAllocator
from aurora.risk.stress_var import StressVaR

__all__ = [
    "ExpectedShortfall",
    "SpectralRiskMeasure",
    "ConditionalDrawdownAtRisk",
    "FactorRiskParity",
    "HierarchicalEqualRiskContribution",
    "MaxDiversificationPortfolio",
    "MostDiversifiedAlloc",
    "EqualMarginalVolPortfolio",
    "RiskBudgetingAllocator",
    "StressVaR",
]
