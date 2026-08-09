from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pandas as pd


EXPECTED_SIGNALS = {
    "AM",
    "BM",
    "BMdec",
    "BPEBM",
    "BookLeverage",
    "CF",
    "EBM",
    "EP",
    "EntMult",
    "Leverage",
}

EXPECTED_HASHES = {
    "AM": "5c66c0e4e0cfcf3ecb68ca6a28d707600500462a8065694d161ab0be380ad750",
    "BM": "b852ede9b0b5cb9da89e752ca4c5348ed96380a923357fa9e7dd5274a9a5d946",
    "BMdec": "111bb8df1db87d92fb55ec4c070dc157281655afe80d9f54796ee4572f533d06",
    "BPEBM": "2fc3537cf2b935b4ec1204dc7966c0fe475683a7a47a9df74b5837b80dddf9c6",
    "BookLeverage": "af34ed6680a162075ec28554f8ddc485eef35ffbc06783b09431fdfbb01c9298",
    "CF": "09532e1ce762f64f4b225c5f4bd00b48ae40de55003da0295b1ae617585f1296",
    "EBM": "2fc3537cf2b935b4ec1204dc7966c0fe475683a7a47a9df74b5837b80dddf9c6",
    "EP": "7879a38168363a50056907b7819023be609e29a4514bfc7b9bc547a3bd590a96",
    "EntMult": "3959786d1f35735633a840c626f3241384cc913f5d026435a02c85c0b44161d9",
    "Leverage": "c63e0c634038e25511493d98fa9ee58099613f5d022df7bc74a33619d034e70b",
}


def _module():
    return import_module("aurora.research.openap_181.valuation_accounting_batch")


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
    probe = module.evaluate_valuation_accounting_documents(
        _official_document_fixtures()
    )
    probe.update(
        {
            "formula_sources_verified": True,
            "formula_files": 9,
            "formula_signals": 10,
            "raw_source_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    return probe


def test_valuation_accounting_universe_and_formula_hashes_are_frozen() -> None:
    module = _module()

    assert module.VALUATION_ACCOUNTING_SIGNALS == frozenset(EXPECTED_SIGNALS)
    assert set(module.FORMULA_REQUIREMENTS) == EXPECTED_SIGNALS
    assert set(module.VALUATION_ACCOUNTING_BLOCKERS) == EXPECTED_SIGNALS
    assert set(module.OPENAP_FORMULA_FILES) == EXPECTED_SIGNALS
    assert module.OPENAP_COMMIT == "8db892442c2c3a3779b0f1eac4370d3655be15a1"
    assert {
        signal: metadata["sha256"]
        for signal, metadata in module.OPENAP_FORMULA_FILES.items()
    } == EXPECTED_HASHES
    assert len(
        {metadata["path"] for metadata in module.OPENAP_FORMULA_FILES.values()}
    ) == 9


def test_exact_formula_requirements_preserve_openap_semantics() -> None:
    requirements = _module().FORMULA_REQUIREMENTS

    assert requirements["AM"]["formula"] == "at/mve_permco"
    assert "log" in requirements["BM"]["formula"]
    assert requirements["BM"]["window_months"] == 6
    assert "datadate" in requirements["BM"]["timing"]
    assert requirements["BMdec"]["window_months"] == 17
    assert "12-month and 17-month" in requirements["BMdec"]["timing"]
    assert "pstk, then pstkrv, then pstkl" in requirements["BMdec"]["formula"]
    assert "txditc missing becomes zero" in requirements["BookLeverage"]["formula"]
    assert requirements["CF"]["formula"] == "(ib+dp)/mve_permco"
    assert "dvpa" in requirements["EBM"]["exact_inputs"]
    assert "BP-EBM" in requirements["BPEBM"]["formula"]
    assert requirements["EP"]["window_months"] == 6
    assert "negative EP becomes missing" in requirements["EP"]["filters"]
    assert "dc" in requirements["EntMult"]["exact_inputs"]
    assert "ceq<0 or oibdp<0" in requirements["EntMult"]["filters"]
    assert requirements["Leverage"]["formula"] == "lt/mve_permco"
    assert all(
        requirement["identity"]
        == "historical GVKEY to PERMNO/PERMCO validity intervals"
        for requirement in requirements.values()
    )


def test_official_documents_prove_no_exact_free_route() -> None:
    summary = _module().evaluate_valuation_accounting_documents(
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
    summary = module.evaluate_valuation_accounting_documents(
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
    evidence = module.build_valuation_accounting_evidence(
        _valid_probe(),
        evidence_run_url="https://github.com/example/aurora/actions/runs/123",
        evidence_artifact="openap-181-valuation-accounting-source-probe-results",
        implementation_commit="a" * 40,
    )

    assert set(evidence["signal"]) == EXPECTED_SIGNALS
    assert len(evidence) == evidence["signal"].nunique() == 10
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
    assert evidence["blocking_reason"].nunique() == 10
    assert evidence.set_index("signal")["blocking_reason"].to_dict() == (
        module.VALUATION_ACCOUNTING_BLOCKERS
    )


def test_probe_outputs_contain_no_raw_source_data(tmp_path: Path) -> None:
    module = _module()
    module.write_valuation_accounting_outputs(
        _valid_probe(),
        output_dir=tmp_path,
        evidence_run_url="https://github.com/example/aurora/actions/runs/123",
        evidence_artifact="openap-181-valuation-accounting-source-probe-results",
        implementation_commit="b" * 40,
    )

    expected = {
        "valuation_accounting_source_probe.json",
        "valuation_accounting_source_assessment.csv",
        "valuation_accounting_formula_requirements.csv",
        "valuation_accounting_batch_evidence.csv",
        "VALUATION_ACCOUNTING_SOURCE_PROBE_REPORT.md",
    }
    assert {path.name for path in tmp_path.iterdir()} == expected
    evidence = pd.read_csv(tmp_path / "valuation_accounting_batch_evidence.csv")
    assert len(evidence) == 10
    assert not any(path.suffix in {".zip", ".parquet"} for path in tmp_path.iterdir())


def test_workflows_are_github_only_sha_pinned_and_integrated() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (
        root / ".github/workflows/openap-181-valuation-accounting-source-probe.yml"
    )
    completion = root / ".github/workflows/openap-181-completion-audit.yml"
    script = root / "scripts/run_openap_181_valuation_accounting_source_probe.py"

    assert workflow.is_file()
    assert script.is_file()
    text = workflow.read_text(encoding="utf-8")
    assert "workflow_call:" in text
    assert "source_sha" in text
    assert "Checkout exact implementation revision" in text
    assert "test_openap_181_valuation_accounting_batch.py" in text
    assert "valuation_accounting_batch_evidence.csv" in text
    assert "strict_approved" in text
    assert "GITHUB_ACTIONS" in text
    assert "OOS_LOCKED" not in text
    assert "FORWARD" not in text

    completion_text = completion.read_text(encoding="utf-8")
    assert "valuation_accounting_evidence_run_id" in completion_text
    assert "valuation_accounting_probe:" in completion_text
    assert "valuation_accounting_batch_evidence.csv" in completion_text
