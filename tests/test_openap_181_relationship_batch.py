from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pandas as pd
import pytest

from aurora.research.openap_181 import relationship_batch
from aurora.research.openap_181.relationship_batch import (
    OPENAP_COMMIT,
    OPENAP_FORMULA_SOURCES,
    RELATIONSHIP_BLOCKERS,
    RELATIONSHIP_FORMULA_REQUIREMENTS,
    RELATIONSHIP_SIGNAL_FAMILIES,
    RELATIONSHIP_SIGNALS,
    SOURCE_ASSESSMENTS,
    build_relationship_batch_evidence,
    evaluate_relationship_source_documents,
    write_relationship_source_probe_outputs,
)


EXPECTED_RELATIONSHIP_SIGNALS = {
    "CustomerMomentum",
    "iomom_cust",
    "iomom_supp",
    "retConglomerate",
    "sinAlgo",
}


def _official_document_fixtures() -> dict[str, str]:
    return {
        "bea_io": (
            "The InputOutput dataset provides make and use tables, direct requirements, "
            "and total requirements statistics. Input-output data are updated each year "
            "and provide information on 71 industry categories."
        ),
        "bea_terms": (
            "BEA statistics are public domain. The BEA API provides programmatic access "
            "to published economic statistics after free registration."
        ),
        "census_concordance": (
            "These tables provide direct relationships between classification systems, "
            "including 1987 SIC to 1997 and 2002 NAICS. Mappings may be one-to-many."
        ),
        "census_terms": "United States Census Bureau information is public domain.",
        "sec_api": (
            "EDGAR APIs require no authentication or API keys. Company Facts aggregates "
            "non-custom taxonomy facts that apply to the entire filing entity."
        ),
        "sec_xbrl": (
            "XBRL instances may include dimensions, domain members and segment information. "
            "Company-specific extensions and filing contexts remain part of the instance."
        ),
        "sec_reuse": "Government-created SEC and EDGAR public filing content is free to access and reuse.",
        "sec_fsd": (
            "Financial Statement Data Sets contain as-filed numeric data from April 2009, "
            "but do not provide all of the data available in filings and notes."
        ),
        "compustat_segments": (
            "Compustat Financials includes standardized segment data and point-in-time "
            "snapshots. Access requires a licensed data package and sign in."
        ),
        "factset_supply_chain": (
            "FactSet Supply Chain Relationships identifies customers and suppliers through "
            "time. It is a data feed and a subscription is required."
        ),
    }


def _valid_probe() -> dict[str, object]:
    probe = evaluate_relationship_source_documents(_official_document_fixtures())
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


def test_relationship_universe_formulas_and_families_are_frozen() -> None:
    assert RELATIONSHIP_SIGNALS == frozenset(EXPECTED_RELATIONSHIP_SIGNALS)
    assert set(OPENAP_FORMULA_SOURCES) == EXPECTED_RELATIONSHIP_SIGNALS
    assert set(RELATIONSHIP_FORMULA_REQUIREMENTS) == EXPECTED_RELATIONSHIP_SIGNALS
    assert set(RELATIONSHIP_SIGNAL_FAMILIES) == EXPECTED_RELATIONSHIP_SIGNALS
    assert set(RELATIONSHIP_BLOCKERS) == EXPECTED_RELATIONSHIP_SIGNALS
    assert OPENAP_COMMIT == "8db892442c2c3a3779b0f1eac4370d3655be15a1"
    assert OPENAP_FORMULA_SOURCES["CustomerMomentum"]["sha256"] == (
        "ea3f920fa3df6d261daf55de57b261083e7f853f7e18930cce8af2d5dc1168ce"
    )
    assert OPENAP_FORMULA_SOURCES["iomom_cust"] == OPENAP_FORMULA_SOURCES["iomom_supp"]
    assert RELATIONSHIP_SIGNAL_FAMILIES["CustomerMomentum"] == "firm_customer_links"
    assert RELATIONSHIP_SIGNAL_FAMILIES["iomom_supp"] == "bea_industry_network"
    assert RELATIONSHIP_SIGNAL_FAMILIES["retConglomerate"] == "business_segments"
    assert "five-year" in RELATIONSHIP_FORMULA_REQUIREMENTS["iomom_cust"]["timing"]
    assert "80%" in RELATIONSHIP_FORMULA_REQUIREMENTS["retConglomerate"]["formula"]


def test_official_documents_separate_free_components_from_exact_commercial_panels() -> None:
    summary = evaluate_relationship_source_documents(_official_document_fixtures())

    assert summary["official_documents_verified"] is True
    assert summary["source_access_decision_complete"] is True
    assert summary["unresolved_documents"] == []
    assert summary["bea_io_free_authorized"] is True
    assert summary["bea_industry_network_verified"] is True
    assert summary["census_historical_concordance_verified"] is True
    assert summary["census_concordance_unique_firm_bridge"] is False
    assert summary["sec_free_reuse_authorized"] is True
    assert summary["sec_companyfacts_entity_only"] is True
    assert summary["sec_full_segment_notes_in_fsd"] is False
    assert summary["compustat_segments_commercial_verified"] is True
    assert summary["factset_supply_chain_commercial_verified"] is True
    assert summary["exact_free_authorized_source_found"] is False
    assert summary["strict_approved"] == 0


def test_document_access_failure_is_recorded_without_becoming_approval() -> None:
    documents = _official_document_fixtures()
    documents["factset_supply_chain"] = ""
    summary = evaluate_relationship_source_documents(
        documents,
        access_errors={"factset_supply_chain": "HTTP Error 403: Forbidden"},
    )

    assert summary["official_documents_verified"] is False
    assert summary["source_access_decision_complete"] is True
    assert summary["access_blocked_documents"] == ["factset_supply_chain"]
    assert summary["unresolved_documents"] == []
    assert summary["exact_free_authorized_source_found"] is False
    assert summary["strict_approved"] == 0


def test_source_assessments_keep_free_components_and_exact_benchmarks_distinct() -> None:
    sources = {row["source_id"]: row for row in SOURCE_ASSESSMENTS}

    assert sources["bea_input_output"]["project_use_authorized"] is True
    assert sources["bea_input_output"]["exact_for_openap"] is False
    assert sources["census_naics_concordance"]["project_use_authorized"] is True
    assert sources["sec_edgar"]["project_use_authorized"] is True
    assert sources["sec_edgar"]["exact_for_openap"] is False
    assert sources["compustat_commercial"]["exact_for_openap"] is True
    assert sources["compustat_commercial"]["project_use_authorized"] is False
    assert sources["factset_supply_chain_commercial"]["project_use_authorized"] is False


def test_relationship_evidence_covers_five_signals_with_specific_blockers() -> None:
    evidence = build_relationship_batch_evidence(
        _valid_probe(),
        evidence_run_url="https://github.com/example/aurora/actions/runs/15",
        evidence_artifact="openap-181-relationship-source-probe-results",
        implementation_commit="d" * 40,
    ).set_index("signal")

    assert set(evidence.index) == EXPECTED_RELATIONSHIP_SIGNALS
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
    assert evidence["blocking_reason"].str.startswith("relationship_source_blocked:").all()
    assert "principal_customer_panel" in evidence.loc["CustomerMomentum", "blocking_reason"]
    assert "five_year_lagged_firm_naics" in evidence.loc["iomom_cust", "blocking_reason"]
    assert "segment_sales_80pct_assets" in evidence.loc["retConglomerate", "blocking_reason"]
    assert "full_history_segment_classification" in evidence.loc["sinAlgo", "blocking_reason"]
    assert evidence["blocking_reason"].nunique() == 5


def test_relationship_evidence_rejects_incomplete_or_promotable_probe() -> None:
    incomplete = _valid_probe()
    incomplete["source_access_decision_complete"] = False
    with pytest.raises(ValueError, match="Invalid or incomplete relationship probe evidence"):
        build_relationship_batch_evidence(
            incomplete,
            evidence_run_url="https://github.com/example/aurora/actions/runs/15",
            evidence_artifact="openap-181-relationship-source-probe-results",
            implementation_commit="d" * 40,
        )

    promotable = _valid_probe()
    promotable["exact_free_authorized_source_found"] = True
    with pytest.raises(ValueError, match="Invalid or incomplete relationship probe evidence"):
        build_relationship_batch_evidence(
            promotable,
            evidence_run_url="https://github.com/example/aurora/actions/runs/15",
            evidence_artifact="openap-181-relationship-source-probe-results",
            implementation_commit="d" * 40,
        )


def test_relationship_probe_outputs_are_metadata_only(tmp_path: Path) -> None:
    write_relationship_source_probe_outputs(
        _valid_probe(),
        output_dir=tmp_path,
        evidence_run_url="https://github.com/example/aurora/actions/runs/15",
        evidence_artifact="openap-181-relationship-source-probe-results",
        implementation_commit="e" * 40,
    )

    expected = {
        "relationship_source_probe.json",
        "relationship_source_assessment.csv",
        "relationship_formula_requirements.csv",
        "relationship_batch_evidence.csv",
        "RELATIONSHIP_SOURCE_PROBE_REPORT.md",
    }
    assert {path.name for path in tmp_path.iterdir()} == expected
    evidence = pd.read_csv(tmp_path / "relationship_batch_evidence.csv")
    formulas = pd.read_csv(tmp_path / "relationship_formula_requirements.csv")
    assert len(evidence) == evidence["signal"].nunique() == 5
    assert len(formulas) == formulas["signal"].nunique() == 5
    assert not any(
        token in path.name.lower()
        for path in tmp_path.iterdir()
        for token in ("raw", "filing_records", "segment_records", "returns")
    )


def test_live_relationship_probe_verifies_pinned_formulas_and_metadata_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    formula_payload = b"# pinned relationship formula fixture\n"
    formula_hash = sha256(formula_payload).hexdigest()
    formula_sources = {
        signal: {"path": f"Signals/pyCode/Predictors/{signal}.py", "sha256": formula_hash}
        for signal in EXPECTED_RELATIONSHIP_SIGNALS
    }
    documents = _official_document_fixtures()
    document_urls = {name: f"https://official.example/{name}" for name in documents}

    def fake_fetch(url: str, *, attempts: int = 3) -> bytes:
        assert attempts >= 1
        if "raw.githubusercontent.com" in url:
            return formula_payload
        return documents[url.rsplit("/", 1)[-1]].encode("utf-8")

    monkeypatch.setattr(relationship_batch, "OPENAP_FORMULA_SOURCES", formula_sources)
    monkeypatch.setattr(relationship_batch, "DOCUMENT_URLS", document_urls)
    monkeypatch.setattr(
        relationship_batch, "DOCUMENT_GROUPS", {name: (name,) for name in documents}
    )
    monkeypatch.setattr(relationship_batch, "_fetch", fake_fetch)

    summary = relationship_batch.run_relationship_source_probe(
        output_dir=tmp_path,
        evidence_run_url="https://github.com/example/aurora/actions/runs/16",
        evidence_artifact="openap-181-relationship-source-probe-results",
        implementation_commit="f" * 40,
    )

    assert summary["formula_sources_verified"] is True
    assert summary["formula_signals"] == 5
    assert summary["source_access_decision_complete"] is True
    assert summary["exact_free_authorized_source_found"] is False
    assert summary["raw_source_data_downloaded"] is False
    assert summary["raw_files_in_artifact"] is False
    assert summary["locked_opened"] is False
    assert summary["validation_used_for_selection"] is False
    evidence = pd.read_csv(tmp_path / "relationship_batch_evidence.csv")
    assert len(evidence) == evidence["signal"].nunique() == 5
    assert evidence["strict_gate_result"].eq("blocked").all()
