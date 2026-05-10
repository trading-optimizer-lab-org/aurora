# ruff: noqa: N806
"""Canonical portfolio problem / solution shapes (R171).

These dataclasses are the *stable data interface* between callers, the
existing optimisers in ``aurora.portfolio.optimizers`` and downstream
consumers (cost-aware wrapper, attribution, reports). They carry no
business logic of their own -- the optimiser caller is responsible for
populating ``constraint_violations``.

Design
------
- ``PortfolioProblem`` -- inputs needed to solve an allocation problem:
  return matrix, asset ids, optional previous weights, optional sector
  metadata, risk-free rate.
- ``PortfolioConstraints`` -- re-exported alias of the existing
  ``aurora.portfolio.constraints.PortfolioConstraints`` so callers have a
  single import surface.
- ``PortfolioSolution`` -- everything an optimiser must return for a
  consumer to reason about the result:
    * weights (np.ndarray)
    * expected_risk (model-implied)
    * realised_risk (computed on the same return matrix)
    * expected_return / realised_return
    * turnover (vs ``previous_weights``)
    * costs (currency-neutral fraction of NAV consumed by trading)
    * warnings (tuple of human strings -- e.g. "fallback to equal weight")
    * constraint_violations (tuple of human strings -- non-empty means
      the solution violates the user's hard constraints; the cost-aware
      wrapper raises by default in this case)

All three are frozen dataclasses. ``constraint_violations`` is always a
``tuple[str, ...]`` so it survives equality and hashing.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

# Re-export so callers have a single "portfolio.problem" import surface.
from aurora.portfolio.constraints import PortfolioConstraints

__all__ = [
    "PortfolioConstraints",
    "PortfolioProblem",
    "PortfolioSolution",
]


@dataclass(frozen=True)
class PortfolioProblem:
    """Inputs to an allocator call.

    Parameters
    ----------
    returns
        (T, N) per-period return matrix. Rows = time, cols = asset.
    asset_ids
        Optional asset identifiers, length N. If omitted, ``asset_<i>``
        is used.
    previous_weights
        Optional length-N weight vector held *before* this rebalance.
        Used by turnover-aware optimisers + cost-aware wrappers.
    constraints
        Hard constraints. If omitted, defaults to long-only fully
        invested per ``PortfolioConstraints()``.
    sectors
        Optional length-N sector labels for downstream reporting.
    risk_free_rate
        Per-period risk-free rate (used by Sharpe-like measures).
    metadata
        Free-form mapping to keep ad-hoc context (snapshot hash,
        policy hash, asset class, etc). Stored as a dict but not
        mutated by callers.
    """

    returns: np.ndarray
    asset_ids: tuple[str, ...] = ()
    previous_weights: np.ndarray | None = None
    constraints: PortfolioConstraints = field(
        default_factory=PortfolioConstraints
    )
    sectors: tuple[str, ...] = ()
    risk_free_rate: float = 0.0
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Coerce returns to a 2-D ndarray. We do not copy unless coercion
        # is needed -- the caller might pass a freshly-built array.
        R = np.asarray(self.returns, dtype=float)
        if R.ndim == 1:
            R = R.reshape(-1, 1)
        if R.ndim != 2:
            raise ValueError(
                f"returns must be 1-D or 2-D, got {R.ndim}-D"
            )
        object.__setattr__(self, "returns", R)
        T, N = R.shape

        # Asset IDs default
        if not self.asset_ids:
            object.__setattr__(
                self,
                "asset_ids",
                tuple(f"asset_{i}" for i in range(N)),
            )
        elif len(self.asset_ids) != N:
            raise ValueError(
                f"asset_ids length {len(self.asset_ids)} != N={N}"
            )

        # Previous weights
        if self.previous_weights is not None:
            pw = np.asarray(self.previous_weights, dtype=float).ravel()
            if pw.size != N:
                raise ValueError(
                    f"previous_weights size {pw.size} != N={N}"
                )
            object.__setattr__(self, "previous_weights", pw)

        # Sectors must match N when provided
        if self.sectors and len(self.sectors) != N:
            raise ValueError(
                f"sectors length {len(self.sectors)} != N={N}"
            )
        if not isinstance(self.constraints, PortfolioConstraints):
            raise TypeError(
                "constraints must be a PortfolioConstraints instance"
            )

    # Convenience views ---------------------------------------------------- #
    @property
    def n_assets(self) -> int:
        return int(self.returns.shape[1])

    @property
    def n_periods(self) -> int:
        return int(self.returns.shape[0])


@dataclass(frozen=True)
class PortfolioSolution:
    """Output of an allocator call.

    Parameters
    ----------
    weights
        Length-N float ndarray of post-optimisation weights.
    expected_risk
        Model-implied risk number (e.g. portfolio volatility from
        the optimisation objective).
    realised_risk
        Same risk measure computed on the realised in-sample path
        ``returns @ weights``. Differs from ``expected_risk`` when the
        optimiser used shrinkage / smoothed covariance.
    expected_return
        Model-implied portfolio mean.
    realised_return
        Sample mean of ``returns @ weights``.
    turnover
        L1 distance from ``previous_weights`` (0.0 when no previous
        weights supplied).
    costs
        Cost incurred by reaching ``weights`` from ``previous_weights``,
        as a fraction of NAV. Set by the cost-aware wrapper.
    warnings
        Human-readable strings describing soft fallbacks (e.g.
        "fell back to equal weight: T < 2"). NOT a constraint signal.
    constraint_violations
        Human-readable strings describing HARD failures. The cost-aware
        wrapper raises by default if non-empty.
    risk_measure
        Label of the risk measure used (variance / cvar / etc).
    metadata
        Free-form context (hash strings, scenario name, etc).
    """

    weights: np.ndarray
    expected_risk: float = 0.0
    realised_risk: float = 0.0
    expected_return: float = 0.0
    realised_return: float = 0.0
    turnover: float = 0.0
    costs: float = 0.0
    warnings: tuple[str, ...] = ()
    constraint_violations: tuple[str, ...] = ()
    risk_measure: str = "variance"
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        w = np.asarray(self.weights, dtype=float).ravel()
        object.__setattr__(self, "weights", w)
        # Force tuple types -- a list slips through dataclass typing but
        # then breaks equality / hashing later.
        if not isinstance(self.warnings, tuple):
            object.__setattr__(self, "warnings", tuple(self.warnings))
        if not isinstance(self.constraint_violations, tuple):
            object.__setattr__(
                self,
                "constraint_violations",
                tuple(self.constraint_violations),
            )

    # Convenience helpers -------------------------------------------------- #
    @property
    def is_admissible(self) -> bool:
        """True when the solution has no hard constraint violations."""
        return not self.constraint_violations

    def to_dict(self) -> dict[str, object]:
        """Plain-dict view for reports / JSON / evidence packs."""
        return {
            "weights": self.weights.tolist(),
            "expected_risk": float(self.expected_risk),
            "realised_risk": float(self.realised_risk),
            "expected_return": float(self.expected_return),
            "realised_return": float(self.realised_return),
            "turnover": float(self.turnover),
            "costs": float(self.costs),
            "warnings": list(self.warnings),
            "constraint_violations": list(self.constraint_violations),
            "risk_measure": str(self.risk_measure),
            "metadata": dict(self.metadata),
        }


# --------------------------------------------------------------------------- #
# Helpers used by the cost-aware wrapper                                      #
# --------------------------------------------------------------------------- #
def _realised_metrics(
    weights: Sequence[float],
    returns: np.ndarray,
    risk_measure: str,
) -> tuple[float, float]:
    """Sample mean + risk of the in-sample portfolio path."""
    from aurora.portfolio.risk_measures import (
        cvar,
        semi_variance,
        variance,
    )
    w = np.asarray(weights, dtype=float).ravel()
    R = np.asarray(returns, dtype=float)
    if w.size == 0 or R.size == 0:
        return 0.0, 0.0
    port = R @ w
    mean_r = float(np.mean(port)) if port.size else 0.0
    if risk_measure == "variance":
        risk_v = variance(port)
    elif risk_measure == "semi_variance":
        risk_v = semi_variance(port, threshold=0.0)
    elif risk_measure == "cvar":
        risk_v = cvar(port, alpha=0.05)
    else:
        risk_v = variance(port)
    return mean_r, float(risk_v)
