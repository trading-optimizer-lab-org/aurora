"""Calibratable square-root + linear market-impact model.

Models execution cost (in price units, per share) as::

    impact(qty) = a * (qty / adv) + b * sqrt(qty / adv) * sigma + c

where ``adv`` is average daily volume and ``sigma`` is daily volatility.
Coefficients ``a``, ``b`` (and optional intercept ``c``) can be
calibrated by least-squares against observed (size, cost) pairs.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np


@dataclass(frozen=True)
class MarketImpactConfig:
    """Configuration for :class:`MarketImpactModel`."""
    a: float = 0.1               # linear coefficient (in vol units)
    b: float = 0.5               # sqrt coefficient
    c: float = 0.0               # intercept
    sigma_default: float = 0.02  # used if not provided per-call
    adv_default: float = 1e6
    fit_intercept: bool = False

    def __post_init__(self):
        for name in ("a", "b"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.sigma_default <= 0:
            raise ValueError("sigma_default must be > 0")
        if self.adv_default <= 0:
            raise ValueError("adv_default must be > 0")


@dataclass
class MarketImpactResult:
    """Calibration result returned by :meth:`MarketImpactModel.calibrate`."""
    a: float
    b: float
    c: float
    rmse: float
    n_obs: int


class MarketImpactModel:
    """Square-root + linear market-impact model with simple calibration."""

    def __init__(self, config: Optional[MarketImpactConfig] = None):
        self.config = config or MarketImpactConfig()
        self.a = float(self.config.a)
        self.b = float(self.config.b)
        self.c = float(self.config.c)

    def predict(
        self,
        qty: float,
        adv: Optional[float] = None,
        sigma: Optional[float] = None,
    ) -> float:
        """Predicted impact in *price* units (e.g. dollars per share)."""
        if qty < 0:
            raise ValueError("qty must be >= 0")
        adv = float(adv if adv is not None else self.config.adv_default)
        sigma = float(sigma if sigma is not None else self.config.sigma_default)
        if adv <= 0 or sigma <= 0:
            raise ValueError("adv and sigma must be > 0")
        ratio = qty / adv
        return float(self.a * ratio + self.b * np.sqrt(ratio) * sigma + self.c)

    def calibrate(
        self,
        sizes: Sequence[float],
        costs: Sequence[float],
        adv: Optional[Sequence[float]] = None,
        sigma: Optional[Sequence[float]] = None,
    ) -> MarketImpactResult:
        """Fit ``a``, ``b`` (and optional ``c``) by least squares."""
        sizes_arr = np.asarray(sizes, dtype=float)
        costs_arr = np.asarray(costs, dtype=float)
        if sizes_arr.shape != costs_arr.shape:
            raise ValueError("sizes and costs shape mismatch")
        if sizes_arr.size < 2:
            raise ValueError("need at least 2 observations")
        if np.any(sizes_arr < 0):
            raise ValueError("sizes must be >= 0")
        n = sizes_arr.size
        adv_arr = (
            np.asarray(adv, dtype=float)
            if adv is not None
            else np.full(n, self.config.adv_default)
        )
        sigma_arr = (
            np.asarray(sigma, dtype=float)
            if sigma is not None
            else np.full(n, self.config.sigma_default)
        )
        if np.any(adv_arr <= 0) or np.any(sigma_arr <= 0):
            raise ValueError("adv, sigma must be > 0")
        ratio = sizes_arr / adv_arr
        x_lin = ratio
        x_sqrt = np.sqrt(ratio) * sigma_arr
        if self.config.fit_intercept:
            X = np.column_stack([x_lin, x_sqrt, np.ones(n)])
        else:
            X = np.column_stack([x_lin, x_sqrt])
        coef, *_ = np.linalg.lstsq(X, costs_arr, rcond=None)
        if self.config.fit_intercept:
            self.a, self.b, self.c = float(coef[0]), float(coef[1]), float(coef[2])
        else:
            self.a, self.b = float(coef[0]), float(coef[1])
            self.c = 0.0
        residuals = costs_arr - X @ coef
        rmse = float(np.sqrt(np.mean(residuals ** 2)))
        return MarketImpactResult(
            a=self.a, b=self.b, c=self.c, rmse=rmse, n_obs=n,
        )
