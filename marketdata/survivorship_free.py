"""Survivorship-free point-in-time universe.

Provides a CRSP-style universe API: at any historical date the membership
includes both currently-listed and delisted symbols active on that date.
The class ships with a deterministic mock dataset so unit tests can verify
delisted-name inclusion without external data.

Listing schema:
    symbol, listing_date, delisting_date (or NaT), exchange, sector
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class UniverseConfig:
    """Static config.

    Attributes:
        include_delisted: when True, return both delisted and live symbols.
        n_mock_symbols: how many synthetic symbols the mock dataset contains.
        mock_seed: seed used by the deterministic mock generator.
    """
    include_delisted: bool = True
    n_mock_symbols: int = 50
    mock_seed: int = 42


class SurvivorshipFreeUniverse:
    """Point-in-time membership across listed + delisted names."""

    _COLS = ("symbol", "listing_date", "delisting_date", "exchange", "sector")
    _SECTORS = ("Tech", "Financials", "Health", "Energy", "Industrials",
                "Consumer", "Utilities", "Materials", "Comm")
    _EXCHANGES = ("NYSE", "NASDAQ", "AMEX")

    def __init__(self, config: Optional[UniverseConfig] = None) -> None:
        self.config = config or UniverseConfig()
        self._listings: Optional[pd.DataFrame] = None

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def load_listings(self, listings: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """Load (or mock) the master listing table.

        ``listings`` overrides the mock when provided.
        """
        if listings is not None:
            df = listings.copy()
            for col in ("listing_date", "delisting_date"):
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors="coerce")
            self._listings = df.reset_index(drop=True)
            return self._listings
        self._listings = self._mock_listings()
        return self._listings

    def members_as_of(self, as_of: pd.Timestamp) -> pd.DataFrame:
        """Return listings active on ``as_of``.

        A symbol is considered active when ``listing_date <= as_of`` and
        ``delisting_date is NaT or delisting_date >= as_of``.
        """
        if self._listings is None:
            self.load_listings()
        as_of = pd.Timestamp(as_of)
        assert self._listings is not None
        df = self._listings
        active_listed = df["listing_date"] <= as_of
        active_not_delisted = df["delisting_date"].isna() | (df["delisting_date"] >= as_of)
        out = df[active_listed & active_not_delisted].reset_index(drop=True)
        if not self.config.include_delisted:
            out = out[out["delisting_date"].isna()].reset_index(drop=True)
        return out[list(self._COLS)]

    def delisted_in_window(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> pd.DataFrame:
        """Symbols delisted within ``[start, end]`` (inclusive)."""
        if self._listings is None:
            self.load_listings()
        assert self._listings is not None
        df = self._listings
        mask = df["delisting_date"].notna() & (
            df["delisting_date"].between(pd.Timestamp(start), pd.Timestamp(end))
        )
        return df.loc[mask, list(self._COLS)].reset_index(drop=True)

    def n_active(self, as_of: pd.Timestamp) -> int:
        """Convenience helper: count of names active on ``as_of``."""
        return int(len(self.members_as_of(as_of)))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _mock_listings(self) -> pd.DataFrame:
        rng = np.random.default_rng(self.config.mock_seed)
        n = self.config.n_mock_symbols
        symbols = [f"SYM{i:03d}" for i in range(n)]
        # Listings spread over 1990-2015.
        listing_offsets = rng.integers(0, 365 * 25, size=n)
        listings = pd.Timestamp("1990-01-01") + pd.to_timedelta(listing_offsets, unit="D")
        # ~30% of symbols delisted between listing+1y and 2024.
        delisted_mask = rng.random(size=n) < 0.30
        delisting = []
        for i in range(n):
            if not delisted_mask[i]:
                delisting.append(pd.NaT)
                continue
            min_date = listings[i] + pd.Timedelta(days=365)
            max_date = pd.Timestamp("2024-12-31")
            if min_date >= max_date:
                delisting.append(pd.NaT)
                continue
            span_days = (max_date - min_date).days
            delisting.append(min_date + pd.Timedelta(days=int(rng.integers(0, span_days))))
        return pd.DataFrame({
            "symbol": symbols,
            "listing_date": listings,
            "delisting_date": delisting,
            "exchange": rng.choice(self._EXCHANGES, size=n),
            "sector": rng.choice(self._SECTORS, size=n),
        })
