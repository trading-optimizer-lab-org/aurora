# ruff: noqa: N806
"""Cost-aware portfolio optimisation wrapper (R171).

Wraps a ``PortfolioOptimizer`` so that:

1. The base optimiser is called on the problem.
2. Turnover (vs ``previous_weights``) is computed.
3. Transaction costs are charged via either:
   - ``aurora.core.costs.CostModel`` (when the caller passes one), or
   - a flat per-side cost-rate fallback (``cost_rate``).
4. If trading costs exceed ``max_cost_to_edge_ratio`` of the gross
   expected edge, the wrapper *refuses* the trade and returns the
   previous weight vector with a warning -- this is a soft refusal,
   not a hard fail.
5. Constraint violations (per ``problem.constraints``) are HARD
   failures: by default they raise ``ConstraintViolation``. Pass
   ``warn_only=True`` to instead surface them as
   ``constraint_violations`` on the returned solution.

The wrapper reuses the core ``CostModel.per_trade_bps`` helper if
available, otherwise falls back to ``cost_rate`` (a flat per-unit
turnover charge). Both paths converge on a single ``costs`` field on the
returned ``PortfolioSolution``.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
from aurora.portfolio.allocation import PortfolioOptimizer
from aurora.portfolio.problem import (
    PortfolioProblem,
    PortfolioSolution,
    _realised_metrics,
)

__all__ = [
    "ConstraintViolation",
    "CostAwareResult",
    "optimise_cost_aware",
]


class ConstraintViolation(RuntimeError):
    """Raised when an optimiser solution violates ``PortfolioConstraints``.

    The list of violations is attached on ``self.violations`` so callers
    can introspect without parsing the message.
    """

    def __init__(self, violations: tuple[str, ...]) -> None:
        super().__init__(
            "portfolio solution violates hard constraints: "
            + "; ".join(violations)
        )
        self.violations = tuple(violations)


# Alias for clarity in callers / tests -- the canonical return type IS
# PortfolioSolution; CostAwareResult exists only as a documentation alias.
CostAwareResult = PortfolioSolution


def optimise_cost_aware(
    optimizer: PortfolioOptimizer,
    problem: PortfolioProblem,
    *,
    cost_rate: float = 0.0,
    cost_model=None,
    max_cost_to_edge_ratio: float = 1.0,
    warn_only: bool = False,
    risk_measure: str = "variance",
) -> PortfolioSolution:
    """Run ``optimizer`` on ``problem`` with turnover + cost penalties.

    Parameters
    ----------
    optimizer
        Any ``PortfolioOptimizer``. Must already be configured (we just
        call ``fit`` + ``predict``).
    problem
        ``PortfolioProblem`` carrying returns, previous weights and
        constraints.
    cost_rate
        Flat per-unit-turnover cost (e.g. 0.0005 = 5 bps per unit
        turnover). Used when ``cost_model`` is None or it does not
        expose ``per_trade_bps``.
    cost_model
        Optional ``aurora.core.costs.CostModel``. If passed, we use
        ``cost_model.per_trade_bps()`` to derive a per-unit-turnover
        rate. Falls back to ``cost_rate`` on any error.
    max_cost_to_edge_ratio
        If the cost of trading exceeds this ratio of the gross expected
        edge ``mean(R @ w_new) - mean(R @ w_prev)``, the wrapper
        *refuses* the trade: the returned solution carries the previous
        weights and a warning. ``1.0`` means "any positive cost is fine
        as long as edge is positive". ``0.0`` would always refuse on
        positive cost. Set to ``float('inf')`` to disable refusal
        entirely (e.g. when measuring pure cost mechanics).
    warn_only
        If False (default), constraint violations raise
        ``ConstraintViolation``. If True, violations are surfaced on
        the solution's ``constraint_violations`` field.
    risk_measure
        Label propagated onto ``PortfolioSolution``. Used for realised
        risk computation.
    """
    if cost_rate < 0:
        raise ValueError("cost_rate must be >= 0")
    if max_cost_to_edge_ratio < 0:
        raise ValueError("max_cost_to_edge_ratio must be >= 0")

    R = problem.returns
    N = problem.n_assets

    prev_w = (
        problem.previous_weights
        if problem.previous_weights is not None
        else np.zeros(N, dtype=float)
    )

    # 1. Run the base optimiser ------------------------------------------ #
    optimizer.fit(R)
    w_new = optimizer.predict()
    if w_new.size != N:
        raise ValueError(
            f"optimizer returned weights of size {w_new.size}, "
            f"expected N={N}"
        )

    warnings: list[str] = []

    # 2. Turnover + cost ------------------------------------------------- #
    turnover = float(np.sum(np.abs(w_new - prev_w)))
    rate = _resolve_cost_rate(cost_rate, cost_model)
    costs = float(turnover * rate)

    # 3. Edge / refusal -------------------------------------------------- #
    if R.shape[0] > 0:
        gross_edge = float(np.mean(R @ w_new) - np.mean(R @ prev_w))
    else:
        gross_edge = 0.0

    refused = False
    if not np.isinf(max_cost_to_edge_ratio):
        if costs > 0 and gross_edge <= 0:
            # Cost > 0 against zero-or-negative edge: never accept.
            refused = True
            warnings.append(
                f"refused: cost={costs:.6g} > 0 but gross_edge="
                f"{gross_edge:.6g}"
            )
        elif costs > max_cost_to_edge_ratio * gross_edge and gross_edge > 0:
            refused = True
            warnings.append(
                f"refused: cost={costs:.6g} exceeds "
                f"{max_cost_to_edge_ratio:.6g} x edge={gross_edge:.6g}"
            )

    if refused:
        w_final = prev_w.copy()
        turnover_final = 0.0
        costs_final = 0.0
    else:
        w_final = w_new
        turnover_final = turnover
        costs_final = costs

    # 4. Constraint validation ------------------------------------------ #
    violations = tuple(
        problem.constraints.validate(
            w_final,
            previous_weights=prev_w,
        )
    )
    if violations and not warn_only:
        raise ConstraintViolation(violations)

    # 5. Realised metrics + assembly ------------------------------------ #
    realised_mean, realised_risk = _realised_metrics(
        w_final, R, risk_measure=risk_measure,
    )
    expected_mean = realised_mean  # we only have empirical data here
    expected_risk = realised_risk

    return PortfolioSolution(
        weights=w_final,
        expected_risk=expected_risk,
        realised_risk=realised_risk,
        expected_return=expected_mean,
        realised_return=realised_mean,
        turnover=turnover_final,
        costs=costs_final,
        warnings=tuple(warnings),
        constraint_violations=violations,
        risk_measure=risk_measure,
        metadata={"refused": refused, "gross_edge": gross_edge},
    )


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _resolve_cost_rate(cost_rate: float, cost_model) -> float:
    """Translate optional ``CostModel`` to a per-unit-turnover rate.

    If ``cost_model`` exposes ``per_trade_bps()`` we convert the bps
    figure into a fractional rate. Otherwise we fall back to the raw
    ``cost_rate`` argument. Any unexpected error in the cost-model path
    falls through to the flat rate.
    """
    if cost_model is None:
        return float(cost_rate)
    fn = getattr(cost_model, "per_trade_bps", None)
    if fn is None:
        return float(cost_rate)
    try:
        bps = float(fn())
    except Exception:  # noqa: BLE001
        return float(cost_rate)
    # ``per_trade_bps`` is a *round-trip* figure for a 100% NAV change.
    # Per unit turnover (where unit turnover = sum |delta_w| = 1.0) the
    # cost is bps / 1e4. The sum-of-absolute-changes already includes
    # buys and sells so we treat the figure as one-sided.
    return bps / 1e4


# Re-export ``replace`` so callers can produce derived solutions easily.
__all__.append("replace")
