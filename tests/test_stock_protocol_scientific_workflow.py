"""Static contracts for the complete GitHub-only scientific campaign."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAYER_WORKFLOW = ROOT / ".github" / "workflows" / "_stock-protocol-scientific-layer.yml"
CAMPAIGN_WORKFLOW = ROOT / ".github" / "workflows" / "stock-protocol-scientific-rebuild-360jobs.yml"


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
