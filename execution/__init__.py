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

from quantforge.execution.twap import TWAPAlgo, TWAPConfig, TWAPSchedule
from quantforge.execution.vwap import VWAPAlgo, VWAPConfig, VWAPSchedule
from quantforge.execution.pov import POVAlgo, POVConfig, POVSchedule
from quantforge.execution.implementation_shortfall import (
    ImplementationShortfallOptimizer,
    ISConfig,
    ISResult,
)
from quantforge.execution.almgren_chriss import (
    AlmgrenChrissExecutor,
    AlmgrenChrissConfig,
    AlmgrenChrissSchedule,
)
from quantforge.execution.market_impact import (
    MarketImpactModel,
    MarketImpactConfig,
    MarketImpactResult,
)
from quantforge.execution.liquidity_seeking import (
    LiquiditySeekingAlgo,
    LiquiditySeekingConfig,
    VenueQuote,
)
from quantforge.execution.iceberg import (
    IcebergOrderManager,
    IcebergConfig,
    IcebergState,
)
from quantforge.execution.pegged_orders import (
    PeggedOrderTypes,
    PeggedConfig,
    PeggedQuote,
)
from quantforge.execution.conditional_orders import (
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
