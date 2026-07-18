"""Static contracts for the complete GitHub-only scientific campaign."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAYER_WORKFLOW = ROOT / ".github" / "workflows" / "_stock-protocol-scientific-layer.yml"
CAMPAIGN_WORKFLOW = ROOT / ".github" / "workflows" / "stock-protocol-scientific-rebuild-360jobs.yml"
RECOVERY_WORKFLOW = ROOT / ".github" / "workflows" / "stock-protocol-scientific-recovery-360jobs.yml"
PORTFOLIO_RECOVERY_WORKFLOW = (
    ROOT
    / ".github"
    / "workflows"
    / "stock-protocol-scientific-resume-from-exits-360jobs.yml"
)
FINALIZE_WORKFLOW = ROOT / ".github" / "workflows" / "stock-protocol-scientific-finalize-existing-run.yml"
HOLDOUT_FINALIZE_WORKFLOW = (
    ROOT
    / ".github"
    / "workflows"
    / "_stock-protocol-scientific-holdout-finalize.yml"
)


def test_reusable_layer_workflow_has_real_dynamic_matrices_and_strict_merge():
    text = LAYER_WORKFLOW.read_text(encoding="utf-8")
    assert text.count("max-parallel: 180") == 2
    assert "matrix_a" in text and "matrix_b" in text
    assert "run_stock_protocol_scientific_pipeline.py plan" in text
    assert "run_stock_protocol_scientific_pipeline.py evaluate" in text
    assert "run_stock_protocol_scientific_pipeline.py merge" in text
    assert "continue-on-error" not in text
    assert "task=-1" not in text


def test_campaign_is_bounded_chained_and_uses_360_real_robustness_jobs():
    text = CAMPAIGN_WORKFLOW.read_text(encoding="utf-8")
    assert "--end 2021-01-01" in text
    assert "build-benchmarks" in text
    assert 'DATA_END: "2020-12-31"' in text
    assert 'LOCKED_START: "2021-01-01"' in text
    for layer in ("signal", "weights", "entries", "exits", "portfolio", "costs"):
        assert f"layer: {layer}" in text
    assert "task_count=360" in text or "--task-count 360" in text
    assert text.count("max-parallel: 180") >= 2
    assert "freeze-robustness" in text
    assert "holdout" in text
    assert "needs: robustness_merge" in text
    assert "finalize_stock_protocol_scientific.py" in text
    assert "stock-protocol-scientific-rebuild-360jobs-results" in text
    assert "continue-on-error" not in text


def test_campaign_runs_on_github_and_never_uses_validation_or_locked_for_selection():
    text = CAMPAIGN_WORKFLOW.read_text(encoding="utf-8")
    assert "runs-on: ubuntu-latest" in text
    assert "locked_opened=false" in text
    assert "validation_used_for_selection=false" in text
    assert "AURORA_ALLOW_LOCAL_RUNS_EXPLICIT" not in text
    assert "2016-01-01" not in text.split("holdout:", 1)[0]


def test_campaign_assembles_every_required_artifact_file():
    text = CAMPAIGN_WORKFLOW.read_text(encoding="utf-8")
    for name in (
        "signal_results.csv",
        "weight_results.csv",
        "entry_results.csv",
        "exit_results.csv",
        "portfolio_results.csv",
        "cost_results.csv",
        "walk_forward_results.csv",
        "robustness_results.csv",
        "parameter_stability.csv",
        "statistical_tests.csv",
        "holdout_2016_2020.csv",
    ):
        assert name in text


def test_recovery_reuses_only_frozen_layers_and_repeats_real_robustness():
    text = RECOVERY_WORKFLOW.read_text(encoding="utf-8")
    for artifact in (
        "stock-protocol-scientific-pack",
        "stock-protocol-signal-merged",
        "stock-protocol-weights-merged",
        "stock-protocol-entries-merged",
        "stock-protocol-exits-merged",
        "stock-protocol-portfolio-merged",
        "stock-protocol-costs-merged",
    ):
        assert artifact in text
    assert "--task-count 360" in text
    assert text.count("max-parallel: 180") == 2
    assert "freeze-robustness" in text
    assert "needs: robustness_merge" in text
    assert "stock-protocol-scientific-rebuild-360jobs-results" in text
    assert "continue-on-error" not in text


def test_recovery_is_github_only_and_keeps_locked_closed():
    text = RECOVERY_WORKFLOW.read_text(encoding="utf-8")
    assert 'DATA_END: "2020-12-31"' in text
    assert 'LOCKED_START: "2021-01-01"' in text
    assert "locked_opened=false" in text
    assert "validation_used_for_selection=false" in text
    assert "AURORA_ALLOW_LOCAL_RUNS_EXPLICIT" not in text


def test_recovery_detects_and_preserves_the_full_universe_pack():
    text = RECOVERY_WORKFLOW.read_text(encoding="utf-8")
    assert "aurora-full-us-daily-pre2021" in text
    assert "full_universe" in text
    assert "timeout-minutes: 360" in text
    for name in (
        "full_dataset_inventory.csv",
        "full_dataset_audit.json",
        "two_symbol_root_cause.md",
        "pre2021_pack_audit.json",
        "pre2021_symbol_coverage.csv",
        "data_shard_manifest.json",
        "dataset_exclusions.csv",
    ):
        assert name in text
    assert "stock-protocol-scientific-full-universe-360jobs-results" in text


def test_recovery_prepares_ten_frozen_candidates_in_parallel_before_robustness():
    text = RECOVERY_WORKFLOW.read_text(encoding="utf-8")

    assert "prepare_candidates:" in text
    assert "candidate_index: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]" in text
    assert "max-parallel: 10" in text
    assert "prepare-candidate" in text
    assert "merge-candidates" in text
    assert "needs: [recover_source, prepare_candidates]" in text
    assert "run_stock_protocol_scientific_postselection.py prepare\n" not in text


def test_registered_recovery_can_dispatch_resume_from_exits_without_touching_main():
    text = RECOVERY_WORKFLOW.read_text(encoding="utf-8")
    assert "resume_from_exits" in text
    assert (
        "uses: ./.github/workflows/_stock-protocol-scientific-holdout-finalize.yml"
        in text
    )
    assert "source_run_id: ${{ inputs.source_run_id }}" in text


def test_portfolio_recovery_resumes_from_frozen_exits_and_finishes_campaign():
    text = PORTFOLIO_RECOVERY_WORKFLOW.read_text(encoding="utf-8")
    assert "source_run_id" in text
    for artifact in (
        "aurora-full-us-daily-pre2021",
        "stock-protocol-signal-merged",
        "stock-protocol-weights-merged",
        "stock-protocol-entries-merged",
        "stock-protocol-exits-merged",
    ):
        assert artifact in text
    assert "layer: portfolio" in text
    assert "previous_artifact: stock-protocol-exits-merged" in text
    assert "layer: costs" in text
    assert "previous_artifact: stock-protocol-portfolio-merged" in text
    assert "--task-count 360" in text
    assert text.count("max-parallel: 180") == 2
    assert "freeze-robustness" in text
    assert "needs: robustness_merge" in text
    assert "finalize_stock_protocol_scientific.py" in text
    assert "stock-protocol-scientific-full-universe-360jobs-results" in text
    assert 'DATA_END: "2020-12-31"' in text
    assert 'LOCKED_START: "2021-01-01"' in text
    assert "locked_opened=false" in text
    assert "validation_used_for_selection=false" in text
    assert "continue-on-error" not in text


def test_finalizer_workflow_resumes_at_holdout_from_frozen_robustness():
    wrapper = FINALIZE_WORKFLOW.read_text(encoding="utf-8")
    text = HOLDOUT_FINALIZE_WORKFLOW.read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/_stock-protocol-scientific-holdout-finalize.yml" in wrapper
    assert "workflow_call:" in text
    for artifact in (
        "stock-protocol-scientific-pack",
        "stock-protocol-signal-merged",
        "stock-protocol-weights-merged",
        "stock-protocol-entries-merged",
        "stock-protocol-exits-merged",
        "stock-protocol-portfolio-merged",
        "stock-protocol-costs-merged",
        "stock-protocol-scientific-postselection-inputs",
        "stock-protocol-scientific-robustness-merged",
        "stock-protocol-scientific-holdout",
    ):
        assert artifact in text
    assert "run_stock_protocol_scientific_postselection.py holdout" in text
    assert "needs: holdout" in text
    assert "finalize_stock_protocol_scientific.py" in text
    assert "stock-protocol-scientific-full-universe-360jobs-results" in text
    assert "pre2021_pack_audit.json" in text
    assert "full_dataset_audit.json" in text
    assert 'DATA_END: "2020-12-31"' in text
    assert 'LOCKED_START: "2021-01-01"' in text
    assert "locked_opened=false" in text
    assert "validation_used_for_selection=false" in text
    assert "AURORA_ALLOW_LOCAL_RUNS_EXPLICIT" not in text
    assert "run_stock_protocol_scientific_pipeline.py evaluate" not in text
    assert "run_stock_protocol_scientific_postselection.py evaluate-task" not in text
