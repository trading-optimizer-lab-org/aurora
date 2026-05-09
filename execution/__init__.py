"""QuantForge execution algorithms (Batch E — Sophisticated Execution).

Ten algorithmic execution modules:

* :mod:`twap` -- Time-weighted average price scheduler.
* :mod:`vwap` -- Volume-weighted average price using historical volume curve.
* :mod:`pov` -- Percent-of-volume participation.
* :mod:`implementation_shortfall` -- Perold IS framework optimizer.
* :mod:`almgren_chriss` -- Optimal liquidation with linear impact + risk aversion.
* :mod:`market_impact` -- Square-root + linear impact components, calibratable.
* :mod:`liquidity_seeking` -- Probe across venues, place when liquidity appears.
* :mod:`iceberg` -- Auto-replenish display size with hidden remainder.
* :mod:`pegged_orders` -- Mid-peg, primary peg, market peg implementations.
* :mod:`conditional_orders` -- Bracket OCO, trailing stops, stop-limit.
"""
from __future__ import annotations

from aurora.execution.twap import TWAPAlgo, TWAPConfig, TWAPSchedule
from aurora.execution.vwap import VWAPAlgo, VWAPConfig, VWAPSchedule
from aurora.execution.pov import POVAlgo, POVConfig, POVSchedule
from aurora.execution.implementation_shortfall import (
    ImplementationShortfallOptimizer,
    ISConfig,
    ISResult,
)
from aurora.execution.almgren_chriss import (
    AlmgrenChrissExecutor,
    AlmgrenChrissConfig,
    AlmgrenChrissSchedule,
)
from aurora.execution.market_impact import (
    MarketImpactModel,
    MarketImpactConfig,
    MarketImpactResult,
)
from aurora.execution.liquidity_seeking import (
    LiquiditySeekingAlgo,
    LiquiditySeekingConfig,
    VenueQuote,
)
from aurora.execution.iceberg import (
    IcebergOrderManager,
    IcebergConfig,
    IcebergState,
)
from aurora.execution.pegged_orders import (
    PeggedOrderTypes,
    PeggedConfig,
    PeggedQuote,
)
from aurora.execution.conditional_orders import (
    ConditionalOrderManager,
    ConditionalConfig,
    BracketOrder,
    TrailingStop,
    StopLimit,
)

__all__ = [
    "TWAPAlgo",
    "TWAPConfig",
    "TWAPSchedule",
    "VWAPAlgo",
    "VWAPConfig",
    "VWAPSchedule",
    "POVAlgo",
    "POVConfig",
    "POVSchedule",
    "ImplementationShortfallOptimizer",
    "ISConfig",
    "ISResult",
    "AlmgrenChrissExecutor",
    "AlmgrenChrissConfig",
    "AlmgrenChrissSchedule",
    "MarketImpactModel",
    "MarketImpactConfig",
    "MarketImpactResult",
    "LiquiditySeekingAlgo",
    "LiquiditySeekingConfig",
    "VenueQuote",
    "IcebergOrderManager",
    "IcebergConfig",
    "IcebergState",
    "PeggedOrderTypes",
    "PeggedConfig",
    "PeggedQuote",
    "ConditionalOrderManager",
    "ConditionalConfig",
    "BracketOrder",
    "TrailingStop",
    "StopLimit",
]
