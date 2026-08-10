"""Causal, positive-evidence SEC reconstruction of the OpenAP Spinoff signal.

SEC filings can prove that a current issuer completed a spin-off, but they do
not reproduce CRSP acquisition flags or PERMNO age.  This module therefore
emits values only for issuers with an explicit completed-event date in their
own causal filings and never promotes the reconstruction to the strict score.
"""

from __future__ import annotations

from datetime import date
from html.parser import HTMLParser
import re
from typing import Any
from urllib.parse import urlparse

import numpy as np
import pandas as pd


SPINOFF_FORMULA_SHA256 = (
    "8ab61e7a77f8d93bf0d53647d17efa8d27f6072d3e113c5920810ce182d1ab7b"
)
SPINOFF_FORMULA_URL = (
    "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
    "8db892442c2c3a3779b0f1eac4370d3655be15a1/"
    "Signals/pyCode/Predictors/Spinoff.py"
)
SEC_CURRENT_IDENTITY_URL = (
    "https://www.sec.gov/files/company_tickers_exchange.json"
)

_INITIAL_FORM_10 = frozenset({"10-12B", "10-12G"})
_EVIDENCE_FORMS = frozenset(
    {"10-12B", "10-12B/A", "10-12G", "10-12G/A", "8-K", "10-Q", "10-K"}
)
_SUBMISSION_REQUIRED = frozenset(
    {
        "cik",
        "accession_number",
        "accepted_at",
        "filing_date",
        "form",
        "primary_document",
        "source",
    }
)
_UNIVERSE_REQUIRED = frozenset(
    {
        "security_id",
        "ticker",
        "cik",
        "exchange_family",
        "issuer_share_class_count",
        "identity_available_at",
        "identity_source_url",
    }
)
_DOCUMENT_REQUIRED = frozenset(
    {
        "security_id",
        "ticker",
        "cik",
        "accession_number",
        "accepted_at",
        "form",
        "primary_document",
        "source_url",
        "retrieved_at",
        "transport_sha256",
        "document_text",
    }
)
_EVIDENCE_REQUIRED = frozenset(
    {
        "security_id",
        "ticker",
        "cik",
        "accession_number",
        "accepted_at",
        "event_date",
        "source_url",
        "retrieved_at",
        "transport_sha256",
        "evidence_quality",
    }
)
_CANDIDATE_COLUMNS = (
    "security_id",
    "ticker",
    "cik",
    "accession_number",
    "accepted_at",
    "form",
    "primary_document",
    "source_url",
)
_EVIDENCE_COLUMNS = (
    "security_id",
    "ticker",
    "cik",
    "accession_number",
    "accepted_at",
    "form",
    "event_date",
    "source_url",
    "retrieved_at",
    "transport_sha256",
    "evidence_quality",
)
_OUTPUT_COLUMNS = (
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
    "event_date",
    "event_age_months",
    "source_id",
    "source_url",
    "formula_id",
    "formula_sha256",
    "observation_count",
    "fidelity_class",
    "current_usable",
    "reason_if_missing",
    "caveat",
    "strict_score_eligible",
)
_ACCESSION_RE = re.compile(r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
_DOCUMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.(?:htm|html|txt)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SPIN_TERM = r"spin[\s-]?off"
_MONTH_DATE_TOKEN = (
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+[0-9]{1,2},\s+20[0-9]{2}"
)
_DATE_TOKEN = rf"(?:{_MONTH_DATE_TOKEN}|20[0-9]{{2}}-[0-9]{{2}}-[0-9]{{2}})"
_COMPLETION_DATE_PATTERNS = tuple(
    re.compile(pattern, flags=re.IGNORECASE)
    for pattern in (
        rf"(?:on\s+)?(?P<event_date>{_DATE_TOKEN})\s*,?[^.\n]{{0,180}}"
        rf"completed\s+(?:the\s+)?{_SPIN_TERM}",
        rf"(?:on\s+)?(?P<event_date>{_DATE_TOKEN})\s*,?[^.\n]{{0,180}}"
        rf"{_SPIN_TERM}\s+(?:was|has\s+been)\s+completed",
        rf"{_SPIN_TERM}\s+(?:was|has\s+been)\s+completed\s+(?:on\s+)?"
        rf"(?P<event_date>{_DATE_TOKEN})",
        rf"completed\s+(?:the\s+)?{_SPIN_TERM}[^.\n]{{0,100}}\s+on\s+"
        rf"(?P<event_date>{_DATE_TOKEN})",
        rf"(?:on\s+)?(?P<event_date>{_DATE_TOKEN})\s*,?[^.\n]{{0,180}}"
        rf"became\s+an?\s+independent[^.\n]{{0,180}}completion\s+of\s+"
        rf"(?:the\s+)?{_SPIN_TERM}",
        rf"(?:on\s+)?(?P<event_date>{_DATE_TOKEN})\s*,?[^.\n]{{0,180}}"
        rf"completed\s+(?:its|the)\s+separation[^.\n]{{0,180}}"
        rf"{_SPIN_TERM}",
    )
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._excluded_depth = 0
        self.parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag.lower() in {"script", "style", "noscript"}:
            self._excluded_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._excluded_depth = max(0, self._excluded_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._excluded_depth == 0 and data.strip():
            self.parts.append(data)


def _require_columns(
    frame: pd.DataFrame,
    required: frozenset[str],
    label: str,
) -> None:
    missing = sorted(required.difference(frame.columns))
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
    return str(value).strip()


def _cik(value: object) -> str:
    text = _clean_text(value)
    if re.fullmatch(r"[0-9]{1,10}", text):
        return f"{int(text):010d}"
    if re.fullmatch(r"[0-9]{1,10}\.0+", text):
        return f"{int(float(text)):010d}"
    return ""


def _timestamp(value: object) -> pd.Timestamp:
    try:
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
    except (TypeError, ValueError):
        return pd.NaT
    if pd.isna(parsed):
        return pd.NaT
    return pd.Timestamp(parsed)


def _official_filing_url(value: object, *, cik: str = "") -> bool:
    try:
        parsed = urlparse(_clean_text(value))
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.netloc.lower() != "www.sec.gov":
        return False
    prefix = "/Archives/edgar/data/"
    if not parsed.path.startswith(prefix):
        return False
    if cik:
        unpadded = str(int(cik))
        return parsed.path.startswith(f"{prefix}{unpadded}/")
    return True


def _month_start(value: object) -> pd.Timestamp:
    timestamp = _timestamp(value)
    if pd.isna(timestamp):
        return pd.NaT
    return timestamp.tz_localize(None).to_period("M").to_timestamp()


def _event_is_causal(row: pd.Series) -> bool:
    event_date = row.get("event_date")
    accepted_at = row.get("accepted_at")
    if pd.isna(event_date) or pd.isna(accepted_at):
        return False
    return bool(event_date <= accepted_at.date())


def _filing_url(cik: str, accession: str, primary_document: str) -> str:
    accession_path = accession.replace("-", "")
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{int(cik)}/{accession_path}/{primary_document}"
    )


def select_sec_spinoff_filing_candidates(
    submissions: pd.DataFrame,
    current_universe: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    lookback_months: int = 36,
) -> pd.DataFrame:
    """Select bounded official filing documents for recent Form 10 issuers."""

    _require_columns(submissions, _SUBMISSION_REQUIRED, "SEC submissions")
    _require_columns(current_universe, _UNIVERSE_REQUIRED, "current universe")
    formation = _timestamp(formation_at)
    if pd.isna(formation) or lookback_months < 24 or lookback_months > 60:
        raise ValueError("Spinoff formation or lookback is invalid")
    universe = current_universe.copy()
    universe["cik"] = universe["cik"].map(_cik)
    universe["security_id"] = universe["security_id"].map(_clean_text)
    universe["ticker"] = universe["ticker"].map(
        lambda value: _clean_text(value).upper()
    )
    if (
        universe[["security_id", "ticker", "cik"]].eq("").any().any()
        or universe["security_id"].duplicated(keep=False).any()
        or universe["cik"].duplicated(keep=False).any()
    ):
        raise ValueError("current universe identity is blank or ambiguous")

    frame = submissions.copy()
    frame["cik"] = frame["cik"].map(_cik)
    frame["accession_number"] = frame["accession_number"].map(_clean_text)
    frame["accepted_at"] = frame["accepted_at"].map(_timestamp)
    frame["form"] = frame["form"].map(lambda value: _clean_text(value).upper())
    frame["primary_document"] = frame["primary_document"].map(_clean_text)
    frame["source"] = frame["source"].map(_clean_text)
    lookback = _month_start(formation) - pd.DateOffset(months=lookback_months)
    frame = frame.loc[
        frame["cik"].ne("")
        & frame["cik"].isin(universe["cik"])
        & frame["accepted_at"].notna()
        & frame["accepted_at"].le(formation)
        & frame["accepted_at"].map(_month_start).ge(lookback)
        & frame["form"].isin(_EVIDENCE_FORMS)
        & frame["accession_number"].map(
            lambda value: _ACCESSION_RE.fullmatch(value) is not None
        )
        & frame["primary_document"].map(
            lambda value: _DOCUMENT_RE.fullmatch(value) is not None
        )
        & frame["source"].isin({"sec_submissions_bulk", "sec_submissions_api"})
    ].copy()
    initial = frame.loc[frame["form"].isin(_INITIAL_FORM_10)]
    if initial.empty:
        return pd.DataFrame(columns=_CANDIDATE_COLUMNS)
    first_form_10 = initial.groupby("cik")["accepted_at"].min()
    frame = frame.loc[frame["cik"].isin(first_form_10.index)].copy()
    frame = frame.loc[
        frame.apply(
            lambda row: row["accepted_at"] >= first_form_10.loc[row["cik"]],
            axis=1,
        )
    ]
    frame = frame.merge(
        universe[["security_id", "ticker", "cik"]],
        on="cik",
        how="inner",
        validate="many_to_one",
    )
    frame["source_url"] = frame.apply(
        lambda row: _filing_url(
            row["cik"],
            row["accession_number"],
            row["primary_document"],
        ),
        axis=1,
    )
    frame = frame.sort_values(
        ["security_id", "accepted_at", "accession_number"],
        kind="stable",
    ).drop_duplicates(
        ["security_id", "accession_number"], keep="first"
    )
    bounded: list[pd.DataFrame] = []
    for _, issuer in frame.groupby("security_id", sort=False):
        form_10 = issuer.loc[issuer["form"].str.startswith("10-12")]
        context = pd.concat(
            [
                issuer.loc[issuer["form"].eq("8-K")].head(8),
                issuer.loc[issuer["form"].eq("10-Q")].head(3),
                issuer.loc[issuer["form"].eq("10-K")].head(2),
            ],
            ignore_index=False,
        )
        bounded.append(
            pd.concat([form_10, context], ignore_index=False).drop_duplicates(
                ["accession_number"], keep="first"
            )
        )
    return pd.concat(bounded, ignore_index=True)[list(_CANDIDATE_COLUMNS)].sort_values(
        ["security_id", "accepted_at", "accession_number"],
        kind="stable",
    ).reset_index(drop=True)


def _plain_text(value: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(str(value))
        parser.close()
    except (ValueError, AssertionError):
        return ""
    text = " ".join(parser.parts) if parser.parts else str(value)
    text = text.replace("\u2010", "-").replace("\u2011", "-")
    text = text.replace("\u2012", "-").replace("\u2013", "-")
    return re.sub(r"\s+", " ", text).strip()


def _parsed_date(value: str) -> date | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    timestamp = pd.Timestamp(parsed)
    if not 1990 <= timestamp.year <= 2100:
        return None
    return timestamp.date()


def detect_sec_spinoff_completion_date(document_text: str) -> date | None:
    """Return an explicit completed spin-off date, never a proposed date."""

    text = _plain_text(document_text)
    if not text:
        return None
    for pattern in _COMPLETION_DATE_PATTERNS:
        for match in pattern.finditer(text):
            prefix = text[max(0, match.start() - 90) : match.start()].lower()
            if re.search(
                r"\b(?:if|may|might|could|would|expected|expects|anticipated|"
                r"planned|proposed|subject\s+to)\b",
                prefix,
            ):
                continue
            event_date = _parsed_date(match.group("event_date"))
            if event_date is not None:
                return event_date
    return None


def extract_sec_spinoff_completion_evidence(
    documents: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Reduce downloaded filing documents to causal positive event evidence."""

    _require_columns(documents, _DOCUMENT_REQUIRED, "SEC filing documents")
    formation = _timestamp(formation_at)
    if pd.isna(formation):
        raise ValueError("Spinoff formation_at is invalid")
    rows: list[dict[str, Any]] = []
    for document in documents.to_dict(orient="records"):
        cik = _cik(document["cik"])
        accepted = _timestamp(document["accepted_at"])
        retrieved = _timestamp(document["retrieved_at"])
        source_url = _clean_text(document["source_url"])
        digest = _clean_text(document["transport_sha256"]).lower()
        event_date = detect_sec_spinoff_completion_date(
            _clean_text(document["document_text"])
        )
        if (
            not cik
            or pd.isna(accepted)
            or accepted > formation
            or pd.isna(retrieved)
            or not _official_filing_url(source_url, cik=cik)
            or _SHA256_RE.fullmatch(digest) is None
            or event_date is None
            or event_date > accepted.date()
            or event_date > formation.date()
        ):
            continue
        rows.append(
            {
                "security_id": _clean_text(document["security_id"]),
                "ticker": _clean_text(document["ticker"]).upper(),
                "cik": cik,
                "accession_number": _clean_text(document["accession_number"]),
                "accepted_at": accepted,
                "form": _clean_text(document["form"]).upper(),
                "event_date": event_date,
                "source_url": source_url,
                "retrieved_at": retrieved,
                "transport_sha256": digest,
                "evidence_quality": (
                    "sec_filing_explicit_completed_spinoff_with_event_date"
                ),
            }
        )
    evidence = pd.DataFrame(rows, columns=_EVIDENCE_COLUMNS)
    if evidence.empty:
        return evidence
    return evidence.sort_values(
        ["security_id", "event_date", "accepted_at", "accession_number"],
        kind="stable",
    ).drop_duplicates(
        ["security_id", "accession_number", "event_date"], keep="first"
    ).reset_index(drop=True)


def calculate_sec_spinoff_current(
    evidence: pd.DataFrame,
    current_universe: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Calculate a non-strict Spinoff value only for explicitly proven events."""

    _require_columns(evidence, _EVIDENCE_REQUIRED, "SEC spin-off evidence")
    _require_columns(current_universe, _UNIVERSE_REQUIRED, "current universe")
    formation = _timestamp(formation_at)
    retrieved = _timestamp(retrieved_at)
    if pd.isna(formation) or pd.isna(retrieved):
        raise ValueError("Spinoff formation_at or retrieved_at is invalid")
    universe = current_universe.copy()
    universe["security_id"] = universe["security_id"].map(_clean_text)
    universe["ticker"] = universe["ticker"].map(
        lambda value: _clean_text(value).upper()
    )
    universe["cik"] = universe["cik"].map(_cik)
    if universe["security_id"].duplicated(keep=False).any():
        raise ValueError("current universe has duplicate security_id")

    normalized = evidence.copy()
    normalized["security_id"] = normalized["security_id"].map(_clean_text)
    normalized["ticker"] = normalized["ticker"].map(
        lambda value: _clean_text(value).upper()
    )
    normalized["cik"] = normalized["cik"].map(_cik)
    normalized["accepted_at"] = normalized["accepted_at"].map(_timestamp)
    normalized["retrieved_at"] = normalized["retrieved_at"].map(_timestamp)
    normalized["source_url"] = normalized["source_url"].map(_clean_text)
    normalized["transport_sha256"] = normalized["transport_sha256"].map(
        lambda value: _clean_text(value).lower()
    )
    normalized["event_date"] = pd.to_datetime(
        normalized["event_date"], errors="coerce"
    ).dt.date
    normalized = normalized.loc[
        normalized["accepted_at"].notna()
        & normalized["accepted_at"].le(formation)
        & normalized["retrieved_at"].notna()
        & normalized["event_date"].notna()
        & normalized["event_date"].le(formation.date())
        & normalized.apply(_event_is_causal, axis=1)
        & normalized["evidence_quality"].eq(
            "sec_filing_explicit_completed_spinoff_with_event_date"
        )
        & normalized.apply(
            lambda row: _official_filing_url(row["source_url"], cik=row["cik"]),
            axis=1,
        )
        & normalized["transport_sha256"].map(
            lambda value: _SHA256_RE.fullmatch(value) is not None
        )
    ].copy()
    formation_month = _month_start(formation)
    rows: list[dict[str, Any]] = []
    for current in universe.sort_values("security_id").to_dict(orient="records"):
        security_id = _clean_text(current["security_id"])
        ticker = _clean_text(current["ticker"]).upper()
        cik = _cik(current["cik"])
        identity_available = _timestamp(current["identity_available_at"])
        identity_source = _clean_text(current["identity_source_url"])
        share_classes = pd.to_numeric(
            current["issuer_share_class_count"], errors="coerce"
        )
        issuer = normalized.loc[
            normalized["security_id"].eq(security_id)
            & normalized["cik"].eq(cik)
            & normalized["ticker"].eq(ticker)
        ].sort_values(["event_date", "accepted_at", "accession_number"])
        value: float | None = None
        event_date: date | None = None
        event_age: int | None = None
        filed_at = pd.NaT
        available_at = identity_available
        source_url = identity_source
        reason = ""
        if not security_id or not ticker or not cik:
            reason = "invalid_current_security_identity"
        elif pd.isna(identity_available) or identity_available > formation:
            reason = "current_identity_available_after_formation_or_invalid"
        elif identity_source != SEC_CURRENT_IDENTITY_URL:
            reason = "current_identity_source_is_not_official_sec"
        elif pd.isna(share_classes) or float(share_classes) != 1.0:
            reason = "current_issuer_has_multiple_share_classes"
        elif issuer.empty:
            reason = "completed_spinoff_event_not_proven"
        elif issuer["event_date"].nunique() != 1:
            reason = "conflicting_completed_spinoff_event_dates"
        else:
            proven = issuer.iloc[0]
            event_date = proven["event_date"]
            event_month = pd.Timestamp(event_date).to_period("M").to_timestamp()
            event_age = int(
                formation_month.to_period("M").ordinal
                - event_month.to_period("M").ordinal
            )
            if event_age < 0:
                reason = "completed_spinoff_event_after_formation"
            else:
                value = float(event_age <= 24)
                filed_at = proven["accepted_at"]
                available_at = max(identity_available, filed_at)
                source_url = str(proven["source_url"])
        finite = value is not None and np.isfinite(float(value))
        rows.append(
            {
                "security_id": security_id,
                "ticker": ticker,
                "cik": cik,
                "signal": "Spinoff",
                "formation_at": formation.isoformat(),
                "period_end": formation_month.date().isoformat(),
                "filed_at": "" if pd.isna(filed_at) else filed_at.isoformat(),
                "available_at": (
                    "" if pd.isna(available_at) else available_at.isoformat()
                ),
                "retrieved_at": retrieved.isoformat(),
                "value": float(value) if finite else float("nan"),
                "event_date": "" if event_date is None else event_date.isoformat(),
                "event_age_months": (
                    float("nan") if event_age is None else int(event_age)
                ),
                "source_id": "sec_edgar_submissions_and_filings",
                "source_url": source_url,
                "formula_id": "openap_spinoff_completed_event_age_le_24",
                "formula_sha256": SPINOFF_FORMULA_SHA256,
                "observation_count": int(len(issuer)),
                "fidelity_class": "reconstructed" if finite else "unavailable",
                "current_usable": bool(finite),
                "reason_if_missing": "" if finite else reason,
                "caveat": (
                    "SEC completed-event date approximates the start of CRSP "
                    "FirmAgeNoScreen and does not establish PERMNO history"
                ),
                "strict_score_eligible": False,
            }
        )
    return pd.DataFrame(rows, columns=_OUTPUT_COLUMNS).reset_index(drop=True)


__all__ = [
    "SEC_CURRENT_IDENTITY_URL",
    "SPINOFF_FORMULA_SHA256",
    "SPINOFF_FORMULA_URL",
    "calculate_sec_spinoff_current",
    "detect_sec_spinoff_completion_date",
    "extract_sec_spinoff_completion_evidence",
    "select_sec_spinoff_filing_candidates",
]
