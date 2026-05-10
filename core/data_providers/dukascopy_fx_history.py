"""Dukascopy FX history provider (R156 deferred, FX_TICK_RESEARCH).

Dukascopy publishes free historical FX / CFD tick and bar data via the
``datafeed.dukascopy.com`` endpoint. Bars are served as LZMA-compressed
``.bi5`` files. This provider is a minimal scaffold that is gated behind
``AU_ENABLE_DUKASCOPY=1`` so it never runs as part of a default ingestion
job. Tests inject a pre-decoded HTTP client; the production decoder is
left as a follow-up because Aurora's current focus remains daily
equities.

The provider does NOT decompress ``.bi5`` files itself; the injectable
``http_get`` callable is expected to return a tuple of bar tuples (the
test client mocks the binary path). Wiring real decompression is a
separate task.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Optional, Tuple

from . import ProviderDescriptor, ProviderRole
from ._free_bulk_common import FreeBulkLineage, utcnow_iso
from aurora.data_contracts.lineage import DataLineage

_log = logging.getLogger(__name__)


PROVIDER_NAME = "dukascopy_fx_history"
PROVIDER_URL = "https://datafeed.dukascopy.com/datafeed/"
ENABLE_ENV_VAR = "AU_ENABLE_DUKASCOPY"

DukascopyInterval = Literal["M1", "M5", "H1", "D1"]


DUKASCOPY_DESCRIPTOR = ProviderDescriptor(
    name=PROVIDER_NAME,
    role=ProviderRole.FX_TICK_RESEARCH,
    licence_terms_url=(
        "https://www.dukascopy.com/swiss/english/marketwatch/historical/"
    ),
    rate_limits="historical batch download",
    auth_required=False,
    asset_classes=("fx", "cfd"),
    intervals=("tick", "minute", "hour", "daily"),
    adjustment_posture="RAW",
    reliability="COMMUNITY",
)


def _check_gate() -> None:
    """Refuse to construct unless ``AU_ENABLE_DUKASCOPY=1``.

    Module import does not trip the gate because :data:`DUKASCOPY_DESCRIPTOR`
    is a pure data object that the registry consults to advertise the
    provider. The gate fires when callers actually try to open a client.
    """
    if os.environ.get(ENABLE_ENV_VAR, "") != "1":
        raise RuntimeError(
            "Dukascopy FX provider is gated; set "
            f"{ENABLE_ENV_VAR}=1 to opt in. Dukascopy is intended for "
            "intraday FX research and is not approved for default "
            "daily-equity ingestion."
        )


@dataclass(frozen=True)
class DukascopyTick:
    """A single Dukascopy tick (millisecond resolution)."""

    time_iso: str
    bid: float
    ask: float
    bid_volume: float
    ask_volume: float


@dataclass(frozen=True)
class DukascopyBar:
    """A single Dukascopy bar at a declared interval."""

    time_iso: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    interval: DukascopyInterval


@dataclass(frozen=True)
class DukascopyFXSeries:
    """A typed FX series with provenance.

    Attributes:
        instrument: e.g. ``"EURUSD"``.
        bars: tuple of :class:`DukascopyBar` in chronological order.
        provenance: :class:`FreeBulkLineage` carrier.
    """

    instrument: str
    bars: Tuple[DukascopyBar, ...]
    provenance: FreeBulkLineage


HttpGet = Callable[[str, Mapping[str, Any]], Tuple[Tuple[Any, ...], ...]]


def _default_http_get(
    url: str, params: Mapping[str, Any]
) -> Tuple[Tuple[Any, ...], ...]:  # pragma: no cover - production path
    raise RuntimeError(
        "DukascopyClient requires an injected http_get callable. "
        "The default production HTTP path (LZMA .bi5 decompression) "
        "is intentionally not wired in this deferred scaffold."
    )


class DukascopyClient:
    """Minimal Dukascopy FX client with an injectable HTTP callable.

    The HTTP callable receives ``(url, query_params)`` and returns a
    tuple of pre-decoded bar tuples. Each bar tuple is in the order
    ``(time_iso, open, high, low, close, volume)``.
    """

    def __init__(self, http_get: Optional[HttpGet] = None) -> None:
        _check_gate()
        self._http_get = http_get or _default_http_get

    def fetch_bars(
        self,
        instrument: str,
        *,
        start: str,
        end: str,
        interval: DukascopyInterval = "D1",
    ) -> DukascopyFXSeries:
        if not isinstance(instrument, str) or not instrument:
            raise ValueError("instrument must be a non-empty string")
        if interval not in ("M1", "M5", "H1", "D1"):
            raise ValueError(
                f"interval={interval!r} not in {{'M1','M5','H1','D1'}}"
            )
        params: Mapping[str, Any] = {
            "instrument": instrument,
            "start": start,
            "end": end,
            "interval": interval,
        }
        url = f"{PROVIDER_URL}{instrument}/bars/{interval}"
        rows = self._http_get(url, params)
        bars = tuple(
            DukascopyBar(
                time_iso=str(r[0]),
                open=float(r[1]),
                high=float(r[2]),
                low=float(r[3]),
                close=float(r[4]),
                volume=float(r[5]),
                interval=interval,
            )
            for r in rows
        )
        provenance = self._build_provenance(
            instrument=instrument,
            params=params,
            bar_count=len(bars),
            date_range=(
                (bars[0].time_iso, bars[-1].time_iso) if bars else ("", "")
            ),
        )
        return DukascopyFXSeries(
            instrument=instrument,
            bars=bars,
            provenance=provenance,
        )

    @staticmethod
    def _build_provenance(
        *,
        instrument: str,
        params: Mapping[str, Any],
        bar_count: int,
        date_range: Tuple[str, str],
    ) -> FreeBulkLineage:
        retrieved = utcnow_iso()
        lineage = DataLineage(
            input_dataset_hash=retrieved,
            transformation_chain=("dukascopy_fetch_bars",),
            code_version="aurora-r156",
            contract_version="dukascopy_bars_v0",
            snapshot_hash="",
            validator_version="0.0",
            decision_outcome="accepted",
            contract_hash="",
        )
        return FreeBulkLineage(
            lineage=lineage,
            provider_name=PROVIDER_NAME,
            provider_url=PROVIDER_URL,
            retrieved_at_iso=retrieved,
            auth_mode="none",
            query_params=dict(params),
            row_count=int(bar_count),
            date_range=date_range,
            symbol_count=1,
            extra={
                "asset_class": "fx",
                "reliability": "COMMUNITY",
                "adjustment_posture": "RAW",
                "instrument": instrument,
                "deferred_scaffold": True,
                "warning": (
                    "Dukascopy is a deferred R156 scaffold; production "
                    ".bi5 decompression is not wired."
                ),
            },
        )


def descriptor() -> ProviderDescriptor:
    """Return the static :class:`ProviderDescriptor` for the registry."""
    return DUKASCOPY_DESCRIPTOR


__all__ = [
    "DUKASCOPY_DESCRIPTOR",
    "DukascopyBar",
    "DukascopyClient",
    "DukascopyFXSeries",
    "DukascopyTick",
    "ENABLE_ENV_VAR",
    "PROVIDER_NAME",
    "PROVIDER_URL",
    "descriptor",
]
