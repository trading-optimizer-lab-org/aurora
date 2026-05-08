"""Slippage learning loop (R130).

Calibrate the slippage model from realised fills in paper / live.
Each fill produces a residual (expected vs realised impact); the
loop fits a regression and updates the model for the next backtest.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np


@dataclass(frozen=True)
class FillObservation:
    """One realised fill record."""

    expected_bps: float
    realised_bps: float
    notional_dollars: float
    daily_volume_dollars: float


@dataclass(frozen=True)
class CalibrationResult:
    """Output of the calibration regression."""

    n_observations: int
    fitted_intercept_bps: float
    fitted_size_coef_bps_per_pct_adv: float
    residual_std_bps: float
    advised_slippage_bps: float


def calibrate_slippage(observations: List[FillObservation]) -> CalibrationResult:
    """Fit a linear model: realised_bps = a + b * (notional / ADV) * 100.

    Returns the advised constant slippage_bps to plug into the
    CostModel: the intercept plus the model's expected size impact at
    the median observed notional / ADV.
    """
    if not observations:
        raise ValueError("observations list is empty")
    realised = np.asarray([o.realised_bps for o in observations], dtype=float)
    pct_adv = np.asarray(
        [
            (o.notional_dollars / max(o.daily_volume_dollars, 1.0)) * 100.0
            for o in observations
        ],
        dtype=float,
    )

    # Simple OLS: realised = a + b * pct_adv
    if len(observations) < 2:
        return CalibrationResult(
            n_observations=len(observations),
            fitted_intercept_bps=float(realised.mean()),
            fitted_size_coef_bps_per_pct_adv=0.0,
            residual_std_bps=0.0,
            advised_slippage_bps=float(realised.mean()),
        )

    A = np.column_stack([np.ones_like(pct_adv), pct_adv])
    coef, *_ = np.linalg.lstsq(A, realised, rcond=None)
    a = float(coef[0])
    b = float(coef[1])
    pred = a + b * pct_adv
    residuals = realised - pred
    median_pct_adv = float(np.median(pct_adv))
    advised = a + b * median_pct_adv
    return CalibrationResult(
        n_observations=len(observations),
        fitted_intercept_bps=a,
        fitted_size_coef_bps_per_pct_adv=b,
        residual_std_bps=float(residuals.std(ddof=0)),
        advised_slippage_bps=advised,
    )


__all__ = [
    "FillObservation",
    "CalibrationResult",
    "calibrate_slippage",
]
