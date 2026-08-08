"""Small causal feature cache keyed by data and code identity."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FeatureStoreKey:
    symbol: str
    dataset_sha256: str
    code_sha: str
    start: str
    end: str

    @property
    def value(self) -> str:
        payload = "|".join((self.symbol, self.dataset_sha256, self.code_sha, self.start, self.end))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class FeatureStore:
    """Cache features once per symbol while preserving close-time causality."""

    def __init__(self, *, dataset_sha256: str, code_sha: str, start: str, end: str) -> None:
        self.dataset_sha256 = dataset_sha256
        self.code_sha = code_sha
        self.start = start
        self.end = end
        self._cache: dict[str, pd.DataFrame] = {}

    def key(self, symbol: str) -> FeatureStoreKey:
        return FeatureStoreKey(symbol, self.dataset_sha256, self.code_sha, self.start, self.end)

    def get_or_build(self, symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
        if symbol not in self._cache:
            self._cache[symbol] = self._build(frame)
        return self._cache[symbol].copy()

    @staticmethod
    def _build(frame: pd.DataFrame) -> pd.DataFrame:
        source = frame.sort_index(kind="mergesort").copy()
        close = source["tr_close"] if "tr_close" in source else source["close"]
        high = source["high"] if "high" in source else close
        low = source["low"] if "low" in source else close
        volume = source["volume"] if "volume" in source else pd.Series(0.0, index=source.index)
        result = pd.DataFrame(index=source.index)
        for window in (10, 20, 50, 100, 150, 200):
            result[f"ema_{window}"] = close.ewm(span=window, adjust=False, min_periods=window).mean()
            result[f"sma_{window}"] = close.rolling(window, min_periods=window).mean()
        true_range = pd.concat(
            [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
            axis=1,
        ).max(axis=1)
        result["atr_14"] = true_range.rolling(14, min_periods=14).mean()
        result["adv_20"] = (close * volume).rolling(20, min_periods=20).mean()
        for window in (10, 20, 50, 252):
            result[f"rolling_high_{window}"] = close.rolling(window, min_periods=window).max()
            result[f"rolling_low_{window}"] = close.rolling(window, min_periods=window).min()
            spread = (
                result[f"rolling_high_{window}"] - result[f"rolling_low_{window}"]
            ).replace(0.0, np.nan)
            result[f"close_position_range_{window}"] = (
                close - result[f"rolling_low_{window}"]
            ) / spread
        for window in (20, 63, 126, 252):
            result[f"return_{window}d"] = close.pct_change(window)
        return result

    def manifest(self) -> Mapping[str, object]:
        return {
            "schema_version": "1",
            "dataset_sha256": self.dataset_sha256,
            "code_sha": self.code_sha,
            "start": self.start,
            "end": self.end,
            "symbols": sorted(self._cache),
            "keys": {symbol: self.key(symbol).value for symbol in sorted(self._cache)},
        }
