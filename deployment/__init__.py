"""Aurora deployment: brokers, paper/live wrappers, sizing, allocators,
HRP, Black-Litterman, covariance shrinkage, risk parity, liquidity, preflight.

Optional brokers (Alpaca, IB, Coinbase, Kraken) and Lumibot wrappers are
imported lazily; missing optional dependencies are tolerated.
"""
from __future__ import annotations

# Brokers (always-available domain types + optional adapters) ---------------
from aurora.deployment.brokers import (
    AlpacaAdapter,
    AuditLog,
    BrokerConfig,
    CoinbaseAdapter,
    create_broker,
    IBAdapter,
    KillSwitch,
    KrakenAdapter,
    Order,
    PaperBroker,
    Position,
)

# Sizing ---------------------------------------------------------------------
from aurora.deployment.sizing import (
    fixed_risk_size,
    kelly_size,
    RiskBudget,
    RiskInfo,
    vol_target_size,
)

# Allocator + portfolio construction ----------------------------------------
from aurora.deployment.allocator import (
    equal_vol,
    equal_weight,
    inverse_dd,
    StrategyAllocator,
)
from aurora.deployment.black_litterman import BlackLittermanModel, BLResult
from aurora.deployment.cov_shrinkage import (
    exponential_cov,
    ledoit_wolf_shrinkage,
    oas_shrinkage,
)
from aurora.deployment.hrp import hrp_allocate, HRPResult
from aurora.deployment.liquidity import (
    compute_liquidity_profile,
    LiquidityAwarePortfolio,
    LiquidityProfile,
)
# ``risk_parity`` is the canonical name kept for backwards compat; the
# allocator-style alias ``risk_parity_allocator`` mirrors the
# equal_weight/equal_vol/inverse_dd allocator names. ``risk_parity_weights``
# remains importable from ``aurora.deployment.risk_parity``.
from aurora.deployment.risk_parity import (
    risk_parity_weights as risk_parity,
    RPResult,
)
from aurora.deployment.risk_parity import (
    risk_parity_weights as risk_parity_allocator,
)
from aurora.deployment.risk_optim import OptimResult

# Preflight ------------------------------------------------------------------
# ``run_preflight`` is the canonical entrypoint. ``preflight_checks`` is kept
# as an alias because earlier versions of API_REFERENCE referred to it.
from aurora.deployment.preflight import (
    PreflightCheck,
    PreflightReport,
    run_preflight,
)
from aurora.deployment.preflight import run_preflight as preflight_checks

# Lumibot-dependent wrappers (paper/live). Each module guards the lumibot
# import internally and exposes a usable class regardless of extras
# availability, so importing here is unconditional.
from aurora.deployment.paper import QFPaperStrategy
from aurora.deployment.live import (
    LiveConfig,
    QFLiveStrategy,
    submit_with_retry,
    TransientOrderError,
)

# Batch E: advanced portfolio modules ---------------------------------------
from aurora.deployment.meta_allocator import (
    MetaAllocator,
    MetaAllocatorConfig,
    MetaAllocatorResult,
)
from aurora.deployment.regime_risk_parity import (
    RegimeRiskParity,
    RegimeRPConfig,
    RegimeRPResult,
)
from aurora.deployment.bl_with_llm_views import (
    BLLLMConfig,
    BLLLMResult,
    BLLLMViews,
)
from aurora.deployment.sector_hrp import (
    SectorHRP,
    SectorHRPConfig,
    SectorHRPResult,
)
from aurora.deployment.vol_target_forecast import (
    VolTargetForecastConfig,
    VolTargetForecastResult,
    VolTargetForecaster,
)
from aurora.deployment.tail_hedging import (
    TailHedgeConfig,
    TailHedgeResult,
    TailHedgingOverlay,
    black_scholes_put,
)
from aurora.deployment.fx_hedger import (
    FXHedgeResult,
    FXHedger,
    FXHedgerConfig,
)
from aurora.deployment.tax_loss_harvester import (
    TLHConfig,
    TLHResult,
    TaxLossHarvester,
)
from aurora.deployment.glide_path import (
    GlidePathConfig,
    GlidePathResult,
    RetirementGlidePath,
)
from aurora.deployment.esg_filter import (
    ESGConfig,
    ESGFilter,
    ESGFilterResult,
)

__all__ = [
    # brokers
    "AlpacaAdapter",
    "AuditLog",
    "BrokerConfig",
    "CoinbaseAdapter",
    "create_broker",
    "IBAdapter",
    "KillSwitch",
    "KrakenAdapter",
    "Order",
    "PaperBroker",
    "Position",
    # sizing
    "fixed_risk_size",
    "kelly_size",
    "RiskBudget",
    "RiskInfo",
    "vol_target_size",
    # portfolio
    "BlackLittermanModel",
    "BLResult",
    "HRPResult",
    "OptimResult",
    "RPResult",
    "StrategyAllocator",
    "equal_vol",
    "equal_weight",
    "exponential_cov",
    "hrp_allocate",
    "inverse_dd",
    "ledoit_wolf_shrinkage",
    "oas_shrinkage",
    "risk_parity",
    "risk_parity_allocator",
    # liquidity
    "LiquidityAwarePortfolio",
    "LiquidityProfile",
    "compute_liquidity_profile",
    # preflight
    "PreflightCheck",
    "PreflightReport",
    "preflight_checks",
    "run_preflight",
    # paper/live (may be None when lumibot is missing)
    "LiveConfig",
    "QFLiveStrategy",
    "QFPaperStrategy",
    "submit_with_retry",
    "TransientOrderError",
    # Batch E: advanced portfolio modules
    "MetaAllocator",
    "MetaAllocatorConfig",
    "MetaAllocatorResult",
    "RegimeRiskParity",
    "RegimeRPConfig",
    "RegimeRPResult",
    "BLLLMViews",
    "BLLLMConfig",
    "BLLLMResult",
    "SectorHRP",
    "SectorHRPConfig",
    "SectorHRPResult",
    "VolTargetForecaster",
    "VolTargetForecastConfig",
    "VolTargetForecastResult",
    "TailHedgingOverlay",
    "TailHedgeConfig",
    "TailHedgeResult",
    "black_scholes_put",
    "FXHedger",
    "FXHedgerConfig",
    "FXHedgeResult",
    "TaxLossHarvester",
    "TLHConfig",
    "TLHResult",
    "RetirementGlidePath",
    "GlidePathConfig",
    "GlidePathResult",
    "ESGFilter",
    "ESGConfig",
    "ESGFilterResult",
]
