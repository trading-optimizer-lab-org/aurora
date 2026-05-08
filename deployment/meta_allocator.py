"""Meta-allocator: allocator-of-allocators.

Top-level chooses among (HRP, RiskParity, BL, equal_weight) based on an
externally-provided regime label, returning the active sub-allocator weights
on the asset universe.

Design
------
- ``MetaAllocatorConfig`` is a frozen dataclass selecting the regime->method
  mapping plus per-method options (lookback, linkage, BL views, ...).
- ``MetaAllocator.allocate(prices, regime)`` chooses one sub-allocator from
  ``{"hrp", "risk_parity", "bl", "equal_weight"}`` based on the regime label
  and returns a tidy ``pd.DataFrame`` with one row of weights.

The regime input is intentionally a free-form label (string or int). Mapping
regimes to allocators is the responsibility of the caller's regime detector
(e.g. :class:`quantforge.regime.GaussianHMM`); this module only does the
selection. Default mapping:

    regime  -> method
    "bull"  -> "hrp"
    "bear"  -> "risk_parity"
    "neutral" -> "equal_weight"

Any other label falls back to ``default_method``.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from quantforge.deployment.hrp import hrp_allocate
from quantforge.deployment.risk_parity import risk_parity_weights
from quantforge.deployment.black_litterman import (
    BlackLittermanModel,
    market_implied_returns,
)


_VALID_METHODS = ("hrp", "risk_parity", "bl", "equal_weight")


@dataclass
class MetaAllocatorConfig:
    """Configuration for :class:`MetaAllocator`."""
    regime_to_method: dict = field(
        default_factory=lambda: {
            "bull": "hrp",
            "bear": "risk_parity",
            "neutral": "equal_weight",
        }
    )
    default_method: str = "equal_weight"
    lookback: int = 252  # bars of returns used to estimate cov / corr
    bl_risk_aversion: float = 2.5
    bl_tau: float = 0.05
    hrp_linkage: str = "single"
    rp_method: str = "sqp"

    def __post_init__(self) -> None:
        if self.default_method not in _VALID_METHODS:
            raise ValueError(
                f"default_method {self.default_method!r} not in {_VALID_METHODS}"
            )
        for label, method in self.regime_to_method.items():
            if method not in _VALID_METHODS:
                raise ValueError(
                    f"regime_to_method[{label!r}] = {method!r} not in "
                    f"{_VALID_METHODS}"
                )
        if self.lookback < 5:
            raise ValueError(f"lookback must be >= 5, got {self.lookback}")


@dataclass
class MetaAllocatorResult:
    """Output of :meth:`MetaAllocator.allocate`."""
    weights: pd.DataFrame      # 1-row DataFrame indexed by regime label
    method_used: str           # which sub-allocator produced the row
    regime: object             # the regime label that drove the selection


class MetaAllocator:
    """Allocator-of-allocators.

    Args:
        config: :class:`MetaAllocatorConfig`. ``None`` -> defaults.
    """

    def __init__(self, config: Optional[MetaAllocatorConfig] = None):
        self.config = config or MetaAllocatorConfig()

    # --------------------------------------------------------------------- #
    def _select_method(self, regime: object) -> str:
        return self.config.regime_to_method.get(regime, self.config.default_method)

    # --------------------------------------------------------------------- #
    def allocate(
        self,
        prices: pd.DataFrame,
        regime: object = "neutral",
        market_caps: Optional[pd.Series] = None,
        views_p: Optional[pd.DataFrame] = None,
        views_q: Optional[pd.Series] = None,
    ) -> MetaAllocatorResult:
        """Compute weights via the regime-selected sub-allocator.

        Args:
            prices: TxN price DataFrame, columns = asset names.
            regime: regime label (any hashable). Maps to a method via
                ``config.regime_to_method``; unknown labels fall back to
                ``config.default_method``.
            market_caps: required when method='bl' to build the CAPM prior.
            views_p, views_q: optional BL views (only used when method='bl').
        """
        if not isinstance(prices, pd.DataFrame):
            raise TypeError("prices must be a pd.DataFrame")
        if prices.shape[1] < 2:
            raise ValueError(
                f"need >= 2 assets, got {prices.shape[1]}"
            )
        if prices.shape[0] < 2:
            raise ValueError(
                f"need >= 2 price observations, got {prices.shape[0]}"
            )

        method = self._select_method(regime)
        assets = list(prices.columns)
        rets = prices.pct_change().dropna()
        # Truncate to lookback for cov estimation.
        rets_lb = rets.tail(self.config.lookback)
        if len(rets_lb) < 2:
            raise ValueError(
                f"insufficient returns after lookback truncation: {len(rets_lb)}"
            )

        if method == "equal_weight":
            w = pd.Series(1.0 / len(assets), index=assets)
        elif method == "hrp":
            res = hrp_allocate(rets_lb, linkage_method=self.config.hrp_linkage)
            w = res.weights
        elif method == "risk_parity":
            cov = rets_lb.cov()
            res = risk_parity_weights(cov, method=self.config.rp_method)
            w = res.weights
        elif method == "bl":
            cov = rets_lb.cov()
            if market_caps is None:
                # Fallback to equal market caps if user did not provide.
                market_caps = pd.Series(1.0, index=assets)
            mc = market_caps.reindex(assets).fillna(1.0)
            pi = market_implied_returns(
                mc, cov, risk_aversion=self.config.bl_risk_aversion
            )
            bl = BlackLittermanModel(
                pi, cov, views_p=views_p, views_q=views_q,
                tau=self.config.bl_tau,
            )
            w = bl.optimal_weights(risk_aversion=self.config.bl_risk_aversion)
            # BL can produce negative weights in unconstrained MV; clip and renorm.
            w = w.clip(lower=0.0)
            s = w.sum()
            if s > 0:
                w = w / s
            else:
                w = pd.Series(1.0 / len(assets), index=assets)
        else:
            raise ValueError(f"unknown method {method!r}")  # pragma: no cover

        weights_df = pd.DataFrame(
            [w.reindex(assets).values],
            index=[regime],
            columns=assets,
        )
        return MetaAllocatorResult(
            weights=weights_df, method_used=method, regime=regime
        )
