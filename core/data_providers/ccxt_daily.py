"""CCXT daily OHLCV provider (R155 CRYPTO_MULTI, optional).

Thin role-aware wrapper around the existing :class:`CCXTProvider` so the
R155 registry has a CRYPTO_MULTI entry without duplicating the pagination
logic. The wrapper is *opt-in* -- it skips registration cleanly when
``ccxt`` is not installed.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd

from . import ProviderUnavailable
from ._free_bulk_common import (
    OHLCV_DAILY_V1,
    FreeBulkLineage,
    assert_against_contract,
    build_lineage,
    normalise_ohlcv_frame,
    utcnow_iso,
)

_log = logging.getLogger(__name__)


PROVIDER_NAME = "ccxt_daily"
PROVIDER_URL = "https://github.com/ccxt/ccxt"


def is_ccxt_available() -> bool:
    """Return True when the optional ``ccxt`` package is importable."""
    try:
        import ccxt  # noqa: F401
        return True
    except Exception:
        return False


class CCXTDailyProvider:
    """Role-aware wrapper that defers fetch to :class:`CCXTProvider`."""

    name: str = PROVIDER_NAME
    version: str = "ccxt_daily:1.0"
    point_in_time: bool = False
    tier_permission: str = "IS_TRAIN"
    schema_version: str = "1.0"

    def __init__(self, exchange_id: str = "binance") -> None:
        if not is_ccxt_available():
            raise ProviderUnavailable(
                "ccxt_daily provider requires the optional ``ccxt`` package; "
                "install with ``pip install ccxt``"
            )
        from .ccxt_provider import CCXTProvider
        self._inner = CCXTProvider(exchange_id=exchange_id)
        self.exchange_id = exchange_id

    def is_point_in_time(self) -> bool:
        return self._inner.is_point_in_time()

    def supported_tiers(self) -> set[str]:
        return self._inner.supported_tiers()

    def fetch_daily(
        self,
        symbol: str,
        *,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> tuple[pd.DataFrame, FreeBulkLineage]:
        ds = self._inner.fetch(
            symbol,
            pd.Timestamp(start) if start else None,
            pd.Timestamp(end) if end else None,
            timeframe="1d",
        )
        df = normalise_ohlcv_frame(ds.data)
        snapshot_hash = assert_against_contract(df, OHLCV_DAILY_V1)
        lineage = build_lineage(
            df=df,
            contract=OHLCV_DAILY_V1,
            provider_name=self.name,
            provider_url=PROVIDER_URL,
            retrieved_at_iso=utcnow_iso(),
            auth_mode="none",
            query_params={
                "symbol": symbol,
                "start": start,
                "end": end,
                "exchange_id": self.exchange_id,
            },
            snapshot_hash=snapshot_hash,
            symbol_count=1,
            extra={
                "reliability": "COMMUNITY",
                "source": "ccxt",
                "exchange_id": self.exchange_id,
                "adjustment_posture": "RAW",
            },
        )
        return df, lineage

    def fetch(self, symbol, start, end, **kwargs: Any):
        return self._inner.fetch(symbol, start, end, **kwargs)


def descriptor():
    from . import ProviderDescriptor, ProviderRole
    return ProviderDescriptor(
        name=PROVIDER_NAME,
        role=ProviderRole.CRYPTO_MULTI,
        licence_terms_url="https://github.com/ccxt/ccxt/blob/master/LICENSE.txt",
        rate_limits="depends on exchange (rateLimit honoured by ccxt)",
        auth_required=False,
        asset_classes=("crypto",),
        intervals=("1d", "1h", "1m"),
        adjustment_posture="RAW",
        reliability="COMMUNITY",
    )


__all__ = [
    "CCXTDailyProvider",
    "PROVIDER_NAME",
    "PROVIDER_URL",
    "descriptor",
    "is_ccxt_available",
]
