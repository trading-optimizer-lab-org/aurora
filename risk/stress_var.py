"""Stress VaR (Basel III SVaR).

Reference: Basel III, Revisions to the Basel II market risk framework (BCBS
2011). SVaR is computed on a fixed 12-month historical stress window of
significant financial distress (e.g. 2008-2009).

Common stress windows
---------------------
- ``'2008'``  : 2008-09-01 to 2009-08-31  (GFC)
- ``'2020'``  : 2020-02-15 to 2021-02-15  (COVID-19)
- ``'2022'``  : 2022-01-01 to 2022-12-31  (Inflation/Rates)
- ``'custom'``: user-provided start/end dates
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Mapping

import numpy as np
import pandas as pd


_PRESETS: Mapping[str, tuple[str, str]] = {
    "2008": ("2008-09-01", "2009-08-31"),
    "2020": ("2020-02-15", "2021-02-15"),
    "2022": ("2022-01-01", "2022-12-31"),
}


@dataclass
class StressVaR:
    """Basel III SVaR calibration on a historical stress window.

    Parameters
    ----------
    confidence
        Confidence level (Basel default 0.99).
    holding_period
        Holding-period horizon in trading days (Basel default 10).
    window
        Preset ('2008', '2020', '2022') or 'custom'.
    custom_start, custom_end
        Required if ``window == 'custom'``. ISO date strings.
    method
        ``'historical'`` or ``'parametric'`` (Gaussian).
    """
    confidence: float = 0.99
    holding_period: int = 10
    window: str = "2008"
    custom_start: Optional[str] = None
    custom_end: Optional[str] = None
    method: str = "historical"

    def __post_init__(self) -> None:
        if not (0.0 < self.confidence < 1.0):
            raise ValueError("confidence must be in (0,1)")
        if self.holding_period < 1:
            raise ValueError("holding_period must be >= 1")
        if self.method not in ("historical", "parametric"):
            raise ValueError("method must be 'historical' or 'parametric'")
        if self.window != "custom" and self.window not in _PRESETS:
            raise ValueError(f"window must be 'custom' or one of {list(_PRESETS)}")
        if self.window == "custom":
            if not (self.custom_start and self.custom_end):
                raise ValueError("custom_start and custom_end required for window='custom'")

    def _window_dates(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        if self.window == "custom":
            return pd.Timestamp(self.custom_start), pd.Timestamp(self.custom_end)
        s, e = _PRESETS[self.window]
        return pd.Timestamp(s), pd.Timestamp(e)

    def _slice_window(self, returns: pd.Series) -> pd.Series:
        if not isinstance(returns.index, pd.DatetimeIndex):
            raise TypeError("returns must have a DatetimeIndex")
        s, e = self._window_dates()
        sub = returns.loc[(returns.index >= s) & (returns.index <= e)]
        return sub.dropna()

    def compute(self, returns) -> float:
        """Compute SVaR on a single returns series. Returned as positive loss fraction."""
        if isinstance(returns, pd.Series):
            sub = self._slice_window(returns)
        else:
            # numeric vector: treat as already-stress-window losses
            arr = np.asarray(returns, dtype=float).ravel()
            arr = arr[~np.isnan(arr)]
            sub = pd.Series(arr)
        if sub.size == 0:
            return 0.0
        losses = -sub.to_numpy()
        if self.method == "historical":
            base_var = float(np.quantile(losses, self.confidence))
        else:
            mu = float(losses.mean())
            sd = float(losses.std(ddof=1)) if losses.size > 1 else 0.0
            from scipy.stats import norm
            base_var = float(mu + sd * norm.ppf(self.confidence))
        # Basel scaling: SVaR_h = VaR_1d * sqrt(h)
        return float(base_var * np.sqrt(self.holding_period))

    def allocate(self, returns_df: pd.DataFrame) -> np.ndarray:
        """Inverse-SVaR weights across columns of a DataFrame indexed by date."""
        if not isinstance(returns_df, pd.DataFrame):
            raise TypeError("returns_df must be a pd.DataFrame with DatetimeIndex")
        N = returns_df.shape[1]
        if N == 0:
            return np.array([])
        svars = np.array([self.compute(returns_df.iloc[:, j]) for j in range(N)])
        if not np.all(svars > 0):
            return np.full(N, 1.0 / N)
        inv = 1.0 / svars
        return inv / inv.sum()
