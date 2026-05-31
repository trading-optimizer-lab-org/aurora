"""CVaR / CDaR portfolio optimization (Task H.2 of Aurora v1.1).

Implements:
- min_cvar:               minimize Conditional Value-at-Risk (Expected Shortfall)
- min_cdar:               minimize Conditional Drawdown-at-Risk
- max_sharpe_cvar:        maximize (mean - rf) / CVaR (Sharpe-CVaR ratio)
- efficient_cvar_frontier: trace the efficient frontier under CVaR risk

References:
- Rockafellar & Uryasev (2000), "Optimization of Conditional Value-at-Risk".
- Chekhlov, Uryasev & Zabarankin (2003-2005), "Drawdown measure in portfolio
  optimization".
- PyPortfolioOpt's efficient_cvar.py / efficient_cdar.py (LP formulation).

Optimization backend
--------------------
Primary backend: cvxpy (LP via highs/ECOS/SCS).
Fallback backend: scipy.optimize.linprog with manually-constructed sparse
constraint matrices, used automatically when cvxpy is not importable.

CVaR LP (Rockafellar-Uryasev)
-----------------------------
Decision vars: w in R^N (weights), zeta in R (VaR aux), u in R^T (slacks).

    minimize     zeta + (1 / (alpha * T)) * sum_t u_t
    subject to   u_t >= -returns_t @ w - zeta            (t = 1..T)
                 u_t >= 0
                 sum(w) = 1
                 w_lo <= w <= w_hi
                 [optional] mu @ w >= target_return

CDaR LP (Chekhlov-Uryasev-Zabarankin)
-------------------------------------
Decision vars: w in R^N, xi in R^T (cumulative wealth proxy), zeta in R, u in R^T.

We work with the cumulative log-equivalent returns sequence x_t = sum_{s<=t} (R_s @ w);
running max y_t = max_{s<=t} x_s; drawdown d_t = y_t - x_t. The LP form replaces
y_t with a free variable xi_t constrained by xi_t >= xi_{t-1} and xi_t >= x_t,
and then the CVaR-of-drawdowns formulation gives:

    minimize     zeta + (1/(alpha*T)) * sum_t u_t
    subject to   u_t >= xi_t - x_t - zeta
                 u_t >= 0
                 xi_t >= xi_{t-1}                        (xi_0 = 0)
                 xi_t >= x_t
                 x_t = sum_{s<=t} (R_s @ w)
                 sum(w) = 1, weight bounds, optional return target

This is still an LP because x_t is linear in w.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.sparse import csr_matrix, eye as speye, vstack, hstack

try:
    import cvxpy as cp
    _HAVE_CVXPY = True
except Exception:
    _HAVE_CVXPY = False


# --------------------------------------------------------------------------- #
# Result                                                                      #
# --------------------------------------------------------------------------- #
@dataclass
class OptimResult:
    """Output of an optimizer call."""
    weights: pd.Series
    objective_value: float           # CVaR / CDaR / -ratio at optimum
    constraints_active: list = field(default_factory=list)
    n_assets: int = 0
    method: str = ""

    def to_dict(self) -> dict:
        return {
            "weights": self.weights.to_dict(),
            "objective_value": float(self.objective_value),
            "constraints_active": list(self.constraints_active),
            "n_assets": int(self.n_assets),
            "method": self.method,
        }


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _validate_returns(returns: pd.DataFrame) -> tuple[np.ndarray, list, int, int]:
    if not isinstance(returns, pd.DataFrame):
        raise TypeError("returns must be a pandas DataFrame")
    if returns.empty:
        raise ValueError("returns is empty")
    if returns.isna().any().any():
        # match PyPortfolioOpt: NaN-fill with 0 is unsafe; require user to clean
        raise ValueError("returns contains NaN; clean before optimizing")
    R = returns.values.astype(float)
    if not np.all(np.isfinite(R)):
        raise ValueError("returns contains non-finite values")
    T, N = R.shape
    if T < 2:
        raise ValueError(f"need at least 2 rows of returns, got {T}")
    if N < 1:
        raise ValueError(f"need at least 1 asset, got {N}")
    return R, list(returns.columns), T, N


def _validate_alpha(alpha: float) -> float:
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    return float(alpha)


def _validate_bounds(weight_bounds: tuple, n: int,
                     gross_cap: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Validate (lo, hi) weight bounds against the budget constraint.

    Performs three feasibility checks:
        1) per-asset: lo_i <= hi_i
        2) asset-level vs budget: n * lo > gross_cap (cannot satisfy lower
           bounds within budget) and n * hi < gross_cap (cannot reach budget
           even at upper bounds)
        3) sum: sum(lo) <= gross_cap <= sum(hi)
    """
    lo, hi = weight_bounds
    lo_arr = np.full(n, float(lo))
    hi_arr = np.full(n, float(hi))
    if np.any(lo_arr > hi_arr):
        raise ValueError(f"weight_bounds: lo > hi ({lo} > {hi})")
    # Asset-level conflict: lower-bound forces total weight above gross_cap.
    min_w = float(lo_arr.min())
    max_w = float(hi_arr.max())
    if min_w > 0 and gross_cap < n * min_w - 1e-9:
        raise ValueError(
            f"weight_bounds infeasible: min_w={min_w:.6f} on N={n} assets "
            f"requires N*min_w={n * min_w:.4f} > gross_cap={gross_cap:.4f}"
        )
    if max_w > 0 and gross_cap > n * max_w + 1e-9:
        raise ValueError(
            f"weight_bounds infeasible: max_w={max_w:.6f} on N={n} assets "
            f"caps total at N*max_w={n * max_w:.4f} < gross_cap={gross_cap:.4f}"
        )
    if hi_arr.sum() < gross_cap - 1e-9 or lo_arr.sum() > gross_cap + 1e-9:
        raise ValueError(
            f"weight bounds infeasible for sum(w) = {gross_cap}: "
            f"lo_sum={lo_arr.sum():.4f}, hi_sum={hi_arr.sum():.4f}"
        )
    return lo_arr, hi_arr


def _active_constraints(w: np.ndarray, lo: np.ndarray, hi: np.ndarray,
                        target_return: Optional[float], mu: np.ndarray,
                        tol: float = 1e-6) -> list:
    out = ["sum_to_one"]
    if np.any(np.abs(w - lo) < tol):
        out.append("lower_bound")
    if np.any(np.abs(w - hi) < tol):
        out.append("upper_bound")
    if target_return is not None and abs(float(mu @ w) - target_return) < 1e-4:
        out.append("target_return")
    return out


# --------------------------------------------------------------------------- #
# CVaR — cvxpy backend                                                        #
# --------------------------------------------------------------------------- #
def _cvar_cvxpy(R: np.ndarray, alpha: float,
                target_return: Optional[float],
                lo: np.ndarray, hi: np.ndarray) -> tuple[np.ndarray, float]:
    T, N = R.shape
    w = cp.Variable(N)
    zeta = cp.Variable()
    u = cp.Variable(T, nonneg=True)
    constraints = [
        u >= -R @ w - zeta,
        cp.sum(w) == 1,
        w >= lo,
        w <= hi,
    ]
    if target_return is not None:
        mu = R.mean(axis=0)
        constraints.append(mu @ w >= target_return)
    obj = cp.Minimize(zeta + cp.sum(u) / (alpha * T))
    prob = cp.Problem(obj, constraints)
    prob.solve(solver=cp.HIGHS) if "HIGHS" in cp.installed_solvers() else prob.solve()
    if w.value is None or prob.status not in ("optimal", "optimal_inaccurate"):
        raise RuntimeError(f"CVaR optimization failed: status={prob.status}")
    return np.asarray(w.value, dtype=float), float(prob.value)


# --------------------------------------------------------------------------- #
# CVaR — scipy.linprog fallback                                               #
# --------------------------------------------------------------------------- #
def _cvar_scipy(R: np.ndarray, alpha: float,
                target_return: Optional[float],
                lo: np.ndarray, hi: np.ndarray) -> tuple[np.ndarray, float]:
    """LP: variables x = [w (N), zeta (1), u (T)].

    Objective: 0_w . w + 1 . zeta + (1/(alpha*T)) . sum(u)

    A_ub @ x <= b_ub:
        u_t >= -R_t w - zeta   <=>   -R_t w - zeta - u_t <= 0
        u_t >= 0                <=>   -u_t <= 0
        [optional] mu w >= R*  <=>  -mu w <= -R*

    A_eq @ x = b_eq:
        sum(w) = 1

    Bounds:
        lo_i <= w_i <= hi_i;  zeta free (-inf, inf);  u_t free.
        We rely on the explicit u_t >= 0 inequality rather than bounds (cleaner).
    """
    T, N = R.shape
    nvar = N + 1 + T  # [w, zeta, u]
    c = np.zeros(nvar, dtype=float)
    c[N] = 1.0
    c[N + 1:] = 1.0 / (alpha * T)

    rows = []  # csr blocks for A_ub
    rhs = []   # b_ub

    # Block 1: -R_t w - zeta - u_t <= 0   (T rows)
    A1_w = csr_matrix(-R)                              # (T, N)
    A1_z = csr_matrix(-np.ones((T, 1)))                # (T, 1)
    A1_u = -speye(T, format="csr")                     # (T, T)
    A1 = hstack([A1_w, A1_z, A1_u], format="csr")
    rows.append(A1)
    rhs.append(np.zeros(T))

    # Block 2: -u_t <= 0   (T rows; ensures u >= 0)
    A2_w = csr_matrix((T, N))
    A2_z = csr_matrix((T, 1))
    A2_u = -speye(T, format="csr")
    A2 = hstack([A2_w, A2_z, A2_u], format="csr")
    rows.append(A2)
    rhs.append(np.zeros(T))

    # Block 3: optional return target  -mu w <= -R*
    if target_return is not None:
        mu = R.mean(axis=0)
        A3_w = csr_matrix(-mu.reshape(1, -1))
        A3_z = csr_matrix((1, 1))
        A3_u = csr_matrix((1, T))
        A3 = hstack([A3_w, A3_z, A3_u], format="csr")
        rows.append(A3)
        rhs.append(np.array([-float(target_return)]))

    A_ub = vstack(rows, format="csr")
    b_ub = np.concatenate(rhs)

    # Equality: sum(w) = 1
    A_eq_w = csr_matrix(np.ones((1, N)))
    A_eq_z = csr_matrix((1, 1))
    A_eq_u = csr_matrix((1, T))
    A_eq = hstack([A_eq_w, A_eq_z, A_eq_u], format="csr")
    b_eq = np.array([1.0])

    bounds = (
        [(float(lo[i]), float(hi[i])) for i in range(N)]
        + [(None, None)]                # zeta free
        + [(0.0, None)] * T             # u_t >= 0 also via bounds (redundant safety)
    )

    res = linprog(
        c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
        bounds=bounds, method="highs",
    )
    if not res.success:
        raise RuntimeError(f"CVaR linprog failed: {res.message}")
    x = res.x
    w_opt = x[:N]
    return w_opt, float(res.fun)


# --------------------------------------------------------------------------- #
# Public CVaR API                                                             #
# --------------------------------------------------------------------------- #
def min_cvar(returns: pd.DataFrame, alpha: float = 0.05,
             target_return: float | None = None,
             weight_bounds: tuple = (0.0, 1.0)) -> OptimResult:
    """Minimize Conditional Value-at-Risk (Expected Shortfall) at level alpha.

    Args:
        returns: DataFrame of asset returns (T x N).
        alpha: tail probability (5% default = expected loss in worst 5%).
        target_return: optional minimum portfolio return (mean) constraint.
        weight_bounds: (lo, hi) per asset. Default (0, 1) = long-only fully invested.

    Returns:
        OptimResult with CVaR-minimizing weights and CVaR objective value.
    """
    R, cols, T, N = _validate_returns(returns)
    a = _validate_alpha(alpha)
    lo, hi = _validate_bounds(weight_bounds, N)

    if _HAVE_CVXPY:
        try:
            w, val = _cvar_cvxpy(R, a, target_return, lo, hi)
            backend = "cvxpy"
        except Exception:
            w, val = _cvar_scipy(R, a, target_return, lo, hi)
            backend = "scipy_linprog_fallback"
    else:
        w, val = _cvar_scipy(R, a, target_return, lo, hi)
        backend = "scipy_linprog"

    mu = R.mean(axis=0)
    weights = pd.Series(w, index=cols, name="weights")
    return OptimResult(
        weights=weights,
        objective_value=float(val),
        constraints_active=_active_constraints(w, lo, hi, target_return, mu),
        n_assets=N,
        method=f"min_cvar:{backend}",
    )


# --------------------------------------------------------------------------- #
# CDaR — cvxpy backend                                                        #
# --------------------------------------------------------------------------- #
def _cdar_cvxpy(R: np.ndarray, alpha: float,
                target_return: Optional[float],
                lo: np.ndarray, hi: np.ndarray) -> tuple[np.ndarray, float]:
    T, N = R.shape
    w = cp.Variable(N)
    xi = cp.Variable(T)            # running max proxy
    zeta = cp.Variable()
    u = cp.Variable(T, nonneg=True)

    # Cumulative returns x_t = sum_{s<=t} R_s @ w. Use cumsum to avoid
    # materialising the T*T lower-triangular ones matrix (memory blow-up
    # at large T).
    CR = np.cumsum(R, axis=0)      # (T, N)
    x = CR @ w                     # shape (T,)

    constraints = [
        cp.sum(w) == 1,
        w >= lo,
        w <= hi,
        u >= xi - x - zeta,
        xi >= x,
    ]
    # xi monotone non-decreasing (xi_t >= xi_{t-1})
    if T >= 2:
        constraints.append(xi[1:] >= xi[:-1])
    constraints.append(xi[0] >= 0)  # xi starts >= 0

    if target_return is not None:
        mu = R.mean(axis=0)
        constraints.append(mu @ w >= target_return)

    obj = cp.Minimize(zeta + cp.sum(u) / (alpha * T))
    prob = cp.Problem(obj, constraints)
    prob.solve(solver=cp.HIGHS) if "HIGHS" in cp.installed_solvers() else prob.solve()
    if w.value is None or prob.status not in ("optimal", "optimal_inaccurate"):
        raise RuntimeError(f"CDaR optimization failed: status={prob.status}")
    return np.asarray(w.value, dtype=float), float(prob.value)


# --------------------------------------------------------------------------- #
# CDaR — scipy.linprog fallback                                               #
# --------------------------------------------------------------------------- #
def _cdar_scipy(R: np.ndarray, alpha: float,
                target_return: Optional[float],
                lo: np.ndarray, hi: np.ndarray) -> tuple[np.ndarray, float]:
    """LP: variables x = [w (N), xi (T), zeta (1), u (T)].

    Cumulative returns are not stored as variables; instead we substitute
    x_t = (C R)_t @ w where C is the lower-triangular cumsum matrix.

    A_ub:
        u_t >= xi_t - x_t - zeta   <=>  -CR_t w - xi_t   wait: xi_t - x_t - zeta - u_t <= 0
                                        => xi_t - (C R w)_t - zeta - u_t <= 0
                                        => -(C R)_t w + xi_t - zeta - u_t <= 0
        -u_t <= 0
        -xi_t + (C R)_t w <= 0      (xi_t >= x_t)
        xi_{t-1} - xi_t <= 0        (monotone)
        -xi_0 <= 0                  (xi_0 >= 0)
        [optional]  -mu w <= -R*

    A_eq: sum(w) = 1
    Bounds: lo<=w<=hi, xi free, zeta free, u >= 0.
    """
    T, N = R.shape
    # CR[t, j] = sum_{s<=t} R[s, j] -- cumsum avoids the T*T tril dense matrix
    # (which is ~18MB for T=1500 and grows quadratically).
    CR = np.cumsum(R, axis=0)           # (T, N)
    nvar = N + T + 1 + T                # [w, xi, zeta, u]

    c = np.zeros(nvar, dtype=float)
    c[N + T] = 1.0                       # zeta
    c[N + T + 1:] = 1.0 / (alpha * T)    # u

    def _slice():
        # column ranges
        w_cols = slice(0, N)
        xi_cols = slice(N, N + T)
        z_col = N + T
        u_cols = slice(N + T + 1, nvar)
        return w_cols, xi_cols, z_col, u_cols

    rows = []
    rhs = []

    # Block 1: u >= xi - x - zeta -> -CR w + xi - zeta - u <= 0
    A1_w = csr_matrix(-CR)
    A1_xi = speye(T, format="csr")
    A1_z = csr_matrix(-np.ones((T, 1)))
    A1_u = -speye(T, format="csr")
    A1 = hstack([A1_w, A1_xi, A1_z, A1_u], format="csr")
    rows.append(A1); rhs.append(np.zeros(T))

    # Block 2: -u <= 0
    A2_w = csr_matrix((T, N))
    A2_xi = csr_matrix((T, T))
    A2_z = csr_matrix((T, 1))
    A2_u = -speye(T, format="csr")
    A2 = hstack([A2_w, A2_xi, A2_z, A2_u], format="csr")
    rows.append(A2); rhs.append(np.zeros(T))

    # Block 3: xi >= x -> -xi + CR w <= 0
    A3_w = csr_matrix(CR)
    A3_xi = -speye(T, format="csr")
    A3_z = csr_matrix((T, 1))
    A3_u = csr_matrix((T, T))
    A3 = hstack([A3_w, A3_xi, A3_z, A3_u], format="csr")
    rows.append(A3); rhs.append(np.zeros(T))

    # Block 4: xi monotone -> xi_{t-1} - xi_t <= 0  for t=1..T-1
    if T >= 2:
        rows_idx = []
        cols_idx = []
        data = []
        for t in range(1, T):
            rows_idx += [t - 1, t - 1]
            cols_idx += [t - 1, t]
            data += [1.0, -1.0]
        A4_xi = csr_matrix((data, (rows_idx, cols_idx)), shape=(T - 1, T))
        A4_w = csr_matrix((T - 1, N))
        A4_z = csr_matrix((T - 1, 1))
        A4_u = csr_matrix((T - 1, T))
        A4 = hstack([A4_w, A4_xi, A4_z, A4_u], format="csr")
        rows.append(A4); rhs.append(np.zeros(T - 1))

    # Block 5: -xi_0 <= 0
    A5_w = csr_matrix((1, N))
    A5_xi = csr_matrix(([-1.0], ([0], [0])), shape=(1, T))
    A5_z = csr_matrix((1, 1))
    A5_u = csr_matrix((1, T))
    A5 = hstack([A5_w, A5_xi, A5_z, A5_u], format="csr")
    rows.append(A5); rhs.append(np.zeros(1))

    # Block 6 (optional): -mu w <= -R*
    if target_return is not None:
        mu = R.mean(axis=0)
        A6_w = csr_matrix(-mu.reshape(1, -1))
        A6_xi = csr_matrix((1, T))
        A6_z = csr_matrix((1, 1))
        A6_u = csr_matrix((1, T))
        A6 = hstack([A6_w, A6_xi, A6_z, A6_u], format="csr")
        rows.append(A6); rhs.append(np.array([-float(target_return)]))

    A_ub = vstack(rows, format="csr")
    b_ub = np.concatenate(rhs)

    A_eq_w = csr_matrix(np.ones((1, N)))
    A_eq_xi = csr_matrix((1, T))
    A_eq_z = csr_matrix((1, 1))
    A_eq_u = csr_matrix((1, T))
    A_eq = hstack([A_eq_w, A_eq_xi, A_eq_z, A_eq_u], format="csr")
    b_eq = np.array([1.0])

    bounds = (
        [(float(lo[i]), float(hi[i])) for i in range(N)]
        + [(None, None)] * T            # xi free
        + [(None, None)]                # zeta free
        + [(0.0, None)] * T             # u >= 0
    )

    res = linprog(
        c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
        bounds=bounds, method="highs",
    )
    if not res.success:
        raise RuntimeError(f"CDaR linprog failed: {res.message}")
    x = res.x
    w_opt = x[:N]
    return w_opt, float(res.fun)


# --------------------------------------------------------------------------- #
# Public CDaR API                                                             #
# --------------------------------------------------------------------------- #
def min_cdar(returns: pd.DataFrame, alpha: float = 0.05,
             target_return: float | None = None,
             weight_bounds: tuple = (0.0, 1.0)) -> OptimResult:
    """Minimize Conditional Drawdown-at-Risk.

    CDaR_alpha = E[DD | DD > VaR_alpha(DD)] where DD is the drawdown series of
    the cumulative-returns process for portfolio weights w.

    Args:
        returns: DataFrame of asset returns (T x N).
        alpha: tail probability for drawdown distribution.
        target_return: optional minimum portfolio return constraint.
        weight_bounds: (lo, hi) per asset.

    Returns:
        OptimResult with CDaR-minimizing weights.
    """
    R, cols, T, N = _validate_returns(returns)
    a = _validate_alpha(alpha)
    lo, hi = _validate_bounds(weight_bounds, N)

    if _HAVE_CVXPY:
        try:
            w, val = _cdar_cvxpy(R, a, target_return, lo, hi)
            backend = "cvxpy"
        except Exception:
            w, val = _cdar_scipy(R, a, target_return, lo, hi)
            backend = "scipy_linprog_fallback"
    else:
        w, val = _cdar_scipy(R, a, target_return, lo, hi)
        backend = "scipy_linprog"

    mu = R.mean(axis=0)
    weights = pd.Series(w, index=cols, name="weights")
    return OptimResult(
        weights=weights,
        objective_value=float(val),
        constraints_active=_active_constraints(w, lo, hi, target_return, mu),
        n_assets=N,
        method=f"min_cdar:{backend}",
    )


# --------------------------------------------------------------------------- #
# Efficient frontier                                                          #
# --------------------------------------------------------------------------- #
def _max_return_under_bounds(R: np.ndarray,
                             lo: np.ndarray, hi: np.ndarray) -> float:
    """Return the maximum achievable mean portfolio return under the
    bounds and the simplex constraint ``sum(w) = 1``.

    Solved as a tiny LP:
        maximize    mu @ w
        subject to  sum(w) = 1
                    lo <= w <= hi
    The single-asset upper-bound used previously is incorrect under tight
    upper bounds (e.g. (0, 0.4) on N=4) where no single asset can absorb
    100% of the budget; the LP respects the bounds exactly.
    """
    mu = R.mean(axis=0)
    N = mu.shape[0]
    # linprog minimizes; flip sign for max.
    c = -mu.astype(float)
    A_eq = np.ones((1, N))
    b_eq = np.array([1.0])
    bounds = [(float(lo[i]), float(hi[i])) for i in range(N)]
    res = linprog(c, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if not res.success:
        # Fall back to single-asset max if the LP is infeasible (it shouldn't
        # be when _validate_bounds already passed, but be defensive).
        return float(mu.max())
    return float(-res.fun)


def efficient_cvar_frontier(returns: pd.DataFrame, n_points: int = 20,
                            alpha: float = 0.05,
                            weight_bounds: tuple = (0.0, 1.0)) -> pd.DataFrame:
    """Compute efficient frontier under CVaR risk.

    Sweeps ``target_return`` between the unconstrained ``min_cvar`` solution's
    mean and the **maximum achievable mean under the same weight bounds** (a
    small max-return LP, not a single-asset upper bound — the latter is wrong
    when upper bounds are tight). For each target solves ``min_cvar`` with the
    forwarded ``weight_bounds``.

    Args:
        returns: DataFrame of asset returns (T x N).
        n_points: number of target_return points to sweep.
        alpha: tail probability for CVaR.
        weight_bounds: (lo, hi) per asset; forwarded to every ``min_cvar``
            call along the frontier so the sweep stays in the same feasible
            region.

    Returns:
        DataFrame indexed 0..n_points-1 with columns:
            target_return, cvar, weights (dict).
    """
    R, cols, T, N = _validate_returns(returns)
    _validate_alpha(alpha)
    lo, hi = _validate_bounds(weight_bounds, N)
    if n_points < 2:
        raise ValueError(f"n_points must be >= 2, got {n_points}")

    # Bound the target_return sweep within the SAME weight_bounds as min_cvar
    # so the sweep can never ask for a target the constrained problem cannot
    # achieve.
    base = min_cvar(returns, alpha=alpha, weight_bounds=weight_bounds)
    base_mu = float(R.mean(axis=0) @ base.weights.values)
    max_mu = _max_return_under_bounds(R, lo, hi)

    # If degenerate (max_mu <= base_mu), fall back to a tiny-range sweep
    if max_mu <= base_mu + 1e-9:
        targets = np.linspace(base_mu, base_mu + 1e-6, n_points)
    else:
        targets = np.linspace(base_mu, max_mu - 1e-9, n_points)

    rows = []
    for t in targets:
        try:
            res = min_cvar(returns, alpha=alpha, target_return=float(t),
                           weight_bounds=weight_bounds)
            rows.append({
                "target_return": float(t),
                "cvar": float(res.objective_value),
                "weights": res.weights.to_dict(),
            })
        except RuntimeError as e:
            # Solver failure for this target only. Log full traceback so
            # the operator can inspect the underlying convex-program error
            # while keeping the frontier sweep going.
            import logging
            import traceback
            logging.getLogger(__name__).error(
                "efficient_cvar_frontier: solver failed for target=%s: %s\n%s",
                float(t), e, traceback.format_exc(),
            )
            rows.append({
                "target_return": float(t),
                "cvar": float("nan"),
                "weights": {},
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Max Sharpe-CVaR (return / CVaR ratio)                                       #
# --------------------------------------------------------------------------- #
def max_sharpe_cvar(returns: pd.DataFrame, alpha: float = 0.05,
                    risk_free_rate: float = 0.0,
                    weight_bounds: tuple = (0.0, 1.0)) -> OptimResult:
    """Maximize (mean_return - risk_free_rate) / CVaR.

    The ratio is non-convex in w, but we solve it on the efficient CVaR
    frontier: trace target_return values from min_cvar's mean up to the maximum
    achievable mean (under ``weight_bounds``), compute (mu - rf)/cvar at each
    point, and return the argmax.

    Args:
        returns: DataFrame of asset returns.
        alpha: tail probability for CVaR.
        risk_free_rate: subtracted from portfolio mean per period.
        weight_bounds: (lo, hi) per asset; forwarded to the frontier sweep
            and to the fallback ``min_cvar`` call.

    Returns:
        OptimResult with weights at the max-ratio frontier point.
    """
    R, cols, T, N = _validate_returns(returns)
    _validate_alpha(alpha)
    lo, hi = _validate_bounds(weight_bounds, N)

    frontier = efficient_cvar_frontier(returns, n_points=40, alpha=alpha,
                                       weight_bounds=weight_bounds)
    if frontier.empty or frontier["cvar"].isna().all():
        raise RuntimeError("max_sharpe_cvar: empty / failed frontier")

    # Compute ratio at each frontier point
    best_ratio = -np.inf
    best_row = None
    for _, row in frontier.iterrows():
        cv = row["cvar"]
        if not np.isfinite(cv) or cv <= 1e-12:
            continue
        excess = row["target_return"] - risk_free_rate
        ratio = excess / cv  # CVaR is a (positive) loss measure
        if ratio > best_ratio:
            best_ratio = ratio
            best_row = row

    if best_row is None:
        # All frontier points had non-positive CVaR -> fallback to plain min_cvar
        return min_cvar(returns, alpha=alpha, weight_bounds=weight_bounds)

    w_dict = best_row["weights"]
    w = np.array([w_dict.get(c, 0.0) for c in cols], dtype=float)
    weights = pd.Series(w, index=cols, name="weights")
    mu = R.mean(axis=0)
    return OptimResult(
        weights=weights,
        objective_value=float(-best_ratio),  # store -ratio so "smaller is better"
        constraints_active=_active_constraints(w, lo, hi, None, mu)
        + [f"max_ratio={best_ratio:.6f}"],
        n_assets=N,
        method=f"max_sharpe_cvar:frontier_search:cvxpy={_HAVE_CVXPY}",
    )
