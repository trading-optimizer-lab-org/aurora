"""Per-signal contribution attribution (R105).

When a strategy is built from N signals (R77 / R109), attribute
realised PnL contribution per signal so an operator can drop the
dead-weight signals before promotion.

Approach: for each signal s, compute the strategy PnL with s on vs s
off, holding all other signals constant. The contribution of s is the
delta. Sum of contributions <= total PnL (the residual is interaction
between signals; we surface it explicitly so the operator can see how
much PnL the ensemble generates beyond the per-signal sum).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence

import numpy as np


@dataclass(frozen=True)
class SignalContribution:
    """One signal's leave-one-out contribution."""

    signal_name: str
    pnl_with: float
    pnl_without: float
    contribution: float


@dataclass(frozen=True)
class AttributionResult:
    """The contribution table + interaction residual."""

    contributions: List[SignalContribution]
    full_pnl: float
    sum_of_contributions: float

    @property
    def interaction_residual(self) -> float:
        return self.full_pnl - self.sum_of_contributions


def attribute_signals(
    signals: Dict[str, np.ndarray],
    *,
    asset_returns: np.ndarray,
    combine: Callable[[Dict[str, np.ndarray]], np.ndarray],
) -> AttributionResult:
    """Leave-one-out contribution per signal.

    Args:
        signals: dict of signal_name -> per-bar signal series.
        asset_returns: per-bar asset returns.
        combine: callable that maps a {name -> signal} dict to the
            per-bar weight vector. Caller supplies this so the
            attribution stays agnostic to the ensemble logic (vote
            threshold, weighted average, regression blend, ...).

    Returns:
        :class:`AttributionResult`.
    """
    if not signals:
        raise ValueError("signals dict is empty")
    asset_returns = np.asarray(asset_returns, dtype=float)
    full_weights = combine(signals)
    full_pnl = float(np.sum(full_weights * asset_returns))

    contributions: List[SignalContribution] = []
    for name, vec in signals.items():
        without = {k: v for k, v in signals.items() if k != name}
        if not without:
            without_weights = np.zeros_like(asset_returns)
        else:
            without_weights = combine(without)
        without_pnl = float(np.sum(without_weights * asset_returns))
        contributions.append(SignalContribution(
            signal_name=name,
            pnl_with=full_pnl,
            pnl_without=without_pnl,
            contribution=full_pnl - without_pnl,
        ))
    contributions.sort(key=lambda c: c.contribution, reverse=True)
    sum_contrib = sum(c.contribution for c in contributions)
    return AttributionResult(
        contributions=contributions,
        full_pnl=full_pnl,
        sum_of_contributions=sum_contrib,
    )


__all__ = [
    "SignalContribution",
    "AttributionResult",
    "attribute_signals",
]
