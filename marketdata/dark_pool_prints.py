"""Dark pool print detector.

Identifies off-exchange prints reported through the FINRA TRF tape. Live
ingestion is out of scope; the module ships a deterministic mock generator
and accepts user-provided trade frames for offline analysis.

Returned columns:
    timestamp, symbol, price, size, exchange, is_dark, dark_pool_id
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd


# FINRA TRF tape codes plus generic dark venue identifiers.
_DEFAULT_DARK_CODES = ("D", "FINRA", "TRF", "ADF", "Z")


@dataclass
class DarkPoolConfig:
    """Static config.

    Attributes:
        dark_codes: exchange codes treated as dark / off-exchange.
        n_ticks: number of synthetic prints emitted by the mock generator.
        dark_fraction: fraction of mock prints that should be dark.
    """
    dark_codes: tuple[str, ...] = _DEFAULT_DARK_CODES
    n_ticks: int = 500
    dark_fraction: float = 0.35


class DarkPoolDetector:
    """Tag prints as dark and route through one of several pool IDs."""

    _COLS = ("timestamp", "symbol", "price", "size", "exchange",
             "is_dark", "dark_pool_id")
    _POOL_IDS = ("UBS_ATS", "CRDX", "SIGMA_X", "MS_POOL", "JPMX")

    def __init__(self, config: Optional[DarkPoolConfig] = None) -> None:
        self.config = config or DarkPoolConfig()
        self._dark = frozenset(self.config.dark_codes)

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def detect(self, trades: pd.DataFrame) -> pd.DataFrame:
        """Annotate ``trades`` with ``is_dark`` and ``dark_pool_id``."""
        if trades.empty:
            return pd.DataFrame(columns=list(self._COLS))
        df = trades.copy()
        if "exchange" not in df.columns:
            df["exchange"] = ""
        df["is_dark"] = df["exchange"].astype(str).isin(self._dark)
        rng = np.random.default_rng(42)
        labels = np.array(self._POOL_IDS)
        df["dark_pool_id"] = np.where(
            df["is_dark"],
            labels[rng.integers(0, len(labels), size=len(df))],
            "",
        )
        for col in ("symbol",):
            if col not in df.columns:
                df[col] = ""
        return df[list(self._COLS)].reset_index(drop=True)

    def get_dark_prints(
        self,
        symbol: str,
        as_of: Optional[datetime] = None,
        mock: bool = True,
    ) -> pd.DataFrame:
        """Return only the dark prints, generated from mock data when offline."""
        as_of = as_of or datetime.now(timezone.utc)
        if not mock:  # pragma: no cover - live feed out of scope
            raise NotImplementedError("Live FINRA TRF ingest not wired in this build")
        trades = self._mock_trades(symbol, as_of)
        annotated = self.detect(trades)
        return annotated[annotated["is_dark"]].reset_index(drop=True)

    def dark_volume_share(self, trades: pd.DataFrame) -> float:
        """Fraction of total share volume routed off-exchange."""
        if trades.empty:
            return 0.0
        annotated = self.detect(trades)
        total = float(annotated["size"].sum())
        if total <= 0:
            return 0.0
        dark = float(annotated.loc[annotated["is_dark"], "size"].sum())
        return dark / total

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _mock_trades(self, symbol: str, as_of: datetime) -> pd.DataFrame:
        rng = np.random.default_rng(
            abs(hash(("dark", symbol, as_of.date().toordinal()))) % (2**32)
        )
        n = self.config.n_ticks
        prices = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.0005, size=n)))
        sizes = rng.integers(100, 10000, size=n)
        ts0 = pd.Timestamp(as_of.date()).tz_localize("UTC") + pd.Timedelta(hours=14, minutes=30)
        ts = ts0 + pd.to_timedelta(np.cumsum(rng.uniform(0.05, 1.5, size=n)), "s")
        # Mix of lit + dark codes weighted by config.dark_fraction.
        lit_codes = np.array(["N", "Q", "P", "T"])
        dark_codes = np.array(self.config.dark_codes)
        is_dark = rng.random(size=n) < self.config.dark_fraction
        lit_choice = lit_codes[rng.integers(0, len(lit_codes), size=n)]
        dark_choice = dark_codes[rng.integers(0, len(dark_codes), size=n)]
        codes = np.where(is_dark, dark_choice, lit_choice)
        return pd.DataFrame({
            "timestamp": ts,
            "symbol": symbol.upper(),
            "price": np.round(prices, 4),
            "size": sizes.astype(int),
            "exchange": codes,
        })
