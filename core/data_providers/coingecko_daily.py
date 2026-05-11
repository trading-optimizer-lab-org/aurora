"""CoinGecko daily metadata + market history provider (R155 CRYPTO_METADATA).

CoinGecko's free public API is rate-limited (~10-30 calls/min). The
provider takes an injectable ``client`` callable that the caller can
mock in tests; the production client uses ``urllib`` and respects a
per-call sleep + retry budget.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Mapping, Optional

import pandas as pd

from . import BaseDataProvider, ProviderError
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


PROVIDER_NAME = "coingecko"
PROVIDER_URL = "https://api.coingecko.com/api/v3/"
DEFAULT_SLEEP_SECONDS = 1.5
DEFAULT_MAX_RETRIES = 3


def _default_client(
    coin_id: str,
    vs_currency: str,
    days: int,
) -> Mapping[str, Any]:
    """Production client: fetch market chart with throttling."""
    from urllib.parse import urlencode
    from urllib.request import urlopen
    import json

    url = (
        f"{PROVIDER_URL}coins/{coin_id}/market_chart?"
        + urlencode({"vs_currency": vs_currency, "days": str(days)})
    )
    last_exc: Optional[Exception] = None
    for attempt in range(DEFAULT_MAX_RETRIES):
        try:
            with urlopen(url, timeout=30) as resp:  # nosec B310 -- official
                payload = json.loads(resp.read().decode("utf-8"))
            return payload
        except Exception as exc:  # pragma: no cover - network
            last_exc = exc
            time.sleep(DEFAULT_SLEEP_SECONDS * (attempt + 1))
    raise ProviderError(
        f"coingecko: failed after {DEFAULT_MAX_RETRIES} retries: {last_exc}"
    )


def _market_chart_to_ohlcv(payload: Mapping[str, Any]) -> pd.DataFrame:
    """Convert CoinGecko market_chart payload to an OHLCV-like daily frame.

    CoinGecko's free endpoint returns ``prices`` (timestamp_ms, price)
    tuples. We synthesise an OHLC frame where O=H=L=C=price, with
    ``volume`` from the ``total_volumes`` series when available. This is
    explicitly a *metadata* posture, not a primary OHLCV source --
    flagged as such on the lineage.
    """
    prices = payload.get("prices") or []
    volumes = payload.get("total_volumes") or []
    vol_map: dict[int, float] = {}
    for ts_ms, vol in volumes:
        vol_map[int(ts_ms)] = float(vol)
    rows: list[dict[str, Any]] = []
    for ts_ms, price in prices:
        ts = int(ts_ms)
        rows.append({
            "timestamp_ms": ts,
            "open": float(price),
            "high": float(price),
            "low": float(price),
            "close": float(price),
            "volume": float(vol_map.get(ts, 0.0)),
        })
    if not rows:
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
        )
    df = pd.DataFrame(rows)
    idx = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
    df = df.drop(columns=["timestamp_ms"])
    df.index = pd.DatetimeIndex(idx.values, tz="UTC", name="timestamp")
    return df.sort_index()


class CoinGeckoDailyProvider(BaseDataProvider):
    """CoinGecko daily metadata provider (CRYPTO_METADATA)."""

    name: str = PROVIDER_NAME
    version: str = "coingecko:1.0"
    point_in_time: bool = False
    tier_permission: str = "IS_TRAIN"
    schema_version: str = "1.0"

    def __init__(
        self,
        client: Optional[Callable[[str, str, int], Mapping[str, Any]]] = None,
    ) -> None:
        self._client = client or _default_client

    def fetch_daily(
        self,
        coin_id: str,
        *,
        vs_currency: str = "usd",
        days: int = 365,
    ) -> tuple[pd.DataFrame, FreeBulkLineage]:
        if not coin_id or not isinstance(coin_id, str):
            raise ValueError("coin_id must be a non-empty string")
        payload = self._client(coin_id, vs_currency, days)
        raw = _market_chart_to_ohlcv(payload)
        if len(raw) == 0:
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
            query_params={
                "coin_id": coin_id,
                "vs_currency": vs_currency,
                "days": days,
            },
            snapshot_hash=snapshot_hash,
            symbol_count=1,
            extra={
                "reliability": "OFFICIAL",
                "source": "CoinGecko",
                "rate_limit_aware": True,
                "adjustment_posture": "MIXED",
                "warning": (
                    "CoinGecko market_chart synthesises OHLC from price "
                    "samples; treat as metadata, not OHLCV-primary."
                ),
            },
        )
        return df, lineage

    def _fetch_raw(self, symbol, start, end, **kwargs):  # pragma: no cover
        df, _ = self.fetch_daily(symbol, **kwargs)
        return df


def descriptor():
    from . import ProviderDescriptor, ProviderRole
    return ProviderDescriptor(
        name=PROVIDER_NAME,
        role=ProviderRole.CRYPTO_METADATA,
        licence_terms_url="https://www.coingecko.com/en/terms",
        rate_limits="~10-30 calls/min on free tier; client retries with sleep",
        auth_required=False,
        asset_classes=("crypto",),
        intervals=("1d",),
        adjustment_posture="MIXED",
        reliability="OFFICIAL",
    )


__all__ = [
    "CoinGeckoDailyProvider",
    "PROVIDER_NAME",
    "PROVIDER_URL",
    "_market_chart_to_ohlcv",
    "descriptor",
]
