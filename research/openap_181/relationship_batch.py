"""Pinned formulas and fail-closed source evidence for relationship signals."""

from __future__ import annotations

from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping
import json
import re
import time
import urllib.request

import pandas as pd


OPENAP_COMMIT = "8db892442c2c3a3779b0f1eac4370d3655be15a1"

DOCUMENT_URLS = {
    "bea_io": "https://apps.bea.gov/api/signup/",
    "bea_terms": "https://www.bea.gov/open-data",
    "census_concordance": "https://www.census.gov/naics/concordances/concordances.html",
    "census_terms": "https://www.census.gov/about/policies/copyright.html",
    "sec_api": "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
    "sec_xbrl": "https://www.sec.gov/page/osd_xbrlglossary",
    "sec_reuse": "https://www.sec.gov/about/webmaster-frequently-asked-questions",
    "sec_fsd": "https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets",
    "compustat_segments": (
        "https://www.marketplace.spglobal.com/en/datasets/compustat-financials-%288%29"
    ),
    "factset_supply_chain": (
        "https://www.factset.com/marketplace/catalog/product/"
        "factset-supply-chain-relationships"
    ),
}
DOCUMENT_GROUPS = {name: (name,) for name in DOCUMENT_URLS}
_REQUIRED_DOCUMENTS = frozenset(DOCUMENT_GROUPS)
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")

_IOMOM_PATH = "Signals/pyCode/Predictors/ZZ1_iomom_cust__iomom_supp.py"
OPENAP_FORMULA_SOURCES: dict[str, dict[str, str]] = {
    "CustomerMomentum": {
        "path": "Signals/pyCode/Predictors/CustomerMomentum.py",
        "sha256": "ea3f920fa3df6d261daf55de57b261083e7f853f7e18930cce8af2d5dc1168ce",
    },
    "iomom_cust": {
        "path": _IOMOM_PATH,
        "sha256": "b8f5ec7425ef8e3d8e12e680e73d4f3aa6912eba9cee2e0d23b7ad2ead951f51",
    },
    "iomom_supp": {
        "path": _IOMOM_PATH,
        "sha256": "b8f5ec7425ef8e3d8e12e680e73d4f3aa6912eba9cee2e0d23b7ad2ead951f51",
    },
    "retConglomerate": {
        "path": "Signals/pyCode/Predictors/retConglomerate.py",
        "sha256": "45a9bde0427f776fba5750824ec26c1867352855ee821b9d45913e93c3d43622",
    },
    "sinAlgo": {
        "path": "Signals/pyCode/Predictors/sinAlgo.py",
        "sha256": "18c16b295bd0aab19e7e7581f31f10405fb00c48c01574862805a76d3fd4863f",
    },
}
RELATIONSHIP_SIGNALS = frozenset(OPENAP_FORMULA_SOURCES)

RELATIONSHIP_SIGNAL_FAMILIES = {
    "CustomerMomentum": "firm_customer_links",
    "iomom_cust": "bea_industry_network",
    "iomom_supp": "bea_industry_network",
    "retConglomerate": "business_segments",
    "sinAlgo": "business_segments",
}


def _requirement(
    formula: str,
    exact_inputs: str,
    timing: str,
    sample_start: int,
    sample_end: int,
    identity: str,
) -> dict[str, Any]:
    return {
        "formula": formula,
        "exact_inputs": exact_inputs,
        "timing": timing,
        "sample_start": sample_start,
        "sample_end": sample_end,
        "identity": identity,
    }


RELATIONSHIP_FORMULA_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "CustomerMomentum": _requirement(
        "sales-weighted prior-month returns of each supplier firm's principal customers",
        "compustat_customer_segments;customer_sales_share;customer_monthly_returns",
        "links are annual as filed; customer return is lagged one month; monthly formation",
        1981,
        2004,
        "historical supplier GVKEY to named customer GVKEY/PERMNO and security-month bridge",
    ),
    "iomom_cust": _requirement(
        "BEA make-table customer-industry weighted returns excluding own industry",
        "bea_make_tables;bea_70_industry_weights;firm_naics;industry_month_returns",
        "five-year lagged firm NAICS; annual table vintage; prior-month industry returns",
        1986,
        2017,
        "historical firm NAICS to BEA industry and PERMNO bridge",
    ),
    "iomom_supp": _requirement(
        "BEA use-table supplier-industry weighted returns excluding own industry",
        "bea_use_tables;bea_70_industry_weights;firm_naics;industry_month_returns",
        "five-year lagged firm NAICS; annual table vintage; prior-month industry returns",
        1986,
        2017,
        "historical firm NAICS to BEA industry and PERMNO bridge",
    ),
    "retConglomerate": _requirement(
        "segment-sales-weighted standalone 2-digit SIC returns after requiring 80% asset coverage",
        "compustat_opseg_busseg;segment_sales;segment_assets;segment_sic;standalone_returns",
        "annual segment disclosure available after filing; monthly return formation",
        1977,
        2017,
        "historical segment GVKEY/SID to parent GVKEY and PERMNO bridge",
    ),
    "sinAlgo": _requirement(
        "binary historical firm flag from Compustat segment SIC/NAICS sin-industry membership",
        "compustat_segment_sic;segment_naics;complete_historical_firm_segment_panel",
        "OpenAP applies any observed qualifying segment to the firm's full history and future",
        1926,
        2006,
        "historical segment and parent GVKEY identity with security bridge",
    ),
}


SOURCE_ASSESSMENTS = (
    {
        "source_id": "openap_official",
        "access": "public_code_and_reference_data",
        "history": "published signal-specific reference samples",
        "fields": "official formulas, definitions and historical reference values",
        "project_use_authorized": True,
        "exact_for_openap": True,
        "blocker": "not_a_current_source_and_no_ticker_permno_crosswalk",
    },
    {
        "source_id": "bea_input_output",
        "access": "public_api_and_static_files",
        "history": "historical benchmark and annual make-use tables; vintage varies",
        "fields": "industry make, use, direct and total requirements tables",
        "project_use_authorized": True,
        "exact_for_openap": False,
        "blocker": "industry_network_only_no_firm_year_naics_or_security_identity",
    },
    {
        "source_id": "census_naics_concordance",
        "access": "public_static_files",
        "history": "1987 SIC and multiple NAICS classification vintages",
        "fields": "classification-system concordances",
        "project_use_authorized": True,
        "exact_for_openap": False,
        "blocker": "many_to_many_concordance_not_a_firm_year_classification",
    },
    {
        "source_id": "sec_edgar",
        "access": "public_api_bulk_and_filings",
        "history": "filings long predate structured XBRL; XBRL generally from 2009",
        "fields": "filing text, inline XBRL contexts, CIK and acceptance timestamps",
        "project_use_authorized": True,
        "exact_for_openap": False,
        "blocker": "principal_customer_and_segment_names_are_not_a_complete_standardized_panel",
    },
    {
        "source_id": "compustat_commercial",
        "access": "institutional_vendor_license",
        "history": "North America current, historical, point-in-time and segment products",
        "fields": "customer segments, business/operating segments, sales, assets, SIC, GVKEY",
        "project_use_authorized": False,
        "exact_for_openap": True,
        "blocker": "commercial_subscription_required",
    },
    {
        "source_id": "factset_supply_chain_commercial",
        "access": "commercial_data_feed",
        "history": "North America relationships from 2003; global starts vary",
        "fields": "customers, suppliers, partners, competitors, direction and revenue dependency",
        "project_use_authorized": False,
        "exact_for_openap": False,
        "blocker": "subscription_required_and_not_compustat_segment_equivalent",
    },
    {
        "source_id": "crsp_stock_commercial",
        "access": "institutional_vendor_license",
        "history": "long US security returns and permanent identifiers",
        "fields": "PERMNO, returns, delistings, shares and corporate actions",
        "project_use_authorized": False,
        "exact_for_openap": True,
        "blocker": "commercial_subscription_required",
    },
    {
        "source_id": "wrds_linking_suite",
        "access": "institutional_vendor_license",
        "history": "link validity depends on every underlying product",
        "fields": "CRSP-Compustat and supply-chain identifier links",
        "project_use_authorized": False,
        "exact_for_openap": True,
        "blocker": "wrds_and_each_vendor_license_required",
    },
)


RELATIONSHIP_BLOCKERS = {
    "CustomerMomentum": "relationship_source_blocked:historical_compustat_principal_customer_panel+sales_weights+customer_security_identity+returns_unavailable_free",
    "iomom_cust": "relationship_source_blocked:exact_bea_make_vintages+five_year_lagged_firm_naics+bea70_bridge+historical_security_returns_unvalidated",
    "iomom_supp": "relationship_source_blocked:exact_bea_use_vintages+five_year_lagged_firm_naics+bea70_bridge+historical_security_returns_unvalidated",
    "retConglomerate": "relationship_source_blocked:compustat_segment_sales_80pct_assets+segment_sic+standalone_returns+historical_links_unavailable_free",
    "sinAlgo": "relationship_source_blocked:compustat_full_history_segment_classification+parent_security_identity_unavailable_free",
}


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def _visible_text(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(str(value))
    text = " ".join(parser.parts).lower()
    for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        text = text.replace(dash, "-")
    return " ".join(text.replace("\xa0", " ").split())


def _has_all(text: str, *tokens: str) -> bool:
    return all(token in text for token in tokens)


def evaluate_relationship_source_documents(
    documents: Mapping[str, str],
    *,
    access_errors: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluate primary documents while keeping incomplete access fail-closed."""

    errors = dict(access_errors or {})
    text = {name: _visible_text(documents.get(name, "")) for name in _REQUIRED_DOCUMENTS}
    blocked = sorted(name for name in _REQUIRED_DOCUMENTS if not text[name] and name in errors)
    unresolved = sorted(
        name for name in _REQUIRED_DOCUMENTS if not text[name] and name not in errors
    )

    bea_network = _has_all(text["bea_io"], "inputoutput", "make", "use")
    bea_authorized = _has_all(text["bea_terms"], "public domain", "programmatic access")
    census_history = _has_all(
        text["census_concordance"], "1987 sic", "1997", "2002 naics"
    )
    census_many_to_many = "one-to-many" in text["census_concordance"]
    census_authorized = "public domain" in text["census_terms"]
    sec_entity_only = _has_all(text["sec_api"], "company facts", "entire filing entity")
    sec_dimensions = _has_all(text["sec_xbrl"], "dimensions", "segment information")
    sec_reuse = _has_all(text["sec_reuse"], "free", "reuse")
    sec_fsd_incomplete = _has_all(text["sec_fsd"], "do not provide all", "notes")
    compustat_commercial = _has_all(
        text["compustat_segments"], "segment", "point-in-time", "licensed"
    )
    factset_commercial = _has_all(
        text["factset_supply_chain"], "customers", "suppliers", "subscription"
    )
    checks = (
        bea_network,
        bea_authorized,
        census_history,
        census_many_to_many,
        census_authorized,
        sec_entity_only,
        sec_dimensions,
        sec_reuse,
        sec_fsd_incomplete,
        compustat_commercial,
        factset_commercial,
    )
    return {
        "official_documents_verified": not blocked and not unresolved and all(checks),
        "source_access_decision_complete": not unresolved,
        "access_blocked_documents": blocked,
        "access_errors": {name: errors[name] for name in blocked},
        "unresolved_documents": unresolved,
        "bea_io_free_authorized": bea_authorized,
        "bea_industry_network_verified": bea_network,
        "census_historical_concordance_verified": census_history,
        "census_concordance_unique_firm_bridge": False,
        "sec_free_reuse_authorized": sec_reuse,
        "sec_companyfacts_entity_only": sec_entity_only,
        "sec_xbrl_dimensions_available": sec_dimensions,
        "sec_full_segment_notes_in_fsd": False,
        "compustat_segments_commercial_verified": compustat_commercial,
        "factset_supply_chain_commercial_verified": factset_commercial,
        "exact_free_authorized_source_found": False,
        "strict_approved": 0,
    }


def build_relationship_batch_evidence(
    probe: Mapping[str, Any],
    *,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> pd.DataFrame:
    """Build evidence that can replace generic blockers but cannot promote signals."""

    valid = (
        probe.get("source_access_decision_complete") is True
        and probe.get("unresolved_documents") == []
        and probe.get("formula_sources_verified") is True
        and probe.get("exact_free_authorized_source_found") is False
        and probe.get("raw_source_data_downloaded") is False
        and probe.get("raw_files_in_artifact") is False
        and probe.get("locked_opened") is False
        and probe.get("validation_used_for_selection") is False
        and probe.get("strict_approved") == 0
        and str(evidence_run_url).startswith("https://")
        and bool(str(evidence_artifact).strip())
        and bool(_COMMIT_RE.fullmatch(str(implementation_commit)))
    )
    if not valid:
        raise ValueError("Invalid or incomplete relationship probe evidence")
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
                "blocking_reason": RELATIONSHIP_BLOCKERS[signal],
                "evidence_run_url": str(evidence_run_url),
                "evidence_artifact": str(evidence_artifact).strip(),
                "implementation_commit": str(implementation_commit),
            }
            for signal in sorted(RELATIONSHIP_SIGNALS)
        ]
    )


def write_relationship_source_probe_outputs(
    probe: Mapping[str, Any],
    *,
    output_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> None:
    """Write documentary metadata only, never relationship, filing or return records."""

    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = build_relationship_batch_evidence(
        probe,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    (output_dir / "relationship_source_probe.json").write_text(
        json.dumps(dict(probe), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    pd.DataFrame(SOURCE_ASSESSMENTS).to_csv(
        output_dir / "relationship_source_assessment.csv", index=False
    )
    pd.DataFrame(
        [
            {
                "signal": signal,
                "family": RELATIONSHIP_SIGNAL_FAMILIES[signal],
                **requirement,
                "formula_path": OPENAP_FORMULA_SOURCES[signal]["path"],
                "formula_sha256": OPENAP_FORMULA_SOURCES[signal]["sha256"],
                "formula_commit": OPENAP_COMMIT,
            }
            for signal, requirement in sorted(RELATIONSHIP_FORMULA_REQUIREMENTS.items())
        ]
    ).to_csv(output_dir / "relationship_formula_requirements.csv", index=False)
    evidence.to_csv(output_dir / "relationship_batch_evidence.csv", index=False)
    blocked_docs = ", ".join(probe.get("access_blocked_documents", []))
    report = "\n".join(
        (
            "# OpenAP relationship source probe",
            "",
            "- Five pinned OpenAP formula contracts were verified by source hash.",
            "- BEA and Census provide authorized industry networks and concordances, not firm-year identity.",
            "- SEC filings are authorized and causal, but do not form a complete standardized Compustat segment panel.",
            "- Compustat Historical Segments and FactSet Supply Chain are commercial reference products.",
            f"- Official document access blockers: {blocked_docs or 'none'}.",
            "- No raw relationship, filing, segment or market-return records were downloaded or retained.",
            "- Strict approvals: 0. All five signals remain fail-closed.",
            "",
        )
    )
    (output_dir / "RELATIONSHIP_SOURCE_PROBE_REPORT.md").write_text(
        report, encoding="utf-8"
    )


def _headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Aurora-OpenAP-181-relationship-source-probe/1.0 "
            "contact https://github.com/trading-optimizer-lab-org/aurora"
        ),
        "Accept": "text/html,text/plain,application/json,application/pdf",
    }


def _fetch(url: str, *, attempts: int = 3) -> bytes:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=_headers())
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.read()
        except Exception as exc:  # pragma: no cover - exercised in GitHub Actions
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"Unable to fetch {url}: {last_error}")


def run_relationship_source_probe(
    *,
    output_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> dict[str, Any]:
    """Verify pinned formulas and live official documentation without source data."""

    payload_cache: dict[str, bytes] = {}
    formula_verified = True
    for source in OPENAP_FORMULA_SOURCES.values():
        path = source["path"]
        if path not in payload_cache:
            payload_cache[path] = _fetch(
                "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
                f"{OPENAP_COMMIT}/{path}"
            )
        formula_verified &= sha256(payload_cache[path]).hexdigest() == source["sha256"]
    if not formula_verified:
        raise ValueError("Pinned OpenAP relationship formula source hash mismatch")

    documents: dict[str, str] = {}
    access_errors: dict[str, str] = {}
    for document_name, source_names in DOCUMENT_GROUPS.items():
        payloads: list[str] = []
        errors: list[str] = []
        for source_name in source_names:
            try:
                payloads.append(
                    _fetch(DOCUMENT_URLS[source_name]).decode("utf-8", errors="replace")
                )
            except RuntimeError as exc:
                errors.append(f"{source_name}:{exc}")
        documents[document_name] = " ".join(payloads)
        if errors:
            access_errors[document_name] = ";".join(errors)
    summary = evaluate_relationship_source_documents(
        documents, access_errors=access_errors
    )
    if not summary["source_access_decision_complete"]:
        raise ValueError(
            "Official relationship documentation contract unresolved: "
            + ",".join(summary["unresolved_documents"])
        )
    summary.update(
        {
            "formula_sources_verified": True,
            "formula_commit": OPENAP_COMMIT,
            "formula_signals": len(RELATIONSHIP_SIGNALS),
            "raw_source_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    write_relationship_source_probe_outputs(
        summary,
        output_dir=output_dir,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    return summary


__all__ = [
    "DOCUMENT_GROUPS",
    "DOCUMENT_URLS",
    "OPENAP_COMMIT",
    "OPENAP_FORMULA_SOURCES",
    "RELATIONSHIP_BLOCKERS",
    "RELATIONSHIP_FORMULA_REQUIREMENTS",
    "RELATIONSHIP_SIGNAL_FAMILIES",
    "RELATIONSHIP_SIGNALS",
    "SOURCE_ASSESSMENTS",
    "build_relationship_batch_evidence",
    "evaluate_relationship_source_documents",
    "run_relationship_source_probe",
    "write_relationship_source_probe_outputs",
]
