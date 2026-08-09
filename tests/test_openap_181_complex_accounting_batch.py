from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pandas as pd


EXPECTED_SIGNALS = {
    "DelDRC",
    "FR",
    "GrSaleToGrOverhead",
    "OperProfRD",
    "RDAbility",
    "ShareRepurchase",
    "VarCF",
    "realestate",
}


def _module():
    return import_module("aurora.research.openap_181.complex_accounting_batch")


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
    probe = module.evaluate_complex_accounting_documents(
        _official_document_fixtures()
    )
    probe.update(
        {
            "formula_sources_verified": True,
            "formula_files": 8,
            "raw_source_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    return probe


def test_complex_accounting_universe_and_formula_hashes_are_frozen() -> None:
    module = _module()

    assert module.COMPLEX_ACCOUNTING_SIGNALS == frozenset(EXPECTED_SIGNALS)
    assert set(module.FORMULA_REQUIREMENTS) == EXPECTED_SIGNALS
    assert set(module.COMPLEX_ACCOUNTING_BLOCKERS) == EXPECTED_SIGNALS
    assert set(module.OPENAP_FORMULA_FILES) == EXPECTED_SIGNALS
    assert module.OPENAP_COMMIT == "8db892442c2c3a3779b0f1eac4370d3655be15a1"
    assert module.OPENAP_FORMULA_FILES["DelDRC"]["sha256"] == (
        "b2a07c603cd53e3201db79bc7358209c552babe2e41a1695ae9ab716f0bea808"
    )
    assert module.OPENAP_FORMULA_FILES["FR"]["path"].endswith(
        "ZZ1_FR_FRbook.py"
    )
    assert module.OPENAP_FORMULA_FILES["ShareRepurchase"]["sha256"] == (
        "305fdfbcab492ee39605da792a9dd234d565e09cc3816e889793559b8c1f8657"
    )
    assert all(
        len(metadata["sha256"]) == 64
        for metadata in module.OPENAP_FORMULA_FILES.values()
    )


def test_exact_formula_requirements_preserve_openap_semantics() -> None:
    module = _module()
    requirements = module.FORMULA_REQUIREMENTS

    assert requirements["DelDRC"]["window_months"] == 12
    assert "drc" in requirements["DelDRC"]["exact_inputs"]
    assert "ceq" in requirements["DelDRC"]["filters"]
    assert "pbnaa" in requirements["FR"]["exact_inputs"]
    assert "1980-1986" in requirements["FR"]["formula"]
    assert requirements["GrSaleToGrOverhead"]["window_months"] == 24
    assert "12-month fallback" in requirements["GrSaleToGrOverhead"]["formula"]
    assert "missing xrd becomes zero" in requirements["OperProfRD"]["formula"]
    assert requirements["RDAbility"]["window_months"] == 8 * 12
    assert requirements["RDAbility"]["minimum_periods"] == 6
    assert requirements["RDAbility"]["cross_section"] == "top_xrd_intensity_tercile"
    assert "prstkc > 0" in requirements["ShareRepurchase"]["formula"]
    assert requirements["VarCF"]["window_months"] == 60
    assert requirements["VarCF"]["minimum_periods"] == 24
    assert "ppenb" in requirements["realestate"]["exact_inputs"]
    assert requirements["realestate"]["minimum_industry_observations"] == 5


def test_official_documents_prove_no_exact_free_route() -> None:
    module = _module()
    summary = module.evaluate_complex_accounting_documents(
        _official_document_fixtures()
    )

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
    documents["sec_fsd"] = ""
    summary = module.evaluate_complex_accounting_documents(
        documents,
        access_errors={"sec_fsd": "HTTP Error 403: Forbidden"},
    )

    assert summary["official_documents_verified"] is False
    assert summary["source_access_decision_complete"] is True
    assert summary["access_blocked_documents"] == ["sec_fsd"]
    assert summary["unresolved_documents"] == []
    assert summary["exact_free_authorized_source_found"] is False


def test_batch_evidence_is_signal_specific_and_fail_closed() -> None:
    module = _module()
    evidence = module.build_complex_accounting_evidence(
        _valid_probe(),
        evidence_run_url="https://github.com/example/aurora/actions/runs/123",
        evidence_artifact="openap-181-complex-accounting-source-probe-results",
        implementation_commit="a" * 40,
    )

    assert set(evidence["signal"]) == EXPECTED_SIGNALS
    assert len(evidence) == evidence["signal"].nunique() == 8
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
    assert evidence["blocking_reason"].nunique() == 8
    assert evidence.set_index("signal")["blocking_reason"].to_dict() == (
        module.COMPLEX_ACCOUNTING_BLOCKERS
    )


def test_probe_outputs_contain_no_raw_source_data(tmp_path: Path) -> None:
    module = _module()
    probe = _valid_probe()
    module.write_complex_accounting_outputs(
        probe,
        output_dir=tmp_path,
        evidence_run_url="https://github.com/example/aurora/actions/runs/123",
        evidence_artifact="openap-181-complex-accounting-source-probe-results",
        implementation_commit="b" * 40,
    )

    expected = {
        "complex_accounting_source_probe.json",
        "complex_accounting_source_assessment.csv",
        "complex_accounting_formula_requirements.csv",
        "complex_accounting_batch_evidence.csv",
        "COMPLEX_ACCOUNTING_SOURCE_PROBE_REPORT.md",
    }
    assert {path.name for path in tmp_path.iterdir()} == expected
    evidence = pd.read_csv(tmp_path / "complex_accounting_batch_evidence.csv")
    assert len(evidence) == 8
    assert not any(path.suffix in {".zip", ".parquet"} for path in tmp_path.iterdir())


def test_workflow_is_github_only_sha_pinned_and_fail_closed() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = root / ".github/workflows/openap-181-complex-accounting-source-probe.yml"
    script = root / "scripts/run_openap_181_complex_accounting_source_probe.py"

    assert workflow.is_file()
    assert script.is_file()
    text = workflow.read_text(encoding="utf-8")
    assert "workflow_call:" in text
    assert "source_sha" in text
    assert "Checkout exact implementation revision" in text
    assert "test_openap_181_complex_accounting_batch.py" in text
    assert "complex_accounting_batch_evidence.csv" in text
    assert "strict_approved" in text
    assert "GITHUB_ACTIONS" in text
    assert "OOS_LOCKED" not in text
    assert "FORWARD" not in text
