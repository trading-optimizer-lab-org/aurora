"""Pattern detectors (R79)."""
from __future__ import annotations

import numpy as np


def _local_min_indices(arr: np.ndarray, window: int) -> list[int]:
    out = []
    for i in range(window, len(arr) - window):
        seg = arr[i - window: i + window + 1]
        if arr[i] == seg.min():
            out.append(i)
    return out


def _local_max_indices(arr: np.ndarray, window: int) -> list[int]:
    out = []
    for i in range(window, len(arr) - window):
        seg = arr[i - window: i + window + 1]
        if arr[i] == seg.max():
            out.append(i)
    return out


def detect_double_bottom(
    prices: np.ndarray,
    *,
    pivot_window: int = 5,
    tolerance_pct: float = 0.02,
    min_separation: int = 5,
) -> np.ndarray:
    """Mark bars where a double bottom completes.

    A double bottom is two local minima within ``tolerance_pct`` of each
    other, separated by at least ``min_separation`` bars.
    """
    prices = np.asarray(prices, dtype=float)
    out: np.ndarray = np.zeros(len(prices), dtype=bool)
    pivots = _local_min_indices(prices, pivot_window)
    for i in range(len(pivots) - 1):
        a, b = pivots[i], pivots[i + 1]
        if b - a < min_separation:
            continue
        rel = abs(prices[a] - prices[b]) / max(abs(prices[a]), 1e-9)
        if rel <= tolerance_pct:
            out[b] = True
    return out


def detect_double_top(
    prices: np.ndarray,
    *,
    pivot_window: int = 5,
    tolerance_pct: float = 0.02,
    min_separation: int = 5,
) -> np.ndarray:
    """Mark bars where a double top completes."""
    prices = np.asarray(prices, dtype=float)
    out: np.ndarray = np.zeros(len(prices), dtype=bool)
    pivots = _local_max_indices(prices, pivot_window)
    for i in range(len(pivots) - 1):
        a, b = pivots[i], pivots[i + 1]
        if b - a < min_separation:
            continue
        rel = abs(prices[a] - prices[b]) / max(abs(prices[a]), 1e-9)
        if rel <= tolerance_pct:
            out[b] = True
    return out


def detect_breakout_high(
    prices: np.ndarray,
    *,
    lookback: int = 20,
) -> np.ndarray:
    """Mark bars whose close is the highest in the trailing ``lookback`` window."""
    prices = np.asarray(prices, dtype=float)
    out: np.ndarray = np.zeros(len(prices), dtype=bool)
    for i in range(lookback, len(prices)):
        window = prices[i - lookback: i]
        if prices[i] > window.max():
            out[i] = True
    return out


def detect_breakout_low(
    prices: np.ndarray,
    *,
    lookback: int = 20,
) -> np.ndarray:
    """Mark bars whose close is the lowest in the trailing ``lookback`` window."""
    prices = np.asarray(prices, dtype=float)
    out: np.ndarray = np.zeros(len(prices), dtype=bool)
    for i in range(lookback, len(prices)):
        window = prices[i - lookback: i]
        if prices[i] < window.min():
            out[i] = True
    return out


__all__ = [
    "detect_double_bottom",
    "detect_double_top",
    "detect_breakout_high",
    "detect_breakout_low",
]
