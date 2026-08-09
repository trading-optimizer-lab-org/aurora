"""Pinned formulas and fail-closed source evidence for microstructure signals."""

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
    "openap_repo": (
        "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
        f"{OPENAP_COMMIT}/README.md"
    ),
    "pin_authors": "https://edwinhu.github.io/pin/",
    "twelve_pricing": "https://twelvedata.com/pricing",
    "twelve_history": (
        "https://support.twelvedata.com/en/articles/"
        "5656039-how-to-get-historical-prices"
    ),
    "twelve_us_equities": (
        "https://support.twelvedata.com/en/articles/"
        "9935903-us-equities-market-data"
    ),
    "nyse_taq": "https://www.nyse.com/data-products/catalog/daily-taq",
    "crsp_wrds": (
        "https://wrds-www.wharton.upenn.edu/pages/about/data-vendors/"
        "center-for-research-in-security-prices-crsp/"
    ),
}
DOCUMENT_GROUPS = {name: (name,) for name in DOCUMENT_URLS}
_REQUIRED_DOCUMENTS = frozenset(DOCUMENT_GROUPS)
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")

OPENAP_FORMULA_FILES: dict[str, dict[str, str]] = {
    "BidAskSpread_predictor": {
        "path": "Signals/pyCode/Predictors/BidAskSpread.py",
        "sha256": "ec53918eccd8117256dfc55acdaac97b784a9b47a396809a7db04def88490039",
    },
    "BidAskSpread_prep": {
        "path": "Signals/pyCode/PrepScripts/corwin_schultz_edit.sas",
        # The live GitHub probe reports the actual digest if this pin ever drifts.
        "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    },
    "ProbInformedTrading": {
        "path": "Signals/pyCode/Predictors/ProbInformedTrading.py",
        "sha256": "0ce90bf2d8dc086ae6b39c7941c7c6b4e432e93cf87676fddf0f098c2fc175ab",
    },
    "zerotrade": {
        "path": (
            "Signals/pyCode/Predictors/"
            "ZZ1_zerotrade_zerotradeAlt1_zerotradeAlt12.py"
        ),
        "sha256": "2d2ee47c3c695f21b114a7a13548d07eb517a08a6e0539dc2282743edf95498b",
    },
}

MICROSTRUCTURE_FORMULA_FILES = {
    "BidAskSpread": ("BidAskSpread_predictor", "BidAskSpread_prep"),
    "ProbInformedTrading": ("ProbInformedTrading",),
    "zerotrade1M": ("zerotrade",),
    "zerotrade6M": ("zerotrade",),
    "zerotrade12M": ("zerotrade",),
}
MICROSTRUCTURE_SIGNALS = frozenset(MICROSTRUCTURE_FORMULA_FILES)


def _requirement(
    formula: str,
    exact_inputs: str,
    timing: str,
    identity: str,
    *,
    window_months: int,
    deflator: int | None,
) -> dict[str, Any]:
    return {
        "formula": formula,
        "exact_inputs": exact_inputs,
        "timing": timing,
        "identity": identity,
        "window_months": window_months,
        "deflator": deflator,
    }


MICROSTRUCTURE_FORMULA_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "BidAskSpread": _requirement(
        "Corwin-Schultz two-day high-low spread with CRSP no-trade screens, overnight "
        "adjustment, negative daily estimates set to zero, monthly mean and minimum 12 "
        "daily observations",
        "crsp_dsf_permno;date;bidlo;askhi;prc;vol",
        "month formed only after month end; no value may be available before its final input",
        "historical PERMNO security master including names, share codes and delistings",
        window_months=1,
        deflator=None,
    ),
    "ProbInformedTrading": _requirement(
        "PIN=(a*u)/(a*u+es+eb), set missing for the top 50% of monthly market equity",
        "pin_a;pin_u;pin_es;pin_eb;monthly_mve_c",
        "year t PIN parameters forecast year t+1; no GPIN or OWR substitution",
        "author PERMNO to historical CRSP security-month and current-universe bridge",
        window_months=12,
        deflator=None,
    ),
    "zerotrade1M": _requirement(
        "one-month lag of (zero-volume days + (1/sum turnover)/480000) * 21/ndays",
        "daily_crsp_permno;date;vol;pit_shrout;complete_trading_day_rows",
        "one complete month, shifted by one month",
        "historical PERMNO and point-in-time shares outstanding",
        window_months=1,
        deflator=480_000,
    ),
    "zerotrade6M": _requirement(
        "one-month lag of (six-month zero-volume days + (1/sum turnover)/11000) * "
        "126/ndays",
        "daily_crsp_permno;date;vol;pit_shrout;complete_trading_day_rows",
        "six complete monthly observations, then shifted by one month",
        "historical PERMNO and point-in-time shares outstanding",
        window_months=6,
        deflator=11_000,
    ),
    "zerotrade12M": _requirement(
        "one-month lag of (twelve-month zero-volume days + (1/sum turnover)/11000) * "
        "252/ndays",
        "daily_crsp_permno;date;vol;pit_shrout;complete_trading_day_rows",
        "twelve complete monthly observations, then shifted by one month",
        "historical PERMNO and point-in-time shares outstanding",
        window_months=12,
        deflator=11_000,
    ),
}


SOURCE_ASSESSMENTS = (
    {
        "source_id": "openap_official",
        "access": "public_code_and_reference_data",
        "history": "published signal-specific samples and pinned formula code",
        "fields": "formula wrappers, WRDS prep code and historical reference values",
        "project_use_authorized": True,
        "exact_for_openap": True,
        "blocker": "not_a_current_data_feed_and_requires_wrds_inputs",
    },
    {
        "source_id": "hvidkjaer_pin_archive",
        "access": "public_web_archive_download_with_unverified_reuse_rights",
        "history": "author PIN estimates for 1983-2001 referenced by OpenAP",
        "fields": "yearly PIN parameters keyed by historical security identifiers",
        "project_use_authorized": False,
        "exact_for_openap": True,
        "current_coverage": False,
        "blocker": "ends_2001_and_automation_reuse_rights_not_explicit",
    },
    {
        "source_id": "edwin_hu_pin",
        "access": "public_github_and_zenodo",
        "history": "exact legacy PIN 1993-2012; GPIN and OWR 2003-2024",
        "fields": "PERMNO-year PIN, GPIN and OWR model parameters",
        "project_use_authorized": True,
        "exact_for_openap": True,
        "exact_current_for_openap": False,
        "blocker": "exact_pin_ends_2012_and_gpin_owr_are_not_substitutes",
    },
    {
        "source_id": "twelve_data_basic",
        "access": "free_account_api_key",
        "history": "daily OHLCV from first trading date for most active symbols",
        "fields": "ticker, exchange, MIC and daily OHLCV",
        "project_use_authorized": True,
        "exact_for_openap": False,
        "blocker": (
            "no_permno_history_delistings_pit_shrout_or_proven_zero_volume_row_semantics"
        ),
    },
    {
        "source_id": "sec_edgar",
        "access": "official_api_bulk_and_filings",
        "history": "issuer filings and XBRL shares facts",
        "fields": "CIK, acceptance time and issuer-reported shares facts",
        "project_use_authorized": True,
        "exact_for_openap": False,
        "blocker": "filing_shares_are_not_daily_crsp_shrout_or_a_security_calendar",
    },
    {
        "source_id": "crsp_stock_commercial",
        "access": "institutional_vendor_license",
        "history": "long US security history with permanent identifiers",
        "fields": "PERMNO, bidlo, askhi, prc, vol, shrout, names and delistings",
        "project_use_authorized": False,
        "exact_for_openap": True,
        "blocker": "commercial_subscription_required",
    },
    {
        "source_id": "nyse_taq_commercial",
        "access": "commercial_subscription_or_historical_purchase",
        "history": "consolidated US trades and quotes from 1993",
        "fields": "trades, quotes, NBBO, conditions, timestamps and master records",
        "project_use_authorized": False,
        "exact_for_openap": False,
        "blocker": "license_required_and_not_needed_for_daily_crsp_formula_equivalence",
    },
    {
        "source_id": "wrds_linking_suite",
        "access": "institutional_vendor_license",
        "history": "links among CRSP, Compustat and TAQ products",
        "fields": "historical commercial identifier links",
        "project_use_authorized": False,
        "exact_for_openap": True,
        "blocker": "wrds_and_each_underlying_vendor_license_required",
    },
)


MICROSTRUCTURE_BLOCKERS = {
    "BidAskSpread": (
        "microstructure_source_blocked:exact_crsp_bidlo_askhi_prc_volume_semantics+"
        "permno_history+delistings+full_coverage_unavailable_free"
    ),
    "ProbInformedTrading": (
        "microstructure_source_blocked:exact_pin_parameters_end_2012+current_exact_pin+"
        "historical_permno_to_current_security_identity_unavailable"
    ),
    "zerotrade1M": (
        "microstructure_source_blocked:daily_crsp_zero_volume_rows+pit_shrout+"
        "permno_calendar+480000_one_month_adjustment_unavailable_free"
    ),
    "zerotrade6M": (
        "microstructure_source_blocked:daily_crsp_zero_volume_rows+pit_shrout+"
        "permno_calendar+11000_six_month_adjustment_unavailable_free"
    ),
    "zerotrade12M": (
        "microstructure_source_blocked:daily_crsp_zero_volume_rows+pit_shrout+"
        "permno_calendar+11000_twelve_month_adjustment_unavailable_free"
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
    return all(token in text for token in tokens)


def evaluate_microstructure_source_documents(
    documents: Mapping[str, str],
    *,
    access_errors: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluate primary documents while classifying every access outcome."""

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

    openap_wrds = _has_all(text["openap_repo"], "wrds", "prep scripts", "stock-level")
    pin_legacy = _has_all(text["pin_authors"], "1993-2012", "pin", "permno")
    pin_non_equivalence = _has_all(
        text["pin_authors"], "gpin", "owr", "2003-2024"
    )
    twelve_free = _has_all(text["twelve_pricing"], "basic", "free", "800") and (
        "internal non-display" in text["twelve_pricing"]
    )
    twelve_daily = _has_all(
        text["twelve_history"], "daily", "ohlcv", "first trading date"
    )
    twelve_limited_intraday = "intraday" in text["twelve_history"] and (
        "limited" in text["twelve_history"]
        or "few months" in text["twelve_history"]
        or "few years" in text["twelve_history"]
    )
    twelve_us = _has_all(
        text["twelve_us_equities"], "listed us equities", "otc"
    )
    nyse_taq = _has_all(text["nyse_taq"], "trades", "quotes", "1993") and (
        "purchase" in text["nyse_taq"] or "license" in text["nyse_taq"]
    )
    crsp_exact = _has_all(
        text["crsp_wrds"], "permno", "bid low", "ask high", "shares outstanding"
    ) and ("subscription" in text["crsp_wrds"] or "license" in text["crsp_wrds"])
    checks = (
        openap_wrds,
        pin_legacy,
        pin_non_equivalence,
        twelve_free,
        twelve_daily,
        twelve_limited_intraday,
        twelve_us,
        nyse_taq,
        crsp_exact,
    )
    return {
        "official_documents_verified": not blocked and not unresolved and all(checks),
        "source_access_decision_complete": not unresolved,
        "access_blocked_documents": blocked,
        "access_errors": {name: errors[name] for name in blocked},
        "unresolved_documents": unresolved,
        "openap_wrds_dependency_verified": openap_wrds,
        "pin_exact_legacy_through_2012_verified": pin_legacy,
        "pin_current_models_are_not_exact_pin": pin_non_equivalence,
        "twelve_daily_ohlcv_free_authorized": twelve_free and twelve_daily and twelve_us,
        "twelve_intraday_history_limited": twelve_limited_intraday,
        "twelve_permanent_identity_verified": False,
        "twelve_zero_volume_calendar_semantics_verified": False,
        "crsp_commercial_exact_inputs_verified": crsp_exact,
        "nyse_taq_commercial_verified": nyse_taq,
        "exact_free_authorized_source_found": False,
        "strict_approved": 0,
    }


def build_microstructure_batch_evidence(
    probe: Mapping[str, Any],
    *,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> pd.DataFrame:
    """Build formula evidence that cannot promote a source-blocked signal."""

    valid = (
        probe.get("source_access_decision_complete") is True
        and probe.get("unresolved_documents") == []
        and probe.get("formula_sources_verified") is True
        and probe.get("formula_files") == len(OPENAP_FORMULA_FILES)
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
        raise ValueError("Invalid or incomplete microstructure probe evidence")
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
                "blocking_reason": MICROSTRUCTURE_BLOCKERS[signal],
                "evidence_run_url": str(evidence_run_url),
                "evidence_artifact": str(evidence_artifact).strip(),
                "implementation_commit": str(implementation_commit),
            }
            for signal in sorted(MICROSTRUCTURE_SIGNALS)
        ]
    )


def write_microstructure_source_probe_outputs(
    probe: Mapping[str, Any],
    *,
    output_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> None:
    """Write formula and documentary metadata only, never trades or price data."""

    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = build_microstructure_batch_evidence(
        probe,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    (output_dir / "microstructure_source_probe.json").write_text(
        json.dumps(dict(probe), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    pd.DataFrame(SOURCE_ASSESSMENTS).to_csv(
        output_dir / "microstructure_source_assessment.csv", index=False
    )
    formula_rows = []
    for signal, requirement in sorted(MICROSTRUCTURE_FORMULA_REQUIREMENTS.items()):
        file_names = MICROSTRUCTURE_FORMULA_FILES[signal]
        formula_rows.append(
            {
                "signal": signal,
                **requirement,
                "formula_paths": "|".join(
                    OPENAP_FORMULA_FILES[name]["path"] for name in file_names
                ),
                "formula_sha256": "|".join(
                    OPENAP_FORMULA_FILES[name]["sha256"] for name in file_names
                ),
                "formula_commit": OPENAP_COMMIT,
            }
        )
    pd.DataFrame(formula_rows).to_csv(
        output_dir / "microstructure_formula_requirements.csv", index=False
    )
    evidence.to_csv(output_dir / "microstructure_batch_evidence.csv", index=False)
    blocked_docs = ", ".join(probe.get("access_blocked_documents", []))
    report = "\n".join(
        (
            "# OpenAP microstructure source probe",
            "",
            "- Four pinned OpenAP formula files define five signal contracts.",
            "- BidAskSpread requires the CRSP-specific Corwin-Schultz prep semantics.",
            "- Exact public PIN parameters end in 2012; GPIN and OWR are not substitutes.",
            "- Free daily OHLCV does not prove zero-volume rows, PIT shares or PERMNO history.",
            "- CRSP and NYSE TAQ remain commercial reference products.",
            f"- Official document access blockers: {blocked_docs or 'none'}.",
            "- No raw prices, volume, trades, quotes or PIN parameter records were retained.",
            "- Strict approvals: 0. All five signals remain fail-closed.",
            "",
        )
    )
    (output_dir / "MICROSTRUCTURE_SOURCE_PROBE_REPORT.md").write_text(
        report, encoding="utf-8"
    )


def _headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Aurora-OpenAP-181-microstructure-source-probe/1.0 "
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


def run_microstructure_source_probe(
    *,
    output_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> dict[str, Any]:
    """Verify pinned formulas and live official documentation without source data."""

    mismatches: list[str] = []
    for name, source in OPENAP_FORMULA_FILES.items():
        payload = _fetch(
            "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
            f"{OPENAP_COMMIT}/{source['path']}"
        )
        actual = sha256(payload).hexdigest()
        if actual != source["sha256"]:
            mismatches.append(
                f"{name}:expected={source['sha256']}:actual={actual}"
            )
    if mismatches:
        raise ValueError(
            "Pinned OpenAP microstructure formula source hash mismatch: "
            + ";".join(mismatches)
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
    summary = evaluate_microstructure_source_documents(
        documents, access_errors=access_errors
    )
    if not summary["source_access_decision_complete"]:
        raise ValueError(
            "Official microstructure documentation contract unresolved: "
            + ",".join(summary["unresolved_documents"])
        )
    summary.update(
        {
            "formula_sources_verified": True,
            "formula_commit": OPENAP_COMMIT,
            "formula_files": len(OPENAP_FORMULA_FILES),
            "formula_signals": len(MICROSTRUCTURE_SIGNALS),
            "raw_source_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    write_microstructure_source_probe_outputs(
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
    "MICROSTRUCTURE_BLOCKERS",
    "MICROSTRUCTURE_FORMULA_FILES",
    "MICROSTRUCTURE_FORMULA_REQUIREMENTS",
    "MICROSTRUCTURE_SIGNALS",
    "OPENAP_COMMIT",
    "OPENAP_FORMULA_FILES",
    "SOURCE_ASSESSMENTS",
    "build_microstructure_batch_evidence",
    "evaluate_microstructure_source_documents",
    "run_microstructure_source_probe",
    "write_microstructure_source_probe_outputs",
]
