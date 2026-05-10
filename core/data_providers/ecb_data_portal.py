"""ECB Data Portal provider (R156 FX_REFERENCE).

The European Central Bank publishes euro-area macro, interest rates and
EUR FX reference rates through a public SDMX 2.1 REST API:

    GET https://data-api.ecb.europa.eu/service/data/{dataflow}/{key}

The most common use is the EUR FX reference rates (dataflow ``EXR``).
The series key for daily USD reference rate is e.g.
``D.USD.EUR.SP00.A`` (frequency=Daily, currency=USD, base=EUR,
type=SP00 spot, exchange-rate variation A).

We parse the SDMX-JSON response (Accept:
``application/vnd.sdmx.data+json;version=1.0.0-wd``). Tests inject
``http_get`` so the network is never touched.

Per R156 spec, ECB FX reference rates are macro/context series, not
tradeable assets: lineage is stamped with ``asset_class="MACRO"`` and
``library="macro_multisource"``.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
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


PROVIDER_NAME = "ecb_data_portal"
PROVIDER_URL = "https://data.ecb.europa.eu/"
API_BASE = "https://data-api.ecb.europa.eu/service/data"

ACCEPT_HEADER = "application/vnd.sdmx.data+json;version=1.0.0-wd"


ECB_DESCRIPTOR = ProviderDescriptor(
    name=PROVIDER_NAME,
    role=ProviderRole.FX_REFERENCE,
    licence_terms_url="https://data.ecb.europa.eu/help/data-policy",
    rate_limits="reasonable / no documented hard cap",
    auth_required=False,
    asset_classes=("fx", "macro"),
    intervals=("daily",),
    adjustment_posture="RAW",
    reliability="OFFICIAL",
)


# ---------------------------------------------------------------------------
# Frozen records.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ECBSeriesKey:
    """SDMX dataflow + series key pair."""

    dataflow: str
    key: str

    def __post_init__(self) -> None:
        if not isinstance(self.dataflow, str) or not self.dataflow.strip():
            raise ValueError("ECBSeriesKey.dataflow must be a non-empty string")
        if not isinstance(self.key, str) or not self.key.strip():
            raise ValueError("ECBSeriesKey.key must be a non-empty string")


@dataclass(frozen=True)
class ECBObservation:
    """One observation point on an ECB series.

    ``obs_status`` follows SDMX coded list (CL_OBS_STATUS): ``"A"``
    means normal, ``"M"`` means missing, ``"E"`` means estimated, etc.
    """

    period_iso: str
    value: float
    obs_status: str = "A"


@dataclass(frozen=True)
class ECBSeries:
    """Resolved ECB series with provenance."""

    key: ECBSeriesKey
    title: str
    unit: str
    frequency: str
    observations: Tuple[ECBObservation, ...]
    provenance: FreeBulkLineage


# ---------------------------------------------------------------------------
# Client.
# ---------------------------------------------------------------------------


def _default_http_get(
    url: str,
    params: Optional[Mapping[str, Any]] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> str:
    """Default HTTP client. Tests must inject."""
    raise ProviderUnavailable(
        "ecb_data_portal: no http_get injected; tests must provide a "
        "fixture-backed client."
    )


class ECBClient(BaseDataProvider):
    """Fetch ECB SDMX-JSON series with an injectable HTTP getter.

    Extends :class:`BaseDataProvider` so the role-aware registry can
    hold this provider alongside OHLCV providers; the OHLCV ``fetch``
    contract is intentionally not implemented because ECB serves
    macro/FX-reference series.
    """

    name: str = PROVIDER_NAME
    version: str = "ecb_data_portal:1.0"
    point_in_time: bool = True
    tier_permission: str = "ANY"
    schema_version: str = "1.0"

    def __init__(
        self,
        http_get: Optional[
            Callable[
                [str, Optional[Mapping[str, Any]], Optional[Mapping[str, str]]],
                str,
            ]
        ] = None,
    ) -> None:
        self._http_get = http_get or _default_http_get

    # -- public API ---------------------------------------------------------

    def fetch_eur_fx_reference_rate(
        self,
        currency_pair: str,
        *,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> ECBSeries:
        """Convenience for the EXR dataflow EUR FX reference rate.

        ``currency_pair`` accepts ``"USD"``, ``"USD/EUR"`` or
        ``"EURUSD"``-style strings; only the foreign currency component
        is required because EUR is always the base. Returns the daily
        spot reference rate (``D.{ccy}.EUR.SP00.A``).
        """
        ccy = self._normalise_foreign_currency(currency_pair)
        series_key = ECBSeriesKey(
            dataflow="EXR",
            key=f"D.{ccy}.EUR.SP00.A",
        )
        return self.fetch_series(series_key, start=start, end=end)

    def fetch_series(
        self,
        series_key: ECBSeriesKey,
        *,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> ECBSeries:
        """Fetch a series by SDMX dataflow + key.

        Honours optional ``startPeriod`` / ``endPeriod`` filters
        (ISO dates).
        """
        if not isinstance(series_key, ECBSeriesKey):
            raise TypeError(
                "series_key must be an ECBSeriesKey; "
                f"got {type(series_key).__name__}"
            )
        url = f"{API_BASE}/{series_key.dataflow}/{series_key.key}"
        params: dict[str, Any] = {"format": "jsondata"}
        if start:
            params["startPeriod"] = start
        if end:
            params["endPeriod"] = end
        body = self._http_get(url, params, {"Accept": ACCEPT_HEADER})
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ProviderUnavailable(
                f"ecb_data_portal: response is not JSON: {exc}"
            ) from exc
        return self._parse_sdmx_json(series_key, payload, params)

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _normalise_foreign_currency(currency_pair: str) -> str:
        if not isinstance(currency_pair, str) or not currency_pair.strip():
            raise ValueError("currency_pair must be a non-empty string")
        cp = currency_pair.upper().strip()
        # Accept "USD", "USD/EUR", "USDEUR", "EUR/USD", "EURUSD".
        for sep in ("/", "-", "_"):
            if sep in cp:
                left, _, right = cp.partition(sep)
                if left == "EUR":
                    return right
                if right == "EUR":
                    return left
                # No EUR side: assume the left side is the foreign ccy.
                return left
        if len(cp) == 6:
            left, right = cp[:3], cp[3:]
            if left == "EUR":
                return right
            if right == "EUR":
                return left
            return left
        if len(cp) == 3:
            return cp
        raise ValueError(
            f"currency_pair {currency_pair!r} not recognised; "
            "expected forms: 'USD', 'USD/EUR', 'EURUSD'"
        )

    def _parse_sdmx_json(
        self,
        series_key: ECBSeriesKey,
        payload: Mapping[str, Any],
        query_params: Mapping[str, Any],
    ) -> ECBSeries:
        # SDMX-JSON has the shape:
        # { "header": {...},
        #   "dataSets": [{"series": {"0:0:0:0:0": {"observations": {"0": [v, st, ...]}}}}],
        #   "structure": {"name":..., "dimensions":{"observation":[{"id":"TIME_PERIOD","values":[{"id":"2024-01-02"}, ...]}]}, "attributes": {...} } }
        data_sets = payload.get("dataSets") or []
        structure = payload.get("structure") or {}
        if not data_sets:
            raise ProviderUnavailable(
                f"ecb_data_portal: empty dataSets for {series_key.dataflow}/"
                f"{series_key.key}"
            )
        series_dict = data_sets[0].get("series") or {}
        if not series_dict:
            raise ProviderUnavailable(
                f"ecb_data_portal: no series in response for "
                f"{series_key.dataflow}/{series_key.key}"
            )
        # Take the first (and typically only) series block.
        first_key = next(iter(series_dict.keys()))
        series_block = series_dict[first_key]
        observations_block = series_block.get("observations") or {}

        obs_dims = (
            structure.get("dimensions", {}).get("observation", [])
        )
        # Find TIME_PERIOD dimension values list.
        time_values: list[str] = []
        for d in obs_dims:
            if d.get("id") in ("TIME_PERIOD", "TIME"):
                time_values = [str(v.get("id", "")) for v in d.get("values", [])]
                break

        # Find OBS_STATUS attribute index, if present.
        obs_attrs = structure.get("attributes", {}).get("observation", [])
        status_attr_pos: Optional[int] = None
        status_values: list[str] = []
        for i, attr in enumerate(obs_attrs):
            if attr.get("id") == "OBS_STATUS":
                status_attr_pos = i
                status_values = [
                    str(v.get("id", "A")) for v in attr.get("values", [])
                ]
                break

        observations: list[ECBObservation] = []
        for idx_str, obs_arr in observations_block.items():
            try:
                pos = int(idx_str)
            except (TypeError, ValueError):
                continue
            if pos < 0 or pos >= len(time_values):
                continue
            period_iso = time_values[pos]
            if not isinstance(obs_arr, list) or not obs_arr:
                continue
            try:
                value = float(obs_arr[0]) if obs_arr[0] is not None else float("nan")
            except (TypeError, ValueError):
                value = float("nan")
            obs_status = "A"
            if status_attr_pos is not None and len(obs_arr) > 1 + status_attr_pos:
                idx = obs_arr[1 + status_attr_pos]
                if isinstance(idx, int) and 0 <= idx < len(status_values):
                    obs_status = status_values[idx]
            observations.append(
                ECBObservation(
                    period_iso=period_iso,
                    value=value,
                    obs_status=obs_status,
                )
            )
        observations.sort(key=lambda o: o.period_iso)
        title = str(structure.get("name", "") or "")
        # Frequency lives in the series-level dimensions; keep "daily" as
        # the safe default since this provider declares ``intervals=("daily",)``.
        frequency = "daily"
        # Unit: ECB exposes UNIT_MULT / UNIT in series attrs; fall back
        # to the dataflow code so consumers see something meaningful.
        unit = self._extract_unit(structure)

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
                "dataflow": series_key.dataflow,
                "key": series_key.key,
                **{k: v for k, v in query_params.items() if k != "format"},
            },
            snapshot_hash=snapshot_hash,
            symbol_count=1,
            extra={
                "reliability": "OFFICIAL",
                "source": "ECB",
                "asset_class": "MACRO",
                "library": "macro_multisource",
                "tradeable": False,
                "dataflow": series_key.dataflow,
                "series_key": series_key.key,
                "sdmx_format": "json",
            },
        )
        return ECBSeries(
            key=series_key,
            title=title,
            unit=unit,
            frequency=frequency,
            observations=tuple(observations),
            provenance=provenance,
        )

    @staticmethod
    def _extract_unit(structure: Mapping[str, Any]) -> str:
        series_attrs = structure.get("attributes", {}).get("series", [])
        for attr in series_attrs:
            if attr.get("id") in ("UNIT", "UNIT_MEASURE"):
                values = attr.get("values", [])
                if values:
                    return str(values[0].get("id", "") or values[0].get("name", ""))
        return ""

    @staticmethod
    def _observations_to_frame(
        observations: list[ECBObservation] | Tuple[ECBObservation, ...],
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
    return ECB_DESCRIPTOR


__all__ = [
    "ACCEPT_HEADER",
    "API_BASE",
    "ECB_DESCRIPTOR",
    "ECBClient",
    "ECBObservation",
    "ECBSeries",
    "ECBSeriesKey",
    "PROVIDER_NAME",
    "PROVIDER_URL",
    "descriptor",
]
