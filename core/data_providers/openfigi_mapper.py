"""OpenFIGI identifier-mapping provider (R156 priority 1).

OpenFIGI is Bloomberg's free identifier-mapping service. It maps a
ticker / ISIN / CUSIP / SEDOL / exchange to one or more FIGI candidates.

This module is the AURORA-side adapter. It is deliberately I/O-free in
test paths: callers inject an ``http_post`` callable that returns the
already-parsed JSON response. The default production client is
intentionally None -- live mode requires an operator decision (because
the rate limits and the optional API token both need a deployment
choice). Tests and library callers always pass a mock.

The provider preserves ambiguity: when OpenFIGI returns several
candidates, all of them are returned in the result tuple, and the
``is_ambiguous`` flag is set. Callers must decide how to disambiguate
(typically by passing ``exchange`` or ``id_type=ISIN/CUSIP/SEDOL``);
the provider never silently picks the first match.

Public API
----------
* :class:`FIGIMapping` -- frozen dataclass for one candidate mapping.
* :class:`FIGIQueryResult` -- frozen dataclass wrapping the candidates
  for a single query (with ambiguity flag and provider warning).
* :class:`OpenFIGIClient` -- adapter exposing ``map_symbol`` and
  ``bulk_map``.
* :data:`OPENFIGI_DESCRIPTOR` -- registry-friendly descriptor.
* :func:`descriptor` -- function alias matching the R155 provider style.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

from . import BaseDataProvider, ProviderDescriptor, ProviderRole
from ._free_bulk_common import FreeBulkLineage, build_lineage, utcnow_iso

import pandas as pd

from aurora.data_contracts import (
    ContractField,
    DataContract,
)

_log = logging.getLogger(__name__)


PROVIDER_NAME = "openfigi_mapper"
PROVIDER_URL = "https://api.openfigi.com/v3/mapping"
LICENCE_TERMS_URL = "https://www.openfigi.com/api"

# Public free-tier rate limits per OpenFIGI docs:
#  - Unauthenticated: 25 requests/min, 5 jobs per request.
#  - Authenticated  : 250 requests/min, 100 jobs per request.
RATE_LIMIT_DESCRIPTION = (
    "free tier: 25 req/min unauth (5 jobs/req); "
    "250 req/min authed (100 jobs/req)"
)
_RATE_PER_MIN_UNAUTH = 25
_RATE_PER_MIN_AUTH = 250

# Asset classes OpenFIGI claims to map.
ASSET_CLASSES: Tuple[str, ...] = (
    "equity",
    "bond",
    "fund",
    "etf",
    "fx",
    "crypto",
)

# Minimal contract for a normalised FIGI mapping table -- not used for
# OHLCV gating, but lets us produce a hashable lineage that other
# AURORA components can stamp into provenance.
FIGI_MAPPING_V1 = DataContract(
    name="figi_mapping_v1",
    version="1.0.0",
    description=(
        "OpenFIGI mapping rows: figi, name, ticker, exchange_code, "
        "market_sector, security_type, unique_id, unique_id_type, "
        "currency, composite_figi, share_class_figi."
    ),
    fields=(
        ContractField("figi", dtype_kind="string", nullable=True),
        ContractField("name", dtype_kind="string", nullable=True),
        ContractField("ticker", dtype_kind="string", nullable=True),
        ContractField("exchange_code", dtype_kind="string", nullable=True),
        ContractField("market_sector", dtype_kind="string", nullable=True),
        ContractField("security_type", dtype_kind="string", nullable=True),
        ContractField("unique_id", dtype_kind="string", nullable=True),
        ContractField("unique_id_type", dtype_kind="string", nullable=True),
        ContractField("currency", dtype_kind="string", nullable=True),
        ContractField("composite_figi", dtype_kind="string", nullable=True),
        ContractField("share_class_figi", dtype_kind="string", nullable=True),
    ),
)


# ---------------------------------------------------------------------------
# Frozen dataclasses.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FIGIMapping:
    """A single OpenFIGI candidate mapping.

    All fields are optional because OpenFIGI's response shape varies
    by query type: a SEDOL lookup will not echo a ticker, a TICKER
    lookup may not echo a SEDOL.
    """

    figi: Optional[str] = None
    name: Optional[str] = None
    ticker: Optional[str] = None
    exchange_code: Optional[str] = None
    market_sector: Optional[str] = None
    security_type: Optional[str] = None
    unique_id: Optional[str] = None
    unique_id_type: Optional[str] = None
    currency: Optional[str] = None
    composite_figi: Optional[str] = None
    share_class_figi: Optional[str] = None


@dataclass(frozen=True)
class FIGIQueryResult:
    """The result of a single OpenFIGI query.

    Attributes:
        query: the input job dict actually sent to OpenFIGI (after
            normalisation), preserved so a caller can correlate the
            response with the input.
        mappings: tuple of candidate :class:`FIGIMapping` records. Empty
            when OpenFIGI returned a "no match" response.
        is_ambiguous: True iff ``len(mappings) > 1``. Caller MUST handle
            this -- the provider never silently picks the first match.
        warning: OpenFIGI's per-job warning text (e.g. "no FIGI match").
            None when the response was clean.
        provenance: :class:`FreeBulkLineage` carrier so the caller can
            stamp the lookup into an audit log.
    """

    query: Mapping[str, Any]
    mappings: Tuple[FIGIMapping, ...]
    is_ambiguous: bool
    warning: Optional[str]
    provenance: FreeBulkLineage


# ---------------------------------------------------------------------------
# Descriptor.
# ---------------------------------------------------------------------------


OPENFIGI_DESCRIPTOR = ProviderDescriptor(
    name=PROVIDER_NAME,
    role=ProviderRole.IDENTITY_MAPPING,
    licence_terms_url=LICENCE_TERMS_URL,
    rate_limits=RATE_LIMIT_DESCRIPTION,
    auth_required=False,
    asset_classes=ASSET_CLASSES,
    intervals=(),
    adjustment_posture="MIXED",
    reliability="OFFICIAL",
)


def descriptor() -> ProviderDescriptor:
    """Return the :class:`ProviderDescriptor` for the OpenFIGI mapper."""
    return OPENFIGI_DESCRIPTOR


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _camel_to_snake_mapping(raw: Mapping[str, Any]) -> FIGIMapping:
    """Coerce an OpenFIGI response row (camelCase) to :class:`FIGIMapping`.

    OpenFIGI returns keys like ``marketSector`` and ``exchCode``; we
    map them to snake_case attribute names. Missing keys map to None.
    Unknown keys are ignored so a future schema bump does not crash
    callers. This mirrors the "preserve everything declared, ignore
    everything not declared" stance of the R155 normalisers.
    """
    return FIGIMapping(
        figi=_str_or_none(raw.get("figi")),
        name=_str_or_none(raw.get("name")),
        ticker=_str_or_none(raw.get("ticker")),
        exchange_code=_str_or_none(raw.get("exchCode")),
        market_sector=_str_or_none(raw.get("marketSector")),
        security_type=_str_or_none(raw.get("securityType")),
        unique_id=_str_or_none(raw.get("uniqueID")),
        unique_id_type=_str_or_none(raw.get("uniqueIDFutOpt") or raw.get("uniqueIdType")),
        currency=_str_or_none(raw.get("currency")),
        composite_figi=_str_or_none(raw.get("compositeFIGI")),
        share_class_figi=_str_or_none(raw.get("shareClassFIGI")),
    )


def _str_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value)
    return s if s != "" else None


def _build_job(
    *,
    ticker: Optional[str],
    exchange: Optional[str],
    id_type: str,
    id_value: Optional[str],
) -> dict[str, Any]:
    """Build a single OpenFIGI job dict.

    OpenFIGI expects an ``idType`` enum like ``TICKER``, ``ID_ISIN``,
    ``ID_CUSIP``, ``ID_SEDOL``, etc. We accept the short forms
    ``TICKER / ISIN / CUSIP / SEDOL`` and map to the wire format.
    """
    type_map = {
        "TICKER": "TICKER",
        "ISIN": "ID_ISIN",
        "CUSIP": "ID_CUSIP",
        "SEDOL": "ID_SEDOL",
        "FIGI": "ID_BB_GLOBAL",
        "BB_GLOBAL": "ID_BB_GLOBAL",
    }
    wire_type = type_map.get(id_type.upper(), id_type)
    job: dict[str, Any] = {"idType": wire_type}
    # When the caller passes an explicit id_value (e.g. an ISIN), use
    # it; otherwise fall back to the ticker. The provider does not
    # invent values.
    value = id_value if id_value is not None else ticker
    if value is None:
        raise ValueError(
            "openfigi: must supply either ticker= or id_value= "
            "(both empty would be an unscoped query)"
        )
    job["idValue"] = str(value)
    if exchange:
        job["exchCode"] = str(exchange)
    return job


# ---------------------------------------------------------------------------
# Client.
# ---------------------------------------------------------------------------


HttpPostCallable = Callable[
    [str, Sequence[Mapping[str, Any]], Mapping[str, str]],
    Sequence[Mapping[str, Any]],
]


class OpenFIGIClient(BaseDataProvider):
    """OpenFIGI mapping client with injectable HTTP transport.

    Inherits :class:`BaseDataProvider` so the registry can hold it
    next to OHLCV providers; OHLCV ``fetch`` is intentionally not
    implemented because OpenFIGI is an identity-mapping service.

    Args:
        http_post: callable ``(url, payload, headers) -> response``
            where ``response`` is a sequence of dicts -- one per
            input job -- matching OpenFIGI's documented v3 shape:
            ``[{"data": [{"figi": ..., ...}, ...]}, ...]`` or
            ``[{"warning": "no FIGI match"}, ...]``. Pass a stub for
            tests; pass a real HTTP client (e.g. requests.post wrapper)
            for production. ``None`` means "no client configured", and
            any call to :meth:`map_symbol` / :meth:`bulk_map` raises
            :class:`RuntimeError` so an operator must explicitly choose.
        api_key: optional OpenFIGI API key. If not supplied, the
            ``AU_OPENFIGI_API_KEY`` environment variable is consulted.
            With a key, the rate-limit ceiling is 250/min instead of
            25/min. The value is sent as the ``X-OPENFIGI-APIKEY``
            header, never logged.

    The client maintains an in-process rate limiter so a misconfigured
    test or production caller cannot accidentally exceed the public
    limits. The limiter is a no-op when ``http_post`` is None (because
    no calls happen at all) and when the caller mocks out time via the
    injected client.
    """

    name: str = PROVIDER_NAME
    version: str = "openfigi_mapper:1.0"
    point_in_time: bool = True
    tier_permission: str = "ANY"
    schema_version: str = "1.0"

    def __init__(
        self,
        *,
        http_post: Optional[HttpPostCallable] = None,
        api_key: Optional[str] = None,
        clock: Optional[Callable[[], float]] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> None:
        self._http_post = http_post
        # Resolve API key from env if not passed; never log the value.
        self._api_key = api_key if api_key is not None else os.environ.get(
            "AU_OPENFIGI_API_KEY"
        )
        self._clock = clock if clock is not None else time.monotonic
        self._sleep = sleep if sleep is not None else time.sleep
        self._lock = threading.Lock()
        self._call_times: list[float] = []

    # -- helpers ------------------------------------------------------------

    @property
    def auth_mode(self) -> str:
        return "api_key" if self._api_key else "none"

    def _rate_limit_ceiling(self) -> int:
        return _RATE_PER_MIN_AUTH if self._api_key else _RATE_PER_MIN_UNAUTH

    def _throttle(self) -> None:
        """Block if we have already issued ``ceiling`` calls in the past 60s.

        The limiter is intentionally simple: it tracks call timestamps
        in a list, drops anything older than 60s, and sleeps the
        difference if we are at the ceiling. In tests, callers can
        inject ``clock=`` and ``sleep=`` to make it deterministic; in
        practice tests mock ``http_post`` and so the throttle has at
        most one entry and never sleeps.
        """
        ceiling = self._rate_limit_ceiling()
        with self._lock:
            now = self._clock()
            cutoff = now - 60.0
            self._call_times = [t for t in self._call_times if t > cutoff]
            if len(self._call_times) >= ceiling:
                wait = 60.0 - (now - self._call_times[0])
                if wait > 0:
                    self._sleep(wait)
                    now = self._clock()
                    cutoff = now - 60.0
                    self._call_times = [
                        t for t in self._call_times if t > cutoff
                    ]
            self._call_times.append(now)

    def _require_client(self) -> HttpPostCallable:
        if self._http_post is None:
            raise RuntimeError(
                "OpenFIGI requires injected HTTP client; live mode pending "
                "operator credentials. Pass http_post=... to OpenFIGIClient "
                "(stub in tests; real requests.post wrapper in production)."
            )
        return self._http_post

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["X-OPENFIGI-APIKEY"] = self._api_key
        return h

    # -- public API ---------------------------------------------------------

    def map_symbol(
        self,
        ticker: Optional[str] = None,
        *,
        exchange: Optional[str] = None,
        id_type: str = "TICKER",
        id_value: Optional[str] = None,
    ) -> FIGIQueryResult:
        """Map a single identifier to FIGI candidate(s).

        Args:
            ticker: the ticker symbol when ``id_type == TICKER``.
                Mutually compatible with ``exchange`` to disambiguate.
            exchange: optional MIC / OpenFIGI exchange code, e.g.
                ``"US"``, ``"UN"`` (NYSE), ``"UQ"`` (Nasdaq). When
                supplied, OpenFIGI narrows the candidates accordingly.
            id_type: short identifier scheme. One of ``TICKER``,
                ``ISIN``, ``CUSIP``, ``SEDOL``, ``FIGI``.
            id_value: explicit identifier value. Required when
                ``id_type != TICKER``; for tickers, leave empty and
                pass ``ticker``.

        Returns:
            A :class:`FIGIQueryResult` with all candidate mappings.
            For "no match" responses, ``mappings`` is empty and
            ``warning`` is set.
        """
        results = self.bulk_map(
            (
                {
                    "ticker": ticker,
                    "exchange": exchange,
                    "id_type": id_type,
                    "id_value": id_value,
                },
            )
        )
        return results[0]

    def bulk_map(
        self,
        queries: Sequence[Mapping[str, Any]],
    ) -> Tuple[FIGIQueryResult, ...]:
        """Batch-map a list of queries to FIGI candidates.

        Each query is a mapping with optional keys ``ticker``,
        ``exchange``, ``id_type``, ``id_value``. The provider sends them
        as a single OpenFIGI batch and returns one
        :class:`FIGIQueryResult` per query, in input order.

        Args:
            queries: input jobs.

        Returns:
            Tuple of :class:`FIGIQueryResult` of the same length and
            order as ``queries``.
        """
        post = self._require_client()
        if not queries:
            return ()
        jobs = []
        for q in queries:
            jobs.append(
                _build_job(
                    ticker=q.get("ticker") if isinstance(q, Mapping) else None,
                    exchange=q.get("exchange") if isinstance(q, Mapping) else None,
                    id_type=str(
                        q.get("id_type", "TICKER") if isinstance(q, Mapping) else "TICKER"
                    ),
                    id_value=q.get("id_value") if isinstance(q, Mapping) else None,
                )
            )
        self._throttle()
        response = post(PROVIDER_URL, jobs, self._headers())
        if not isinstance(response, Sequence):
            raise TypeError(
                f"OpenFIGI: expected a sequence of result dicts; "
                f"got {type(response).__name__}"
            )
        if len(response) != len(jobs):
            raise ValueError(
                f"OpenFIGI: expected {len(jobs)} result dicts, "
                f"got {len(response)}"
            )

        out: list[FIGIQueryResult] = []
        retrieved_at = utcnow_iso()
        for job, item in zip(jobs, response):
            mappings, warning = _parse_response_item(item)
            df = _mappings_to_frame(mappings)
            lineage = build_lineage(
                df=df,
                contract=FIGI_MAPPING_V1,
                provider_name=PROVIDER_NAME,
                provider_url=PROVIDER_URL,
                retrieved_at_iso=retrieved_at,
                auth_mode=self.auth_mode,
                query_params=dict(job),
                symbol_count=len(mappings),
                extra={
                    "reliability": "OFFICIAL",
                    "source": "OpenFIGI",
                    "rate_limits": RATE_LIMIT_DESCRIPTION,
                    "warning": warning,
                },
            )
            out.append(
                FIGIQueryResult(
                    query=dict(job),
                    mappings=tuple(mappings),
                    is_ambiguous=len(mappings) > 1,
                    warning=warning,
                    provenance=lineage,
                )
            )
        return tuple(out)


    # -- BaseDataProvider plumbing ------------------------------------------

    def _fetch_raw(self, symbol, start, end, **kwargs):  # pragma: no cover
        raise NotImplementedError(
            "openfigi_mapper is an identity-mapping provider; "
            "use map_symbol() / bulk_map()"
        )


def _parse_response_item(
    item: Mapping[str, Any],
) -> tuple[list[FIGIMapping], Optional[str]]:
    """Translate a single OpenFIGI per-job response into mappings + warning.

    OpenFIGI returns one dict per submitted job. Three shapes:
      * ``{"data": [<row>, ...]}``   -- one or more candidates.
      * ``{"warning": "no FIGI match"}`` -- explicit no-match.
      * ``{"error": "..."}``           -- per-job error (rare).
    We treat both warning and error as "no candidates + warning string"
    so callers handle both uniformly. We never silently drop the
    distinction -- the warning text is preserved verbatim.
    """
    if not isinstance(item, Mapping):
        return [], f"unexpected item type: {type(item).__name__}"
    if "data" in item and item["data"]:
        rows = item["data"]
        if not isinstance(rows, Sequence):
            return [], f"unexpected data shape: {type(rows).__name__}"
        mappings = [
            _camel_to_snake_mapping(r)
            for r in rows
            if isinstance(r, Mapping)
        ]
        # Even with a 'data' field, the response can also carry a
        # warning (e.g. when the result set is partial). Surface both.
        warn = _str_or_none(item.get("warning"))
        return mappings, warn
    if "warning" in item:
        return [], _str_or_none(item.get("warning")) or "no FIGI match"
    if "error" in item:
        return [], f"openfigi error: {_str_or_none(item.get('error'))}"
    # Empty 'data' or unknown shape -- treat as no match.
    return [], "no FIGI match"


def _mappings_to_frame(mappings: Sequence[FIGIMapping]) -> pd.DataFrame:
    """Convert :class:`FIGIMapping` records to a stable DataFrame.

    The frame is hashed for provenance via :func:`build_lineage`.
    Column order is the contract field order so the hash is stable
    across pandas versions.
    """
    columns = [f.name for f in FIGI_MAPPING_V1.fields]
    if not mappings:
        return pd.DataFrame(columns=columns)
    rows = []
    for m in mappings:
        rows.append({
            "figi": m.figi,
            "name": m.name,
            "ticker": m.ticker,
            "exchange_code": m.exchange_code,
            "market_sector": m.market_sector,
            "security_type": m.security_type,
            "unique_id": m.unique_id,
            "unique_id_type": m.unique_id_type,
            "currency": m.currency,
            "composite_figi": m.composite_figi,
            "share_class_figi": m.share_class_figi,
        })
    return pd.DataFrame(rows, columns=columns)


__all__ = [
    "ASSET_CLASSES",
    "FIGI_MAPPING_V1",
    "FIGIMapping",
    "FIGIQueryResult",
    "OPENFIGI_DESCRIPTOR",
    "OpenFIGIClient",
    "PROVIDER_NAME",
    "PROVIDER_URL",
    "RATE_LIMIT_DESCRIPTION",
    "descriptor",
]
