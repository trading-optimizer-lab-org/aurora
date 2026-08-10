"""Fail-closed SEC filing evidence for historical listed-security identity.

The SEC observations produced here corroborate endpoints only.  They never
claim continuous ticker history, PERMNO equivalence, or strict-score fitness.
"""

from __future__ import annotations

from datetime import timedelta
import json
import re
from typing import Any, Mapping
from urllib.parse import urlparse

import pandas as pd


MAX_CORROBORATED_GAP_DAYS = 160
PERIODIC_FORMS = frozenset({"10-K", "10-Q", "20-F", "40-F"})
LISTING_CONCEPTS = (
    "TradingSymbol",
    "SecurityExchangeName",
    "Security12bTitle",
)

_FACT_REQUIRED_COLUMNS = frozenset(
    {
        "cik",
        "accession",
        "accepted_at",
        "form",
        "context_id",
        "concept",
        "value",
        "source_url",
    }
)
_NOTES_SUB_REQUIRED_COLUMNS = frozenset(
    {"adsh", "cik", "form", "accepted", "instance"}
)
_NOTES_TXT_REQUIRED_COLUMNS = frozenset(
    {"adsh", "tag", "version", "context", "iprx", "value"}
)
_NORMALIZED_FACT_COLUMNS = (
    "cik",
    "accession",
    "accepted_at",
    "form",
    "context_id",
    "concept",
    "value",
    "source_url",
    "transport_source_url",
    "transport_sha256",
    "transport_access_method",
    "taxonomy_version",
    "iprx",
)
_OBSERVATION_COLUMNS = (
    "cik",
    "accession",
    "accepted_at",
    "form",
    "context_id",
    "trading_symbol",
    "ticker_key",
    "exchange_name",
    "exchange_family",
    "security_title",
    "security_title_key",
    "source_url",
    "identity_quality",
)
_OBSERVATION_REJECTION_COLUMNS = (
    "cik",
    "accession",
    "accepted_at",
    "form",
    "context_id",
    "source_url",
    "reason_if_rejected",
)
_UNIVERSE_REQUIRED_COLUMNS = frozenset(
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
_CURRENT_UNIVERSE_COLUMNS = (
    "security_id",
    "ticker",
    "cik",
    "exchange_family",
    "issuer_share_class_count",
    "identity_available_at",
    "identity_source_url",
)
_CURRENT_UNIVERSE_REJECTION_COLUMNS = (
    "cik",
    "ticker",
    "exchange",
    "reason_if_rejected",
)
_INTERVAL_COLUMNS = (
    "security_id",
    "cik",
    "ticker",
    "ticker_key",
    "exchange_family",
    "security_title",
    "security_title_key",
    "valid_from",
    "valid_through",
    "start_accession",
    "end_evidence",
    "start_available_at",
    "end_available_at",
    "start_source_url",
    "end_source_url",
    "identity_quality",
    "historical_ticker_interval_verified",
    "strict_score_eligible",
)
_INTERVAL_REJECTION_COLUMNS = (
    "security_id",
    "cik",
    "accession",
    "accepted_at",
    "reason_if_rejected",
)
_EXCH_SWITCH_OUTPUT_COLUMNS = (
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
    "transition_from",
    "transition_to",
    "transition_detected_at",
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

EXCH_SWITCH_FORMULA_SHA256 = (
    "b6947fcace7abc2aa1d12f1f04bcd01a8151da7a8a4bfe15a9e56b8a294e6b5b"
)


class SecListingIdentityError(ValueError):
    """Input evidence violates the historical identity contract."""


def _require_columns(
    frame: pd.DataFrame,
    required: frozenset[str],
    label: str,
) -> None:
    missing = required.difference(frame.columns)
    if missing:
        raise SecListingIdentityError(
            f"{label} is missing columns: {sorted(missing)}"
        )


def _utc_timestamp(value: Any) -> pd.Timestamp:
    try:
        timestamp = pd.to_datetime(value, errors="coerce", utc=True)
    except (TypeError, ValueError):
        return pd.NaT
    if pd.isna(timestamp):
        return pd.NaT
    return pd.Timestamp(timestamp)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        return ""
    return str(value).strip()


def _normalize_cik(value: Any) -> str:
    text = _clean_text(value)
    if re.fullmatch(r"\d{1,10}", text):
        return f"{int(text):010d}"
    if re.fullmatch(r"\d{1,10}\.0", text):
        return f"{int(float(text)):010d}"
    return ""


def _identity_key(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", _clean_text(value).upper())


def normalize_exchange_family(value: Any) -> str:
    """Normalize SEC and provider exchange labels without guessing unknowns."""

    key = _identity_key(value)
    if key in {"XNAS", "XNGS", "XNMS", "XNCM"} or "NASDAQ" in key:
        return "NASDAQ"
    if key in {"XNYS", "NYSE", "NEWYORKSTOCKEXCHANGE"}:
        return "NYSE"
    if key in {"XASE", "AMEX", "NYSEAMER", "NYSEAMERICAN"}:
        return "NYSE_AMERICAN"
    if key in {"ARCX", "NYSEARCA"}:
        return "NYSE_ARCA"
    if key in {"BATS", "BZX", "CBOEBZX", "CBOEBZXEXCHANGE"}:
        return "CBOE_BZX"
    return ""


def parse_current_sec_identity_response(
    content: bytes,
    *,
    access_method: str,
) -> Mapping[str, Any]:
    """Parse direct SEC JSON or the bounded Jina read-through wrapper."""

    try:
        text = bytes(content).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SecListingIdentityError(
            "SEC current identity response is not UTF-8"
        ) from exc
    method = _clean_text(access_method)
    if method == "sec_official_direct":
        candidate = text.strip()
    elif method == "sec_via_jina_readthrough":
        marker = "Markdown Content:"
        if marker not in text:
            raise SecListingIdentityError(
                "SEC identity readthrough response lacks JSON marker"
            )
        candidate = text.split(marker, 1)[1].strip()
        if candidate.startswith("```json"):
            candidate = candidate[7:]
        elif candidate.startswith("```"):
            candidate = candidate[3:]
        if candidate.endswith("```"):
            candidate = candidate[:-3]
        candidate = candidate.strip()
    else:
        raise SecListingIdentityError(
            "SEC current identity access method is unsupported"
        )
    try:
        payload = json.loads(candidate, strict=False)
    except json.JSONDecodeError as exc:
        raise SecListingIdentityError(
            "SEC current identity response is not valid JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise SecListingIdentityError(
            "SEC current identity response is not a JSON object"
        )
    if not isinstance(payload.get("fields"), list) or not isinstance(
        payload.get("data"), list
    ):
        raise SecListingIdentityError(
            "SEC current identity response has no tabular payload"
        )
    return payload


def empty_sec_listing_facts() -> pd.DataFrame:
    """Return a schema-valid empty frame for a fail-closed current subset."""

    return pd.DataFrame(columns=_NORMALIZED_FACT_COLUMNS)


def build_current_sec_universe(
    payload: Mapping[str, Any],
    *,
    retrieved_at: str | pd.Timestamp,
    source_url: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build current listed-security identity directly from the SEC endpoint."""

    if not _official_current_identity_url(source_url):
        raise SecListingIdentityError(
            "current identity source is not the official SEC endpoint"
        )
    retrieved = _utc_timestamp(retrieved_at)
    if pd.isna(retrieved):
        raise SecListingIdentityError("retrieved_at is not a valid timestamp")
    if not isinstance(payload, Mapping):
        raise SecListingIdentityError("SEC current identity payload is not an object")
    fields = payload.get("fields")
    data = payload.get("data")
    if not isinstance(fields, list) or not isinstance(data, list):
        raise SecListingIdentityError("SEC current identity payload has no table")
    field_names = [str(field).strip().lower() for field in fields]
    singular_schema = {"cik", "name", "ticker", "exchange"}
    array_schema = {"cik", "name", "tickers", "exchanges"}
    if singular_schema.issubset(field_names):
        schema_mode = "one_security_per_row"
    elif array_schema.issubset(field_names):
        schema_mode = "issuer_arrays"
    else:
        raise SecListingIdentityError(
            "SEC current identity payload has an invalid schema"
        )

    rows: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    for raw in data:
        if not isinstance(raw, list) or len(raw) != len(field_names):
            raise SecListingIdentityError(
                "SEC current identity payload contains a malformed row"
        )
        record = dict(zip(field_names, raw, strict=True))
        cik = _normalize_cik(record.get("cik"))
        if schema_mode == "one_security_per_row":
            tickers = [record.get("ticker")]
            exchanges = [record.get("exchange")]
        else:
            tickers = record.get("tickers")
            exchanges = record.get("exchanges")
        if isinstance(tickers, str):
            tickers = [tickers]
        if isinstance(exchanges, str):
            exchanges = [exchanges]
        if (
            not cik
            or not isinstance(tickers, list)
            or not isinstance(exchanges, list)
        ):
            raise SecListingIdentityError(
                "SEC current identity payload contains an invalid issuer identity"
            )
        for index, ticker_value in enumerate(tickers):
            ticker = _clean_text(ticker_value).upper()
            exchange = (
                _clean_text(exchanges[index]) if index < len(exchanges) else ""
            )
            exchange_family = normalize_exchange_family(exchange)
            ticker_key = _identity_key(ticker)
            if not ticker_key:
                rejections.append(
                    {
                        "cik": cik,
                        "ticker": ticker,
                        "exchange": exchange,
                        "reason_if_rejected": "invalid_current_ticker",
                    }
                )
                continue
            if exchange_family not in {
                "NASDAQ",
                "NYSE",
                "NYSE_AMERICAN",
                "NYSE_ARCA",
                "CBOE_BZX",
            }:
                rejections.append(
                    {
                        "cik": cik,
                        "ticker": ticker,
                        "exchange": exchange,
                        "reason_if_rejected": "unsupported_current_exchange",
                    }
                )
                continue
            rows.append(
                {
                    "security_id": f"US-SEC-{cik}-{ticker_key}",
                    "ticker": ticker,
                    "cik": cik,
                    "exchange_family": exchange_family,
                    "identity_available_at": retrieved.isoformat(),
                    "identity_source_url": source_url,
                }
            )

    universe = pd.DataFrame(rows)
    if universe.empty:
        raise SecListingIdentityError(
            "SEC current identity payload produced no supported securities"
        )
    conflicts = universe.groupby("security_id")["exchange_family"].nunique()
    if conflicts.gt(1).any():
        raise SecListingIdentityError(
            "SEC current identity payload contains conflicting exchanges"
        )
    universe = universe.drop_duplicates(
        ["security_id", "ticker", "cik", "exchange_family"]
    ).copy()
    class_counts = universe.groupby("cik")["security_id"].transform("nunique")
    universe["issuer_share_class_count"] = class_counts.astype(int)
    universe = universe.loc[:, _CURRENT_UNIVERSE_COLUMNS].sort_values(
        ["security_id", "ticker"]
    ).reset_index(drop=True)
    rejected = pd.DataFrame(
        rejections,
        columns=_CURRENT_UNIVERSE_REJECTION_COLUMNS,
    )
    if not rejected.empty:
        rejected = rejected.drop_duplicates().sort_values(
            ["cik", "ticker", "exchange", "reason_if_rejected"]
        ).reset_index(drop=True)
    return universe, rejected


def _sec_archive_source_reason(
    value: Any,
    *,
    cik: str,
    accession: str,
) -> str:
    parsed = urlparse(_clean_text(value))
    if not (
        parsed.scheme.lower() == "https"
        and parsed.netloc.lower() == "www.sec.gov"
        and parsed.path.lower().startswith("/archives/edgar/")
    ):
        return "unofficial_sec_archive_source"
    expected = f"/archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"
    if not parsed.path.lower().startswith(expected.lower()):
        return "sec_archive_identity_path_mismatch"
    return ""


def _official_current_identity_url(value: Any) -> bool:
    parsed = urlparse(_clean_text(value))
    return (
        parsed.scheme.lower() == "https"
        and parsed.netloc.lower() == "www.sec.gov"
        and parsed.path == "/files/company_tickers_exchange.json"
        and not parsed.query
        and not parsed.fragment
    )


def _official_notes_dataset_url(value: Any) -> bool:
    parsed = urlparse(_clean_text(value))
    return (
        parsed.scheme.lower() == "https"
        and parsed.netloc.lower() == "www.sec.gov"
        and re.fullmatch(
            r"/files/dera/data/financial-statement-notes-data-sets/"
            r"[0-9]{4}(?:q[1-4]|_(?:0[1-9]|1[0-2]))_notes\.zip",
            parsed.path.lower(),
        )
        is not None
        and not parsed.query
        and not parsed.fragment
    )


def _sec_accepted_timestamp(value: Any) -> pd.Timestamp:
    text = _clean_text(value)
    if re.fullmatch(r"[0-9]{14}", text):
        timestamp = pd.to_datetime(
            text,
            format="%Y%m%d%H%M%S",
            errors="coerce",
            utc=True,
        )
        return pd.NaT if pd.isna(timestamp) else pd.Timestamp(timestamp)
    return _utc_timestamp(value)


def normalize_sec_notes_listing_facts(
    submissions: pd.DataFrame,
    text_facts: pd.DataFrame,
    *,
    dataset_source_url: str,
    dataset_sha256: str,
) -> pd.DataFrame:
    """Normalize SEC Notes SUB/TXT rows into exact filing-context facts."""

    _require_columns(
        submissions,
        _NOTES_SUB_REQUIRED_COLUMNS,
        "SEC Notes SUB",
    )
    _require_columns(
        text_facts,
        _NOTES_TXT_REQUIRED_COLUMNS,
        "SEC Notes TXT",
    )
    source_url = _clean_text(dataset_source_url)
    source_hash = _clean_text(dataset_sha256).lower()
    if (
        not _official_notes_dataset_url(source_url)
        or re.fullmatch(r"[0-9a-f]{64}", source_hash) is None
    ):
        raise SecListingIdentityError(
            "SEC Notes dataset source URL or SHA-256 is invalid"
        )

    facts = text_facts.copy()
    facts["_tag"] = facts["tag"].map(_clean_text)
    facts["_version"] = facts["version"].map(_clean_text)
    facts = facts.loc[
        facts["_tag"].isin(LISTING_CONCEPTS)
        & facts["_version"].str.fullmatch(r"dei/[0-9]{4}(?:q[1-4])?")
    ].copy()
    if facts.empty:
        return pd.DataFrame(columns=_NORMALIZED_FACT_COLUMNS)
    facts["_adsh"] = facts["adsh"].map(_clean_text)
    facts["_iprx"] = pd.to_numeric(facts["iprx"], errors="coerce")
    if facts["_iprx"].isna().any() or facts["_iprx"].lt(1).any():
        raise SecListingIdentityError(
            "SEC Notes TXT contains an invalid iprx value"
        )
    referenced = set(facts["_adsh"])

    filing_rows = submissions.copy()
    filing_rows["_adsh"] = filing_rows["adsh"].map(_clean_text)
    filing_rows = filing_rows.loc[filing_rows["_adsh"].isin(referenced)].copy()
    counts = filing_rows["_adsh"].value_counts(dropna=False)
    if set(counts.index) != referenced or not counts.eq(1).all():
        raise SecListingIdentityError(
            "SEC Notes SUB does not contain one filing row per listing accession"
        )
    by_accession = filing_rows.set_index("_adsh", drop=False)

    filing_metadata: dict[str, dict[str, Any]] = {}
    for accession, filing in by_accession.iterrows():
        if re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession) is None:
            raise SecListingIdentityError("SEC Notes contains an invalid accession")
        cik = _normalize_cik(filing["cik"])
        form = _clean_text(filing["form"]).upper()
        accepted_at = _sec_accepted_timestamp(filing["accepted"])
        instance = _clean_text(filing["instance"])
        if not cik:
            raise SecListingIdentityError("SEC Notes contains an invalid CIK")
        if form not in PERIODIC_FORMS:
            raise SecListingIdentityError(
                "SEC Notes listing accession is not an unamended periodic form"
            )
        if pd.isna(accepted_at):
            raise SecListingIdentityError(
                "SEC Notes listing accession has an invalid accepted timestamp"
            )
        if (
            re.fullmatch(r"[A-Za-z0-9._-]+", instance) is None
            or not instance.lower().endswith((".htm", ".html", ".xml"))
        ):
            raise SecListingIdentityError("SEC Notes contains an unsafe SEC filing instance")
        filing_metadata[accession] = {
            "cik": cik,
            "accepted_at": accepted_at,
            "form": form,
            "source_url": (
                "https://www.sec.gov/Archives/edgar/data/"
                f"{int(cik)}/{accession.replace('-', '')}/{instance}"
            ),
        }

    rows: list[dict[str, Any]] = []
    for fact in facts.to_dict(orient="records"):
        accession = str(fact["_adsh"])
        filing = filing_metadata[accession]
        rows.append(
            {
                "cik": filing["cik"],
                "accession": accession,
                "accepted_at": filing["accepted_at"],
                "form": filing["form"],
                "context_id": _clean_text(fact["context"]),
                "concept": f"dei:{fact['_tag']}",
                "value": _clean_text(fact["value"]),
                "source_url": filing["source_url"],
                "transport_source_url": source_url,
                "transport_sha256": source_hash,
                "transport_access_method": "sec_official_notes_direct_fair_access",
                "taxonomy_version": str(fact["_version"]),
                "iprx": int(fact["_iprx"]),
            }
        )
    return pd.DataFrame(rows, columns=_NORMALIZED_FACT_COLUMNS).sort_values(
        ["cik", "accepted_at", "accession", "context_id", "concept", "iprx"]
    ).reset_index(drop=True)


def _empty_observations() -> pd.DataFrame:
    return pd.DataFrame(columns=_OBSERVATION_COLUMNS)


def _empty_observation_rejections() -> pd.DataFrame:
    return pd.DataFrame(columns=_OBSERVATION_REJECTION_COLUMNS)


def extract_sec_listing_observations(
    filing_facts: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Extract one CIK/class/ticker/exchange observation per filing context."""

    _require_columns(filing_facts, _FACT_REQUIRED_COLUMNS, "SEC listing facts")
    formation = _utc_timestamp(formation_at)
    if pd.isna(formation):
        raise SecListingIdentityError("formation_at is not a valid timestamp")

    facts = filing_facts.copy()
    facts["_concept"] = (
        facts["concept"].fillna("").astype(str).str.rsplit(":", n=1).str[-1]
    )
    facts = facts.loc[facts["_concept"].isin(LISTING_CONCEPTS)].copy()
    if facts.empty:
        return _empty_observations(), _empty_observation_rejections()

    group_columns = [
        "cik",
        "accession",
        "accepted_at",
        "form",
        "context_id",
        "source_url",
    ]
    observations: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []

    for raw_key, group in facts.groupby(group_columns, dropna=False, sort=True):
        raw = dict(zip(group_columns, raw_key, strict=True))
        cik = _normalize_cik(raw["cik"])
        accession = _clean_text(raw["accession"])
        accepted_at = _utc_timestamp(raw["accepted_at"])
        form = _clean_text(raw["form"]).upper()
        context_id = _clean_text(raw["context_id"])
        source_url = _clean_text(raw["source_url"])
        rejection = {
            "cik": cik or _clean_text(raw["cik"]),
            "accession": accession,
            "accepted_at": accepted_at,
            "form": form,
            "context_id": context_id,
            "source_url": source_url,
            "reason_if_rejected": "",
        }

        if not cik:
            rejection["reason_if_rejected"] = "invalid_cik"
        elif not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession):
            rejection["reason_if_rejected"] = "invalid_accession"
        elif pd.isna(accepted_at):
            rejection["reason_if_rejected"] = "invalid_accepted_at"
        elif accepted_at > formation:
            rejection["reason_if_rejected"] = "accepted_after_formation"
        elif form not in PERIODIC_FORMS:
            rejection["reason_if_rejected"] = (
                "unsupported_or_amended_periodic_form"
            )
        elif not context_id:
            rejection["reason_if_rejected"] = "missing_context_id"
        else:
            rejection["reason_if_rejected"] = _sec_archive_source_reason(
                source_url,
                cik=cik,
                accession=accession,
            )

        values: dict[str, str] = {}
        if not rejection["reason_if_rejected"]:
            for concept in LISTING_CONCEPTS:
                concept_values = (
                    group.loc[group["_concept"].eq(concept), "value"]
                    .fillna("")
                    .astype(str)
                    .str.strip()
                )
                if concept_values.empty or concept_values.eq("").all():
                    rejection["reason_if_rejected"] = (
                        f"missing_listing_fact:{concept}"
                    )
                    break
                if len(concept_values) != 1 or concept_values.nunique() != 1:
                    rejection["reason_if_rejected"] = (
                        f"conflicting_or_duplicate_listing_fact:{concept}"
                    )
                    break
                values[concept] = str(concept_values.iloc[0])

        ticker_key = _identity_key(values.get("TradingSymbol", ""))
        exchange_family = normalize_exchange_family(
            values.get("SecurityExchangeName", "")
        )
        security_title_key = _identity_key(values.get("Security12bTitle", ""))
        if not rejection["reason_if_rejected"] and not ticker_key:
            rejection["reason_if_rejected"] = "invalid_trading_symbol"
        elif not rejection["reason_if_rejected"] and not exchange_family:
            rejection["reason_if_rejected"] = "unsupported_exchange"
        elif not rejection["reason_if_rejected"] and not security_title_key:
            rejection["reason_if_rejected"] = "invalid_security_title"

        if rejection["reason_if_rejected"]:
            rejections.append(rejection)
            continue
        observations.append(
            {
                "cik": cik,
                "accession": accession,
                "accepted_at": accepted_at,
                "form": form,
                "context_id": context_id,
                "trading_symbol": values["TradingSymbol"].strip().upper(),
                "ticker_key": ticker_key,
                "exchange_name": values["SecurityExchangeName"].strip(),
                "exchange_family": exchange_family,
                "security_title": values["Security12bTitle"].strip(),
                "security_title_key": security_title_key,
                "source_url": source_url,
                "identity_quality": (
                    "sec_filing_context_cik_class_ticker_exchange_observation"
                ),
            }
        )

    accepted_frame = pd.DataFrame(observations, columns=_OBSERVATION_COLUMNS)
    rejected_frame = pd.DataFrame(
        rejections,
        columns=_OBSERVATION_REJECTION_COLUMNS,
    )
    if not accepted_frame.empty:
        accepted_frame = accepted_frame.sort_values(
            ["cik", "accepted_at", "accession", "context_id"]
        ).reset_index(drop=True)
    if not rejected_frame.empty:
        rejected_frame = rejected_frame.sort_values(
            ["cik", "accepted_at", "accession", "context_id"],
            na_position="last",
        ).reset_index(drop=True)
    return accepted_frame, rejected_frame


def _interval_rejection(
    *,
    security_id: str,
    cik: str,
    reason: str,
    observation: pd.Series | None = None,
) -> dict[str, Any]:
    return {
        "security_id": security_id,
        "cik": cik,
        "accession": "" if observation is None else str(observation["accession"]),
        "accepted_at": pd.NaT if observation is None else observation["accepted_at"],
        "reason_if_rejected": reason,
    }


def _interval_row(
    *,
    security_id: str,
    cik: str,
    ticker: str,
    exchange_family: str,
    start: pd.Series,
    valid_through: Any,
    end_evidence: str,
    end_available_at: Any,
    end_source_url: str,
) -> dict[str, Any]:
    return {
        "security_id": security_id,
        "cik": cik,
        "ticker": ticker,
        "ticker_key": _identity_key(ticker),
        "exchange_family": exchange_family,
        "security_title": str(start["security_title"]),
        "security_title_key": str(start["security_title_key"]),
        "valid_from": start["accepted_at"].date(),
        "valid_through": valid_through,
        "start_accession": str(start["accession"]),
        "end_evidence": end_evidence,
        "start_available_at": start["accepted_at"],
        "end_available_at": end_available_at,
        "start_source_url": str(start["source_url"]),
        "end_source_url": end_source_url,
        "identity_quality": "sec_filing_endpoints_corroborated_non_permno",
        "historical_ticker_interval_verified": False,
        "strict_score_eligible": False,
    }


def build_sec_listing_intervals(
    observations: pd.DataFrame,
    current_universe: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    maximum_gap_days: int = MAX_CORROBORATED_GAP_DAYS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build conservative endpoint-corroborated intervals for current securities."""

    _require_columns(
        observations,
        frozenset(_OBSERVATION_COLUMNS),
        "SEC listing observations",
    )
    _require_columns(
        current_universe,
        _UNIVERSE_REQUIRED_COLUMNS,
        "current security universe",
    )
    formation = _utc_timestamp(formation_at)
    if pd.isna(formation):
        raise SecListingIdentityError("formation_at is not a valid timestamp")
    if maximum_gap_days <= 0:
        raise SecListingIdentityError("maximum_gap_days must be positive")
    if current_universe["security_id"].astype(str).duplicated(keep=False).any():
        raise SecListingIdentityError("current universe has duplicate security_id")

    obs = observations.copy()
    obs["cik"] = obs["cik"].map(_normalize_cik)
    obs["accepted_at"] = obs["accepted_at"].map(_utc_timestamp)
    obs = obs.loc[
        obs["cik"].ne("")
        & obs["accepted_at"].notna()
        & obs["accepted_at"].le(formation)
    ].copy()
    intervals: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []

    for current in current_universe.sort_values("security_id").to_dict(
        orient="records"
    ):
        security_id = _clean_text(current["security_id"])
        cik = _normalize_cik(current["cik"])
        ticker = _clean_text(current["ticker"]).upper()
        ticker_key = _identity_key(ticker)
        exchange_family = normalize_exchange_family(current["exchange_family"])
        identity_available_at = _utc_timestamp(current["identity_available_at"])
        identity_source_url = _clean_text(current["identity_source_url"])
        share_class_count = pd.to_numeric(
            current["issuer_share_class_count"], errors="coerce"
        )
        if not security_id or not cik or not ticker_key or not exchange_family:
            rejections.append(
                _interval_rejection(
                    security_id=security_id,
                    cik=cik,
                    reason="invalid_current_security_identity",
                )
            )
            continue
        if pd.isna(identity_available_at) or identity_available_at > formation:
            rejections.append(
                _interval_rejection(
                    security_id=security_id,
                    cik=cik,
                    reason="current_identity_available_after_formation_or_invalid",
                )
            )
            continue
        if not _official_current_identity_url(identity_source_url):
            rejections.append(
                _interval_rejection(
                    security_id=security_id,
                    cik=cik,
                    reason="current_identity_source_is_not_official_sec",
                )
            )
            continue
        if pd.isna(share_class_count) or float(share_class_count) != 1.0:
            rejections.append(
                _interval_rejection(
                    security_id=security_id,
                    cik=cik,
                    reason="current_issuer_has_multiple_share_classes",
                )
            )
            continue

        issuer_obs = obs.loc[
            obs["cik"].eq(cik)
            & obs["accepted_at"].le(identity_available_at)
        ].sort_values(["accepted_at", "accession", "context_id"])
        if issuer_obs.empty:
            rejections.append(
                _interval_rejection(
                    security_id=security_id,
                    cik=cik,
                    reason="no_sec_listing_observation",
                )
            )
            continue

        ambiguous_accessions = set(
            issuer_obs.loc[
                issuer_obs.groupby("accession")["context_id"].transform("nunique").gt(1),
                "accession",
            ]
        )
        for accession in sorted(ambiguous_accessions):
            first = issuer_obs.loc[issuer_obs["accession"].eq(accession)].iloc[0]
            rejections.append(
                _interval_rejection(
                    security_id=security_id,
                    cik=cik,
                    observation=first,
                    reason="ambiguous_multiple_listings_in_accession",
                )
            )
        issuer_obs = issuer_obs.loc[
            ~issuer_obs["accession"].isin(ambiguous_accessions)
        ].reset_index(drop=True)
        issuer_obs["_matches_current"] = (
            issuer_obs["ticker_key"].eq(ticker_key)
            & issuer_obs["exchange_family"].eq(exchange_family)
        )
        for _, mismatch in issuer_obs.loc[~issuer_obs["_matches_current"]].iterrows():
            rejections.append(
                _interval_rejection(
                    security_id=security_id,
                    cik=cik,
                    observation=mismatch,
                    reason="listing_identity_disagrees_with_current_security",
                )
            )

        matching = issuer_obs.loc[issuer_obs["_matches_current"]].reset_index(
            drop=True
        )
        for index in range(len(matching) - 1):
            start = matching.iloc[index]
            end = matching.iloc[index + 1]
            gap_days = (end["accepted_at"].date() - start["accepted_at"].date()).days
            intervening_change = issuer_obs.loc[
                issuer_obs["accepted_at"].gt(start["accepted_at"])
                & issuer_obs["accepted_at"].lt(end["accepted_at"])
                & ~issuer_obs["_matches_current"]
            ]
            if gap_days > maximum_gap_days:
                rejections.append(
                    _interval_rejection(
                        security_id=security_id,
                        cik=cik,
                        observation=end,
                        reason=f"filing_gap_exceeds_{maximum_gap_days}_days",
                    )
                )
                continue
            if not intervening_change.empty:
                continue
            if start["security_title_key"] != end["security_title_key"]:
                rejections.append(
                    _interval_rejection(
                        security_id=security_id,
                        cik=cik,
                        observation=end,
                        reason="security_title_changed_between_filings",
                    )
                )
                continue
            intervals.append(
                _interval_row(
                    security_id=security_id,
                    cik=cik,
                    ticker=ticker,
                    exchange_family=exchange_family,
                    start=start,
                    valid_through=end["accepted_at"].date() - timedelta(days=1),
                    end_evidence=str(end["accession"]),
                    end_available_at=end["accepted_at"],
                    end_source_url=str(end["source_url"]),
                )
            )

        if not matching.empty:
            latest = matching.iloc[-1]
            later_mismatch = issuer_obs.loc[
                issuer_obs["accepted_at"].gt(latest["accepted_at"])
                & ~issuer_obs["_matches_current"]
            ]
            final_gap = (
                identity_available_at.date() - latest["accepted_at"].date()
            ).days
            if later_mismatch.empty and final_gap <= maximum_gap_days:
                intervals.append(
                    _interval_row(
                        security_id=security_id,
                        cik=cik,
                        ticker=ticker,
                        exchange_family=exchange_family,
                        start=latest,
                        valid_through=identity_available_at.date(),
                        end_evidence="current_security_master_endpoint",
                        end_available_at=identity_available_at,
                        end_source_url=identity_source_url,
                    )
                )
            elif later_mismatch.empty and final_gap > maximum_gap_days:
                rejections.append(
                    _interval_rejection(
                        security_id=security_id,
                        cik=cik,
                        observation=latest,
                        reason=f"filing_gap_exceeds_{maximum_gap_days}_days",
                    )
                )

    interval_frame = pd.DataFrame(intervals, columns=_INTERVAL_COLUMNS)
    rejection_frame = pd.DataFrame(
        rejections,
        columns=_INTERVAL_REJECTION_COLUMNS,
    )
    if not interval_frame.empty:
        interval_frame = interval_frame.sort_values(
            ["security_id", "valid_from", "valid_through"]
        ).reset_index(drop=True)
        duplicated_dates = [
            any(
                group.iloc[index]["valid_from"]
                <= group.iloc[index - 1]["valid_through"]
                for index in range(1, len(group))
            )
            for _, group in interval_frame.groupby("security_id", sort=False)
        ]
        if any(duplicated_dates):
            raise SecListingIdentityError(
                "SEC corroborated intervals overlap for one security"
            )
    if not rejection_frame.empty:
        rejection_frame = rejection_frame.drop_duplicates().sort_values(
            ["security_id", "accepted_at", "accession", "reason_if_rejected"],
            na_position="last",
        ).reset_index(drop=True)
    return interval_frame, rejection_frame


def _month_start(value: Any) -> pd.Timestamp:
    timestamp = _utc_timestamp(value)
    if pd.isna(timestamp):
        return pd.NaT
    return timestamp.tz_localize(None).to_period("M").to_timestamp()


def _covers_month_starts(
    intervals: pd.DataFrame,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> bool:
    expected = pd.date_range(start=start, end=end, freq="MS")
    if len(expected) != 13:
        return False
    for month in expected:
        session_date = month.date()
        covering = intervals.loc[
            intervals["valid_from"].le(session_date)
            & intervals["valid_through"].ge(session_date)
        ]
        if len(covering) != 1:
            return False
    return True


def calculate_sec_exch_switch_current(
    observations: pd.DataFrame,
    intervals: pd.DataFrame,
    current_universe: pd.DataFrame,
    *,
    formation_at: str | pd.Timestamp,
    retrieved_at: str | pd.Timestamp,
) -> pd.DataFrame:
    """Calculate a causal, non-strict current reconstruction of ExchSwitch.

    A positive value requires a same-class SEC filing transition from NASDAQ
    or NYSE American into an eligible current exchange.  A zero for current
    NYSE/NYSE American securities requires all 13 relevant month starts to be
    covered by non-overlapping SEC-corroborated intervals.  Current NASDAQ is
    zero directly because the pinned OpenAP condition can only be true when
    the current exchange is NYSE or AMEX.
    """

    _require_columns(
        observations,
        frozenset(_OBSERVATION_COLUMNS),
        "SEC listing observations",
    )
    _require_columns(
        intervals,
        frozenset(_INTERVAL_COLUMNS),
        "SEC listing intervals",
    )
    _require_columns(
        current_universe,
        _UNIVERSE_REQUIRED_COLUMNS,
        "current security universe",
    )
    formation = _utc_timestamp(formation_at)
    retrieved = _utc_timestamp(retrieved_at)
    if pd.isna(formation) or pd.isna(retrieved):
        raise SecListingIdentityError(
            "ExchSwitch formation_at and retrieved_at must be valid timestamps"
        )
    if current_universe["security_id"].astype(str).duplicated(keep=False).any():
        raise SecListingIdentityError("current universe has duplicate security_id")

    formation_month = _month_start(formation)
    lookback_start = formation_month - pd.DateOffset(months=12)
    obs = observations.copy()
    obs["cik"] = obs["cik"].map(_normalize_cik)
    obs["accepted_at"] = obs["accepted_at"].map(_utc_timestamp)
    obs = obs.loc[
        obs["cik"].ne("")
        & obs["accepted_at"].notna()
        & obs["accepted_at"].le(formation)
    ].copy()
    interval_frame = intervals.copy()
    interval_frame["cik"] = interval_frame["cik"].map(_normalize_cik)
    interval_frame["valid_from"] = pd.to_datetime(
        interval_frame["valid_from"], errors="coerce"
    ).dt.date
    interval_frame["valid_through"] = pd.to_datetime(
        interval_frame["valid_through"], errors="coerce"
    ).dt.date

    rows: list[dict[str, Any]] = []
    for current in current_universe.sort_values("security_id").to_dict(
        orient="records"
    ):
        security_id = _clean_text(current["security_id"])
        ticker = _clean_text(current["ticker"]).upper()
        ticker_key = _identity_key(ticker)
        cik = _normalize_cik(current["cik"])
        current_exchange = normalize_exchange_family(current["exchange_family"])
        identity_available = _utc_timestamp(current["identity_available_at"])
        identity_source_url = _clean_text(current["identity_source_url"])
        share_class_count = pd.to_numeric(
            current["issuer_share_class_count"], errors="coerce"
        )
        value: float | None = None
        reason = ""
        transition_from = ""
        transition_detected = pd.NaT
        filed_at = pd.NaT
        available_at = identity_available
        source_urls = [identity_source_url] if identity_source_url else []
        observation_count = 0

        if not security_id or not cik or not ticker_key or not current_exchange:
            reason = "invalid_current_security_identity"
        elif pd.isna(identity_available) or identity_available > formation:
            reason = "current_identity_available_after_formation_or_invalid"
        elif not _official_current_identity_url(identity_source_url):
            reason = "current_identity_source_is_not_official_sec"
        elif pd.isna(share_class_count) or float(share_class_count) != 1.0:
            reason = "current_issuer_has_multiple_share_classes"
        elif current_exchange == "NASDAQ":
            value = 0.0
        elif current_exchange not in {"NYSE", "NYSE_AMERICAN"}:
            reason = "current_exchange_has_no_exact_openap_exchcd_mapping"
        else:
            issuer = obs.loc[
                obs["cik"].eq(cik)
                & obs["ticker_key"].eq(ticker_key)
                & obs["accepted_at"].le(identity_available)
            ].sort_values(["accepted_at", "accession", "context_id"])
            observation_count = len(issuer)
            current_rows = issuer.loc[
                issuer["exchange_family"].eq(current_exchange)
            ]
            old_exchanges = (
                {"NASDAQ", "NYSE_AMERICAN"}
                if current_exchange == "NYSE"
                else {"NASDAQ"}
            )
            transition: tuple[pd.Series, pd.Series] | None = None
            for _, old in issuer.loc[
                issuer["exchange_family"].isin(old_exchanges)
                & issuer["accepted_at"].map(_month_start).ge(lookback_start)
                & issuer["accepted_at"].map(_month_start).lt(formation_month)
            ].sort_values("accepted_at", ascending=False).iterrows():
                later_current = current_rows.loc[
                    current_rows["accepted_at"].gt(old["accepted_at"])
                    & current_rows["security_title_key"].eq(
                        old["security_title_key"]
                    )
                ].sort_values("accepted_at")
                if later_current.empty:
                    continue
                detected = later_current.iloc[0]
                gap_days = (
                    detected["accepted_at"].date()
                    - old["accepted_at"].date()
                ).days
                later_conflict = issuer.loc[
                    issuer["accepted_at"].gt(detected["accepted_at"])
                    & (
                        issuer["exchange_family"].ne(current_exchange)
                        | issuer["security_title_key"].ne(
                            detected["security_title_key"]
                        )
                    )
                ]
                if gap_days <= MAX_CORROBORATED_GAP_DAYS and later_conflict.empty:
                    transition = (old, detected)
                    break
            if transition is not None:
                old, detected = transition
                value = 1.0
                transition_from = str(old["exchange_family"])
                transition_detected = detected["accepted_at"]
                filed_at = detected["accepted_at"]
                available_at = max(identity_available, detected["accepted_at"])
                source_urls.extend(
                    [str(old["source_url"]), str(detected["source_url"])]
                )
            else:
                exact_intervals = interval_frame.loc[
                    interval_frame["security_id"].eq(security_id)
                    & interval_frame["cik"].eq(cik)
                    & interval_frame["ticker_key"].eq(ticker_key)
                    & interval_frame["exchange_family"].eq(current_exchange)
                ]
                if _covers_month_starts(
                    exact_intervals,
                    start=lookback_start,
                    end=formation_month,
                ):
                    value = 0.0
                    source_urls.extend(
                        exact_intervals["start_source_url"].astype(str).tolist()
                    )
                else:
                    reason = "exchange_history_not_corroborated_12_months"

        finite = value is not None
        rows.append(
            {
                "security_id": security_id,
                "ticker": ticker,
                "cik": cik,
                "signal": "ExchSwitch",
                "formation_at": formation.isoformat(),
                "period_end": formation_month.date().isoformat(),
                "filed_at": (
                    "" if pd.isna(filed_at) else filed_at.isoformat()
                ),
                "available_at": (
                    "" if pd.isna(available_at) else available_at.isoformat()
                ),
                "retrieved_at": retrieved.isoformat(),
                "value": value if finite else float("nan"),
                "transition_from": transition_from,
                "transition_to": current_exchange if transition_from else "",
                "transition_detected_at": (
                    ""
                    if pd.isna(transition_detected)
                    else transition_detected.isoformat()
                ),
                "source_id": "sec_edgar_notes|sec_company_tickers_exchange",
                "source_url": "|".join(dict.fromkeys(filter(None, source_urls))),
                "formula_id": "openap_exchswitch_current_exchange_lag_1_12",
                "formula_sha256": EXCH_SWITCH_FORMULA_SHA256,
                "observation_count": int(observation_count),
                "fidelity_class": "reconstructed" if finite else "unavailable",
                "current_usable": bool(finite),
                "reason_if_missing": "" if finite else reason,
                "caveat": (
                    "SEC filing acceptance dates corroborate exchange snapshots, "
                    "not exact CRSP monthly switch dates or PERMNO history"
                ),
                "strict_score_eligible": False,
            }
        )
    return pd.DataFrame(rows, columns=_EXCH_SWITCH_OUTPUT_COLUMNS).reset_index(
        drop=True
    )


def filter_market_bars_by_sec_identity(
    bars: pd.DataFrame,
    intervals: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Keep bars only when exact current identity fits one SEC interval."""

    bar_required = frozenset(
        {"security_id", "cik", "ticker", "exchange_family", "date"}
    )
    _require_columns(bars, bar_required, "market bars")
    _require_columns(intervals, frozenset(_INTERVAL_COLUMNS), "SEC intervals")
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for raw in bars.to_dict(orient="records"):
        row = dict(raw)
        security_id = str(row.get("security_id") or "").strip()
        cik = _normalize_cik(row.get("cik"))
        ticker_key = _identity_key(row.get("ticker"))
        exchange_family = normalize_exchange_family(row.get("exchange_family"))
        date = pd.to_datetime(row.get("date"), errors="coerce")
        candidates = intervals.loc[intervals["security_id"].eq(security_id)]
        exact_identity = candidates.loc[
            candidates["cik"].eq(cik)
            & candidates["ticker_key"].eq(ticker_key)
            & candidates["exchange_family"].eq(exchange_family)
        ]
        if candidates.empty or pd.isna(date):
            row["reason_if_rejected"] = (
                "outside_sec_corroborated_identity_interval"
            )
            rejected.append(row)
            continue
        if exact_identity.empty:
            row["reason_if_rejected"] = (
                "bar_identity_disagrees_with_sec_interval"
            )
            rejected.append(row)
            continue
        session_date = pd.Timestamp(date).date()
        covering = exact_identity.loc[
            exact_identity["valid_from"].le(session_date)
            & exact_identity["valid_through"].ge(session_date)
        ]
        if covering.empty:
            row["reason_if_rejected"] = (
                "outside_sec_corroborated_identity_interval"
            )
            rejected.append(row)
            continue
        if len(covering) != 1:
            row["reason_if_rejected"] = (
                "ambiguous_overlapping_sec_identity_intervals"
            )
            rejected.append(row)
            continue
        interval = covering.iloc[0]
        row["date"] = session_date
        row["historical_identity_corroborated"] = True
        row["identity_quality"] = interval["identity_quality"]
        row["identity_start_accession"] = interval["start_accession"]
        row["identity_end_evidence"] = interval["end_evidence"]
        row["historical_ticker_interval_verified"] = False
        row["strict_score_eligible"] = False
        accepted.append(row)

    accepted_frame = pd.DataFrame(accepted)
    rejected_frame = pd.DataFrame(rejected)
    return accepted_frame.reset_index(drop=True), rejected_frame.reset_index(
        drop=True
    )


__all__ = [
    "EXCH_SWITCH_FORMULA_SHA256",
    "LISTING_CONCEPTS",
    "MAX_CORROBORATED_GAP_DAYS",
    "PERIODIC_FORMS",
    "SecListingIdentityError",
    "build_current_sec_universe",
    "build_sec_listing_intervals",
    "calculate_sec_exch_switch_current",
    "empty_sec_listing_facts",
    "extract_sec_listing_observations",
    "filter_market_bars_by_sec_identity",
    "normalize_sec_notes_listing_facts",
    "normalize_exchange_family",
    "parse_current_sec_identity_response",
]
