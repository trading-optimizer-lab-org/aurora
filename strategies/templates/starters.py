"""Starter strategy templates (R87)."""
from __future__ import annotations

import numpy as np


def _sma(prices: np.ndarray, period: int) -> np.ndarray:
    out = np.full_like(prices, np.nan, dtype=float)
    if period <= 0 or period > len(prices):
        return out
    for i in range(period - 1, len(prices)):
        out[i] = prices[i - period + 1: i + 1].mean()
    return out


def _rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    delta = np.diff(prices, prepend=prices[0])
    up = np.where(delta > 0, delta, 0.0)
    dn = np.where(delta < 0, -delta, 0.0)
    avg_up = np.zeros_like(prices, dtype=float)
    avg_dn = np.zeros_like(prices, dtype=float)
    if len(prices) >= period:
        avg_up[period - 1] = up[:period].mean()
        avg_dn[period - 1] = dn[:period].mean()
        for i in range(period, len(prices)):
            avg_up[i] = (avg_up[i - 1] * (period - 1) + up[i]) / period
            avg_dn[i] = (avg_dn[i - 1] * (period - 1) + dn[i]) / period
    rs = np.where(avg_dn > 0, avg_up / avg_dn, np.inf)
    return 100.0 - 100.0 / (1.0 + rs)


def trend_following_ma_cross(
    prices: np.ndarray,
    *,
    fast: int = 20,
    slow: int = 50,
) -> np.ndarray:
    """Long when fast SMA is above slow SMA, flat otherwise."""
    prices = np.asarray(prices, dtype=float)
    fast_ma = _sma(prices, fast)
    slow_ma = _sma(prices, slow)
    out = np.zeros_like(prices, dtype=float)
    valid = ~(np.isnan(fast_ma) | np.isnan(slow_ma))
    out[valid] = (fast_ma[valid] > slow_ma[valid]).astype(float)
    return out


def mean_reversion_rsi(
    prices: np.ndarray,
    *,
    period: int = 14,
    oversold: float = 30.0,
    overbought: float = 70.0,
) -> np.ndarray:
    """Long when RSI < oversold, short when > overbought, else flat."""
    prices = np.asarray(prices, dtype=float)
    rsi = _rsi(prices, period)
    out = np.zeros_like(prices, dtype=float)
    out[rsi < oversold] = 1.0
    out[rsi > overbought] = -1.0
    return out


def breakout_donchian(
    prices: np.ndarray,
    *,
    lookback: int = 20,
) -> np.ndarray:
    """Long on close above trailing high; short on close below trailing low."""
    prices = np.asarray(prices, dtype=float)
    out = np.zeros_like(prices, dtype=float)
    for i in range(lookback, len(prices)):
        window = prices[i - lookback: i]
        if prices[i] > window.max():
            out[i] = 1.0
        elif prices[i] < window.min():
            out[i] = -1.0
    return out


__all__ = [
    "trend_following_ma_cross",
    "mean_reversion_rsi",
    "breakout_donchian",
]
