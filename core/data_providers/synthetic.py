"""Deterministic synthetic provider for tests.

Generates a Geometric Brownian Motion (GBM) close series from a seed so
two calls with the same arguments produce byte-identical data. Useful
for tests that need a registered provider without a network round-trip.

Tier permission: ``ANY`` (synthetic data is always PIT-correct -- the
RNG cannot peek at the future).
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from . import BaseDataProvider


class SyntheticProvider(BaseDataProvider):
    """GBM synthetic close series from a seed.

    Fetch kwargs:
        seed: int. Defaults to 42. Determines the RNG.
        n_bars: int. Defaults to 500 if both ``start`` and ``end`` are
            None; otherwise auto-computed from the date range.
        freq: pandas freq string for ``pd.date_range``. Defaults to
            ``"B"`` (business days).
        drift: float, mean per-bar log return. Defaults to 0.0005.
        sigma: float, per-bar std of log return. Defaults to 0.01.
        start_price: float starting price. Defaults to 100.0.
    """

    name: str = "synthetic"
    version: str = "synthetic:1.0"
    point_in_time: bool = True
    tier_permission: str = "ANY"

    def _fetch_raw(
        self,
        symbol: str,
        start: Optional[pd.Timestamp],
        end: Optional[pd.Timestamp],
        **kwargs: Any,
    ) -> pd.Series:
        seed = int(kwargs.get("seed", 42))
        freq = kwargs.get("freq", "B")
        drift = float(kwargs.get("drift", 0.0005))
        sigma = float(kwargs.get("sigma", 0.01))
        start_price = float(kwargs.get("start_price", 100.0))

        # Resolve the date range and bar count.
        if start is not None and end is not None:
            idx = pd.date_range(start, end, freq=freq)
            n_bars = len(idx)
        elif start is not None:
            n_bars = int(kwargs.get("n_bars", 500))
            idx = pd.date_range(start, periods=n_bars, freq=freq)
        elif end is not None:
            n_bars = int(kwargs.get("n_bars", 500))
            idx = pd.date_range(end=end, periods=n_bars, freq=freq)
        else:
            n_bars = int(kwargs.get("n_bars", 500))
            idx = pd.date_range("2020-01-01", periods=n_bars, freq=freq)

        if n_bars <= 0:
            return pd.Series([], index=pd.DatetimeIndex([]), name=symbol,
                             dtype="float64")
        rng = np.random.default_rng(seed)
        rets = rng.normal(drift, sigma, n_bars)
        prices = start_price * np.exp(np.cumsum(rets))
        return pd.Series(prices, index=idx, name=symbol)
