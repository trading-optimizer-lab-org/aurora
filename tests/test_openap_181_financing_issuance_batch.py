from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pandas as pd


EXPECTED_SIGNALS = {
    "CompEquIss",
    "CompositeDebtIssuance",
    "ConvDebt",
    "DebtIssuance",
    "DelEqu",
    "NetDebtFinance",
    "NetEquityFinance",
    "NetPayoutYield",
    "PayoutYield",
    "ShareIss1Y",
    "ShareIss5Y",
}

CRSP_ONLY_SIGNALS = {"CompEquIss", "ShareIss1Y", "ShareIss5Y"}

EXPECTED_HASHES = {
    "CompEquIss": "d87a14114fbd43039f32c71bec6c42d017fedaf0130f8f1d58cc227f899b808b",
    "CompositeDebtIssuance": (
        "0ed0dacaca27d2d67a98f1793a6827702a7e73b631491a1195008ba012f68665"
    ),
    "ConvDebt": "71b49dbf704bfc00260084f27442eec35fe26f82200c0c32d767a0ef34a2bcab",
    "DebtIssuance": (
        "be86cb9cf972fd41905e45bbab7505dd99da88c0e888a47604998beb102f0816"
    ),
    "DelEqu": "a040398b319e60cba5bfa8438f24411e39ed8d06a4166b78fc107ba772e2e720",
    "NetDebtFinance": (
        "e8412606b15fe6eba89f37e301b1e8978a963d6798c8494bc34c15b14b3150d6"
    ),
    "NetEquityFinance": (
        "ede836d5312897d3b4e4ba843c007b70b859f5f07790f8c50db10f8f2f9bb385"
    ),
    "NetPayoutYield": (
        "4a30a7eeee64e52bcc4c609ce5134ac873bc1cff7b7e25ace9282f7887a79afe"
    ),
    "PayoutYield": (
        "d9cd4c9f27364929ac0889ed48149f6d7b509c9a6f1d0dc1cde272f2bd8229db"
    ),
    "ShareIss1Y": (
        "adc05d494eb6df3cfd54652d25de00346f396d09b4d5cbb78896b18d6aae5457"
    ),
    "ShareIss5Y": (
        "6d45e71a7756058a4b8ffcbbedcbfe79ff984bf5b01f497b5f770dca1d454d26"
    ),
}


def _module():
    return import_module("aurora.research.openap_181.financing_issuance_batch")


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
    probe = module.evaluate_financing_issuance_documents(
        _official_document_fixtures()
    )
    probe.update(
        {
            "formula_sources_verified": True,
            "formula_files": 11,
            "formula_signals": 11,
            "raw_source_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    return probe


def test_financing_issuance_universe_and_formula_hashes_are_frozen() -> None:
    module = _module()

    assert module.FINANCING_ISSUANCE_SIGNALS == frozenset(EXPECTED_SIGNALS)
    assert module.FINANCING_ISSUANCE_CRSP_ONLY_SIGNALS == frozenset(
        CRSP_ONLY_SIGNALS
    )
    assert set(module.FORMULA_REQUIREMENTS) == EXPECTED_SIGNALS
    assert set(module.FINANCING_ISSUANCE_BLOCKERS) == EXPECTED_SIGNALS
    assert set(module.OPENAP_FORMULA_FILES) == EXPECTED_SIGNALS
    assert module.OPENAP_COMMIT == "8db892442c2c3a3779b0f1eac4370d3655be15a1"
    assert {
        signal: metadata["sha256"]
        for signal, metadata in module.OPENAP_FORMULA_FILES.items()
    } == EXPECTED_HASHES
    assert len(
        {metadata["path"] for metadata in module.OPENAP_FORMULA_FILES.values()}
    ) == 11


def test_exact_formula_requirements_preserve_openap_semantics() -> None:
    requirements = _module().FORMULA_REQUIREMENTS

    assert requirements["CompEquIss"]["window_months"] == 60
    assert "cumulative product of 1+ret" in requirements["CompEquIss"]["formula"]
    assert "calendar-validated" in requirements["CompEquIss"]["timing"]
    assert requirements["CompositeDebtIssuance"]["formula"] == (
        "log((dltt+dlc)/lag60(dltt+dlc))"
    )
    assert "60-row fallback" in requirements["CompositeDebtIssuance"]["timing"]
    assert requirements["ConvDebt"]["formula"] == (
        "1 if nonmissing dc!=0 or nonmissing cshrc!=0; otherwise 0"
    )
    assert "shrcd>11" in requirements["DebtIssuance"]["filters"]
    assert requirements["DelEqu"]["window_months"] == 12
    assert "exact calendar" in requirements["DelEqu"]["timing"]
    assert "dlcch missing becomes zero" in requirements["NetDebtFinance"]["formula"]
    assert "abs(NetDebtFinance)>1" in requirements["NetDebtFinance"]["filters"]
    assert "sstk-prstkc-dv" in requirements["NetEquityFinance"]["formula"]
    assert "24 observations" in requirements["NetPayoutYield"]["filters"]
    assert "true zeros" in requirements["NetPayoutYield"]["filters"]
    assert "dvc+prstkc+pstkrv" in requirements["PayoutYield"]["formula"]
    assert "nonpositive" in requirements["PayoutYield"]["filters"]
    assert requirements["ShareIss1Y"]["window_months"] == 18
    assert "shrout*cfacshr" in requirements["ShareIss1Y"]["formula"]
    assert "lag6" in requirements["ShareIss1Y"]["formula"]
    assert requirements["ShareIss5Y"]["window_months"] == 65
    assert "lag5" in requirements["ShareIss5Y"]["formula"]
    assert "lag65" in requirements["ShareIss5Y"]["formula"]


def test_official_documents_prove_no_exact_free_route() -> None:
    summary = _module().evaluate_financing_issuance_documents(
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
    summary = module.evaluate_financing_issuance_documents(
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
    evidence = module.build_financing_issuance_evidence(
        _valid_probe(),
        evidence_run_url="https://github.com/example/aurora/actions/runs/123",
        evidence_artifact="openap-181-financing-issuance-source-probe-results",
        implementation_commit="a" * 40,
    )

    assert set(evidence["signal"]) == EXPECTED_SIGNALS
    assert len(evidence) == evidence["signal"].nunique() == 11
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
    assert evidence["blocking_reason"].nunique() == 11
    assert evidence.set_index("signal")["blocking_reason"].to_dict() == (
        module.FINANCING_ISSUANCE_BLOCKERS
    )


def test_probe_outputs_contain_no_raw_source_data(tmp_path: Path) -> None:
    module = _module()
    module.write_financing_issuance_outputs(
        _valid_probe(),
        output_dir=tmp_path,
        evidence_run_url="https://github.com/example/aurora/actions/runs/123",
        evidence_artifact="openap-181-financing-issuance-source-probe-results",
        implementation_commit="b" * 40,
    )

    expected = {
        "financing_issuance_source_probe.json",
        "financing_issuance_source_assessment.csv",
        "financing_issuance_formula_requirements.csv",
        "financing_issuance_batch_evidence.csv",
        "FINANCING_ISSUANCE_SOURCE_PROBE_REPORT.md",
    }
    assert {path.name for path in tmp_path.iterdir()} == expected
    evidence = pd.read_csv(tmp_path / "financing_issuance_batch_evidence.csv")
    assert len(evidence) == 11
    assert not any(path.suffix in {".zip", ".parquet"} for path in tmp_path.iterdir())


def test_workflows_are_github_only_sha_pinned_and_integrated() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (
        root / ".github/workflows/openap-181-financing-issuance-source-probe.yml"
    )
    completion = root / ".github/workflows/openap-181-completion-audit.yml"
    script = root / "scripts/run_openap_181_financing_issuance_source_probe.py"

    assert workflow.is_file()
    assert script.is_file()
    text = workflow.read_text(encoding="utf-8")
    assert "workflow_call:" in text
    assert "source_sha" in text
    assert "Checkout exact implementation revision" in text
    assert "test_openap_181_financing_issuance_batch.py" in text
    assert "financing_issuance_batch_evidence.csv" in text
    assert "strict_approved" in text
    assert "GITHUB_ACTIONS" in text
    assert "OOS_LOCKED" not in text
    assert "FORWARD" not in text

    completion_text = completion.read_text(encoding="utf-8")
    assert "financing_issuance_evidence_run_id" in completion_text
    assert "financing_issuance_probe:" in completion_text
    assert "financing_issuance_batch_evidence.csv" in completion_text
