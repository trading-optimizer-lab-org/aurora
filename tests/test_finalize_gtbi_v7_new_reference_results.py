from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from infra.gtbi_v7_new_reference import campaign
from scripts import finalize_gtbi_v7_new_reference_results as finalizer
from infra.gtbi_v7_readiness.canonical import canonical_bytes


def test_final_locked_scan_rejects_post_2020_rows(tmp_path: Path) -> None:
    pd.DataFrame([{"candidate_id": "x", "entry_date": "2021-01-04"}]).to_csv(
        tmp_path / "top_trades_sample.csv", index=False
    )
    with pytest.raises(ValueError, match="locked result rows"):
        finalizer._assert_no_locked_result_rows(tmp_path)


def test_final_locked_scan_accepts_historical_rows_only(tmp_path: Path) -> None:
    pd.DataFrame([{"candidate_id": "x", "entry_date": "2020-12-31"}]).to_csv(
        tmp_path / "top_trades_sample.csv", index=False
    )
    pd.DataFrame([{"candidate_id": "x", "year": 2020}]).to_csv(
        tmp_path / "yearly_trade_performance.csv", index=False
    )
    finalizer._assert_no_locked_result_rows(tmp_path)


def test_finalizer_seals_identity_limitations_and_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    summary = {"campaign_fingerprint": "fp", "best_candidate_id": "best"}
    (artifact / "summary.json").write_text(json.dumps(summary) + "\n", encoding="utf-8")
    verification = {
        "terminal_count": 72_000,
        "leaderboard_rows": 12_000,
        "early_rejected_rows": 60_000,
        "best_candidate_id": "best",
    }
    monkeypatch.setattr(finalizer, "validate_artifact", lambda *args, **kwargs: verification)
    monkeypatch.setattr(
        finalizer,
        "verify_v7_campaign_plan",
        lambda **kwargs: {
            "inputs": {"execution_mode": "optimized_evaluation_v5_event_first"},
            "v7_campaign_contract": {"contract_digest": "sha256:contract"},
        },
    )
    monkeypatch.setattr(
        finalizer,
        "validate_benchmark_evidence",
        lambda **kwargs: {
            "selected_processes_per_runner": 4,
            "selected_symbol_workers_per_process": 1,
            "effective_cpu_count": 4,
            "receipt_digest": "sha256:benchmark",
        },
    )
    monkeypatch.setattr(
        finalizer,
        "validate_smoke_evidence",
        lambda **kwargs: {"receipt_digest": "sha256:smoke"},
    )
    monkeypatch.setattr(finalizer, "_assert_no_locked_result_rows", lambda root: None)
    report = finalizer.finalize(
        artifact_root=artifact,
        plan_root=tmp_path / "plan",
        data_manifest_path=tmp_path / "data.json",
        authorization_path=tmp_path / "auth.json",
        benchmark_path=tmp_path / "benchmark.json",
        smoke_validation_path=tmp_path / "smoke.json",
    )
    sealed = json.loads((artifact / "summary.json").read_text(encoding="utf-8"))
    assert report["historical_campaign_complete"] is True
    assert report["terminal_strategy_identities"] == 72_000
    assert sealed["campaign_id"] == campaign.CAMPAIGN_ID
    assert sealed["locked_authorized"] is False
    assert sealed["locked_data_accessed"] is False
    assert sealed["historical_exclusion_start"] == "2021-01-01"
    assert sealed["survivorship_biased"] is True
    assert sealed["point_in_time_universe"] is False
    assert (artifact / "v7_final_report.json").is_file()
    assert (artifact / "v7_artifact_inventory.json").is_file()


def test_finalizer_binds_merge_recovery_to_original_scientific_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "summary.json").write_text(
        json.dumps({"campaign_fingerprint": "fp", "best_candidate_id": "best"}) + "\n",
        encoding="utf-8",
    )
    verification = {
        "terminal_count": 72_000,
        "leaderboard_rows": 71_865,
        "early_rejected_rows": 135,
        "best_candidate_id": "best",
    }
    monkeypatch.setattr(finalizer, "validate_artifact", lambda *args, **kwargs: verification)
    observed: dict[str, object] = {}

    def verify_plan(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {
            "inputs": {"execution_mode": "optimized_evaluation_v6_fast_strict"},
            "v7_campaign_contract": {"contract_digest": "sha256:contract"},
        }

    monkeypatch.setattr(finalizer, "verify_v7_campaign_plan", verify_plan)
    monkeypatch.setattr(
        finalizer,
        "validate_benchmark_evidence",
        lambda **kwargs: {
            "selected_processes_per_runner": 4,
            "selected_symbol_workers_per_process": 1,
            "effective_cpu_count": 4,
            "receipt_digest": "sha256:benchmark",
        },
    )
    monkeypatch.setattr(
        finalizer,
        "validate_smoke_evidence",
        lambda **kwargs: {"receipt_digest": "sha256:smoke"},
    )
    monkeypatch.setattr(finalizer, "_assert_no_locked_result_rows", lambda root: None)
    scientific_sha = "a" * 40
    recovery_sha = "b" * 40
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_SHA", recovery_sha)
    receipt = {
        "schema_version": "gtbi_v7_new_reference_merge_recovery_receipt_v1",
        "source_full_run_id": 100,
        "source_block_run_id": 101,
        "source_scientific_commit_sha": scientific_sha,
        "merge_recovery_run_id": 102,
        "merge_recovery_commit_sha": recovery_sha,
        "scientific_recalculation_performed": False,
        "locked_authorized": False,
        "locked_data_accessed": False,
        "historical_exclusion_start": "2021-01-01",
    }
    receipt["receipt_digest"] = "sha256:" + hashlib.sha256(canonical_bytes(receipt)).hexdigest()
    receipt_path = artifact / "merge_recovery_receipt.json"
    receipt_path.write_bytes(canonical_bytes(receipt) + b"\n")

    report = finalizer.finalize(
        artifact_root=artifact,
        plan_root=tmp_path / "plan",
        data_manifest_path=tmp_path / "data.json",
        authorization_path=tmp_path / "auth.json",
        benchmark_path=tmp_path / "benchmark.json",
        smoke_validation_path=tmp_path / "smoke.json",
        merge_recovery_receipt_path=receipt_path,
    )

    assert observed["expected_code_sha"] == scientific_sha
    assert report["merge_recovery"] is True
    assert report["scientific_recalculation_performed"] is False
    assert report["source_full_run_id"] == 100
