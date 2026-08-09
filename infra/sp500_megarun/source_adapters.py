"""Executable adapter registry for the free SP500 mega-run data sources.

The network orchestration is GitHub-only.  These callables are deliberately
small normalization boundaries so fixtures and downloaded raw bytes use the
same code path.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO, StringIO
import re
import zipfile
from xml.etree import ElementTree

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


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _local_attributes(attributes: dict[str, str]) -> dict[str, str]:
    return {_local_name(key): value for key, value in attributes.items()}


def _federal_reserve_zip_xml(
    payload: bytes, *, adapter: str, **_: object
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            members = [
                name
                for name in archive.namelist()
                if not name.endswith("/") and name.lower().endswith(".xml")
            ]
            if not members:
                raise SourceAdapterError(f"ZIP_HAS_NO_XML:{adapter}")
            for member in members:
                current_series: dict[str, str] = {}
                with archive.open(member) as source:
                    for event, element in ElementTree.iterparse(source, events=("start", "end")):
                        tag = _local_name(element.tag)
                        if event == "start" and tag == "Series":
                            current_series = _local_attributes(element.attrib)
                        elif event == "end" and tag == "Obs":
                            observation = _local_attributes(element.attrib)
                            raw_date = observation.get("TIME_PERIOD") or observation.get("time_period")
                            raw_value = observation.get("OBS_VALUE") or observation.get("obs_value")
                            if raw_date and raw_value not in {None, "", "ND"}:
                                rows.append(
                                    {
                                        "date": raw_date,
                                        "value": raw_value,
                                        "series_id": current_series.get("SERIES_ID")
                                        or current_series.get("SERIES_NAME")
                                        or current_series.get("SERIES_TITLE")
                                        or "unknown",
                                        "series_name": current_series.get("SERIES_NAME", ""),
                                        "frequency": current_series.get("FREQ", ""),
                                        "unit": current_series.get("UNIT", ""),
                                        "source_file": member,
                                    }
                                )
                            element.clear()
                        elif event == "end" and tag == "Series":
                            current_series = {}
                            element.clear()
    except SourceAdapterError:
        raise
    except Exception as exc:
        raise SourceAdapterError(f"FEDERAL_RESERVE_XML_PARSE_FAILED:{adapter}") from exc
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise SourceAdapterError(f"FEDERAL_RESERVE_XML_HAS_NO_OBSERVATIONS:{adapter}")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return _nonempty(frame, adapter=adapter)


def _french_zip(payload: bytes, *, adapter: str, **_: object) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            members = sorted(
                name
                for name in archive.namelist()
                if not name.endswith("/") and name.lower().endswith((".csv", ".txt"))
            )
            for member in members:
                text = archive.read(member).decode("utf-8-sig", errors="replace")
                lines = text.splitlines()
                header_index = next(
                    (
                        index
                        for index, line in enumerate(lines[:-1])
                        if "," in line and re.match(r"^\s*\d{8}\s*,", lines[index + 1])
                    ),
                    None,
                )
                if header_index is None:
                    continue
                data_lines = [lines[header_index]]
                for line in lines[header_index + 1 :]:
                    if not re.match(r"^\s*\d{8}\s*,", line):
                        break
                    data_lines.append(line)
                frame = pd.read_csv(StringIO("\n".join(data_lines)))
                first = str(frame.columns[0])
                frame = frame.rename(columns={first: "date"})
                frames.append(frame)
    except Exception as exc:
        raise SourceAdapterError(f"FRENCH_ZIP_PARSE_FAILED:{adapter}") from exc
    if not frames:
        raise SourceAdapterError(f"FRENCH_ZIP_HAS_NO_DAILY_TABLE:{adapter}")
    return _nonempty(pd.concat(frames, ignore_index=True, sort=False), adapter=adapter)


def _read_resource_format(
    payload: bytes, *, adapter: str, format_name: str
) -> pd.DataFrame:
    if adapter == "federal_reserve_ddp_zip_xml" or format_name == "zip_xml":
        return _federal_reserve_zip_xml(payload, adapter=adapter)
    if adapter == "french_zip_csv":
        return _french_zip(payload, adapter=adapter)
    if format_name in {"zip_csv", "zip_txt"}:
        return _zip_table(payload, adapter=adapter)
    if format_name in {"xls", "xlsx"}:
        return _excel(payload, adapter=adapter)
    if format_name == "csv":
        return _csv(payload, adapter=adapter)
    if format_name.startswith("html"):
        return _html(payload, adapter=adapter)
    return _auto_table(payload, adapter=adapter)


def _candidate_dates(values: pd.Series) -> pd.Series:
    cleaned = values.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    result = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    eight = cleaned.str.fullmatch(r"\d{8}")
    six = cleaned.str.fullmatch(r"\d{6}")
    four = cleaned.str.fullmatch(r"\d{4}")
    result.loc[eight] = pd.to_datetime(cleaned.loc[eight], format="%Y%m%d", errors="coerce")
    result.loc[six] = pd.to_datetime(cleaned.loc[six], format="%Y%m", errors="coerce")
    result.loc[four] = pd.to_datetime(cleaned.loc[four], format="%Y", errors="coerce")
    remaining = result.isna() & ~(eight | six | four)
    if remaining.any():
        result.loc[remaining] = pd.to_datetime(cleaned.loc[remaining], errors="coerce")
    return result


def _normalize_and_bound_dates(
    frame: pd.DataFrame, *, adapter: str, maximum_observation_date: str
) -> pd.DataFrame:
    preferred = {
        "date",
        "observation_date",
        "time_period",
        "month",
        "year",
        "period",
        "session",
    }
    candidates = [column for column in frame.columns if str(column).strip().lower() in preferred]
    candidates.extend(column for column in frame.columns[:2] if column not in candidates)
    selected: pd.Series | None = None
    for column in candidates:
        parsed = _candidate_dates(frame[column])
        if int(parsed.notna().sum()) >= max(1, min(3, len(frame))):
            selected = parsed
            break
    if selected is None:
        raise SourceAdapterError(f"DATE_COLUMN_MISSING:{adapter}")
    bounded = frame.copy()
    bounded["date"] = selected
    ceiling = pd.Timestamp(maximum_observation_date)
    bounded = bounded.loc[bounded["date"].notna() & (bounded["date"] <= ceiling)].copy()
    if "value" in bounded:
        bounded["value"] = pd.to_numeric(bounded["value"], errors="coerce")
    return _nonempty(bounded.sort_values("date", kind="mergesort"), adapter=adapter)


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
    "alfred_philly_pit_bundle": _auto_table,
    "federal_reserve_ddp_zip_xml": _auto_table,
    "world_bank_pink_sheet": _auto_table,
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


def normalize_resource_payload(
    adapter: str,
    payload: bytes,
    *,
    format_name: str,
    resource_id: str,
    maximum_observation_date: str,
) -> pd.DataFrame:
    """Normalize one declared resource and reject rows beyond evaluation."""

    if adapter not in _ADAPTERS:
        raise SourceAdapterError(f"UNKNOWN_ADAPTER:{adapter}")
    frame = _read_resource_format(payload, adapter=adapter, format_name=format_name)
    frame = _normalize_and_bound_dates(
        frame,
        adapter=adapter,
        maximum_observation_date=maximum_observation_date,
    )
    frame["resource_id"] = resource_id
    return frame.reset_index(drop=True)
