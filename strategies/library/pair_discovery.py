"""Pair discovery via Engle-Granger cointegration test.

Searches every pair (i, j) in a price universe, computes:
  1. OLS hedge ratio: y_a = beta * y_b + alpha
  2. Spread residual: r = y_a - beta * y_b - alpha
  3. ADF-style stationarity p-value on the residual
  4. Half-life of mean reversion: -ln(2) / lambda from AR(1) on dr

Lazy-imports statsmodels for the proper ADF test; falls back to a hand-rolled
ADF approximation when statsmodels is not installed (no hard dependency).

Returns ranked list of cointegrated pairs (lower p_value = stronger).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import math

import numpy as np
import pandas as pd


@dataclass
class PairResult:
    """One cointegrated pair candidate."""
    sym_a: str
    sym_b: str
    hedge_ratio: float
    alpha: float
    p_value: float
    half_life: float
    spread_std: float


@dataclass
class PairDiscoveryConfig:
    """Configuration for pair search."""
    p_value_threshold: float = 0.05
    min_overlap: int = 252
    max_half_life: float = 252.0
    min_half_life: float = 1.0
    use_statsmodels: bool = True


class PairDiscoveryEngine:
    """Cointegration-based pair finder via Engle-Granger.

    Usage:
        engine = PairDiscoveryEngine(PairDiscoveryConfig())
        prices = {sym: pd.Series, ...}
        pairs = engine.discover(prices)  # ranked list of PairResult
    """

    def __init__(self, config: Optional[PairDiscoveryConfig] = None):
        self.config = config or PairDiscoveryConfig()

    # ---- core stat helpers -------------------------------------------- #

    @staticmethod
    def _ols(y: np.ndarray, x: np.ndarray) -> tuple[float, float, np.ndarray]:
        """Simple OLS y = beta*x + alpha. Returns (beta, alpha, residuals)."""
        x_mean = x.mean()
        y_mean = y.mean()
        var_x = float(np.var(x))
        if var_x <= 0:
            return 0.0, float(y_mean), y - y_mean
        beta = float(np.cov(y, x, ddof=0)[0, 1] / var_x)
        alpha = float(y_mean - beta * x_mean)
        resid = y - beta * x - alpha
        return beta, alpha, resid

    @staticmethod
    def _adf_fallback(r: np.ndarray) -> float:
        """Lightweight ADF-style p-value approximation.

        Regress dr_t = rho * r_{t-1} + eps_t. The t-stat on rho is the ADF
        statistic. Compare to MacKinnon-style critical values (1pct ~ -3.43,
        5pct ~ -2.86, 10pct ~ -2.57). We linearly interpolate / extrapolate
        a p-value in [0.001, 0.5]. This is an APPROXIMATION suitable for
        ranking pairs when statsmodels is unavailable.
        """
        n = len(r)
        if n < 20:
            return 1.0
        dr = np.diff(r)
        rl = r[:-1]
        # Regression dr = rho*rl
        var_rl = float(np.var(rl))
        if var_rl <= 0:
            return 1.0
        rho = float(np.cov(dr, rl, ddof=0)[0, 1] / var_rl)
        pred = rho * rl
        resid = dr - pred
        sse = float(np.sum(resid ** 2))
        dof = n - 2
        if dof <= 0:
            return 1.0
        sigma2 = sse / dof
        se_rho = math.sqrt(sigma2 / (var_rl * (n - 1))) if var_rl > 0 else float("inf")
        if se_rho == 0 or not math.isfinite(se_rho):
            return 1.0
        t_stat = rho / se_rho
        # Map t_stat to approximate p-value via piecewise linear interp
        # of MacKinnon critical values for the no-constant ADF test.
        # More negative => smaller p-value.
        crit = [(-4.5, 0.001), (-3.43, 0.01), (-2.86, 0.05),
                (-2.57, 0.10), (-1.62, 0.25), (-0.44, 0.50), (1.0, 0.95)]
        if t_stat <= crit[0][0]:
            return crit[0][1]
        if t_stat >= crit[-1][0]:
            return crit[-1][1]
        for (t1, p1), (t2, p2) in zip(crit[:-1], crit[1:]):
            if t1 <= t_stat <= t2:
                if t2 == t1:
                    return p1
                w = (t_stat - t1) / (t2 - t1)
                return float(p1 + w * (p2 - p1))
        return 0.5

    @staticmethod
    def _half_life(r: np.ndarray) -> float:
        """Half-life from AR(1) coeff on residual: dr_t = lambda * r_{t-1}."""
        if len(r) < 4:
            return float("inf")
        dr = np.diff(r)
        rl = r[:-1]
        var_rl = float(np.var(rl))
        if var_rl <= 0:
            return float("inf")
        lam = float(np.cov(dr, rl, ddof=0)[0, 1] / var_rl)
        if lam >= 0:
            return float("inf")  # not mean-reverting
        return -math.log(2.0) / lam

    def _engle_granger(self, y_a: np.ndarray, y_b: np.ndarray) -> tuple[float, float, float, float, float]:
        """Run EG test on aligned arrays. Returns (beta, alpha, p_value, half_life, spread_std)."""
        beta, alpha, resid = self._ols(y_a, y_b)
        spread_std = float(np.std(resid))

        p_value = 1.0
        if self.config.use_statsmodels:
            try:
                # Lazy import only when requested
                from statsmodels.tsa.stattools import adfuller  # type: ignore
                # autolag set to None for determinism
                stat = adfuller(resid, autolag=None, maxlag=1, regression="n")
                p_value = float(stat[1])
            except Exception:
                p_value = self._adf_fallback(resid)
        else:
            p_value = self._adf_fallback(resid)

        hl = self._half_life(resid)
        return beta, alpha, p_value, hl, spread_std

    # ---- public API ---------------------------------------------------- #

    def discover(self, prices: dict[str, pd.Series]) -> list[PairResult]:
        """Search all pairs in `prices` for cointegration.

        Args:
            prices: {symbol: pd.Series} with DatetimeIndex.

        Returns:
            List of PairResult sorted by p_value asc, filtered by config.
        """
        if not isinstance(prices, dict) or len(prices) < 2:
            return []
        symbols = sorted(prices.keys())
        results: list[PairResult] = []
        cfg = self.config
        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                sa, sb = symbols[i], symbols[j]
                pa, pb = prices[sa], prices[sb]
                if not isinstance(pa, pd.Series) or not isinstance(pb, pd.Series):
                    continue
                idx = pa.index.intersection(pb.index)
                if len(idx) < cfg.min_overlap:
                    continue
                ya = pa.reindex(idx).dropna().values.astype(float)
                yb = pb.reindex(idx).dropna().values.astype(float)
                m = min(len(ya), len(yb))
                if m < cfg.min_overlap:
                    continue
                ya = ya[-m:]
                yb = yb[-m:]
                try:
                    beta, alpha, p, hl, std = self._engle_granger(ya, yb)
                except Exception:
                    continue
                if not math.isfinite(p) or not math.isfinite(hl):
                    continue
                if p > cfg.p_value_threshold:
                    continue
                if hl < cfg.min_half_life or hl > cfg.max_half_life:
                    continue
                results.append(PairResult(
                    sym_a=sa, sym_b=sb,
                    hedge_ratio=beta, alpha=alpha,
                    p_value=p, half_life=hl, spread_std=std,
                ))
        results.sort(key=lambda r: r.p_value)
        return results
