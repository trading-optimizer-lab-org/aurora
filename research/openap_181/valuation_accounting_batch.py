"""Pinned formulas and fail-closed evidence for OpenAP valuation accounting."""

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
    "AM": {
        "path": "Signals/pyCode/Predictors/AM.py",
        "sha256": "5c66c0e4e0cfcf3ecb68ca6a28d707600500462a8065694d161ab0be380ad750",
    },
    "BM": {
        "path": "Signals/pyCode/Predictors/BM.py",
        "sha256": "b852ede9b0b5cb9da89e752ca4c5348ed96380a923357fa9e7dd5274a9a5d946",
    },
    "BMdec": {
        "path": "Signals/pyCode/Predictors/BMdec.py",
        "sha256": "111bb8df1db87d92fb55ec4c070dc157281655afe80d9f54796ee4572f533d06",
    },
    "BPEBM": {
        "path": "Signals/pyCode/Predictors/ZZ1_EBM_BPEBM.py",
        "sha256": "2fc3537cf2b935b4ec1204dc7966c0fe475683a7a47a9df74b5837b80dddf9c6",
    },
    "BookLeverage": {
        "path": "Signals/pyCode/Predictors/BookLeverage.py",
        "sha256": "af34ed6680a162075ec28554f8ddc485eef35ffbc06783b09431fdfbb01c9298",
    },
    "CF": {
        "path": "Signals/pyCode/Predictors/CF.py",
        "sha256": "09532e1ce762f64f4b225c5f4bd00b48ae40de55003da0295b1ae617585f1296",
    },
    "EBM": {
        "path": "Signals/pyCode/Predictors/ZZ1_EBM_BPEBM.py",
        "sha256": "2fc3537cf2b935b4ec1204dc7966c0fe475683a7a47a9df74b5837b80dddf9c6",
    },
    "EP": {
        "path": "Signals/pyCode/Predictors/EP.py",
        "sha256": "7879a38168363a50056907b7819023be609e29a4514bfc7b9bc547a3bd590a96",
    },
    "EntMult": {
        "path": "Signals/pyCode/Predictors/EntMult.py",
        "sha256": "3959786d1f35735633a840c626f3241384cc913f5d026435a02c85c0b44161d9",
    },
    "Leverage": {
        "path": "Signals/pyCode/Predictors/Leverage.py",
        "sha256": "c63e0c634038e25511493d98fa9ee58099613f5d022df7bc74a33619d034e70b",
    },
}

VALUATION_ACCOUNTING_SIGNALS = frozenset(OPENAP_FORMULA_FILES)
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
    filters: str = "none",
    window_months: int = 1,
) -> dict[str, Any]:
    return {
        "formula": formula,
        "exact_inputs": exact_inputs,
        "timing": timing,
        "identity": "historical GVKEY to PERMNO/PERMCO validity intervals",
        "filters": filters,
        "window_months": window_months,
    }


FORMULA_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "AM": _requirement(
        formula="at/mve_permco",
        exact_inputs="Compustat_at;CRSP_mve_permco;monthly_time_avail_m",
        timing=(
            "annual accounting value aligned to OpenAP monthly availability and "
            "same-month company market equity"
        ),
    ),
    "BM": _requirement(
        formula="log(ceqt/me_datadate); nonpositive ratio becomes missing",
        exact_inputs=(
            "Compustat_ceqt;datadate;CRSP_mve_permco;monthly_time_avail_m"
        ),
        timing=(
            "mve_permco exactly six calendar months before time_avail_m must match "
            "the datadate month, then it is forward-filled"
        ),
        filters="nonpositive ceqt/me_datadate becomes missing through log",
        window_months=6,
    ),
    "BMdec": _requirement(
        formula=(
            "tempPS uses pstk, then pstkrv, then pstkl; tempSE uses seq, then "
            "ceq+tempPS, then at-lt; txditc missing becomes zero; "
            "tempBE=tempSE+txditc-tempPS; BMdec=tempBE/prior December market equity"
        ),
        exact_inputs=(
            "Compustat_txditc;seq;ceq;at;lt;pstk;pstkrv;pstkl;"
            "CRSP_prc;shrout;monthly_time_avail_m"
        ),
        timing=(
            "December abs(prc)*shrout is joined through exact 12-month and 17-month "
            "calendar lags according to formation month"
        ),
        filters="zero December market equity becomes missing",
        window_months=17,
    ),
    "BPEBM": _requirement(
        formula=(
            "BP-EBM where temp=che-dltt-dlc-dc-dvpa+tstkp, "
            "EBM=(ceq+temp)/(mve_permco+temp), and "
            "BP=(ceq+tstkp-dvpa)/mve_permco"
        ),
        exact_inputs=(
            "Compustat_che;dltt;dlc;dc;dvpa;tstkp;ceq;"
            "CRSP_mve_permco;monthly_time_avail_m"
        ),
        timing="all accounting and company market-equity inputs known by formation month",
    ),
    "BookLeverage": _requirement(
        formula=(
            "at/(tempSE+txditc-tempPS); txditc missing becomes zero; tempPS uses "
            "pstk, then pstkrv, then pstkl; tempSE uses seq, then ceq+tempPS, "
            "then at-lt"
        ),
        exact_inputs="Compustat_at;lt;txditc;pstk;pstkrv;pstkl;seq;ceq",
        timing="annual filing value expanded causally on OpenAP monthly availability",
        filters="zero book equity becomes missing",
    ),
    "CF": _requirement(
        formula="(ib+dp)/mve_permco",
        exact_inputs="Compustat_ib;dp;CRSP_mve_permco;monthly_time_avail_m",
        timing=(
            "income and depreciation aligned to OpenAP availability and same-month "
            "company market equity"
        ),
        filters="zero market equity becomes missing",
    ),
    "EBM": _requirement(
        formula=(
            "(ceq+temp)/(mve_permco+temp), where "
            "temp=che-dltt-dlc-dc-dvpa+tstkp"
        ),
        exact_inputs=(
            "Compustat_che;dltt;dlc;dc;dvpa;tstkp;ceq;"
            "CRSP_mve_permco;monthly_time_avail_m"
        ),
        timing="all accounting and company market-equity inputs known by formation month",
    ),
    "EP": _requirement(
        formula="ib/lag6_mve_permco",
        exact_inputs="Compustat_ib;CRSP_mve_permco;monthly_time_avail_m",
        timing="exact six-calendar-month company market-equity lag",
        filters="negative EP becomes missing",
        window_months=6,
    ),
    "EntMult": _requirement(
        formula="(mve_permco+dltt+dlc+dc-che)/oibdp",
        exact_inputs=(
            "Compustat_dltt;dlc;dc;che;oibdp;ceq;"
            "CRSP_mve_permco;monthly_time_avail_m"
        ),
        timing="all accounting and company market-equity inputs known by formation month",
        filters="ceq<0 or oibdp<0 becomes missing",
    ),
    "Leverage": _requirement(
        formula="lt/mve_permco",
        exact_inputs="Compustat_lt;CRSP_mve_permco;monthly_time_avail_m",
        timing=(
            "liabilities aligned to OpenAP availability and same-month company "
            "market equity"
        ),
    ),
}


VALUATION_ACCOUNTING_BLOCKERS = {
    "AM": (
        "valuation_accounting_source_blocked:exact_compustat_at+"
        "crsp_mve_permco+pre2009_history+historical_gvkey_permno_permco_identity+"
        "coverage_fidelity_unmeasured"
    ),
    "BM": (
        "valuation_accounting_source_blocked:exact_compustat_ceqt_datadate+"
        "crsp_mve_permco+6m_datadate_alignment_and_log_semantics+pre2009_history+"
        "historical_gvkey_permno_permco_identity+coverage_fidelity_unmeasured"
    ),
    "BMdec": (
        "valuation_accounting_source_blocked:exact_compustat_book_equity_fallbacks+"
        "crsp_prc_shrout+december_12m_17m_lags+pre2009_history+"
        "historical_gvkey_permno_permco_identity+coverage_fidelity_unmeasured"
    ),
    "BPEBM": (
        "valuation_accounting_source_blocked:exact_compustat_che_dltt_dlc_dc_dvpa_"
        "tstkp_ceq+crsp_mve_permco+dc_and_preferred_semantics+pre2009_history+"
        "historical_gvkey_permno_permco_identity+coverage_fidelity_unmeasured"
    ),
    "BookLeverage": (
        "valuation_accounting_source_blocked:exact_compustat_book_equity_fallbacks+"
        "txditc_missing_zero_semantics+pre2009_history+historical_gvkey_permno_"
        "identity+coverage_fidelity_unmeasured"
    ),
    "CF": (
        "valuation_accounting_source_blocked:exact_compustat_ib_dp+"
        "crsp_mve_permco+pre2009_history+historical_gvkey_permno_permco_identity+"
        "coverage_fidelity_unmeasured"
    ),
    "EBM": (
        "valuation_accounting_source_blocked:exact_compustat_che_dltt_dlc_dc_dvpa_"
        "tstkp_ceq+crsp_mve_permco+enterprise_denominator_semantics+pre2009_history+"
        "historical_gvkey_permno_permco_identity+coverage_fidelity_unmeasured"
    ),
    "EP": (
        "valuation_accounting_source_blocked:exact_compustat_ib+"
        "crsp_mve_permco+6m_calendar_lag_and_negative_filter+pre2009_history+"
        "historical_gvkey_permno_permco_identity+coverage_fidelity_unmeasured"
    ),
    "EntMult": (
        "valuation_accounting_source_blocked:exact_compustat_dltt_dlc_dc_che_oibdp_"
        "ceq+crsp_mve_permco+negative_filter_semantics+pre2009_history+"
        "historical_gvkey_permno_permco_identity+coverage_fidelity_unmeasured"
    ),
    "Leverage": (
        "valuation_accounting_source_blocked:exact_compustat_lt+"
        "crsp_mve_permco+pre2009_history+historical_gvkey_permno_permco_identity+"
        "coverage_fidelity_unmeasured"
    ),
}


def evaluate_valuation_accounting_documents(
    documents: Mapping[str, str],
    *,
    access_errors: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Reuse the official accounting and historical-identity decision contract."""

    return evaluate_complex_accounting_documents(
        documents,
        access_errors=access_errors,
    )


def build_valuation_accounting_evidence(
    probe: Mapping[str, Any],
    *,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> pd.DataFrame:
    """Build ten signal-specific blockers without promoting partial proxies."""

    valid = (
        probe.get("source_access_decision_complete") is True
        and probe.get("unresolved_documents") == []
        and probe.get("formula_sources_verified") is True
        and probe.get("formula_files") == len(_UNIQUE_FORMULA_FILES)
        and probe.get("formula_signals") == len(VALUATION_ACCOUNTING_SIGNALS)
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
        raise ValueError("Invalid or incomplete valuation accounting evidence")
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
                "blocking_reason": VALUATION_ACCOUNTING_BLOCKERS[signal],
                "evidence_run_url": str(evidence_run_url),
                "evidence_artifact": str(evidence_artifact).strip(),
                "implementation_commit": str(implementation_commit),
            }
            for signal in sorted(VALUATION_ACCOUNTING_SIGNALS)
        ]
    )


def write_valuation_accounting_outputs(
    probe: Mapping[str, Any],
    *,
    output_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> None:
    """Write formula and documentary evidence only; never retain source data."""

    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = build_valuation_accounting_evidence(
        probe,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    (output_dir / "valuation_accounting_source_probe.json").write_text(
        json.dumps(dict(probe), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    pd.DataFrame(SOURCE_ASSESSMENTS).to_csv(
        output_dir / "valuation_accounting_source_assessment.csv",
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
        for signal in sorted(VALUATION_ACCOUNTING_SIGNALS)
    ]
    pd.DataFrame(requirements).to_csv(
        output_dir / "valuation_accounting_formula_requirements.csv",
        index=False,
    )
    evidence.to_csv(
        output_dir / "valuation_accounting_batch_evidence.csv",
        index=False,
    )
    blocked_docs = ", ".join(probe.get("access_blocked_documents", []))
    report = "\n".join(
        (
            "# OpenAP valuation accounting source probe",
            "",
            "- Ten signals map to nine current OpenAP files pinned by commit and SHA-256.",
            "- Every formula requires exact Compustat semantics; nine also require CRSP market data.",
            "- SEC FSD is as-filed XBRL from 2009, not standardized Compustat history.",
            "- OpenFIGI does not provide historical PERMNO/PERMCO validity intervals.",
            "- Exact CRSP and Compustat inputs remain subscriber or licensed products.",
            f"- Official document access blockers: {blocked_docs or 'none'}.",
            "- No filings, fundamentals or market observations were retained.",
            "- Strict approvals: 0. All ten signals remain fail-closed.",
            "",
        )
    )
    (output_dir / "VALUATION_ACCOUNTING_SOURCE_PROBE_REPORT.md").write_text(
        report,
        encoding="utf-8",
    )


def run_valuation_accounting_source_probe(
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
    summary = evaluate_valuation_accounting_documents(
        documents,
        access_errors=access_errors,
    )
    if not summary["source_access_decision_complete"]:
        raise ValueError(
            "Valuation accounting documentation contract unresolved: "
            + ",".join(summary["unresolved_documents"])
        )
    summary.update(
        {
            "formula_sources_verified": True,
            "formula_commit": OPENAP_COMMIT,
            "formula_files": len(_UNIQUE_FORMULA_FILES),
            "formula_signals": len(VALUATION_ACCOUNTING_SIGNALS),
            "raw_source_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    write_valuation_accounting_outputs(
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
    "VALUATION_ACCOUNTING_BLOCKERS",
    "VALUATION_ACCOUNTING_SIGNALS",
    "build_valuation_accounting_evidence",
    "evaluate_valuation_accounting_documents",
    "run_valuation_accounting_source_probe",
    "write_valuation_accounting_outputs",
]
