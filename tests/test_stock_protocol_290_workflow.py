"""Static contract for the immutable original-290 event-study workflow."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / ".github/workflows/_stock-protocol-original-290-event-study.yml"
DISPATCH = ROOT / ".github/workflows/stock-protocol-original-290-event-study.yml"
RECOVERY = ROOT / ".github/workflows/stock-protocol-original-290-event-study-recovery.yml"
FX_ARTIFACT = "stock-protocol-290-frozen-fx"
FX_RATES = "stock-protocol-290-fx-rates.csv"


def test_workflows_are_valid_yaml() -> None:
    core = yaml.safe_load(CORE.read_text(encoding="utf-8"))
    dispatch = yaml.safe_load(DISPATCH.read_text(encoding="utf-8"))
    recovery = yaml.safe_load(RECOVERY.read_text(encoding="utf-8"))
    assert core["name"] == "Stock Protocol Original 290 Event Study Core"
    assert dispatch["name"] == "Stock Protocol Original 290 Opportunity Event Study"
    assert recovery["name"] == (
        "Stock Protocol Original 290 Opportunity Event Study Recovery"
    )


def test_recovery_splits_only_the_missing_shard_and_reuses_completed_artifacts() -> None:
    document = yaml.safe_load(RECOVERY.read_text(encoding="utf-8"))
    matrix = document["jobs"]["missing-slice"]["strategy"]["matrix"]["include"]
    assert [(row["exit_start"], row["exit_end"]) for row in matrix] == [
        (0, 5),
        (5, 10),
        (10, 15),
        (15, 20),
        (20, 25),
        (25, 29),
    ]
    text = RECOVERY.read_text(encoding="utf-8")
    assert "--entry-index 7" in text
    assert "--period A" in text
    assert "${{ inputs.source_run_id }}" in text
    assert "stock-protocol-290-historical-*" in text
    assert "verify_stock_protocol_290_event_study.py final" in text


def test_workflow_pins_all_required_sources() -> None:
    text = CORE.read_text(encoding="utf-8")
    for required in (
        "29658603488",
        "29804082610",
        "29688666475",
        "29684671183",
        "29645606473",
        "stock-protocol-original-290-contract",
    ):
        assert required in text
    assert "verify_stock_protocol_290_sources.py" in text


def test_contract_downloads_and_consumes_audit_and_exact_artifacts() -> None:
    document = yaml.safe_load(CORE.read_text(encoding="utf-8"))
    steps = document["jobs"]["contract"]["steps"]
    downloads = [
        step["with"]
        for step in steps
        if step.get("uses") == "actions/download-artifact@v4"
    ]

    assert any(
        item.get("run-id") == "${{ env.AUDIT_RUN_ID }}"
        and item.get("name") == "${{ env.AUDIT_ARTIFACT }}"
        and item.get("path") == "audit-source"
        for item in downloads
    )
    assert any(
        item.get("run-id") == "${{ env.EXACT_RUN_ID }}"
        and item.get("name") == "${{ env.EXACT_ARTIFACT }}"
        and item.get("path") == "exact-source"
        for item in downloads
    )
    prepare = next(step for step in steps if step.get("name") == "Prepare frozen causal FX once")
    assert "--audit-root audit-source" in prepare["run"]
    assert "--exact-root exact-source" in prepare["run"]
    assert "--source-lock stock-protocol-290-source-lock.json" in prepare["run"]


def test_fx_is_uploaded_once_and_merge_must_consume_the_frozen_file() -> None:
    document = yaml.safe_load(CORE.read_text(encoding="utf-8"))
    contract_steps = document["jobs"]["contract"]["steps"]
    fx_uploads = [
        step
        for step in contract_steps
        if step.get("uses") == "actions/upload-artifact@v4"
        and step["with"].get("name") == FX_ARTIFACT
    ]
    assert len(fx_uploads) == 1
    assert fx_uploads[0]["with"]["path"] == "fx-rates"

    merge_steps = document["jobs"]["merge-and-verify"]["steps"]
    fx_download = next(
        step
        for step in merge_steps
        if step.get("uses") == "actions/download-artifact@v4"
        and step["with"].get("name") == FX_ARTIFACT
    )
    assert fx_download["with"]["path"] == "fx-rates"
    verify = next(
        step for step in merge_steps if step.get("name") == "Verify frozen FX artifact"
    )
    assert "--verify-root fx-rates" in verify["run"]
    merge = next(step for step in merge_steps if step.get("name") == "Merge statistics, audits and report")
    assert f"--fx-rates fx-rates/{FX_RATES}" in merge["run"]


def test_final_artifact_preserves_source_lock_and_fx_provenance_before_verification() -> None:
    document = yaml.safe_load(CORE.read_text(encoding="utf-8"))
    steps = document["jobs"]["merge-and-verify"]["steps"]
    preserve_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Preserve frozen source evidence in final artifact"
    )
    verify_index = next(
        index
        for index, step in enumerate(steps)
        if step.get("name") == "Fail hard unless the final contract is complete"
    )
    preserve = steps[preserve_index]["run"]
    assert preserve_index < verify_index
    assert "contract/stock-protocol-290-source-lock.json" in preserve
    assert "fx-rates/stock-protocol-290-fx-source-lock.json" in preserve
    assert "_artifact_manifest" in preserve


def test_workflow_uses_ten_historical_and_thirty_corrected_shards() -> None:
    document = yaml.safe_load(CORE.read_text(encoding="utf-8"))
    historical = document["jobs"]["historical-replication"]["strategy"]["matrix"]
    corrected = document["jobs"]["corrected-event-study"]["strategy"]["matrix"]
    assert historical["entry_index"] == list(range(10))
    assert corrected["entry_index"] == list(range(10))
    assert corrected["period"] == ["A", "B", "C"]
    assert document["jobs"]["historical-replication"]["timeout-minutes"] < 360
    assert document["jobs"]["corrected-event-study"]["timeout-minutes"] < 360


def test_final_artifact_is_only_uploaded_after_successful_verification() -> None:
    text = CORE.read_text(encoding="utf-8")
    final = text.split("name: stock-protocol-original-290-opportunity-event-study", 1)[0]
    assert "verify_stock_protocol_290_event_study.py final" in final
    assert "if: always()" not in text
    assert "simulate_daily_portfolio" not in text
    assert "max_positions" not in text


def test_workflow_declares_cutoff_and_diagnostic_roles_in_code_contract() -> None:
    text = CORE.read_text(encoding="utf-8")
    assert "tests/test_stock_protocol_independent_opportunity_executor.py" in text
    assert "tests/test_stock_protocol_290_statistics.py" in text
    assert "tests/test_stock_protocol_290_shards.py" in text
    assert "tests/test_stock_protocol_290_merge.py" in text
    assert "tests/test_stock_protocol_290_workflow.py" in text
