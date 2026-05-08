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

from quantforge.risk.expected_shortfall import ExpectedShortfall
from quantforge.risk.spectral_risk import SpectralRiskMeasure
from quantforge.risk.conditional_dd import ConditionalDrawdownAtRisk
from quantforge.risk.risk_parity_factor import FactorRiskParity
from quantforge.risk.herc import HierarchicalEqualRiskContribution
from quantforge.risk.max_diversification import MaxDiversificationPortfolio
from quantforge.risk.most_diversified import MostDiversifiedAlloc
from quantforge.risk.equal_marginal_vol import EqualMarginalVolPortfolio
from quantforge.risk.risk_budgeting import RiskBudgetingAllocator
from quantforge.risk.stress_var import StressVaR

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
