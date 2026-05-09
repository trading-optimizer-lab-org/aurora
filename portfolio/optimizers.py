# ruff: noqa: N806, N803, B007
"""Internal mean-risk and risk-budgeting optimisers.

- ``MeanRiskOptimizer`` minimises a chosen risk measure (variance,
  semi-variance, CVaR) subject to ``PortfolioConstraints``. Optionally
  targets a minimum expected return.
- ``RiskBudgetingOptimizer`` solves for weights so that each asset
  contributes a target fraction of total risk (Bruder-Roncalli style
  iterative scheme).
- ``SkfolioAdapter`` is a stub that lazy-imports skfolio and skips
  cleanly if it is not installed.

Only scipy is required as an external dep (already present).
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from quantforge.portfolio.allocation import (
    PortfolioOptimizer,
    _check_returns_matrix,
)
from quantforge.portfolio.constraints import PortfolioConstraints
from quantforge.portfolio.risk_measures import cvar, semi_variance, variance
from scipy.optimize import minimize

_RISK_MEASURES = {"variance", "semi_variance", "cvar"}


class MeanRiskOptimizer(PortfolioOptimizer):
    """Mean-risk optimiser.

    Minimises ``risk(w'R) - lambda * mean(w'R)`` subject to:
    - ``sum(w) <= net_exposure_max``
    - ``sum(w) >= cash_floor`` (= 1 - cash_floor when net_exposure_max=1)
    - per-asset bounds (``min_weight``, ``max_weight``)
    - optional target expected return: ``mean(w'R) >= target_return``

    Notes
    -----
    The objective is convex for ``variance`` and ``semi_variance``;
    ``cvar`` is non-smooth but the empirical sample CVaR is convex too,
    so SLSQP converges in practice for small portfolios.
    """

    def __init__(
        self,
        risk_measure: str = "variance",
        target_return: float | None = None,
        lambda_mean: float = 0.0,
        constraints: PortfolioConstraints | None = None,
        alpha: float = 0.05,
        max_iter: int = 200,
    ) -> None:
        super().__init__()
        if risk_measure not in _RISK_MEASURES:
            raise ValueError(
                f"risk_measure must be in {_RISK_MEASURES}, "
                f"got {risk_measure!r}"
            )
        if max_iter < 1:
            raise ValueError("max_iter must be >= 1")
        self.risk_measure = risk_measure
        self.target_return = target_return
        self.lambda_mean = float(lambda_mean)
        self.constraints = constraints or PortfolioConstraints()
        self.alpha = float(alpha)
        self.max_iter = int(max_iter)
        self._summary: dict[str, float] = {}

    # ------------------------------------------------------------------ #
    def fit(self, returns: np.ndarray) -> MeanRiskOptimizer:
        R = _check_returns_matrix(returns)
        T, N = R.shape
        self._n_assets = N
        if N == 0:
            self._weights = np.array([], dtype=float)
            self._fitted = True
            self._summary = {"n_assets": 0.0}
            return self
        if T < 2:
            # Not enough data: fall back to equal weight.
            self._weights = np.full(N, 1.0 / N)
            self._fitted = True
            self._summary = {"n_assets": float(N), "fallback": 1.0}
            return self

        mean_r = R.mean(axis=0)
        c = self.constraints

        bounds = [(c.min_weight, c.max_weight) for _ in range(N)]
        eq_constraints = []
        ineq_constraints = []

        # Net exposure: enforce as equality at net_exposure_max when there
        # is no cash room (cash_floor = 1 - net_exposure_max). Otherwise
        # we use it as an inequality cap with a sum floor.
        net_max = c.net_exposure_max
        net_min = max(0.0, 1.0 - c.cash_floor) if c.cash_floor < 1.0 else 0.0
        net_min = min(net_min, net_max)
        if abs(net_max - net_min) < 1e-12:
            # Equality: sum(w) == net_max (e.g. fully invested)
            eq_constraints.append({
                "type": "eq",
                "fun": lambda w, target=net_max: float(np.sum(w) - target),
            })
        else:
            ineq_constraints.append({
                "type": "ineq",
                "fun": lambda w, cap=net_max: float(cap - np.sum(w)),
            })
            ineq_constraints.append({
                "type": "ineq",
                "fun": lambda w, floor=net_min: float(np.sum(w) - floor),
            })

        # Gross exposure: |w_i| sum cap. Only meaningful when shorts allowed.
        if not c.long_only:
            ineq_constraints.append({
                "type": "ineq",
                "fun": lambda w, cap=c.gross_exposure_max: float(
                    cap - np.sum(np.abs(w))
                ),
            })

        # Target return
        if self.target_return is not None:
            tr = float(self.target_return)
            ineq_constraints.append({
                "type": "ineq",
                "fun": lambda w, mu=mean_r, t=tr: float(np.dot(w, mu) - t),
            })

        # Group caps -- soft inequalities; we ignore them here because
        # ``PortfolioConstraints.group_max`` is keyed by group label and
        # would require ``group_labels`` at fit() time. Caller can enforce
        # via post-validation.

        # Initial guess: equal weight scaled to net_max.
        w0 = np.full(N, net_max / N)
        w0 = np.clip(w0, c.min_weight, c.max_weight)

        result = minimize(
            self._objective,
            w0,
            args=(R, mean_r),
            method="SLSQP",
            bounds=bounds,
            constraints=eq_constraints + ineq_constraints,
            options={"maxiter": self.max_iter, "ftol": 1e-9},
        )

        w = np.asarray(result.x, dtype=float)
        # Floor tiny negatives from numerical noise when long-only.
        if c.long_only:
            w = np.clip(w, 0.0, None)
        self._weights = w
        self._fitted = True
        self._summary = {
            "n_assets": float(N),
            "objective": float(result.fun),
            "iterations": float(result.nit),
            "success": float(bool(result.success)),
            "expected_return": float(np.dot(w, mean_r)),
        }
        return self

    def summary(self) -> dict[str, float]:
        base = super().summary()
        base.update(self._summary)
        return base

    # ------------------------------------------------------------------ #
    def _objective(
        self,
        w: np.ndarray,
        R: np.ndarray,
        mean_r: np.ndarray,
    ) -> float:
        port = R @ w
        if self.risk_measure == "variance":
            risk_val = variance(port)
        elif self.risk_measure == "semi_variance":
            risk_val = semi_variance(port, threshold=0.0)
        else:  # cvar
            risk_val = cvar(port, alpha=self.alpha)
        mean_term = float(np.dot(w, mean_r))
        return float(risk_val - self.lambda_mean * mean_term)


class RiskBudgetingOptimizer(PortfolioOptimizer):
    """Equal- or custom-risk-contribution allocator.

    Solves iteratively for weights w with:
        RC_i(w) = w_i * (Sigma w)_i / sqrt(w' Sigma w) propto budget_i

    Long-only, fully invested. Convergence is monitored by the L2 change
    of the weight vector.
    """

    def __init__(
        self,
        risk_budgets: Sequence[float] | None = None,
        max_iter: int = 1000,
        tol: float = 1e-8,
        constraints: PortfolioConstraints | None = None,
    ) -> None:
        super().__init__()
        if max_iter < 1:
            raise ValueError("max_iter must be >= 1")
        if tol <= 0:
            raise ValueError("tol must be > 0")
        self.risk_budgets = (
            np.asarray(risk_budgets, dtype=float).ravel()
            if risk_budgets is not None
            else None
        )
        if self.risk_budgets is not None:
            if (self.risk_budgets < 0).any():
                raise ValueError("risk_budgets must be >= 0")
            s = self.risk_budgets.sum()
            if s <= 0:
                raise ValueError("risk_budgets must sum to > 0")
            self.risk_budgets = self.risk_budgets / s
        self.max_iter = int(max_iter)
        self.tol = float(tol)
        self.constraints = constraints or PortfolioConstraints()
        self._summary: dict[str, float] = {}

    def fit(self, returns: np.ndarray) -> RiskBudgetingOptimizer:
        R = _check_returns_matrix(returns)
        T, N = R.shape
        self._n_assets = N
        if N == 0:
            self._weights = np.array([], dtype=float)
            self._fitted = True
            self._summary = {"n_assets": 0.0}
            return self
        if self.risk_budgets is not None and self.risk_budgets.size != N:
            raise ValueError(
                f"risk_budgets size {self.risk_budgets.size} != "
                f"returns columns {N}"
            )
        if T < 2:
            self._weights = np.full(N, 1.0 / N)
            self._fitted = True
            self._summary = {"n_assets": float(N), "fallback": 1.0}
            return self

        budgets = (
            self.risk_budgets if self.risk_budgets is not None
            else np.full(N, 1.0 / N)
        )
        Sigma = np.cov(R, rowvar=False, ddof=1)
        std = np.sqrt(np.clip(np.diag(Sigma), 1e-16, None))
        # Initial inverse-vol guess
        w = 1.0 / std
        w = w / w.sum()

        iters = 0
        last_norm = np.inf
        for iters in range(1, self.max_iter + 1):
            sw = Sigma @ w
            port_var = float(w @ sw)
            if port_var <= 1e-16:
                break
            port_vol = float(np.sqrt(port_var))
            rc = w * sw / port_vol  # marginal RC vector, sums to port_vol
            # Update each weight so its share of total risk -> budgets[i].
            # Standard fixed-point: w_i_new = budget_i * port_vol / (Sigma w)_i
            with np.errstate(divide="ignore", invalid="ignore"):
                w_new = budgets * port_vol / sw
            w_new = np.where(np.isfinite(w_new), w_new, w)
            if self.constraints.long_only:
                w_new = np.clip(w_new, 0.0, None)
            s = w_new.sum()
            if s <= 0:
                break
            w_new = w_new / s
            last_norm = float(np.linalg.norm(w_new - w))
            w = w_new
            if last_norm < self.tol:
                break
            del rc

        self._weights = w
        self._fitted = True
        self._summary = {
            "n_assets": float(N),
            "iterations": float(iters),
            "final_step_norm": float(last_norm),
        }
        return self

    def summary(self) -> dict[str, float]:
        base = super().summary()
        base.update(self._summary)
        return base


class SkfolioAdapter(PortfolioOptimizer):
    """Stub adapter for the optional ``skfolio`` package.

    The real ``skfolio`` import is deferred to ``fit`` so importing
    QuantForge does not require the dependency. If ``skfolio`` is not
    installed, ``fit`` raises ``ImportError`` with a clear message --
    tests using ``pytest.importorskip`` skip cleanly.
    """

    def __init__(self, estimator_name: str = "MeanRisk", **kwargs) -> None:
        super().__init__()
        self.estimator_name = estimator_name
        self.kwargs = dict(kwargs)
        self._estimator = None

    def fit(self, returns: np.ndarray) -> SkfolioAdapter:
        try:
            import skfolio  # noqa: F401
        except ImportError as exc:  # pragma: no cover - exercised in tests
            raise ImportError(
                "skfolio is not installed. Install with "
                "'pip install skfolio' to use SkfolioAdapter."
            ) from exc
        # If skfolio IS available, we still don't have a guaranteed shape
        # for its API at this version, so callers must instantiate the
        # estimator themselves and pass it via kwargs['estimator'] for
        # full control. Keep this minimal here.
        R = _check_returns_matrix(returns)
        N = R.shape[1]
        # Fallback: equal weight if no estimator is supplied. This adapter
        # is intentionally a thin stub; users wanting the real skfolio
        # behaviour should subclass and override.
        self._weights = np.full(N, 1.0 / N) if N else np.array([])
        self._n_assets = N
        self._fitted = True
        return self
