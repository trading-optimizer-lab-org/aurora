"""Fail-closed Field-Ritter inputs and current OpenAP IPO reconstructions.

The module performs no network access.  It reads one manually acquired official
workbook only when a transport manifest proves the exact URL, source vintage,
byte size, and SHA-256 digest.  A current CIK is linked to a Field-Ritter PERMNO
only through CUSIP, one US common-stock OpenFIGI share class, matching tickers,
and a conservative issuer-name match.  The resulting bridge is current
corroboration, not a historical CRSP/SEC identity interval.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pandas as pd

from .sec_companyfacts_149 import build_companyfacts_identity


FIELD_RITTER_WORKBOOK_URL = (
    "https://site.warrington.ufl.edu/ritter/files/IPO-age.xlsx"
)
FIELD_RITTER_DOCUMENTATION_URL = (
    "https://site.warrington.ufl.edu/ritter/files/founding-dates.pdf"
)
FIELD_RITTER_SOURCE_ID = "field_ritter_ipo_1975_2025"
FIELD_RITTER_ACCESS_METHOD = "manual_official_static_excel"
FIELD_RITTER_SHEET = "1975-2025"

FIELD_RITTER_MANIFEST_COLUMNS = frozenset(
    {
        "source_id",
        "source_url",
        "documentation_url",
        "access_url",
        "access_method",
        "published_at",
        "retrieved_at",
        "sha256",
        "size_bytes",
        "status",
        "http_status",
        "failure_reason",
    }
)

_WORKBOOK_HEADERS = (
    "offer date",
    "IPO name",
    "Ticker",
    "CUSIP",
    "ADR (2=ADR)",
    "VC",
    "Dual",
    "Post-issue shares",
    "Internet",
    "CRSP Perm",
    "Founding",
    "Rollup",
)
_WORKBOOK_OUTPUT_COLUMNS = (
    "source_row",
    "ipo_offer_date",
    "company_name",
    "ticker",
    "cusip",
    "cusip_quality",
    "permno",
    "founding_year",
    "adr_code",
    "vc_code",
    "dual_class_code",
    "post_issue_shares",
    "internet_code",
    "rollup_code",
    "source_available_at",
    "source_retrieved_at",
    "source_url",
    "documentation_url",
    "transport_sha256",
    "openap_first_permno",
)
_REJECTION_COLUMNS = ("source_row", "reason_if_rejected")
_OPENFIGI_REQUIRED_COLUMNS = frozenset(
    {"cusip", "ticker", "mapping_status", "candidates_json"}
)
_RD_REQUIRED_COLUMNS = frozenset(
    {
        "cik",
        "taxonomy",
        "tag",
        "unit",
        "value",
        "period_start",
        "period_end",
        "form",
        "filed",
        "available_at",
        "accession_number",
        "fy",
        "fp",
    }
)
_RD_OUTPUT_COLUMNS = (
    "security_id",
    "ticker",
    "cik",
    "rd_expense",
    "period_end",
    "filed_at",
    "available_at",
    "accession_number",
    "source_url",
    "explicit_zero",
)
_SIGNAL_OUTPUT_COLUMNS = (
    "security_id",
    "ticker",
    "cik",
    "signal",
    "formation_at",
    "period_end",
    "filed_at",
    "available_at",
    "retrieved_at",
    "value",
    "fidelity_class",
    "current_usable",
    "source_id",
    "source_url",
    "formula_id",
    "formula_sha256",
    "observation_count",
    "reason_if_missing",
    "caveat",
    "strict_score_eligible",
)

_FORMULA_METADATA = {
    "AgeIPO": {
        "formula_id": "openap_ageipo_field_ritter_year_age_3_36m_min100",
        "sha256": "e3e6bb214aab63d92c5cbe278462c016d588ab61383cdea8c637b9c12f3f30b3",
        "caveat": (
            "Field-Ritter is complete only through 2025, excludes SPAC-merger "
            "new lists, and the current CIK bridge is not a historical CRSP link"
        ),
    },
    "IndIPO": {
        "formula_id": "openap_indipo_field_ritter_calendar_month_3_36",
        "sha256": "351163e16d519066360d6f598ecbdc9779de57fe5620564f67afbd01b1c0c37b",
        "caveat": (
            "Unmatched securities remain missing because the 2025 workbook "
            "does not prove that they are non-IPOs at the current formation"
        ),
    },
    "RDIPO": {
        "formula_id": "openap_rdipo_field_ritter_sec_explicit_rd_zero_7_36m",
        "sha256": "a6aa23c8388f49a16f710a70835b07be21a043193169704d6ce2b37ba4d3a568",
        "caveat": (
            "SEC XBRL reconstructs Compustat xrd; an omitted R&D concept is "
            "never converted to zero"
        ),
    },
}

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_OFFICE_REL_NS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
)
_PACKAGE_REL_NS = (
    "http://schemas.openxmlformats.org/package/2006/relationships"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CELL_REFERENCE_RE = re.compile(r"^([A-Z]{1,3})([1-9][0-9]*)$")
_FIGI_RE = re.compile(r"^BBG[A-Z0-9]{9}$")

_MAX_WORKBOOK_BYTES = 16 * 1024**2
_MAX_TOTAL_UNCOMPRESSED_BYTES = 96 * 1024**2
_MAX_XML_MEMBER_BYTES = 64 * 1024**2
_MAX_SOURCE_ROWS = 100_000
_MAX_COMPRESSION_RATIO = 500

_LEGAL_NAME_EQUIVALENTS = {
    "INCORPORATED": "INC",
    "CORPORATION": "CORP",
    "COMPANY": "CO",
    "LIMITED": "LTD",
}
_LEGAL_NAME_SUFFIXES = {
    "CO",
    "CORP",
    "INC",
    "LLC",
    "LLP",
    "LP",
    "LTD",
    "PLC",
}
_LEGAL_NAME_JURISDICTIONS = {"DE", "DEL", "MD", "NV", "NY", "PA", "VA"}


def _require_columns(
    frame: pd.DataFrame,
    required: frozenset[str] | set[str],
    label: str,
) -> None:
    missing = sorted(set(required).difference(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing columns: {missing}")


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _utc_timestamp(value: object, label: str) -> pd.Timestamp:
    timestamp = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(timestamp):
        raise ValueError(f"{label} has an invalid timestamp")
    return pd.Timestamp(timestamp)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validated_manifest(
    source_manifest: pd.DataFrame,
    workbook_path: Path,
) -> tuple[pd.Series, pd.Timestamp, pd.Timestamp]:
    _require_columns(
        source_manifest,
        FIELD_RITTER_MANIFEST_COLUMNS,
        "Field-Ritter source manifest",
    )
    if len(source_manifest) != 1:
        raise ValueError(
            "Field-Ritter source manifest must contain exactly one row"
        )
    row = source_manifest.iloc[0]
    if (
        _clean_text(row["source_id"]) != FIELD_RITTER_SOURCE_ID
        or _clean_text(row["source_url"]) != FIELD_RITTER_WORKBOOK_URL
        or _clean_text(row["access_url"]) != FIELD_RITTER_WORKBOOK_URL
        or _clean_text(row["documentation_url"])
        != FIELD_RITTER_DOCUMENTATION_URL
        or _clean_text(row["access_method"])
        != FIELD_RITTER_ACCESS_METHOD
    ):
        raise ValueError(
            "Field-Ritter source manifest is not exact official Field-Ritter evidence"
        )
    http_status = pd.to_numeric(row["http_status"], errors="coerce")
    if (
        _clean_text(row["status"]) != "downloaded"
        or pd.isna(http_status)
        or float(http_status) != 200.0
        or _clean_text(row["failure_reason"])
    ):
        raise ValueError(
            "Field-Ritter workbook requires downloaded HTTP 200 evidence"
        )
    published = _utc_timestamp(row["published_at"], "Field-Ritter published_at")
    retrieved = _utc_timestamp(row["retrieved_at"], "Field-Ritter retrieved_at")
    if published > retrieved:
        raise ValueError(
            "Field-Ritter published_at must not follow retrieved_at"
        )
    if workbook_path.name != "IPO-age.xlsx" or not workbook_path.is_file():
        raise ValueError("Field-Ritter workbook must be the local IPO-age.xlsx")
    size = workbook_path.stat().st_size
    expected_size = pd.to_numeric(row["size_bytes"], errors="coerce")
    if (
        size <= 0
        or size > _MAX_WORKBOOK_BYTES
        or pd.isna(expected_size)
        or float(expected_size) != float(size)
    ):
        raise ValueError(
            "Field-Ritter workbook size does not match its manifest"
        )
    expected_hash = _clean_text(row["sha256"]).lower()
    if _SHA256_RE.fullmatch(expected_hash) is None:
        raise ValueError("Field-Ritter manifest has an invalid SHA-256")
    if _sha256(workbook_path) != expected_hash:
        raise ValueError(
            "Field-Ritter workbook SHA-256 does not match its manifest"
        )
    return row, published, retrieved


def _safe_zip(archive: zipfile.ZipFile) -> None:
    total_uncompressed = 0
    names: set[str] = set()
    for info in archive.infolist():
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if (
            info.filename in names
            or path.is_absolute()
            or ".." in path.parts
            or info.flag_bits & 0x1
        ):
            raise ValueError("Field-Ritter workbook contains an unsafe ZIP member")
        names.add(info.filename)
        if info.is_dir():
            continue
        if info.file_size < 0 or info.file_size > _MAX_XML_MEMBER_BYTES:
            raise ValueError("Field-Ritter workbook contains an unsafe member size")
        total_uncompressed += info.file_size
        if total_uncompressed > _MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise ValueError("Field-Ritter workbook expands beyond the safety bound")
        if (
            info.compress_size == 0
            and info.file_size > 0
            or info.compress_size > 0
            and info.file_size / info.compress_size > _MAX_COMPRESSION_RATIO
        ):
            raise ValueError(
                "Field-Ritter workbook contains an unsafe compression ratio"
            )


def _xml_member(archive: zipfile.ZipFile, name: str) -> ET.Element:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise ValueError(f"Field-Ritter workbook is missing {name}") from exc
    if info.file_size <= 0 or info.file_size > _MAX_XML_MEMBER_BYTES:
        raise ValueError(f"Field-Ritter workbook has an unsafe {name}")
    try:
        return ET.fromstring(archive.read(info))
    except ET.ParseError as exc:
        raise ValueError(f"Field-Ritter workbook has invalid XML in {name}") from exc


def _worksheet_member(archive: zipfile.ZipFile) -> str:
    workbook = _xml_member(archive, "xl/workbook.xml")
    workbook_properties = workbook.find(f"{{{_MAIN_NS}}}workbookPr")
    if (
        workbook_properties is not None
        and _clean_text(workbook_properties.get("date1904")).lower()
        in {"1", "true"}
    ):
        raise ValueError(
            "Field-Ritter workbook changed to the unsupported 1904 date system"
        )
    sheets = workbook.findall(f".//{{{_MAIN_NS}}}sheet")
    matching = [sheet for sheet in sheets if sheet.get("name") == FIELD_RITTER_SHEET]
    if len(sheets) != 1 or len(matching) != 1:
        raise ValueError(
            "Field-Ritter workbook must contain exactly the 1975-2025 sheet"
        )
    relationship_id = matching[0].get(f"{{{_OFFICE_REL_NS}}}id")
    relationships = _xml_member(archive, "xl/_rels/workbook.xml.rels")
    targets = [
        relation.get("Target", "")
        for relation in relationships.findall(f"{{{_PACKAGE_REL_NS}}}Relationship")
        if relation.get("Id") == relationship_id
    ]
    if len(targets) != 1:
        raise ValueError("Field-Ritter worksheet relationship is ambiguous")
    target = PurePosixPath(targets[0].replace("\\", "/"))
    if target.is_absolute() or ".." in target.parts:
        raise ValueError("Field-Ritter worksheet relationship is unsafe")
    member = str(PurePosixPath("xl") / target)
    if member not in archive.namelist():
        raise ValueError("Field-Ritter worksheet member is missing")
    return member


def _shared_strings(archive: zipfile.ZipFile) -> tuple[str, ...]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return ()
    root = _xml_member(archive, "xl/sharedStrings.xml")
    values: list[str] = []
    for item in root.findall(f"{{{_MAIN_NS}}}si"):
        values.append(
            "".join(
                node.text or ""
                for node in item.iter(f"{{{_MAIN_NS}}}t")
            )
        )
    return tuple(values)


def _column_index(reference: str) -> tuple[int, int]:
    match = _CELL_REFERENCE_RE.fullmatch(reference)
    if match is None:
        raise ValueError("Field-Ritter worksheet has an invalid cell reference")
    column = 0
    for character in match.group(1):
        column = column * 26 + ord(character) - 64
    return column - 1, int(match.group(2))


def _cell_text(cell: ET.Element, shared: tuple[str, ...]) -> str:
    if cell.find(f"{{{_MAIN_NS}}}f") is not None:
        raise ValueError("Field-Ritter worksheet must not contain formula cells")
    cell_type = cell.get("t", "")
    if cell_type == "inlineStr":
        return "".join(
            node.text or "" for node in cell.iter(f"{{{_MAIN_NS}}}t")
        )
    value_node = cell.find(f"{{{_MAIN_NS}}}v")
    value = "" if value_node is None else value_node.text or ""
    if cell_type == "s":
        try:
            index = int(value)
            return shared[index]
        except (ValueError, IndexError) as exc:
            raise ValueError(
                "Field-Ritter worksheet has an invalid shared-string index"
            ) from exc
    if cell_type in {"", "n", "str", "b"}:
        return value
    raise ValueError(
        f"Field-Ritter worksheet has unsupported cell type: {cell_type}"
    )


def _raw_rows(archive: zipfile.ZipFile) -> list[tuple[int, tuple[str, ...]]]:
    shared = _shared_strings(archive)
    worksheet = _xml_member(archive, _worksheet_member(archive))
    rows: list[tuple[int, tuple[str, ...]]] = []
    seen_rows: set[int] = set()
    for row in worksheet.findall(f".//{{{_MAIN_NS}}}sheetData/{{{_MAIN_NS}}}row"):
        row_number_text = row.get("r", "")
        if not row_number_text.isdigit():
            raise ValueError("Field-Ritter worksheet has an invalid row number")
        row_number = int(row_number_text)
        if row_number in seen_rows or row_number <= 0:
            raise ValueError("Field-Ritter worksheet has duplicate rows")
        seen_rows.add(row_number)
        values = [""] * len(_WORKBOOK_HEADERS)
        seen_columns: set[int] = set()
        for cell in row.findall(f"{{{_MAIN_NS}}}c"):
            column, referenced_row = _column_index(cell.get("r", ""))
            if referenced_row != row_number or column in seen_columns:
                raise ValueError("Field-Ritter worksheet cell identity is inconsistent")
            seen_columns.add(column)
            value = _cell_text(cell, shared)
            if column >= len(values):
                continue
            values[column] = value
        if any(_clean_text(value) for value in values):
            rows.append((row_number, tuple(values)))
        if len(rows) > _MAX_SOURCE_ROWS + 1:
            raise ValueError("Field-Ritter worksheet exceeds the row safety bound")
    if not rows or rows[0][0] != 1:
        raise ValueError("Field-Ritter worksheet is missing its header row")
    header = tuple(_clean_text(value) for value in rows[0][1])
    if header != _WORKBOOK_HEADERS:
        raise ValueError("Field-Ritter workbook header contract changed")
    return rows[1:]


def _parse_integer(value: object) -> int | None:
    text = _clean_text(value)
    if re.fullmatch(r"[+-]?[0-9]+", text):
        return int(text)
    if re.fullmatch(r"[+-]?[0-9]+\.0+", text):
        return int(float(text))
    return None


def _parse_offer_date(value: object) -> date | None:
    text = _clean_text(value)
    if re.fullmatch(r"[0-9]{8}(?:\.0+)?", text):
        parsed = pd.to_datetime(text[:8], format="%Y%m%d", errors="coerce")
    elif re.fullmatch(r"[0-9]{1,5}(?:\.0+)?", text):
        # The official workbook stores offer dates as Excel serial numbers.
        # 1899-12-30 matches the 1900-date-system convention used by pandas.
        parsed = pd.Timestamp("1899-12-30") + pd.to_timedelta(
            int(float(text)),
            unit="D",
        )
    elif re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
        parsed = pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")
    else:
        return None
    if pd.isna(parsed) or not 1900 <= pd.Timestamp(parsed).year <= 2100:
        return None
    return pd.Timestamp(parsed).date()


def _cusip_character_value(character: str) -> int:
    if character.isdigit():
        return int(character)
    if "A" <= character <= "Z":
        return ord(character) - ord("A") + 10
    return {"*": 36, "@": 37, "#": 38}[character]


def _cusip_check_digit(cusip8: str) -> str:
    total = 0
    for index, character in enumerate(cusip8):
        number = _cusip_character_value(character)
        if index % 2 == 1:
            number *= 2
        total += number // 10 + number % 10
    return str((10 - total % 10) % 10)


def _normalize_cusip(value: object) -> tuple[str, str]:
    text = re.sub(r"[^A-Z0-9*@#]", "", _clean_text(value).upper())
    if re.fullmatch(r"[A-Z0-9*@#]{8}", text):
        return text + _cusip_check_digit(text), "check_digit_derived_from_cusip8"
    if re.fullmatch(r"[A-Z0-9*@#]{8}[0-9]", text):
        if text[-1] == _cusip_check_digit(text[:8]):
            return text, "cusip9_check_digit_verified"
        return "", "invalid_cusip9_check_digit"
    return "", "invalid_or_missing_cusip"


def _normalize_source_rows(
    rows: list[tuple[int, tuple[str, ...]]],
    *,
    published_at: pd.Timestamp,
    retrieved_at: pd.Timestamp,
    transport_sha256: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    normalized: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for source_row, values in rows:
        raw = dict(zip(_WORKBOOK_HEADERS, values, strict=True))
        offer_date = _parse_offer_date(raw["offer date"])
        company_name = _clean_text(raw["IPO name"])
        permno = _parse_integer(raw["CRSP Perm"])
        founding_year = _parse_integer(raw["Founding"])
        reasons: list[str] = []
        if offer_date is None:
            reasons.append("invalid_offer_date")
        if not company_name:
            reasons.append("missing_company_name")
        if permno is None or permno <= 0 or permno == 999:
            reasons.append("invalid_or_missing_permno")
        if (
            founding_year is None
            or founding_year < 1000
            or offer_date is not None
            and founding_year > offer_date.year
        ):
            reasons.append("invalid_founding_year")
        if reasons:
            rejected.append(
                {
                    "source_row": source_row,
                    "reason_if_rejected": ";".join(reasons),
                }
            )
            continue
        cusip, cusip_quality = _normalize_cusip(raw["CUSIP"])
        post_issue_shares = pd.to_numeric(
            _clean_text(raw["Post-issue shares"]), errors="coerce"
        )
        normalized.append(
            {
                "source_row": source_row,
                "ipo_offer_date": offer_date,
                "company_name": company_name,
                "ticker": _clean_text(raw["Ticker"]).upper(),
                "cusip": cusip,
                "cusip_quality": cusip_quality,
                "permno": int(permno),
                "founding_year": int(founding_year),
                "adr_code": _clean_text(raw["ADR (2=ADR)"]),
                "vc_code": _clean_text(raw["VC"]),
                "dual_class_code": _clean_text(raw["Dual"]),
                "post_issue_shares": (
                    float(post_issue_shares)
                    if pd.notna(post_issue_shares)
                    and np.isfinite(float(post_issue_shares))
                    and float(post_issue_shares) >= 0
                    else np.nan
                ),
                "internet_code": _clean_text(raw["Internet"]),
                "rollup_code": _clean_text(raw["Rollup"]),
                "source_available_at": published_at,
                "source_retrieved_at": retrieved_at,
                "source_url": FIELD_RITTER_WORKBOOK_URL,
                "documentation_url": FIELD_RITTER_DOCUMENTATION_URL,
                "transport_sha256": transport_sha256,
                "openap_first_permno": False,
            }
        )
    frame = pd.DataFrame(normalized, columns=_WORKBOOK_OUTPUT_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values("source_row", kind="stable").reset_index(drop=True)
        frame["openap_first_permno"] = ~frame["permno"].duplicated(keep="first")
    rejected_frame = pd.DataFrame(rejected, columns=_REJECTION_COLUMNS)
    return frame, rejected_frame


def load_field_ritter_ipo_workbook(
    workbook_path: Path | str,
    source_manifest: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int | str]]:
    """Load the exact official Field-Ritter workbook without network access."""

    path = Path(workbook_path)
    manifest, published, retrieved = _validated_manifest(source_manifest, path)
    try:
        with zipfile.ZipFile(path) as archive:
            _safe_zip(archive)
            source_rows = _raw_rows(archive)
    except zipfile.BadZipFile as exc:
        raise ValueError("Field-Ritter workbook is not a valid XLSX ZIP") from exc
    rows, rejected = _normalize_source_rows(
        source_rows,
        published_at=published,
        retrieved_at=retrieved,
        transport_sha256=_clean_text(manifest["sha256"]).lower(),
    )
    summary: dict[str, int | str] = {
        "source_rows": len(source_rows),
        "normalized_rows": len(rows),
        "rejected_rows": len(rejected),
        "openap_selected_permnos": int(rows["openap_first_permno"].sum()),
        "source_published_at": published.isoformat(),
        "workbook_size_bytes": path.stat().st_size,
    }
    return rows, rejected, summary


def select_openap_ipo_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """Mirror the pinned OpenAP loader's first-observation-per-PERMNO rule."""

    required = {
        "source_row",
        "permno",
        "ipo_offer_date",
        "founding_year",
    }
    _require_columns(rows, required, "Field-Ritter rows")
    frame = rows.copy()
    frame["source_row"] = pd.to_numeric(frame["source_row"], errors="coerce")
    frame["permno"] = pd.to_numeric(frame["permno"], errors="coerce")
    if (
        frame["source_row"].isna().any()
        or frame["permno"].isna().any()
        or frame["source_row"].duplicated().any()
    ):
        raise ValueError("Field-Ritter normalized rows have invalid identities")
    selected = (
        frame.sort_values("source_row", kind="stable")
        .drop_duplicates("permno", keep="first")
        .copy()
    )
    selected["openap_first_permno"] = True
    return selected.sort_values("permno", kind="stable").reset_index(drop=True)


def _issuer_identity_key(value: object) -> str:
    tokens = re.findall(
        r"[A-Z0-9]+",
        _clean_text(value).upper().replace("&", " AND "),
    )
    tokens = [_LEGAL_NAME_EQUIVALENTS.get(token, token) for token in tokens]
    while tokens and tokens[-1] in _LEGAL_NAME_JURISDICTIONS:
        tokens.pop()
    while tokens and tokens[-1] in _LEGAL_NAME_SUFFIXES:
        tokens.pop()
    return "".join(tokens)


def _openfigi_share_class(candidates_json: object, ticker: str) -> str:
    try:
        candidates = json.loads(str(candidates_json))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(candidates, list):
        return ""
    expected_ticker = _clean_text(ticker).upper()
    figis: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_ticker = _clean_text(candidate.get("ticker")).upper()
        market_sector = _clean_text(candidate.get("marketSector")).lower()
        exchange_code = _clean_text(candidate.get("exchCode")).upper()
        security_type = " ".join(
            [
                _clean_text(candidate.get("securityType")),
                _clean_text(candidate.get("securityType2")),
            ]
        ).lower()
        figi = _clean_text(candidate.get("shareClassFIGI")).upper()
        if (
            candidate_ticker == expected_ticker
            and market_sector == "equity"
            and exchange_code == "US"
            and "common stock" in security_type
            and _FIGI_RE.fullmatch(figi)
        ):
            figis.add(figi)
    return next(iter(figis)) if len(figis) == 1 else ""


def _current_sec_names(companyfacts: pd.DataFrame) -> pd.DataFrame:
    _require_columns(companyfacts, {"cik", "entity_name"}, "SEC CompanyFacts")
    names = companyfacts[["cik", "entity_name"]].copy()
    names["cik"] = pd.to_numeric(names["cik"], errors="coerce")
    names["issuer_name_key"] = names["entity_name"].map(_issuer_identity_key)
    names = names.loc[names["cik"].notna() & names["issuer_name_key"].ne("")]
    counts = names.groupby("cik")["issuer_name_key"].nunique()
    unambiguous = set(counts.loc[counts.eq(1)].index)
    return names.loc[names["cik"].isin(unambiguous)][
        ["cik", "entity_name", "issuer_name_key"]
    ].drop_duplicates("cik")


def build_field_ritter_current_identity(
    ipo_rows: pd.DataFrame,
    cusip_map: pd.DataFrame,
    companyfacts: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    identity_available_at: str | pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Corroborate a current CIK against one Field-Ritter PERMNO record."""

    ipo_required = {
        "source_row",
        "ipo_offer_date",
        "company_name",
        "ticker",
        "cusip",
        "permno",
        "founding_year",
        "source_available_at",
        "source_retrieved_at",
        "source_url",
        "documentation_url",
        "transport_sha256",
        "openap_first_permno",
    }
    _require_columns(ipo_rows, ipo_required, "Field-Ritter IPO rows")
    _require_columns(cusip_map, _OPENFIGI_REQUIRED_COLUMNS, "OpenFIGI mapping")
    formation = _utc_timestamp(formation_at, "formation_at")
    identity_available = _utc_timestamp(
        identity_available_at,
        "identity_available_at",
    )
    if identity_available > formation:
        raise ValueError("Current SEC/OpenFIGI identity is available after formation")

    selected = select_openap_ipo_rows(ipo_rows)
    identity = build_companyfacts_identity(status).copy()
    identity["ticker"] = identity["symbol"].astype(str).str.upper()
    ticker_counts = identity.groupby("ticker")["cik"].nunique()
    identity = identity.loc[
        identity["ticker"].isin(ticker_counts.loc[ticker_counts.eq(1)].index)
    ].copy()
    names = _current_sec_names(companyfacts)
    identity = identity.merge(names, on="cik", how="inner", validate="one_to_one")
    identity_by_ticker = {
        str(row.ticker): row for row in identity.itertuples(index=False)
    }

    mapping = cusip_map.copy()
    mapping["normalized_cusip"] = mapping["cusip"].map(
        lambda value: _normalize_cusip(value)[0]
    )
    mapping["mapped_ticker"] = (
        mapping["ticker"].fillna("").astype(str).str.strip().str.upper()
    )
    mapping["share_class_figi"] = mapping.apply(
        lambda row: _openfigi_share_class(
            row["candidates_json"], row["mapped_ticker"]
        ),
        axis=1,
    )
    mapping_counts = mapping.groupby("normalized_cusip", dropna=False).agg(
        row_count=("normalized_cusip", "size"),
        ticker_count=("mapped_ticker", "nunique"),
        status_count=("mapping_status", "nunique"),
        figi_count=("share_class_figi", "nunique"),
    )
    unambiguous_cusips = set(
        mapping_counts.loc[
            mapping_counts["row_count"].eq(1)
            & mapping_counts["ticker_count"].eq(1)
            & mapping_counts["status_count"].eq(1)
            & mapping_counts["figi_count"].eq(1)
        ].index
    )
    mapping_by_cusip = {
        str(row.normalized_cusip): row
        for row in mapping.loc[
            mapping["normalized_cusip"].isin(unambiguous_cusips)
        ].itertuples(index=False)
    }

    linked: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for ipo in selected.itertuples(index=False):
        reason = ""
        source_available = pd.to_datetime(
            ipo.source_available_at,
            errors="coerce",
            utc=True,
        )
        ticker = _clean_text(ipo.ticker).upper()
        cusip = _clean_text(ipo.cusip).upper()
        mapped = mapping_by_cusip.get(cusip)
        current = identity_by_ticker.get(ticker)
        if pd.isna(source_available) or source_available > formation:
            reason = "field_ritter_source_available_after_formation_or_invalid"
        elif not ticker:
            reason = "field_ritter_ticker_missing"
        elif not cusip:
            reason = "field_ritter_cusip_missing_or_invalid"
        elif mapped is None:
            reason = "openfigi_mapping_not_unique_us_common_stock"
        elif _clean_text(mapped.mapping_status) != "mapped_unique" or not _clean_text(
            mapped.share_class_figi
        ):
            reason = "openfigi_mapping_not_unique_us_common_stock"
        elif _clean_text(mapped.mapped_ticker).upper() != ticker:
            reason = "field_ritter_and_openfigi_ticker_disagree"
        elif current is None:
            reason = "sec_current_identity_missing_or_ambiguous"
        elif _issuer_identity_key(ipo.company_name) != _clean_text(
            current.issuer_name_key
        ):
            reason = "field_ritter_and_sec_issuer_name_disagree"
        if reason:
            rejected.append(
                {
                    "source_row": int(ipo.source_row),
                    "permno": int(ipo.permno),
                    "ticker": ticker,
                    "reason_if_rejected": reason,
                }
            )
            continue
        linked.append(
            {
                "source_row": int(ipo.source_row),
                "security_id": str(current.security_id),
                "ticker": ticker,
                "cik": f"{int(current.cik):010d}",
                "entity_name": str(current.entity_name),
                "permno": int(ipo.permno),
                "ipo_offer_date": ipo.ipo_offer_date,
                "founding_year": int(ipo.founding_year),
                "cusip": cusip,
                "share_class_figi": str(mapped.share_class_figi),
                "source_available_at": pd.Timestamp(source_available),
                "source_retrieved_at": pd.Timestamp(ipo.source_retrieved_at),
                "identity_available_at": identity_available,
                "source_url": str(ipo.source_url),
                "documentation_url": str(ipo.documentation_url),
                "transport_sha256": str(ipo.transport_sha256),
                "identity_quality": (
                    "field_ritter_cusip_openfigi_sec_ticker_name_current_bridge"
                ),
                "historical_ticker_interval_verified": False,
                "strict_score_eligible": False,
            }
        )

    linked_frame = pd.DataFrame(linked)
    if not linked_frame.empty:
        duplicate_mask = linked_frame["security_id"].duplicated(keep=False) | linked_frame[
            "share_class_figi"
        ].duplicated(keep=False)
        if duplicate_mask.any():
            duplicate_rows = linked_frame.loc[duplicate_mask]
            rejected.extend(
                {
                    "source_row": int(row.source_row),
                    "permno": int(row.permno),
                    "ticker": str(row.ticker),
                    "reason_if_rejected": "multiple_field_ritter_records_map_to_current_security",
                }
                for row in duplicate_rows.itertuples(index=False)
            )
            linked_frame = linked_frame.loc[~duplicate_mask].copy()
        linked_frame = linked_frame.sort_values("security_id").reset_index(drop=True)
    rejected_frame = pd.DataFrame(rejected)
    if not rejected_frame.empty:
        rejected_frame = rejected_frame.sort_values("source_row").reset_index(drop=True)
    return linked_frame, rejected_frame


def extract_causal_sec_rd_expense(
    companyfacts: pd.DataFrame,
    status: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Return the latest explicit annual SEC R&D fact available at formation."""

    _require_columns(companyfacts, _RD_REQUIRED_COLUMNS, "SEC CompanyFacts")
    formation = _utc_timestamp(formation_at, "formation_at")
    frame = companyfacts.copy()
    frame["cik"] = pd.to_numeric(frame["cik"], errors="coerce")
    frame["rd_expense"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["period_start"] = pd.to_datetime(
        frame["period_start"], errors="coerce", utc=True
    )
    frame["period_end"] = pd.to_datetime(
        frame["period_end"], errors="coerce", utc=True
    )
    frame["filed_at"] = pd.to_datetime(frame["filed"], errors="coerce", utc=True)
    frame["available_at"] = pd.to_datetime(
        frame["available_at"], errors="coerce", utc=True
    )
    duration = (frame["period_end"] - frame["period_start"]).dt.days
    frame = frame.loc[
        frame["cik"].notna()
        & frame["taxonomy"].fillna("").astype(str).str.lower().eq("us-gaap")
        & frame["tag"].eq("ResearchAndDevelopmentExpense")
        & frame["unit"].eq("USD")
        & frame["form"].isin({"10-K", "10-K/A"})
        & frame["fp"].fillna("").astype(str).eq("FY")
        & duration.between(250, 450)
        & frame["rd_expense"].notna()
        & np.isfinite(frame["rd_expense"])
        & frame["rd_expense"].ge(0)
        & frame["period_end"].notna()
        & frame["period_end"].le(formation)
        & frame["filed_at"].notna()
        & frame["filed_at"].le(formation)
        & frame["period_end"].le(frame["filed_at"])
        & frame["available_at"].notna()
        & frame["available_at"].le(formation)
        & frame["filed_at"].le(frame["available_at"])
        & frame["accession_number"].map(_clean_text).ne("")
    ].copy()
    if frame.empty:
        return pd.DataFrame(columns=_RD_OUTPUT_COLUMNS)
    latest_period = frame.groupby("cik")["period_end"].transform("max")
    frame = frame.loc[frame["period_end"].eq(latest_period)].copy()
    latest_available = frame.groupby("cik")["available_at"].transform("max")
    frame = frame.loc[frame["available_at"].eq(latest_available)].copy()
    conflicts = frame.groupby("cik")["rd_expense"].transform("nunique").gt(1)
    frame = frame.loc[~conflicts].sort_values(
        ["cik", "available_at", "accession_number"], kind="stable"
    ).drop_duplicates("cik", keep="last")

    identity = build_companyfacts_identity(status).copy()
    identity = identity.rename(columns={"symbol": "ticker"})
    output = frame.merge(identity, on="cik", how="inner", validate="one_to_one")
    if output.empty:
        return pd.DataFrame(columns=_RD_OUTPUT_COLUMNS)
    output["cik"] = output["cik"].map(lambda value: f"{int(value):010d}")
    output["source_url"] = output["cik"].map(
        lambda cik: (
            "https://data.sec.gov/api/xbrl/companyfacts/"
            f"CIK{cik}.json"
        )
    )
    output["explicit_zero"] = output["rd_expense"].eq(0.0)
    return output[list(_RD_OUTPUT_COLUMNS)].sort_values("security_id").reset_index(
        drop=True
    )


def _maximum_timestamp(*values: object) -> pd.Timestamp | None:
    timestamps = [pd.to_datetime(value, errors="coerce", utc=True) for value in values]
    valid = [pd.Timestamp(value) for value in timestamps if pd.notna(value)]
    return max(valid) if valid else None


def _iso(value: object) -> str:
    timestamp = pd.to_datetime(value, errors="coerce", utc=True)
    return "" if pd.isna(timestamp) else pd.Timestamp(timestamp).isoformat()


def calculate_field_ritter_ipo_signals(
    current_identity: pd.DataFrame,
    linked_ipos: pd.DataFrame,
    rd_observations: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Calculate conservative current AgeIPO, IndIPO, and RDIPO values."""

    _require_columns(
        current_identity,
        {"security_id", "ticker", "cik"},
        "Current security identity",
    )
    linked_required = {
        "security_id",
        "ticker",
        "cik",
        "permno",
        "ipo_offer_date",
        "founding_year",
        "source_available_at",
        "identity_available_at",
        "source_url",
        "documentation_url",
        "transport_sha256",
    }
    _require_columns(linked_ipos, linked_required, "Linked Field-Ritter IPOs")
    rd_required = {
        "security_id",
        "rd_expense",
        "period_end",
        "filed_at",
        "available_at",
        "accession_number",
        "source_url",
        "explicit_zero",
    }
    _require_columns(rd_observations, rd_required, "SEC R&D observations")
    formation = _utc_timestamp(formation_at, "formation_at")
    retrieved = _utc_timestamp(retrieved_at, "retrieved_at")
    current = current_identity.copy()
    current["security_id"] = current["security_id"].map(_clean_text)
    current["ticker"] = current["ticker"].map(lambda value: _clean_text(value).upper())
    current["cik"] = current["cik"].map(
        lambda value: f"{int(float(value)):010d}"
        if re.fullmatch(r"[0-9]+(?:\.0+)?", _clean_text(value))
        else ""
    )
    identity_columns = ["security_id", "ticker", "cik"]
    blank_counts = current[identity_columns].eq("").sum()
    duplicate_mask = current["security_id"].duplicated(keep=False)
    if blank_counts.any() or duplicate_mask.any():
        blank_rows = current.loc[
            current[identity_columns].eq("").any(axis=1), identity_columns
        ].head(10)
        duplicate_ids = sorted(
            current.loc[duplicate_mask, "security_id"].astype(str).unique()
        )[:10]
        raise ValueError(
            "Current security identity is blank or duplicated: "
            f"blank_counts={blank_counts.astype(int).to_dict()}, "
            f"blank_rows={blank_rows.to_dict(orient='records')}, "
            f"duplicate_security_ids={duplicate_ids}"
        )
    if linked_ipos["security_id"].duplicated().any():
        raise ValueError("Linked Field-Ritter IPOs contain duplicate securities")
    if rd_observations["security_id"].duplicated().any():
        raise ValueError("SEC R&D observations contain duplicate securities")

    linked_by_security = {
        str(row.security_id): row for row in linked_ipos.itertuples(index=False)
    }
    rd_by_security = {
        str(row.security_id): row for row in rd_observations.itertuples(index=False)
    }
    formation_month = formation.tz_localize(None).to_period("M").to_timestamp()

    recent_for_age: set[str] = set()
    month_metadata: dict[str, tuple[float, int]] = {}
    for security_id, ipo in linked_by_security.items():
        offer = pd.to_datetime(ipo.ipo_offer_date, errors="coerce")
        source_available = pd.to_datetime(
            ipo.source_available_at, errors="coerce", utc=True
        )
        identity_available = pd.to_datetime(
            ipo.identity_available_at, errors="coerce", utc=True
        )
        if (
            pd.isna(offer)
            or pd.isna(source_available)
            or pd.isna(identity_available)
            or source_available > formation
            or identity_available > formation
        ):
            continue
        offer_month = pd.Timestamp(offer).to_period("M").to_timestamp()
        months_days = float((formation_month - offer_month).days / 30.44)
        months_calendar = int(
            formation_month.to_period("M").ordinal
            - offer_month.to_period("M").ordinal
        )
        month_metadata[security_id] = (months_days, months_calendar)
        if 3 <= months_days <= 36:
            recent_for_age.add(security_id)
    age_cohort_count = len(recent_for_age)

    rows: list[dict[str, Any]] = []
    for security in current.itertuples(index=False):
        security_id = str(security.security_id)
        ipo = linked_by_security.get(security_id)
        metadata = month_metadata.get(security_id)
        rd = rd_by_security.get(security_id)
        base_available: pd.Timestamp | None = None
        if ipo is not None:
            base_available = _maximum_timestamp(
                ipo.source_available_at,
                ipo.identity_available_at,
            )
        for signal in ("AgeIPO", "IndIPO", "RDIPO"):
            value: float | None = None
            reason = ""
            filed_at = ""
            available = base_available
            observations = 1 if ipo is not None else 0
            if ipo is None or metadata is None:
                reason = "ipo_identity_not_corroborated"
            else:
                months_days, months_calendar = metadata
                if signal == "AgeIPO":
                    observations = age_cohort_count
                    if not 3 <= months_days <= 36:
                        reason = "not_applicable:outside_3_36_months"
                    elif age_cohort_count < 100:
                        reason = "confirmed_recent_ipo_cohort_below_100"
                    else:
                        founding_year = pd.to_numeric(
                            ipo.founding_year, errors="coerce"
                        )
                        if pd.isna(founding_year):
                            reason = "field_ritter_founding_year_missing"
                        else:
                            value = float(formation_month.year - int(founding_year))
                elif signal == "IndIPO":
                    value = float(3 <= months_calendar <= 36)
                else:
                    if not 6 < months_calendar <= 36:
                        value = 0.0
                    elif rd is None:
                        reason = "explicit_sec_rd_expense_missing"
                    else:
                        rd_available = pd.to_datetime(
                            rd.available_at, errors="coerce", utc=True
                        )
                        amount = pd.to_numeric(rd.rd_expense, errors="coerce")
                        if (
                            pd.isna(rd_available)
                            or rd_available > formation
                            or pd.isna(amount)
                            or not np.isfinite(float(amount))
                            or float(amount) < 0
                        ):
                            reason = "explicit_sec_rd_expense_missing"
                        elif float(amount) == 0.0 and bool(rd.explicit_zero):
                            value = 1.0
                        elif float(amount) > 0.0:
                            value = 0.0
                        else:
                            reason = "explicit_sec_rd_expense_missing"
                        if pd.notna(rd_available) and rd_available <= formation:
                            available = _maximum_timestamp(available, rd_available)
                            filed_at = _iso(rd.filed_at)
                            observations = 2
            finite = value is not None and np.isfinite(float(value))
            formula = _FORMULA_METADATA[signal]
            source_url = FIELD_RITTER_WORKBOOK_URL
            if signal == "RDIPO" and rd is not None:
                source_url += f"|{_clean_text(rd.source_url)}"
            rows.append(
                {
                    "security_id": security_id,
                    "ticker": str(security.ticker),
                    "cik": str(security.cik),
                    "signal": signal,
                    "formation_at": formation.isoformat(),
                    "period_end": formation_month.date().isoformat(),
                    "filed_at": filed_at,
                    "available_at": _iso(available),
                    "retrieved_at": retrieved.isoformat(),
                    "value": float(value) if finite else np.nan,
                    "fidelity_class": "reconstructed" if finite else "unavailable",
                    "current_usable": bool(finite),
                    "source_id": "field_ritter_ipo|openfigi|sec_edgar",
                    "source_url": source_url,
                    "formula_id": formula["formula_id"],
                    "formula_sha256": formula["sha256"],
                    "observation_count": int(observations),
                    "reason_if_missing": "" if finite else reason,
                    "caveat": formula["caveat"],
                    "strict_score_eligible": False,
                }
            )
    return pd.DataFrame(rows, columns=_SIGNAL_OUTPUT_COLUMNS).sort_values(
        ["security_id", "signal"]
    ).reset_index(drop=True)


__all__ = [
    "FIELD_RITTER_ACCESS_METHOD",
    "FIELD_RITTER_DOCUMENTATION_URL",
    "FIELD_RITTER_MANIFEST_COLUMNS",
    "FIELD_RITTER_SOURCE_ID",
    "FIELD_RITTER_WORKBOOK_URL",
    "build_field_ritter_current_identity",
    "calculate_field_ritter_ipo_signals",
    "extract_causal_sec_rd_expense",
    "load_field_ritter_ipo_workbook",
    "select_openap_ipo_rows",
]
