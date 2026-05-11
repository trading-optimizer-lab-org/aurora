"""Tiingo daily EOD provider (R156 OPTIONAL_PRICE_FALLBACK).

Tiingo is a paid-API-key vendor with a free tier (50 req/hour, ~1000
daily symbols). It serves adjusted EOD bars for equities, ETFs, mutual
funds and crypto. We treat it strictly as an *optional* fallback that
the operator must enable by exporting :data:`TOKEN_ENV_VAR`.

Constructor contract:

* If ``http_get`` is injected (test path), we accept either a real
  token or no token: tests own the network seam.
* If ``http_get`` is not injected and the env var is unset, we raise
  ``RuntimeError`` with an operator-actionable message. This refuses
  silent activation and flushes "we have a token" assumptions out of
  the build matrix.

The module imports cleanly even when the env var is unset so the
descriptor remains inspectable from CLI / registry tooling without
side-effects.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import BaseDataProvider, ProviderDescriptor, ProviderRole
from ._free_bulk_common import FreeBulkLineage, utcnow_iso
from aurora.data_contracts import DataLineage

_log = logging.getLogger(__name__)


PROVIDER_NAME = "tiingo_daily"
PROVIDER_URL = "https://api.tiingo.com"
TOKEN_ENV_VAR = "AU_TIINGO_API_TOKEN"


TIINGO_DESCRIPTOR = ProviderDescriptor(
    name=PROVIDER_NAME,
    role=ProviderRole.OPTIONAL_PRICE_FALLBACK,
    licence_terms_url="https://www.tiingo.com/about/terms",
    rate_limits="50 req/hour free / 1000 daily symbols max",
    auth_required=True,
    asset_classes=("equity", "etf", "mutual_fund", "crypto"),
    intervals=("daily",),
    adjustment_posture="ADJUSTED",
    reliability="COMMUNITY",
)


# ---------------------------------------------------------------------------
# Frozen records.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TiingoEODBar:
    """One adjusted daily bar from Tiingo's ``/tiingo/daily`` endpoint."""

    date_iso: str
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: int
    dividend: float
    split_factor: float
    provenance: FreeBulkLineage


# ---------------------------------------------------------------------------
# Default HTTP client (production).
# ---------------------------------------------------------------------------


def _default_http_get(
    url: str, headers: Mapping[str, str]
) -> Mapping[str, Any]:  # pragma: no cover - net
    req = Request(url, headers=dict(headers))
    with urlopen(req, timeout=30) as resp:  # nosec B310 -- official URL
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _build_lineage(
    *,
    endpoint: str,
    ticker: str,
    asset_class: str,
    query_params: Mapping[str, Any],
    row_count: int,
    date_range: Tuple[str, str],
) -> FreeBulkLineage:
    lineage = DataLineage(
        input_dataset_hash=utcnow_iso(),
        transformation_chain=("tiingo_daily.fetch_daily",),
        code_version="aurora-r156",
        contract_version="0.0.0",
        snapshot_hash="",
        validator_version="1.0.0",
        decision_outcome="accepted",
        contract_hash="",
    )
    return FreeBulkLineage(
        lineage=lineage,
        provider_name=PROVIDER_NAME,
        provider_url=f"{PROVIDER_URL}{endpoint}",
        retrieved_at_iso=utcnow_iso(),
        auth_mode="api_token",
        query_params=dict(query_params),
        row_count=int(row_count),
        date_range=date_range,
        symbol_count=1,
        extra={
            "reliability": "COMMUNITY",
            "source": "Tiingo",
            "ticker": ticker,
            "asset_class": asset_class,
            "is_optional_fallback": True,
            "is_fallback": True,
            "adjustment_posture": "ADJUSTED",
        },
    )


def _missing_token_message() -> str:
    return (
        "Tiingo requires AU_TIINGO_API_TOKEN. "
        "Either export the env var with a Tiingo API token, or "
        "construct TiingoClient(http_get=<stub>) when used in tests / "
        "fixtures. Refusing silent activation."
    )


# ---------------------------------------------------------------------------
# Client.
# ---------------------------------------------------------------------------


class TiingoClient:
    """Tiingo daily EOD client.

    Constructor:

    * ``http_get``: optional injectable callable
      ``(url: str, headers: Mapping[str, str]) -> Mapping[str, Any]``.
    * ``api_token``: explicit token override; falls back to
      :data:`TOKEN_ENV_VAR`.

    Raises ``RuntimeError`` when no token is reachable AND no
    ``http_get`` was injected.
    """

    def __init__(
        self,
        http_get: Optional[
            Callable[[str, Mapping[str, str]], Mapping[str, Any]]
        ] = None,
        api_token: Optional[str] = None,
    ) -> None:
        token = api_token or os.environ.get(TOKEN_ENV_VAR, "") or None
        if token is None and http_get is None:
            raise RuntimeError(_missing_token_message())
        self._token = token
        self._http_get = http_get or _default_http_get

    # -- timeseries: daily bars ------------------------------------------

    def fetch_daily(
        self,
        ticker: str,
        *,
        start: Optional[str] = None,
        end: Optional[str] = None,
        asset_class: str = "equity",
    ) -> Tuple[TiingoEODBar, ...]:
        """Fetch adjusted daily bars from ``/tiingo/daily/{ticker}/prices``."""
        if not ticker or not isinstance(ticker, str):
            raise ValueError("ticker must be a non-empty string")
        params: dict[str, Any] = {}
        if start:
            params["startDate"] = start
        if end:
            params["endDate"] = end
        endpoint = f"/tiingo/daily/{ticker}/prices"
        url = (
            f"{PROVIDER_URL}{endpoint}"
            + (f"?{urlencode(params)}" if params else "")
        )
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "aurora-r156-tiingo",
        }
        if self._token:
            headers["Authorization"] = f"Token {self._token}"
        payload = self._http_get(url, headers)
        rows = payload if isinstance(payload, list) else payload.get("data", [])
        if not isinstance(rows, list):
            rows = []

        # Compute date range first so the lineage knows the span.
        dates = [str(r.get("date", "")) for r in rows if r.get("date")]
        date_range = (
            (dates[0], dates[-1]) if dates else ("", "")
        )
        provenance = _build_lineage(
            endpoint=endpoint,
            ticker=ticker,
            asset_class=asset_class,
            query_params={
                **params,
                "asset_class": asset_class,
            },
            row_count=len(rows),
            date_range=date_range,
        )

        out: list[TiingoEODBar] = []
        for row in rows:
            try:
                bar = TiingoEODBar(
                    date_iso=str(row.get("date", "")),
                    open=float(row.get("open", 0.0)),
                    high=float(row.get("high", 0.0)),
                    low=float(row.get("low", 0.0)),
                    close=float(row.get("close", 0.0)),
                    adj_close=float(
                        row.get("adjClose", row.get("close", 0.0))
                    ),
                    volume=int(row.get("volume", 0)),
                    dividend=float(row.get("divCash", 0.0)),
                    split_factor=float(row.get("splitFactor", 1.0)),
                    provenance=provenance,
                )
            except (TypeError, ValueError) as exc:
                _log.debug("tiingo_daily: skipping malformed row: %s", exc)
                continue
            out.append(bar)
        return tuple(out)


class TiingoDailyProvider(BaseDataProvider):
    """Thin metadata-carrying shell for the registry.

    Tiingo serves adjusted EOD bars but the surface is typed
    (:class:`TiingoEODBar`) rather than a generic OHLCV frame. The
    registry needs a ``DataProvider`` instance to attach the
    descriptor; this shell satisfies that requirement without
    pretending to support generic ``fetch(symbol)``.
    """

    name: str = PROVIDER_NAME
    version: str = "tiingo_daily:1.0"
    point_in_time: bool = False
    tier_permission: str = "IS_TRAIN"
    schema_version: str = "1.0"

    def _fetch_raw(self, symbol, start, end, **kwargs):  # pragma: no cover
        raise NotImplementedError(
            "tiingo_daily surfaces typed records via "
            "TiingoClient.fetch_daily, not generic fetch(symbol). "
            "See aurora.core.data_providers.tiingo_daily."
        )


def descriptor() -> ProviderDescriptor:
    return TIINGO_DESCRIPTOR


__all__ = [
    "PROVIDER_NAME",
    "PROVIDER_URL",
    "TIINGO_DESCRIPTOR",
    "TOKEN_ENV_VAR",
    "TiingoClient",
    "TiingoDailyProvider",
    "TiingoEODBar",
    "descriptor",
]
