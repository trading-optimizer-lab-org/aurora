"""FRED macro daily provider (R155 MACRO).

Wraps an injectable client that returns a pandas Series for a FRED
series id. In production the client uses ``fredapi`` (already wrapped
by :mod:`aurora.altdata.fred_macro`); tests inject a deterministic
fixture loader.

Output: a DataFrame matching :data:`MACRO_DAILY_V1` (columns
``timestamp``, ``value``). asset_class is recorded in lineage as
``MACRO`` so downstream consumers do not confuse macro series with
ticker-level OHLCV.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Mapping, Optional

import pandas as pd

from . import BaseDataProvider, ProviderUnavailable
from ._free_bulk_common import (
    MACRO_DAILY_V1,
    FreeBulkLineage,
    assert_against_contract,
    build_lineage,
    utcnow_iso,
)

_log = logging.getLogger(__name__)


PROVIDER_NAME = "fred_macro"
PROVIDER_URL = "https://fred.stlouisfed.org/"


def _default_client(
    series_id: str, kwargs: Mapping[str, Any]
) -> pd.Series:
    """Production client: route through the existing altdata adapter.

    The altdata adapter already handles caching + API key resolution.
    Tests must inject their own client to avoid network use.
    """
    try:
        from aurora.altdata.fred_macro import FREDAdapter, FREDConfig
    except Exception as exc:  # pragma: no cover
        raise ProviderUnavailable(
            "fred_macro provider requires aurora.altdata.fred_macro"
        ) from exc
    cfg = FREDConfig()
    adapter = FREDAdapter(cfg)
    series = adapter.fetch_series(series_id)
    if not isinstance(series, pd.Series):
        raise ProviderUnavailable(
            f"fred_macro: adapter returned {type(series).__name__}, expected Series"
        )
    return series


class FREDDailyProvider(BaseDataProvider):
    """FRED macro provider returning a single-value DataFrame."""

    name: str = PROVIDER_NAME
    version: str = "fred_macro:1.0"
    point_in_time: bool = True
    tier_permission: str = "ANY"
    schema_version: str = "1.0"

    def __init__(
        self,
        client: Optional[Callable[[str, Mapping[str, Any]], pd.Series]] = None,
    ) -> None:
        self._client = client or _default_client

    def fetch_series(
        self,
        series_id: str,
        **kwargs: Any,
    ) -> tuple[pd.DataFrame, FreeBulkLineage]:
        if not series_id or not isinstance(series_id, str):
            raise ValueError("series_id must be a non-empty string")
        series = self._client(series_id, dict(kwargs))
        df = self._series_to_frame(series)
        snapshot_hash = assert_against_contract(df, MACRO_DAILY_V1)
        auth_mode = "api_key" if os.environ.get("FRED_API_KEY") else "none"
        lineage = build_lineage(
            df=df,
            contract=MACRO_DAILY_V1,
            provider_name=self.name,
            provider_url=PROVIDER_URL,
            retrieved_at_iso=utcnow_iso(),
            auth_mode=auth_mode,
            query_params={"series_id": series_id, **kwargs},
            snapshot_hash=snapshot_hash,
            symbol_count=1,
            extra={
                "reliability": "OFFICIAL",
                "source": "FRED",
                "asset_class": "MACRO",
                "series_id": series_id,
                "library": "macro_daily",
            },
        )
        return df, lineage

    @staticmethod
    def _series_to_frame(series: pd.Series) -> pd.DataFrame:
        if series is None or len(series) == 0:
            return pd.DataFrame(columns=["timestamp", "value"])
        idx = series.index
        if isinstance(idx, pd.DatetimeIndex):
            if idx.tz is None:
                idx = idx.tz_localize("UTC")
            else:
                idx = idx.tz_convert("UTC")
        else:
            idx = pd.to_datetime(idx, utc=True, errors="coerce")
        df = pd.DataFrame({
            "timestamp": idx,
            "value": pd.to_numeric(series.values, errors="coerce"),
        })
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    def _fetch_raw(self, symbol, start, end, **kwargs):  # pragma: no cover
        df, _ = self.fetch_series(symbol, **kwargs)
        return df


def descriptor():
    from . import ProviderDescriptor, ProviderRole
    return ProviderDescriptor(
        name=PROVIDER_NAME,
        role=ProviderRole.MACRO,
        licence_terms_url="https://fred.stlouisfed.org/legal/",
        rate_limits="120 requests/min/key",
        auth_required=False,
        asset_classes=("macro",),
        intervals=("1d",),
        adjustment_posture="RAW",
        reliability="OFFICIAL",
    )


__all__ = ["FREDDailyProvider", "PROVIDER_NAME", "PROVIDER_URL", "descriptor"]
