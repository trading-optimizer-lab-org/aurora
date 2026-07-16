"""Static contract for the existing-data full-universe scientific campaign."""
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "stock-protocol-scientific-full-universe-360jobs.yml"
LAYER = ROOT / ".github" / "workflows" / "_stock-protocol-scientific-layer.yml"


def test_full_universe_workflow_is_valid_yaml():
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert document["name"] == "Stock Protocol Scientific Full Universe 360 Jobs"
    assert "prepare_data" in document["jobs"]
    assert "assemble" in document["jobs"]


def test_full_universe_workflow_reuses_exact_existing_artifact():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "29148013009" in text
    assert "gtbi-external-pack-data" in text
    assert "sha256:f2704de81fabc9ffaa90684b936555a737b70f9d5a3204dfa7a13c40bd3c3ca6" in text
    assert "0e226f53adeed4117cb95c50b831e640a7831dbc860323fe88c8dd50316b4e0e" in text.lower()
    assert "eec0c4d26038af392d089396dd1493a724550c46b9707ceb9a540a2d67b86c97" in text.lower()
    assert "build-universe" not in text
    assert "download-prices" not in text
    assert "yfinance" not in text.lower()


def test_full_universe_workflow_has_strict_pack_controls():
    text = WORKFLOW.read_text(encoding="utf-8")
    for expected in ("4828", "20364502", "20327106", "2020-12-31", "2021-01-01"):
        assert expected in text
    assert "aurora-full-us-daily-pre2021" in text
    assert "prepare_stock_protocol_full_dataset.py" in text
    assert "pack_symbols < 1000" in text or "--minimum-symbols 1000" in text
    assert "locked_opened=false" in text
    assert "validation_used_for_selection=false" in text


def test_full_universe_workflow_executes_every_layer_and_360_robustness_tasks():
    text = WORKFLOW.read_text(encoding="utf-8")
    for layer in ("signal", "weights", "entries", "exits", "portfolio", "costs"):
        assert f"layer: {layer}" in text
    assert "--task-count 360" in text
    assert text.count("max-parallel: 180") >= 2
    assert "freeze-robustness" in text
    assert "holdout" in text
    assert "finalize_stock_protocol_scientific.py" in text


def test_final_artifact_contains_dataset_and_scientific_evidence():
    text = WORKFLOW.read_text(encoding="utf-8")
    for name in (
        "full_dataset_inventory.csv",
        "full_dataset_audit.json",
        "two_symbol_root_cause.md",
        "pre2021_pack_audit.json",
        "pre2021_symbol_coverage.csv",
        "data_shard_manifest.json",
        "dataset_exclusions.csv",
        "implementation_matrix.csv",
        "signal_layer_results.csv",
        "entry_layer_results.csv",
        "exit_layer_results.csv",
        "portfolio_layer_results.csv",
        "cost_scenarios.csv",
        "walk_forward_results.csv",
        "robustness_results.csv",
        "holdout_2016_2020.csv",
        "pareto_frontier.csv",
        "final_recommendation.md",
    ):
        assert name in text


def test_reusable_layer_accepts_the_exact_pack_artifact_name():
    text = LAYER.read_text(encoding="utf-8")
    assert "pack_artifact_name" in text
    assert text.count("name: ${{ inputs.pack_artifact_name }}") == 3
