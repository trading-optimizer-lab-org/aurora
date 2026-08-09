"""Pinned source research and fail-closed evidence for OpenAP option signals."""

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
OPENAP_FORMULA_SOURCES = {
    "CPVolSpread": {
        "path": "Signals/pyCode/Predictors/CPVolSpread.py",
        "sha256": "f7d0fbe74fa3216edd5c76296aafe58de02683b65776e19a682dd15043a99e2b",
    },
    "RIVolSpread": {
        "path": "Signals/pyCode/Predictors/ZZ1_RIVolSpread.py",
        "sha256": "9093acd8f0986b0c1851ced0e6d42f26a383d31dc969661b7c8d328287d38a4d",
    },
    "SmileSlope": {
        "path": "Signals/pyCode/Predictors/SmileSlope.py",
        "sha256": "85cebddf7e3cc8600d79bad3ebaf8a4fdcb3a35da541d27431c8d32255af754b",
    },
    "skew1": {
        "path": "Signals/pyCode/Predictors/skew1.py",
        "sha256": "7876eb7a57e27f00bd8b95eb1505a20133ca0e86922456b8bd95a39147c9f9bc",
    },
    "dCPVolSpread": {
        "path": "Signals/pyCode/Predictors/dCPVolSpread.py",
        "sha256": "3c8161ddb2a638ff372486e89f2a13e84365b6419eb05cd9c4b5be20f8007de9",
    },
    "dVolCall": {
        "path": "Signals/pyCode/Predictors/dVolCall.py",
        "sha256": "090e2495275d6084541e5077b965929650f6b4ebf9c2832e38a78ed0786f6521",
    },
    "dVolPut": {
        "path": "Signals/pyCode/Predictors/dVolPut.py",
        "sha256": "d1670ee98dfa7a1de2060274a8194d25c59a46d55025ca5b279c99eb54698a8e",
    },
    "OptionVolume1": {
        "path": "Signals/pyCode/Predictors/ZZ1_OptionVolume1_OptionVolume2.py",
        "sha256": "4cf760ad9e67c34671506d426f19c365e673c7b34b2c53298afeac7d92d71d26",
    },
    "OptionVolume2": {
        "path": "Signals/pyCode/Predictors/ZZ1_OptionVolume1_OptionVolume2.py",
        "sha256": "4cf760ad9e67c34671506d426f19c365e673c7b34b2c53298afeac7d92d71d26",
    },
}
OPTION_SIGNALS = frozenset(OPENAP_FORMULA_SOURCES)

OPTION_FORMULA_REQUIREMENTS: dict[str, dict[str, str]] = {
    "CPVolSpread": {
        "formula": "ATM call implied volatility minus ATM put implied volatility",
        "exact_inputs": "historical_atm_call_iv;historical_atm_put_iv",
        "history": "OpenAP study sample 1996-2004",
    },
    "RIVolSpread": {
        "formula": "past-30-day realized volatility minus ATM implied volatility",
        "exact_inputs": "daily_crsp_returns;historical_atm_iv;historical_identity",
        "history": "OpenAP study sample 1996-2004",
    },
    "SmileSlope": {
        "formula": "month-end 30-day put IV at delta -0.50 minus call IV at delta 0.50",
        "exact_inputs": "optionmetrics_vsurfd;30_day_surface;delta_surface;month_end",
        "history": "OpenAP study sample 1996-2005",
    },
    "skew1": {
        "formula": "nearest-above-one put moneyness IV minus nearest-below-one call moneyness IV",
        "exact_inputs": (
            "raw_contract_history;10_to_60_dte;moneyness;price;volume;open_interest;"
            "implied_volatility;underlying_price;historical_identity"
        ),
        "history": "OpenAP study sample 1996-2005",
    },
    "dVolCall": {
        "formula": "first difference of 30-day call implied volatility at delta 0.50",
        "exact_inputs": "optionmetrics_vsurfd;30_day_delta_surface;monthly_first_difference",
        "history": "OpenAP study sample 1996-2011",
    },
    "dVolPut": {
        "formula": "first difference of 30-day put implied volatility at absolute delta 0.50",
        "exact_inputs": "optionmetrics_vsurfd;30_day_delta_surface;monthly_first_difference",
        "history": "OpenAP study sample 1996-2011",
    },
    "dCPVolSpread": {
        "formula": "pinned OpenAP difference of dVolCall and dVolPut",
        "exact_inputs": "exact_dVolCall;exact_dVolPut;pinned_formula_orientation",
        "history": "OpenAP study sample 1996-2011",
    },
    "OptionVolume1": {
        "formula": "monthly volume over all puts and calls divided by monthly stock volume",
        "exact_inputs": "all_exchange_option_volume;crsp_stock_volume;historical_identity",
        "history": "OpenAP study sample 1996-2010",
    },
    "OptionVolume2": {
        "formula": "OptionVolume1 divided by its mean from t-6 to t-1",
        "exact_inputs": "exact_OptionVolume1;t_minus_6_to_t_minus_1_history",
        "history": "OpenAP study sample 1996-2010",
    },
}

DOCUMENT_URLS = {
    "marketdata_pricing": "https://www.marketdata.app/pricing/",
    "marketdata_terms": "https://www.marketdata.app/terms/",
    "massive_pricing": "https://massive.com/options",
    "massive_terms": "https://massive.com/legal/market-data-terms-of-service",
    "tradier_history": (
        "https://docs.tradier.com/reference/brokerage-api-markets-get-history"
    ),
    "tradier_rights": "https://docs.tradier.com/docs/faq",
    "occ_data": (
        "https://www.theocc.com/market-data/market-data-reports/"
        "volume-and-open-interest/volume-query"
    ),
    "occ_terms": "https://www.theocc.com/specialpages/legal/terms-and-conditions",
    "cboe_delayed": "https://www.cboe.com/delayed_quotes/API/quote_table/",
    "cboe_volume": (
        "https://www.cboe.com/us/options/market_statistics/historical_data/"
    ),
    "alpha_vantage": "https://www.alphavantage.co/documentation/",
    "optionmetrics": "https://optionmetrics.com/data-products/",
    "wrds": "https://wrds-www.wharton.upenn.edu/pages/grid-items/option-suite-wrds/",
}

SOURCE_ASSESSMENTS = (
    {
        "source_id": "marketdata_options_free",
        "access": "free_account",
        "history": "one rolling year of historical chains",
        "fields": "chain,IV,delta,volume,open_interest",
        "project_use_authorized": False,
        "exact_for_openap": False,
        "blocker": "history_too_short_and_research_requires_professional_permission",
    },
    {
        "source_id": "massive_options_basic",
        "access": "free_individual_account",
        "history": "two years",
        "fields": "contract_reference,OHLCV_aggregates",
        "project_use_authorized": False,
        "exact_for_openap": False,
        "blocker": "no_historical_IV_or_open_interest_and_individual_use_only",
    },
    {
        "source_id": "tradier_personal_api",
        "access": "free_brokerage_account",
        "history": "contract OHLCV by known OCC symbol",
        "fields": "OHLCV,current_chain,current_greeks_outside_sandbox",
        "project_use_authorized": False,
        "exact_for_openap": False,
        "blocker": "no_historical_chain_surface_IV_open_interest_or_permanent_identity",
    },
    {
        "source_id": "occ_option_volume",
        "access": "public_reference_only",
        "history": "24 rolling months",
        "fields": "issuer_call_put_volume",
        "project_use_authorized": False,
        "exact_for_openap": False,
        "blocker": "website_terms_prohibit_automated_systems_and_history_is_too_short",
    },
    {
        "source_id": "cboe_delayed_options",
        "access": "manual_delayed_table",
        "history": "current delayed snapshot",
        "fields": "chain,IV,greeks,volume,open_interest",
        "project_use_authorized": False,
        "exact_for_openap": False,
        "blocker": "automated_extraction_explicitly_prohibited_and_no_history",
    },
    {
        "source_id": "cboe_public_aggregate",
        "access": "public_aggregate_download",
        "history": "dataset dependent",
        "fields": "Cboe_exchange_option_volume",
        "project_use_authorized": True,
        "exact_for_openap": False,
        "blocker": "not_a_full_market_chain_or_volatility_surface",
    },
    {
        "source_id": "alpha_vantage_options_premium",
        "access": "paid_api",
        "history": "15+ years since 2008",
        "fields": "historical_chain,IV,greeks",
        "project_use_authorized": False,
        "exact_for_openap": False,
        "blocker": "premium_not_zero_cost_and_history_starts_after_openap_sample_start",
    },
    {
        "source_id": "optionmetrics_ivydb_us",
        "access": "commercial_subscription",
        "history": "complete daily history since January 1996",
        "fields": "prices,volume,open_interest,IV,greeks,surface,permanent_identity",
        "project_use_authorized": False,
        "exact_for_openap": True,
        "blocker": "commercial_subscription_required",
    },
)

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data)


def _visible_text(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(str(value))
    text = " ".join(parser.parts).lower()
    for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        text = text.replace(dash, "-")
    return " ".join(text.replace("\xa0", " ").split())


def _has_all(text: str, *tokens: str) -> bool:
    return all(token in text for token in tokens)


def evaluate_options_source_documents(
    documents: Mapping[str, str],
) -> dict[str, Any]:
    """Evaluate primary-source documentation without treating it as data coverage."""

    required = {
        "marketdata",
        "massive",
        "tradier_history",
        "tradier_rights",
        "occ_data",
        "occ_terms",
        "cboe_delayed",
        "cboe_volume",
        "alpha_vantage",
        "optionmetrics",
        "wrds",
    }
    missing = required - set(documents)
    if missing:
        raise ValueError(f"Missing options source documents: {sorted(missing)}")
    text = {key: _visible_text(documents[key]) for key in required}
    checks = {
        "marketdata": (
            ("1 year" in text["marketdata"] or "one year" in text["marketdata"])
            and "historical option" in text["marketdata"]
            and "personal" in text["marketdata"]
            and ("research" in text["marketdata"] or "testing" in text["marketdata"])
        ),
        "massive": (
            "options basic" in text["massive"]
            and ("$0" in text["massive"] or "free" in text["massive"])
            and "2 years historical data" in text["massive"]
            and ("individual use" in text["massive"] or "personal" in text["massive"])
        ),
        "tradier_history": (
            "occ option symbol" in text["tradier_history"]
            and _has_all(text["tradier_history"], "open", "high", "low", "close", "volume")
        ),
        "tradier_rights": _has_all(
            text["tradier_rights"], "tradier partner", "personal use only"
        ),
        "occ_data": (
            "past 24 months" in text["occ_data"]
            and _has_all(text["occ_data"], "daily", "weekly", "monthly", "underlying symbol")
        ),
        "occ_terms": (
            "automated system" in text["occ_terms"]
            and "robots" in text["occ_terms"]
            and "spiders" in text["occ_terms"]
        ),
        "cboe_delayed": (
            "strictly prohibited" in text["cboe_delayed"]
            and "auto-extraction" in text["cboe_delayed"]
        ),
        "cboe_volume": (
            "historical options volume" in text["cboe_volume"]
            and "single symbol" in text["cboe_volume"]
            and "month or year" in text["cboe_volume"]
        ),
        "alpha_vantage": (
            "historical options" in text["alpha_vantage"]
            and "15+ years" in text["alpha_vantage"]
            and "premium" in text["alpha_vantage"]
        ),
        "optionmetrics": (
            "complete historical record" in text["optionmetrics"]
            and "january 1996" in text["optionmetrics"]
            and "constant-maturity volatility surface" in text["optionmetrics"]
            and "permanent id" in text["optionmetrics"]
        ),
        "wrds": (
            "requires subscription" in text["wrds"]
            and "optionmetrics" in text["wrds"]
        ),
    }
    return {
        "document_checks": checks,
        "official_documents_verified": all(checks.values()),
        "marketdata_free_history_years": 1,
        "massive_free_history_years": 2,
        "occ_history_months": 24,
        "tradier_historical_fields": "ohlcv_only",
        "optionmetrics_history_start": "1996-01-01",
        "optionmetrics_commercial_benchmark_verified": checks["optionmetrics"]
        and checks["wrds"],
        "exact_free_authorized_source_found": False,
        "strict_approved": 0,
    }


def _blockers() -> dict[str, str]:
    return {
        "CPVolSpread": (
            "options_source_blocked:exact_atm_call_minus_put_iv_history_from_1996_"
            "and_permanent_identity_have_no_free_authorized_source"
        ),
        "RIVolSpread": (
            "options_source_blocked:exact_30_day_realized_minus_atm_iv_requires_crsp_"
            "returns_optionmetrics_equivalent_iv_history_and_historical_identity"
        ),
        "SmileSlope": (
            "options_source_blocked:exact_month_end_30_day_delta_surface_for_put_and_"
            "call_iv_from_1996_has_no_free_authorized_source"
        ),
        "skew1": (
            "options_source_blocked:exact_10_to_60_dte_contract_filters_need_historical_"
            "price_volume_open_interest_iv_moneyness_and_identity_unavailable_free"
        ),
        "dVolCall": (
            "options_source_blocked:exact_call_30_day_delta_surface_first_difference_"
            "from_1996_has_no_free_authorized_source"
        ),
        "dVolPut": (
            "options_source_blocked:exact_put_30_day_delta_surface_first_difference_"
            "from_1996_has_no_free_authorized_source"
        ),
        "dCPVolSpread": (
            "options_source_blocked:exact_pinned_difference_requires_both_call_and_put_"
            "30_day_delta_surface_histories_with_no_free_authorized_source"
        ),
        "OptionVolume1": (
            "options_source_blocked:all_exchange_monthly_option_volume_exact_crsp_stock_"
            "volume_and_historical_identity_are_not_jointly_available_free"
        ),
        "OptionVolume2": (
            "options_source_blocked:exact_optionvolume1_and_t_minus_6_to_t_minus_1_"
            "history_are_not_jointly_available_from_a_free_authorized_source"
        ),
    }


def build_options_batch_evidence(
    probe: Mapping[str, Any],
    *,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> pd.DataFrame:
    """Create specific blocker rows while making promotion impossible."""

    valid = (
        probe.get("formula_sources_verified") is True
        and probe.get("official_documents_verified") is True
        and probe.get("optionmetrics_commercial_benchmark_verified") is True
        and probe.get("exact_free_authorized_source_found") is False
        and probe.get("raw_market_data_downloaded") is False
        and probe.get("raw_files_in_artifact") is False
        and probe.get("locked_opened") is False
        and probe.get("validation_used_for_selection") is False
        and probe.get("strict_approved") == 0
        and str(evidence_run_url).startswith("https://")
        and bool(str(evidence_artifact).strip())
        and bool(_COMMIT_RE.fullmatch(str(implementation_commit)))
    )
    if not valid:
        raise ValueError("Invalid or incomplete options probe evidence")
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
            for signal, blocker in sorted(_blockers().items())
        ]
    )


def write_options_source_probe_outputs(
    probe: Mapping[str, Any],
    *,
    output_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> None:
    """Write metadata-only evidence; no option market records are persisted."""

    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = build_options_batch_evidence(
        probe,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    (output_dir / "options_source_probe.json").write_text(
        json.dumps(dict(probe), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    pd.DataFrame(SOURCE_ASSESSMENTS).to_csv(
        output_dir / "options_source_assessment.csv", index=False
    )
    pd.DataFrame(
        [
            {
                "signal": signal,
                "formula": requirement["formula"],
                "exact_inputs": requirement["exact_inputs"],
                "history": requirement["history"],
                "formula_path": OPENAP_FORMULA_SOURCES[signal]["path"],
                "formula_sha256": OPENAP_FORMULA_SOURCES[signal]["sha256"],
                "formula_commit": OPENAP_COMMIT,
            }
            for signal, requirement in sorted(OPTION_FORMULA_REQUIREMENTS.items())
        ]
    ).to_csv(output_dir / "options_formula_requirements.csv", index=False)
    evidence.to_csv(output_dir / "options_batch_evidence.csv", index=False)
    report = "\n".join(
        (
            "# OpenAP options source probe",
            "",
            "- Nine pinned option formulas were verified by source hash.",
            "- No raw option market data were downloaded or retained.",
            "- Free routes are too short, omit exact IV/open-interest/surface fields, or are not authorized for this project.",
            "- OptionMetrics IvyDB US is the exact historical benchmark but requires a commercial subscription.",
            "- Strict approvals: 0. All nine signals remain fail-closed.",
            "",
        )
    )
    (output_dir / "OPTIONS_SOURCE_PROBE_REPORT.md").write_text(
        report, encoding="utf-8"
    )


def _headers() -> dict[str, str]:
    return {
        "User-Agent": "Aurora-OpenAP-181-options-source-probe/1.0",
        "Accept": "text/html,text/plain,application/json",
    }


def _fetch(url: str, *, attempts: int = 4) -> bytes:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=_headers())
            with urllib.request.urlopen(request, timeout=180) as response:
                return response.read()
        except Exception as exc:  # pragma: no cover - exercised in GitHub Actions
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"Unable to fetch {url}: {last_error}")


def run_options_source_probe(
    *,
    output_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> dict[str, Any]:
    """Verify pinned formulas and live primary documentation in GitHub Actions."""

    formula_verified = True
    payload_cache: dict[str, bytes] = {}
    for source in OPENAP_FORMULA_SOURCES.values():
        path = source["path"]
        if path not in payload_cache:
            payload_cache[path] = _fetch(
                "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
                f"{OPENAP_COMMIT}/{path}"
            )
        formula_verified &= sha256(payload_cache[path]).hexdigest() == source["sha256"]
    if not formula_verified:
        raise ValueError("Pinned OpenAP options formula source hash mismatch")

    fetched = {
        name: _fetch(url).decode("utf-8", errors="replace")
        for name, url in DOCUMENT_URLS.items()
    }
    documents = {
        "marketdata": fetched["marketdata_pricing"] + " " + fetched["marketdata_terms"],
        "massive": fetched["massive_pricing"] + " " + fetched["massive_terms"],
        "tradier_history": fetched["tradier_history"],
        "tradier_rights": fetched["tradier_rights"],
        "occ_data": fetched["occ_data"],
        "occ_terms": fetched["occ_terms"],
        "cboe_delayed": fetched["cboe_delayed"],
        "cboe_volume": fetched["cboe_volume"],
        "alpha_vantage": fetched["alpha_vantage"],
        "optionmetrics": fetched["optionmetrics"],
        "wrds": fetched["wrds"],
    }
    summary = evaluate_options_source_documents(documents)
    if not summary["official_documents_verified"]:
        failed = [
            name for name, passed in summary["document_checks"].items() if not passed
        ]
        raise ValueError(
            "Official options documentation contract drifted: " + ",".join(failed)
        )
    summary.update(
        {
            "formula_sources_verified": True,
            "formula_commit": OPENAP_COMMIT,
            "formula_signals": len(OPTION_SIGNALS),
            "raw_market_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    write_options_source_probe_outputs(
        summary,
        output_dir=output_dir,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    return summary
