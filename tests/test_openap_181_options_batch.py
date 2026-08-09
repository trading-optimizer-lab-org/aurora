from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from aurora.research.openap_181.options_batch import (
    OPENAP_COMMIT,
    OPENAP_FORMULA_SOURCES,
    OPTION_FORMULA_REQUIREMENTS,
    OPTION_SIGNALS,
    build_options_batch_evidence,
    evaluate_options_source_documents,
    write_options_source_probe_outputs,
)


EXPECTED_OPTION_SIGNALS = {
    "CPVolSpread",
    "RIVolSpread",
    "SmileSlope",
    "skew1",
    "dCPVolSpread",
    "dVolCall",
    "dVolPut",
    "OptionVolume1",
    "OptionVolume2",
}


def _official_document_fixtures() -> dict[str, str]:
    return {
        "marketdata": (
            "Options chains include IV, delta, volume and open interest. Free plan has "
            "1 year historical options. Personal non-professional use only; research and "
            "testing beyond personal usage are professional use."
        ),
        "massive": (
            "Options Basic $0/month. 2 Years Historical Data, End of Day Data, "
            "Individual Use. Minute aggregates include OHLC and volume."
        ),
        "tradier_history": (
            "Historical pricing accepts an OCC option symbol and returns date, open, high, "
            "low, close and volume."
        ),
        "tradier_rights": (
            "Unless you are a Tradier Partner, Tradier APIs are entitled for personal use only."
        ),
        "occ_data": (
            "Volume Query supports underlying symbol, calls and puts, daily, weekly and "
            "monthly reports. Data available for the past 24 months."
        ),
        "occ_terms": (
            "Do not use or launch any automated system, including robots, spiders, or "
            "offline readers, to access the Services."
        ),
        "cboe_delayed": (
            "It is strictly prohibited to download delayed quote table data using "
            "auto-extraction programs, queries or software."
        ),
        "cboe_volume": (
            "Download historical options volume across Cboe exchanges by a single symbol, "
            "product type, or all symbols for a month or year."
        ),
        "alpha_vantage": (
            "Historical Options returns a full historical options chain covering 15+ years. "
            "Subscribe to any premium membership plan to unlock historical options data."
        ),
        "optionmetrics": (
            "IvyDB US contains a complete historical record from January 1996, a standardized "
            "constant-maturity volatility surface, corporate actions and a permanent ID."
        ),
        "wrds": "Option Suite requires subscription to OptionMetrics data.",
    }


def _valid_probe() -> dict[str, object]:
    summary = evaluate_options_source_documents(_official_document_fixtures())
    summary.update(
        {
            "formula_sources_verified": True,
            "raw_market_data_downloaded": False,
            "raw_files_in_artifact": False,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }
    )
    return summary


def test_option_signal_universe_and_formula_sources_are_frozen() -> None:
    assert OPTION_SIGNALS == frozenset(EXPECTED_OPTION_SIGNALS)
    assert set(OPENAP_FORMULA_SOURCES) == EXPECTED_OPTION_SIGNALS
    assert set(OPTION_FORMULA_REQUIREMENTS) == EXPECTED_OPTION_SIGNALS
    assert OPENAP_COMMIT == "8db892442c2c3a3779b0f1eac4370d3655be15a1"
    assert all(len(item["sha256"]) == 64 for item in OPENAP_FORMULA_SOURCES.values())


def test_document_contract_distinguishes_partial_free_routes_from_exact_benchmark() -> None:
    summary = evaluate_options_source_documents(_official_document_fixtures())

    assert summary["official_documents_verified"] is True
    assert summary["marketdata_free_history_years"] == 1
    assert summary["massive_free_history_years"] == 2
    assert summary["occ_history_months"] == 24
    assert summary["tradier_historical_fields"] == "ohlcv_only"
    assert summary["optionmetrics_history_start"] == "1996-01-01"
    assert summary["optionmetrics_commercial_benchmark_verified"] is True
    assert summary["exact_free_authorized_source_found"] is False
    assert summary["strict_approved"] == 0


def test_occ_http_403_is_a_concrete_fail_closed_access_blocker() -> None:
    documents = _official_document_fixtures()
    documents["occ_data"] = ""

    summary = evaluate_options_source_documents(
        documents,
        access_errors={"occ_data": "HTTP Error 403: Forbidden"},
    )

    assert summary["official_documents_verified"] is False
    assert summary["source_access_decision_complete"] is True
    assert summary["access_blocked_documents"] == ["occ_data"]
    assert summary["unresolved_documents"] == []
    assert summary["exact_free_authorized_source_found"] is False
    assert summary["strict_approved"] == 0


def test_options_evidence_covers_all_nine_signals_without_promotion() -> None:
    evidence = build_options_batch_evidence(
        _valid_probe(),
        evidence_run_url="https://github.com/example/aurora/actions/runs/12",
        evidence_artifact="openap-181-options-source-probe-results",
        implementation_commit="a" * 40,
    ).set_index("signal")

    assert set(evidence.index) == EXPECTED_OPTION_SIGNALS
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
    assert evidence["blocking_reason"].str.startswith("options_source_blocked:").all()
    assert "30_day_delta_surface" in evidence.loc["dVolPut", "blocking_reason"]
    assert "t_minus_6_to_t_minus_1" in evidence.loc[
        "OptionVolume2", "blocking_reason"
    ]


def test_options_evidence_rejects_incomplete_or_promotable_probe() -> None:
    incomplete = _valid_probe()
    incomplete["official_documents_verified"] = False
    incomplete["source_access_decision_complete"] = False
    incomplete["unresolved_documents"] = ["occ_data"]
    with pytest.raises(ValueError, match="Invalid or incomplete options probe evidence"):
        build_options_batch_evidence(
            incomplete,
            evidence_run_url="https://github.com/example/aurora/actions/runs/12",
            evidence_artifact="openap-181-options-source-probe-results",
            implementation_commit="a" * 40,
        )

    exact = _valid_probe()
    exact["exact_free_authorized_source_found"] = True
    with pytest.raises(ValueError, match="Invalid or incomplete options probe evidence"):
        build_options_batch_evidence(
            exact,
            evidence_run_url="https://github.com/example/aurora/actions/runs/12",
            evidence_artifact="openap-181-options-source-probe-results",
            implementation_commit="a" * 40,
        )


def test_options_probe_outputs_are_metadata_only(tmp_path: Path) -> None:
    write_options_source_probe_outputs(
        _valid_probe(),
        output_dir=tmp_path,
        evidence_run_url="https://github.com/example/aurora/actions/runs/12",
        evidence_artifact="openap-181-options-source-probe-results",
        implementation_commit="b" * 40,
    )

    expected = {
        "options_source_probe.json",
        "options_source_assessment.csv",
        "options_formula_requirements.csv",
        "options_batch_evidence.csv",
        "OPTIONS_SOURCE_PROBE_REPORT.md",
    }
    assert {path.name for path in tmp_path.iterdir()} == expected
    evidence = pd.read_csv(tmp_path / "options_batch_evidence.csv")
    assert len(evidence) == 9
    assert not any(
        token in path.name.lower()
        for path in tmp_path.iterdir()
        for token in ("raw", "trade", "quote", "chain")
    )
