"""Parse bounded SEC rendered-report read-through evidence."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any


_PPE_REPORT_PATTERNS = (
    re.compile(
        r"Gross\s+Property,?\s*Plant\s+and\s+Equipment\s+by\s+Major\s+"
        r"Asset\s+Class",
        re.IGNORECASE,
    ),
    re.compile(
        r"Property,?\s*Plant\s+and\s+Equipment\s*\(Details\)",
        re.IGNORECASE,
    ),
)


def locate_rendered_ppe_report(filing_summary_text: object) -> str:
    """Return the nearest rendered report filename before a PP&E detail title."""

    text = str(filing_summary_text)
    for pattern in _PPE_REPORT_PATTERNS:
        title = pattern.search(text)
        if title is None:
            continue
        preceding = text[max(0, title.start() - 2500) : title.start()]
        filenames = re.findall(r"R\d+\.htm", preceding, flags=re.IGNORECASE)
        if filenames:
            return filenames[-1]
    return ""


def _plain_label(value: object) -> str:
    text = str(value).strip()
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return text.replace("**", "").strip()


def _period_end(value: object) -> str | None:
    text = _plain_label(value).replace(".", "")
    for pattern in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def _number(value: object) -> float | None:
    text = _plain_label(value).replace("\xa0", " ").strip()
    if not text or text in {"-", "—", "–"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[$,\s()]", "", text)
    if not cleaned:
        return None
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return -number if negative else number


def _markdown_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) >= 2:
            rows.append(cells)
    return rows


def extract_rendered_realestate_inputs(report_text: object) -> list[dict[str, Any]]:
    """Extract exact OpenAP ``realestate`` inputs from one rendered PP&E table."""

    rows = _markdown_rows(str(report_text))
    header_index = -1
    periods: list[str] = []
    for index, cells in enumerate(rows):
        parsed = [_period_end(cell) for cell in cells[1:]]
        if parsed and all(value is not None for value in parsed):
            header_index = index
            periods = [str(value) for value in parsed]
            break
    if header_index < 0 or not periods:
        return []

    values: list[dict[str, float | None]] = [
        {
            "land_gross": None,
            "buildings_gross": None,
            "land_and_buildings_gross": None,
            "ppe_gross": None,
            "ppe_net": None,
        }
        for _ in periods
    ]
    current_member = ""
    for cells in rows[header_index + 1 :]:
        if len(cells) < len(periods) + 1:
            cells = cells + [""] * (len(periods) + 1 - len(cells))
        label = _plain_label(cells[0])
        normalized = re.sub(r"\s+", " ", label).strip().lower()
        if not normalized or set(normalized) <= {"-", " "}:
            continue
        row_values = [_number(cell) for cell in cells[1 : len(periods) + 1]]
        if all(value is None for value in row_values):
            if "line items" not in normalized:
                current_member = normalized
            continue

        if re.fullmatch(
            r"gross property,? plant and equipment", normalized
        ):
            if not current_member:
                key = "ppe_gross"
            elif "land" in current_member and "building" in current_member:
                key = "land_and_buildings_gross"
            elif "land" in current_member:
                key = "land_gross"
            elif "building" in current_member:
                key = "buildings_gross"
            else:
                continue
        elif re.fullmatch(
            r"(?:total )?property,? plant and equipment,? net", normalized
        ):
            key = "ppe_net"
        else:
            continue
        for index, number in enumerate(row_values):
            if number is not None and values[index][key] is None:
                values[index][key] = number

    extracted: list[dict[str, Any]] = []
    for period, item in zip(periods, values):
        combined = item["land_and_buildings_gross"]
        land = item["land_gross"]
        buildings = item["buildings_gross"]
        if combined is not None:
            numerator = combined
            variant = "combined_land_and_buildings_over_gross_ppe"
        elif land is not None and buildings is not None:
            numerator = land + buildings
            variant = "separate_land_plus_buildings_over_gross_ppe"
        else:
            continue
        gross = item["ppe_gross"]
        if gross is None or gross <= 0:
            continue
        extracted.append(
            {
                "period_end": period,
                **item,
                "realestate_numerator": numerator,
                "realestate_raw": numerator / gross,
                "formula_variant": variant,
            }
        )
    return extracted


def build_rendered_realestate_evidence(
    *,
    selected_filing: dict[str, Any],
    report_metadata: dict[str, Any],
    report_text: object,
) -> dict[str, Any]:
    """Bind parsed PP&E inputs to causal filing and transport provenance."""

    parsed = extract_rendered_realestate_inputs(report_text)
    records: list[dict[str, Any]] = []
    for row in parsed:
        records.append(
            {
                "cik": str(selected_filing["cik"]),
                "accession_number": str(selected_filing["accession_number"]),
                "form": str(selected_filing["form"]),
                "report_date": str(selected_filing["report_date"]),
                "filing_date": str(selected_filing["filing_date"]),
                "available_at": str(selected_filing["accepted_at"]),
                "formation_at": str(selected_filing["formation_at"]),
                **row,
                "report_filename": str(report_metadata["report_filename"]),
                "source_url": str(report_metadata["source_url"]),
                "access_url": str(report_metadata["access_url"]),
                "access_method": str(report_metadata["access_method"]),
                "source_sha256": str(report_metadata["sha256"]),
                "source_size_bytes": int(report_metadata["size_bytes"]),
            }
        )

    acquired = bool(records)
    return {
        "signal": "realestate",
        "status": "raw_data_acquired" if acquired else "blocked_source_failure",
        "raw_data_acquired": acquired,
        "realestate_raw_computed": acquired,
        "current_signal_computed": False,
        "strict_score_eligible": False,
        "fidelity": "reconstructed_not_strict",
        "proxy_used": True,
        "minimum_industry_observations": 5,
        "remaining_blocker": (
            "sic2_month_mean_requires_at_least_5_issuers"
            if acquired
            else "rendered_ppe_inputs_missing"
        ),
        "records": records,
    }


__all__ = [
    "build_rendered_realestate_evidence",
    "extract_rendered_realestate_inputs",
    "locate_rendered_ppe_report",
]
