"""Copula tail dependence: detect joint extreme moves beyond linear correlation.

Fits Gaussian, Student-t, or Clayton copulas to multi-asset returns and tests
whether tail dependence (lambda_lower / lambda_upper) is materially nonzero.
Linear correlation underestimates joint crash risk when tails are dependent.

Lazy statsmodels import (only used for some auxiliary fits if available); the
core copula MLE is hand-rolled to avoid the dependency.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import math
import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize_scalar

try:  # lazy availability flag
    import statsmodels.api as _sm  # type: ignore
    STATSMODELS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _sm = None  # type: ignore
    STATSMODELS_AVAILABLE = False


def _to_uniform(x: np.ndarray) -> np.ndarray:
    """Empirical CDF transform to uniform [0,1)."""
    n = len(x)
    ranks = stats.rankdata(x, method="average")
    return ranks / (n + 1.0)


@dataclass
class CopulaTailDependence:
    family: str = "gaussian"  # "gaussian", "student_t", "clayton"
    df_t: float = 5.0  # used if family == "student_t"
    tail_quantile: float = 0.05
    rho: float = 0.0
    theta_clayton: float = 0.0
    lambda_lower: float = 0.0
    lambda_upper: float = 0.0
    linear_corr: float = 0.0
    empirical_lower_tail: float = 0.0
    empirical_upper_tail: float = 0.0
    n_obs: int = 0
    asset_pair: tuple = ()

    def _fit_gaussian(self, u: np.ndarray, v: np.ndarray) -> float:
        # Gaussian copula param via Spearman -> Pearson conversion
        z1 = stats.norm.ppf(np.clip(u, 1e-6, 1 - 1e-6))
        z2 = stats.norm.ppf(np.clip(v, 1e-6, 1 - 1e-6))
        return float(np.corrcoef(z1, z2)[0, 1])

    def _fit_clayton(self, u: np.ndarray, v: np.ndarray) -> float:
        # MLE for Clayton via 1D scalar optimization
        def negll(theta):
            t = float(theta)
            if t <= 1e-6:
                return 1e9
            u_c = np.clip(u, 1e-6, 1 - 1e-6)
            v_c = np.clip(v, 1e-6, 1 - 1e-6)
            sum_term = u_c ** (-t) + v_c ** (-t) - 1.0
            if np.any(sum_term <= 0):
                return 1e9
            ll = (np.log(1.0 + t) + (-t - 1.0) * (np.log(u_c) + np.log(v_c))
                  + (-1.0 / t - 2.0) * np.log(sum_term))
            return -float(np.sum(ll))
        out = minimize_scalar(negll, bounds=(1e-3, 20.0), method="bounded")
        return float(out.x) if out.success else 0.5

    def _gaussian_tail_dependence(self, rho: float) -> tuple:
        # Gaussian copula has zero tail dependence
        return 0.0, 0.0

    def _student_t_tail_dependence(self, rho: float, df: float) -> tuple:
        # Symmetric tail dependence for Student-t copula
        if abs(rho) >= 1.0 or df <= 0:
            return 0.0, 0.0
        x = -math.sqrt((df + 1.0) * (1.0 - rho) / (1.0 + rho))
        lam = 2.0 * stats.t.cdf(x, df=df + 1.0)
        return float(lam), float(lam)

    def _clayton_tail_dependence(self, theta: float) -> tuple:
        # Clayton has lower tail dependence only
        if theta <= 0:
            return 0.0, 0.0
        return float(2.0 ** (-1.0 / theta)), 0.0

    def _empirical_tail(self, u: np.ndarray, v: np.ndarray, q: float) -> tuple:
        """Empirical tail dependence estimates."""
        n = len(u)
        # lower: P(V <= q | U <= q) -> count(both<=q) / count(U<=q)
        n_u_low = max(1, int(np.sum(u <= q)))
        n_both_low = int(np.sum((u <= q) & (v <= q)))
        emp_low = n_both_low / n_u_low

        n_u_hi = max(1, int(np.sum(u >= 1.0 - q)))
        n_both_hi = int(np.sum((u >= 1.0 - q) & (v >= 1.0 - q)))
        emp_hi = n_both_hi / n_u_hi
        return float(emp_low), float(emp_hi)

    def run(self, returns_matrix: pd.DataFrame,
            asset_pair: Optional[tuple] = None) -> "CopulaTailDependence":
        if not isinstance(returns_matrix, pd.DataFrame):
            raise TypeError("returns_matrix must be pd.DataFrame")
        if returns_matrix.shape[1] < 2:
            raise ValueError("returns_matrix must have >=2 columns")
        if returns_matrix.shape[0] < 30:
            raise ValueError("need >=30 observations")
        if self.family not in ("gaussian", "student_t", "clayton"):
            raise ValueError(f"unknown family: {self.family}")
        if not (0.0 < self.tail_quantile < 0.5):
            raise ValueError("tail_quantile must be in (0, 0.5)")

        cols = list(returns_matrix.columns)
        if asset_pair is None:
            asset_pair = (cols[0], cols[1])
        a, b = asset_pair
        if a not in cols or b not in cols:
            raise ValueError(f"asset_pair {asset_pair} not in columns {cols}")
        self.asset_pair = (a, b)

        x = returns_matrix[a].dropna().to_numpy()
        y = returns_matrix[b].dropna().to_numpy()
        m = min(len(x), len(y))
        x = x[-m:]; y = y[-m:]
        u = _to_uniform(x)
        v = _to_uniform(y)
        self.n_obs = m
        self.linear_corr = float(np.corrcoef(x, y)[0, 1])

        emp_low, emp_hi = self._empirical_tail(u, v, self.tail_quantile)
        self.empirical_lower_tail = emp_low
        self.empirical_upper_tail = emp_hi

        if self.family == "gaussian":
            self.rho = self._fit_gaussian(u, v)
            self.lambda_lower, self.lambda_upper = self._gaussian_tail_dependence(self.rho)
        elif self.family == "student_t":
            self.rho = self._fit_gaussian(u, v)
            self.lambda_lower, self.lambda_upper = self._student_t_tail_dependence(self.rho, self.df_t)
        else:  # clayton
            self.theta_clayton = self._fit_clayton(u, v)
            self.lambda_lower, self.lambda_upper = self._clayton_tail_dependence(self.theta_clayton)

        return self
