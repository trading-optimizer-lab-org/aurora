"""FRED macroeconomic series adapter.

Wraps ``fredapi`` lazily. Common series shipped by default:

    GDP        : Gross Domestic Product
    UNRATE     : Civilian Unemployment Rate
    CPIAUCSL   : Consumer Price Index, All Urban Consumers
    DFF        : Federal Funds Effective Rate
    T10Y2Y     : 10-Year Minus 2-Year Treasury Yield Spread

Series are cached as parquet under ``cache_dir`` and re-loaded across runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

DEFAULT_SERIES = ("GDP", "UNRATE", "CPIAUCSL", "DFF", "T10Y2Y")


@dataclass
class FREDConfig:
    """Static config.

    Attributes:
        api_key_env: env var holding a FRED API key.
        cache_dir: directory for parquet cache. Created on first write.
        default_series: convenience series-id tuple consumed by
            :meth:`FREDAdapter.fetch_default`.
    """
    api_key_env: str = "FRED_API_KEY"
    cache_dir: str = "data_cache_qf/fred"
    default_series: tuple[str, ...] = field(
        default_factory=lambda: DEFAULT_SERIES
    )


class FREDAdapter:
    """Fetch + cache FRED time series."""

    def __init__(self, config: Optional[FREDConfig] = None) -> None:
        self.config = config or FREDConfig()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def fetch_series(
        self,
        series_id: str,
        mock: bool = True,
        use_cache: bool = True,
    ) -> pd.Series:
        """Return a single FRED series indexed by date."""
        cache_path = self._cache_path(series_id)
        if use_cache and cache_path.exists():
            return self._read_cache(cache_path, series_id)
        s = (self._mock_series(series_id) if mock
             else self._fetch_remote(series_id))
        if use_cache:
            self._write_cache(cache_path, s)
        return s

    def fetch_default(
        self,
        mock: bool = True,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """Return DataFrame of :attr:`config.default_series`."""
        cols = {}
        for sid in self.config.default_series:
            cols[sid] = self.fetch_series(sid, mock=mock, use_cache=use_cache)
        return pd.DataFrame(cols)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _cache_path(self, series_id: str) -> Path:
        return Path(self.config.cache_dir) / f"{series_id}.parquet"

    def _read_cache(self, path: Path, series_id: str) -> pd.Series:
        df = pd.read_parquet(path)
        s = df.iloc[:, 0]
        s.name = series_id
        return s

    def _write_cache(self, path: Path, s: pd.Series) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        s.to_frame().to_parquet(path)

    def _fetch_remote(self, series_id: str) -> pd.Series:  # pragma: no cover
        import os
        try:
            from fredapi import Fred  # type: ignore
        except ImportError as e:
            raise ImportError("fredapi required for live FRED fetch") from e
        key = os.environ.get(self.config.api_key_env, "")
        if not key:
            raise RuntimeError(
                f"missing env var {self.config.api_key_env}"
            )
        fred = Fred(api_key=key)
        s = fred.get_series(series_id)
        s.name = series_id
        return s

    def _mock_series(self, series_id: str) -> pd.Series:
        rng = np.random.default_rng(abs(hash(series_id)) % (2**32))
        idx = pd.date_range("2000-01-01", periods=300, freq="MS")
        # Series-specific deterministic shape so tests can assert behaviour.
        if series_id == "UNRATE":
            base = 5.0 + np.sin(np.linspace(0, 6.28, len(idx))) * 2.0
            noise = rng.normal(0, 0.1, len(idx))
            vals = np.clip(base + noise, 2.0, 15.0)
        elif series_id == "DFF":
            vals = np.clip(rng.normal(2.0, 1.5, len(idx)), 0.0, 10.0)
        elif series_id == "T10Y2Y":
            vals = rng.normal(0.5, 0.6, len(idx))
        else:
            # Trending series for GDP / CPIAUCSL
            trend = np.linspace(100.0, 250.0, len(idx))
            vals = trend + rng.normal(0, 1.0, len(idx))
        return pd.Series(vals, index=idx, name=series_id)
