"""Regime-aware adaptive optimisation (R99).

Strategies that re-tune their parameters when a regime detector
flags a regime shift. The primitive ships:

- :class:`RegimePolicy` -- a per-regime parameter dict.
- :func:`adaptive_signal` -- given a regime tag series, evaluate the
  per-bar signal using the appropriate per-regime template.

Pairs with R71 isolation so adaptive re-tuning never lifts an
OOSGuard. The regime detector is supplied by the caller (HMM, Hurst,
Bayesian -- see :mod:`regime/`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class RegimePolicy:
    """Parameter dict per regime tag.

    Operators wire the same template (e.g. R87 trend_following_ma_cross)
    with different parameters per regime.
    """

    parameters: Dict[str, Dict[str, float]] = field(default_factory=dict)
    fallback_regime: str = "default"

    def params_for(self, regime: str) -> Dict[str, float]:
        if regime in self.parameters:
            return dict(self.parameters[regime])
        return dict(self.parameters.get(self.fallback_regime, {}))


def adaptive_signal(
    *,
    prices: np.ndarray,
    regime_tags: Sequence[str],
    template_fn: Callable[..., np.ndarray],
    policy: RegimePolicy,
) -> np.ndarray:
    """Evaluate ``template_fn`` per regime and stitch the per-bar output.

    Args:
        prices: per-bar price.
        regime_tags: per-bar regime label (e.g. "trending", "rangebound").
        template_fn: e.g. ``trend_following_ma_cross``. Called once per
            unique regime in ``regime_tags`` with the policy's params
            for that regime.
        policy: per-regime parameter dictionary.

    Returns:
        per-bar signal vector.
    """
    prices = np.asarray(prices, dtype=float)
    if len(regime_tags) != len(prices):
        raise ValueError("regime_tags must be the same length as prices")
    out = np.zeros_like(prices, dtype=float)
    cache: Dict[str, np.ndarray] = {}
    unique = sorted(set(regime_tags))
    for regime in unique:
        params = policy.params_for(regime)
        cache[regime] = np.asarray(
            template_fn(prices, **params), dtype=float
        )
    for i, regime in enumerate(regime_tags):
        out[i] = cache[regime][i]
    return out


__all__ = [
    "RegimePolicy",
    "adaptive_signal",
]
