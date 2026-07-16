"""Decoupled current-backfill and historical point-in-time universe interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class UniverseSnapshot:
    as_of: pd.Timestamp
    symbols: tuple[str, ...]
    mode: str
    point_in_time: bool
    survivorship_limited: bool
    source: str

    def __post_init__(self) -> None:
        timestamp = pd.Timestamp(self.as_of).normalize()
        object.__setattr__(self, "as_of", timestamp)
        if timestamp >= pd.Timestamp("2021-01-01"):
            raise ValueError("universe snapshot crosses locked boundary")
        if not self.symbols:
            raise ValueError("universe snapshot cannot be empty")
        if tuple(sorted(set(self.symbols))) != self.symbols:
            raise ValueError("universe symbols must be sorted and unique")


class HistoricalPointInTimeUniverseProvider(ABC):
    """Required interface for membership known on a historical date."""

    @abstractmethod
    def snapshot_as_of(self, as_of: pd.Timestamp) -> UniverseSnapshot:
        raise NotImplementedError


class CurrentUniverseBackfillProvider:
    """Retrospective present-day symbols, explicitly not survivorship-free."""

    def __init__(self, symbols: Iterable[str], source: str = "current_public_us_universe"):
        cleaned = tuple(sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}))
        if not cleaned:
            raise ValueError("current universe symbols cannot be empty")
        self._symbols = cleaned
        self._source = source

    def snapshot_as_of(self, as_of: pd.Timestamp) -> UniverseSnapshot:
        return UniverseSnapshot(
            as_of=pd.Timestamp(as_of),
            symbols=self._symbols,
            mode="current_universe_backfill",
            point_in_time=False,
            survivorship_limited=True,
            source=self._source,
        )
