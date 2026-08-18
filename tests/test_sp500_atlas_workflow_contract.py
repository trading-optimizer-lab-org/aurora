from __future__ import annotations

from pathlib import Path
import json


ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/sp500-atlas-run.yml"
POSTRUN_WORKFLOW = ROOT / ".github/workflows/sp500-atlas-postrun.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_uses_exact_commit_and_static_shards() -> None:
    text = _text()
    assert "ref: ${{ github.sha }}" in text
    assert 'run: test "$ATLAS_REQUESTED_COMMIT_SHA" = "$GITHUB_SHA"' in text
    assert "run_sp500_atlas_worker.py" in text
    assert "reduce_sp500_atlas_run.py" in text
    assert text.count("max-parallel: 120") == 3
    assert text.count("fail-fast: false") == 3
    assert "recipe_count" in text
    assert "total_shards" in text
    assert "smoke_serial" in text
    assert "launch_authorization" in text
    assert "ATLAS_FROZEN_FULL_PLAN_ACCEPTED" in text
    assert "atlas_campaign_selection.json" in text
    assert "selection_sha256" in text


def test_workflow_has_bounded_retries_and_no_dynamic_claim_loop() -> None:
    text = _text().lower()
    assert "for attempt in 1 2 3" in text
    assert "claim" not in text
    assert "database" not in text
    assert "neon" not in text
    assert "continue_segment" not in text
    assert "workflow_run" not in text


def test_workflow_preserves_train_only_boundaries_and_final_failure_gate() -> None:
    text = _text()
    assert "train_snapshot_1993_2010" in text or "runtime_input_run_id" in text
    assert "validation_opened" in text
    assert "locked_opened" in text
    assert "Require complete shard set and preserve all rows" in text
    assert "if: ${{ always() && needs.preflight.result == 'success' && inputs.run_mode == 'full' }}" in text


def test_freeze_manifest_binds_exact_plan_and_keeps_launch_closed() -> None:
    freeze = json.loads(
        (ROOT / "config/sp500_atlas_1/freeze_manifest_v1.json").read_text(encoding="utf-8")
    )
    assert freeze["requested_recipe_count"] == 12079704
    assert freeze["total_shards"] == 360
    assert freeze["train_end"] == "2010-12-31"
    assert freeze["validation_opened"] is False
    assert freeze["locked_opened"] is False
    assert freeze["execution_authorized"] is False
    assert freeze["launch_authorized"] is False
    assert freeze["required_launch_authorization"] == "AUTHORIZE_SP500_ATLAS_FULL_RUN"


def test_atlas_workflows_do_not_checkout_or_execute_untrusted_commit_inputs() -> None:
    calibration = (ROOT / ".github/workflows/sp500-atlas-calibration.yml").read_text(
        encoding="utf-8"
    )
    run = _text()
    assert "ref: ${{ inputs.commit_sha }}" not in calibration
    assert "ref: ${{ inputs.commit_sha }}" not in run
    assert 'ref: ${{ github.sha }}' in calibration
    assert 'ref: ${{ github.sha }}' in run
    assert 'run: test "$ATLAS_REQUESTED_COMMIT_SHA" = "$GITHUB_SHA"' in calibration
    assert 'run: test "$ATLAS_REQUESTED_COMMIT_SHA" = "$GITHUB_SHA"' in run


def test_postrun_workflow_is_train_only_and_publishes_robustness_audit() -> None:
    text = POSTRUN_WORKFLOW.read_text(encoding="utf-8")
    assert "run_sp500_atlas_robustness.py" in text
    assert "report_sp500_atlas_multiple_testing.py" in text
    assert "create_sp500_atlas_final_audit.py" in text
    assert "validation_opened" in text
    assert "locked_opened" in text
    assert "sp500-atlas-postrun-results" in text
