from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pandas as pd
import pytest

import aurora.research.openap_181.analyst_batch as analyst_batch
from aurora.research.openap_181.analyst_batch import (
    ANALYST_FORMULA_REQUIREMENTS,
    ANALYST_SIGNAL_FAMILIES,
    ANALYST_SIGNALS,
    OPENAP_COMMIT,
    OPENAP_FORMULA_SOURCES,
    SOURCE_ASSESSMENTS,
    build_analyst_batch_evidence,
    evaluate_analyst_source_documents,
    write_analyst_source_probe_outputs,
)


EXPECTED_ANALYST_SIGNALS = {
    "AOP",
    "AnalystRevision",
    "ChangeInRecommendation",
    "ChForecastAccrual",
    "DownRecomm",
    "EarningsForecastDisparity",
    "EarningsStreak",
    "EarningsSurprise",
    "EarnSupBig",
    "ExclExp",
    "FEPS",
    "ForecastDispersion",
    "NumEarnIncrease",
    "PredictedFE",
    "RevenueSurprise",
    "UpRecomm",
    "fgr5yrLag",
    "sfe",
}


def _official_document_fixtures() -> dict[str, str]:
    return {
        "ibes": (
            "LSEG IBES detailed and summary estimates. Broker and analyst identifiers "
            "were reassigned; treat each data vintage as an entirely separate sample. "
            "WRDS subscription and LSEG vendor license are required."
        ),
        "alpha_vantage_docs": (
            "Earnings Estimates returns annual and quarterly EPS and revenue estimates "
            "with analyst count and revision history."
        ),
        "alpha_vantage_terms": (
            "Personal non-commercial use. Commercial use includes investment analysis, "
            "research, testing and monitoring unless agreed otherwise in writing."
        ),
        "fmp_docs": (
            "Financial Estimates API returns projected revenue and earnings per share. "
            "Historical Grades records analyst grades for a stock symbol."
        ),
        "fmp_pricing": (
            "Basic is free with 250 calls per day and five years of historical data for "
            "individual use."
        ),
        "fmp_terms": (
            "Without prior written approval the customer may not create derivative works. "
            "Personal use is strictly non-business and non-commercial."
        ),
        "twelve_data_pricing": (
            "Basic Free has 8 API credits and 800 a day. Grow includes fundamentals data. "
            "Individual plans are for personal, internal and non-commercial purposes."
        ),
        "twelve_data_analysis": (
            "Earnings is available on the Grow plan and above. EPS revisions cover the "
            "last week and month; recommendations return an average recommendation score."
        ),
        "nasdaq_data_link": (
            "Zacks Earnings Estimates ZEE Premium. Zacks Analyst Ratings and Target "
            "Prices ZAR Premium."
        ),
        "zacks": (
            "Historical point-in-time consensus estimates and recommendations are "
            "available through WRDS or directly under a research system license."
        ),
        "intrinio": (
            "EPS Estimates, Long-Term Growth Estimates and Analyst Ratings are Enterprise "
            "products sourced from Zacks; free trial only."
        ),
        "sec_api": (
            "EDGAR APIs require no authentication or API keys. XBRL was first required "
            "in 2009 and Company Facts aggregates standard taxonomy facts across filings."
        ),
        "sec_fsd": (
            "Financial Statement Data Sets include submissions from 4/15/2009. All numeric "
            "data is as filed and includes amendments, redundancies and inconsistencies."
        ),
        "sec_reuse": (
            "All government-created SEC content and EDGAR public filing content are free "
            "to access and reuse."
        ),
    }


def _valid_probe() -> dict[str, object]:
    probe = evaluate_analyst_source_documents(_official_document_fixtures())
    probe.update(
        {
            "formula_sources_verified": True,
            "raw_source_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    return probe


def test_analyst_universe_formula_sources_and_samples_are_frozen() -> None:
    assert ANALYST_SIGNALS == frozenset(EXPECTED_ANALYST_SIGNALS)
    assert set(OPENAP_FORMULA_SOURCES) == EXPECTED_ANALYST_SIGNALS
    assert set(ANALYST_FORMULA_REQUIREMENTS) == EXPECTED_ANALYST_SIGNALS
    assert set(ANALYST_SIGNAL_FAMILIES) == EXPECTED_ANALYST_SIGNALS
    assert OPENAP_COMMIT == "8db892442c2c3a3779b0f1eac4370d3655be15a1"
    assert all(len(item["sha256"]) == 64 for item in OPENAP_FORMULA_SOURCES.values())
    assert {
        signal
        for signal, item in ANALYST_FORMULA_REQUIREMENTS.items()
        if item["sample_start"] <= 2009
    } == EXPECTED_ANALYST_SIGNALS
    assert ANALYST_FORMULA_REQUIREMENTS["EarningsSurprise"]["sample_start"] == 1974
    assert ANALYST_FORMULA_REQUIREMENTS["EarningsSurprise"]["sample_end"] == 1981
    assert ANALYST_FORMULA_REQUIREMENTS["PredictedFE"]["timing"] == (
        "June formation; twelve-month hold; regressors lagged twelve months"
    )
    assert "individual_analyst_id" in ANALYST_FORMULA_REQUIREMENTS[
        "ChangeInRecommendation"
    ]["exact_inputs"]


def test_signal_families_separate_accounting_recommendation_and_mixed_routes() -> None:
    groups: dict[str, set[str]] = {}
    for signal, family in ANALYST_SIGNAL_FAMILIES.items():
        groups.setdefault(family, set()).add(signal)

    assert groups["accounting_compustat"] == {
        "EarningsSurprise",
        "EarnSupBig",
        "NumEarnIncrease",
        "RevenueSurprise",
    }
    assert groups["ibes_recommendations"] == {
        "ChangeInRecommendation",
        "DownRecomm",
        "UpRecomm",
    }
    assert groups["ibes_compustat_crsp_cross_section"] == {"PredictedFE"}
    assert groups["ibes_mixed"] == {
        "AOP",
        "ChForecastAccrual",
        "ExclExp",
        "fgr5yrLag",
        "sfe",
    }


def test_official_documents_prove_no_exact_free_authorized_analyst_source() -> None:
    summary = evaluate_analyst_source_documents(_official_document_fixtures())

    assert summary["official_documents_verified"] is True
    assert summary["source_access_decision_complete"] is True
    assert summary["unresolved_documents"] == []
    assert summary["ibes_commercial_benchmark_verified"] is True
    assert summary["ibes_vintage_identity_risk_verified"] is True
    assert summary["alpha_vantage_aggregate_only"] is True
    assert summary["alpha_vantage_project_use_authorized"] is False
    assert summary["fmp_project_use_authorized"] is False
    assert summary["twelve_data_free_analysis_entitled"] is False
    assert summary["nasdaq_zacks_premium_verified"] is True
    assert summary["sec_free_reuse_authorized"] is True
    assert summary["sec_as_filed_start"] == "2009-04-15"
    assert summary["sec_compustat_equivalence_proven"] is False
    assert summary["exact_free_authorized_source_found"] is False
    assert summary["strict_approved"] == 0


def test_source_access_failure_is_recorded_as_a_concrete_blocker() -> None:
    documents = _official_document_fixtures()
    documents["zacks"] = ""
    summary = evaluate_analyst_source_documents(
        documents,
        access_errors={"zacks": "HTTP Error 403: Forbidden"},
    )

    assert summary["official_documents_verified"] is False
    assert summary["source_access_decision_complete"] is True
    assert summary["access_blocked_documents"] == ["zacks"]
    assert summary["unresolved_documents"] == []
    assert summary["exact_free_authorized_source_found"] is False
    assert summary["strict_approved"] == 0


def test_source_assessments_keep_commercial_and_sec_routes_distinct() -> None:
    sources = {row["source_id"]: row for row in SOURCE_ASSESSMENTS}

    assert sources["lseg_ibes_commercial"]["exact_for_openap"] is True
    assert sources["lseg_ibes_commercial"]["project_use_authorized"] is False
    assert sources["sec_edgar_xbrl"]["project_use_authorized"] is True
    assert sources["sec_edgar_xbrl"]["exact_for_openap"] is False
    assert sources["alpha_vantage_free"]["project_use_authorized"] is False
    assert sources["fmp_basic"]["project_use_authorized"] is False
    assert sources["twelve_data_basic"]["exact_for_openap"] is False
    assert sources["nasdaq_zacks_premium"]["access"] == "paid_subscription"


def test_analyst_evidence_covers_18_signals_with_specific_fail_closed_routes() -> None:
    evidence = build_analyst_batch_evidence(
        _valid_probe(),
        evidence_run_url="https://github.com/example/aurora/actions/runs/12",
        evidence_artifact="openap-181-analyst-source-probe-results",
        implementation_commit="a" * 40,
    ).set_index("signal")

    assert set(evidence.index) == EXPECTED_ANALYST_SIGNALS
    assert evidence["formula_implemented"].eq(True).all()
    for gate in {
        "data_pipeline_implemented",
        "point_in_time_verified",
        "identity_verified",
        "coverage_measured",
        "fidelity_measured",
    }:
        assert evidence[gate].eq(False).all()
    assert evidence["coverage_result"].eq("not_measured").all()
    assert evidence["fidelity_result"].eq("not_measured").all()
    assert evidence["strict_gate_result"].eq("blocked").all()
    assert evidence["blocking_reason"].str.startswith("analyst_source_blocked:").all()
    assert not evidence["blocking_reason"].str.contains(
        "point_in_time_analyst_history_missing_or_unvalidated", regex=False
    ).any()
    assert "individual_analyst_recommendation_vintages" in evidence.loc[
        "ChangeInRecommendation", "blocking_reason"
    ]
    assert "full_cross_sectional_regression_inputs" in evidence.loc[
        "PredictedFE", "blocking_reason"
    ]
    assert "sec_xbrl_to_compustat_epspxq_equivalence" in evidence.loc[
        "EarningsSurprise", "blocking_reason"
    ]
    assert "sec_xbrl_to_compustat_revtq_cshprq_equivalence" in evidence.loc[
        "RevenueSurprise", "blocking_reason"
    ]
    assert evidence["blocking_reason"].nunique() >= 8


def test_analyst_evidence_rejects_incomplete_or_promotable_probe() -> None:
    incomplete = _valid_probe()
    incomplete["source_access_decision_complete"] = False
    incomplete["unresolved_documents"] = ["ibes"]
    with pytest.raises(ValueError, match="Invalid or incomplete analyst probe evidence"):
        build_analyst_batch_evidence(
            incomplete,
            evidence_run_url="https://github.com/example/aurora/actions/runs/12",
            evidence_artifact="openap-181-analyst-source-probe-results",
            implementation_commit="a" * 40,
        )

    promotable = _valid_probe()
    promotable["exact_free_authorized_source_found"] = True
    with pytest.raises(ValueError, match="Invalid or incomplete analyst probe evidence"):
        build_analyst_batch_evidence(
            promotable,
            evidence_run_url="https://github.com/example/aurora/actions/runs/12",
            evidence_artifact="openap-181-analyst-source-probe-results",
            implementation_commit="a" * 40,
        )


def test_analyst_probe_outputs_are_metadata_only(tmp_path: Path) -> None:
    write_analyst_source_probe_outputs(
        _valid_probe(),
        output_dir=tmp_path,
        evidence_run_url="https://github.com/example/aurora/actions/runs/12",
        evidence_artifact="openap-181-analyst-source-probe-results",
        implementation_commit="b" * 40,
    )

    expected = {
        "analyst_source_probe.json",
        "analyst_source_assessment.csv",
        "analyst_formula_requirements.csv",
        "analyst_batch_evidence.csv",
        "ANALYST_SOURCE_PROBE_REPORT.md",
    }
    assert {path.name for path in tmp_path.iterdir()} == expected
    evidence = pd.read_csv(tmp_path / "analyst_batch_evidence.csv")
    formulas = pd.read_csv(tmp_path / "analyst_formula_requirements.csv")
    assert len(evidence) == evidence["signal"].nunique() == 18
    assert len(formulas) == formulas["signal"].nunique() == 18
    assert not any(
        token in path.name.lower()
        for path in tmp_path.iterdir()
        for token in ("raw", "estimate_records", "recommendation_records", "filings")
    )


def test_live_analyst_probe_verifies_pinned_formulas_and_writes_metadata_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    formula_payload = b"# pinned analyst formula fixture\n"
    formula_hash = sha256(formula_payload).hexdigest()
    formula_sources = {
        signal: {
            "path": f"Signals/pyCode/Predictors/{signal}.py",
            "sha256": formula_hash,
        }
        for signal in EXPECTED_ANALYST_SIGNALS
    }
    documents = _official_document_fixtures()
    document_urls = {
        f"fixture_{name}": f"https://official.example/{name}"
        for name in documents
    }
    document_groups = {
        name: (f"fixture_{name}",)
        for name in documents
    }

    def fake_fetch(url: str, *, attempts: int = 4) -> bytes:
        assert attempts >= 1
        if "raw.githubusercontent.com" in url:
            return formula_payload
        name = url.rsplit("/", 1)[-1]
        return documents[name].encode("utf-8")

    monkeypatch.setattr(analyst_batch, "OPENAP_FORMULA_SOURCES", formula_sources)
    monkeypatch.setattr(analyst_batch, "DOCUMENT_URLS", document_urls)
    monkeypatch.setattr(analyst_batch, "DOCUMENT_GROUPS", document_groups)
    monkeypatch.setattr(analyst_batch, "_fetch", fake_fetch)

    summary = analyst_batch.run_analyst_source_probe(
        output_dir=tmp_path,
        evidence_run_url="https://github.com/example/aurora/actions/runs/13",
        evidence_artifact="openap-181-analyst-source-probe-results",
        implementation_commit="c" * 40,
    )

    assert summary["formula_sources_verified"] is True
    assert summary["formula_signals"] == 18
    assert summary["source_access_decision_complete"] is True
    assert summary["exact_free_authorized_source_found"] is False
    assert summary["raw_source_data_downloaded"] is False
    assert summary["raw_files_in_artifact"] is False
    assert summary["locked_opened"] is False
    assert summary["validation_used_for_selection"] is False
    evidence = pd.read_csv(tmp_path / "analyst_batch_evidence.csv")
    assert len(evidence) == evidence["signal"].nunique() == 18
    assert evidence["strict_gate_result"].eq("blocked").all()
