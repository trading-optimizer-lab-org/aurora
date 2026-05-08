"""A/B testing for live strategies.

Apply standard hypothesis tests to compare two strategies' returns.
Two tests are supported:

    welch_t       -- Welch's t-test (parametric, unequal variances)
    mann_whitney  -- Mann-Whitney U (non-parametric)

Both are implemented from scratch on top of NumPy so the module has no
hard dependency on SciPy. SciPy gives more accurate p-values for small
samples but for typical live windows (months of daily returns) the
normal approximation used here is adequate.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import erf, sqrt
import numpy as np


@dataclass
class ABTestResult:
    test: str
    n_a: int
    n_b: int
    mean_a: float
    mean_b: float
    statistic: float
    p_value: float
    alpha: float
    significant: bool
    winner: str  # 'A', 'B', or 'tie'


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _two_sided_p_from_z(z: float) -> float:
    return 2.0 * (1.0 - _normal_cdf(abs(z)))


class ABTestFramework:
    """Compare two strategy return series with a Welch t or Mann-Whitney."""

    def __init__(self, alpha: float = 0.05):
        if not (0.0 < alpha < 1.0):
            raise ValueError("alpha must be in (0, 1)")
        self.alpha = float(alpha)

    def welch_t(self, returns_a: np.ndarray,
                returns_b: np.ndarray) -> ABTestResult:
        a = self._clean(returns_a)
        b = self._clean(returns_b)
        if len(a) < 2 or len(b) < 2:
            raise ValueError("need at least 2 observations per arm")
        mean_a = float(a.mean())
        mean_b = float(b.mean())
        var_a = float(a.var(ddof=1))
        var_b = float(b.var(ddof=1))
        se = (var_a / len(a) + var_b / len(b)) ** 0.5
        if se <= 0:
            t = 0.0
        else:
            t = (mean_a - mean_b) / se
        p = _two_sided_p_from_z(t)
        sig = p < self.alpha
        winner = self._winner(mean_a, mean_b, sig)
        return ABTestResult(
            test="welch_t", n_a=len(a), n_b=len(b),
            mean_a=mean_a, mean_b=mean_b,
            statistic=float(t), p_value=float(p),
            alpha=self.alpha, significant=bool(sig), winner=winner,
        )

    def mann_whitney(self, returns_a: np.ndarray,
                     returns_b: np.ndarray) -> ABTestResult:
        a = self._clean(returns_a)
        b = self._clean(returns_b)
        n_a, n_b = len(a), len(b)
        if n_a < 1 or n_b < 1:
            raise ValueError("need at least 1 observation per arm")
        all_vals = np.concatenate([a, b])
        order = np.argsort(all_vals, kind="mergesort")
        ranks = np.empty_like(order, dtype=float)
        ranks[order] = np.arange(1, len(all_vals) + 1, dtype=float)
        # tie correction: average ranks within ties
        sorted_vals = all_vals[order]
        i = 0
        while i < len(sorted_vals):
            j = i + 1
            while j < len(sorted_vals) and sorted_vals[j] == sorted_vals[i]:
                j += 1
            if j - i > 1:
                avg = ranks[order[i:j]].mean()
                ranks[order[i:j]] = avg
            i = j
        rank_a = ranks[: n_a]
        u_a = rank_a.sum() - n_a * (n_a + 1) / 2
        u_b = n_a * n_b - u_a
        u = min(u_a, u_b)
        # normal approximation
        mu = n_a * n_b / 2.0
        sd = sqrt(n_a * n_b * (n_a + n_b + 1) / 12.0)
        if sd <= 0:
            z = 0.0
        else:
            z = (u - mu) / sd
        p = _two_sided_p_from_z(z)
        sig = p < self.alpha
        mean_a = float(a.mean())
        mean_b = float(b.mean())
        winner = self._winner(mean_a, mean_b, sig)
        return ABTestResult(
            test="mann_whitney", n_a=n_a, n_b=n_b,
            mean_a=mean_a, mean_b=mean_b,
            statistic=float(u), p_value=float(p),
            alpha=self.alpha, significant=bool(sig), winner=winner,
        )

    @staticmethod
    def _clean(arr: np.ndarray) -> np.ndarray:
        a = np.asarray(arr, dtype=float)
        return a[~np.isnan(a)]

    @staticmethod
    def _winner(mean_a: float, mean_b: float, sig: bool) -> str:
        if not sig:
            return "tie"
        return "A" if mean_a > mean_b else "B"
