"""Satellite / geospatial alt-data adapter (stub).

Production providers (Planet, RS Metrics, Orbital Insight) require commercial
contracts and per-AOI delivery pipelines, so this module ships only:

- a typed dataclass interface for AOIs (parking lots, oil tanks)
- a deterministic mock data generator for tests and offline development
- a placeholder ``_fetch_planet`` path that documents the wiring for callers
  who later add real credentials

Returned columns:
    date, aoi_id, aoi_type, metric, value
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import numpy as np
import pandas as pd

_VALID_AOI_TYPES = frozenset({"parking_lot", "oil_tank", "shipping_port"})


@dataclass
class AOI:
    """Area of interest descriptor.

    Attributes:
        aoi_id: unique id used as join key.
        aoi_type: 'parking_lot' | 'oil_tank' | 'shipping_port'.
        lat: degrees, WGS84.
        lon: degrees, WGS84.
        capacity: nominal capacity (cars, barrels, TEU). Used by the mock
            generator to bound returned ``value``.
    """
    aoi_id: str
    aoi_type: str
    lat: float
    lon: float
    capacity: float = 1000.0

    def __post_init__(self) -> None:
        if self.aoi_type not in _VALID_AOI_TYPES:
            raise ValueError(
                f"unknown aoi_type {self.aoi_type!r}, "
                f"valid={sorted(_VALID_AOI_TYPES)}"
            )


@dataclass
class SatelliteConfig:
    """Static config.

    Attributes:
        provider: 'planet' (placeholder for real integrations).
        api_key_env: env var with the provider API key.
        cadence_days: nominal revisit cadence for the mock generator.
    """
    provider: str = "planet"
    api_key_env: str = "PLANET_API_KEY"
    cadence_days: int = 1


class SatelliteAdapter:
    """Geo time-series for parking lot fill, tank levels, port congestion."""

    _COLS = ("date", "aoi_id", "aoi_type", "metric", "value")

    def __init__(self, config: Optional[SatelliteConfig] = None) -> None:
        self.config = config or SatelliteConfig()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def get_metrics(
        self,
        aois: Iterable[AOI],
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        mock: bool = True,
    ) -> pd.DataFrame:
        """Return long-format geo metric series for ``aois``."""
        end = end or datetime.now(timezone.utc)
        start = start or (end - timedelta(days=14))
        if start >= end:
            raise ValueError("start must be before end")
        aoi_list = list(aois)
        if not aoi_list:
            return pd.DataFrame(columns=list(self._COLS))
        if mock:
            return self._mock(aoi_list, start, end)
        return self._fetch_planet(aoi_list, start, end)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _fetch_planet(
        self,
        aois: list[AOI],
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:  # pragma: no cover - placeholder
        import os
        if not os.environ.get(self.config.api_key_env, ""):
            raise RuntimeError(
                f"missing env var {self.config.api_key_env}"
            )
        # Real integration would post AOI footprints to the Planet Tasking
        # API, then derive metrics via a downstream CV pipeline. Out of scope
        # for this package; we return an empty frame so the call shape stays
        # stable.
        return pd.DataFrame(columns=list(self._COLS))

    def _mock(
        self,
        aois: list[AOI],
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        days = pd.date_range(start.date(), end.date(),
                             freq=f"{max(self.config.cadence_days, 1)}D")
        rows = []
        for aoi in aois:
            rng = np.random.default_rng(abs(hash(aoi.aoi_id)) % (2**32))
            metric = self._metric_for(aoi.aoi_type)
            base = aoi.capacity * rng.uniform(0.3, 0.8)
            for d in days:
                noise = rng.normal(0, aoi.capacity * 0.05)
                val = float(np.clip(base + noise, 0.0, aoi.capacity))
                rows.append({
                    "date": d,
                    "aoi_id": aoi.aoi_id,
                    "aoi_type": aoi.aoi_type,
                    "metric": metric,
                    "value": val,
                })
        return pd.DataFrame(rows, columns=list(self._COLS))

    @staticmethod
    def _metric_for(aoi_type: str) -> str:
        return {
            "parking_lot": "fill_pct_count",
            "oil_tank": "barrels",
            "shipping_port": "container_count",
        }[aoi_type]
