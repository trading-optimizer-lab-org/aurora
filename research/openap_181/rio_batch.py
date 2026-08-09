"""Pinned formulas and fail-closed source evidence for OpenAP RIO signals."""

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
OPENAP_FORMULA_FILE: dict[str, str] = {
    "path": (
        "Signals/pyCode/Predictors/"
        "ZZ1_RIO_MB_RIO_Disp_RIO_Turnover_RIO_Volatility.py"
    ),
    # The first live GitHub probe reports the digest and this pin is then frozen.
    "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
}

DOCUMENT_URLS = {
    "openap_formula": (
        "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
        f"{OPENAP_COMMIT}/{OPENAP_FORMULA_FILE['path']}"
    ),
    "nagel_paper": (
        "https://bpb-us-w2.wpmucdn.com/voices.uchicago.edu/dist/f/575/files/"
        "2020/07/shortbtm.pdf"
    ),
    "sec_13f": (
        "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
    ),
    "sec_13f_faq": (
        "https://www.sec.gov/rules-regulations/staff-guidance/division-investment-"
        "management-frequently-asked-questions/frequently-asked-questions-about-form-13f"
    ),
    "openfigi": "https://www.openfigi.com/api/documentation",
    "crsp_wrds": (
        "https://wrds-www.wharton.upenn.edu/pages/about/data-vendors/"
        "center-for-research-in-security-prices-crsp/"
    ),
    "compustat_wrds": (
        "https://wrds-www.wharton.upenn.edu/pages/about/data-vendors/"
        "sp-global-market-intelligence/"
    ),
    "ibes_lseg": (
        "https://www.lseg.com/en/data-analytics/financial-data/company-data/"
        "institutional-brokers-estimate-system-ibes"
    ),
}
DOCUMENT_GROUPS = {name: (name,) for name in DOCUMENT_URLS}
_REQUIRED_DOCUMENTS = frozenset(DOCUMENT_GROUPS)
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")

RIO_SIGNALS = frozenset(
    {"RIO_Disp", "RIO_MB", "RIO_Turnover", "RIO_Volatility"}
)
RIO_SHARED_CONTRACT: dict[str, Any] = {
    "ownership_transform": (
        "missing instown_perc becomes zero, then INST is clipped to [0.0001, 0.9999]"
    ),
    "openap_residual_formula": (
        "log(INST/(1-INST)) + 23.66 - 2.89*log(mve_c) + "
        "0.08*log(mve_c)^2"
    ),
    "nagel_published_residual_formula": (
        "log(INST/(1-INST)) + 23.66 - 2.89*log(SZ) + 0.09*log(SZ)^2"
    ),
    "openap_size_square_coefficient": 0.08,
    "nagel_size_square_coefficient": 0.09,
    "rio_lag_months": 6,
    "excluded_size_percentile": 20,
    "size_breakpoint_universe": "NYSE_and_AMEX",
    "rio_buckets": 5,
}


def _requirement(
    formula: str,
    exact_inputs: str,
    timing: str,
    identity: str,
    characteristic_bucket: str,
    *,
    window_months: int,
    minimum_months: int,
) -> dict[str, Any]:
    return {
        "formula": formula,
        "exact_inputs": exact_inputs,
        "timing": timing,
        "identity": identity,
        "characteristic_bucket": characteristic_bucket,
        "window_months": window_months,
        "minimum_months": minimum_months,
    }


RIO_FORMULA_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "RIO_MB": _requirement(
        "cat_RIO when market-to-book mve_permco/(ceq+txditc) is in its top quintile; "
        "missing txditc becomes zero and negative book denominator is missing",
        "TR_13F_instown_perc;CRSP_mve_c;CRSP_mve_permco;Compustat_ceq;Compustat_txditc",
        "six-calendar-month lagged RIO, using only data available by formation month",
        "historical CUSIP/GVKEY/PERMNO links, names, exchanges and delistings",
        "top_quintile",
        window_months=1,
        minimum_months=1,
    ),
    "RIO_Disp": _requirement(
        "cat_RIO when positive unadjusted I/B/E/S FY1 stdev divided by Compustat at is "
        "in the top two quintiles",
        "TR_13F_instown_perc;CRSP_mve_c;IBES_unadjusted_FY1_stdev;Compustat_at",
        "six-calendar-month lagged RIO and point-in-time forecast vintage",
        "historical CUSIP/GVKEY/PERMNO and IBES ticker links",
        "top_40_percent",
        window_months=1,
        minimum_months=1,
    ),
    "RIO_Turnover": _requirement(
        "cat_RIO when monthly CRSP vol/shrout is in its top quintile",
        "TR_13F_instown_perc;CRSP_mve_c;monthly_CRSP_vol;monthly_CRSP_shrout",
        "six-calendar-month lagged RIO; monthly turnover available after month end",
        "historical PERMNO, exchange, names and delistings",
        "top_quintile",
        window_months=1,
        minimum_months=1,
    ),
    "RIO_Volatility": _requirement(
        "cat_RIO when 12-month rolling standard deviation of monthly CRSP ret, minimum "
        "six observations, is in its top quintile",
        "TR_13F_instown_perc;CRSP_mve_c;monthly_CRSP_ret",
        "six-calendar-month lagged RIO; trailing returns only through formation month",
        "historical PERMNO, exchange, names and delistings",
        "top_quintile",
        window_months=12,
        minimum_months=6,
    ),
}

SOURCE_ASSESSMENTS = (
    {
        "source_id": "openap_official",
        "access": "public_pinned_code",
        "history": "current executable OpenAP formula contract",
        "fields": "formula and named WRDS input tables",
        "project_use_authorized": True,
        "exact_for_openap": True,
        "blocker": "code_is_not_a_current_data_feed_and_differs_from_paper_coefficient",
    },
    {
        "source_id": "nagel_2005",
        "access": "public_author_paper",
        "history": "research sample 1980-2003",
        "fields": "published RIO equation, lags, universe and portfolio sorts",
        "project_use_authorized": True,
        "exact_for_openap": False,
        "blocker": "published_square_coefficient_0_09_differs_from_openap_0_08",
    },
    {
        "source_id": "sec_13f",
        "access": "official_public_bulk_and_filings",
        "history": "structured XML from May 2013; older filings require text parsing",
        "fields": "manager, CUSIP, shares, value, filing and report dates, amendments",
        "project_use_authorized": True,
        "exact_for_openap": False,
        "blocker": (
            "not_cleaned_TR_13F_instown_perc_and_confidential_amended_holdings_plus_"
            "historical_security_denominator_remain"
        ),
    },
    {
        "source_id": "openfigi",
        "access": "official_public_mapping_api",
        "history": "current identifier mappings",
        "fields": "CUSIP and other third-party identifiers to FIGI metadata",
        "project_use_authorized": True,
        "exact_for_openap": False,
        "historical_permno_bridge": False,
        "blocker": "no_historical_permno_or_cusip_validity_intervals",
    },
    {
        "source_id": "crsp_stock_commercial",
        "access": "institutional_vendor_license",
        "history": "long US security history",
        "fields": "PERMNO, returns, volume, shares, market equity, exchanges and delistings",
        "project_use_authorized": False,
        "exact_for_openap": True,
        "blocker": "commercial_subscription_required",
    },
    {
        "source_id": "compustat_commercial",
        "access": "institutional_vendor_license",
        "history": "long point-in-time company fundamentals",
        "fields": "at, ceq, txditc and GVKEY history",
        "project_use_authorized": False,
        "exact_for_openap": True,
        "blocker": "commercial_subscription_required",
    },
    {
        "source_id": "lseg_ibes_commercial",
        "access": "institutional_vendor_license",
        "history": "historical unadjusted analyst forecast vintages",
        "fields": "FY1 forecast stdev, period indicator and IBES identifiers",
        "project_use_authorized": False,
        "exact_for_openap": True,
        "blocker": "commercial_subscription_and_historical_link_required",
    },
    {
        "source_id": "wrds_linking_suite",
        "access": "institutional_vendor_license",
        "history": "historical CRSP/Compustat/IBES links",
        "fields": "CUSIP, GVKEY, IBES ticker and PERMNO validity intervals",
        "project_use_authorized": False,
        "exact_for_openap": True,
        "blocker": "wrds_and_underlying_vendor_licenses_required",
    },
)

_COMMON_BLOCKER = (
    "openap_0.08_vs_nagel_0.09+exact_TR13F_instown_perc+six_month_permno_"
    "identity+nyse_amex_size_breakpoints+full_coverage_unavailable_free"
)
RIO_BLOCKERS = {
    "RIO_MB": (
        "rio_source_blocked:" + _COMMON_BLOCKER + "+compustat_ceq_txditc+crsp_mve_permco"
    ),
    "RIO_Disp": (
        "rio_source_blocked:" + _COMMON_BLOCKER
        + "+pit_unadjusted_ibes_fy1_stdev+ibes_permno_link+compustat_at"
    ),
    "RIO_Turnover": (
        "rio_source_blocked:" + _COMMON_BLOCKER + "+monthly_crsp_vol_shrout"
    ),
    "RIO_Volatility": (
        "rio_source_blocked:" + _COMMON_BLOCKER
        + "+twelve_month_crsp_returns_minimum_six"
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


def evaluate_rio_source_documents(
    documents: Mapping[str, str],
    *,
    access_errors: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Classify primary RIO formula and data-source documents fail-closed."""

    errors = dict(access_errors or {})
    text = {
        name: _visible_text(documents.get(name, "")) for name in _REQUIRED_DOCUMENTS
    }
    blocked = sorted(
        name for name in _REQUIRED_DOCUMENTS if not text[name] and name in errors
    )
    unresolved = sorted(
        name for name in _REQUIRED_DOCUMENTS if not text[name] and name not in errors
    )
    openap_inputs = _has_all(
        text["openap_formula"], "tr_13f", "permno", "compustat", "crsp", "0.08"
    ) and _has_all(text["openap_formula"], "ibes", "six calendar month")
    nagel_formula = _has_all(
        text["nagel_paper"], "-23.66", "2.89", "0.09", "20th", "t-2"
    )
    sec_history = _has_all(text["sec_13f"], "may 2013", "xml", "quarter")
    sec_lag = _has_all(text["sec_13f_faq"], "45 days", "quarter end") and (
        "confidential" in text["sec_13f_faq"]
    )
    openfigi_gap = _has_all(text["openfigi"], "cusip", "figi") and (
        "does not provide historical permno" in text["openfigi"]
        or "no historical permno" in text["openfigi"]
    )
    crsp = _has_all(text["crsp_wrds"], "permno", "returns", "volume", "license")
    compustat = _has_all(
        text["compustat_wrds"], "total assets", "common equity", "deferred taxes", "license"
    )
    ibes = _has_all(
        text["ibes_lseg"], "unadjusted", "forecast", "standard deviation", "licensed"
    )
    checks = (
        openap_inputs,
        nagel_formula,
        sec_history,
        sec_lag,
        openfigi_gap,
        crsp,
        compustat,
        ibes,
    )
    return {
        "official_documents_verified": not blocked and not unresolved and all(checks),
        "source_access_decision_complete": not unresolved,
        "access_blocked_documents": blocked,
        "access_errors": {name: errors[name] for name in blocked},
        "unresolved_documents": unresolved,
        "openap_inputs_verified": openap_inputs,
        "nagel_formula_verified": nagel_formula,
        "openap_nagel_coefficient_discrepancy_verified": openap_inputs and nagel_formula,
        "sec_structured_history_starts_2013": sec_history,
        "sec_reporting_lag_and_confidentiality_verified": sec_lag,
        "openfigi_not_permno_history": openfigi_gap,
        "commercial_exact_inputs_verified": crsp and compustat and ibes,
        "exact_free_authorized_source_found": False,
        "strict_approved": 0,
    }


def build_rio_batch_evidence(
    probe: Mapping[str, Any],
    *,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> pd.DataFrame:
    """Build per-signal RIO evidence without promoting incomplete data routes."""

    valid = (
        probe.get("source_access_decision_complete") is True
        and probe.get("unresolved_documents") == []
        and probe.get("formula_sources_verified") is True
        and probe.get("formula_files") == 1
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
        raise ValueError("Invalid or incomplete RIO probe evidence")
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
                "blocking_reason": RIO_BLOCKERS[signal],
                "evidence_run_url": str(evidence_run_url),
                "evidence_artifact": str(evidence_artifact).strip(),
                "implementation_commit": str(implementation_commit),
            }
            for signal in sorted(RIO_SIGNALS)
        ]
    )


def write_rio_source_probe_outputs(
    probe: Mapping[str, Any],
    *,
    output_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> None:
    """Write formula and source metadata only, never holdings or market data."""

    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = build_rio_batch_evidence(
        probe,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    (output_dir / "rio_source_probe.json").write_text(
        json.dumps(dict(probe), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    pd.DataFrame(SOURCE_ASSESSMENTS).to_csv(
        output_dir / "rio_source_assessment.csv", index=False
    )
    rows = [
        {
            "signal": signal,
            **RIO_SHARED_CONTRACT,
            **requirement,
            "formula_path": OPENAP_FORMULA_FILE["path"],
            "formula_sha256": OPENAP_FORMULA_FILE["sha256"],
            "formula_commit": OPENAP_COMMIT,
        }
        for signal, requirement in sorted(RIO_FORMULA_REQUIREMENTS.items())
    ]
    pd.DataFrame(rows).to_csv(output_dir / "rio_formula_requirements.csv", index=False)
    evidence.to_csv(output_dir / "rio_batch_evidence.csv", index=False)
    blocked_docs = ", ".join(probe.get("access_blocked_documents", []))
    report = "\n".join(
        (
            "# OpenAP RIO source probe",
            "",
            "- One pinned OpenAP program defines four RIO signal contracts.",
            "- OpenAP uses a 0.08 squared-size coefficient; Nagel (2005) publishes 0.09.",
            "- Official structured SEC 13F bulk history starts in May 2013.",
            "- Raw 13F plus OpenFIGI is not the cleaned TR_13F/PERMNO panel used by OpenAP.",
            "- Exact CRSP, Compustat and I/B/E/S inputs remain licensed products.",
            f"- Official document access blockers: {blocked_docs or 'none'}.",
            "- No holdings, prices, returns, fundamentals or forecasts were retained.",
            "- Strict approvals: 0. All four signals remain fail-closed.",
            "",
        )
    )
    (output_dir / "RIO_SOURCE_PROBE_REPORT.md").write_text(report, encoding="utf-8")


def _headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Aurora-OpenAP-181-RIO-source-probe/1.0 "
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


def run_rio_source_probe(
    *,
    output_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> dict[str, Any]:
    """Verify the pinned formula and official documents without source data."""

    payload = _fetch(
        "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
        f"{OPENAP_COMMIT}/{OPENAP_FORMULA_FILE['path']}"
    )
    actual = sha256(payload).hexdigest()
    if actual != OPENAP_FORMULA_FILE["sha256"]:
        raise ValueError(
            "Pinned OpenAP RIO formula source hash mismatch: "
            f"expected={OPENAP_FORMULA_FILE['sha256']}:actual={actual}"
        )

    documents: dict[str, str] = {}
    access_errors: dict[str, str] = {}
    for document_name, source_names in DOCUMENT_GROUPS.items():
        payloads: list[str] = []
        errors: list[str] = []
        for source_name in source_names:
            try:
                payloads.append(
                    _fetch(DOCUMENT_URLS[source_name]).decode(
                        "utf-8", errors="replace"
                    )
                )
            except RuntimeError as exc:
                errors.append(f"{source_name}:{exc}")
        documents[document_name] = " ".join(payloads)
        if errors:
            access_errors[document_name] = ";".join(errors)
    summary = evaluate_rio_source_documents(documents, access_errors=access_errors)
    if not summary["source_access_decision_complete"]:
        raise ValueError(
            "Official RIO documentation contract unresolved: "
            + ",".join(summary["unresolved_documents"])
        )
    summary.update(
        {
            "formula_sources_verified": True,
            "formula_commit": OPENAP_COMMIT,
            "formula_files": 1,
            "formula_signals": len(RIO_SIGNALS),
            "raw_source_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    write_rio_source_probe_outputs(
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
    "OPENAP_FORMULA_FILE",
    "RIO_BLOCKERS",
    "RIO_FORMULA_REQUIREMENTS",
    "RIO_SHARED_CONTRACT",
    "RIO_SIGNALS",
    "SOURCE_ASSESSMENTS",
    "build_rio_batch_evidence",
    "evaluate_rio_source_documents",
    "run_rio_source_probe",
    "write_rio_source_probe_outputs",
]
