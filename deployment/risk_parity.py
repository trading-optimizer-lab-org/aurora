"""Proper risk parity allocator (convex solver).

Implements the Maillard-Roncalli-Teiletche (2010) Equal Risk Contribution
portfolio plus general risk-budgeting, with three solver backends:

- ``sqp``    : scipy.optimize.minimize (SLSQP) on the squared deviation objective
- ``cyclic`` : MRT-2010 cyclic coordinate update (used as the in-house fallback)
- ``cvxpy`` : convex log-barrier reformulation (Spinu / Bai-Scheinberg-Tutuncu),
              used when ``cvxpy`` is importable; raises if requested but missing

Conventions
-----------
- ``cov`` MUST be a symmetric positive (semi-)definite ``pd.DataFrame`` with
  matching row/column index. The asset universe is taken from that index.
- Output weights are non-negative and sum to 1.0.
- Risk contribution per asset is defined as
    RC_i = w_i * (Sigma w)_i / sqrt(w^T Sigma w)
  so that sum_i RC_i = sigma_p (portfolio volatility).

References
----------
Maillard, Roncalli, Teiletche (2010). "The Properties of Equally Weighted Risk
Contribution Portfolios." J. Portfolio Mgmt. 36(4).
Spinu (2013). "An Algorithm for Computing Risk Parity Portfolios."
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# Result                                                                      #
# --------------------------------------------------------------------------- #
@dataclass
class RPResult:
    """Output of risk_parity_weights / equal_risk_contribution / risk_budget."""
    weights: pd.Series                  # solution weights, sum to 1, w >= 0
    risk_contributions: pd.Series       # RC_i = w_i * (Sigma w)_i / sigma_p
    target_contributions: pd.Series     # b_i (normalized so sum to 1)
    portfolio_vol: float                # sqrt(w^T Sigma w)
    n_iterations: int                   # iterations consumed by the solver
    converged: bool                     # whether the chosen tolerance was met
    method: str = "sqp"                 # which backend produced the result


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _validate_cov(cov: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """Validate covariance matrix; return (numpy_cov, asset_names)."""
    if not isinstance(cov, pd.DataFrame):
        raise TypeError("cov must be a pandas DataFrame")
    if cov.shape[0] != cov.shape[1]:
        raise ValueError(f"cov must be square, got {cov.shape}")
    if list(cov.index) != list(cov.columns):
        raise ValueError("cov.index must equal cov.columns")
    arr = cov.to_numpy(dtype=float)
    if not np.all(np.isfinite(arr)):
        raise ValueError("cov contains NaN or Inf")
    # Symmetrize defensively (numerical noise)
    arr = 0.5 * (arr + arr.T)
    diag = np.diag(arr)
    if np.any(diag <= 0):
        raise ValueError("cov has non-positive diagonal entries")
    return arr, list(cov.index)


def _normalize_target(target: Optional[pd.Series],
                      assets: list[str]) -> np.ndarray:
    """Return a target-contribution vector summing to 1, indexed by assets."""
    n = len(assets)
    if target is None:
        return np.full(n, 1.0 / n)
    if not isinstance(target, pd.Series):
        raise TypeError("target_risk_contributions must be a pandas Series")
    missing = [a for a in assets if a not in target.index]
    if missing:
        raise ValueError(f"target missing assets: {missing}")
    b = target.reindex(assets).to_numpy(dtype=float)
    if np.any(b <= 0):
        raise ValueError("target_risk_contributions must be strictly positive")
    return b / b.sum()


def risk_contributions(weights: pd.Series, cov: pd.DataFrame) -> pd.Series:
    """Compute total risk contributions RC_i for given weights.

    RC_i = w_i * (Sigma w)_i / sqrt(w^T Sigma w).
    The returned Series sums to the portfolio volatility.
    """
    if not isinstance(weights, pd.Series):
        raise TypeError("weights must be a pandas Series")
    arr, assets = _validate_cov(cov)
    missing = [a for a in assets if a not in weights.index]
    if missing:
        raise ValueError(f"weights missing assets: {missing}")
    w = weights.reindex(assets).to_numpy(dtype=float)
    sigma_w = arr @ w
    var = float(w @ sigma_w)
    if var <= 0:
        return pd.Series(np.zeros_like(w), index=assets)
    sigma_p = np.sqrt(var)
    rc = w * sigma_w / sigma_p
    return pd.Series(rc, index=assets)


# --------------------------------------------------------------------------- #
# Solvers                                                                     #
# --------------------------------------------------------------------------- #
def _solve_cyclic(cov: np.ndarray, b: np.ndarray, max_iter: int,
                  tol: float) -> tuple[np.ndarray, int, bool]:
    """MRT-2010 cyclic coordinate descent on individual w_i.

    Per Maillard-Roncalli-Teiletche (2010), at each step we update one weight
    at a time so that asset i contributes risk b_i. Solving the per-coordinate
    quadratic for w_i with sigma_w_i = sum_{j!=i} cov_ij * w_j gives:

        cov_ii * w_i^2 + sigma_w_i * w_i - b_i * (w^T Sigma w) = 0

    We iterate the unnormalized vector y until risk contributions match b,
    then normalize to sum 1 at the end. This is provably convergent for PD
    cov and b > 0.
    """
    n = len(b)
    diag = np.diag(cov)
    # Inverse-vol seed (unnormalized; final normalization at end)
    y = 1.0 / np.sqrt(diag)
    y = y / y.sum()

    for it in range(1, max_iter + 1):
        y_old = y.copy()
        # One sweep over all coordinates
        for i in range(n):
            # sigma_w_i excluding own contribution
            sw_i = float(cov[i] @ y) - cov[i, i] * y[i]
            var = float(y @ (cov @ y))
            # Quadratic: a*x^2 + b_lin*x - c = 0, x = y[i]
            a = cov[i, i]
            b_lin = sw_i
            c = b[i] * var
            # Positive root of a x^2 + b_lin x - c = 0
            disc = b_lin * b_lin + 4.0 * a * c
            if disc < 0 or a <= 0:
                continue
            x = (-b_lin + np.sqrt(disc)) / (2.0 * a)
            if x > 0:
                y[i] = x

        # Convergence: change in y between sweeps
        if np.max(np.abs(y - y_old)) < tol * max(np.max(np.abs(y)), 1e-16):
            w = y / y.sum()
            return w, it, True

    s = y.sum()
    if s <= 0:
        return np.full(n, 1.0 / n), max_iter, False
    return y / s, max_iter, False


def _solve_sqp(cov: np.ndarray, b: np.ndarray, max_iter: int,
               tol: float) -> tuple[np.ndarray, int, bool]:
    """SLSQP on sum_i (RC_i / sigma_p - b_i)^2 with sum(w)=1, w>=0.

    Minimizing on the *normalized* contribution removes the dependence on the
    unknown portfolio vol scale and is well-behaved for SLSQP.
    """
    from scipy.optimize import minimize

    n = len(b)
    diag = np.diag(cov)
    w0 = 1.0 / np.sqrt(diag)
    w0 = w0 / w0.sum()

    def objective(w: np.ndarray) -> float:
        sw = cov @ w
        var = float(w @ sw)
        if var <= 0:
            return 1.0  # large penalty
        rc = w * sw / var  # normalized contributions, sum to 1
        return float(np.sum((rc - b) ** 2))

    def grad(w: np.ndarray) -> np.ndarray:
        """Analytic Jacobian of sum_i (rc_i - b_i)^2.

        Let sw = Sigma w, v = w' Sigma w. Then rc_i = w_i * sw_i / v.
        d(rc_i)/dw_k = (delta_ik * sw_i + w_i * Sigma_ik) / v
                      - 2 * rc_i * sw_k / v.
        df/dw_k = 2 * sum_i (rc_i - b_i) * d(rc_i)/dw_k.

        This collapses to:
            df/dw_k = 2/v * [(rc - b) ⊙ sw]_k
                     + 2/v * (Sigma · ((rc - b) ⊙ w))_k
                     - 4/v * sum_i (rc_i - b_i) * rc_i * sw_k.

        Closed-form replaces the previous O(n) finite-difference loop so
        the optimizer scales linearly in time per iteration rather than
        quadratically.
        """
        sw = cov @ w
        v = float(w @ sw)
        if v <= 0:
            # Defensive: matches the objective penalty branch so SLSQP keeps
            # progressing instead of stalling on NaNs.
            return np.zeros_like(w)
        rc = w * sw / v
        diff = rc - b
        # diag-term:  (delta_ik * sw_i)/v  =>  (diff * sw)_k / v at i=k
        term_diag = (diff * sw) / v
        # off-diag:  Sigma_ik * w_i / v  =>  (Sigma' * (diff * w))_k / v
        # Sigma is symmetric here (covariance), so Sigma' = Sigma.
        term_offdiag = (cov @ (diff * w)) / v
        # cross:  -2 * rc_i * sw_k / v at every i, summed over i
        scalar = float(np.sum(diff * rc))
        term_cross = (2.0 * scalar / v) * sw
        return 2.0 * (term_diag + term_offdiag - term_cross)

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    bounds = [(0.0, 1.0)] * n

    res = minimize(
        objective,
        w0,
        jac=grad,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": max_iter, "ftol": tol, "disp": False},
    )
    w = np.maximum(res.x, 0.0)
    s = w.sum()
    if s <= 0:
        return np.full(n, 1.0 / n), int(res.nit), False
    w = w / s

    # Verify convergence on the contribution criterion (looser than ftol)
    sigma_w = cov @ w
    total = float(w @ sigma_w)
    if total <= 0:
        return np.full(n, 1.0 / n), int(res.nit), False
    rc = w * sigma_w / total
    converged = bool(res.success) and np.max(np.abs(rc - b)) < max(tol * 100, 1e-4)
    return w, int(res.nit), converged


def _solve_cvxpy(cov: np.ndarray, b: np.ndarray, max_iter: int,
                 tol: float) -> tuple[np.ndarray, int, bool]:
    """Convex log-barrier formulation (Spinu 2013).

        minimize  0.5 * y^T Sigma y - sum_i b_i log(y_i)
        s.t.      y > 0

    Then w = y / sum(y) is the risk-parity portfolio with budgets b.
    """
    try:
        import cvxpy as cp
    except ImportError as exc:
        raise RuntimeError(
            "method='cvxpy' requested but cvxpy is not installed"
        ) from exc

    n = len(b)
    y = cp.Variable(n, pos=True)
    objective = 0.5 * cp.quad_form(y, cp.psd_wrap(cov)) - b @ cp.log(y)
    prob = cp.Problem(cp.Minimize(objective))
    try:
        prob.solve(max_iters=max_iter, abstol=tol, reltol=tol)
    except (cp.error.SolverError, Exception):
        return np.full(n, 1.0 / n), 0, False

    if y.value is None:
        return np.full(n, 1.0 / n), 0, False
    w = np.maximum(np.asarray(y.value, dtype=float), 0.0)
    s = w.sum()
    if s <= 0:
        return np.full(n, 1.0 / n), 0, False
    w = w / s

    sigma_w = cov @ w
    total = float(w @ sigma_w)
    if total <= 0:
        return np.full(n, 1.0 / n), 0, False
    rc = w * sigma_w / total
    converged = np.max(np.abs(rc - b)) < max(tol * 100, 1e-4)
    return w, max_iter, bool(converged)


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #
_VALID_METHODS = ("sqp", "cyclic", "cvxpy")


def risk_parity_weights(cov: pd.DataFrame,
                        target_risk_contributions: Optional[pd.Series] = None,
                        method: str = "sqp",
                        max_iter: int = 500,
                        tol: float = 1e-8) -> RPResult:
    """Compute risk parity weights via convex optimization.

    Parameters
    ----------
    cov
        Square symmetric covariance ``pd.DataFrame`` (asset universe = index).
    target_risk_contributions
        Per-asset risk-contribution targets; defaults to equal (1/N each).
        Internally normalized to sum to 1.
    method
        ``'sqp'``    : SLSQP convex solver via scipy
        ``'cvxpy'``  : log-barrier convex formulation (requires cvxpy)
        ``'cyclic'`` : Maillard-Roncalli-Teiletche cyclic update
    max_iter, tol
        Convergence parameters passed to the chosen solver.
    """
    if method not in _VALID_METHODS:
        raise ValueError(
            f"unknown method {method!r}, valid: {_VALID_METHODS}"
        )
    if max_iter < 1:
        raise ValueError("max_iter must be >= 1")
    if tol <= 0:
        raise ValueError("tol must be > 0")

    arr, assets = _validate_cov(cov)
    b = _normalize_target(target_risk_contributions, assets)

    if method == "cyclic":
        w, n_it, conv = _solve_cyclic(arr, b, max_iter, tol)
    elif method == "sqp":
        w, n_it, conv = _solve_sqp(arr, b, max_iter, tol)
    else:  # cvxpy
        w, n_it, conv = _solve_cvxpy(arr, b, max_iter, tol)

    weights = pd.Series(w, index=assets, name="weights")
    sigma_w = arr @ w
    var = float(w @ sigma_w)
    portfolio_vol = float(np.sqrt(max(var, 0.0)))
    if portfolio_vol > 0:
        rc = w * sigma_w / portfolio_vol
    else:
        rc = np.zeros_like(w)

    return RPResult(
        weights=weights,
        risk_contributions=pd.Series(rc, index=assets, name="risk_contribution"),
        target_contributions=pd.Series(b, index=assets, name="target"),
        portfolio_vol=portfolio_vol,
        n_iterations=int(n_it),
        converged=bool(conv),
        method=method,
    )


def equal_risk_contribution(cov: pd.DataFrame, **kwargs) -> RPResult:
    """Equal risk contribution (1/N each) — convenience wrapper."""
    return risk_parity_weights(cov, target_risk_contributions=None, **kwargs)


def risk_budget(cov: pd.DataFrame, budget: pd.Series, **kwargs) -> RPResult:
    """Risk budgeting with explicit per-asset budget (will be normalized)."""
    if not isinstance(budget, pd.Series):
        raise TypeError("budget must be a pandas Series")
    return risk_parity_weights(cov, target_risk_contributions=budget, **kwargs)
