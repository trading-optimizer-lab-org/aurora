from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pandas as pd


EXPECTED_SIGNALS = {
    "ChAssetTurnover",
    "ChInvIA",
    "ChTax",
    "GrLTNOA",
    "GrSaleToGrInv",
    "InvGrowth",
    "OrderBacklog",
    "OrderBacklogChg",
    "Tax",
    "XFIN",
}

EXPECTED_HASHES = {
    "ChAssetTurnover": (
        "f584e17a303ce790c6515eff040535a3fd86201129e415e504bce36c499bb651"
    ),
    "ChInvIA": (
        "09d5b9ae1836066d80de96b77352632246eafe30bbefb59fdf2c635291d90388"
    ),
    "ChTax": "04a5a239bed7f24ca9b0503b033eb0a7c579202da5f4144af2bfd718afc3ebda",
    "GrLTNOA": (
        "d82c228fe3f391c514dfcf1ae32b3709fdedc1c0b8173459e6ea9c3bbacb3aa1"
    ),
    "GrSaleToGrInv": (
        "0dd077f6ae9ab052955525ca1a53adbb06e4e4ea73c4fcbc956e8eb0574e41e6"
    ),
    "InvGrowth": (
        "177fb08aabfafd0ff460be24eb75d5180c18db4bade422cc3fefcd7802cae4fa"
    ),
    "OrderBacklog": (
        "a075ad1af49c8979d14037d0cd8a80adc91ebf92810010d57658fe8795c08954"
    ),
    "OrderBacklogChg": (
        "2e87eb4c390a81b382e2948c17c3b48b74c8628e68dcfaa120ba54d5d52251c7"
    ),
    "Tax": "060ba47cb7d7e9a40634bc806e6e70f1c35cdff75896e984b857ea6fb27000f1",
    "XFIN": "560138c5c24d6ad834bcbd28b5746eaf95ecbf4089adbaa7daba867204966fdd",
}


def _module():
    return import_module("aurora.research.openap_181.accounting_change_batch")


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
    probe = module.evaluate_accounting_change_documents(_official_document_fixtures())
    probe.update(
        {
            "formula_sources_verified": True,
            "formula_files": 10,
            "formula_signals": 10,
            "raw_source_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    return probe


def test_accounting_change_universe_and_formula_hashes_are_frozen() -> None:
    module = _module()

    assert module.ACCOUNTING_CHANGE_SIGNALS == frozenset(EXPECTED_SIGNALS)
    assert set(module.FORMULA_REQUIREMENTS) == EXPECTED_SIGNALS
    assert set(module.ACCOUNTING_CHANGE_BLOCKERS) == EXPECTED_SIGNALS
    assert set(module.OPENAP_FORMULA_FILES) == EXPECTED_SIGNALS
    assert module.OPENAP_COMMIT == "8db892442c2c3a3779b0f1eac4370d3655be15a1"
    assert {
        signal: metadata["sha256"]
        for signal, metadata in module.OPENAP_FORMULA_FILES.items()
    } == EXPECTED_HASHES
    assert len(
        {metadata["path"] for metadata in module.OPENAP_FORMULA_FILES.values()}
    ) == 10


def test_exact_formula_requirements_preserve_current_openap_semantics() -> None:
    requirements = _module().FORMULA_REQUIREMENTS

    assert requirements["ChAssetTurnover"]["formula"] == (
        "sale/mean(operating_assets,lag12_operating_assets)-lag12_asset_turnover"
    )
    assert "forward-fill ppent" in requirements["ChAssetTurnover"]["filters"]
    assert "exact calendar 12-month" in requirements["ChAssetTurnover"]["timing"]
    assert requirements["ChInvIA"]["formula"] == (
        "capx_growth-minus-monthly_two_digit_sic_mean"
    )
    assert "lag12 and lag24 average" in requirements["ChInvIA"]["timing"]
    assert "ppent change" in requirements["ChInvIA"]["filters"]
    assert requirements["ChTax"]["formula"] == "(txtq-lag12_txtq)/lag12_at"
    assert "exact calendar 12-month" in requirements["ChTax"]["timing"]
    assert "12-row positional lags" in requirements["GrLTNOA"]["timing"]
    assert "working-capital adjustment" in requirements["GrLTNOA"]["formula"]
    assert "lag12 and lag24 average" in requirements["GrSaleToGrInv"]["timing"]
    assert "fallback to lag12 growth" in requirements["GrSaleToGrInv"]["filters"]
    assert requirements["InvGrowth"]["formula"] == (
        "real_invt/lag12_real_invt-1"
    )
    assert "SIC 4xxx and 6xxx" in requirements["InvGrowth"]["filters"]
    assert requirements["OrderBacklog"]["formula"] == (
        "ob/(0.5*(at+lag12_at))"
    )
    assert "12-row positional lag" in requirements["OrderBacklog"]["timing"]
    assert requirements["OrderBacklogChg"]["formula"] == (
        "order_backlog-lag12_order_backlog"
    )
    assert "12-row positional lags" in requirements["OrderBacklogChg"]["timing"]
    assert "historical statutory rates" in requirements["Tax"]["timing"]
    assert "alternative txt-txdi" in requirements["Tax"]["formula"]
    assert requirements["XFIN"]["formula"] == (
        "(sstk-dv-prstkc+dltis-dltr+dlcch)/at"
    )
    assert "missing dlcch becomes zero" in requirements["XFIN"]["filters"]


def test_official_documents_prove_no_exact_free_route() -> None:
    summary = _module().evaluate_accounting_change_documents(
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
    summary = module.evaluate_accounting_change_documents(
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
    evidence = module.build_accounting_change_evidence(
        _valid_probe(),
        evidence_run_url="https://github.com/example/aurora/actions/runs/123",
        evidence_artifact="openap-181-accounting-change-source-probe-results",
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
        module.ACCOUNTING_CHANGE_BLOCKERS
    )


def test_probe_outputs_contain_no_raw_source_data(tmp_path: Path) -> None:
    module = _module()
    module.write_accounting_change_outputs(
        _valid_probe(),
        output_dir=tmp_path,
        evidence_run_url="https://github.com/example/aurora/actions/runs/123",
        evidence_artifact="openap-181-accounting-change-source-probe-results",
        implementation_commit="b" * 40,
    )

    expected = {
        "accounting_change_source_probe.json",
        "accounting_change_source_assessment.csv",
        "accounting_change_formula_requirements.csv",
        "accounting_change_batch_evidence.csv",
        "ACCOUNTING_CHANGE_SOURCE_PROBE_REPORT.md",
    }
    assert {path.name for path in tmp_path.iterdir()} == expected
    evidence = pd.read_csv(tmp_path / "accounting_change_batch_evidence.csv")
    assert len(evidence) == 10
    assert not any(path.suffix in {".zip", ".parquet"} for path in tmp_path.iterdir())


def test_workflows_are_github_only_sha_pinned_and_integrated() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = root / ".github/workflows/openap-181-accounting-change-source-probe.yml"
    completion = root / ".github/workflows/openap-181-completion-audit.yml"
    script = root / "scripts/run_openap_181_accounting_change_source_probe.py"

    assert workflow.is_file()
    assert script.is_file()
    text = workflow.read_text(encoding="utf-8")
    assert "workflow_call:" in text
    assert "source_sha" in text
    assert "Checkout exact implementation revision" in text
    assert "test_openap_181_accounting_change_batch.py" in text
    assert "accounting_change_batch_evidence.csv" in text
    assert "strict_approved" in text
    assert "GITHUB_ACTIONS" in text
    assert "OOS_LOCKED" not in text
    assert "FORWARD" not in text

    completion_text = completion.read_text(encoding="utf-8")
    assert "accounting_change_evidence_run_id" in completion_text
    assert "accounting_change_probe:" in completion_text
    assert "accounting_change_batch_evidence.csv" in completion_text
