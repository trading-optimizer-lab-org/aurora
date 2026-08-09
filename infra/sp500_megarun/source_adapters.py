"""Executable adapter registry for the free SP500 mega-run data sources.

The network orchestration is GitHub-only.  These callables are deliberately
small normalization boundaries so fixtures and downloaded raw bytes use the
same code path.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO, StringIO
import zipfile

import pandas as pd


class SourceAdapterError(ValueError):
    """Raised when raw source bytes cannot be normalized safely."""


@dataclass(frozen=True)
class SourceAdapter:
    name: str
    normalize: object


def _nonempty(frame: pd.DataFrame, *, adapter: str) -> pd.DataFrame:
    frame = frame.dropna(how="all").copy()
    if frame.empty:
        raise SourceAdapterError(f"EMPTY_NORMALIZED_DATA:{adapter}")
    return frame


def _csv(payload: bytes, *, adapter: str, **_: object) -> pd.DataFrame:
    try:
        frame = pd.read_csv(BytesIO(payload))
    except Exception as exc:
        raise SourceAdapterError(f"CSV_PARSE_FAILED:{adapter}") from exc
    return _nonempty(frame, adapter=adapter)


def _zip_table(payload: bytes, *, adapter: str, **_: object) -> pd.DataFrame:
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            candidates = sorted(
                name
                for name in archive.namelist()
                if not name.endswith("/") and name.lower().endswith((".csv", ".txt"))
            )
            if not candidates:
                raise SourceAdapterError(f"ZIP_HAS_NO_TABLE:{adapter}")
            raw = archive.read(candidates[0])
    except SourceAdapterError:
        raise
    except Exception as exc:
        raise SourceAdapterError(f"ZIP_PARSE_FAILED:{adapter}") from exc
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        frame = pd.read_csv(StringIO(text), sep=None, engine="python")
    except Exception as exc:
        raise SourceAdapterError(f"ZIP_TABLE_PARSE_FAILED:{adapter}") from exc
    return _nonempty(frame, adapter=adapter)


def _excel(payload: bytes, *, adapter: str, **_: object) -> pd.DataFrame:
    try:
        frame = pd.read_excel(BytesIO(payload))
    except Exception as exc:
        raise SourceAdapterError(f"EXCEL_PARSE_FAILED:{adapter}") from exc
    return _nonempty(frame, adapter=adapter)


def _html(payload: bytes, *, adapter: str, **_: object) -> pd.DataFrame:
    try:
        tables = pd.read_html(StringIO(payload.decode("utf-8", errors="replace")))
    except Exception as exc:
        raise SourceAdapterError(f"HTML_TABLE_PARSE_FAILED:{adapter}") from exc
    if not tables:
        raise SourceAdapterError(f"HTML_HAS_NO_TABLE:{adapter}")
    return _nonempty(tables[0], adapter=adapter)


def _auto_table(payload: bytes, *, adapter: str, **kwargs: object) -> pd.DataFrame:
    if payload.startswith(b"PK\x03\x04"):
        try:
            return _zip_table(payload, adapter=adapter, **kwargs)
        except SourceAdapterError:
            return _excel(payload, adapter=adapter, **kwargs)
    prefix = payload[:512].lstrip().lower()
    if prefix.startswith((b"<!doctype html", b"<html", b"<table")):
        return _html(payload, adapter=adapter, **kwargs)
    return _csv(payload, adapter=adapter, **kwargs)


def _spy_snapshot(payload: bytes, *, adapter: str, **kwargs: object) -> pd.DataFrame:
    return _auto_table(payload, adapter=adapter, **kwargs)


def _derived_calendar(payload: bytes, *, adapter: str, **kwargs: object) -> pd.DataFrame:
    frame = _auto_table(payload, adapter=adapter, **kwargs)
    date_columns = [column for column in frame.columns if str(column).lower() in {"date", "session"}]
    if not date_columns:
        raise SourceAdapterError(f"CALENDAR_DATE_COLUMN_MISSING:{adapter}")
    dates = pd.to_datetime(frame[date_columns[0]], errors="coerce")
    result = pd.DataFrame({"date": dates}).dropna().drop_duplicates().sort_values("date")
    return _nonempty(result, adapter=adapter)


_ADAPTERS = {
    "existing_spy_snapshot": _spy_snapshot,
    "cboe_history_csv": _auto_table,
    "cboe_causal_vol30_bridge": _auto_table,
    "cftc_legacy_zip": _zip_table,
    "fred_alfred_bundle": _auto_table,
    "alfred_initial_bundle": _auto_table,
    "philadelphia_realtime_bundle": _auto_table,
    "derived_conditions_composite": _auto_table,
    "derived_uncertainty_composite": _auto_table,
    "finra_margin_xlsx": _auto_table,
    "aaii_history_xlsx": _auto_table,
    "academic_table": _auto_table,
    "french_zip_csv": _zip_table,
    "occ_historical_volume": _auto_table,
    "derived_spy_calendar": _derived_calendar,
}


def registered_adapter_names() -> set[str]:
    """Return adapter names backed by normalization callables."""

    return set(_ADAPTERS)


def normalize_source_payload(adapter: str, payload: bytes) -> pd.DataFrame:
    """Normalize one raw payload through the named fail-closed adapter."""

    try:
        normalizer = _ADAPTERS[adapter]
    except KeyError as exc:
        raise SourceAdapterError(f"UNKNOWN_ADAPTER:{adapter}") from exc
    return normalizer(payload, adapter=adapter)
