"""Pinned formulas and fail-closed evidence for the OpenAP accruals/NOA batch."""

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
    "AbnormalAccruals": {
        "path": (
            "Signals/pyCode/Predictors/"
            "ZZ2_AbnormalAccruals_AbnormalAccrualsPercent.py"
        ),
        "sha256": "3bcd221d7e4099dc71a5760ee086c7a4d0159673840f817b22c2df42415936e4",
    },
    "Accruals": {
        "path": "Signals/pyCode/Predictors/Accruals.py",
        "sha256": "847b1889c54b1c913f94a63647611a98ae908cc33e6364fa7ac2adf5b62d916c",
    },
    "ChNNCOA": {
        "path": "Signals/pyCode/Predictors/ChNNCOA.py",
        "sha256": "a7051153f0a6297a50a26219089af19f4312bfb5a204fdde34d08fd7d990fd1e",
    },
    "DelCOA": {
        "path": "Signals/pyCode/Predictors/DelCOA.py",
        "sha256": "b9d0732718ba6879fafcd966913db75cbfdc4295d97f7b077b660e24a60d9d09",
    },
    "DelCOL": {
        "path": "Signals/pyCode/Predictors/DelCOL.py",
        "sha256": "b3b263ac8ac1cd7c01bf54bbb0e9f160205f474ef091ebfa5b798777d817dcce",
    },
    "DelFINL": {
        "path": "Signals/pyCode/Predictors/DelFINL.py",
        "sha256": "96f66ea157938cf8b7583c4b0dcd3bd230e105d28aa8bd455f78fef99d3b4c85",
    },
    "DelLTI": {
        "path": "Signals/pyCode/Predictors/DelLTI.py",
        "sha256": "8955523b4a82e04fe113cbc723e56f8e7f2046c4b06fef9ecf1a96efc3baa422",
    },
    "DelNetFin": {
        "path": "Signals/pyCode/Predictors/DelNetFin.py",
        "sha256": "1830473d43cb94fcca0bf59d9c8f0403fc77a3617a96f517402fbe73e47344fa",
    },
    "NOA": {
        "path": "Signals/pyCode/Predictors/NOA.py",
        "sha256": "0210dfc4111cb3af1a924137a780da81f664c998d43852fe3b3e4cb657e558a2",
    },
    "PctTotAcc": {
        "path": "Signals/pyCode/Predictors/PctTotAcc.py",
        "sha256": "938a1d8e183c328ab9162b1412ebd1be99a90673656884f46ca3cc9a56e5ae03",
    },
    "TotalAccruals": {
        "path": "Signals/pyCode/Predictors/TotalAccruals.py",
        "sha256": "574589faf026f7e09821bec93fe83520ce46180a8bb1cdd8e0bead082e344975",
    },
    "dNoa": {
        "path": "Signals/pyCode/Predictors/dNoa.py",
        "sha256": "6365154204a05b8e600148e7d6954d5c0cf3d419ac16f86dd7def78470b9b1fa",
    },
}

ACCRUALS_NOA_SIGNALS = frozenset(OPENAP_FORMULA_FILES)
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")


def _requirement(
    *,
    formula: str,
    exact_inputs: str,
    timing: str,
    identity: str,
    filters: str = "none",
    cross_section: str = "none",
    window_months: int = 12,
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
        "minimum_industry_observations": minimum_industry_observations,
    }


FORMULA_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "AbnormalAccruals": _requirement(
        formula=(
            "OLS residual of (ib-CFO)/lag_at on 1/lag_at, "
            "delta_sale/lag_at and ppegt/lag_at; CFO uses oancf or the "
            "fopt balance-sheet fallback"
        ),
        exact_inputs=(
            "Compustat_at;oancf;fopt;act;che;lct;dlc;ib;sale;ppegt;ni;"
            "sic;fyear;datadate;CRSP_exchcd;monthly_time_avail_m"
        ),
        timing="annual filings expanded causally for no more than 12 months",
        identity="historical GVKEY to PERMNO validity intervals",
        filters=(
            "trim all regressors at 0.1% and 99.9% by fyear; minimum six "
            "observations per fyear-SIC2; exclude NASDAQ before 1982"
        ),
        cross_section="fyear_sic2_ols",
        minimum_industry_observations=6,
    ),
    "Accruals": _requirement(
        formula=(
            "(delta_act-delta_che-(delta_lct-delta_dlc-delta_txp)-dp) "
            "/ average total assets; missing txp becomes zero"
        ),
        exact_inputs="Compustat_txp;act;che;lct;dlc;at;dp;monthly_time_avail_m",
        timing="12-month trailing values known by each formation month",
        identity="historical GVKEY to PERMNO validity intervals",
    ),
    "ChNNCOA": _requirement(
        formula=(
            "12-month change in ((at-act-ivao)-(lt-dlc-dltt))/at"
        ),
        exact_inputs="Compustat_at;act;ivao;lt;dlc;dltt;monthly_time_avail_m",
        timing="12-month trailing values known by each formation month",
        identity="historical GVKEY to PERMNO validity intervals",
    ),
    "DelCOA": _requirement(
        formula="delta(act-che)/(0.5*(at+lag12_at))",
        exact_inputs="Compustat_at;act;che;monthly_time_avail_m",
        timing="12-month trailing values known by each formation month",
        identity="historical GVKEY to PERMNO validity intervals",
    ),
    "DelCOL": _requirement(
        formula="delta(lct-dlc)/(0.5*(at+lag12_at))",
        exact_inputs="Compustat_at;lct;dlc;monthly_time_avail_m",
        timing="12-month trailing values known by each formation month",
        identity="historical GVKEY to PERMNO validity intervals",
    ),
    "DelFINL": _requirement(
        formula=(
            "delta(dltt+dlc+pstk)/(0.5*(at+lag12_at)); "
            "pstk missing becomes zero"
        ),
        exact_inputs="Compustat_at;pstk;dltt;dlc;monthly_time_avail_m",
        timing="exact 12-month calendar lag known by each formation month",
        identity="historical GVKEY to PERMNO validity intervals",
    ),
    "DelLTI": _requirement(
        formula="delta(ivao)/(0.5*(at+lag12_at))",
        exact_inputs="Compustat_at;ivao;monthly_time_avail_m",
        timing="exact 12-month calendar lag known by each formation month",
        identity="historical GVKEY to PERMNO validity intervals",
    ),
    "DelNetFin": _requirement(
        formula=(
            "delta((ivst+ivao)-(dltt+dlc+pstk))/(0.5*(at+lag12_at)); "
            "pstk missing becomes zero"
        ),
        exact_inputs=(
            "Compustat_at;pstk;dltt;dlc;ivst;ivao;monthly_time_avail_m"
        ),
        timing="exact 12-month calendar lag known by each formation month",
        identity="historical GVKEY to PERMNO validity intervals",
    ),
    "NOA": _requirement(
        formula="((at-che)-(at-dltt-mib-dc-ceq))/lag12_at",
        exact_inputs="Compustat_at;che;dltt;mib;dc;ceq;monthly_time_avail_m",
        timing="12-month lagged total assets known by each formation month",
        identity="historical GVKEY to PERMNO validity intervals",
    ),
    "PctTotAcc": _requirement(
        formula=(
            "(ni-(prstkcc-sstk+dvt+oancf+fincf+ivncf))/absolute ni"
        ),
        exact_inputs=(
            "Compustat_ni;prstkcc;sstk;dvt;oancf;fincf;ivncf;"
            "monthly_time_avail_m"
        ),
        timing="cash-flow filing accepted before each formation month",
        identity="historical GVKEY to PERMNO validity intervals",
        window_months=1,
    ),
    "TotalAccruals": _requirement(
        formula=(
            "year <= 1989: delta working-capital, noncurrent and financial "
            "components; year > 1989: ni-(oancf+ivncf+fincf)+"
            "sstk-prstkc-dv; divide by lag12_at; selected component fields "
            "missing become zero"
        ),
        exact_inputs=(
            "Compustat_ivao;ivst;dltt;dlc;pstk;sstk;prstkc;dv;act;che;"
            "lct;at;lt;ni;oancf;ivncf;fincf;monthly_time_avail_m"
        ),
        timing="year-regime formula and 12-month lag known by formation month",
        identity="historical GVKEY to PERMNO validity intervals",
    ),
    "dNoa": _requirement(
        formula=(
            "delta((at-che)-(at-dltt-mib-dlc-pstk-ceq))/lag12_at; "
            "missing debt, minority interest and preferred stock become zero"
        ),
        exact_inputs=(
            "Compustat_at;che;dltt;dlc;mib;pstk;ceq;monthly_time_avail_m"
        ),
        timing="exact 12-month calendar lag known by each formation month",
        identity="historical GVKEY to PERMNO validity intervals",
    ),
}


ACCRUALS_NOA_BLOCKERS = {
    "AbnormalAccruals": (
        "accruals_noa_source_blocked:exact_compustat_accrual_ols_fields+"
        "crsp_exchcd+fyear_sic2_ols_min6_and_winsorization+pre2009_history+"
        "historical_gvkey_permno_identity+coverage_fidelity_unmeasured"
    ),
    "Accruals": (
        "accruals_noa_source_blocked:exact_compustat_txp_act_che_lct_dlc_at_dp+"
        "missing_txp_semantics+pre2009_history+historical_gvkey_permno_identity+"
        "coverage_fidelity_unmeasured"
    ),
    "ChNNCOA": (
        "accruals_noa_source_blocked:exact_compustat_at_act_ivao_lt_dlc_dltt+"
        "12m_noa_change+pre2009_history+historical_gvkey_permno_identity+"
        "coverage_fidelity_unmeasured"
    ),
    "DelCOA": (
        "accruals_noa_source_blocked:exact_compustat_at_act_che+12m_average_assets+"
        "pre2009_history+historical_gvkey_permno_identity+coverage_fidelity_unmeasured"
    ),
    "DelCOL": (
        "accruals_noa_source_blocked:exact_compustat_at_lct_dlc+12m_average_assets+"
        "pre2009_history+historical_gvkey_permno_identity+coverage_fidelity_unmeasured"
    ),
    "DelFINL": (
        "accruals_noa_source_blocked:exact_compustat_at_pstk_dltt_dlc+"
        "pstk_missing_zero_semantics+pre2009_history+historical_gvkey_permno_identity+"
        "coverage_fidelity_unmeasured"
    ),
    "DelLTI": (
        "accruals_noa_source_blocked:exact_compustat_at_ivao+12m_calendar_lag+"
        "pre2009_history+historical_gvkey_permno_identity+coverage_fidelity_unmeasured"
    ),
    "DelNetFin": (
        "accruals_noa_source_blocked:exact_compustat_at_pstk_dltt_dlc_ivst_ivao+"
        "pstk_missing_zero_semantics+pre2009_history+historical_gvkey_permno_identity+"
        "coverage_fidelity_unmeasured"
    ),
    "NOA": (
        "accruals_noa_source_blocked:exact_compustat_at_che_dltt_mib_dc_ceq+"
        "dc_semantics+pre2009_history+historical_gvkey_permno_identity+"
        "coverage_fidelity_unmeasured"
    ),
    "PctTotAcc": (
        "accruals_noa_source_blocked:exact_compustat_ni_prstkcc_sstk_dvt_oancf_fincf_ivncf+"
        "cashflow_semantics+pre2009_history+historical_gvkey_permno_identity+"
        "coverage_fidelity_unmeasured"
    ),
    "TotalAccruals": (
        "accruals_noa_source_blocked:exact_compustat_balance_sheet_and_cashflow_fields+"
        "pre1990_formula_regime+pre2009_history+historical_gvkey_permno_identity+"
        "coverage_fidelity_unmeasured"
    ),
    "dNoa": (
        "accruals_noa_source_blocked:exact_compustat_at_che_dltt_dlc_mib_pstk_ceq+"
        "missing_component_zero_semantics+pre2009_history+"
        "historical_gvkey_permno_identity+coverage_fidelity_unmeasured"
    ),
}


def evaluate_accruals_noa_documents(
    documents: Mapping[str, str],
    *,
    access_errors: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Reuse the verified official accounting/identity decision contract."""

    return evaluate_complex_accounting_documents(
        documents,
        access_errors=access_errors,
    )


def build_accruals_noa_evidence(
    probe: Mapping[str, Any],
    *,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> pd.DataFrame:
    """Build twelve signal-specific blockers without promoting partial mappings."""

    valid = (
        probe.get("source_access_decision_complete") is True
        and probe.get("unresolved_documents") == []
        and probe.get("formula_sources_verified") is True
        and probe.get("formula_files") == len(ACCRUALS_NOA_SIGNALS)
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
        raise ValueError("Invalid or incomplete accruals/NOA evidence")
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
                "blocking_reason": ACCRUALS_NOA_BLOCKERS[signal],
                "evidence_run_url": str(evidence_run_url),
                "evidence_artifact": str(evidence_artifact).strip(),
                "implementation_commit": str(implementation_commit),
            }
            for signal in sorted(ACCRUALS_NOA_SIGNALS)
        ]
    )


def write_accruals_noa_outputs(
    probe: Mapping[str, Any],
    *,
    output_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> None:
    """Write formula and documentary evidence only; never retain source data."""

    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = build_accruals_noa_evidence(
        probe,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    (output_dir / "accruals_noa_source_probe.json").write_text(
        json.dumps(dict(probe), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    pd.DataFrame(SOURCE_ASSESSMENTS).to_csv(
        output_dir / "accruals_noa_source_assessment.csv",
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
        for signal in sorted(ACCRUALS_NOA_SIGNALS)
    ]
    pd.DataFrame(requirements).to_csv(
        output_dir / "accruals_noa_formula_requirements.csv",
        index=False,
    )
    evidence.to_csv(output_dir / "accruals_noa_batch_evidence.csv", index=False)
    blocked_docs = ", ".join(probe.get("access_blocked_documents", []))
    report = "\n".join(
        (
            "# OpenAP accruals and NOA source probe",
            "",
            "- Twelve current OpenAP formula files are pinned by commit and SHA-256.",
            "- SEC FSD is as-filed XBRL from 2009, not standardized Compustat history.",
            "- Several formulas require pre-2009 or pre-1990 observations.",
            "- OpenFIGI does not supply the historical PERMNO validity spine.",
            "- Exact CRSP and Compustat inputs remain subscriber or licensed products.",
            f"- Official document access blockers: {blocked_docs or 'none'}.",
            "- No filings, fundamentals or market observations were retained.",
            "- Strict approvals: 0. All twelve signals remain fail-closed.",
            "",
        )
    )
    (output_dir / "ACCRUALS_NOA_SOURCE_PROBE_REPORT.md").write_text(
        report,
        encoding="utf-8",
    )


def run_accruals_noa_source_probe(
    *,
    output_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> dict[str, Any]:
    """Verify pinned formulas and official documents without source observations."""

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
    summary = evaluate_accruals_noa_documents(
        documents,
        access_errors=access_errors,
    )
    if not summary["source_access_decision_complete"]:
        raise ValueError(
            "Accruals/NOA documentation contract unresolved: "
            + ",".join(summary["unresolved_documents"])
        )
    summary.update(
        {
            "formula_sources_verified": True,
            "formula_commit": OPENAP_COMMIT,
            "formula_files": len(OPENAP_FORMULA_FILES),
            "formula_signals": len(ACCRUALS_NOA_SIGNALS),
            "raw_source_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    write_accruals_noa_outputs(
        summary,
        output_dir=output_dir,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    return summary


__all__ = [
    "ACCRUALS_NOA_BLOCKERS",
    "ACCRUALS_NOA_SIGNALS",
    "FORMULA_REQUIREMENTS",
    "OPENAP_COMMIT",
    "OPENAP_FORMULA_FILES",
    "build_accruals_noa_evidence",
    "evaluate_accruals_noa_documents",
    "run_accruals_noa_source_probe",
    "write_accruals_noa_outputs",
]
