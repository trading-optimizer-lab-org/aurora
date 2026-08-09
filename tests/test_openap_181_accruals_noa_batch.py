from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pandas as pd


EXPECTED_SIGNALS = {
    "AbnormalAccruals",
    "Accruals",
    "ChNNCOA",
    "DelCOA",
    "DelCOL",
    "DelFINL",
    "DelLTI",
    "DelNetFin",
    "NOA",
    "PctTotAcc",
    "TotalAccruals",
    "dNoa",
}


def _module():
    return import_module("aurora.research.openap_181.accruals_noa_batch")


def _official_document_fixtures() -> dict[str, str]:
    return {
        "sec_fsd": (
            "Financial Statement Data Sets contain numeric information from primary "
            "financial statements extracted from XBRL and presented without change as "
            "filed. Quarterly files cover January 2009 onward."
        ),
        "sec_edgar_apis": (
            "XBRL was first required in 2009. Facts use standard US-GAAP or IFRS "
            "taxonomies, and companies can extend them with custom taxonomies."
        ),
        "openfigi": (
            "The free OpenFIGI API maps third-party identifiers to FIGIs and returns "
            "instrument metadata. It does not publish PERMNO validity intervals."
        ),
        "crsp": (
            "CRSP subscribers use proprietary permanent identifier PERMNO to track US "
            "equities over time and across corporate restructurings."
        ),
        "compustat": (
            "Compustat Financials supplies standardized financial items, historical "
            "snapshots and point-in-time data as a licensed S&P Global product."
        ),
    }


def _valid_probe() -> dict[str, object]:
    module = _module()
    probe = module.evaluate_accruals_noa_documents(_official_document_fixtures())
    probe.update(
        {
            "formula_sources_verified": True,
            "formula_files": 12,
            "raw_source_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    return probe


def test_accruals_noa_universe_and_formula_hashes_are_frozen() -> None:
    module = _module()

    assert module.ACCRUALS_NOA_SIGNALS == frozenset(EXPECTED_SIGNALS)
    assert set(module.FORMULA_REQUIREMENTS) == EXPECTED_SIGNALS
    assert set(module.ACCRUALS_NOA_BLOCKERS) == EXPECTED_SIGNALS
    assert set(module.OPENAP_FORMULA_FILES) == EXPECTED_SIGNALS
    assert module.OPENAP_COMMIT == "8db892442c2c3a3779b0f1eac4370d3655be15a1"
    assert module.OPENAP_FORMULA_FILES["AbnormalAccruals"]["sha256"] == (
        "3bcd221d7e4099dc71a5760ee086c7a4d0159673840f817b22c2df42415936e4"
    )
    assert module.OPENAP_FORMULA_FILES["NOA"]["sha256"] == (
        "0210dfc4111cb3af1a924137a780da81f664c998d43852fe3b3e4cb657e558a2"
    )
    assert module.OPENAP_FORMULA_FILES["TotalAccruals"]["sha256"] == (
        "574589faf026f7e09821bec93fe83520ce46180a8bb1cdd8e0bead082e344975"
    )
    assert all(
        len(metadata["sha256"]) == 64
        for metadata in module.OPENAP_FORMULA_FILES.values()
    )


def test_exact_formula_requirements_preserve_openap_semantics() -> None:
    module = _module()
    requirements = module.FORMULA_REQUIREMENTS

    assert requirements["Accruals"]["window_months"] == 12
    assert "missing txp becomes zero" in requirements["Accruals"]["formula"]
    assert "average total assets" in requirements["Accruals"]["formula"]
    assert requirements["AbnormalAccruals"]["cross_section"] == "fyear_sic2_ols"
    assert requirements["AbnormalAccruals"]["minimum_industry_observations"] == 6
    assert "0.1% and 99.9%" in requirements["AbnormalAccruals"]["filters"]
    assert "NASDAQ before 1982" in requirements["AbnormalAccruals"]["filters"]
    assert "ivao" in requirements["ChNNCOA"]["exact_inputs"]
    assert "pstk missing becomes zero" in requirements["DelFINL"]["formula"]
    assert "ivst" in requirements["DelNetFin"]["exact_inputs"]
    assert "dc" in requirements["NOA"]["exact_inputs"]
    assert "absolute ni" in requirements["PctTotAcc"]["formula"]
    assert "year <= 1989" in requirements["TotalAccruals"]["formula"]
    assert "year > 1989" in requirements["TotalAccruals"]["formula"]
    assert "missing debt, minority interest and preferred stock become zero" in (
        requirements["dNoa"]["formula"]
    )
    assert all(
        requirements[signal]["window_months"] == 12
        for signal in EXPECTED_SIGNALS - {"AbnormalAccruals", "PctTotAcc"}
    )


def test_official_documents_prove_no_exact_free_route() -> None:
    module = _module()
    summary = module.evaluate_accruals_noa_documents(_official_document_fixtures())

    assert summary["official_documents_verified"] is True
    assert summary["source_access_decision_complete"] is True
    assert summary["unresolved_documents"] == []
    assert summary["sec_as_filed_since_2009_verified"] is True
    assert summary["sec_custom_taxonomies_verified"] is True
    assert summary["openfigi_not_permno_history"] is True
    assert summary["crsp_subscription_and_permno_verified"] is True
    assert summary["compustat_standardized_pit_product_verified"] is True
    assert summary["exact_free_authorized_source_found"] is False
    assert summary["strict_approved"] == 0


def test_access_errors_are_recorded_without_inventing_document_verification() -> None:
    module = _module()
    documents = _official_document_fixtures()
    documents["sec_edgar_apis"] = ""
    summary = module.evaluate_accruals_noa_documents(
        documents,
        access_errors={"sec_edgar_apis": "HTTP Error 403: Forbidden"},
    )

    assert summary["official_documents_verified"] is False
    assert summary["source_access_decision_complete"] is True
    assert summary["access_blocked_documents"] == ["sec_edgar_apis"]
    assert summary["unresolved_documents"] == []
    assert summary["exact_free_authorized_source_found"] is False


def test_batch_evidence_is_signal_specific_and_fail_closed() -> None:
    module = _module()
    evidence = module.build_accruals_noa_evidence(
        _valid_probe(),
        evidence_run_url="https://github.com/example/aurora/actions/runs/123",
        evidence_artifact="openap-181-accruals-noa-source-probe-results",
        implementation_commit="a" * 40,
    )

    assert set(evidence["signal"]) == EXPECTED_SIGNALS
    assert len(evidence) == evidence["signal"].nunique() == 12
    assert evidence["formula_implemented"].eq(True).all()
    assert evidence["data_pipeline_implemented"].eq(False).all()
    for column in {
        "point_in_time_verified",
        "identity_verified",
        "coverage_measured",
        "fidelity_measured",
        "score_eligible",
    }:
        assert evidence[column].eq(False).all()
    assert evidence["strict_gate_result"].eq("blocked").all()
    assert evidence["blocking_reason"].nunique() == 12
    assert evidence.set_index("signal")["blocking_reason"].to_dict() == (
        module.ACCRUALS_NOA_BLOCKERS
    )


def test_probe_outputs_contain_no_raw_source_data(tmp_path: Path) -> None:
    module = _module()
    module.write_accruals_noa_outputs(
        _valid_probe(),
        output_dir=tmp_path,
        evidence_run_url="https://github.com/example/aurora/actions/runs/123",
        evidence_artifact="openap-181-accruals-noa-source-probe-results",
        implementation_commit="b" * 40,
    )

    expected = {
        "accruals_noa_source_probe.json",
        "accruals_noa_source_assessment.csv",
        "accruals_noa_formula_requirements.csv",
        "accruals_noa_batch_evidence.csv",
        "ACCRUALS_NOA_SOURCE_PROBE_REPORT.md",
    }
    assert {path.name for path in tmp_path.iterdir()} == expected
    evidence = pd.read_csv(tmp_path / "accruals_noa_batch_evidence.csv")
    assert len(evidence) == 12
    assert not any(path.suffix in {".zip", ".parquet"} for path in tmp_path.iterdir())


def test_workflow_is_github_only_sha_pinned_and_fail_closed() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = root / ".github/workflows/openap-181-accruals-noa-source-probe.yml"
    script = root / "scripts/run_openap_181_accruals_noa_source_probe.py"

    assert workflow.is_file()
    assert script.is_file()
    text = workflow.read_text(encoding="utf-8")
    assert "workflow_call:" in text
    assert "source_sha" in text
    assert "Checkout exact implementation revision" in text
    assert "test_openap_181_accruals_noa_batch.py" in text
    assert "accruals_noa_batch_evidence.csv" in text
    assert "strict_approved" in text
    assert "GITHUB_ACTIONS" in text
    assert "OOS_LOCKED" not in text
    assert "FORWARD" not in text
