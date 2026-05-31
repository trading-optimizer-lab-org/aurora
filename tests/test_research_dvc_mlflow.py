"""Tests for aurora.research.dvc_mlflow."""
from __future__ import annotations
import json
import pytest

from aurora.research.dvc_mlflow import (
    DVCMLflowIntegration,
    RunRecord,
)


def test_basic_run_lifecycle(tmp_path):
    tracker = DVCMLflowIntegration(experiment="exp1", tracking_dir=tmp_path)
    rec = tracker.start_run(params={"lr": 0.01})
    assert isinstance(rec, RunRecord)
    tracker.log_metric(rec.run_id, "sharpe", 1.5)
    tracker.log_metric(rec.run_id, "calmar", 0.8)
    tracker.log_artifact(rec.run_id, "model.pkl")
    final = tracker.end_run(rec.run_id)
    assert final.metrics["sharpe"] == 1.5
    assert final.metrics["calmar"] == 0.8
    assert "model.pkl" in final.artifacts
    assert final.ended_at >= final.started_at


def test_persistence_to_disk(tmp_path):
    tracker = DVCMLflowIntegration(experiment="ex2", tracking_dir=tmp_path)
    rec = tracker.start_run(params={"a": 1})
    tracker.log_metric(rec.run_id, "m", 0.5)
    tracker.end_run(rec.run_id)
    path = tmp_path / f"ex2_{rec.run_id}.json"
    assert path.exists()
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["metrics"]["m"] == 0.5


def test_unknown_run_raises(tmp_path):
    tracker = DVCMLflowIntegration(experiment="x", tracking_dir=tmp_path)
    with pytest.raises(KeyError):
        tracker.log_metric("nope", "k", 1.0)
    with pytest.raises(KeyError):
        tracker.log_artifact("nope", "p")
    with pytest.raises(KeyError):
        tracker.end_run("nope")


def test_empty_experiment_rejected():
    with pytest.raises(ValueError):
        DVCMLflowIntegration(experiment="")


def test_list_runs(tmp_path):
    tracker = DVCMLflowIntegration(experiment="x", tracking_dir=tmp_path)
    a = tracker.start_run()
    b = tracker.start_run()
    runs = tracker.list_runs()
    assert {a.run_id, b.run_id} == {r.run_id for r in runs}


def test_availability_flags_are_bool(tmp_path):
    tracker = DVCMLflowIntegration(experiment="x", tracking_dir=tmp_path)
    assert isinstance(tracker.mlflow_available, bool)
    assert isinstance(tracker.dvc_available, bool)
