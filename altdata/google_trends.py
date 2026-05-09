"""Google Trends search-volume adapter.

Wraps ``pytrends`` lazily. Returns a daily series of search volume per keyword
plus a rolling z-score so callers can use it as an attention/momentum signal.

Tests use ``mock=True`` to avoid network and the periodic 429s that pytrends
incurs against trends.google.com.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import numpy as np
import pandas as pd


@dataclass
class GoogleTrendsConfig:
    """Static config.

    Attributes:
        timeframe: pytrends timeframe string (e.g. ``'today 3-m'`` or
            ``'2024-01-01 2024-12-31'``).
        geo: ISO geo code (default ``''`` for worldwide).
        zscore_window: rolling window in days for z-score computation.
        timeout_s: request timeout in seconds.
    """
    timeframe: str = "today 3-m"
    geo: str = ""
    zscore_window: int = 30
    timeout_s: float = 10.0


class GoogleTrendsAdapter:
    """Search-volume z-score per keyword."""

    _COLS = ("date", "keyword", "search_volume", "zscore")

    def __init__(self, config: Optional[GoogleTrendsConfig] = None) -> None:
        self.config = config or GoogleTrendsConfig()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def get_interest(
        self,
        keywords: Iterable[str],
        mock: bool = True,
    ) -> pd.DataFrame:
        """Return long-format DataFrame of search volume + z-score."""
        kws = [k for k in keywords if k]
        if not kws:
            return pd.DataFrame(columns=list(self._COLS))
        wide = (self._mock_wide(kws) if mock
                else self._fetch_wide(kws))
        return self._to_long_with_zscore(wide)

    def compute_zscore(self, s: pd.Series) -> pd.Series:
        """Rolling z-score with the configured window."""
        win = max(self.config.zscore_window, 2)
        roll = s.rolling(win, min_periods=2)
        mean = roll.mean()
        std = roll.std(ddof=0).replace(0.0, np.nan)
        z = (s - mean) / std
        return z.fillna(0.0)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _to_long_with_zscore(self, wide: pd.DataFrame) -> pd.DataFrame:
        if wide.empty:
            return pd.DataFrame(columns=list(self._COLS))
        rows = []
        for kw in wide.columns:
            s = wide[kw].astype(float)
            z = self.compute_zscore(s)
            for d, v, zv in zip(s.index, s.values, z.values):
                rows.append({
                    "date": pd.Timestamp(d),
                    "keyword": kw,
                    "search_volume": float(v),
                    "zscore": float(zv),
                })
        return pd.DataFrame(rows, columns=list(self._COLS))

    def _fetch_wide(
        self,
        keywords: list[str],
    ) -> pd.DataFrame:  # pragma: no cover - network
        try:
            from pytrends.request import TrendReq
        except ImportError as e:
            raise ImportError("pytrends required for live Google Trends") from e
        pt = TrendReq(timeout=self.config.timeout_s)
        # pytrends supports up to 5 kw per build_payload call.
        out = []
        for i in range(0, len(keywords), 5):
            chunk = keywords[i:i + 5]
            pt.build_payload(
                kw_list=chunk,
                timeframe=self.config.timeframe,
                geo=self.config.geo,
            )
            df = pt.interest_over_time()
            if "isPartial" in df.columns:
                df = df.drop(columns=["isPartial"])
            out.append(df)
        if not out:
            return pd.DataFrame()
        return pd.concat(out, axis=1)

    def _mock_wide(self, keywords: list[str]) -> pd.DataFrame:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=120)
        idx = pd.date_range(start, end, freq="D")
        cols = {}
        for kw in keywords:
            rng = np.random.default_rng(abs(hash(("trends", kw))) % (2**32))
            base = rng.uniform(20, 80)
            walk = np.cumsum(rng.normal(0, 3, len(idx)))
            vals = np.clip(base + walk, 0.0, 100.0)
            cols[kw] = vals
        return pd.DataFrame(cols, index=idx)
