"""DBnomics multi-source macro provider (R156 MACRO_MULTI_SOURCE).

DBnomics aggregates many public statistical sources (ECB, BIS, OECD,
INSEE, IMF, World Bank, etc.) under a single REST API. It is a broader
macro complement to FRED. Because DBnomics redistributes upstream data,
each series stamps the original ``provider`` (e.g. ``ECB``), the
``dataset`` code (e.g. ``EXR``), the ``series`` code (e.g.
``D.USD.EUR.SP00.A``) and the upstream licence string in provenance.

Endpoints used (v22 of the public API):

* ``GET https://api.db.nomics.world/v22/search?q=<query>``
* ``GET https://api.db.nomics.world/v22/series/{provider}/{dataset}/{series}?observations=1``

Tests inject ``http_get`` so the network is never touched. The default
client raises :class:`ProviderUnavailable` unless ``AU_DBNOMICS_HTTP=1``
is set explicitly so an accidental fetch does not silently call out.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Tuple

import pandas as pd

from . import (
    BaseDataProvider,
    ProviderDescriptor,
    ProviderRole,
    ProviderUnavailable,
)
from ._free_bulk_common import (
    MACRO_DAILY_V1,
    FreeBulkLineage,
    assert_against_contract,
    build_lineage,
    utcnow_iso,
)

_log = logging.getLogger(__name__)


PROVIDER_NAME = "dbnomics_macro"
PROVIDER_URL = "https://db.nomics.world/"
API_BASE = "https://api.db.nomics.world/v22"

# Provider/dataset/series codes are upper-case alnum + a small set of
# punctuation. Validate so a malformed series id surfaces at construction
# time rather than producing a confusing 404.
_CODE_RE = re.compile(r"^[A-Za-z0-9_\-./]+$")


DBNOMICS_DESCRIPTOR = ProviderDescriptor(
    name=PROVIDER_NAME,
    role=ProviderRole.MACRO_MULTI_SOURCE,
    licence_terms_url="https://db.nomics.world/legal",
    rate_limits="100 req/min",
    auth_required=False,
    asset_classes=("macro",),
    intervals=("daily", "weekly", "monthly", "quarterly", "annual"),
    adjustment_posture="RAW",
    reliability="OFFICIAL",
)


# ---------------------------------------------------------------------------
# Frozen records.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DBnomicsSeriesId:
    """Triple uniquely identifying a DBnomics series.

    The triple ``(provider_code, dataset_code, series_code)`` is the
    canonical addressable identifier in DBnomics. ``provider_code`` is
    the *upstream* provider (e.g. ``ECB``, ``BIS``, ``IMF``), not
    DBnomics itself.
    """

    provider_code: str
    dataset_code: str
    series_code: str

    def __post_init__(self) -> None:
        for field_name in ("provider_code", "dataset_code", "series_code"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"DBnomicsSeriesId.{field_name} must be a non-empty string"
                )
            if not _CODE_RE.match(value):
                raise ValueError(
                    f"DBnomicsSeriesId.{field_name}={value!r} contains "
                    "characters outside [A-Za-z0-9_./-]"
                )

    def as_path(self) -> str:
        return f"{self.provider_code}/{self.dataset_code}/{self.series_code}"


@dataclass(frozen=True)
class DBnomicsObservation:
    """One observation point on a DBnomics series."""

    period_iso: str
    value: float
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DBnomicsSeries:
    """Resolved DBnomics series with provenance."""

    series_id: DBnomicsSeriesId
    name: str
    unit: str
    frequency: str
    upstream_licence: str
    observations: Tuple[DBnomicsObservation, ...]
    provenance: FreeBulkLineage


# ---------------------------------------------------------------------------
# Client.
# ---------------------------------------------------------------------------


def _default_http_get(url: str, params: Optional[Mapping[str, Any]] = None) -> str:
    """Default HTTP client. Refuses to call out unless explicitly opted in."""
    if os.environ.get("AU_DBNOMICS_HTTP") != "1":
        raise ProviderUnavailable(
            "dbnomics_macro: no http_get injected and AU_DBNOMICS_HTTP=1 "
            "is not set; tests must inject a fixture-backed client."
        )
    # Lazy import so we never import urllib at module load.
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen

    full = url
    if params:
        full = f"{url}?{urlencode(dict(params))}"
    req = Request(full, headers={"User-Agent": "aurora-dbnomics/1.0"})
    with urlopen(req, timeout=30) as resp:  # pragma: no cover - networked
        return resp.read().decode("utf-8")


class DBnomicsClient(BaseDataProvider):
    """Discover + fetch DBnomics series with an injectable HTTP getter.

    Extends :class:`BaseDataProvider` so the role-aware registry can
    hold this provider alongside OHLCV providers; the OHLCV ``fetch``
    contract is intentionally not implemented because DBnomics serves
    macro/context series.
    """

    name: str = PROVIDER_NAME
    version: str = "dbnomics_macro:1.0"
    point_in_time: bool = True
    tier_permission: str = "ANY"
    schema_version: str = "1.0"

    def __init__(
        self,
        http_get: Optional[
            Callable[[str, Optional[Mapping[str, Any]]], str]
        ] = None,
    ) -> None:
        self._http_get = http_get or _default_http_get

    # -- discovery ----------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        max_results: int = 20,
    ) -> Tuple[Tuple[str, str, str, str], ...]:
        """Search the DBnomics catalogue.

        Returns a tuple of ``(provider_code, dataset_code, series_code,
        name)`` discovery rows. Empty tuple when no match.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if max_results <= 0:
            raise ValueError("max_results must be positive")
        url = f"{API_BASE}/search"
        body = self._http_get(url, {"q": query, "limit": max_results})
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ProviderUnavailable(
                f"dbnomics_macro: search returned non-JSON: {exc}"
            ) from exc
        results = payload.get("results", {}).get("docs", [])
        out: list[tuple[str, str, str, str]] = []
        for doc in results[:max_results]:
            provider = str(doc.get("provider_code", ""))
            dataset = str(doc.get("dataset_code", ""))
            series = str(doc.get("series_code", ""))
            name = str(doc.get("name", "") or doc.get("series_name", ""))
            if provider and dataset and series:
                out.append((provider, dataset, series, name))
        return tuple(out)

    # -- fetch --------------------------------------------------------------

    def fetch_series(self, series_id: DBnomicsSeriesId) -> DBnomicsSeries:
        """Fetch a single series with observations.

        Hits ``/v22/series/{provider}/{dataset}/{series}?observations=1``.
        """
        if not isinstance(series_id, DBnomicsSeriesId):
            raise TypeError(
                "series_id must be a DBnomicsSeriesId; "
                f"got {type(series_id).__name__}"
            )
        url = f"{API_BASE}/series/{series_id.as_path()}"
        body = self._http_get(url, {"observations": "1"})
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ProviderUnavailable(
                f"dbnomics_macro: fetch returned non-JSON: {exc}"
            ) from exc
        return self._parse_series_response(series_id, payload)

    # -- internals ----------------------------------------------------------

    def _parse_series_response(
        self,
        series_id: DBnomicsSeriesId,
        payload: Mapping[str, Any],
    ) -> DBnomicsSeries:
        series_block = (
            payload.get("series", {}).get("docs", [])
        )
        if not series_block:
            raise ProviderUnavailable(
                f"dbnomics_macro: series {series_id.as_path()!r} not found "
                "in response"
            )
        doc = series_block[0]
        name = str(doc.get("name") or doc.get("series_name") or "")
        unit = str(doc.get("@frequency") or doc.get("unit") or "")
        frequency = str(doc.get("@frequency") or doc.get("frequency") or "")
        # Upstream licence: DBnomics surfaces this in the dataset block.
        dataset_meta = payload.get("dataset", {}) or {}
        upstream_licence = str(
            dataset_meta.get("attribution")
            or dataset_meta.get("licence")
            or doc.get("attribution")
            or "Aggregated by DBnomics; consult upstream provider terms"
        )
        periods = doc.get("period", []) or []
        values = doc.get("value", []) or []
        attrs_per_obs = doc.get("observations_attributes") or []
        observations: list[DBnomicsObservation] = []
        for i, period in enumerate(periods):
            raw_value = values[i] if i < len(values) else None
            try:
                numeric_value = float(raw_value)
            except (TypeError, ValueError):
                # DBnomics encodes missing as "NA"; keep as NaN.
                numeric_value = float("nan")
            attr_dict: dict[str, Any] = {}
            if i < len(attrs_per_obs):
                attr_pair = attrs_per_obs[i]
                if isinstance(attr_pair, list) and len(attr_pair) == 2:
                    attr_dict[str(attr_pair[0])] = attr_pair[1]
                elif isinstance(attr_pair, dict):
                    attr_dict.update({str(k): v for k, v in attr_pair.items()})
            observations.append(
                DBnomicsObservation(
                    period_iso=str(period),
                    value=numeric_value,
                    attributes=attr_dict,
                )
            )
        df = self._observations_to_frame(observations)
        snapshot_hash = assert_against_contract(df, MACRO_DAILY_V1)
        provenance = build_lineage(
            df=df,
            contract=MACRO_DAILY_V1,
            provider_name=PROVIDER_NAME,
            provider_url=PROVIDER_URL,
            retrieved_at_iso=utcnow_iso(),
            auth_mode="none",
            query_params={
                "provider_code": series_id.provider_code,
                "dataset_code": series_id.dataset_code,
                "series_code": series_id.series_code,
            },
            snapshot_hash=snapshot_hash,
            symbol_count=1,
            extra={
                "reliability": "OFFICIAL",
                "source": "DBnomics",
                "asset_class": "MACRO",
                "library": "macro_multisource",
                "upstream_provider": series_id.provider_code,
                "upstream_dataset": series_id.dataset_code,
                "upstream_series": series_id.series_code,
                "upstream_licence": upstream_licence,
            },
        )
        return DBnomicsSeries(
            series_id=series_id,
            name=name,
            unit=unit,
            frequency=frequency,
            upstream_licence=upstream_licence,
            observations=tuple(observations),
            provenance=provenance,
        )

    @staticmethod
    def _observations_to_frame(
        observations: Tuple[DBnomicsObservation, ...] | list[DBnomicsObservation],
    ) -> pd.DataFrame:
        if not observations:
            return pd.DataFrame({
                "timestamp": pd.Series(dtype="datetime64[ns, UTC]"),
                "value": pd.Series(dtype="float64"),
            })
        ts = pd.to_datetime(
            [o.period_iso for o in observations], utc=True, errors="coerce"
        )
        df = pd.DataFrame({
            "timestamp": ts,
            "value": pd.to_numeric(
                [o.value for o in observations], errors="coerce"
            ),
        })
        df = df.dropna(subset=["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df


def descriptor() -> ProviderDescriptor:
    """Return the :class:`ProviderDescriptor` for this provider."""
    return DBNOMICS_DESCRIPTOR


__all__ = [
    "DBNOMICS_DESCRIPTOR",
    "DBnomicsClient",
    "DBnomicsObservation",
    "DBnomicsSeries",
    "DBnomicsSeriesId",
    "PROVIDER_NAME",
    "PROVIDER_URL",
    "API_BASE",
    "descriptor",
]
