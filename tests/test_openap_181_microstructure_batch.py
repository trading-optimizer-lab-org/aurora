from __future__ import annotations

from hashlib import sha256
from importlib import import_module
from pathlib import Path

import pandas as pd
import pytest


EXPECTED_MICROSTRUCTURE_SIGNALS = {
    "BidAskSpread",
    "ProbInformedTrading",
    "zerotrade1M",
    "zerotrade6M",
    "zerotrade12M",
}


def _module():
    return import_module("aurora.research.openap_181.microstructure_batch")


def _official_document_fixtures() -> dict[str, str]:
    return {
        "openap_repo": (
            "Signals pyCode downloads data from WRDS. Prep scripts run on the WRDS Cloud. "
            "Predictors construct stock-level signals after the prep data are downloaded."
        ),
        "pin_authors": (
            "Legacy data contain original yearly PIN parameter estimates for 1993-2012, "
            "keyed by PERMNO. The current repository contains GPIN and OWR estimates for "
            "2003-2024 based on WRDS DTAQ Intraday Indicators; GPIN and OWR are distinct models."
        ),
        "twelve_pricing": (
            "Basic is free with 8 API credits per minute and 800 requests per day for "
            "internal non-display usage. An API key and account are required."
        ),
        "twelve_history": (
            "Daily OHLCV intervals contain history from the first trading date for most "
            "symbols. Intraday history is limited. Earliest date varies by instrument."
        ),
        "twelve_us_equities": (
            "Historical end-of-day data are available after midnight on the next trading "
            "day and cover listed US equities. OTC securities are not included by default."
        ),
        "nyse_taq": (
            "Daily TAQ contains all trades, quotes, NBBO and master files from 1993 to "
            "present. Historical access requires purchase and a data license."
        ),
        "crsp_wrds": (
            "CRSP daily stock files provide PERMNO, daily prices, bid low, ask high, volume, "
            "shares outstanding, delisting information and historical names. Access requires "
            "a separate CRSP institutional subscription and license."
        ),
    }


def _valid_probe() -> dict[str, object]:
    module = _module()
    probe = module.evaluate_microstructure_source_documents(
        _official_document_fixtures()
    )
    probe.update(
        {
            "formula_sources_verified": True,
            "formula_files": 4,
            "raw_source_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    return probe


def test_microstructure_universe_formulas_and_requirements_are_frozen() -> None:
    module = _module()

    assert module.MICROSTRUCTURE_SIGNALS == frozenset(
        EXPECTED_MICROSTRUCTURE_SIGNALS
    )
    assert set(module.MICROSTRUCTURE_FORMULA_REQUIREMENTS) == (
        EXPECTED_MICROSTRUCTURE_SIGNALS
    )
    assert set(module.MICROSTRUCTURE_BLOCKERS) == EXPECTED_MICROSTRUCTURE_SIGNALS
    assert module.OPENAP_COMMIT == "8db892442c2c3a3779b0f1eac4370d3655be15a1"
    assert module.OPENAP_FORMULA_FILES["BidAskSpread_predictor"]["sha256"] == (
        "ec53918eccd8117256dfc55acdaac97b784a9b47a396809a7db04def88490039"
    )
    assert module.OPENAP_FORMULA_FILES["ProbInformedTrading"]["sha256"] == (
        "0ce90bf2d8dc086ae6b39c7941c7c6b4e432e93cf87676fddf0f098c2fc175ab"
    )
    assert module.OPENAP_FORMULA_FILES["zerotrade"]["sha256"] == (
        "2d2ee47c3c695f21b114a7a13548d07eb517a08a6e0539dc2282743edf95498b"
    )
    assert module.OPENAP_FORMULA_FILES["BidAskSpread_prep"]["path"].endswith(
        "PrepScripts/corwin_schultz_edit.sas"
    )
    assert module.OPENAP_FORMULA_FILES["BidAskSpread_prep"]["sha256"] == (
        "551fdc4e58104e0a2180032d7b534e979951474f2f4259b1e897f6dd3d5847f0"
    )
    assert "minimum 12 daily observations" in (
        module.MICROSTRUCTURE_FORMULA_REQUIREMENTS["BidAskSpread"]["formula"]
    )
    assert "top 50%" in (
        module.MICROSTRUCTURE_FORMULA_REQUIREMENTS["ProbInformedTrading"]["formula"]
    )
    assert module.MICROSTRUCTURE_FORMULA_REQUIREMENTS["zerotrade1M"][
        "deflator"
    ] == 480_000
    assert module.MICROSTRUCTURE_FORMULA_REQUIREMENTS["zerotrade6M"][
        "deflator"
    ] == 11_000
    assert module.MICROSTRUCTURE_FORMULA_REQUIREMENTS["zerotrade12M"][
        "window_months"
    ] == 12


def test_official_documents_prove_partial_free_routes_but_no_exact_current_route() -> None:
    module = _module()
    summary = module.evaluate_microstructure_source_documents(
        _official_document_fixtures()
    )

    assert summary["official_documents_verified"] is True
    assert summary["source_access_decision_complete"] is True
    assert summary["unresolved_documents"] == []
    assert summary["openap_wrds_dependency_verified"] is True
    assert summary["pin_exact_legacy_through_2012_verified"] is True
    assert summary["pin_current_models_are_not_exact_pin"] is True
    assert summary["twelve_daily_ohlcv_free_authorized"] is True
    assert summary["twelve_permanent_identity_verified"] is False
    assert summary["twelve_zero_volume_calendar_semantics_verified"] is False
    assert summary["crsp_commercial_exact_inputs_verified"] is True
    assert summary["nyse_taq_commercial_verified"] is True
    assert summary["exact_free_authorized_source_found"] is False
    assert summary["strict_approved"] == 0


def test_document_access_failure_is_recorded_without_approval() -> None:
    module = _module()
    documents = _official_document_fixtures()
    documents["crsp_wrds"] = ""
    summary = module.evaluate_microstructure_source_documents(
        documents,
        access_errors={"crsp_wrds": "HTTP Error 403: Forbidden"},
    )

    assert summary["official_documents_verified"] is False
    assert summary["source_access_decision_complete"] is True
    assert summary["access_blocked_documents"] == ["crsp_wrds"]
    assert summary["unresolved_documents"] == []
    assert summary["exact_free_authorized_source_found"] is False
    assert summary["strict_approved"] == 0


def test_source_assessments_keep_partial_free_and_exact_commercial_routes_distinct() -> None:
    module = _module()
    sources = {row["source_id"]: row for row in module.SOURCE_ASSESSMENTS}

    assert sources["openap_official"]["project_use_authorized"] is True
    assert sources["hvidkjaer_pin_archive"]["exact_for_openap"] is True
    assert sources["hvidkjaer_pin_archive"]["current_coverage"] is False
    assert sources["edwin_hu_pin"]["project_use_authorized"] is True
    assert sources["edwin_hu_pin"]["exact_current_for_openap"] is False
    assert sources["twelve_data_basic"]["project_use_authorized"] is True
    assert sources["twelve_data_basic"]["exact_for_openap"] is False
    assert sources["crsp_stock_commercial"]["exact_for_openap"] is True
    assert sources["crsp_stock_commercial"]["project_use_authorized"] is False
    assert sources["nyse_taq_commercial"]["project_use_authorized"] is False


def test_microstructure_evidence_covers_five_signals_with_specific_blockers() -> None:
    module = _module()
    evidence = module.build_microstructure_batch_evidence(
        _valid_probe(),
        evidence_run_url="https://github.com/example/aurora/actions/runs/17",
        evidence_artifact="openap-181-microstructure-source-probe-results",
        implementation_commit="a" * 40,
    ).set_index("signal")

    assert set(evidence.index) == EXPECTED_MICROSTRUCTURE_SIGNALS
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
    assert evidence["blocking_reason"].str.startswith(
        "microstructure_source_blocked:"
    ).all()
    assert "bidlo_askhi" in evidence.loc["BidAskSpread", "blocking_reason"]
    assert "exact_pin" in evidence.loc["ProbInformedTrading", "blocking_reason"]
    assert "480000" in evidence.loc["zerotrade1M", "blocking_reason"]
    assert "six_month" in evidence.loc["zerotrade6M", "blocking_reason"]
    assert "twelve_month" in evidence.loc["zerotrade12M", "blocking_reason"]
    assert evidence["blocking_reason"].nunique() == 5


def test_microstructure_evidence_rejects_incomplete_or_promotable_probe() -> None:
    module = _module()
    incomplete = _valid_probe()
    incomplete["source_access_decision_complete"] = False
    with pytest.raises(ValueError, match="Invalid or incomplete microstructure probe"):
        module.build_microstructure_batch_evidence(
            incomplete,
            evidence_run_url="https://github.com/example/aurora/actions/runs/17",
            evidence_artifact="openap-181-microstructure-source-probe-results",
            implementation_commit="a" * 40,
        )

    promotable = _valid_probe()
    promotable["exact_free_authorized_source_found"] = True
    with pytest.raises(ValueError, match="Invalid or incomplete microstructure probe"):
        module.build_microstructure_batch_evidence(
            promotable,
            evidence_run_url="https://github.com/example/aurora/actions/runs/17",
            evidence_artifact="openap-181-microstructure-source-probe-results",
            implementation_commit="a" * 40,
        )


def test_microstructure_probe_outputs_are_metadata_only(tmp_path: Path) -> None:
    module = _module()
    module.write_microstructure_source_probe_outputs(
        _valid_probe(),
        output_dir=tmp_path,
        evidence_run_url="https://github.com/example/aurora/actions/runs/17",
        evidence_artifact="openap-181-microstructure-source-probe-results",
        implementation_commit="b" * 40,
    )

    expected = {
        "microstructure_source_probe.json",
        "microstructure_source_assessment.csv",
        "microstructure_formula_requirements.csv",
        "microstructure_batch_evidence.csv",
        "MICROSTRUCTURE_SOURCE_PROBE_REPORT.md",
    }
    assert {path.name for path in tmp_path.iterdir()} == expected
    evidence = pd.read_csv(tmp_path / "microstructure_batch_evidence.csv")
    formulas = pd.read_csv(tmp_path / "microstructure_formula_requirements.csv")
    assert len(evidence) == evidence["signal"].nunique() == 5
    assert len(formulas) == formulas["signal"].nunique() == 5
    assert not any(
        token in path.name.lower()
        for path in tmp_path.iterdir()
        for token in ("raw", "ohlcv", "trades", "quotes", "pin_parameters")
    )


def test_live_probe_verifies_pinned_formulas_and_metadata_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    formula_payloads = {
        name: f"# pinned {name} formula fixture\n".encode("utf-8")
        for name in module.OPENAP_FORMULA_FILES
    }
    formula_files = {
        name: {
            "path": details["path"],
            "sha256": sha256(formula_payloads[name]).hexdigest(),
        }
        for name, details in module.OPENAP_FORMULA_FILES.items()
    }
    documents = _official_document_fixtures()
    document_urls = {name: f"https://official.example/{name}" for name in documents}

    def fake_fetch(url: str, *, attempts: int = 3) -> bytes:
        assert attempts >= 1
        if "raw.githubusercontent.com" in url:
            path = url.split(f"/{module.OPENAP_COMMIT}/", 1)[1]
            name = next(
                key for key, details in formula_files.items() if details["path"] == path
            )
            return formula_payloads[name]
        return documents[url.rsplit("/", 1)[-1]].encode("utf-8")

    monkeypatch.setattr(module, "OPENAP_FORMULA_FILES", formula_files)
    monkeypatch.setattr(module, "DOCUMENT_URLS", document_urls)
    monkeypatch.setattr(
        module, "DOCUMENT_GROUPS", {name: (name,) for name in documents}
    )
    monkeypatch.setattr(module, "_fetch", fake_fetch)

    summary = module.run_microstructure_source_probe(
        output_dir=tmp_path,
        evidence_run_url="https://github.com/example/aurora/actions/runs/18",
        evidence_artifact="openap-181-microstructure-source-probe-results",
        implementation_commit="c" * 40,
    )

    assert summary["formula_sources_verified"] is True
    assert summary["formula_files"] == 4
    assert summary["source_access_decision_complete"] is True
    assert summary["exact_free_authorized_source_found"] is False
    assert summary["raw_source_data_downloaded"] is False
    assert summary["raw_files_in_artifact"] is False
    assert summary["locked_opened"] is False
    assert summary["validation_used_for_selection"] is False
    evidence = pd.read_csv(tmp_path / "microstructure_batch_evidence.csv")
    assert len(evidence) == evidence["signal"].nunique() == 5
    assert evidence["strict_gate_result"].eq("blocked").all()
