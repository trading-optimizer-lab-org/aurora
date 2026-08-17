from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/sp500-atlas-run.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_uses_exact_commit_and_static_shards() -> None:
    text = _text()
    assert "ref: ${{ inputs.commit_sha }}" in text
    assert "run_sp500_atlas_worker.py" in text
    assert "reduce_sp500_atlas_run.py" in text
    assert text.count("max-parallel: 120") == 3
    assert text.count("fail-fast: false") == 3
    assert "recipe_count" in text
    assert "total_shards" in text
    assert "smoke_serial" in text
    assert "launch_authorization" in text
    assert "ATLAS_FROZEN_FULL_PLAN_ACCEPTED" in text


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
