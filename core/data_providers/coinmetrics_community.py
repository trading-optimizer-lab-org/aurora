"""Coin Metrics community-API provider (R156 CRYPTO_METRICS).

Coin Metrics publishes a free community-tier REST API at
``https://community-api.coinmetrics.io/v4`` that exposes asset catalog,
asset-level metrics (e.g. ``AdrActCnt`` -- active addresses), and market
trade / quote data. The community licence is **non-commercial** by
default so every record we surface carries a
``"community_non_commercial_licence"`` warning unless the operator has
acknowledged the upgrade by setting :data:`OPERATOR_OVERRIDE_ENV`.

The provider takes an injectable ``http_get`` callable so tests can
mock the HTTP layer without touching the network. The default client
uses :mod:`urllib.request`.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import urlopen

from . import BaseDataProvider, ProviderDescriptor, ProviderRole
from ._free_bulk_common import FreeBulkLineage, utcnow_iso
from aurora.data_contracts import DataLineage

_log = logging.getLogger(__name__)


PROVIDER_NAME = "coinmetrics_community"
PROVIDER_URL = "https://community-api.coinmetrics.io/v4"
LICENCE_WARNING = "community_non_commercial_licence"
OPERATOR_OVERRIDE_ENV = "AU_COINMETRICS_LICENCE_OVERRIDE"


COINMETRICS_DESCRIPTOR = ProviderDescriptor(
    name=PROVIDER_NAME,
    role=ProviderRole.CRYPTO_METRICS,
    licence_terms_url="https://docs.coinmetrics.io/api/v4/#community",
    rate_limits="100 req/6sec free",
    auth_required=False,
    asset_classes=("crypto",),
    intervals=("daily", "hourly", "metric"),
    adjustment_posture="RAW",
    reliability="COMMUNITY",
)


# ---------------------------------------------------------------------------
# Frozen records.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CMAsset:
    """A single asset row returned by ``/catalog/assets``."""

    asset: str
    full_name: str
    symbol: str
    category: str
    is_active: bool
    provenance: Optional[FreeBulkLineage] = None


@dataclass(frozen=True)
class CMMetricObservation:
    """One ``(asset, metric, time, value)`` data point."""

    time_iso: str
    asset: str
    metric_name: str
    value: float
    provenance: Optional[FreeBulkLineage] = None


@dataclass(frozen=True)
class CMMarketData:
    """One market record (price + volume snapshot)."""

    market: str
    time_iso: str
    price_usd: float
    volume_usd: float
    provenance: FreeBulkLineage


# ---------------------------------------------------------------------------
# Default HTTP client (production).
# ---------------------------------------------------------------------------


def _default_http_get(url: str) -> Mapping[str, Any]:  # pragma: no cover - net
    with urlopen(url, timeout=30) as resp:  # nosec B310 -- official URL
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _licence_warnings() -> Tuple[str, ...]:
    """Return the licence-warning tuple unless the operator override is set."""
    if os.environ.get(OPERATOR_OVERRIDE_ENV, "") == "1":
        return ()
    return (LICENCE_WARNING,)


def _build_metadata_lineage(
    *,
    endpoint: str,
    query_params: Mapping[str, Any],
    row_count: int,
    date_range: Tuple[str, str] = ("", ""),
    symbol_count: int = 0,
) -> FreeBulkLineage:
    """Wrap a non-frame Coin Metrics response in a FreeBulkLineage envelope.

    Coin Metrics records are not OHLCV bars so we cannot run them
    through the OHLCV contract. We still emit a FreeBulkLineage so
    downstream tooling can attach the licence warning + provider
    identity to every record.
    """
    lineage = DataLineage(
        input_dataset_hash=utcnow_iso(),
        transformation_chain=("coinmetrics_community.fetch",),
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
        auth_mode="none",
        query_params=dict(query_params),
        row_count=int(row_count),
        date_range=date_range,
        symbol_count=int(symbol_count),
        extra={
            "reliability": "COMMUNITY",
            "source": "Coin Metrics community API",
            "licence_terms_url": COINMETRICS_DESCRIPTOR.licence_terms_url,
        },
        warnings=_licence_warnings(),
    )


def _build_url(endpoint: str, params: Mapping[str, Any]) -> str:
    cleaned = {k: v for k, v in params.items() if v is not None}
    if cleaned:
        return f"{PROVIDER_URL}{endpoint}?{urlencode(cleaned)}"
    return f"{PROVIDER_URL}{endpoint}"


# ---------------------------------------------------------------------------
# Client.
# ---------------------------------------------------------------------------


class CoinMetricsClient:
    """Thin wrapper around the Coin Metrics community REST API.

    The ``http_get`` callable receives a fully-formed URL and returns
    the parsed JSON payload. Tests inject a stub that resolves URLs to
    local fixtures.
    """

    def __init__(
        self,
        http_get: Optional[Callable[[str], Mapping[str, Any]]] = None,
    ) -> None:
        if http_get is None:
            raise RuntimeError(
                "CoinMetricsClient requires an injected http_get "
                "callable. The default URL-based client is opt-in via "
                "CoinMetricsClient.with_default_http(). Tests must "
                "always inject a stub."
            )
        self._http_get = http_get

    @classmethod
    def with_default_http(cls) -> "CoinMetricsClient":
        """Construct a client backed by the production urllib client."""
        return cls(http_get=_default_http_get)

    # -- catalog ---------------------------------------------------------

    def list_assets(self) -> Tuple[CMAsset, ...]:
        """Return the asset catalog (``/catalog/assets``)."""
        url = _build_url("/catalog/assets", {})
        payload = self._http_get(url)
        rows = payload.get("data") or []
        provenance = _build_metadata_lineage(
            endpoint="/catalog/assets",
            query_params={},
            row_count=len(rows),
            symbol_count=len(rows),
        )
        out: list[CMAsset] = []
        for row in rows:
            out.append(
                CMAsset(
                    asset=str(row.get("asset", "")),
                    full_name=str(row.get("full_name", "")),
                    symbol=str(row.get("symbol", "")),
                    category=str(row.get("category", "")),
                    is_active=bool(row.get("is_active", False)),
                    provenance=provenance,
                )
            )
        return tuple(out)

    # -- timeseries: asset metrics ---------------------------------------

    def fetch_metric(
        self,
        asset: str,
        metric: str,
        *,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> Tuple[CMMetricObservation, ...]:
        """Fetch a single asset metric series.

        Endpoint: ``/timeseries/asset-metrics``.
        """
        if not asset or not isinstance(asset, str):
            raise ValueError("asset must be a non-empty string")
        if not metric or not isinstance(metric, str):
            raise ValueError("metric must be a non-empty string")
        params = {
            "assets": asset,
            "metrics": metric,
            "start_time": start,
            "end_time": end,
            "frequency": "1d",
        }
        url = _build_url("/timeseries/asset-metrics", params)
        payload = self._http_get(url)
        rows = payload.get("data") or []
        provenance = _build_metadata_lineage(
            endpoint="/timeseries/asset-metrics",
            query_params=params,
            row_count=len(rows),
            symbol_count=1,
        )
        out: list[CMMetricObservation] = []
        for row in rows:
            value_raw = row.get(metric)
            if value_raw is None:
                continue
            try:
                value = float(value_raw)
            except (TypeError, ValueError):
                continue
            out.append(
                CMMetricObservation(
                    time_iso=str(row.get("time", "")),
                    asset=str(row.get("asset", asset)),
                    metric_name=metric,
                    value=value,
                    provenance=provenance,
                )
            )
        return tuple(out)

    # -- timeseries: market data -----------------------------------------

    def fetch_market_data(
        self,
        market: str,
        *,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> Tuple[CMMarketData, ...]:
        """Fetch market price + volume samples.

        Endpoint: ``/timeseries/market-trades`` (collapsed to one
        record per response row).
        """
        if not market or not isinstance(market, str):
            raise ValueError("market must be a non-empty string")
        params = {
            "markets": market,
            "start_time": start,
            "end_time": end,
        }
        url = _build_url("/timeseries/market-trades", params)
        payload = self._http_get(url)
        rows = payload.get("data") or []
        provenance = _build_metadata_lineage(
            endpoint="/timeseries/market-trades",
            query_params=params,
            row_count=len(rows),
            symbol_count=1,
        )
        out: list[CMMarketData] = []
        for row in rows:
            try:
                price = float(row.get("price", 0.0))
                volume = float(row.get("amount", row.get("volume_usd", 0.0)))
            except (TypeError, ValueError):
                continue
            out.append(
                CMMarketData(
                    market=str(row.get("market", market)),
                    time_iso=str(row.get("time", "")),
                    price_usd=price,
                    volume_usd=volume,
                    provenance=provenance,
                )
            )
        return tuple(out)


class CoinMetricsCommunityProvider(BaseDataProvider):
    """Thin metadata-carrying shell so the registry can list this role.

    The community API serves typed records (assets / metric series /
    market trades) rather than OHLCV frames, so direct ``fetch(symbol)``
    calls are out of contract for this provider. Use
    :class:`CoinMetricsClient` to read records; this class exists so
    ``DataProviderRegistry.list_by_role(CRYPTO_METRICS)`` can locate
    the provider by name.
    """

    name: str = PROVIDER_NAME
    version: str = "coinmetrics_community:1.0"
    point_in_time: bool = False
    tier_permission: str = "IS_TRAIN"
    schema_version: str = "1.0"

    def _fetch_raw(self, symbol, start, end, **kwargs):  # pragma: no cover
        raise NotImplementedError(
            "coinmetrics_community surfaces typed records via "
            "CoinMetricsClient.fetch_metric / fetch_market_data / "
            "list_assets, not generic fetch(symbol). See "
            "aurora.core.data_providers.coinmetrics_community."
        )


def descriptor() -> ProviderDescriptor:
    return COINMETRICS_DESCRIPTOR


__all__ = [
    "COINMETRICS_DESCRIPTOR",
    "CMAsset",
    "CMMarketData",
    "CMMetricObservation",
    "CoinMetricsClient",
    "CoinMetricsCommunityProvider",
    "LICENCE_WARNING",
    "OPERATOR_OVERRIDE_ENV",
    "PROVIDER_NAME",
    "PROVIDER_URL",
    "descriptor",
]
