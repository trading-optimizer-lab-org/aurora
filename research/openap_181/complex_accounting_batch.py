"""Pinned formulas and fail-closed evidence for complex OpenAP accounting signals."""

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
OPENAP_FORMULA_FILES: dict[str, dict[str, str]] = {
    "DelDRC": {
        "path": "Signals/pyCode/Predictors/DelDRC.py",
        "sha256": "b2a07c603cd53e3201db79bc7358209c552babe2e41a1695ae9ab716f0bea808",
    },
    "FR": {
        "path": "Signals/pyCode/Predictors/ZZ1_FR_FRbook.py",
        "sha256": "8dbe39c5efa2112faea3ecdb7b605b1420e7e0bd067a7b7a01a315abd34c8d0f",
    },
    "GrSaleToGrOverhead": {
        "path": "Signals/pyCode/Predictors/GrSaleToGrOverhead.py",
        "sha256": "6bdb090d093d504f36c3c9cffc0070059c061e5bbebbbc09ebcf6a45f5dac58c",
    },
    "OperProfRD": {
        "path": "Signals/pyCode/Predictors/OperProfRD.py",
        "sha256": "b68d80ea3cc45b2fa4ce6b842f4a9c4fcbe7a1e9393a4cab456629222cdf4e72",
    },
    "RDAbility": {
        "path": "Signals/pyCode/Predictors/RDAbility.py",
        "sha256": "8a8e2dd8afafde672021f22774d11dd84b4951a89510dbb5759c76ea3839cea6",
    },
    "ShareRepurchase": {
        "path": "Signals/pyCode/Predictors/ShareRepurchase.py",
        "sha256": "305fdfbcab492ee39605da792a9dd234d565e09cc3816e889793559b8c1f8657",
    },
    "VarCF": {
        "path": "Signals/pyCode/Predictors/VarCF.py",
        "sha256": "88a67993274bda2490306e942605537be4752af7dd708d3181ef0b8a880123b9",
    },
    "realestate": {
        "path": "Signals/pyCode/Predictors/realestate.py",
        "sha256": "83f46e96b508f2274c5da5919c24be2271b226204b6996a8baee15038740f771",
    },
}

COMPLEX_ACCOUNTING_SIGNALS = frozenset(OPENAP_FORMULA_FILES)
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")

DOCUMENT_URLS = {
    "sec_fsd": (
        "https://www.sec.gov/data-research/sec-markets-data/"
        "financial-statement-data-sets"
    ),
    "sec_edgar_apis": (
        "https://www.sec.gov/search-filings/"
        "edgar-application-programming-interfaces"
    ),
    "openfigi": "https://www.openfigi.com/api/documentation",
    "crsp": "https://www.crsp.org/research/",
    "compustat": (
        "https://www.spglobal.com/market-intelligence/en/solutions/products/"
        "fundamental-data"
    ),
}
_REQUIRED_DOCUMENTS = frozenset(DOCUMENT_URLS)


def _requirement(
    *,
    formula: str,
    exact_inputs: str,
    timing: str,
    identity: str,
    filters: str = "none",
    cross_section: str = "none",
    window_months: int = 1,
    minimum_periods: int = 1,
    minimum_industry_observations: int = 0,
) -> dict[str, Any]:
    return {
        "formula": formula,
        "exact_inputs": exact_inputs,
        "timing": timing,
        "identity": identity,
        "filters": filters,
        "cross_section": cross_section,
        "window_months": window_months,
        "minimum_periods": minimum_periods,
        "minimum_industry_observations": minimum_industry_observations,
    }


FORMULA_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "DelDRC": _requirement(
        formula="(drc-lag12_drc)/(0.5*(at+lag12_at))",
        exact_inputs="Compustat_drc;at;ceq;sale;sic;monthly_time_avail_m",
        timing="annual filing value expanded causally on OpenAP monthly availability",
        identity="historical GVKEY to PERMNO validity intervals",
        filters="ceq<=0;drc_zero_and_zero_change;sale<5;SIC_6000_6999",
        window_months=12,
    ),
    "FR": _requirement(
        formula=(
            "FVPA-PBO scaled by mve_permco; 1980-1986 pbnaa/pbnvv, "
            "1987-1997 pplao+pplau and pbpro+pbpru, 1998+ pplao/pbpro"
        ),
        exact_inputs=(
            "Compustat_pbnaa;pplao;pplau;pbnvv;pbpro;pbpru;at;"
            "CRSP_mve_permco;shrcd"
        ),
        timing="year-specific pension definitions joined to monthly OpenAP availability",
        identity="historical GVKEY, PERMNO and PERMCO links",
        filters="shrcd<=11",
    ),
    "GrSaleToGrOverhead": _requirement(
        formula=(
            "growth from current value versus mean of 12- and 24-month lags for sale "
            "minus xsga growth; 12-month fallback when primary is missing"
        ),
        exact_inputs="Compustat_sale;xsga;monthly_time_avail_m",
        timing="only filings available before each formation month",
        identity="historical GVKEY to PERMNO validity intervals",
        window_months=24,
    ),
    "OperProfRD": _requirement(
        formula="(revt-cogs-xsga+xrd)/at; missing xrd becomes zero",
        exact_inputs=(
            "Compustat_xrd;revt;cogs;xsga;at;ceq;CRSP_mve_c;shrcd;sicCRSP"
        ),
        timing="monthly OpenAP availability from accepted filings",
        identity="historical GVKEY/PERMNO/PERMCO links and CRSP name history",
        filters="shrcd<=11;mve_c_ceq_at_nonmissing;exclude_sic_6000_6999",
    ),
    "RDAbility": _requirement(
        formula=(
            "mean of five lag-specific rolling coefficients from log sales growth on "
            "lagged log(1+xrd/sale), 8 annual observations with minimum 6"
        ),
        exact_inputs="Compustat_xrd;sale;fyear;datadate;monthly_time_avail_m",
        timing="annual as-filed histories expanded for 12 months without future filings",
        identity="historical GVKEY to PERMNO validity intervals",
        filters="negative_xrd_or_sales_missing;positive_xrd_required",
        cross_section="top_xrd_intensity_tercile",
        window_months=8 * 12,
        minimum_periods=6,
    ),
    "ShareRepurchase": _requirement(
        formula="1 when Compustat prstkc > 0, 0 otherwise, missing when prstkc missing",
        exact_inputs="Compustat_prstkc;monthly_time_avail_m",
        timing="cash-flow statement accepted before formation month",
        identity="historical GVKEY to PERMNO validity intervals",
    ),
    "VarCF": _requirement(
        formula="rolling variance of (ib+dp)/mve_permco",
        exact_inputs="Compustat_ib;dp;CRSP_mve_permco;monthly_time_avail_m",
        timing="trailing monthly values only through formation month",
        identity="historical GVKEY, PERMNO and PERMCO links",
        window_months=60,
        minimum_periods=24,
    ),
    "realestate": _requirement(
        formula=(
            "industry-adjusted (fatb+fatl)/ppegt, falling back to "
            "(ppenb+ppenls)/ppent"
        ),
        exact_inputs="Compustat_ppenb;ppenls;fatb;fatl;ppegt;ppent;at;CRSP_sic",
        timing="accepted annual filing values expanded on OpenAP monthly availability",
        identity="historical GVKEY/PERMNO links and CRSP SIC history",
        filters="at_nonmissing;ppent_or_ppegt_nonmissing",
        cross_section="two_digit_crsp_sic_month_mean_adjustment",
        minimum_industry_observations=5,
    ),
}


SOURCE_ASSESSMENTS = (
    {
        "source_id": "openap_official",
        "access": "public_pinned_code",
        "history": "current executable formula definitions",
        "fields": "exact formulas and named Compustat/CRSP inputs",
        "project_use_authorized": True,
        "exact_for_openap": True,
        "data_feed": False,
        "blocker": "code_is_not_a_data_feed",
    },
    {
        "source_id": "sec_financial_statement_datasets",
        "access": "official_public_bulk",
        "history": "primary financial statements from 2009 onward",
        "fields": "as-filed XBRL facts, filings, tags and presentation",
        "project_use_authorized": True,
        "exact_for_openap": False,
        "data_feed": True,
        "blocker": "not_standardized_compustat_semantics_or_pre_2009_history",
    },
    {
        "source_id": "sec_edgar",
        "access": "official_public_api_and_filings",
        "history": "filings and XBRL from 2009, older unstructured filings",
        "fields": "CIK, accession, acceptance time and filer taxonomies",
        "project_use_authorized": True,
        "exact_for_openap": False,
        "data_feed": True,
        "blocker": "custom_tags_and_no_historical_permno_spine",
    },
    {
        "source_id": "openfigi",
        "access": "official_public_mapping_api",
        "history": "current identifier mappings",
        "fields": "third-party identifiers to FIGI metadata",
        "project_use_authorized": True,
        "exact_for_openap": False,
        "data_feed": True,
        "blocker": "no_permno_or_historical_validity_intervals",
    },
    {
        "source_id": "crsp_stock_commercial",
        "access": "subscriber_product",
        "history": "long US security and market history",
        "fields": "PERMNO, PERMCO, market equity, share codes, SIC and delistings",
        "project_use_authorized": False,
        "exact_for_openap": True,
        "data_feed": True,
        "blocker": "commercial_subscription_required",
    },
    {
        "source_id": "compustat_commercial",
        "access": "licensed_product",
        "history": "standardized fundamentals from 1950 and PIT from 1987",
        "fields": "all named Compustat fields and historical snapshots",
        "project_use_authorized": False,
        "exact_for_openap": True,
        "data_feed": True,
        "blocker": "commercial_license_required",
    },
    {
        "source_id": "wrds_linking_suite",
        "access": "institutional_license",
        "history": "historical CRSP/Compustat validity intervals",
        "fields": "GVKEY, PERMNO and PERMCO links",
        "project_use_authorized": False,
        "exact_for_openap": True,
        "data_feed": True,
        "blocker": "wrds_and_vendor_licenses_required",
    },
)


COMPLEX_ACCOUNTING_BLOCKERS = {
    "DelDRC": (
        "complex_accounting_source_blocked:exact_compustat_drc_ceq_sale_at+"
        "custom_xbrl_mapping+pre2009_history+historical_gvkey_permno_identity+"
        "coverage_fidelity_unmeasured"
    ),
    "FR": (
        "complex_accounting_source_blocked:exact_pension_regime_fields_1980_plus+"
        "crsp_mve_permco_shrcd+pre2009_history+historical_gvkey_permno_permco_identity+"
        "coverage_fidelity_unmeasured"
    ),
    "GrSaleToGrOverhead": (
        "complex_accounting_source_blocked:exact_compustat_sale_xsga_12_24m_lags+"
        "custom_xbrl_mapping+pre2009_history+historical_gvkey_permno_identity+"
        "coverage_fidelity_unmeasured"
    ),
    "OperProfRD": (
        "complex_accounting_source_blocked:exact_compustat_revt_cogs_xsga_xrd_at_ceq+"
        "crsp_mve_shrcd_sic+historical_gvkey_permno_permco_identity+"
        "coverage_fidelity_unmeasured"
    ),
    "RDAbility": (
        "complex_accounting_source_blocked:exact_compustat_xrd_sale_8y_rolling_ols+"
        "five_lags_top_tercile_cross_section+pre2009_history+historical_gvkey_permno_identity+"
        "coverage_fidelity_unmeasured"
    ),
    "ShareRepurchase": (
        "complex_accounting_source_blocked:exact_compustat_prstkc_semantics+"
        "sec_xbrl_tag_equivalence_unvalidated+pre2009_history+historical_gvkey_permno_identity+"
        "coverage_fidelity_unmeasured"
    ),
    "VarCF": (
        "complex_accounting_source_blocked:exact_compustat_ib_dp+crsp_mve_permco+"
        "60m_window_min24+historical_gvkey_permno_permco_identity+"
        "coverage_fidelity_unmeasured"
    ),
    "realestate": (
        "complex_accounting_source_blocked:exact_compustat_property_fields+"
        "crsp_sic_industry_cross_section+pre2009_history+historical_gvkey_permno_identity+"
        "coverage_fidelity_unmeasured"
    ),
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
    return all(token.lower() in text for token in tokens)


def evaluate_complex_accounting_documents(
    documents: Mapping[str, str],
    *,
    access_errors: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Classify the official accounting and identity documents fail-closed."""

    errors = dict(access_errors or {})
    text = {
        name: _visible_text(documents.get(name, ""))
        for name in _REQUIRED_DOCUMENTS
    }
    checks = {
        "sec_fsd": _has_all(text["sec_fsd"], "xbrl", "as filed", "2009"),
        "sec_edgar_apis": _has_all(
            text["sec_edgar_apis"], "xbrl", "custom taxonomies", "2009"
        ),
        "openfigi": _has_all(text["openfigi"], "third-party identifiers", "figi"),
        "crsp": _has_all(text["crsp"], "permno")
        and ("subscriber" in text["crsp"] or "subscription" in text["crsp"])
        and ("over time" in text["crsp"] or "restructur" in text["crsp"]),
        "compustat": _has_all(text["compustat"], "compustat", "standardized")
        and ("point-in-time" in text["compustat"] or "point in time" in text["compustat"]),
    }
    blocked = sorted(name for name, verified in checks.items() if not verified and name in errors)
    unresolved = sorted(
        name for name, verified in checks.items() if not verified and name not in errors
    )
    exact_free = any(
        source["project_use_authorized"]
        and source["exact_for_openap"]
        and source["data_feed"]
        for source in SOURCE_ASSESSMENTS
    )
    return {
        "official_documents_verified": all(checks.values()),
        "source_access_decision_complete": not unresolved,
        "access_blocked_documents": blocked,
        "access_errors": {name: errors[name] for name in blocked},
        "unresolved_documents": unresolved,
        "sec_as_filed_since_2009_verified": checks["sec_fsd"],
        "sec_custom_taxonomies_verified": checks["sec_edgar_apis"],
        "openfigi_not_permno_history": checks["openfigi"]
        and (
            "permno" not in text["openfigi"]
            or "does not publish permno" in text["openfigi"]
            or "does not provide historical permno" in text["openfigi"]
            or "no historical permno" in text["openfigi"]
        ),
        "crsp_subscription_and_permno_verified": checks["crsp"],
        "compustat_standardized_pit_product_verified": checks["compustat"],
        "exact_free_authorized_source_found": exact_free,
        "strict_approved": 0,
    }


def build_complex_accounting_evidence(
    probe: Mapping[str, Any],
    *,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> pd.DataFrame:
    """Build eight signal-specific blockers without promoting partial reconstructions."""

    valid = (
        probe.get("source_access_decision_complete") is True
        and probe.get("unresolved_documents") == []
        and probe.get("formula_sources_verified") is True
        and probe.get("formula_files") == len(COMPLEX_ACCOUNTING_SIGNALS)
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
        raise ValueError("Invalid or incomplete complex accounting evidence")
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
                "score_eligible": False,
                "blocking_reason": COMPLEX_ACCOUNTING_BLOCKERS[signal],
                "evidence_run_url": str(evidence_run_url),
                "evidence_artifact": str(evidence_artifact).strip(),
                "implementation_commit": str(implementation_commit),
            }
            for signal in sorted(COMPLEX_ACCOUNTING_SIGNALS)
        ]
    )


def write_complex_accounting_outputs(
    probe: Mapping[str, Any],
    *,
    output_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> None:
    """Write formula and documentary evidence only; never retain source data."""

    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = build_complex_accounting_evidence(
        probe,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    (output_dir / "complex_accounting_source_probe.json").write_text(
        json.dumps(dict(probe), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    pd.DataFrame(SOURCE_ASSESSMENTS).to_csv(
        output_dir / "complex_accounting_source_assessment.csv", index=False
    )
    requirements = [
        {
            "signal": signal,
            **FORMULA_REQUIREMENTS[signal],
            "formula_path": OPENAP_FORMULA_FILES[signal]["path"],
            "formula_sha256": OPENAP_FORMULA_FILES[signal]["sha256"],
            "formula_commit": OPENAP_COMMIT,
        }
        for signal in sorted(COMPLEX_ACCOUNTING_SIGNALS)
    ]
    pd.DataFrame(requirements).to_csv(
        output_dir / "complex_accounting_formula_requirements.csv", index=False
    )
    evidence.to_csv(output_dir / "complex_accounting_batch_evidence.csv", index=False)
    blocked_docs = ", ".join(probe.get("access_blocked_documents", []))
    report = "\n".join(
        (
            "# OpenAP complex accounting source probe",
            "",
            "- Eight current OpenAP formula files are pinned by commit and SHA-256.",
            "- SEC FSD is as-filed XBRL from 2009, not standardized Compustat history.",
            "- OpenFIGI does not supply the historical PERMNO validity spine.",
            "- Exact CRSP and Compustat inputs remain subscriber or licensed products.",
            f"- Official document access blockers: {blocked_docs or 'none'}.",
            "- No filings, fundamentals or market observations were retained.",
            "- Strict approvals: 0. All eight signals remain fail-closed.",
            "",
        )
    )
    (output_dir / "COMPLEX_ACCOUNTING_SOURCE_PROBE_REPORT.md").write_text(
        report, encoding="utf-8"
    )


def _headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Aurora-OpenAP-181-complex-accounting-probe/1.0 "
            "contact https://github.com/trading-optimizer-lab-org/aurora"
        ),
        "Accept": "text/html,text/plain,application/json",
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


def run_complex_accounting_source_probe(
    *,
    output_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> dict[str, Any]:
    """Verify pinned formulas and official documents without downloading source data."""

    for signal, metadata in sorted(OPENAP_FORMULA_FILES.items()):
        url = (
            "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
            f"{OPENAP_COMMIT}/{metadata['path']}"
        )
        actual = sha256(_fetch(url)).hexdigest()
        if actual != metadata["sha256"]:
            raise ValueError(
                "Pinned OpenAP formula source hash mismatch: "
                f"signal={signal}:expected={metadata['sha256']}:actual={actual}"
            )

    documents: dict[str, str] = {}
    access_errors: dict[str, str] = {}
    for name, url in DOCUMENT_URLS.items():
        try:
            documents[name] = _fetch(url).decode("utf-8", errors="replace")
        except RuntimeError as exc:
            documents[name] = ""
            access_errors[name] = f"{name}:{exc}"
    summary = evaluate_complex_accounting_documents(
        documents, access_errors=access_errors
    )
    if not summary["source_access_decision_complete"]:
        raise ValueError(
            "Complex accounting documentation contract unresolved: "
            + ",".join(summary["unresolved_documents"])
        )
    summary.update(
        {
            "formula_sources_verified": True,
            "formula_commit": OPENAP_COMMIT,
            "formula_files": len(OPENAP_FORMULA_FILES),
            "formula_signals": len(COMPLEX_ACCOUNTING_SIGNALS),
            "raw_source_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    write_complex_accounting_outputs(
        summary,
        output_dir=output_dir,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    return summary


__all__ = [
    "COMPLEX_ACCOUNTING_BLOCKERS",
    "COMPLEX_ACCOUNTING_SIGNALS",
    "DOCUMENT_URLS",
    "FORMULA_REQUIREMENTS",
    "OPENAP_COMMIT",
    "OPENAP_FORMULA_FILES",
    "SOURCE_ASSESSMENTS",
    "build_complex_accounting_evidence",
    "evaluate_complex_accounting_documents",
    "run_complex_accounting_source_probe",
    "write_complex_accounting_outputs",
]
