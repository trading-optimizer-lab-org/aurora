"""Executable adapter registry for the free SP500 mega-run data sources.

The network orchestration is GitHub-only.  These callables are deliberately
small normalization boundaries so fixtures and downloaded raw bytes use the
same code path.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO, StringIO
import re
from typing import Mapping
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


def _excel_without_header(payload: bytes, *, adapter: str, **_: object) -> pd.DataFrame:
    try:
        sheets = pd.read_excel(BytesIO(payload), sheet_name=None, header=None)
    except Exception as exc:
        try:
            sheets = pd.read_excel(
                BytesIO(payload), sheet_name=None, header=None, engine="calamine"
            )
        except Exception as fallback_exc:
            raise SourceAdapterError(
                f"EXCEL_PARSE_FAILED:{adapter}:{type(exc).__name__}:{str(exc)[:120]}:"
                f"CALAMINE:{type(fallback_exc).__name__}:{str(fallback_exc)[:120]}"
            ) from fallback_exc
    frames: list[pd.DataFrame] = []
    for sheet_name, frame in sheets.items():
        if frame.dropna(how="all").empty:
            continue
        copy = frame.copy()
        copy["source_sheet"] = str(sheet_name)
        frames.append(copy)
    if not frames:
        raise SourceAdapterError(f"EXCEL_HAS_NO_TABLE:{adapter}")
    data_frames = [
        frame
        for frame in frames
        if not str(frame["source_sheet"].iloc[0]).strip().casefold().startswith(
            ("note", "doc", "readme")
        )
    ]
    if data_frames:
        frames = data_frames
    return _nonempty(pd.concat(frames, ignore_index=True, sort=False), adapter=adapter)


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
            members = sorted(name for name in archive.namelist() if not name.endswith("/"))
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


def _cftc_zip(payload: bytes, *, adapter: str, **_: object) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    inspected: list[str] = []
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            members = sorted(name for name in archive.namelist() if not name.endswith("/"))
            for member in members:
                raw = archive.read(member)
                inspected.append(f"{member}:{len(raw)}")
                if not raw.strip():
                    continue
                if raw.startswith(b"PK\x03\x04"):
                    try:
                        nested = _cftc_zip(raw, adapter=adapter)
                    except SourceAdapterError:
                        continue
                    nested["source_file"] = f"{member}!" + nested["source_file"].astype(str)
                    frames.append(nested)
                    continue
                if raw.startswith(b"\xd0\xcf\x11\xe0"):
                    try:
                        frame = pd.read_excel(BytesIO(raw), header=None)
                    except Exception:
                        continue
                    frame["source_file"] = member
                    frames.append(frame)
                    continue
                try:
                    frame = pd.read_csv(
                        BytesIO(raw),
                        sep=",",
                        encoding="cp1252",
                        engine="python",
                        on_bad_lines="skip",
                    )
                except pd.errors.EmptyDataError:
                    frame = pd.DataFrame()
                if frame.dropna(how="all").empty:
                    try:
                        frame = pd.read_fwf(StringIO(raw.decode("cp1252", errors="replace")))
                    except Exception:
                        frame = pd.DataFrame()
                if not frame.dropna(how="all").empty:
                    frame["source_file"] = member
                    frames.append(frame)
    except Exception as exc:
        raise SourceAdapterError(
            f"CFTC_ZIP_PARSE_FAILED:{adapter}:{type(exc).__name__}:{str(exc)[:200]}"
        ) from exc
    if not frames:
        raise SourceAdapterError(
            f"CFTC_ZIP_HAS_NO_ROWS:{adapter}:MEMBERS:{'|'.join(inspected)[:500]}"
        )
    return _nonempty(pd.concat(frames, ignore_index=True, sort=False), adapter=adapter)


def _world_bank_monthly(
    payload: bytes, *, adapter: str, resource_metadata: Mapping[str, object]
) -> pd.DataFrame:
    requested = str(resource_metadata.get("series", "")).strip().casefold()
    if not requested:
        raise SourceAdapterError(f"WORLD_BANK_SERIES_MISSING:{adapter}")
    try:
        sheets = pd.read_excel(BytesIO(payload), sheet_name=None, header=None)
    except Exception as exc:
        raise SourceAdapterError(
            f"WORLD_BANK_EXCEL_PARSE_FAILED:{type(exc).__name__}:{str(exc)[:200]}"
        ) from exc
    for sheet_name, raw in sheets.items():
        for row_index in range(min(30, len(raw))):
            labels = [str(value).strip() if pd.notna(value) else "" for value in raw.iloc[row_index]]
            lowered = [value.casefold() for value in labels]
            date_indexes = [index for index, value in enumerate(lowered) if value == "date"]
            series_indexes = [
                index
                for index, value in enumerate(lowered)
                if value and (requested in value or value in requested)
            ]
            if not series_indexes:
                continue
            date_index = date_indexes[0] if date_indexes else 0
            series_index = series_indexes[0]
            frame = raw.iloc[row_index + 1 :, [date_index, series_index]].copy()
            frame.columns = ["date", "value"]
            frame["series_name"] = labels[series_index]
            frame["source_sheet"] = str(sheet_name)
            return _nonempty(frame, adapter=adapter)
    raise SourceAdapterError(f"WORLD_BANK_SERIES_NOT_FOUND:{adapter}:{requested}")


def _read_resource_format(
    payload: bytes,
    *,
    adapter: str,
    format_name: str,
    resource_metadata: Mapping[str, object],
) -> pd.DataFrame:
    if adapter == "federal_reserve_ddp_zip_xml" or format_name == "zip_xml":
        return _federal_reserve_zip_xml(payload, adapter=adapter)
    if adapter == "french_zip_csv":
        return _french_zip(payload, adapter=adapter)
    if adapter == "cftc_legacy_zip":
        return _cftc_zip(payload, adapter=adapter)
    if adapter == "world_bank_pink_sheet":
        return _world_bank_monthly(
            payload,
            adapter=adapter,
            resource_metadata=resource_metadata,
        )
    if format_name in {"zip_csv", "zip_txt"}:
        return _zip_table(payload, adapter=adapter)
    if format_name in {"xls", "xlsx"}:
        if adapter in {
            "alfred_philly_pit_bundle",
            "philadelphia_realtime_bundle",
            "shiller_monthly_excel",
            "cboe_history_csv",
            "cboe_causal_vol30_bridge",
        }:
            return _excel_without_header(payload, adapter=adapter)
        return _excel(payload, adapter=adapter)
    if format_name == "csv":
        return _csv(payload, adapter=adapter)
    if format_name.startswith("html"):
        return _html(payload, adapter=adapter)
    return _auto_table(payload, adapter=adapter)


def _candidate_dates(values: pd.Series, *, column_name: str = "") -> pd.Series:
    cleaned = values.astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    result = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    eight_raw = cleaned.str.fullmatch(r"\d{8}")
    eight_years = pd.to_numeric(cleaned.str[:4].where(eight_raw), errors="coerce")
    eight = eight_raw & eight_years.between(1800, 2100)
    six_raw = cleaned.str.fullmatch(r"\d{6}")
    four_raw = cleaned.str.fullmatch(r"\d{4}")
    four_years = pd.to_numeric(cleaned.where(four_raw), errors="coerce")
    four = four_raw & four_years.between(1800, 2100)
    result.loc[eight] = pd.to_datetime(cleaned.loc[eight], format="%Y%m%d", errors="coerce")
    if "yymmdd" in column_name.casefold():
        result.loc[six_raw] = pd.to_datetime(
            cleaned.loc[six_raw], format="%y%m%d", errors="coerce"
        )
        six = six_raw
    else:
        years = pd.to_numeric(cleaned.str[:4], errors="coerce")
        months = pd.to_numeric(cleaned.str[4:], errors="coerce")
        valid_six = six_raw & years.between(1800, 2100) & months.between(1, 12)
        result.loc[valid_six] = pd.to_datetime(
            cleaned.loc[valid_six], format="%Y%m", errors="coerce"
        )
        six = valid_six
    result.loc[four] = pd.to_datetime(cleaned.loc[four], format="%Y", errors="coerce")
    world_bank_raw = cleaned.str.fullmatch(r"\d{4}M\d{2}", case=False)
    world_bank_years = pd.to_numeric(cleaned.str[:4].where(world_bank_raw), errors="coerce")
    world_bank_month = world_bank_raw & world_bank_years.between(1800, 2100)
    result.loc[world_bank_month] = pd.to_datetime(
        cleaned.loc[world_bank_month].str.replace("M", "", case=False),
        format="%Y%m",
        errors="coerce",
    )
    quarter_raw = cleaned.str.fullmatch(r"\d{4}Q[1-4]", case=False)
    quarter_years = pd.to_numeric(cleaned.str[:4].where(quarter_raw), errors="coerce")
    quarter = quarter_raw & quarter_years.between(1800, 2100)
    if quarter.any():
        quarter_values = cleaned.loc[quarter].str.upper()
        result.loc[quarter] = pd.PeriodIndex(quarter_values, freq="Q").to_timestamp()
    quarter_variant_raw = cleaned.str.fullmatch(r"\d{4}\s*[: -]?\s*Q[1-4]", case=False)
    quarter_variant = quarter_variant_raw & ~quarter_raw
    if quarter_variant.any():
        normalized_quarters = cleaned.loc[quarter_variant].str.upper().str.replace(
            r"\s*[: -]?\s*Q", "Q", regex=True
        )
        result.loc[quarter_variant] = pd.PeriodIndex(
            normalized_quarters, freq="Q"
        ).to_timestamp()
    decimal_raw = cleaned.str.fullmatch(r"\d{4}\.\d{1,2}")
    decimal_years = pd.to_numeric(cleaned.str[:4].where(decimal_raw), errors="coerce")
    decimal_month = decimal_raw & decimal_years.between(1800, 2100)
    if decimal_month.any():
        pieces = cleaned.loc[decimal_month].str.split(".", expand=True)
        normalized = pieces[0] + pieces[1].str.zfill(2)
        result.loc[decimal_month] = pd.to_datetime(normalized, format="%Y%m", errors="coerce")
    colon_month_raw = cleaned.str.fullmatch(r"\d{4}:\d{2}")
    colon_years = pd.to_numeric(cleaned.str[:4].where(colon_month_raw), errors="coerce")
    colon_month = colon_month_raw & colon_years.between(1800, 2100)
    if colon_month.any():
        result.loc[colon_month] = pd.to_datetime(
            cleaned.loc[colon_month].str.replace(":", ""),
            format="%Y%m",
            errors="coerce",
        )
    remaining = result.isna() & ~(
        eight_raw
        | six
        | six_raw
        | four_raw
        | world_bank_raw
        | quarter_raw
        | decimal_raw
        | colon_month_raw
    )
    if remaining.any():
        plausible = cleaned.loc[remaining].str.match(
            r"^(?:[A-Za-z]{3,9}[- /]\d{2,4}|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}[- /]\d{1,2}(?:[- /]\d{1,2})?(?:\s+\d{2}:\d{2}:\d{2})?)$"
        )
        indexes = plausible.index[plausible]
        result.loc[indexes] = pd.to_datetime(cleaned.loc[indexes], errors="coerce")
    plausible_year = result.dt.year.between(1800, 2100)
    result.loc[~plausible_year.fillna(False)] = pd.NaT
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
    selected_score = 0
    for column in candidates:
        parsed = _candidate_dates(frame[column], column_name=str(column))
        score = int(parsed.notna().sum())
        if score >= max(1, min(3, len(frame))) and score > selected_score:
            selected = parsed
            selected_score = score
    if selected is None:
        sample = frame.iloc[:5, :3].astype(str).to_dict(orient="list")
        raise SourceAdapterError(f"DATE_COLUMN_MISSING:{adapter}:{str(sample)[:500]}")
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
    "shiller_monthly_excel": _auto_table,
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
    resource_metadata: Mapping[str, object] | None = None,
) -> pd.DataFrame:
    """Normalize one declared resource and reject rows beyond evaluation."""

    if adapter not in _ADAPTERS:
        raise SourceAdapterError(f"UNKNOWN_ADAPTER:{adapter}")
    frame = _read_resource_format(
        payload,
        adapter=adapter,
        format_name=format_name,
        resource_metadata=resource_metadata or {},
    )
    frame = _normalize_and_bound_dates(
        frame,
        adapter=adapter,
        maximum_observation_date=maximum_observation_date,
    )
    frame["resource_id"] = resource_id
    return frame.reset_index(drop=True)
