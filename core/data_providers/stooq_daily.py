"""Stooq daily OHLCV provider (R155 PRICE_PRIMARY).

Stooq publishes free end-of-day equity, ETF, FX and futures data via
``https://stooq.com/q/d/l/?s=<symbol>&i=d``. Rate limits are aggressive
and recent changes have introduced API-key / CAPTCHA gating on certain
endpoints. This adapter explicitly detects those failure modes and
raises :class:`StooqAuthRequired` so an operator can react -- it never
silently degrades to an unofficial source.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any, Callable, List, Mapping, Optional

import pandas as pd

from . import BaseDataProvider, ProviderError, ProviderUnavailable
from ._free_bulk_common import (
    OHLCV_DAILY_V1,
    FreeBulkLineage,
    assert_against_contract,
    build_lineage,
    normalise_ohlcv_frame,
    utcnow_iso,
)

_log = logging.getLogger(__name__)


PROVIDER_NAME = "stooq"
PROVIDER_URL = "https://stooq.com/q/d/l/"


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class StooqAuthRequired(ProviderError):
    """Stooq blocked the request with an auth / CAPTCHA gate.

    The operator-facing message includes the symbol and the upstream
    response excerpt so the operations team can decide whether to
    register an API key or fall back manually.
    """


# ---------------------------------------------------------------------------
# Default fetcher (production).
# ---------------------------------------------------------------------------


def _default_client(symbol: str, start: Optional[str], end: Optional[str]) -> str:
    """Production HTTP client. Tests inject their own.

    Returns the raw CSV text. Network errors are propagated; auth
    detection is handled by the parser, not the client.
    """
    try:
        from urllib.parse import urlencode
        from urllib.request import urlopen
    except Exception as exc:  # pragma: no cover
        raise ProviderUnavailable("stooq requires urllib from stdlib") from exc
    params: dict[str, str] = {"s": symbol.lower(), "i": "d"}
    if start:
        params["d1"] = start.replace("-", "")
    if end:
        params["d2"] = end.replace("-", "")
    url = PROVIDER_URL + "?" + urlencode(params)
    with urlopen(url, timeout=30) as resp:  # nosec B310 -- official URL
        return resp.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Parsing helpers.
# ---------------------------------------------------------------------------


# Phrases Stooq uses when blocking a request. Detection is case-insensitive
# and substring-based so a small message change does not silently break
# the gate.
_AUTH_PHRASES = (
    "no data",
    "captcha",
    "api key",
    "subscription required",
    "exceeded",
    "rate limit",
)


def _detect_auth_required(text: str, symbol: str) -> None:
    """Raise :class:`StooqAuthRequired` if the response looks like a gate.

    Stooq's auth page is HTML with very specific phrases; the CSV path
    starts with a header row containing ``date,open,high,low,close,volume``.
    Anything that does NOT start with that header is treated as a probable
    auth gate -- safer than missing a real failure.
    """
    head = text.strip().splitlines()[:1]
    head0 = head[0].lower() if head else ""
    if not head0:
        raise StooqAuthRequired(
            f"stooq returned an empty response for symbol={symbol!r}; "
            "operator action: register an API key or retry later."
        )
    if head0.startswith("<"):
        raise StooqAuthRequired(
            f"stooq returned HTML (likely CAPTCHA / auth gate) for "
            f"symbol={symbol!r}; first 200 chars: {text[:200]!r}. "
            "operator action: register an API key, complete CAPTCHA "
            "in browser, or fall back to a different provider."
        )
    if "date,open,high,low,close,volume" not in head0:
        # Some auth flows return a plain text "Exceeded daily limit"
        # message without HTML tags.
        if any(phrase in text.lower() for phrase in _AUTH_PHRASES):
            raise StooqAuthRequired(
                f"stooq blocked request for symbol={symbol!r}; "
                f"response: {text[:200]!r}. operator action: "
                "register an API key or retry later."
            )
        raise StooqAuthRequired(
            f"stooq response for symbol={symbol!r} did not contain the "
            f"expected CSV header. response: {text[:200]!r}"
        )


def _parse_csv(text: str) -> pd.DataFrame:
    """Parse Stooq CSV text into a DataFrame.

    The CSV columns are ``Date,Open,High,Low,Close,Volume``. We coerce
    the date column to a UTC DatetimeIndex; volume is left numeric.
    """
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, Any]] = []
    for row in reader:
        rows.append(row)
    if not rows:
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], name="timestamp"),
        )
    df = pd.DataFrame(rows)
    # Normalise column names so the downstream contract path is uniform.
    df.columns = [c.strip().lower() for c in df.columns]
    if "date" not in df.columns:
        raise ValueError("stooq CSV missing 'Date' column")
    idx = pd.to_datetime(df["date"], utc=True, errors="coerce")
    df = df.drop(columns=["date"])
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df.index = pd.DatetimeIndex(idx.values, tz="UTC", name="timestamp")
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df


# ---------------------------------------------------------------------------
# Provider class.
# ---------------------------------------------------------------------------


class StooqDailyProvider(BaseDataProvider):
    """Stooq daily OHLCV adapter (PRICE_PRIMARY)."""

    name: str = PROVIDER_NAME
    version: str = "stooq:1.0"
    point_in_time: bool = False
    tier_permission: str = "IS_TRAIN"
    schema_version: str = "1.0"

    def __init__(
        self,
        client: Optional[Callable[[str, Optional[str], Optional[str]], str]] = None,
    ) -> None:
        self._client = client or _default_client

    def fetch_daily(
        self,
        symbol: str,
        *,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> tuple[pd.DataFrame, FreeBulkLineage]:
        """Fetch daily OHLCV for ``symbol`` and return ``(df, lineage)``.

        Raises:
            StooqAuthRequired: if the upstream blocks the request.
            FreeBulkContractViolation: if the parsed frame fails
                :data:`OHLCV_DAILY_V1`.
        """
        if not symbol or not isinstance(symbol, str):
            raise ValueError("symbol must be a non-empty string")
        text = self._client(symbol, start, end)
        _detect_auth_required(text, symbol)
        raw = _parse_csv(text)
        df = normalise_ohlcv_frame(raw)
        snapshot_hash = assert_against_contract(df, OHLCV_DAILY_V1)
        lineage = build_lineage(
            df=df,
            contract=OHLCV_DAILY_V1,
            provider_name=self.name,
            provider_url=PROVIDER_URL,
            retrieved_at_iso=utcnow_iso(),
            auth_mode="none",
            query_params={"symbol": symbol, "start": start, "end": end},
            snapshot_hash=snapshot_hash,
            symbol_count=1,
            extra={
                "reliability": "OFFICIAL",
                "source": "Stooq",
                "adjustment_posture": "MIXED",
            },
        )
        return df, lineage

    def _fetch_raw(
        self,
        symbol: str,
        start,
        end,
        **kwargs: Any,
    ) -> pd.DataFrame:
        df, _ = self.fetch_daily(
            symbol,
            start=start.strftime("%Y-%m-%d") if start is not None else None,
            end=end.strftime("%Y-%m-%d") if end is not None else None,
        )
        return df


def descriptor():
    """Return the registry-friendly :class:`ProviderDescriptor`."""
    from . import ProviderDescriptor, ProviderRole
    return ProviderDescriptor(
        name=PROVIDER_NAME,
        role=ProviderRole.PRICE_PRIMARY,
        licence_terms_url="https://stooq.com/conditions/",
        rate_limits="aggressive (CAPTCHA / API key may be required)",
        auth_required=False,
        asset_classes=("equities", "etf", "forex", "futures", "index"),
        intervals=("1d",),
        adjustment_posture="MIXED",
        reliability="OFFICIAL",
    )


__all__ = [
    "StooqAuthRequired",
    "StooqDailyProvider",
    "PROVIDER_NAME",
    "PROVIDER_URL",
    "descriptor",
]
