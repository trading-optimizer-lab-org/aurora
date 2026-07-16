"""Scientific contracts for immutable, chained protocol layers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aurora.research.stock_protocol import layers


def _decision() -> dict[str, object]:
    return {
        "candidate_id": "momentum_top_10",
        "parameters": {"formation": "12-1", "top_percent": 10},
        "validation_metrics": {"sharpe": 0.8, "max_drawdown": -0.2},
        "decision": "advance",
    }


def test_snapshot_records_complete_reproducibility_contract(tmp_path: Path):
    source = tmp_path / "signal_results.csv"
    source.write_text("candidate_id,score\na,1.0\n", encoding="utf-8")

    output = layers.freeze_snapshot(
        layer="signal",
        input_artifact=source,
        output_path=tmp_path / "signal_snapshot.json",
        policy_hash="policy-123",
        dataset_hash="dataset-456",
        date_start="1995-01-01",
        date_end="2015-12-31",
        universe="current_universe_backfill",
        decisions=[_decision()],
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["layer"] == "signal"
    assert payload["input_artifact_sha256"] == layers.sha256_file(source)
    assert payload["policy_hash"] == "policy-123"
    assert payload["dataset_hash"] == "dataset-456"
    assert payload["date_start"] == "1995-01-01"
    assert payload["date_end"] == "2015-12-31"
    assert payload["universe"] == "current_universe_backfill"
    assert payload["survivorship_limited"] is True
    assert payload["locked_opened"] is False
    assert payload["decisions"] == [_decision()]
    assert payload["snapshot_sha256"] == layers.snapshot_payload_hash(payload)


def test_snapshot_loader_rejects_tampering(tmp_path: Path):
    source = tmp_path / "signal_results.csv"
    source.write_text("candidate_id,score\na,1.0\n", encoding="utf-8")
    snapshot = layers.freeze_snapshot(
        layer="signal",
        input_artifact=source,
        output_path=tmp_path / "signal_snapshot.json",
        policy_hash="policy",
        dataset_hash="dataset",
        date_start="1995-01-01",
        date_end="2015-12-31",
        universe="current_universe_backfill",
        decisions=[_decision()],
    )
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    payload["decisions"][0]["parameters"]["top_percent"] = 99
    snapshot.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="snapshot hash"):
        layers.load_snapshot(
            snapshot,
            expected_layer="signal",
            expected_policy_hash="policy",
            expected_dataset_hash="dataset",
        )


def test_snapshot_loader_rejects_wrong_policy_dataset_or_layer(tmp_path: Path):
    source = tmp_path / "signal_results.csv"
    source.write_text("candidate_id,score\na,1.0\n", encoding="utf-8")
    snapshot = layers.freeze_snapshot(
        layer="signal",
        input_artifact=source,
        output_path=tmp_path / "signal_snapshot.json",
        policy_hash="policy",
        dataset_hash="dataset",
        date_start="1995-01-01",
        date_end="2015-12-31",
        universe="current_universe_backfill",
        decisions=[_decision()],
    )

    with pytest.raises(ValueError, match="layer"):
        layers.load_snapshot(snapshot, "weights", "policy", "dataset")
    with pytest.raises(ValueError, match="policy"):
        layers.load_snapshot(snapshot, "signal", "other", "dataset")
    with pytest.raises(ValueError, match="dataset"):
        layers.load_snapshot(snapshot, "signal", "policy", "other")


@pytest.mark.parametrize(
    ("phase", "expected_previous"),
    [
        ("weights", "signal"),
        ("entries", "weights"),
        ("exits", "entries"),
        ("portfolio", "exits"),
        ("costs", "portfolio"),
        ("walk_forward", "costs"),
        ("robustness", "walk_forward"),
        ("final", "robustness"),
    ],
)
def test_every_downstream_phase_has_exact_predecessor(phase: str, expected_previous: str):
    assert layers.required_predecessor(phase) == expected_previous


def test_signal_is_only_phase_without_predecessor():
    assert layers.required_predecessor("signal") is None
    with pytest.raises(ValueError, match="unknown phase"):
        layers.required_predecessor("made_up")


def test_snapshot_cannot_include_locked_or_post_boundary_dates(tmp_path: Path):
    source = tmp_path / "results.csv"
    source.write_text("candidate_id\na\n", encoding="utf-8")
    with pytest.raises(ValueError, match="locked boundary"):
        layers.freeze_snapshot(
            layer="signal",
            input_artifact=source,
            output_path=tmp_path / "bad.json",
            policy_hash="policy",
            dataset_hash="dataset",
            date_start="1995-01-01",
            date_end="2021-01-01",
            universe="current_universe_backfill",
            decisions=[_decision()],
        )

