"""Strategy Zoo.

Pre-loaded library of 50+ named single-asset strategies sourced from public
academic literature. Each entry is a thin Strategy subclass wrapping one of:

  * an existing implementation in quantforge/strategies/library
  * a simple closed-form signal computed from price/return statistics

The zoo is INTENTIONALLY single-asset and self-contained. Multi-asset and
factor strategies are stubbed to single-asset variants so the entire zoo
can be backtested through aurora.core.engine.run_backtest.

Public API:
    list_strategies() -> list[ZooEntry]
    get(name) -> ZooEntry
    instantiate(name, **overrides) -> Strategy
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Type
import numpy as np
import pandas as pd

from aurora.strategies.base import Strategy, StrategySpec
from aurora.strategies.library.ma_cross import MACross
from aurora.strategies.library.tsmom import TSMomentum
from aurora.strategies.library.bollinger_mr import BollingerMR
from aurora.strategies.library.dual_momentum import DualMomentum
from aurora.strategies.library.rsi_meanrev import RSIMeanRev
from aurora.strategies.library.donchian import DonchianBreakout


# ---- Building-block helper signals ----------------------------------------


def _rolling_returns(p: np.ndarray, w: int) -> np.ndarray:
    out = np.full(len(p), np.nan)
    for i in range(w, len(p)):
        if p[i - w] > 0:
            out[i] = p[i] / p[i - w] - 1.0
    return out


def _rolling_std(p: np.ndarray, w: int) -> np.ndarray:
    s = pd.Series(p)
    return s.rolling(w, min_periods=w).std(ddof=0).values


def _zscore(p: np.ndarray, w: int) -> np.ndarray:
    s = pd.Series(p)
    mean = s.rolling(w, min_periods=w).mean().values
    std = s.rolling(w, min_periods=w).std(ddof=0).values
    out = np.full(len(p), np.nan)
    mask = (std > 0)
    out[mask] = (p[mask] - mean[mask]) / std[mask]
    return out


# ---- Generic parameterised strategies (used to spawn many zoo entries) -----


class _LookbackMomentum(Strategy):
    """Long if past `lookback` return > threshold; else flat or short."""
    def __init__(self, lookback: int = 60, threshold: float = 0.0,
                 allow_short: bool = False):
        self.lookback = int(lookback)
        self.threshold = float(threshold)
        self.allow_short = bool(allow_short)

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="LookbackMomentum",
            params={"lookback": 60, "threshold": 0.0, "allow_short": False},
            param_ranges={"lookback": (10, 252), "threshold": (-0.05, 0.05),
                          "allow_short": [True, False]},
        )

    def signals(self, prices: pd.Series) -> np.ndarray:
        p = prices.values.astype(float)
        rets = _rolling_returns(p, self.lookback)
        sig = np.zeros(len(p))
        for i in range(len(p)):
            r = rets[i]
            if np.isnan(r):
                continue
            if r > self.threshold:
                sig[i] = 1.0
            elif self.allow_short and r < -self.threshold:
                sig[i] = -1.0
        return sig


class _LowVolFilter(Strategy):
    """Long if rolling vol below median vol over a longer window."""
    def __init__(self, vol_window: int = 20, ref_window: int = 252):
        self.vol_window = int(vol_window)
        self.ref_window = int(ref_window)

    @classmethod
    def spec(cls) -> StrategySpec:
        return StrategySpec(
            name="LowVolFilter",
            params={"vol_window": 20, "ref_window": 252},
            param_ranges={"vol_window": (5, 60), "ref_window": (60, 504)},
        )

    def signals(self, prices: pd.Series) -> np.ndarray:
        p = prices.values.astype(float)
        rets = np.diff(p, prepend=p[0]) / np.where(p > 0, p, 1.0)
        vol = pd.Series(rets).rolling(self.vol_window, min_periods=self.vol_window).std(ddof=0).values
        ref = pd.Series(vol).rolling(self.ref_window, min_periods=self.ref_window).median().values
        sig = np.zeros(len(p))
        for i in range(len(p)):
            if np.isnan(vol[i]) or np.isnan(ref[i]):
                continue
            if vol[i] < ref[i]:
                sig[i] = 1.0
        return sig


class _BettingAgainstBeta(Strategy):
    """Single-asset BAB stub: long when realized vol low, scaled to leverage 1."""
    def __init__(self, vol_window: int = 60):
        self.vol_window = int(vol_window)

    def signals(self, prices: pd.Series) -> np.ndarray:
        p = prices.values.astype(float)
        rets = np.diff(p, prepend=p[0]) / np.where(p > 0, p, 1.0)
        vol = pd.Series(rets).rolling(self.vol_window, min_periods=self.vol_window).std(ddof=0).values
        sig = np.zeros(len(p))
        for i in range(len(p)):
            if np.isnan(vol[i]) or vol[i] <= 0:
                continue
            # invert vol, normalize to [0,1]
            sig[i] = float(np.clip(0.01 / max(vol[i], 1e-6), 0.0, 1.0))
        return sig


class _BettingAgainstVol(Strategy):
    """Long when realized vol below long-term mean, short when above."""
    def __init__(self, vol_window: int = 20, ref_window: int = 252):
        self.vol_window = int(vol_window)
        self.ref_window = int(ref_window)

    def signals(self, prices: pd.Series) -> np.ndarray:
        p = prices.values.astype(float)
        rets = np.diff(p, prepend=p[0]) / np.where(p > 0, p, 1.0)
        vol = pd.Series(rets).rolling(self.vol_window, min_periods=self.vol_window).std(ddof=0).values
        ref = pd.Series(vol).rolling(self.ref_window, min_periods=self.ref_window).mean().values
        sig = np.zeros(len(p))
        for i in range(len(p)):
            if np.isnan(vol[i]) or np.isnan(ref[i]):
                continue
            sig[i] = 1.0 if vol[i] < ref[i] else -1.0
        return sig


class _ZScoreReversion(Strategy):
    """Mean reversion on rolling z-score of price."""
    def __init__(self, window: int = 20, entry: float = 2.0, allow_short: bool = True):
        self.window = int(window)
        self.entry = float(entry)
        self.allow_short = bool(allow_short)

    def signals(self, prices: pd.Series) -> np.ndarray:
        p = prices.values.astype(float)
        z = _zscore(p, self.window)
        sig = np.zeros(len(p))
        for i in range(len(p)):
            if np.isnan(z[i]):
                continue
            if z[i] < -self.entry:
                sig[i] = 1.0
            elif z[i] > self.entry and self.allow_short:
                sig[i] = -1.0
        return sig


class _PriceChannel(Strategy):
    """Long on close > rolling high, short on close < rolling low."""
    def __init__(self, window: int = 20, allow_short: bool = True):
        self.window = int(window)
        self.allow_short = bool(allow_short)

    def signals(self, prices: pd.Series) -> np.ndarray:
        p = prices.values.astype(float)
        s = pd.Series(p)
        hi = s.shift(1).rolling(self.window, min_periods=self.window).max().values
        lo = s.shift(1).rolling(self.window, min_periods=self.window).min().values
        sig = np.zeros(len(p))
        for i in range(len(p)):
            if np.isnan(hi[i]) or np.isnan(lo[i]):
                continue
            if p[i] > hi[i]:
                sig[i] = 1.0
            elif p[i] < lo[i] and self.allow_short:
                sig[i] = -1.0
        return sig


class _ConstantLong(Strategy):
    def signals(self, prices: pd.Series) -> np.ndarray:
        return np.ones(len(prices), dtype=float)


class _ConstantFlat(Strategy):
    def signals(self, prices: pd.Series) -> np.ndarray:
        return np.zeros(len(prices), dtype=float)


# ---- Zoo entry registration -----------------------------------------------


@dataclass
class ZooEntry:
    """A registered zoo strategy."""
    name: str
    paper_ref: str
    family: str  # momentum, value, low-vol, mean-rev, breakout, etc.
    cls: Type[Strategy]
    default_params: dict[str, Any] = field(default_factory=dict)


def _build_registry() -> list[ZooEntry]:
    entries: list[ZooEntry] = []

    # Momentum (10+)
    for L in (60, 120, 180, 252):
        entries.append(ZooEntry(
            f"momentum_{L}", f"Jegadeesh-Titman 1993 (L={L})",
            "momentum", _LookbackMomentum, {"lookback": L},
        ))
    for sk in (0, 21, 42):
        entries.append(ZooEntry(
            f"tsmom_252_skip{sk}", f"Moskowitz-Ooi-Pedersen 2012 (skip={sk})",
            "tsmomentum", TSMomentum, {"lookback": 252, "skip": sk},
        ))
    entries.append(ZooEntry(
        "tsmom_short_horizon", "MOP 2012 short", "tsmomentum",
        TSMomentum, {"lookback": 60, "skip": 0},
    ))

    # Long-only momentum variants
    for L in (40, 80, 160):
        entries.append(ZooEntry(
            f"momentum_long_only_{L}", f"momentum long-only L={L}",
            "momentum", _LookbackMomentum,
            {"lookback": L, "allow_short": False},
        ))

    # Trend-following (MA cross variants)
    for fast, slow in [(10, 50), (20, 100), (50, 200), (5, 20), (12, 26)]:
        entries.append(ZooEntry(
            f"macross_{fast}_{slow}", f"MA cross {fast}/{slow}",
            "trend", MACross, {"fast": fast, "slow": slow},
        ))

    # Donchian breakouts
    for w in (20, 55, 100, 200):
        entries.append(ZooEntry(
            f"donchian_{w}", f"Donchian {w}-day breakout (Turtles)",
            "breakout", DonchianBreakout, {"channel": w, "exit_channel": max(5, w // 4)},
        ))

    # Price channel
    for w in (10, 20, 50):
        entries.append(ZooEntry(
            f"channel_{w}", f"Price channel {w}", "breakout",
            _PriceChannel, {"window": w},
        ))

    # Mean reversion (Bollinger + z-score + RSI)
    for std in (1.5, 2.0, 2.5):
        entries.append(ZooEntry(
            f"bollinger_{std}", f"Bollinger MR {std}sigma", "mean_rev",
            BollingerMR, {"period": 20, "num_std": std},
        ))
    for w in (10, 20, 60):
        entries.append(ZooEntry(
            f"zscore_{w}", f"Z-score reversion w={w}", "mean_rev",
            _ZScoreReversion, {"window": w},
        ))
    for low, high in [(20, 80), (30, 70), (15, 85)]:
        entries.append(ZooEntry(
            f"rsi_{low}_{high}", f"RSI MR {low}/{high}", "mean_rev",
            RSIMeanRev, {"oversold": float(low), "overbought": float(high)},
        ))

    # Low-vol family
    for vw in (20, 60, 120):
        entries.append(ZooEntry(
            f"lowvol_{vw}", f"Low-vol filter w={vw}", "low_vol",
            _LowVolFilter, {"vol_window": vw},
        ))

    # BAB / BAV
    entries.append(ZooEntry(
        "bab_60", "Frazzini-Pedersen 2014 BAB (single-asset)", "low_vol",
        _BettingAgainstBeta, {"vol_window": 60},
    ))
    entries.append(ZooEntry(
        "bab_120", "Frazzini-Pedersen 2014 BAB long", "low_vol",
        _BettingAgainstBeta, {"vol_window": 120},
    ))
    entries.append(ZooEntry(
        "bav_252", "Betting against vol (single-asset)", "low_vol",
        _BettingAgainstVol, {"vol_window": 20, "ref_window": 252},
    ))

    # Dual momentum (Antonacci)
    for L in (126, 252, 378):
        entries.append(ZooEntry(
            f"dual_momentum_{L}", f"Antonacci dual momentum L={L}",
            "momentum", DualMomentum, {"lookback": L},
        ))

    # Additional momentum/threshold variants
    for thr in (0.01, 0.02, 0.05):
        entries.append(ZooEntry(
            f"momentum_thr_{int(thr*100)}", f"Momentum with threshold {thr:.0%}",
            "momentum", _LookbackMomentum,
            {"lookback": 120, "threshold": thr},
        ))

    # Additional MA cross variants
    for fast, slow in [(8, 21), (15, 60), (40, 150)]:
        entries.append(ZooEntry(
            f"macross_{fast}_{slow}", f"MA cross {fast}/{slow} extended",
            "trend", MACross, {"fast": fast, "slow": slow},
        ))

    # Additional channel variant
    entries.append(ZooEntry(
        "channel_long_only_30", "Price channel 30 long-only",
        "breakout", _PriceChannel, {"window": 30, "allow_short": False},
    ))

    # Sentinel baselines
    entries.append(ZooEntry(
        "buy_and_hold", "Buy and hold benchmark", "baseline",
        _ConstantLong, {},
    ))
    entries.append(ZooEntry(
        "all_cash", "All-cash baseline", "baseline",
        _ConstantFlat, {},
    ))
    return entries


_REGISTRY: list[ZooEntry] = _build_registry()
_REGISTRY_BY_NAME: dict[str, ZooEntry] = {e.name: e for e in _REGISTRY}


class StrategyZoo:
    """Static-style accessor over the zoo registry."""

    @staticmethod
    def list_strategies() -> list[ZooEntry]:
        return list(_REGISTRY)

    @staticmethod
    def get(name: str) -> ZooEntry:
        if name not in _REGISTRY_BY_NAME:
            raise KeyError(f"unknown zoo strategy: {name!r}")
        return _REGISTRY_BY_NAME[name]

    @staticmethod
    def instantiate(name: str, **overrides) -> Strategy:
        e = StrategyZoo.get(name)
        params = {**e.default_params, **overrides}
        return e.cls(**params)

    @staticmethod
    def families() -> list[str]:
        return sorted({e.family for e in _REGISTRY})

    @staticmethod
    def by_family(family: str) -> list[ZooEntry]:
        return [e for e in _REGISTRY if e.family == family]

    @staticmethod
    def count() -> int:
        return len(_REGISTRY)
