"""Official FINRA source probe and fail-closed evidence for short-interest signals."""

from __future__ import annotations

from hashlib import sha256
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse
import json
import re
import time
import urllib.request
import zipfile

import pandas as pd


FINRA_FILES_URL = (
    "https://www.finra.org/finra-data/browse-catalog/equity-short-interest/files"
)
FINRA_ABOUT_URL = (
    "https://www.finra.org/finra-data/browse-catalog/equity-short-interest"
)
FINRA_GLOSSARY_URL = (
    "https://www.finra.org/finra-data/browse-catalog/equity-short-interest/glossary"
)
FINRA_SCHEDULE_URL = (
    "https://www.finra.org/filing-reporting/regulatory-filing-systems/short-interest"
)
OPENAP_COMMIT = "8db892442c2c3a3779b0f1eac4370d3655be15a1"
OPENAP_FORMULA_SOURCES = {
    "ShortInterest": {
        "path": "Signals/pyCode/Predictors/ShortInterest.py",
        "sha256": "25baaf9fd432a4b4805e57cddfb7cb7882eddf8ea27d3cde5b502c304d932b94",
    },
    "IO_ShortInterest": {
        "path": "Signals/pyCode/Predictors/IO_ShortInterest.py",
        "sha256": "716310d258802f2a9bc5cf3f02ae012b3e59908a932c75dd5a0701833e222b26",
    },
    "Recomm_ShortInterest": {
        "path": "Signals/pyCode/Predictors/Recomm_ShortInterest.py",
        "sha256": "154a287aa7b4a16ac5af0990b7d1d7712d8bd01fe98f93e250405c470e0f772e",
    },
}

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED_COLUMNS = (
    "settlement_date",
    "issue_name",
    "symbol",
    "market",
    "current_short",
    "previous_short",
    "revision_flag",
)
_HEADER_ALIASES = {
    "date": "settlement_date",
    "settlementdate": "settlement_date",
    "issuename": "issue_name",
    "symbol": "symbol",
    "issuesymbolidentifier": "symbol",
    "market": "market",
    "marketcategorycode": "market",
    "currentshort": "current_short",
    "currentshortposition": "current_short",
    "currentshortpositionquantity": "current_short",
    "currentshortsharenumber": "current_short",
    "previousshort": "previous_short",
    "previousshortposition": "previous_short",
    "previousshortpositionquantity": "previous_short",
    "previousshortsharenumber": "previous_short",
    "revisionflag": "revision_flag",
}


class _FinraLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.hrefs.append(href.strip())


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data)


def extract_visible_text(html: str) -> str:
    """Convert official HTML to normalized visible text for semantic checks."""

    parser = _VisibleTextParser()
    parser.feed(str(html))
    text = " ".join(parser.parts).lower()
    for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        text = text.replace(dash, "-")
    return " ".join(text.replace("\xa0", " ").split())


def extract_finra_file_links(html: str) -> tuple[str, ...]:
    """Extract unique HTTPS links hosted by FINRA's public download CDN."""

    parser = _FinraLinkParser()
    parser.feed(str(html))
    links: list[str] = []
    seen: set[str] = set()
    for href in parser.hrefs:
        parsed = urlparse(href)
        if parsed.scheme != "https" or parsed.hostname != "cdn.finra.org":
            continue
        named_short_interest = re.search(
            r"short[-_]?interest|shortinterest", parsed.path, re.I
        )
        dated_biweekly = re.fullmatch(
            r"/equity/otcmarket/biweekly/shrt\d{8}\.csv", parsed.path, re.I
        )
        if not named_short_interest and not dated_biweekly:
            continue
        if href not in seen:
            seen.add(href)
            links.append(href)
    if not links:
        raise ValueError("No official FINRA short-interest file links found")
    return tuple(links)


def _normalise_header(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def parse_finra_short_interest_text(text: str) -> pd.DataFrame:
    """Parse an official delimited public file into a strict minimal schema."""

    source = str(text).lstrip("\ufeff")
    first_line = source.splitlines()[0] if source.splitlines() else ""
    separator = "|" if "|" in first_line else ("\t" if "\t" in first_line else ",")
    rows = pd.read_csv(StringIO(source), sep=separator, dtype="string")
    rename = {
        column: _HEADER_ALIASES[_normalise_header(column)]
        for column in rows.columns
        if _normalise_header(column) in _HEADER_ALIASES
    }
    rows = rows.rename(columns=rename)
    missing = set(_REQUIRED_COLUMNS) - set(rows.columns)
    if missing:
        raise ValueError(f"FINRA short-interest file is missing columns: {sorted(missing)}")
    rows = rows.loc[:, list(_REQUIRED_COLUMNS)].copy()
    for column in _REQUIRED_COLUMNS:
        rows[column] = rows[column].astype("string").str.strip()
    rows = rows.loc[rows["symbol"].fillna("").ne("")].reset_index(drop=True)
    if rows.empty:
        raise ValueError("FINRA short-interest file contains no security rows")
    return rows


def _parse_settlement_dates(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    compact = text.str.fullmatch(r"\d{8}", na=False)
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    if compact.any():
        parsed.loc[compact] = pd.to_datetime(
            text.loc[compact], format="%Y%m%d", errors="coerce"
        )
    if (~compact).any():
        parsed.loc[~compact] = pd.to_datetime(text.loc[~compact], errors="coerce")
    return parsed


def summarize_finra_short_interest_rows(
    chunks: Iterable[pd.DataFrame],
) -> dict[str, Any]:
    """Measure source rows without claiming exact signal coverage or fidelity."""

    frames: list[pd.DataFrame] = []
    for chunk in chunks:
        missing = set(_REQUIRED_COLUMNS) - set(chunk.columns)
        if missing:
            raise ValueError(f"FINRA short-interest rows are missing columns: {sorted(missing)}")
        frames.append(chunk.loc[:, list(_REQUIRED_COLUMNS)].copy())
    if not frames:
        raise ValueError("FINRA short-interest rows contain no chunks")
    rows = pd.concat(frames, ignore_index=True)
    if rows.empty:
        raise ValueError("FINRA short-interest rows contain no records")
    dates = _parse_settlement_dates(rows["settlement_date"])
    if dates.isna().any():
        raise ValueError("FINRA short-interest rows contain invalid settlement dates")
    current = pd.to_numeric(rows["current_short"], errors="coerce")
    previous = pd.to_numeric(rows["previous_short"], errors="coerce")
    if current.notna().sum() == 0 or previous.notna().sum() == 0:
        raise ValueError("FINRA short-interest rows contain no numeric positions")
    market = rows["market"].fillna("").astype(str).str.strip().str.upper()
    otc = market.str.contains("OTC", regex=False)
    revision = rows["revision_flag"].fillna("").astype(str).str.strip().str.upper()
    revision_flagged = ~revision.isin({"", "N", "NO", "FALSE", "0"})
    symbols = rows["symbol"].fillna("").astype(str).str.strip()
    return {
        "rows": len(rows),
        "unique_symbols": int(symbols.loc[symbols.ne("")].nunique()),
        "listed_rows": int((~otc).sum()),
        "otc_rows": int(otc.sum()),
        "missing_current_short": int(current.isna().sum()),
        "revision_flagged_rows": int(revision_flagged.sum()),
        "first_settlement_date": dates.min().date().isoformat(),
        "last_settlement_date": dates.max().date().isoformat(),
        "markets": sorted(set(market.loc[market.ne("")])),
        "signal_coverage_measured": False,
    }


def _headers() -> dict[str, str]:
    return {
        "User-Agent": "Aurora-OpenAP-181-short-interest-probe/1.0",
        "Accept": "text/html,text/plain,application/zip,application/octet-stream",
    }


def _fetch(url: str, *, attempts: int = 4) -> tuple[bytes, str]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=_headers())
            with urllib.request.urlopen(request, timeout=180) as response:
                return response.read(), response.headers.get_content_type()
        except Exception as exc:  # pragma: no cover - exercised in GitHub Actions
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"Unable to fetch {url}: {last_error}")


def _decode_public_file(payload: bytes) -> str:
    if payload.startswith(b"PK\x03\x04"):
        from io import BytesIO

        with zipfile.ZipFile(BytesIO(payload)) as archive:
            members = [name for name in archive.namelist() if not name.endswith("/")]
            if len(members) != 1:
                raise ValueError(f"Expected one file in FINRA archive; found {members}")
            payload = archive.read(members[0])
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Unable to decode FINRA short-interest file")


def _formula_requirements() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal": "ShortInterest",
                "formula": "shortint / shrout",
                "public_numerator": "FINRA listed short-interest files since June 2021",
                "missing_exact_inputs": "exact_monthly_crsp_shrout;historical_gvkey_permno_identity",
            },
            {
                "signal": "IO_ShortInterest",
                "formula": "monthly short-interest tail combined with instown_perc",
                "public_numerator": "FINRA listed short-interest files since June 2021",
                "missing_exact_inputs": "exact_monthly_crsp_shrout;exact_tr_13f_instown_perc;historical_identity",
            },
            {
                "signal": "Recomm_ShortInterest",
                "formula": "monthly short-interest quintile combined with recommendation quintile",
                "public_numerator": "FINRA listed short-interest files since June 2021",
                "missing_exact_inputs": "exact_monthly_crsp_shrout;exact_ibes_individual_recommendation_history;historical_identity",
            },
        ]
    )


def build_short_interest_batch_evidence(
    probe: Mapping[str, Any],
    *,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> pd.DataFrame:
    """Create concrete blocker evidence without promoting any signal."""

    required_true = (
        "formula_sources_verified",
        "finra_files_page_verified",
        "finra_about_page_verified",
        "finra_glossary_verified",
        "finra_schedule_verified",
        "latest_public_file_verified",
    )
    valid = (
        all(probe.get(field) is True for field in required_true)
        and probe.get("listed_history_start") == "2021-06-01"
        and probe.get("historical_revisions_available") is False
        and probe.get("raw_redistribution_authorized") is False
        and probe.get("raw_files_in_artifact") is False
        and str(evidence_run_url).startswith("https://")
        and bool(str(evidence_artifact).strip())
        and bool(_COMMIT_RE.fullmatch(str(implementation_commit)))
    )
    if not valid:
        raise ValueError("Invalid or incomplete short-interest probe evidence")
    blockers = {
        "ShortInterest": (
            "short_interest_source_partial:finra_listed_numerator_available_since_"
            "2021_06_but_exact_monthly_crsp_shrout_historical_gvkey_permno_identity_"
            "and_revision_vintages_are_unavailable"
        ),
        "IO_ShortInterest": (
            "short_interest_source_partial:finra_listed_numerator_available_but_"
            "exact_monthly_crsp_shrout_exact_tr_13f_instown_perc_historical_identity_"
            "and_stock_level_fidelity_are_unverified"
        ),
        "Recomm_ShortInterest": (
            "short_interest_source_partial:finra_listed_numerator_available_but_"
            "exact_monthly_crsp_shrout_exact_ibes_individual_recommendation_history_"
            "historical_identity_and_stock_level_fidelity_are_unverified"
        ),
    }
    return pd.DataFrame(
        [
            {
                "signal": signal,
                "formula_implemented": True,
                "data_pipeline_implemented": False,
                "point_in_time_verified": False,
                "identity_verified": False,
                "coverage_measured": False,
                "fidelity_measured": False,
                "coverage_result": "not_measured",
                "fidelity_result": "not_measured",
                "strict_gate_result": "blocked",
                "blocking_reason": blocker,
                "evidence_run_url": str(evidence_run_url),
                "evidence_artifact": str(evidence_artifact).strip(),
                "implementation_commit": str(implementation_commit),
            }
            for signal, blocker in blockers.items()
        ]
    )


def _latest_link(links: tuple[str, ...]) -> str:
    def date_key(url: str) -> tuple[int, str]:
        digits = re.findall(r"(?:20\d{2})[-_/]?(?:0[1-9]|1[0-2])[-_/]?(?:0[1-9]|[12]\d|3[01])", url)
        compact = re.sub(r"\D", "", digits[-1]) if digits else ""
        return (int(compact) if len(compact) == 8 else 0, url)

    return max(links, key=date_key)


def run_short_interest_source_probe(
    *,
    output_dir: Path,
    download_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> dict[str, Any]:
    """Probe one latest official file and write metadata-only evidence."""

    output_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)
    files_payload, _ = _fetch(FINRA_FILES_URL)
    about_payload, _ = _fetch(FINRA_ABOUT_URL)
    glossary_payload, _ = _fetch(FINRA_GLOSSARY_URL)
    schedule_payload, _ = _fetch(FINRA_SCHEDULE_URL)
    files_text = files_payload.decode("utf-8", errors="replace")
    files_visible = extract_visible_text(files_text)
    about = extract_visible_text(about_payload.decode("utf-8", errors="replace"))
    glossary = extract_visible_text(
        glossary_payload.decode("utf-8", errors="replace")
    )
    schedule = extract_visible_text(
        schedule_payload.decode("utf-8", errors="replace")
    )
    links = extract_finra_file_links(files_text)
    files_verified = (
        "equity short interest files" in files_visible
        and bool(links)
        and ("archive files" in files_visible or "otce.finra.org" in files_text.lower())
    )
    about_verified = (
        "five years" in about
        and "business day" in about
        and "most recent" in about
        and ("exchange-listed" in about or "exchange listed" in about)
        and ("over-the-counter" in about or "otc" in about)
    )
    glossary_document_verified = "equity short interest data glossary" in glossary
    schedule_verified = all(
        field in schedule for field in ("settlement date", "due date", "publication date")
    )
    documentation_checks = {
        "files": files_verified,
        "about": about_verified,
        "glossary": glossary_document_verified,
        "schedule": schedule_verified,
    }
    failed_checks = [name for name, passed in documentation_checks.items() if not passed]
    if failed_checks:
        raise ValueError(
            "Official FINRA short-interest documentation contract drifted: "
            + ",".join(failed_checks)
        )

    formula_verified = True
    for source in OPENAP_FORMULA_SOURCES.values():
        url = (
            "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
            f"{OPENAP_COMMIT}/{source['path']}"
        )
        payload, _ = _fetch(url)
        formula_verified &= sha256(payload).hexdigest() == source["sha256"]
    if not formula_verified:
        raise ValueError("Pinned OpenAP short-interest formula source hash mismatch")

    latest_url = _latest_link(links)
    public_payload, content_type = _fetch(latest_url)
    raw_target = download_dir / Path(urlparse(latest_url).path).name
    raw_target.write_bytes(public_payload)
    rows = parse_finra_short_interest_text(_decode_public_file(public_payload))
    metrics = summarize_finra_short_interest_rows([rows])
    glossary_verified = glossary_document_verified and set(_REQUIRED_COLUMNS).issubset(
        rows.columns
    )
    summary = {
        "formula_sources_verified": True,
        "finra_files_page_verified": files_verified,
        "finra_about_page_verified": about_verified,
        "finra_glossary_verified": glossary_verified,
        "finra_schedule_verified": schedule_verified,
        "latest_public_file_verified": True,
        "latest_public_file_url": latest_url,
        "public_file_links_found": len(links),
        "listed_history_start": "2021-06-01",
        "historical_revisions_available": False,
        "raw_redistribution_authorized": False,
        "raw_files_in_artifact": False,
        "source_metrics": metrics,
        "strict_approved": 0,
        "locked_opened": False,
        "validation_used_for_selection": False,
    }
    evidence = build_short_interest_batch_evidence(
        summary,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    integrity = pd.DataFrame(
        [
            {
                "source_url": latest_url,
                "sha256": sha256(public_payload).hexdigest(),
                "size_bytes": len(public_payload),
                "content_type": content_type,
                "download_verified": True,
                "raw_in_artifact": False,
            }
        ]
    )
    (output_dir / "short_interest_source_probe.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    pd.DataFrame([metrics]).to_csv(
        output_dir / "finra_short_interest_source_metrics.csv", index=False
    )
    integrity.to_csv(output_dir / "finra_short_interest_file_integrity.csv", index=False)
    _formula_requirements().to_csv(
        output_dir / "short_interest_formula_requirements.csv", index=False
    )
    evidence.to_csv(output_dir / "short_interest_batch_evidence.csv", index=False)
    report = "\n".join(
        (
            "# FINRA short-interest source probe",
            "",
            f"- Official files discovered: {len(links)}",
            f"- Latest bounded file: {latest_url}",
            f"- Rows measured: {metrics['rows']}",
            f"- Settlement dates: {metrics['first_settlement_date']} to {metrics['last_settlement_date']}",
            "- Listed history starts in June 2021; earlier public files are OTC-only.",
            "- Historical correction vintages are not retained by the public product.",
            "- Raw source file omitted from the artifact.",
            "- Strict approvals: 0. All three signals remain blocked on exact inputs, identity, PIT, coverage and fidelity.",
            "",
        )
    )
    (output_dir / "SHORT_INTEREST_SOURCE_PROBE_REPORT.md").write_text(
        report, encoding="utf-8"
    )
    return summary


__all__ = [
    "FINRA_ABOUT_URL",
    "FINRA_FILES_URL",
    "FINRA_GLOSSARY_URL",
    "FINRA_SCHEDULE_URL",
    "OPENAP_COMMIT",
    "OPENAP_FORMULA_SOURCES",
    "build_short_interest_batch_evidence",
    "extract_finra_file_links",
    "extract_visible_text",
    "parse_finra_short_interest_text",
    "run_short_interest_source_probe",
    "summarize_finra_short_interest_rows",
]
