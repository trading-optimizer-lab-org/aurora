"""Pinned formulas and fail-closed evidence for operating accounting signals."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping
import json
import re

import pandas as pd

from aurora.research.openap_181.complex_accounting_batch import (
    DOCUMENT_URLS,
    SOURCE_ASSESSMENTS,
    _fetch,
    evaluate_complex_accounting_documents,
)


OPENAP_COMMIT = "8db892442c2c3a3779b0f1eac4370d3655be15a1"
OPENAP_FORMULA_FILES: dict[str, dict[str, str]] = {
    "AdExp": {
        "path": "Signals/pyCode/Predictors/AdExp.py",
        "sha256": "2e813c7e054aecddfe759d1b9c136c88ffb62755408f4ecc3697e870033aa82e",
    },
    "Cash": {
        "path": "Signals/pyCode/Predictors/Cash.py",
        "sha256": "7e9f046dd3ebe3581b57ede655a9f1ba68340dcbf53167ed6fe0030e746ecab2",
    },
    "CashProd": {
        "path": "Signals/pyCode/Predictors/CashProd.py",
        "sha256": "2541484ba36d9869221987b2a5ec015f3dd9aa5ce4406f8a0ffea56173ce1983",
    },
    "GP": {
        "path": "Signals/pyCode/Predictors/GP.py",
        "sha256": "6a05de4a5b6ddb47a320e1d95d6392e625bfca3b50091e698be9fd866a6c8576",
    },
    "Investment": {
        "path": "Signals/pyCode/Predictors/Investment.py",
        "sha256": "9b5b843157e7a57f67f6d8de610f165c27a69a5bf7cff8e671fef0e52a472e17",
    },
    "OPLeverage": {
        "path": "Signals/pyCode/Predictors/OPLeverage.py",
        "sha256": "683200c6f2b3f48fe3da68baa1f871634b825a38a04a0058d1efc033a05089c7",
    },
    "OperProf": {
        "path": "Signals/pyCode/Predictors/OperProf.py",
        "sha256": "68bef53d98e13fea98dc282bdd2a97d0bb49beaf5b59ff123a83dd03dc0bf658",
    },
    "RD": {
        "path": "Signals/pyCode/Predictors/RD.py",
        "sha256": "c9b58cea6980a3570096ab08c9e1cd224bb89e5dc0cfbadc80777bbbb263edf3",
    },
    "SP": {
        "path": "Signals/pyCode/Predictors/SP.py",
        "sha256": "4645a61c5b36a42900442c05cf287b44cbe8434f7b4447945ee54c0dc1501e1b",
    },
    "cfp": {
        "path": "Signals/pyCode/Predictors/cfp.py",
        "sha256": "71b6f3fc630ec686409d5cc9c49d60cda5381402886bf7ea7a3f119093fe41ed",
    },
    "roaq": {
        "path": "Signals/pyCode/Predictors/roaq.py",
        "sha256": "17ef6905930c74a3c697bbe51a4bb217b0ceb0b25d4026f3608e7b36a6735559",
    },
    "tang": {
        "path": "Signals/pyCode/Predictors/tang.py",
        "sha256": "cfdbe9c1f2d68e423c10efff085d92e747ae7f033cd9cbf4f9d136447f881681",
    },
}

OPERATING_ACCOUNTING_SIGNALS = frozenset(OPENAP_FORMULA_FILES)
OPERATING_ACCOUNTING_MARKET_SIGNALS = frozenset(
    {"AdExp", "CashProd", "OperProf", "RD", "SP", "cfp"}
)
_UNIQUE_FORMULA_FILES = frozenset(
    (metadata["path"], metadata["sha256"])
    for metadata in OPENAP_FORMULA_FILES.values()
)
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")


def _requirement(
    *,
    formula: str,
    exact_inputs: str,
    timing: str,
    identity: str,
    filters: str = "none",
    window_months: int = 1,
) -> dict[str, Any]:
    return {
        "formula": formula,
        "exact_inputs": exact_inputs,
        "timing": timing,
        "identity": identity,
        "filters": filters,
        "window_months": window_months,
    }


_LINKED_IDENTITY = "historical GVKEY to PERMNO/PERMCO validity intervals"

FORMULA_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "AdExp": _requirement(
        formula="xad/mve_permco",
        exact_inputs="Compustat_xad;CRSP_mve_permco;permno;monthly_time_avail_m",
        timing="same-month accounting availability and company market equity",
        identity=_LINKED_IDENTITY,
        filters="xad<=0 becomes missing",
    ),
    "Cash": _requirement(
        formula="cheq/atq",
        exact_inputs="Compustat_gvkey;rdq;cheq;atq;permno",
        timing=(
            "deduplicate gvkey-rdq, set availability to rdq month plus two months, "
            "and retain the newest rdq in overlapping months"
        ),
        identity=_LINKED_IDENTITY,
        filters="current OpenAP dup==1 and nonmissing atq selection; require atq>0",
        window_months=3,
    ),
    "CashProd": _requirement(
        formula="(mve_permco-at)/che",
        exact_inputs="Compustat_at;che;CRSP_mve_permco;permno;monthly_time_avail_m",
        timing="same-month accounting availability and company market equity",
        identity=_LINKED_IDENTITY,
        filters="first permno-month accounting observation; inner market join",
    ),
    "cfp": _requirement(
        formula=(
            "oancf/mve_permco when oancf when nonmissing; otherwise "
            "(ib-accrual_level)/mve_permco"
        ),
        exact_inputs=(
            "Compustat_act;che;lct;dlc;txp;dp;ib;oancf;CRSP_mve_permco;"
            "permno;monthly_time_avail_m"
        ),
        timing="exact calendar 12-month lags for all balance-sheet changes",
        identity=_LINKED_IDENTITY,
        filters="mve_permco==0 becomes missing; first permno-month observation",
        window_months=12,
    ),
    "GP": _requirement(
        formula="(revt-cogs)/at",
        exact_inputs="Compustat_revt;cogs;at;sic;permno;monthly_time_avail_m",
        timing="annual filing values expanded on OpenAP monthly availability",
        identity=_LINKED_IDENTITY,
        filters="exclude financial firms with SIC 6000-6999; drop missing result",
    ),
    "Investment": _requirement(
        formula="(capx/revt)/rolling36_mean(capx/revt)",
        exact_inputs="Compustat_capx;revt;permno;monthly_time_avail_m",
        timing=(
            "36-month monthly rolling mean with minimum 24 observations, after "
            "first permno-month deduplication"
        ),
        identity=_LINKED_IDENTITY,
        filters="revt<10 becomes missing",
        window_months=36,
    ),
    "OPLeverage": _requirement(
        formula="(cogs+xsga)/at, where missing xsga becomes zero",
        exact_inputs="Compustat_xsga;cogs;at;permno;monthly_time_avail_m",
        timing="first permno-month accounting observation",
        identity=_LINKED_IDENTITY,
    ),
    "OperProf": _requirement(
        formula="(revt-cogs-xsga-xint)/ceq",
        exact_inputs=(
            "Compustat_revt;cogs;xsga;xint;ceq;CRSP_mve_c;gvkey;permno;"
            "monthly_time_avail_m"
        ),
        timing="same-month accounting availability and cross-sectional market size",
        identity=_LINKED_IDENTITY,
        filters="exclude smallest within-month mve_c tercile using current qcut",
    ),
    "RD": _requirement(
        formula="xrd/mve_permco",
        exact_inputs="Compustat_xrd;CRSP_mve_permco;gvkey;permno;monthly_time_avail_m",
        timing="same-month accounting availability and company market equity",
        identity=_LINKED_IDENTITY,
    ),
    "SP": _requirement(
        formula="sale/mve_permco",
        exact_inputs="Compustat_sale;CRSP_mve_permco;permno;monthly_time_avail_m",
        timing="same-month accounting availability and company market equity",
        identity=_LINKED_IDENTITY,
        filters="first permno-month accounting observation; drop missing result",
    ),
    "roaq": _requirement(
        formula="ibq/lag3_atq",
        exact_inputs="Compustat_gvkey;ibq;atq;permno;monthly_time_avail_m",
        timing="exact calendar three-month lag for quarterly assets",
        identity=_LINKED_IDENTITY,
        window_months=3,
    ),
    "tang": _requirement(
        formula="(che+0.715*rect+0.547*invt+0.535*ppegt)/at",
        exact_inputs=(
            "Compustat_che;rect;invt;ppegt;at;sic;permno;monthly_time_avail_m"
        ),
        timing="first permno-month accounting observation",
        identity=_LINKED_IDENTITY,
        filters=(
            "retain manufacturing SIC 2000-3999; size-decile FC is computed but "
            "not applied to the current OpenAP output"
        ),
    ),
}


OPERATING_ACCOUNTING_BLOCKERS = {
    "AdExp": (
        "operating_accounting_source_blocked:exact_compustat_xad+crsp_mve_permco+"
        "positive_xad_semantics+pre2009_history+historical_gvkey_permno_permco_"
        "identity+coverage_fidelity_unmeasured"
    ),
    "Cash": (
        "operating_accounting_source_blocked:exact_quarterly_compustat_rdq_cheq_"
        "atq+duplicate_and_three_month_expansion_semantics+pre2009_history+"
        "historical_gvkey_permno_identity+coverage_fidelity_unmeasured"
    ),
    "CashProd": (
        "operating_accounting_source_blocked:exact_compustat_at_che+crsp_mve_"
        "permco+same_month_join_semantics+pre2009_history+historical_gvkey_permno_"
        "permco_identity+coverage_fidelity_unmeasured"
    ),
    "cfp": (
        "operating_accounting_source_blocked:exact_compustat_oancf_ib_dp_act_che_"
        "lct_dlc_txp+crsp_mve_permco+12m_calendar_lag_and_fallback_semantics+"
        "pre2009_history+historical_gvkey_permno_identity+coverage_fidelity_"
        "unmeasured"
    ),
    "GP": (
        "operating_accounting_source_blocked:exact_compustat_revt_cogs_at_sic+"
        "financial_filter_semantics+pre2009_history+historical_gvkey_permno_"
        "identity+coverage_fidelity_unmeasured"
    ),
    "Investment": (
        "operating_accounting_source_blocked:exact_compustat_capx_revt+36m_rolling_"
        "mean_24obs_and_revenue_filter+pre2009_history+historical_gvkey_permno_"
        "identity+coverage_fidelity_unmeasured"
    ),
    "OPLeverage": (
        "operating_accounting_source_blocked:exact_compustat_xsga_cogs_at+missing_"
        "xsga_zero_semantics+pre2009_history+historical_gvkey_permno_identity+"
        "coverage_fidelity_unmeasured"
    ),
    "OperProf": (
        "operating_accounting_source_blocked:exact_compustat_revt_cogs_xsga_xint_"
        "ceq+crsp_mve_c+monthly_size_tercile_universe+pre2009_history+historical_"
        "gvkey_permno_identity+coverage_fidelity_unmeasured"
    ),
    "RD": (
        "operating_accounting_source_blocked:exact_compustat_xrd+crsp_mve_permco+"
        "same_month_join_semantics+pre2009_history+historical_gvkey_permno_permco_"
        "identity+coverage_fidelity_unmeasured"
    ),
    "SP": (
        "operating_accounting_source_blocked:exact_compustat_sale+crsp_mve_permco+"
        "same_month_join_semantics+pre2009_history+historical_gvkey_permno_permco_"
        "identity+coverage_fidelity_unmeasured"
    ),
    "roaq": (
        "operating_accounting_source_blocked:exact_quarterly_compustat_ibq_atq+"
        "3m_calendar_lag_semantics+pre2009_history+historical_gvkey_permno_"
        "identity+coverage_fidelity_unmeasured"
    ),
    "tang": (
        "operating_accounting_source_blocked:exact_compustat_che_rect_invt_ppegt_"
        "at_sic+manufacturing_and_unapplied_fc_semantics+pre2009_history+"
        "historical_gvkey_permno_identity+coverage_fidelity_unmeasured"
    ),
}


def evaluate_operating_accounting_documents(
    documents: Mapping[str, str],
    *,
    access_errors: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Reuse the official accounting and historical-identity decision contract."""

    return evaluate_complex_accounting_documents(
        documents,
        access_errors=access_errors,
    )


def build_operating_accounting_evidence(
    probe: Mapping[str, Any],
    *,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> pd.DataFrame:
    """Build signal-specific blockers without promoting partial proxies."""

    valid = (
        probe.get("source_access_decision_complete") is True
        and probe.get("unresolved_documents") == []
        and probe.get("formula_sources_verified") is True
        and probe.get("formula_files") == len(_UNIQUE_FORMULA_FILES)
        and probe.get("formula_signals") == len(OPERATING_ACCOUNTING_SIGNALS)
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
        raise ValueError("Invalid or incomplete operating accounting evidence")
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
                "blocking_reason": OPERATING_ACCOUNTING_BLOCKERS[signal],
                "evidence_run_url": str(evidence_run_url),
                "evidence_artifact": str(evidence_artifact).strip(),
                "implementation_commit": str(implementation_commit),
            }
            for signal in sorted(OPERATING_ACCOUNTING_SIGNALS)
        ]
    )


def write_operating_accounting_outputs(
    probe: Mapping[str, Any],
    *,
    output_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> None:
    """Write formula and documentary evidence only; never retain source data."""

    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = build_operating_accounting_evidence(
        probe,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    (output_dir / "operating_accounting_source_probe.json").write_text(
        json.dumps(dict(probe), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    pd.DataFrame(SOURCE_ASSESSMENTS).to_csv(
        output_dir / "operating_accounting_source_assessment.csv",
        index=False,
    )
    requirements = [
        {
            "signal": signal,
            **FORMULA_REQUIREMENTS[signal],
            "formula_path": OPENAP_FORMULA_FILES[signal]["path"],
            "formula_sha256": OPENAP_FORMULA_FILES[signal]["sha256"],
            "formula_commit": OPENAP_COMMIT,
        }
        for signal in sorted(OPERATING_ACCOUNTING_SIGNALS)
    ]
    pd.DataFrame(requirements).to_csv(
        output_dir / "operating_accounting_formula_requirements.csv",
        index=False,
    )
    evidence.to_csv(
        output_dir / "operating_accounting_batch_evidence.csv",
        index=False,
    )
    blocked_docs = ", ".join(probe.get("access_blocked_documents", []))
    report = "\n".join(
        (
            "# OpenAP operating accounting source probe",
            "",
            "- Twelve current OpenAP formula files are pinned by commit and SHA-256.",
            "- Six formulas require market inputs; all twelve require historical identity.",
            "- SEC FSD is as-filed XBRL from 2009, not standardized Compustat history.",
            "- OpenFIGI does not provide historical PERMNO/PERMCO validity intervals.",
            "- Exact CRSP and Compustat inputs remain subscriber or licensed products.",
            f"- Official document access blockers: {blocked_docs or 'none'}.",
            "- No filings, fundamentals or market observations were retained.",
            "- Strict approvals: 0. All twelve signals remain fail-closed.",
            "",
        )
    )
    (output_dir / "OPERATING_ACCOUNTING_SOURCE_PROBE_REPORT.md").write_text(
        report,
        encoding="utf-8",
    )


def run_operating_accounting_source_probe(
    *,
    output_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> dict[str, Any]:
    """Verify pinned formulas and official documents without source observations."""

    for path, expected_hash in sorted(_UNIQUE_FORMULA_FILES):
        url = (
            "https://raw.githubusercontent.com/OpenSourceAP/CrossSection/"
            f"{OPENAP_COMMIT}/{path}"
        )
        actual = sha256(_fetch(url)).hexdigest()
        if actual != expected_hash:
            raise ValueError(
                "Pinned OpenAP formula source hash mismatch: "
                f"path={path}:expected={expected_hash}:actual={actual}"
            )

    documents: dict[str, str] = {}
    access_errors: dict[str, str] = {}
    for name, url in DOCUMENT_URLS.items():
        try:
            documents[name] = _fetch(url).decode("utf-8", errors="replace")
        except RuntimeError as exc:
            documents[name] = ""
            access_errors[name] = f"{name}:{exc}"
    summary = evaluate_operating_accounting_documents(
        documents,
        access_errors=access_errors,
    )
    if not summary["source_access_decision_complete"]:
        raise ValueError(
            "Operating accounting documentation contract unresolved: "
            + ",".join(summary["unresolved_documents"])
        )
    summary.update(
        {
            "formula_sources_verified": True,
            "formula_commit": OPENAP_COMMIT,
            "formula_files": len(_UNIQUE_FORMULA_FILES),
            "formula_signals": len(OPERATING_ACCOUNTING_SIGNALS),
            "raw_source_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    write_operating_accounting_outputs(
        summary,
        output_dir=output_dir,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    return summary


__all__ = [
    "FORMULA_REQUIREMENTS",
    "OPENAP_COMMIT",
    "OPENAP_FORMULA_FILES",
    "OPERATING_ACCOUNTING_BLOCKERS",
    "OPERATING_ACCOUNTING_MARKET_SIGNALS",
    "OPERATING_ACCOUNTING_SIGNALS",
    "build_operating_accounting_evidence",
    "evaluate_operating_accounting_documents",
    "run_operating_accounting_source_probe",
    "write_operating_accounting_outputs",
]
