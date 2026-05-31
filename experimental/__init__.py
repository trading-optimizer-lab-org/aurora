"""Aurora experimental — wild-idea modules.

Each module is self-contained and uses lazy imports for any heavy / optional
third-party dependency (qiskit, torch, sklearn, ...). Importing this package
should not pull any of those in. Public symbols are re-exported below;
failures are swallowed so that a single broken extra cannot poison the
package.
"""
from __future__ import annotations

__all__: list[str] = []

try:
    from aurora.experimental.quantum_placeholder import QuantumPortfolioOptimizer  # noqa: F401
    __all__.append("QuantumPortfolioOptimizer")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.federated_learning import FederatedTrainer  # noqa: F401
    __all__.append("FederatedTrainer")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.zk_performance_proof import ZKPerformanceProof  # noqa: F401
    __all__.append("ZKPerformanceProof")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.strategy_nft import StrategyNFT  # noqa: F401
    __all__.append("StrategyNFT")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.dao_governance import DAOGovernance  # noqa: F401
    __all__.append("DAOGovernance")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.trade_vs_claude import TradeVsClaude  # noqa: F401
    __all__.append("TradeVsClaude")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.strategy_breeding import StrategyBreeder  # noqa: F401
    __all__.append("StrategyBreeder")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.self_modifying_strategy import SelfModifyingStrategy  # noqa: F401
    __all__.append("SelfModifyingStrategy")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.climate_carbon_aware import CarbonAwareAllocator  # noqa: F401
    __all__.append("CarbonAwareAllocator")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.news_entropy_regime import NewsEntropyRegime  # noqa: F401
    __all__.append("NewsEntropyRegime")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.ai_auto_ceo import AIAutoCEO  # noqa: F401
    __all__.append("AIAutoCEO")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.trader_dna import TraderDNAProfiler  # noqa: F401
    __all__.append("TraderDNAProfiler")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.synthetic_alpha import SyntheticAlphaGenerator  # noqa: F401
    __all__.append("SyntheticAlphaGenerator")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.competitor_pnl_reverse import CompetitorPnLReverseEngineer  # noqa: F401
    __all__.append("CompetitorPnLReverseEngineer")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.prediction_markets import PolymarketAdapter  # noqa: F401
    __all__.append("PolymarketAdapter")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.twitter_alpha_bot import TwitterAlphaBot  # noqa: F401
    __all__.append("TwitterAlphaBot")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.earnings_call_live import EarningsCallLiveTrader  # noqa: F401
    __all__.append("EarningsCallLiveTrader")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.smart_contract_escrow import PerformanceFeeEscrow  # noqa: F401
    __all__.append("PerformanceFeeEscrow")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.dex_aggregator import DEXAggregator  # noqa: F401
    __all__.append("DEXAggregator")
except ImportError:  # pragma: no cover
    pass

try:
    from aurora.experimental.strategy_lending import StrategyLendingMarketplace  # noqa: F401
    __all__.append("StrategyLendingMarketplace")
except ImportError:  # pragma: no cover
    pass
