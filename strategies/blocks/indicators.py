"""Indicator block library (R86).

Standard indicator set with parameter ranges and warmup windows so the
auto-discovery generator (R77) and the rule editor IR (R78) can sample
valid configurations.

Each :class:`IndicatorBlock` exposes a ``compute(prices, **params)``
callable that returns an aligned-length array. Anti-lookahead:
``compute(prices)[i]`` MUST only depend on ``prices[:i+1]`` -- the
helper :func:`require_anti_lookahead` enforces this in tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# Parameter ranges
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ParameterRange:
    """Allowed range for one parameter sampled by the generator."""

    name: str
    low: float
    high: float
    is_integer: bool = False

    def sample(self, rng: np.random.Generator) -> float:
        if self.is_integer:
            return int(rng.integers(int(self.low), int(self.high) + 1))
        return float(rng.uniform(self.low, self.high))


# --------------------------------------------------------------------------
# Indicator block
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class IndicatorBlock:
    """Frozen indicator definition.

    Attributes:
        name: short canonical name (``"RSI"``, ``"EMA"``, ...).
        compute: callable that returns the indicator values for a
            given price series and parameters.
        params: parameter-name -> ParameterRange.
        warmup_attr: name of the parameter that drives the warmup
            window. Used by the generator to size the IS_TRAIN slice
            so the indicator is well-defined.
    """

    name: str
    compute: Callable[..., np.ndarray]
    params: Dict[str, ParameterRange]
    warmup_attr: Optional[str] = None

    def sample_params(self, rng: np.random.Generator) -> Dict[str, Any]:
        return {n: r.sample(rng) for n, r in self.params.items()}

    def warmup(self, params: Dict[str, Any]) -> int:
        if self.warmup_attr is None:
            return 0
        try:
            return int(params[self.warmup_attr])
        except (KeyError, TypeError, ValueError):
            return 0


# --------------------------------------------------------------------------
# Compute primitives
# --------------------------------------------------------------------------


def _to_series(prices) -> pd.Series:
    if isinstance(prices, pd.Series):
        return prices
    return pd.Series(np.asarray(prices, dtype=float))


def sma(prices, period: int = 20) -> np.ndarray:
    return _to_series(prices).rolling(int(period), min_periods=int(period)).mean().to_numpy()


def ema(prices, period: int = 20) -> np.ndarray:
    return _to_series(prices).ewm(span=int(period), adjust=False, min_periods=int(period)).mean().to_numpy()


def rsi(prices, period: int = 14) -> np.ndarray:
    s = _to_series(prices)
    delta = s.diff()
    gain = delta.clip(lower=0).rolling(int(period), min_periods=int(period)).mean()
    loss = -delta.clip(upper=0).rolling(int(period), min_periods=int(period)).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).to_numpy()


def bollinger_upper(prices, period: int = 20, num_std: float = 2.0) -> np.ndarray:
    s = _to_series(prices)
    mid = s.rolling(int(period), min_periods=int(period)).mean()
    std = s.rolling(int(period), min_periods=int(period)).std(ddof=0)
    return (mid + num_std * std).to_numpy()


def bollinger_lower(prices, period: int = 20, num_std: float = 2.0) -> np.ndarray:
    s = _to_series(prices)
    mid = s.rolling(int(period), min_periods=int(period)).mean()
    std = s.rolling(int(period), min_periods=int(period)).std(ddof=0)
    return (mid - num_std * std).to_numpy()


def atr_proxy(prices, period: int = 14) -> np.ndarray:
    """Close-only ATR proxy (rolling mean of |delta|)."""
    s = _to_series(prices)
    tr = s.diff().abs()
    return tr.rolling(int(period), min_periods=int(period)).mean().to_numpy()


def macd_line(prices, fast: int = 12, slow: int = 26) -> np.ndarray:
    e_fast = pd.Series(ema(prices, period=fast))
    e_slow = pd.Series(ema(prices, period=slow))
    return (e_fast - e_slow).to_numpy()


def stochastic_k(prices, period: int = 14) -> np.ndarray:
    s = _to_series(prices)
    low = s.rolling(int(period), min_periods=int(period)).min()
    high = s.rolling(int(period), min_periods=int(period)).max()
    rng = (high - low).replace(0, np.nan)
    return (100 * (s - low) / rng).to_numpy()


def adx_proxy(prices, period: int = 14) -> np.ndarray:
    """Close-only ADX proxy: rolling mean of |ROC|."""
    s = _to_series(prices)
    roc = s.pct_change().abs()
    return roc.rolling(int(period), min_periods=int(period)).mean().to_numpy()


def donchian_upper(prices, period: int = 20) -> np.ndarray:
    return _to_series(prices).rolling(int(period), min_periods=int(period)).max().to_numpy()


def donchian_lower(prices, period: int = 20) -> np.ndarray:
    return _to_series(prices).rolling(int(period), min_periods=int(period)).min().to_numpy()


def momentum(prices, period: int = 20) -> np.ndarray:
    s = _to_series(prices)
    return (s - s.shift(int(period))).to_numpy()


def roc(prices, period: int = 12) -> np.ndarray:
    s = _to_series(prices)
    return s.pct_change(int(period)).to_numpy()


def cci_proxy(prices, period: int = 20) -> np.ndarray:
    """Close-only Commodity Channel Index proxy."""
    s = _to_series(prices)
    sma_v = s.rolling(int(period), min_periods=int(period)).mean()
    md = (s - sma_v).abs().rolling(int(period), min_periods=int(period)).mean()
    out = (s - sma_v) / (0.015 * md.replace(0, np.nan))
    return out.to_numpy()


def williams_r(prices, period: int = 14) -> np.ndarray:
    s = _to_series(prices)
    high = s.rolling(int(period), min_periods=int(period)).max()
    low = s.rolling(int(period), min_periods=int(period)).min()
    rng = (high - low).replace(0, np.nan)
    return (-100 * (high - s) / rng).to_numpy()


def obv_proxy(prices, period: int = 14) -> np.ndarray:
    """Close-only OBV proxy: cumulative sign(delta) over rolling window."""
    s = _to_series(prices)
    sign = np.sign(s.diff().fillna(0))
    return sign.rolling(int(period), min_periods=int(period)).sum().to_numpy()


def vwap_proxy(prices, period: int = 20) -> np.ndarray:
    """Close-only VWAP proxy (no real volume): rolling mean."""
    return sma(prices, period=period)


def hurst_proxy(prices, period: int = 50) -> np.ndarray:
    """Rolling Hurst exponent estimate via standard-deviation ratio."""
    s = _to_series(prices).pct_change().dropna()
    out = np.full(len(prices), np.nan)
    for i in range(int(period), len(s) + 1):
        window = s.iloc[i - int(period): i]
        if window.std() == 0:
            out[i] = np.nan
            continue
        # Simple R/S-style proxy, capped to (0, 1).
        rng = window.max() - window.min()
        std = window.std()
        if std == 0:
            continue
        out[i] = float(np.clip(np.log(rng / std + 1e-9) / np.log(int(period)), 0, 1))
    return out


# --------------------------------------------------------------------------
# Standard registry
# --------------------------------------------------------------------------


@dataclass
class IndicatorRegistry:
    """Mutable registry of indicator blocks."""

    blocks: Dict[str, IndicatorBlock] = field(default_factory=dict)

    def register(self, block: IndicatorBlock) -> None:
        self.blocks[block.name] = block

    def get(self, name: str) -> IndicatorBlock:
        if name not in self.blocks:
            raise KeyError(f"unknown indicator block: {name!r}")
        return self.blocks[name]

    def names(self) -> list[str]:
        return sorted(self.blocks)

    def __len__(self) -> int:
        return len(self.blocks)

    def __contains__(self, name: str) -> bool:
        return name in self.blocks


def _build_standard_registry() -> IndicatorRegistry:
    reg = IndicatorRegistry()
    reg.register(IndicatorBlock(
        name="SMA",
        compute=sma,
        params={"period": ParameterRange("period", 5, 200, is_integer=True)},
        warmup_attr="period",
    ))
    reg.register(IndicatorBlock(
        name="EMA",
        compute=ema,
        params={"period": ParameterRange("period", 5, 200, is_integer=True)},
        warmup_attr="period",
    ))
    reg.register(IndicatorBlock(
        name="RSI",
        compute=rsi,
        params={"period": ParameterRange("period", 5, 30, is_integer=True)},
        warmup_attr="period",
    ))
    reg.register(IndicatorBlock(
        name="BollingerUpper",
        compute=bollinger_upper,
        params={
            "period": ParameterRange("period", 10, 50, is_integer=True),
            "num_std": ParameterRange("num_std", 1.5, 3.0),
        },
        warmup_attr="period",
    ))
    reg.register(IndicatorBlock(
        name="BollingerLower",
        compute=bollinger_lower,
        params={
            "period": ParameterRange("period", 10, 50, is_integer=True),
            "num_std": ParameterRange("num_std", 1.5, 3.0),
        },
        warmup_attr="period",
    ))
    reg.register(IndicatorBlock(
        name="ATR",
        compute=atr_proxy,
        params={"period": ParameterRange("period", 5, 30, is_integer=True)},
        warmup_attr="period",
    ))
    reg.register(IndicatorBlock(
        name="MACD",
        compute=macd_line,
        params={
            "fast": ParameterRange("fast", 5, 20, is_integer=True),
            "slow": ParameterRange("slow", 20, 50, is_integer=True),
        },
        warmup_attr="slow",
    ))
    reg.register(IndicatorBlock(
        name="StochK",
        compute=stochastic_k,
        params={"period": ParameterRange("period", 5, 30, is_integer=True)},
        warmup_attr="period",
    ))
    reg.register(IndicatorBlock(
        name="ADX",
        compute=adx_proxy,
        params={"period": ParameterRange("period", 7, 30, is_integer=True)},
        warmup_attr="period",
    ))
    reg.register(IndicatorBlock(
        name="DonchianUpper",
        compute=donchian_upper,
        params={"period": ParameterRange("period", 10, 100, is_integer=True)},
        warmup_attr="period",
    ))
    reg.register(IndicatorBlock(
        name="DonchianLower",
        compute=donchian_lower,
        params={"period": ParameterRange("period", 10, 100, is_integer=True)},
        warmup_attr="period",
    ))
    reg.register(IndicatorBlock(
        name="Momentum",
        compute=momentum,
        params={"period": ParameterRange("period", 5, 100, is_integer=True)},
        warmup_attr="period",
    ))
    reg.register(IndicatorBlock(
        name="ROC",
        compute=roc,
        params={"period": ParameterRange("period", 5, 50, is_integer=True)},
        warmup_attr="period",
    ))
    reg.register(IndicatorBlock(
        name="CCI",
        compute=cci_proxy,
        params={"period": ParameterRange("period", 10, 30, is_integer=True)},
        warmup_attr="period",
    ))
    reg.register(IndicatorBlock(
        name="WilliamsR",
        compute=williams_r,
        params={"period": ParameterRange("period", 5, 30, is_integer=True)},
        warmup_attr="period",
    ))
    reg.register(IndicatorBlock(
        name="OBV",
        compute=obv_proxy,
        params={"period": ParameterRange("period", 10, 50, is_integer=True)},
        warmup_attr="period",
    ))
    reg.register(IndicatorBlock(
        name="VWAPProxy",
        compute=vwap_proxy,
        params={"period": ParameterRange("period", 5, 50, is_integer=True)},
        warmup_attr="period",
    ))
    return reg


STANDARD_REGISTRY = _build_standard_registry()


# --------------------------------------------------------------------------
# Anti-lookahead helper for tests
# --------------------------------------------------------------------------


def require_anti_lookahead(
    block: IndicatorBlock,
    prices: np.ndarray,
    params: Dict[str, Any],
) -> bool:
    """True iff ``block.compute`` does not look ahead.

    Implementation: cap the input at a few different tail-truncations
    and assert that the prefix of the output is unchanged.
    """
    full = block.compute(prices, **params)
    n = len(prices)
    for k in (n // 4, n // 2, 3 * n // 4):
        if k < block.warmup(params) + 5:
            continue
        truncated = block.compute(prices[:k], **params)
        # Both must produce a non-trivial prefix; compare ignoring NaN.
        a = full[: k - 1]
        b = truncated[: k - 1]
        for i, (x, y) in enumerate(zip(a, b)):
            if np.isnan(x) and np.isnan(y):
                continue
            if not np.isclose(x, y, equal_nan=False):
                return False
    return True
