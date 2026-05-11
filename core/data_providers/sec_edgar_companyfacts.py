"""SEC EDGAR company facts provider (R156 FUNDAMENTALS).

Official U.S. SEC EDGAR provider for company facts (XBRL concepts),
submissions metadata and ticker / CIK mapping.

The provider exposes three fetch surfaces:

* :meth:`SECEdgarClient.fetch_ticker_cik_map` -- the public ticker/CIK
  table at ``https://www.sec.gov/files/company_tickers.json``.
* :meth:`SECEdgarClient.fetch_submissions` -- the per-company filing
  history at ``https://data.sec.gov/submissions/CIK{cik:010d}.json``.
* :meth:`SECEdgarClient.fetch_companyfacts` -- the per-company XBRL
  facts at ``https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json``.

Plus a bulk path for the nightly archive
(:meth:`SECEdgarClient.ingest_companyfacts_zip`) that yields one
:class:`CompanyFactsBundle` per CIK in the ZIP without holding the
whole archive in memory.

Point-in-time discipline
------------------------

Every :class:`XBRLFact` carries ``filing_date_iso`` AND
``accepted_iso``. The strict PIT timestamp is ``accepted_iso`` (when
SEC stamped the filing as accepted -- the first moment a strategy
could have known the value). :func:`assert_pit_safe` and
:func:`filter_pit_safe` use ``accepted_iso`` to refuse / filter facts
whose acceptance is later than the decision timestamp. That matches
the spec line "strategies cannot use a fact before its filing /
accepted / available timestamp" (R156 line 3295-3296).

Auth
----

SEC's public API requires a polite ``User-Agent`` header that includes
an operator email. The constructor requires either an explicit
``user_agent=`` argument or the ``AU_SEC_EDGAR_USER_AGENT`` env var;
otherwise :class:`SECEdgarClient` raises :class:`RuntimeError`. Tests
pass ``user_agent="Aurora Test test@example.com"`` (or set the env
var). Tests must also pass an ``http_get`` callable so no live network
hit happens.
"""
from __future__ import annotations

import json
import logging
import os
import warnings
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Optional, Tuple

import pandas as pd

from . import ProviderDescriptor, ProviderRole
from ._free_bulk_common import (
    FreeBulkLineage,
    build_lineage,
    utcnow_iso,
)
from aurora.data_contracts import (
    AvailabilityPolicy,
    ContractField,
    DataContract,
)

_log = logging.getLogger(__name__)


PROVIDER_NAME = "sec_edgar_companyfacts"
PROVIDER_URL = "https://www.sec.gov/"
TICKER_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL_TEMPLATE = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
COMPANYFACTS_URL_TEMPLATE = (
    "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
)
USER_AGENT_ENV_VAR = "AU_SEC_EDGAR_USER_AGENT"


# ---------------------------------------------------------------------------
# Provider descriptor (FUNDAMENTALS).
# ---------------------------------------------------------------------------


SEC_EDGAR_DESCRIPTOR = ProviderDescriptor(
    name=PROVIDER_NAME,
    role=ProviderRole.FUNDAMENTALS,
    licence_terms_url="https://www.sec.gov/about/data.htm",
    rate_limits="10 req/sec",
    auth_required=False,
    asset_classes=("equity",),
    intervals=("filing",),
    adjustment_posture="RAW",
    reliability="OFFICIAL",
)


# ---------------------------------------------------------------------------
# Data contract for stored facts (used by TimeSeriesStore).
# ---------------------------------------------------------------------------


SEC_FACTS_V1 = DataContract(
    name="sec_companyfacts_v1",
    version="1.0.0",
    description=(
        "SEC EDGAR XBRL company facts. Each row is one (cik, taxonomy, "
        "tag, accession_number, period_end) tuple with its scalar value, "
        "unit, period bounds, frame label, filing date and accepted "
        "timestamp. accepted_iso is the strict PIT availability axis."
    ),
    fields=(
        ContractField("cik", dtype_kind="integer"),
        ContractField("taxonomy", dtype_kind="string"),
        ContractField("tag", dtype_kind="string"),
        ContractField("unit", dtype_kind="string"),
        ContractField("value", dtype_kind="numeric", nullable=True),
        ContractField("period_start_iso", dtype_kind="string", nullable=True),
        ContractField("period_end_iso", dtype_kind="string"),
        ContractField("frame", dtype_kind="string", nullable=True),
        ContractField("accession_number", dtype_kind="string"),
        ContractField("filing_date_iso", dtype_kind="string"),
        ContractField("accepted_iso", dtype_kind="string"),
        ContractField("form", dtype_kind="string"),
        ContractField("source_url", dtype_kind="string"),
    ),
    timestamp_col="accepted_iso",
    timezone="UTC",
    allow_naive_timestamps=True,
    availability=AvailabilityPolicy(
        event_time_col="period_end_iso",
        available_time_col="accepted_iso",
    ),
)


# ---------------------------------------------------------------------------
# Frozen records.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CIKMapping:
    """One row of the SEC ticker / CIK table."""

    cik: int
    ticker: str
    name: str
    exchange: str = ""


@dataclass(frozen=True)
class Submission:
    """One filing in a company's submission history."""

    accession_number: str
    filing_date_iso: str
    accepted_iso: str
    form: str
    primary_document: str
    period_of_report_iso: str
    is_xbrl: bool


@dataclass(frozen=True)
class XBRLFact:
    """One scalar XBRL fact reported in one filing.

    ``accepted_iso`` is the strict PIT availability axis: a strategy
    deciding at time T may only consume facts whose ``accepted_iso <= T``.
    Use :func:`assert_pit_safe` or :func:`filter_pit_safe` at the call
    site -- this dataclass does NOT block reads on its own.
    """

    cik: int
    taxonomy: str
    tag: str
    unit: str
    value: float
    period_start_iso: str
    period_end_iso: str
    frame: str
    accession_number: str
    filing_date_iso: str
    accepted_iso: str
    form: str
    source_url: str


@dataclass(frozen=True)
class CompanyFactsBundle:
    """All facts + submissions for one CIK plus its provenance."""

    cik: int
    entity_name: str
    facts: Tuple[XBRLFact, ...]
    submissions: Tuple[Submission, ...]
    provenance: FreeBulkLineage


# ---------------------------------------------------------------------------
# Point-in-time helpers.
# ---------------------------------------------------------------------------


def _to_ts(iso_or_ts: Any) -> pd.Timestamp:
    """Coerce ISO string / Timestamp -> tz-naive UTC Timestamp.

    The PIT comparison must be tz-consistent. SEC's ``accepted`` field
    carries a trailing ``Z`` (UTC); a caller's decision_date is often
    a naive Timestamp meant to mean UTC. We strip tz from the parsed
    value so the comparison never raises ``Cannot compare tz-naive and
    tz-aware timestamps``.
    """
    if isinstance(iso_or_ts, pd.Timestamp):
        ts = iso_or_ts
    else:
        ts = pd.Timestamp(iso_or_ts)
    if ts.tz is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


def assert_pit_safe(fact: XBRLFact, decision_date: Any) -> None:
    """Raise if ``fact.accepted_iso`` is later than ``decision_date``.

    Use at the boundary of any strategy / factory consumer that reads
    SEC facts: each fact must be both (a) reported and (b) accepted by
    the SEC before the strategy's decision time.
    """
    decision_ts = _to_ts(decision_date)
    accepted_ts = _to_ts(fact.accepted_iso)
    if accepted_ts > decision_ts:
        raise ValueError(
            f"Fact accepted at {fact.accepted_iso} cannot be used for "
            f"decisions at {decision_ts.isoformat()} "
            f"(cik={fact.cik}, tag={fact.tag}, "
            f"accession={fact.accession_number})"
        )


def filter_pit_safe(
    facts: Tuple[XBRLFact, ...] | list[XBRLFact],
    decision_date: Any,
) -> Tuple[XBRLFact, ...]:
    """Return only the facts whose ``accepted_iso <= decision_date``.

    Equivalent to :func:`assert_pit_safe` per item but never raises;
    returns the safe subset as a tuple to keep the result immutable.
    """
    decision_ts = _to_ts(decision_date)
    return tuple(
        f for f in facts if _to_ts(f.accepted_iso) <= decision_ts
    )


# ---------------------------------------------------------------------------
# Default HTTP client (production).
# ---------------------------------------------------------------------------


def _default_http_get(url: str, headers: Mapping[str, str]) -> bytes:
    """Production GET: stdlib ``urllib.request`` so no extra dep needed."""
    from urllib.request import Request, urlopen

    req = Request(url, headers=dict(headers))
    with urlopen(req, timeout=60) as resp:  # nosec B310 -- official URL
        return resp.read()


# ---------------------------------------------------------------------------
# Client.
# ---------------------------------------------------------------------------


class SECEdgarClient:
    """SEC EDGAR fetcher with injectable HTTP transport."""

    name: str = PROVIDER_NAME
    version: str = "sec_edgar_companyfacts:1.0"

    def __init__(
        self,
        http_get: Optional[Callable[[str, Mapping[str, str]], bytes]] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        ua = user_agent if user_agent is not None else os.environ.get(
            USER_AGENT_ENV_VAR
        )
        if not ua:
            raise RuntimeError(
                "SEC EDGAR requires User-Agent; set "
                f"{USER_AGENT_ENV_VAR}"
            )
        self._user_agent = ua
        self._http_get = http_get or _default_http_get

    # -- private helpers --------------------------------------------------

    def _headers(self) -> Mapping[str, str]:
        return {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
        }

    def _get_json(self, url: str) -> Any:
        raw = self._http_get(url, self._headers())
        if isinstance(raw, (bytes, bytearray)):
            text = bytes(raw).decode("utf-8", errors="replace")
        else:
            text = str(raw)
        return json.loads(text)

    # -- ticker / CIK mapping ---------------------------------------------

    def fetch_ticker_cik_map(self) -> Tuple[CIKMapping, ...]:
        """Return the public ticker / CIK table.

        SEC's payload is a JSON object keyed by sequential index. Each
        entry has ``cik_str`` (int or string), ``ticker``, ``title``.
        Some downstream variants also include ``exchange``; we keep
        the field optional to handle both shapes.
        """
        payload = self._get_json(TICKER_CIK_URL)
        rows: list[CIKMapping] = []
        if isinstance(payload, dict):
            entries = payload.values()
        elif isinstance(payload, list):
            entries = payload
        else:
            entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            cik_raw = entry.get("cik_str", entry.get("cik"))
            if cik_raw is None:
                continue
            try:
                cik = int(cik_raw)
            except (TypeError, ValueError):
                continue
            ticker = str(entry.get("ticker", "")).strip().upper()
            name = str(entry.get("title", entry.get("name", ""))).strip()
            exchange = str(entry.get("exchange", "")).strip()
            if not ticker:
                continue
            rows.append(
                CIKMapping(cik=cik, ticker=ticker, name=name, exchange=exchange)
            )
        return tuple(rows)

    # -- submissions ------------------------------------------------------

    def fetch_submissions(self, cik: int) -> Tuple[Submission, ...]:
        """Return the recent submissions list for ``cik``.

        SEC stores recent filings under ``filings.recent`` with parallel
        arrays (``accessionNumber``, ``filingDate``, ``acceptanceDateTime``,
        ``form``, ``primaryDocument``, ``periodOfReport``, ``isXBRL``).
        """
        url = SUBMISSIONS_URL_TEMPLATE.format(cik=int(cik))
        payload = self._get_json(url)
        return _parse_submissions_payload(payload)

    # -- companyfacts -----------------------------------------------------

    def fetch_companyfacts(self, cik: int) -> CompanyFactsBundle:
        """Return the full XBRL fact bundle for ``cik``.

        The bundle contains every (taxonomy, tag, unit, period) row the
        SEC has on file. Submissions are NOT inside the companyfacts
        endpoint -- they are fetched separately and merged in.
        """
        url = COMPANYFACTS_URL_TEMPLATE.format(cik=int(cik))
        payload = self._get_json(url)
        facts, entity_name, warnings_seen = _parse_companyfacts_payload(
            payload, source_url=url
        )
        submissions = self.fetch_submissions(int(cik))
        merged = _merge_submission_metadata(facts, submissions)
        provenance = _build_companyfacts_lineage(
            cik=int(cik),
            facts=merged,
            url=url,
            warnings_seen=warnings_seen,
        )
        return CompanyFactsBundle(
            cik=int(cik),
            entity_name=entity_name,
            facts=merged,
            submissions=submissions,
            provenance=provenance,
        )

    # -- bulk archive -----------------------------------------------------

    def ingest_companyfacts_zip(
        self, zip_path: Path | str
    ) -> Iterator[CompanyFactsBundle]:
        """Yield one :class:`CompanyFactsBundle` per company in ``zip_path``.

        SEC's nightly archive is a ZIP of per-CIK JSON files. Each
        member file is named ``CIK{0000000000}.json``. We stream entries
        instead of loading the whole archive so the call is memory-safe
        even on the ~1.5 GB production archive.
        """
        zp = Path(zip_path)
        with zipfile.ZipFile(zp) as zf:
            for member in zf.namelist():
                if not member.lower().endswith(".json"):
                    continue
                with zf.open(member) as fh:
                    raw = fh.read()
                try:
                    payload = json.loads(raw.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    _log.warning(
                        "sec_edgar: failed to parse %s in %s", member, zp
                    )
                    continue
                cik_int = _coerce_cik_from_payload(payload, fallback_name=member)
                if cik_int is None:
                    continue
                source_url = f"zip://{zp.name}#{member}"
                facts, entity_name, warnings_seen = _parse_companyfacts_payload(
                    payload, source_url=source_url
                )
                provenance = _build_companyfacts_lineage(
                    cik=cik_int,
                    facts=facts,
                    url=source_url,
                    warnings_seen=warnings_seen,
                )
                yield CompanyFactsBundle(
                    cik=cik_int,
                    entity_name=entity_name,
                    facts=facts,
                    submissions=(),
                    provenance=provenance,
                )


# ---------------------------------------------------------------------------
# Parsing helpers (free functions so tests can exercise them directly).
# ---------------------------------------------------------------------------


def _parse_submissions_payload(payload: Any) -> Tuple[Submission, ...]:
    """Parse the ``submissions/CIK*.json`` JSON shape into Submissions."""
    if not isinstance(payload, dict):
        return ()
    filings = payload.get("filings", {})
    if not isinstance(filings, dict):
        return ()
    recent = filings.get("recent", {})
    if not isinstance(recent, dict):
        return ()
    accession = recent.get("accessionNumber", []) or []
    filing_date = recent.get("filingDate", []) or []
    accepted = recent.get("acceptanceDateTime", []) or []
    form = recent.get("form", []) or []
    primary = recent.get("primaryDocument", []) or []
    period = recent.get("periodOfReport", []) or []
    is_xbrl = recent.get("isXBRL", []) or []
    n = min(
        len(accession),
        len(filing_date),
        len(accepted),
        len(form),
        len(primary),
        len(period),
    )
    out: list[Submission] = []
    for i in range(n):
        try:
            xbrl_flag = bool(int(is_xbrl[i])) if i < len(is_xbrl) else False
        except (TypeError, ValueError):
            xbrl_flag = False
        out.append(
            Submission(
                accession_number=str(accession[i]),
                filing_date_iso=str(filing_date[i]),
                accepted_iso=str(accepted[i]),
                form=str(form[i]),
                primary_document=str(primary[i]),
                period_of_report_iso=str(period[i]),
                is_xbrl=xbrl_flag,
            )
        )
    return tuple(out)


def _coerce_cik_from_payload(
    payload: Any, *, fallback_name: str = ""
) -> Optional[int]:
    """Pull the CIK out of a companyfacts JSON; fall back to filename."""
    if isinstance(payload, dict):
        cik_raw = payload.get("cik")
        if cik_raw is not None:
            try:
                return int(cik_raw)
            except (TypeError, ValueError):
                pass
    # Filename-style ``CIK0000320193.json`` -- strip the prefix.
    fb = fallback_name.split("/")[-1].split("\\")[-1]
    if fb.lower().startswith("cik"):
        digits = "".join(ch for ch in fb if ch.isdigit())
        if digits:
            try:
                return int(digits)
            except ValueError:
                return None
    return None


def _parse_companyfacts_payload(
    payload: Any, *, source_url: str
) -> tuple[Tuple[XBRLFact, ...], str, Tuple[str, ...]]:
    """Parse the companyfacts JSON into (facts, entity_name, warnings).

    Walks ``payload['facts'][taxonomy][tag]['units'][unit]`` -- the
    nested structure SEC uses. Records a warning when one tag reports
    in more than one unit (e.g. USD and EUR for the same series).
    """
    if not isinstance(payload, dict):
        return (), "", ()
    cik_raw = payload.get("cik")
    try:
        cik = int(cik_raw) if cik_raw is not None else 0
    except (TypeError, ValueError):
        cik = 0
    entity_name = str(payload.get("entityName", payload.get("name", "")))
    facts_root = payload.get("facts", {})
    if not isinstance(facts_root, dict):
        return (), entity_name, ()
    out: list[XBRLFact] = []
    warnings_seen: list[str] = []
    for taxonomy_key, tags in facts_root.items():
        if not isinstance(tags, dict):
            continue
        for tag_key, tag_payload in tags.items():
            if not isinstance(tag_payload, dict):
                continue
            units = tag_payload.get("units", {})
            if not isinstance(units, dict):
                continue
            unit_keys = [u for u in units.keys() if isinstance(u, str)]
            if len(unit_keys) > 1:
                msg = (
                    f"unit_inconsistency: tag {tag_key!r} reports in units "
                    f"{sorted(unit_keys)}"
                )
                warnings_seen.append(msg)
                warnings.warn(msg, UserWarning, stacklevel=3)
            for unit_key, entries in units.items():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    try:
                        value = float(entry.get("val"))
                    except (TypeError, ValueError):
                        continue
                    out.append(
                        XBRLFact(
                            cik=cik,
                            taxonomy=str(taxonomy_key),
                            tag=str(tag_key),
                            unit=str(unit_key),
                            value=value,
                            period_start_iso=str(entry.get("start", "")),
                            period_end_iso=str(entry.get("end", "")),
                            frame=str(entry.get("frame", "")),
                            accession_number=str(entry.get("accn", "")),
                            filing_date_iso=str(entry.get("filed", "")),
                            accepted_iso=str(
                                entry.get("accepted", entry.get("filed", ""))
                            ),
                            form=str(entry.get("form", "")),
                            source_url=source_url,
                        )
                    )
    return tuple(out), entity_name, tuple(warnings_seen)


def _merge_submission_metadata(
    facts: Tuple[XBRLFact, ...],
    submissions: Tuple[Submission, ...],
) -> Tuple[XBRLFact, ...]:
    """Backfill ``accepted_iso`` on facts using the submissions table.

    Companyfacts entries normally carry ``filed`` (filing date) and
    sometimes ``accepted``; when ``accepted`` is missing we pull the
    accepted timestamp from the matching submission. This keeps PIT
    timestamps strict even when the SEC payload is sparse.
    """
    if not submissions:
        return facts
    by_accession: dict[str, Submission] = {
        s.accession_number: s for s in submissions
    }
    out: list[XBRLFact] = []
    for f in facts:
        sub = by_accession.get(f.accession_number)
        if sub is not None and (
            not f.accepted_iso or f.accepted_iso == f.filing_date_iso
        ):
            out.append(
                XBRLFact(
                    cik=f.cik,
                    taxonomy=f.taxonomy,
                    tag=f.tag,
                    unit=f.unit,
                    value=f.value,
                    period_start_iso=f.period_start_iso,
                    period_end_iso=f.period_end_iso,
                    frame=f.frame,
                    accession_number=f.accession_number,
                    filing_date_iso=f.filing_date_iso or sub.filing_date_iso,
                    accepted_iso=sub.accepted_iso or f.accepted_iso,
                    form=f.form or sub.form,
                    source_url=f.source_url,
                )
            )
        else:
            out.append(f)
    return tuple(out)


# ---------------------------------------------------------------------------
# Lineage / TimeSeriesStore integration.
# ---------------------------------------------------------------------------


def facts_to_dataframe(facts: Tuple[XBRLFact, ...]) -> pd.DataFrame:
    """Convert a tuple of facts into the canonical fundamentals frame."""
    cols = (
        "cik",
        "taxonomy",
        "tag",
        "unit",
        "value",
        "period_start_iso",
        "period_end_iso",
        "frame",
        "accession_number",
        "filing_date_iso",
        "accepted_iso",
        "form",
        "source_url",
    )
    if not facts:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in cols})
    rows = [
        {
            "cik": f.cik,
            "taxonomy": f.taxonomy,
            "tag": f.tag,
            "unit": f.unit,
            "value": f.value,
            "period_start_iso": f.period_start_iso,
            "period_end_iso": f.period_end_iso,
            "frame": f.frame,
            "accession_number": f.accession_number,
            "filing_date_iso": f.filing_date_iso,
            "accepted_iso": f.accepted_iso,
            "form": f.form,
            "source_url": f.source_url,
        }
        for f in facts
    ]
    return pd.DataFrame(rows, columns=list(cols))


def _build_companyfacts_lineage(
    *,
    cik: int,
    facts: Tuple[XBRLFact, ...],
    url: str,
    warnings_seen: Tuple[str, ...],
) -> FreeBulkLineage:
    df = facts_to_dataframe(facts)
    # SEC_FACTS_V1 declares accepted_iso as the timestamp_col; build_lineage
    # uses it to derive date_range. We keep the timestamps as strings
    # (no tz coercion) so the contract's allow_naive_timestamps stays honest.
    return build_lineage(
        df=df,
        contract=SEC_FACTS_V1,
        provider_name=PROVIDER_NAME,
        provider_url=PROVIDER_URL,
        retrieved_at_iso=utcnow_iso(),
        auth_mode="user_agent",
        query_params={"cik": cik, "endpoint": url},
        symbol_count=1,
        extra={
            "reliability": "OFFICIAL",
            "source": "SEC EDGAR",
            "asset_class": "FUNDAMENTALS",
            "library": "fundamentals_sec",
            "endpoint": url,
            "row_count": len(facts),
            "unit_warnings": list(warnings_seen),
        },
    )


def store_bundle(
    bundle: CompanyFactsBundle,
    *,
    store: Any | None = None,
    library: str = "fundamentals_sec",
    replace: bool = False,
) -> Any:
    """Persist a :class:`CompanyFactsBundle` via TimeSeriesStore.

    The store is keyed on the CIK; one bundle = one stored DataFrame
    version. Lazy-imports the default store so test files that do not
    use the store do not pay the import cost.
    """
    if store is None:
        from aurora.data_contracts.timeseries_store import default_store

        store = default_store()
    df = facts_to_dataframe(bundle.facts)
    metadata = {
        "cik": str(bundle.cik),
        "entity_name": bundle.entity_name,
        "provider": PROVIDER_NAME,
        "endpoint": bundle.provenance.extra.get("endpoint", ""),
        "retrieved_at_iso": bundle.provenance.retrieved_at_iso,
        "row_count": str(len(bundle.facts)),
    }
    return store.put(
        library=library,
        symbol=str(bundle.cik),
        df=df,
        metadata=metadata,
        replace=replace,
    )


def descriptor() -> ProviderDescriptor:
    """Return the provider descriptor (parity with sibling providers)."""
    return SEC_EDGAR_DESCRIPTOR


__all__ = [
    "CIKMapping",
    "CompanyFactsBundle",
    "PROVIDER_NAME",
    "PROVIDER_URL",
    "SEC_EDGAR_DESCRIPTOR",
    "SEC_FACTS_V1",
    "SECEdgarClient",
    "Submission",
    "TICKER_CIK_URL",
    "USER_AGENT_ENV_VAR",
    "XBRLFact",
    "assert_pit_safe",
    "descriptor",
    "facts_to_dataframe",
    "filter_pit_safe",
    "store_bundle",
]
