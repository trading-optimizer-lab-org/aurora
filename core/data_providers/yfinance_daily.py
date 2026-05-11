"""yfinance daily OHLCV provider (R155 PRICE_FALLBACK).

yfinance is an *unofficial* scrape of Yahoo Finance. This provider
returns the OHLCV daily contract but tags every produced lineage with
``unofficial_source=True`` so downstream consumers cannot accidentally
treat it as authoritative.

The provider takes an injectable ``client`` callable that receives
``(symbol, start, end, kwargs)`` and returns a DataFrame with at least
``Open``, ``High``, ``Low``, ``Close``, ``Volume`` columns and a
DatetimeIndex. Tests mock this callable; production wraps
``yfinance.download``.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

import pandas as pd

from . import BaseDataProvider, ProviderUnavailable
from ._free_bulk_common import (
    OHLCV_DAILY_V1,
    FreeBulkLineage,
    assert_against_contract,
    build_lineage,
    empty_ohlcv_frame,
    normalise_ohlcv_frame,
    utcnow_iso,
)

_log = logging.getLogger(__name__)


PROVIDER_NAME = "yfinance_daily"
PROVIDER_URL = "https://github.com/ranaroussi/yfinance"


# ---------------------------------------------------------------------------
# Default client (production).
# ---------------------------------------------------------------------------


def _default_client(
    symbol: str,
    start: Optional[str],
    end: Optional[str],
    kwargs: dict[str, Any],
) -> pd.DataFrame:
    """Production client wrapping ``yfinance.download``.

    Tests must inject a deterministic client.
    """
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover
        raise ProviderUnavailable(
            "yfinance_daily provider requires the optional ``yfinance`` "
            "package; install with ``pip install yfinance``"
        ) from exc
    df = yf.download(
        symbol,
        start=start or "1990-01-01",
        end=end or pd.Timestamp.today().strftime("%Y-%m-%d"),
        auto_adjust=bool(kwargs.get("auto_adjust", True)),
        progress=False,
    )
    if df is None:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        # yfinance returns a (field, ticker) MultiIndex when ``symbol`` is
        # a list. Flatten by taking field-level columns.
        df = df.droplevel(1, axis=1)
    return df


# ---------------------------------------------------------------------------
# Provider class.
# ---------------------------------------------------------------------------


class YFinanceDailyProvider(BaseDataProvider):
    """yfinance daily OHLCV adapter (PRICE_FALLBACK, COMMUNITY)."""

    name: str = PROVIDER_NAME
    version: str = "yfinance_daily:1.0"
    point_in_time: bool = False
    tier_permission: str = "IS_TRAIN"
    schema_version: str = "1.0"

    def __init__(
        self,
        client: Optional[
            Callable[[str, Optional[str], Optional[str], dict[str, Any]], pd.DataFrame]
        ] = None,
    ) -> None:
        self._client = client or _default_client

    def fetch_daily(
        self,
        symbol: str,
        *,
        start: Optional[str] = None,
        end: Optional[str] = None,
        **kwargs: Any,
    ) -> tuple[pd.DataFrame, FreeBulkLineage]:
        """Fetch daily OHLCV with explicit ``unofficial_source`` provenance."""
        if not symbol or not isinstance(symbol, str):
            raise ValueError("symbol must be a non-empty string")
        raw = self._client(symbol, start, end, dict(kwargs))
        if raw is None or len(raw) == 0:
            df = empty_ohlcv_frame()
        else:
            df = normalise_ohlcv_frame(raw)
        snapshot_hash = assert_against_contract(df, OHLCV_DAILY_V1)
        lineage = build_lineage(
            df=df,
            contract=OHLCV_DAILY_V1,
            provider_name=self.name,
            provider_url=PROVIDER_URL,
            retrieved_at_iso=utcnow_iso(),
            auth_mode="none",
            query_params={"symbol": symbol, "start": start, "end": end, **kwargs},
            snapshot_hash=snapshot_hash,
            symbol_count=1,
            extra={
                "reliability": "COMMUNITY",
                "source": "yfinance",
                "unofficial_source": True,
                "adjustment_posture": "ADJUSTED",
                "warning": (
                    "yfinance is an unofficial scrape; data may be retroactively "
                    "adjusted between calls."
                ),
            },
        )
        return df, lineage

    def _fetch_raw(self, symbol, start, end, **kwargs):
        df, _ = self.fetch_daily(
            symbol,
            start=start.strftime("%Y-%m-%d") if start is not None else None,
            end=end.strftime("%Y-%m-%d") if end is not None else None,
            **kwargs,
        )
        return df


def descriptor():
    """Return the registry-friendly :class:`ProviderDescriptor`."""
    from . import ProviderDescriptor, ProviderRole
    return ProviderDescriptor(
        name=PROVIDER_NAME,
        role=ProviderRole.PRICE_FALLBACK,
        licence_terms_url="https://github.com/ranaroussi/yfinance/blob/main/LICENSE.txt",
        rate_limits="unofficial; throttling at vendor discretion",
        auth_required=False,
        asset_classes=("equities", "etf", "forex", "index"),
        intervals=("1d",),
        adjustment_posture="ADJUSTED",
        reliability="COMMUNITY",
    )


__all__ = ["YFinanceDailyProvider", "PROVIDER_NAME", "PROVIDER_URL", "descriptor"]
