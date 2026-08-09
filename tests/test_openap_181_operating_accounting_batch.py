from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pandas as pd


EXPECTED_SIGNALS = {
    "AdExp",
    "Cash",
    "CashProd",
    "GP",
    "Investment",
    "OPLeverage",
    "OperProf",
    "RD",
    "SP",
    "cfp",
    "roaq",
    "tang",
}

MARKET_INPUT_SIGNALS = {"AdExp", "CashProd", "OperProf", "RD", "SP", "cfp"}

EXPECTED_HASHES = {
    "AdExp": "2e813c7e054aecddfe759d1b9c136c88ffb62755408f4ecc3697e870033aa82e",
    "Cash": "7e9f046dd3ebe3581b57ede655a9f1ba68340dcbf53167ed6fe0030e746ecab2",
    "CashProd": (
        "2541484ba36d9869221987b2a5ec015f3dd9aa5ce4406f8a0ffea56173ce1983"
    ),
    "GP": "6a05de4a5b6ddb47a320e1d95d6392e625bfca3b50091e698be9fd866a6c8576",
    "Investment": (
        "9b5b843157e7a57f67f6d8de610f165c27a69a5bf7cff8e671fef0e52a472e17"
    ),
    "OPLeverage": (
        "683200c6f2b3f48fe3da68baa1f871634b825a38a04a0058d1efc033a05089c7"
    ),
    "OperProf": (
        "68bef53d98e13fea98dc282bdd2a97d0bb49beaf5b59ff123a83dd03dc0bf658"
    ),
    "RD": "c9b58cea6980a3570096ab08c9e1cd224bb89e5dc0cfbadc80777bbbb263edf3",
    "SP": "4645a61c5b36a42900442c05cf287b44cbe8434f7b4447945ee54c0dc1501e1b",
    "cfp": "71b6f3fc630ec686409d5cc9c49d60cda5381402886bf7ea7a3f119093fe41ed",
    "roaq": (
        "17ef6905930c74a3c697bbe51a4bb217b0ceb0b25d4026f3608e7b36a6735559"
    ),
    "tang": (
        "cfdbe9c1f2d68e423c10efff085d92e747ae7f033cd9cbf4f9d136447f881681"
    ),
}


def _module():
    return import_module("aurora.research.openap_181.operating_accounting_batch")


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
    probe = module.evaluate_operating_accounting_documents(
        _official_document_fixtures()
    )
    probe.update(
        {
            "formula_sources_verified": True,
            "formula_files": 12,
            "formula_signals": 12,
            "raw_source_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    return probe


def test_operating_accounting_universe_and_formula_hashes_are_frozen() -> None:
    module = _module()

    assert module.OPERATING_ACCOUNTING_SIGNALS == frozenset(EXPECTED_SIGNALS)
    assert module.OPERATING_ACCOUNTING_MARKET_SIGNALS == frozenset(
        MARKET_INPUT_SIGNALS
    )
    assert set(module.FORMULA_REQUIREMENTS) == EXPECTED_SIGNALS
    assert set(module.OPERATING_ACCOUNTING_BLOCKERS) == EXPECTED_SIGNALS
    assert set(module.OPENAP_FORMULA_FILES) == EXPECTED_SIGNALS
    assert module.OPENAP_COMMIT == "8db892442c2c3a3779b0f1eac4370d3655be15a1"
    assert {
        signal: metadata["sha256"]
        for signal, metadata in module.OPENAP_FORMULA_FILES.items()
    } == EXPECTED_HASHES
    assert len(
        {metadata["path"] for metadata in module.OPENAP_FORMULA_FILES.values()}
    ) == 12


def test_exact_formula_requirements_preserve_current_openap_semantics() -> None:
    requirements = _module().FORMULA_REQUIREMENTS

    assert requirements["AdExp"]["formula"] == "xad/mve_permco"
    assert "xad<=0" in requirements["AdExp"]["filters"]
    assert requirements["Cash"]["formula"] == "cheq/atq"
    assert "rdq month plus two months" in requirements["Cash"]["timing"]
    assert "atq>0" in requirements["Cash"]["filters"]
    assert requirements["CashProd"]["formula"] == "(mve_permco-at)/che"
    assert "oancf when nonmissing" in requirements["cfp"]["formula"]
    assert "exact calendar 12-month" in requirements["cfp"]["timing"]
    assert requirements["GP"]["formula"] == "(revt-cogs)/at"
    assert "SIC 6000-6999" in requirements["GP"]["filters"]
    assert requirements["Investment"]["window_months"] == 36
    assert "minimum 24 observations" in requirements["Investment"]["timing"]
    assert "revt<10" in requirements["Investment"]["filters"]
    assert "missing xsga becomes zero" in requirements["OPLeverage"]["formula"]
    assert "smallest within-month mve_c tercile" in requirements["OperProf"][
        "filters"
    ]
    assert requirements["RD"]["formula"] == "xrd/mve_permco"
    assert requirements["SP"]["formula"] == "sale/mve_permco"
    assert requirements["roaq"]["formula"] == "ibq/lag3_atq"
    assert "exact calendar three-month" in requirements["roaq"]["timing"]
    assert "0.715*rect" in requirements["tang"]["formula"]
    assert "FC is computed but not applied" in requirements["tang"]["filters"]


def test_official_documents_prove_no_exact_free_route() -> None:
    summary = _module().evaluate_operating_accounting_documents(
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


def test_access_errors_do_not_invent_document_verification() -> None:
    module = _module()
    documents = _official_document_fixtures()
    documents["sec_fsd"] = ""
    summary = module.evaluate_operating_accounting_documents(
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
    evidence = module.build_operating_accounting_evidence(
        _valid_probe(),
        evidence_run_url="https://github.com/example/aurora/actions/runs/123",
        evidence_artifact="openap-181-operating-accounting-source-probe-results",
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
        module.OPERATING_ACCOUNTING_BLOCKERS
    )


def test_probe_outputs_contain_no_raw_source_data(tmp_path: Path) -> None:
    module = _module()
    module.write_operating_accounting_outputs(
        _valid_probe(),
        output_dir=tmp_path,
        evidence_run_url="https://github.com/example/aurora/actions/runs/123",
        evidence_artifact="openap-181-operating-accounting-source-probe-results",
        implementation_commit="b" * 40,
    )

    expected = {
        "operating_accounting_source_probe.json",
        "operating_accounting_source_assessment.csv",
        "operating_accounting_formula_requirements.csv",
        "operating_accounting_batch_evidence.csv",
        "OPERATING_ACCOUNTING_SOURCE_PROBE_REPORT.md",
    }
    assert {path.name for path in tmp_path.iterdir()} == expected
    evidence = pd.read_csv(tmp_path / "operating_accounting_batch_evidence.csv")
    assert len(evidence) == 12
    assert not any(path.suffix in {".zip", ".parquet"} for path in tmp_path.iterdir())


def test_workflows_are_github_only_sha_pinned_and_integrated() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (
        root / ".github/workflows/openap-181-operating-accounting-source-probe.yml"
    )
    completion = root / ".github/workflows/openap-181-completion-audit.yml"
    script = root / "scripts/run_openap_181_operating_accounting_source_probe.py"

    assert workflow.is_file()
    assert script.is_file()
    text = workflow.read_text(encoding="utf-8")
    assert "workflow_call:" in text
    assert "source_sha" in text
    assert "Checkout exact implementation revision" in text
    assert "test_openap_181_operating_accounting_batch.py" in text
    assert "operating_accounting_batch_evidence.csv" in text
    assert "strict_approved" in text
    assert "GITHUB_ACTIONS" in text
    assert "OOS_LOCKED" not in text
    assert "FORWARD" not in text

    completion_text = completion.read_text(encoding="utf-8")
    assert "operating_accounting_evidence_run_id" in completion_text
    assert "operating_accounting_probe:" in completion_text
    assert "operating_accounting_batch_evidence.csv" in completion_text
