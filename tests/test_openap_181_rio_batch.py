from __future__ import annotations

from hashlib import sha256
from importlib import import_module
from pathlib import Path

import pandas as pd
import pytest


EXPECTED_RIO_SIGNALS = {
    "RIO_Disp",
    "RIO_MB",
    "RIO_Turnover",
    "RIO_Volatility",
}


def _module():
    return import_module("aurora.research.openap_181.rio_batch")


def _official_document_fixtures() -> dict[str, str]:
    return {
        "openap_formula": (
            "OpenAP combines TR_13F instown_perc, SignalMasterTable PERMNO and market "
            "equity, Compustat at ceq txditc, monthly CRSP vol shrout ret, and unadjusted "
            "IBES FY1 stdev. It uses a six calendar month lag and coefficient 0.08."
        ),
        "nagel_paper": (
            "Nagel 2005 residual institutional ownership regresses logit(INST) on Log SZ "
            "and squared Log SZ. Equation 2 reports -23.66 + 2.89 Log SZ - 0.09 squared. "
            "Stocks below the 20th NYSE/Amex size percentile are excluded and RI as of "
            "quarter t-2 is used in independent quintile sorts."
        ),
        "sec_13f": (
            "The official Form 13F structured data sets contain XML submitted from May "
            "2013 through the current period. Data are quarterly and include amendments."
        ),
        "sec_13f_faq": (
            "Managers file within 45 days after quarter end. The official Section 13(f) "
            "securities list is published by the SEC and confidential treatment may apply."
        ),
        "openfigi": (
            "OpenFIGI maps third-party identifiers including CUSIP to FIGI. A key raises "
            "rate limits. It does not provide historical PERMNO ownership links."
        ),
        "crsp_wrds": (
            "CRSP provides PERMNO, prices, returns, volume, shares outstanding, exchange "
            "codes, names and delistings under an institutional subscription and license."
        ),
        "compustat_wrds": (
            "Compustat provides total assets, common equity and deferred taxes with a "
            "historical CRSP link under a commercial institutional license."
        ),
        "ibes_lseg": (
            "LSEG I/B/E/S provides unadjusted historical analyst forecast detail and "
            "summary statistics including standard deviation and forecast period indicator. "
            "Historical access and linking are licensed products."
        ),
    }


def _valid_probe() -> dict[str, object]:
    module = _module()
    probe = module.evaluate_rio_source_documents(_official_document_fixtures())
    probe.update(
        {
            "formula_sources_verified": True,
            "formula_files": 1,
            "raw_source_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    return probe


def test_rio_universe_formula_and_requirements_are_frozen() -> None:
    module = _module()

    assert module.RIO_SIGNALS == frozenset(EXPECTED_RIO_SIGNALS)
    assert set(module.RIO_FORMULA_REQUIREMENTS) == EXPECTED_RIO_SIGNALS
    assert set(module.RIO_BLOCKERS) == EXPECTED_RIO_SIGNALS
    assert module.OPENAP_COMMIT == "8db892442c2c3a3779b0f1eac4370d3655be15a1"
    assert module.OPENAP_FORMULA_FILE["path"].endswith(
        "ZZ1_RIO_MB_RIO_Disp_RIO_Turnover_RIO_Volatility.py"
    )
    assert module.OPENAP_FORMULA_FILE["sha256"] == (
        "34a01df935551f7c8f19f5521084a658f5bc401d65c54c3fcabb7746438a6afa"
    )
    assert module.DOCUMENT_URLS["ibes_lseg"].endswith("/ibes-estimates")
    assert module.RIO_SHARED_CONTRACT["openap_size_square_coefficient"] == 0.08
    assert module.RIO_SHARED_CONTRACT["nagel_size_square_coefficient"] == 0.09
    assert module.RIO_SHARED_CONTRACT["rio_lag_months"] == 6
    assert module.RIO_SHARED_CONTRACT["excluded_size_percentile"] == 20
    assert module.RIO_FORMULA_REQUIREMENTS["RIO_Disp"]["characteristic_bucket"] == (
        "top_40_percent"
    )
    assert module.RIO_FORMULA_REQUIREMENTS["RIO_Volatility"]["window_months"] == 12
    assert module.RIO_FORMULA_REQUIREMENTS["RIO_Volatility"]["minimum_months"] == 6


def test_official_documents_prove_formula_discrepancy_and_no_exact_free_route() -> None:
    module = _module()
    summary = module.evaluate_rio_source_documents(_official_document_fixtures())

    assert summary["official_documents_verified"] is True
    assert summary["source_access_decision_complete"] is True
    assert summary["unresolved_documents"] == []
    assert summary["openap_inputs_verified"] is True
    assert summary["nagel_formula_verified"] is True
    assert summary["openap_nagel_coefficient_discrepancy_verified"] is True
    assert summary["sec_structured_history_starts_2013"] is True
    assert summary["sec_reporting_lag_and_confidentiality_verified"] is True
    assert summary["openfigi_not_permno_history"] is True
    assert summary["commercial_exact_inputs_verified"] is True
    assert summary["exact_free_authorized_source_found"] is False
    assert summary["strict_approved"] == 0


def test_document_access_failure_is_classified_without_approval() -> None:
    module = _module()
    documents = _official_document_fixtures()
    documents["ibes_lseg"] = ""
    summary = module.evaluate_rio_source_documents(
        documents,
        access_errors={"ibes_lseg": "HTTP Error 403: Forbidden"},
    )

    assert summary["official_documents_verified"] is False
    assert summary["source_access_decision_complete"] is True
    assert summary["access_blocked_documents"] == ["ibes_lseg"]
    assert summary["unresolved_documents"] == []
    assert summary["exact_free_authorized_source_found"] is False
    assert summary["strict_approved"] == 0


def test_rio_source_assessments_separate_free_partial_and_exact_commercial() -> None:
    module = _module()
    sources = {row["source_id"]: row for row in module.SOURCE_ASSESSMENTS}

    assert sources["sec_13f"]["project_use_authorized"] is True
    assert sources["sec_13f"]["exact_for_openap"] is False
    assert sources["openfigi"]["project_use_authorized"] is True
    assert sources["openfigi"]["historical_permno_bridge"] is False
    assert sources["crsp_stock_commercial"]["exact_for_openap"] is True
    assert sources["crsp_stock_commercial"]["project_use_authorized"] is False
    assert sources["compustat_commercial"]["project_use_authorized"] is False
    assert sources["lseg_ibes_commercial"]["project_use_authorized"] is False


def test_rio_evidence_covers_four_signals_with_specific_blockers() -> None:
    module = _module()
    evidence = module.build_rio_batch_evidence(
        _valid_probe(),
        evidence_run_url="https://github.com/example/aurora/actions/runs/19",
        evidence_artifact="openap-181-rio-source-probe-results",
        implementation_commit="a" * 40,
    ).set_index("signal")

    assert set(evidence.index) == EXPECTED_RIO_SIGNALS
    assert evidence["formula_implemented"].eq(True).all()
    for gate in {
        "data_pipeline_implemented",
        "point_in_time_verified",
        "identity_verified",
        "coverage_measured",
        "fidelity_measured",
    }:
        assert evidence[gate].eq(False).all()
    assert evidence["strict_gate_result"].eq("blocked").all()
    assert evidence["blocking_reason"].str.startswith("rio_source_blocked:").all()
    assert "compustat" in evidence.loc["RIO_MB", "blocking_reason"]
    assert "ibes" in evidence.loc["RIO_Disp", "blocking_reason"]
    assert "monthly_crsp_vol_shrout" in evidence.loc[
        "RIO_Turnover", "blocking_reason"
    ]
    assert "twelve_month_crsp_returns" in evidence.loc[
        "RIO_Volatility", "blocking_reason"
    ]
    assert evidence["blocking_reason"].nunique() == 4


def test_rio_evidence_rejects_incomplete_or_promotable_probe() -> None:
    module = _module()
    incomplete = _valid_probe()
    incomplete["source_access_decision_complete"] = False
    with pytest.raises(ValueError, match="Invalid or incomplete RIO probe"):
        module.build_rio_batch_evidence(
            incomplete,
            evidence_run_url="https://github.com/example/aurora/actions/runs/19",
            evidence_artifact="openap-181-rio-source-probe-results",
            implementation_commit="a" * 40,
        )

    promotable = _valid_probe()
    promotable["exact_free_authorized_source_found"] = True
    with pytest.raises(ValueError, match="Invalid or incomplete RIO probe"):
        module.build_rio_batch_evidence(
            promotable,
            evidence_run_url="https://github.com/example/aurora/actions/runs/19",
            evidence_artifact="openap-181-rio-source-probe-results",
            implementation_commit="a" * 40,
        )


def test_rio_probe_outputs_are_metadata_only(tmp_path: Path) -> None:
    module = _module()
    module.write_rio_source_probe_outputs(
        _valid_probe(),
        output_dir=tmp_path,
        evidence_run_url="https://github.com/example/aurora/actions/runs/19",
        evidence_artifact="openap-181-rio-source-probe-results",
        implementation_commit="b" * 40,
    )

    expected = {
        "rio_source_probe.json",
        "rio_source_assessment.csv",
        "rio_formula_requirements.csv",
        "rio_batch_evidence.csv",
        "RIO_SOURCE_PROBE_REPORT.md",
    }
    assert {path.name for path in tmp_path.iterdir()} == expected
    evidence = pd.read_csv(tmp_path / "rio_batch_evidence.csv")
    formulas = pd.read_csv(tmp_path / "rio_formula_requirements.csv")
    assert len(evidence) == evidence["signal"].nunique() == 4
    assert len(formulas) == formulas["signal"].nunique() == 4
    assert not any(
        token in path.name.lower()
        for path in tmp_path.iterdir()
        for token in ("raw", "holdings", "prices", "returns", "forecasts")
    )


def test_live_probe_verifies_pinned_formula_and_metadata_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    formula_payload = b"# pinned RIO formula fixture\n"
    formula_file = {
        "path": module.OPENAP_FORMULA_FILE["path"],
        "sha256": sha256(formula_payload).hexdigest(),
    }
    documents = _official_document_fixtures()
    document_urls = {name: f"https://official.example/{name}" for name in documents}

    def fake_fetch(url: str, *, attempts: int = 3) -> bytes:
        assert attempts >= 1
        if "raw.githubusercontent.com" in url:
            return formula_payload
        return documents[url.rsplit("/", 1)[-1]].encode("utf-8")

    monkeypatch.setattr(module, "OPENAP_FORMULA_FILE", formula_file)
    monkeypatch.setattr(module, "DOCUMENT_URLS", document_urls)
    monkeypatch.setattr(
        module, "DOCUMENT_GROUPS", {name: (name,) for name in documents}
    )
    monkeypatch.setattr(module, "_fetch", fake_fetch)

    summary = module.run_rio_source_probe(
        output_dir=tmp_path,
        evidence_run_url="https://github.com/example/aurora/actions/runs/20",
        evidence_artifact="openap-181-rio-source-probe-results",
        implementation_commit="c" * 40,
    )

    assert summary["formula_sources_verified"] is True
    assert summary["formula_files"] == 1
    assert summary["formula_signals"] == 4
    assert summary["source_access_decision_complete"] is True
    assert summary["exact_free_authorized_source_found"] is False
    assert summary["raw_source_data_downloaded"] is False
    assert summary["raw_files_in_artifact"] is False
    assert summary["locked_opened"] is False
    assert summary["validation_used_for_selection"] is False
    evidence = pd.read_csv(tmp_path / "rio_batch_evidence.csv")
    assert len(evidence) == evidence["signal"].nunique() == 4
    assert evidence["strict_gate_result"].eq("blocked").all()
