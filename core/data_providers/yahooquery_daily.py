"""yahooquery daily OHLCV provider (R155 PRICE_FALLBACK).

Same posture as yfinance: unofficial source, COMMUNITY reliability.
Lineage carries ``unofficial_source=True`` and a ``warning`` string.
The injectable client receives ``(symbol, start, end, kwargs)`` and
returns a DataFrame.
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


PROVIDER_NAME = "yahooquery_daily"
PROVIDER_URL = "https://github.com/dpguthrie/yahooquery"


def _default_client(
    symbol: str,
    start: Optional[str],
    end: Optional[str],
    kwargs: dict[str, Any],
) -> pd.DataFrame:
    """Production client wrapping ``yahooquery.Ticker.history``."""
    try:
        from yahooquery import Ticker
    except ImportError as exc:  # pragma: no cover
        raise ProviderUnavailable(
            "yahooquery_daily provider requires the optional ``yahooquery`` "
            "package; install with ``pip install yahooquery``"
        ) from exc
    t = Ticker(symbol)
    period = kwargs.get("period", "max" if start is None else None)
    if period:
        df = t.history(period=period, interval="1d")
    else:
        df = t.history(start=start, end=end, interval="1d")
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


class YahooQueryDailyProvider(BaseDataProvider):
    """yahooquery daily OHLCV adapter (PRICE_FALLBACK, COMMUNITY)."""

    name: str = PROVIDER_NAME
    version: str = "yahooquery_daily:1.0"
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
                "source": "yahooquery",
                "unofficial_source": True,
                "adjustment_posture": "ADJUSTED",
                "warning": (
                    "yahooquery is an unofficial scrape; data may be "
                    "retroactively adjusted between calls."
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
    from . import ProviderDescriptor, ProviderRole
    return ProviderDescriptor(
        name=PROVIDER_NAME,
        role=ProviderRole.PRICE_FALLBACK,
        licence_terms_url="https://github.com/dpguthrie/yahooquery/blob/master/LICENSE.txt",
        rate_limits="unofficial; throttling at vendor discretion",
        auth_required=False,
        asset_classes=("equities", "etf", "forex", "index"),
        intervals=("1d",),
        adjustment_posture="ADJUSTED",
        reliability="COMMUNITY",
    )


__all__ = ["YahooQueryDailyProvider", "PROVIDER_NAME", "PROVIDER_URL", "descriptor"]
