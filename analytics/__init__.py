"""Analytics module — comprehensive performance metrics, attribution, factor
analysis, and round-trip extraction."""
from dataclasses import dataclass

import pandas as pd

from aurora.analytics import attribution, factor_analysis, metrics_full, round_trip
from aurora.analytics.attribution import (
    AttributionResult,
    attribution_by_factor,
    brinson_attribution,
)
from aurora.analytics.factor_analysis import (
    information_coefficient,
    quantile_spread,
)


@dataclass
class BrinsonDecomposition:
    """Concrete dataclass form of a Brinson 1985 attribution.

    Wraps :func:`brinson_attribution` so callers that prefer a typed
    container over a generic :class:`AttributionResult` get explicit
    ``allocation`` / ``selection`` / ``interaction`` / ``total`` series.
    """

    method: str
    contributions: pd.DataFrame
    allocation: pd.Series
    selection: pd.Series
    interaction: pd.Series
    total: pd.Series
    excess_return: float

    @classmethod
    def from_inputs(
        cls,
        weights: pd.DataFrame,
        benchmark_weights: pd.DataFrame,
        returns: pd.DataFrame,
        portfolio_returns: pd.DataFrame | None = None,
    ) -> "BrinsonDecomposition":
        """Build from the same inputs accepted by :func:`brinson_attribution`."""
        result = brinson_attribution(
            weights, benchmark_weights, returns, portfolio_returns
        )
        return cls.from_result(result)

    @classmethod
    def from_result(cls, result: AttributionResult) -> "BrinsonDecomposition":
        """Wrap an existing :class:`AttributionResult` from ``brinson_attribution``."""
        contrib = result.contributions
        return cls(
            method=result.method,
            contributions=contrib,
            allocation=contrib["allocation"].copy(),
            selection=contrib["selection"].copy(),
            interaction=contrib["interaction"].copy(),
            total=contrib["total"].copy(),
            excess_return=float(result.total),
        )

# Submodule re-exports (kept distinct from class / function entries so
# downstream tooling can tell apart "module" from "callable").
_SUBMODULES = [
    "attribution",
    "factor_analysis",
    "metrics_full",
    "round_trip",
]

# Class / function / dataclass entries — the public callable API.
_PUBLIC_API = [
    "attribution_by_factor",
    "BrinsonDecomposition",
    "brinson_attribution",
    "information_coefficient",
    "quantile_spread",
]

__all__ = _SUBMODULES + _PUBLIC_API
