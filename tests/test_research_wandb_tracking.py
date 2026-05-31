"""Tests for aurora.research.wandb_tracking."""
from __future__ import annotations
import pytest

from aurora.research.wandb_tracking import WandBTracker, WandBRun


def test_basic_run_lifecycle():
    t = WandBTracker(project="qf")
    run = t.init(config={"lr": 0.01}, name="r1")
    assert isinstance(run, WandBRun)
    t.log("r1", {"loss": 0.5}, step=1)
    t.log("r1", {"loss": 0.3, "acc": 0.9}, step=2)
    final = t.finish("r1")
    assert final.finished is True
    assert final.summary["loss"] == 0.3
    assert final.summary["acc"] == 0.9
    assert len(final.history) == 2


def test_duplicate_name_rejected():
    t = WandBTracker(project="qf")
    t.init(name="dup")
    with pytest.raises(ValueError):
        t.init(name="dup")


def test_unknown_run_id_raises():
    t = WandBTracker(project="qf")
    with pytest.raises(KeyError):
        t.log("x", {"k": 1.0})
    with pytest.raises(KeyError):
        t.finish("x")


def test_log_empty_metrics_rejected():
    t = WandBTracker(project="qf")
    t.init(name="r")
    with pytest.raises(ValueError):
        t.log("r", {})


def test_sweep_cartesian():
    t = WandBTracker(project="qf")
    grid = t.sweep("g", parameters={"lr": [0.01, 0.1], "bs": [32, 64]})
    assert len(grid) == 4
    seen = {(g["lr"], g["bs"]) for g in grid}
    assert seen == {(0.01, 32), (0.01, 64), (0.1, 32), (0.1, 64)}


def test_sweep_empty_values_rejected():
    t = WandBTracker(project="qf")
    with pytest.raises(ValueError):
        t.sweep("g", parameters={"lr": []})


def test_empty_project_rejected():
    with pytest.raises(ValueError):
        WandBTracker(project="")


def test_list_runs():
    t = WandBTracker(project="qf")
    t.init(name="a"); t.init(name="b")
    names = {r.run_id for r in t.list_runs()}
    assert names == {"a", "b"}


def test_wandb_availability_flag():
    t = WandBTracker(project="qf")
    assert isinstance(t.wandb_available, bool)
