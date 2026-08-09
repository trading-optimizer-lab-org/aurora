"""Pinned formulas and fail-closed evidence for OpenAP financing and issuance."""

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
    "CompEquIss": {
        "path": "Signals/pyCode/Predictors/CompEquIss.py",
        "sha256": "d87a14114fbd43039f32c71bec6c42d017fedaf0130f8f1d58cc227f899b808b",
    },
    "CompositeDebtIssuance": {
        "path": "Signals/pyCode/Predictors/CompositeDebtIssuance.py",
        "sha256": "0ed0dacaca27d2d67a98f1793a6827702a7e73b631491a1195008ba012f68665",
    },
    "ConvDebt": {
        "path": "Signals/pyCode/Predictors/ConvDebt.py",
        "sha256": "71b49dbf704bfc00260084f27442eec35fe26f82200c0c32d767a0ef34a2bcab",
    },
    "DebtIssuance": {
        "path": "Signals/pyCode/Predictors/DebtIssuance.py",
        "sha256": "be86cb9cf972fd41905e45bbab7505dd99da88c0e888a47604998beb102f0816",
    },
    "DelEqu": {
        "path": "Signals/pyCode/Predictors/DelEqu.py",
        "sha256": "a040398b319e60cba5bfa8438f24411e39ed8d06a4166b78fc107ba772e2e720",
    },
    "NetDebtFinance": {
        "path": "Signals/pyCode/Predictors/NetDebtFinance.py",
        "sha256": "e8412606b15fe6eba89f37e301b1e8978a963d6798c8494bc34c15b14b3150d6",
    },
    "NetEquityFinance": {
        "path": "Signals/pyCode/Predictors/NetEquityFinance.py",
        "sha256": "ede836d5312897d3b4e4ba843c007b70b859f5f07790f8c50db10f8f2f9bb385",
    },
    "NetPayoutYield": {
        "path": "Signals/pyCode/Predictors/NetPayoutYield.py",
        "sha256": "4a30a7eeee64e52bcc4c609ce5134ac873bc1cff7b7e25ace9282f7887a79afe",
    },
    "PayoutYield": {
        "path": "Signals/pyCode/Predictors/PayoutYield.py",
        "sha256": "d9cd4c9f27364929ac0889ed48149f6d7b509c9a6f1d0dc1cde272f2bd8229db",
    },
    "ShareIss1Y": {
        "path": "Signals/pyCode/Predictors/ShareIss1Y.py",
        "sha256": "adc05d494eb6df3cfd54652d25de00346f396d09b4d5cbb78896b18d6aae5457",
    },
    "ShareIss5Y": {
        "path": "Signals/pyCode/Predictors/ShareIss5Y.py",
        "sha256": "6d45e71a7756058a4b8ffcbbedcbfe79ff984bf5b01f497b5f770dca1d454d26",
    },
}

FINANCING_ISSUANCE_SIGNALS = frozenset(OPENAP_FORMULA_FILES)
FINANCING_ISSUANCE_CRSP_ONLY_SIGNALS = frozenset(
    {"CompEquIss", "ShareIss1Y", "ShareIss5Y"}
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


_CRSP_IDENTITY = "historical CRSP PERMNO validity across corporate actions"
_LINKED_IDENTITY = "historical GVKEY to PERMNO/PERMCO validity intervals"

FORMULA_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "CompEquIss": _requirement(
        formula=(
            "log(mve_c/lag60_mve_c)-buy_and_hold_60m, where buy_and_hold uses "
            "the cumulative product of 1+ret"
        ),
        exact_inputs="CRSP_ret;mve_c;permno;monthly_time_avail_m",
        timing="calendar-validated 60-month lags for return index and mve_c",
        identity=_CRSP_IDENTITY,
        window_months=60,
    ),
    "CompositeDebtIssuance": _requirement(
        formula="log((dltt+dlc)/lag60(dltt+dlc))",
        exact_inputs="Compustat_dltt;dlc;permno;monthly_time_avail_m",
        timing=(
            "exact 60-calendar-month match first, then the current OpenAP "
            "60-row fallback when the exact match is missing"
        ),
        identity=_LINKED_IDENTITY,
        window_months=60,
    ),
    "ConvDebt": _requirement(
        formula="1 if nonmissing dc!=0 or nonmissing cshrc!=0; otherwise 0",
        exact_inputs="Compustat_dc;cshrc;permno;monthly_time_avail_m",
        timing="annual filing value expanded on OpenAP monthly availability",
        identity=_LINKED_IDENTITY,
    ),
    "DebtIssuance": _requirement(
        formula="1 if nonmissing dltis>0; otherwise 0",
        exact_inputs=(
            "Compustat_ceq;dltis;CRSP_mve_permco;shrcd;permno;monthly_time_avail_m"
        ),
        timing="accounting and same-month company market inputs joined exactly",
        identity=_LINKED_IDENTITY,
        filters="set missing when shrcd>11 or log(ceq/mve_permco) is missing",
    ),
    "DelEqu": _requirement(
        formula="(ceq-lag12_ceq)/(0.5*(at+lag12_at))",
        exact_inputs="Compustat_ceq;at;permno;monthly_time_avail_m",
        timing="exact calendar 12-month self-join for ceq and at",
        identity=_LINKED_IDENTITY,
        window_months=12,
    ),
    "NetDebtFinance": _requirement(
        formula=(
            "(dltis-dltr+dlcch)/(0.5*(at+lag12_at)); "
            "dlcch missing becomes zero"
        ),
        exact_inputs="Compustat_dltis;dltr;dlcch;at;permno;monthly_time_avail_m",
        timing="current OpenAP positional 12-row lag of at after permno-month sort",
        identity=_LINKED_IDENTITY,
        filters="abs(NetDebtFinance)>1 becomes missing",
        window_months=12,
    ),
    "NetEquityFinance": _requirement(
        formula="(sstk-prstkc-dv)/(0.5*(at+lag12_at))",
        exact_inputs="Compustat_sstk;prstkc;dv;at;permno;monthly_time_avail_m",
        timing="current OpenAP positional 12-row lag of at after permno-month sort",
        identity=_LINKED_IDENTITY,
        filters="abs(NetEquityFinance)>1 becomes missing",
        window_months=12,
    ),
    "NetPayoutYield": _requirement(
        formula="(dvc+prstkc-sstk)/lag6_mve_permco",
        exact_inputs=(
            "Compustat_dvc;prstkc;sstk;sic;ceq;CRSP_mve_permco;permno;"
            "monthly_time_avail_m"
        ),
        timing="exact six-calendar-month company market-equity lag",
        identity=_LINKED_IDENTITY,
        filters=(
            "remove true zeros but preserve component cancellation as 1e-19; "
            "exclude SIC 6000-6999; require ceq>0 or missing, at least 24 "
            "observations, and a finite nonmissing value"
        ),
        window_months=6,
    ),
    "PayoutYield": _requirement(
        formula="(dvc+prstkc+pstkrv)/lag6_mve_permco",
        exact_inputs=(
            "Compustat_dvc;prstkc;pstkrv;sic;ceq;datadate;CRSP_mve_permco;"
            "permno;monthly_time_avail_m"
        ),
        timing="exact six-calendar-month company market-equity lag",
        identity=_LINKED_IDENTITY,
        filters=(
            "nonpositive yield becomes missing; exclude SIC 6000-6999; require "
            "ceq>0 or missing, at least 24 observations, and a finite value"
        ),
        window_months=6,
    ),
    "ShareIss1Y": _requirement(
        formula=(
            "(lag6(shrout*cfacshr)-lag18(shrout*cfacshr))/"
            "lag18(shrout*cfacshr)"
        ),
        exact_inputs="CRSP_shrout;cfacshr;permno;monthly_time_avail_m",
        timing="exact calendar 6-month and 18-month lags",
        identity=_CRSP_IDENTITY,
        window_months=18,
    ),
    "ShareIss5Y": _requirement(
        formula=(
            "(lag5(shrout*cfacshr)-lag65(shrout*cfacshr))/"
            "lag65(shrout*cfacshr)"
        ),
        exact_inputs="CRSP_shrout;cfacshr;permno;monthly_time_avail_m",
        timing="exact calendar 5-month and 65-month lags",
        identity=_CRSP_IDENTITY,
        window_months=65,
    ),
}


FINANCING_ISSUANCE_BLOCKERS = {
    "CompEquIss": (
        "financing_issuance_source_blocked:exact_crsp_ret_mve_c+"
        "60m_calendar_validated_return_and_market_value_history+historical_permno_"
        "identity+coverage_fidelity_unmeasured"
    ),
    "CompositeDebtIssuance": (
        "financing_issuance_source_blocked:exact_compustat_dltt_dlc+"
        "60m_calendar_then_positional_fallback_semantics+pre2009_history+"
        "historical_gvkey_permno_identity+coverage_fidelity_unmeasured"
    ),
    "ConvDebt": (
        "financing_issuance_source_blocked:exact_compustat_dc_cshrc+"
        "nonmissing_nonzero_indicator_semantics+pre2009_history+historical_gvkey_"
        "permno_identity+coverage_fidelity_unmeasured"
    ),
    "DebtIssuance": (
        "financing_issuance_source_blocked:exact_compustat_ceq_dltis+"
        "crsp_mve_permco_shrcd+bm_and_share_code_filters+pre2009_history+"
        "historical_gvkey_permno_permco_identity+coverage_fidelity_unmeasured"
    ),
    "DelEqu": (
        "financing_issuance_source_blocked:exact_compustat_at_ceq+"
        "12m_calendar_lag_semantics+pre2009_history+historical_gvkey_permno_"
        "identity+coverage_fidelity_unmeasured"
    ),
    "NetDebtFinance": (
        "financing_issuance_source_blocked:exact_compustat_dlcch_dltis_dltr_at+"
        "missing_zero_positional_12m_lag_and_abs_filter+pre2009_history+"
        "historical_gvkey_permno_identity+coverage_fidelity_unmeasured"
    ),
    "NetEquityFinance": (
        "financing_issuance_source_blocked:exact_compustat_sstk_prstkc_dv_at+"
        "positional_12m_lag_and_abs_filter+pre2009_history+historical_gvkey_"
        "permno_identity+coverage_fidelity_unmeasured"
    ),
    "NetPayoutYield": (
        "financing_issuance_source_blocked:exact_compustat_dvc_prstkc_sstk_sic_"
        "ceq+crsp_mve_permco+6m_lag_zero_sic_ceq_24obs_filters+pre2009_history+"
        "historical_gvkey_permno_permco_identity+coverage_fidelity_unmeasured"
    ),
    "PayoutYield": (
        "financing_issuance_source_blocked:exact_compustat_dvc_prstkc_pstkrv_sic_"
        "ceq_datadate+crsp_mve_permco+6m_lag_positive_sic_ceq_24obs_filters+"
        "pre2009_history+historical_gvkey_permno_permco_identity+coverage_fidelity_"
        "unmeasured"
    ),
    "ShareIss1Y": (
        "financing_issuance_source_blocked:exact_crsp_shrout_cfacshr+"
        "6m_18m_calendar_lags+historical_permno_corporate_action_identity+"
        "coverage_fidelity_unmeasured"
    ),
    "ShareIss5Y": (
        "financing_issuance_source_blocked:exact_crsp_shrout_cfacshr+"
        "5m_65m_calendar_lags+historical_permno_corporate_action_identity+"
        "coverage_fidelity_unmeasured"
    ),
}


def evaluate_financing_issuance_documents(
    documents: Mapping[str, str],
    *,
    access_errors: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Reuse the official accounting and historical-identity decision contract."""

    return evaluate_complex_accounting_documents(
        documents,
        access_errors=access_errors,
    )


def build_financing_issuance_evidence(
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
        and probe.get("formula_signals") == len(FINANCING_ISSUANCE_SIGNALS)
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
        raise ValueError("Invalid or incomplete financing issuance evidence")
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
                "blocking_reason": FINANCING_ISSUANCE_BLOCKERS[signal],
                "evidence_run_url": str(evidence_run_url),
                "evidence_artifact": str(evidence_artifact).strip(),
                "implementation_commit": str(implementation_commit),
            }
            for signal in sorted(FINANCING_ISSUANCE_SIGNALS)
        ]
    )


def write_financing_issuance_outputs(
    probe: Mapping[str, Any],
    *,
    output_dir: Path,
    evidence_run_url: str,
    evidence_artifact: str,
    implementation_commit: str,
) -> None:
    """Write formula and documentary evidence only; never retain source data."""

    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = build_financing_issuance_evidence(
        probe,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    (output_dir / "financing_issuance_source_probe.json").write_text(
        json.dumps(dict(probe), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    pd.DataFrame(SOURCE_ASSESSMENTS).to_csv(
        output_dir / "financing_issuance_source_assessment.csv",
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
        for signal in sorted(FINANCING_ISSUANCE_SIGNALS)
    ]
    pd.DataFrame(requirements).to_csv(
        output_dir / "financing_issuance_formula_requirements.csv",
        index=False,
    )
    evidence.to_csv(
        output_dir / "financing_issuance_batch_evidence.csv",
        index=False,
    )
    blocked_docs = ", ".join(probe.get("access_blocked_documents", []))
    report = "\n".join(
        (
            "# OpenAP financing and issuance source probe",
            "",
            "- Eleven signals map to eleven current OpenAP files pinned by commit and SHA-256.",
            "- Three formulas require exact CRSP history; eight require exact Compustat semantics and most also CRSP data or identity.",
            "- SEC FSD is as-filed XBRL from 2009, not standardized Compustat history.",
            "- OpenFIGI does not provide historical PERMNO/PERMCO validity intervals.",
            "- Exact CRSP and Compustat inputs remain subscriber or licensed products.",
            f"- Official document access blockers: {blocked_docs or 'none'}.",
            "- No filings, fundamentals or market observations were retained.",
            "- Strict approvals: 0. All eleven signals remain fail-closed.",
            "",
        )
    )
    (output_dir / "FINANCING_ISSUANCE_SOURCE_PROBE_REPORT.md").write_text(
        report,
        encoding="utf-8",
    )


def run_financing_issuance_source_probe(
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
    summary = evaluate_financing_issuance_documents(
        documents,
        access_errors=access_errors,
    )
    if not summary["source_access_decision_complete"]:
        raise ValueError(
            "Financing issuance documentation contract unresolved: "
            + ",".join(summary["unresolved_documents"])
        )
    summary.update(
        {
            "formula_sources_verified": True,
            "formula_commit": OPENAP_COMMIT,
            "formula_files": len(_UNIQUE_FORMULA_FILES),
            "formula_signals": len(FINANCING_ISSUANCE_SIGNALS),
            "raw_source_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    write_financing_issuance_outputs(
        summary,
        output_dir=output_dir,
        evidence_run_url=evidence_run_url,
        evidence_artifact=evidence_artifact,
        implementation_commit=implementation_commit,
    )
    return summary


__all__ = [
    "FINANCING_ISSUANCE_BLOCKERS",
    "FINANCING_ISSUANCE_CRSP_ONLY_SIGNALS",
    "FINANCING_ISSUANCE_SIGNALS",
    "FORMULA_REQUIREMENTS",
    "OPENAP_COMMIT",
    "OPENAP_FORMULA_FILES",
    "build_financing_issuance_evidence",
    "evaluate_financing_issuance_documents",
    "run_financing_issuance_source_probe",
    "write_financing_issuance_outputs",
]
