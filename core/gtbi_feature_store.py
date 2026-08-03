"""Authoritative, I/O-free feature cache used by GTBI evaluators.

The module deliberately accepts the scientific calculation callbacks from the
consumer.  This keeps the cache reusable without duplicating OHLCV preparation,
RSI, or market-regime semantics from the frozen GTBI evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import time
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


PrepareOhlcv = Callable[[pd.DataFrame], pd.DataFrame]
RsiCalculator = Callable[[pd.Series, int], pd.Series]
MarketTrendCalculator = Callable[[pd.Index, pd.DataFrame, Any], pd.Series]


def exact_float_cache_token(value: float) -> str:
    """Represent an effective float exactly instead of merging nearby values."""

    return float(value).hex()


def frame_content_identity(
    frame: pd.DataFrame,
    columns: Iterable[str] | None = None,
) -> str:
    """Return a content identity that detects in-place frame changes."""

    selected_columns = [column for column in (columns or frame.columns) if column in frame.columns]
    selected = frame.loc[:, selected_columns] if selected_columns else frame
    digest = hashlib.sha256()
    digest.update(json.dumps(selected_columns, separators=(",", ":")).encode("utf-8"))
    digest.update(
        pd.util.hash_pandas_object(selected, index=True, categorize=False)
        .to_numpy(dtype=np.uint64, copy=False)
        .tobytes()
    )
    return digest.hexdigest()


def benchmark_cache_identity(frame: pd.DataFrame) -> str:
    """Bind benchmark-derived values to the benchmark's current content."""

    return frame_content_identity(frame, ("date", "close"))


class SignalPrimitiveStore:
    """Lazy numeric and boolean primitive cache for one prepared symbol."""

    def __init__(
        self,
        frame: pd.DataFrame,
        benchmark_prices: pd.DataFrame,
        *,
        prepare_ohlcv: PrepareOhlcv,
        rsi_calculator: RsiCalculator,
        market_trend_calculator: MarketTrendCalculator,
        price_columns: Sequence[str],
    ) -> None:
        self._prepare_ohlcv = prepare_ohlcv
        self._rsi_calculator = rsi_calculator
        self._market_trend_calculator = market_trend_calculator
        self._price_columns = tuple(price_columns)
        self.frame = prepare_ohlcv(frame)
        self.benchmark = prepare_ohlcv(benchmark_prices)
        self.close = self.frame["close"] if not self.frame.empty else pd.Series(dtype=float)
        self.high = self.frame["high"] if not self.frame.empty else pd.Series(dtype=float)
        self.low = self.frame["low"] if not self.frame.empty else pd.Series(dtype=float)
        self.volume = (
            self.frame["volume"].fillna(0.0) if not self.frame.empty else pd.Series(dtype=float)
        )
        self.index = self.frame.index
        self.frame_identity = frame_content_identity(self.frame, self._price_columns)
        self.benchmark_identity = benchmark_cache_identity(self.benchmark)
        self.cache: dict[tuple[Any, ...], pd.Series] = {}
        self.entry_cache: dict[tuple[Any, ...], pd.Series] = {}
        self.market_cache: dict[tuple[Any, ...], pd.Series] = {}

    def const(self, value: bool) -> pd.Series:
        return pd.Series(bool(value), index=self.index, dtype=bool)

    def sma(self, window: int) -> pd.Series:
        key = ("sma", int(window))
        if key not in self.cache:
            self.cache[key] = self.close.rolling(int(window), min_periods=int(window)).mean()
        return self.cache[key]

    def ema(self, window: int) -> pd.Series:
        key = ("ema", int(window))
        if key not in self.cache:
            self.cache[key] = self.close.ewm(
                span=int(window), adjust=False, min_periods=int(window)
            ).mean()
        return self.cache[key]

    def adv(self, window: int, *, min_periods: int | None = None) -> pd.Series:
        key = ("adv", int(window), min_periods)
        if key not in self.cache:
            self.cache[key] = self.volume.rolling(
                int(window),
                min_periods=min_periods or min(int(window), len(self.frame)),
            ).mean()
        return self.cache[key]

    def rolling_high(
        self,
        window: int,
        *,
        shift: int = 0,
        min_periods: int | None = None,
    ) -> pd.Series:
        key = ("rolling_high", int(window), int(shift), min_periods)
        if key not in self.cache:
            source = self.high.shift(int(shift)) if shift else self.high
            self.cache[key] = source.rolling(
                int(window),
                min_periods=min_periods or min(int(window), len(self.frame)),
            ).max()
        return self.cache[key]

    def rolling_low(
        self,
        window: int,
        *,
        shift: int = 0,
        min_periods: int | None = None,
    ) -> pd.Series:
        key = ("rolling_low", int(window), int(shift), min_periods)
        if key not in self.cache:
            source = self.low.shift(int(shift)) if shift else self.low
            self.cache[key] = source.rolling(
                int(window),
                min_periods=min_periods or min(int(window), len(self.frame)),
            ).min()
        return self.cache[key]

    def rsi(self, period: int) -> pd.Series:
        key = ("rsi", int(period))
        if key not in self.cache:
            self.cache[key] = self._rsi_calculator(self.close, int(period)).fillna(50.0)
        return self.cache[key]

    def pct_return(self, lookback: int) -> pd.Series:
        key = ("pct_return", int(lookback))
        if key not in self.cache:
            self.cache[key] = self.close / self.close.shift(int(lookback)) - 1.0
        return self.cache[key]

    def adr(self, window: int) -> pd.Series:
        key = ("adr", int(window))
        if key not in self.cache:
            self.cache[key] = (
                self.close.pct_change().abs().rolling(int(window), min_periods=int(window)).mean()
            )
        return self.cache[key]

    def spy_close(self) -> pd.Series:
        key = ("spy_close", self.benchmark_identity)
        if key not in self.cache:
            self.cache[key] = (
                self.benchmark["close"].reindex(self.index).ffill()
                if not self.benchmark.empty
                else pd.Series(np.nan, index=self.index)
            )
        return self.cache[key]

    def rs_line(self) -> pd.Series:
        key = ("rs_line", self.benchmark_identity)
        if key not in self.cache:
            self.cache[key] = (
                pd.Series(np.nan, index=self.index)
                if self.benchmark.empty
                else self.close / self.spy_close().replace(0.0, np.nan)
            )
        return self.cache[key]

    def rs_avg(self, window: int) -> pd.Series:
        key = ("rs_avg", int(window), self.benchmark_identity)
        if key not in self.cache:
            self.cache[key] = (
                self.rs_line()
                .rolling(int(window), min_periods=min(int(window), len(self.frame)))
                .mean()
            )
        return self.cache[key]

    def rs_high(self, window: int) -> pd.Series:
        key = ("rs_high", int(window), self.benchmark_identity)
        if key not in self.cache:
            self.cache[key] = (
                self.rs_line()
                .rolling(int(window), min_periods=min(int(window), len(self.frame)))
                .max()
            )
        return self.cache[key]

    def close_gt_ema(self, window: int) -> pd.Series:
        key = ("close_gt_ema", int(window))
        if key not in self.cache:
            self.cache[key] = self.close > self.ema(int(window))
        return self.cache[key]

    def ema_gt_ema(self, fast: int, slow: int) -> pd.Series:
        key = ("ema_gt_ema", int(fast), int(slow))
        if key not in self.cache:
            self.cache[key] = self.ema(int(fast)) > self.ema(int(slow))
        return self.cache[key]

    def close_breaks_high(self, window: int) -> pd.Series:
        key = ("close_breaks_high", int(window))
        if key not in self.cache:
            self.cache[key] = self.close > self.rolling_high(
                int(window), shift=1, min_periods=int(window)
            )
        return self.cache[key]

    def volume_gt_adv(self, window: int, multiple: float) -> pd.Series:
        key = ("volume_gt_adv", int(window), exact_float_cache_token(multiple))
        if key not in self.cache:
            self.cache[key] = self.volume > self.adv(int(window)) * float(multiple)
        return self.cache[key]

    def rs_ratio_gt_ma(self, window: int) -> pd.Series:
        key = ("rs_ratio_gt_ma", int(window), self.benchmark_identity)
        if key not in self.cache:
            self.cache[key] = (
                self.const(True)
                if self.benchmark.empty
                else self.rs_line() > self.rs_avg(int(window))
            )
        return self.cache[key]

    def market_trend(self, config: Any) -> pd.Series:
        key = (
            "market_trend",
            self.frame_identity,
            self.benchmark_identity,
            int(config.market_ma_days),
            int(config.market_momentum_days),
            bool(config.strict_market_filter),
        )
        if key not in self.market_cache:
            self.market_cache[key] = self._market_trend_calculator(
                self.index, self.benchmark, config
            )
        return self.market_cache[key]


@dataclass(frozen=True)
class FeatureStore:
    """Immutable per-job index of content-bound per-symbol primitive stores."""

    symbol_frames: Mapping[str, pd.DataFrame]
    benchmark_prices: pd.DataFrame
    primitive_stores: Mapping[str, SignalPrimitiveStore]
    prepare_ohlcv: PrepareOhlcv = field(repr=False, compare=False)
    rsi_calculator: RsiCalculator = field(repr=False, compare=False)
    market_trend_calculator: MarketTrendCalculator = field(repr=False, compare=False)
    price_columns: tuple[str, ...] = field(repr=False, compare=False)
    seconds_build: float = 0.0
    enabled: bool = True

    def primitives_for(
        self,
        symbol: str,
        frame: pd.DataFrame,
        benchmark_prices: pd.DataFrame,
    ) -> SignalPrimitiveStore:
        prepared = self.prepare_ohlcv(frame)
        benchmark = self.prepare_ohlcv(benchmark_prices)
        frame_identity = frame_content_identity(prepared, self.price_columns)
        benchmark_identity = benchmark_cache_identity(benchmark)
        existing = self.primitive_stores.get(str(symbol)) if self.enabled else None
        if (
            existing is not None
            and existing.frame_identity == frame_identity
            and existing.benchmark_identity == benchmark_identity
        ):
            return existing
        return SignalPrimitiveStore(
            prepared,
            benchmark,
            prepare_ohlcv=self.prepare_ohlcv,
            rsi_calculator=self.rsi_calculator,
            market_trend_calculator=self.market_trend_calculator,
            price_columns=self.price_columns,
        )


def build_feature_store(
    symbol_frames: Mapping[str, pd.DataFrame],
    benchmark_prices: pd.DataFrame,
    *,
    prepare_ohlcv: PrepareOhlcv,
    rsi_calculator: RsiCalculator,
    market_trend_calculator: MarketTrendCalculator,
    price_columns: Sequence[str],
    enabled: bool = True,
) -> FeatureStore:
    """Build one content-bound feature store without any I/O or lookahead."""

    start = time.perf_counter()
    benchmark = prepare_ohlcv(benchmark_prices)
    prepared_frames = {str(symbol): prepare_ohlcv(frame) for symbol, frame in symbol_frames.items()}
    primitive_stores = (
        {
            symbol: SignalPrimitiveStore(
                frame,
                benchmark,
                prepare_ohlcv=prepare_ohlcv,
                rsi_calculator=rsi_calculator,
                market_trend_calculator=market_trend_calculator,
                price_columns=price_columns,
            )
            for symbol, frame in prepared_frames.items()
        }
        if enabled
        else {}
    )
    return FeatureStore(
        symbol_frames=MappingProxyType(prepared_frames),
        benchmark_prices=benchmark,
        primitive_stores=MappingProxyType(primitive_stores),
        prepare_ohlcv=prepare_ohlcv,
        rsi_calculator=rsi_calculator,
        market_trend_calculator=market_trend_calculator,
        price_columns=tuple(price_columns),
        seconds_build=float(time.perf_counter() - start),
        enabled=bool(enabled),
    )
