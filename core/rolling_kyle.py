"""Rolling Kyle's lambda estimator (R131).

The price-impact coefficient (Kyle's lambda) is currently a static fit
in the cost / microstructure layer. Liquidity regime changes mean a
single number is wrong by the time the calibration is months old.

This module provides a rolling estimator that fits

    delta_price_t = lambda * signed_volume_t + epsilon_t

over a trailing window, returning a time-series of lambdas. Callers
plug the latest estimate into ``CostModel.slippage_bps`` or feed it
into the dynamic-cap evaluator (R133).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np


@dataclass(frozen=True)
class KyleEstimate:
    """One rolling-window estimate of Kyle's lambda."""

    end_index: int
    lambda_bps_per_pct_volume: float
    r_squared: float
    n_obs: int


def rolling_kyle_lambda(
    delta_prices_bps: np.ndarray,
    signed_volume_pct: np.ndarray,
    *,
    window: int = 60,
    step: int = 5,
) -> List[KyleEstimate]:
    """Rolling OLS fit of price-impact slope.

    Args:
        delta_prices_bps: per-bar mid-price change in bps.
        signed_volume_pct: per-bar signed volume as a percentage of ADV
            (positive for buys, negative for sells).
        window: bars per rolling window.
        step: stride between windows.

    Returns:
        list of :class:`KyleEstimate`, one per window.
    """
    delta = np.asarray(delta_prices_bps, dtype=float)
    vol = np.asarray(signed_volume_pct, dtype=float)
    if len(delta) != len(vol):
        raise ValueError("delta_prices_bps and signed_volume_pct must align")
    if window < 5:
        raise ValueError("window must be >= 5")

    out: List[KyleEstimate] = []
    n = len(delta)
    end = window
    while end <= n:
        x = vol[end - window: end]
        y = delta[end - window: end]
        if np.std(x) <= 1e-9:
            out.append(KyleEstimate(
                end_index=end - 1,
                lambda_bps_per_pct_volume=0.0,
                r_squared=0.0,
                n_obs=window,
            ))
        else:
            A = np.column_stack([np.ones_like(x), x])
            coef, *_ = np.linalg.lstsq(A, y, rcond=None)
            pred = A @ coef
            ss_res = float(np.sum((y - pred) ** 2))
            ss_tot = float(np.sum((y - y.mean()) ** 2))
            r2 = 0.0 if ss_tot <= 1e-12 else 1.0 - ss_res / ss_tot
            out.append(KyleEstimate(
                end_index=end - 1,
                lambda_bps_per_pct_volume=float(coef[1]),
                r_squared=r2,
                n_obs=window,
            ))
        end += step
    return out


__all__ = [
    "KyleEstimate",
    "rolling_kyle_lambda",
]
