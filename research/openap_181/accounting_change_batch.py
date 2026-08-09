"""Pinned formulas and fail-closed evidence for accounting-change signals."""

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
    "ChAssetTurnover": {
        "path": "Signals/pyCode/Predictors/ChAssetTurnover.py",
        "sha256": "f584e17a303ce790c6515eff040535a3fd86201129e415e504bce36c499bb651",
    },
    "ChInvIA": {
        "path": "Signals/pyCode/Predictors/ChInvIA.py",
        "sha256": "09d5b9ae1836066d80de96b77352632246eafe30bbefb59fdf2c635291d90388",
    },
    "ChTax": {
        "path": "Signals/pyCode/Predictors/ChTax.py",
        "sha256": "04a5a239bed7f24ca9b0503b033eb0a7c579202da5f4144af2bfd718afc3ebda",
    },
    "GrLTNOA": {
        "path": "Signals/pyCode/Predictors/GrLTNOA.py",
        "sha256": "d82c228fe3f391c514dfcf1ae32b3709fdedc1c0b8173459e6ea9c3bbacb3aa1",
    },
    "GrSaleToGrInv": {
        "path": "Signals/pyCode/Predictors/GrSaleToGrInv.py",
        "sha256": "0dd077f6ae9ab052955525ca1a53adbb06e4e4ea73c4fcbc956e8eb0574e41e6",
    },
    "InvGrowth": {
        "path": "Signals/pyCode/Predictors/InvGrowth.py",
        "sha256": "177fb08aabfafd0ff460be24eb75d5180c18db4bade422cc3fefcd7802cae4fa",
    },
    "OrderBacklog": {
        "path": "Signals/pyCode/Predictors/OrderBacklog.py",
        "sha256": "a075ad1af49c8979d14037d0cd8a80adc91ebf92810010d57658fe8795c08954",
    },
    "OrderBacklogChg": {
        "path": "Signals/pyCode/Predictors/OrderBacklogChg.py",
        "sha256": "2e87eb4c390a81b382e2948c17c3b48b74c8628e68dcfaa120ba54d5d52251c7",
    },
    "Tax": {
        "path": "Signals/pyCode/Predictors/Tax.py",
        "sha256": "060ba47cb7d7e9a40634bc806e6e70f1c35cdff75896e984b857ea6fb27000f1",
    },
    "XFIN": {
        "path": "Signals/pyCode/Predictors/XFIN.py",
        "sha256": "560138c5c24d6ad834bcbd28b5746eaf95ecbf4089adbaa7daba867204966fdd",
    },
}

ACCOUNTING_CHANGE_SIGNALS = frozenset(OPENAP_FORMULA_FILES)
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


_LINKED_IDENTITY = "historical GVKEY to PERMNO validity intervals"

FORMULA_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "ChAssetTurnover": _requirement(
        formula=(
            "sale/mean(operating_assets,lag12_operating_assets)-"
            "lag12_asset_turnover"
        ),
        exact_inputs=(
            "Compustat_rect;invt;aco;ppent;intan;ap;lco;lo;sale;permno;"
            "monthly_time_avail_m"
        ),
        timing=(
            "exact calendar 12-month operating-assets lag followed by exact "
            "calendar 12-month asset-turnover lag"
        ),
        identity=_LINKED_IDENTITY,
        filters=(
            "forward-fill ppent within permno; negative asset turnover becomes "
            "missing; first permno-month observation"
        ),
        window_months=24,
    ),
    "ChInvIA": _requirement(
        formula="capx_growth-minus-monthly_two_digit_sic_mean",
        exact_inputs=(
            "Compustat_capx;ppent;CRSP_sicCRSP;permno;monthly_time_avail_m"
        ),
        timing=(
            "exact calendar lag12 and lag24 average baseline followed by "
            "same-month two-digit CRSP SIC cross-section"
        ),
        identity=_LINKED_IDENTITY,
        filters=(
            "missing capx falls back to ppent change; missing primary growth falls "
            "back to lag12 growth; zero denominators become missing"
        ),
        window_months=24,
    ),
    "ChTax": _requirement(
        formula="(txtq-lag12_txtq)/lag12_at",
        exact_inputs=(
            "Compustat_gvkey;quarterly_txtq;annual_at;permno;monthly_time_avail_m"
        ),
        timing=(
            "inner annual-quarterly availability merge with exact calendar "
            "12-month lags by gvkey"
        ),
        identity=_LINKED_IDENTITY,
        window_months=12,
    ),
    "GrLTNOA": _requirement(
        formula=(
            "current_ltnoa/at-lag12_ltnoa/lag12_at-working-capital adjustment"
        ),
        exact_inputs=(
            "Compustat_rect;invt;ppent;aco;intan;ao;ap;lco;lo;at;dp;permno;"
            "monthly_time_avail_m"
        ),
        timing="current OpenAP uses 12-row positional lags after permno-month sort",
        identity=_LINKED_IDENTITY,
        filters="first permno-month observation",
        window_months=12,
    ),
    "GrSaleToGrInv": _requirement(
        formula="sale_growth-minus-inventory_growth",
        exact_inputs="Compustat_sale;invt;permno;monthly_time_avail_m",
        timing=(
            "current OpenAP uses positional lag12 and lag24 average baselines "
            "after permno-month sort"
        ),
        identity=_LINKED_IDENTITY,
        filters=(
            "zero denominators become missing; fallback to lag12 growth when the "
            "primary difference is missing; first permno-month observation"
        ),
        window_months=24,
    ),
    "InvGrowth": _requirement(
        formula="real_invt/lag12_real_invt-1",
        exact_inputs=(
            "Compustat_invt;sic;ppent;at;GNP_deflator;permno;monthly_time_avail_m"
        ),
        timing="deflate inventory then use exact calendar 12-month lag",
        identity=_LINKED_IDENTITY,
        filters=(
            "exclude SIC 4xxx and 6xxx; require at>0 and ppent>0 or missing; "
            "first permno-month observation"
        ),
        window_months=12,
    ),
    "OrderBacklog": _requirement(
        formula="ob/(0.5*(at+lag12_at))",
        exact_inputs="Compustat_ob;at;permno;monthly_time_avail_m",
        timing="current OpenAP uses a 12-row positional lag after permno-month sort",
        identity=_LINKED_IDENTITY,
        filters="ob==0 becomes missing; first permno-month observation",
        window_months=12,
    ),
    "OrderBacklogChg": _requirement(
        formula="order_backlog-lag12_order_backlog",
        exact_inputs="Compustat_ob;at;permno;monthly_time_avail_m",
        timing=(
            "current OpenAP uses 12-row positional lags for assets and then for "
            "scaled order backlog"
        ),
        identity=_LINKED_IDENTITY,
        filters="ob==0 makes scaled order backlog missing; first permno-month row",
        window_months=24,
    ),
    "Tax": _requirement(
        formula=(
            "((txfo+txfed)/tax_rate)/ib with alternative txt-txdi calculation"
        ),
        exact_inputs=(
            "Compustat_txfo;txfed;ib;txt;txdi;permno;monthly_time_avail_m"
        ),
        timing=(
            "historical statutory rates: 0.48 default, 0.46 in 1979-1986, 0.40 "
            "in 1987, 0.34 in 1988-1992, and 0.35 from 1993"
        ),
        identity=_LINKED_IDENTITY,
        filters=(
            "use alternative when txfo or txfed is missing; tax activity with "
            "non-positive income can become one; retain finite values"
        ),
    ),
    "XFIN": _requirement(
        formula="(sstk-dv-prstkc+dltis-dltr+dlcch)/at",
        exact_inputs=(
            "Compustat_sstk;dv;prstkc;dltis;dltr;dlcch;at;permno;"
            "monthly_time_avail_m"
        ),
        timing="first permno-month accounting observation",
        identity=_LINKED_IDENTITY,
        filters="missing dlcch becomes zero",
    ),
}


ACCOUNTING_CHANGE_BLOCKERS = {
    "ChAssetTurnover": (
        "accounting_change_source_blocked:exact_compustat_rect_invt_aco_ppent_"
        "intan_ap_lco_lo_sale+ppent_forward_fill_and_two_calendar_lags+pre2009_"
        "history+historical_gvkey_permno_identity+coverage_fidelity_unmeasured"
    ),
    "ChInvIA": (
        "accounting_change_source_blocked:exact_compustat_capx_ppent+crsp_sic_"
        "history+capx_fallback_and_two_digit_industry_universe+pre2009_history+"
        "historical_gvkey_permno_identity+coverage_fidelity_unmeasured"
    ),
    "ChTax": (
        "accounting_change_source_blocked:exact_quarterly_compustat_txtq+annual_"
        "at+annual_quarterly_available_at_merge_and_12m_calendar_lags+pre2009_"
        "history+historical_gvkey_permno_identity+coverage_fidelity_unmeasured"
    ),
    "GrLTNOA": (
        "accounting_change_source_blocked:exact_compustat_rect_invt_ppent_aco_"
        "intan_ao_ap_lco_lo_at_dp+12row_lag_and_working_capital_semantics+"
        "pre2009_history+historical_gvkey_permno_identity+coverage_fidelity_"
        "unmeasured"
    ),
    "GrSaleToGrInv": (
        "accounting_change_source_blocked:exact_compustat_sale_invt+12row_24row_"
        "average_and_fallback_semantics+pre2009_history+historical_gvkey_permno_"
        "identity+coverage_fidelity_unmeasured"
    ),
    "InvGrowth": (
        "accounting_change_source_blocked:exact_compustat_invt_sic_ppent_at+gnp_"
        "deflator_alignment+industry_filters_and_12m_calendar_lag+pre2009_history+"
        "historical_gvkey_permno_identity+coverage_fidelity_unmeasured"
    ),
    "OrderBacklog": (
        "accounting_change_source_blocked:exact_compustat_ob_at+order_backlog_"
        "standardization_and_12row_lag+pre2009_history+historical_gvkey_permno_"
        "identity+coverage_fidelity_unmeasured"
    ),
    "OrderBacklogChg": (
        "accounting_change_source_blocked:exact_compustat_ob_at+scaled_backlog_"
        "two_stage_12row_lag_semantics+pre2009_history+historical_gvkey_permno_"
        "identity+coverage_fidelity_unmeasured"
    ),
    "Tax": (
        "accounting_change_source_blocked:exact_compustat_txfo_txfed_ib_txt_"
        "txdi+historical_tax_rate_and_missing_value_semantics+pre2009_history+"
        "historical_gvkey_permno_identity+coverage_fidelity_unmeasured"
    ),
    "XFIN": (
        "accounting_change_source_blocked:exact_compustat_sstk_dv_prstkc_dltis_"
        "dltr_dlcch_at+missing_dlcch_zero_semantics+pre2009_history+historical_"
        "gvkey_permno_identity+coverage_fidelity_unmeasured"
    ),
}


def evaluate_accounting_change_documents(
    documents: Mapping[str, str],
    *,
    access_errors: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Reuse the official accounting and historical-identity decision contract."""

    return evaluate_complex_accounting_documents(
        documents,
        access_errors=access_errors,
    )


def build_accounting_change_evidence(
    probe: Mapping[str, Any],
    *,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> pd.DataFrame:
    """Build signal-specific blockers without promoting partial reconstructions."""

    valid = (
        probe.get("source_access_decision_complete") is True
        and probe.get("unresolved_documents") == []
        and probe.get("formula_sources_verified") is True
        and probe.get("formula_files") == len(_UNIQUE_FORMULA_FILES)
        and probe.get("formula_signals") == len(ACCOUNTING_CHANGE_SIGNALS)
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
        raise ValueError("Invalid or incomplete accounting-change evidence")
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
                "blocking_reason": ACCOUNTING_CHANGE_BLOCKERS[signal],
                "evidence_run_url": str(evidence_run_url),
                "evidence_artifact": str(evidence_artifact).strip(),
                "implementation_commit": str(implementation_commit),
            }
            for signal in sorted(ACCOUNTING_CHANGE_SIGNALS)
        ]
    )


def write_accounting_change_outputs(
    probe: Mapping[str, Any],
    *,
    output_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> None:
    """Write formula and documentary evidence only; never retain source data."""

    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = build_accounting_change_evidence(
        probe,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    (output_dir / "accounting_change_source_probe.json").write_text(
        json.dumps(dict(probe), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    pd.DataFrame(SOURCE_ASSESSMENTS).to_csv(
        output_dir / "accounting_change_source_assessment.csv",
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
        for signal in sorted(ACCOUNTING_CHANGE_SIGNALS)
    ]
    pd.DataFrame(requirements).to_csv(
        output_dir / "accounting_change_formula_requirements.csv",
        index=False,
    )
    evidence.to_csv(
        output_dir / "accounting_change_batch_evidence.csv",
        index=False,
    )
    blocked_docs = ", ".join(probe.get("access_blocked_documents", []))
    report = "\n".join(
        (
            "# OpenAP accounting-change source probe",
            "",
            "- Ten current OpenAP formula files are pinned by commit and SHA-256.",
            "- Current positional and calendar lag semantics are frozen separately.",
            "- SEC FSD is as-filed XBRL from 2009, not standardized Compustat history.",
            "- OpenFIGI does not provide historical PERMNO validity intervals.",
            "- Exact CRSP and Compustat inputs remain subscriber or licensed products.",
            f"- Official document access blockers: {blocked_docs or 'none'}.",
            "- No filings, fundamentals or market observations were retained.",
            "- Strict approvals: 0. All ten signals remain fail-closed.",
            "",
        )
    )
    (output_dir / "ACCOUNTING_CHANGE_SOURCE_PROBE_REPORT.md").write_text(
        report,
        encoding="utf-8",
    )


def run_accounting_change_source_probe(
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
    summary = evaluate_accounting_change_documents(
        documents,
        access_errors=access_errors,
    )
    if not summary["source_access_decision_complete"]:
        raise ValueError(
            "Accounting-change documentation contract unresolved: "
            + ",".join(summary["unresolved_documents"])
        )
    summary.update(
        {
            "formula_sources_verified": True,
            "formula_commit": OPENAP_COMMIT,
            "formula_files": len(_UNIQUE_FORMULA_FILES),
            "formula_signals": len(ACCOUNTING_CHANGE_SIGNALS),
            "raw_source_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    write_accounting_change_outputs(
        summary,
        output_dir=output_dir,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    return summary


__all__ = [
    "ACCOUNTING_CHANGE_BLOCKERS",
    "ACCOUNTING_CHANGE_SIGNALS",
    "FORMULA_REQUIREMENTS",
    "OPENAP_COMMIT",
    "OPENAP_FORMULA_FILES",
    "build_accounting_change_evidence",
    "evaluate_accounting_change_documents",
    "run_accounting_change_source_probe",
    "write_accounting_change_outputs",
]
