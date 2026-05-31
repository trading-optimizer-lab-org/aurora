"""Tests for the experiment tracker (aurora.registry.experiments)."""
from __future__ import annotations

import json
import os

import pandas as pd
import pytest

from aurora.registry.experiments import (
    ExperimentTracker,
    ExperimentMeta,
    GenerationLog,
    ExperimentResult,
)


# ---------- helpers ----------

def _make_tracker(tmp_path) -> ExperimentTracker:
    return ExperimentTracker(root=str(tmp_path / "experiments"))


def _start_basic(tracker: ExperimentTracker, name: str = "exp1",
                 optimizer: str = "ga", strategy_class: str = "SMAStrategy",
                 asset: str = "SPY", seed: int = 42) -> str:
    return tracker.start_experiment(
        name=name,
        optimizer=optimizer,
        strategy_class=strategy_class,
        asset=asset,
        period_start="2015-01-01",
        period_end="2020-12-31",
        config={"population": 50, "generations": 10},
        seed=seed,
    )


# ---------- tests ----------

def test_start_experiment_creates_dir(tmp_path):
    tracker = _make_tracker(tmp_path)
    eid = _start_basic(tracker)

    # ID format: <utc_timestamp>_<8-hex-uuid>; total length 21+1+8 = 30 (with %f)
    assert isinstance(eid, str)
    assert "_" in eid
    ts_part, hex_part = eid.split("_", 1)
    assert len(hex_part) == 8
    assert len(ts_part) == 21  # YYYYMMDDTHHMMSSffffff -> 21 chars
    exp_dir = os.path.join(tracker.root, eid)
    assert os.path.isdir(exp_dir)
    assert os.path.isfile(os.path.join(exp_dir, "meta.json"))
    # generations.jsonl is created lazily on the first log_generation call;
    # start_experiment no longer touches an empty file there.

    # meta has the right shape
    with open(os.path.join(exp_dir, "meta.json"), "r", encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["experiment_id"] == eid
    assert meta["status"] == "running"
    assert meta["optimizer"] == "ga"
    assert meta["finished_at"] is None
    assert meta["seed"] == 42
    assert meta["config"] == {"population": 50, "generations": 10}


def test_log_generation_appends(tmp_path):
    tracker = _make_tracker(tmp_path)
    eid = _start_basic(tracker)

    tracker.log_generation(eid, gen=0, best_fit=(1.5, 0.8, 0.3, 0.1),
                           median_fit=(1.0, 0.5, 0.2, 0.2),
                           n_evaluated=50, pareto_size=10)
    tracker.log_generation(eid, gen=1, best_fit=(1.7, 0.9, 0.35, 0.09),
                           median_fit=(1.1, 0.55, 0.25, 0.18),
                           n_evaluated=50, pareto_size=12)

    gen_path = os.path.join(tracker.root, eid, "generations.jsonl")
    with open(gen_path, "r", encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    assert len(lines) == 2
    g0 = json.loads(lines[0])
    g1 = json.loads(lines[1])
    assert g0["generation"] == 0
    assert g0["pareto_size"] == 10
    assert g1["generation"] == 1
    assert g1["pareto_size"] == 12

    # logging into a non-existent experiment must fail
    with pytest.raises(FileNotFoundError):
        tracker.log_generation("does_not_exist", gen=0, best_fit=(0,),
                               median_fit=(0,), n_evaluated=0, pareto_size=0)


def test_finish_experiment_updates_status(tmp_path):
    tracker = _make_tracker(tmp_path)
    eid = _start_basic(tracker)

    pareto = [({"fast": 10, "slow": 50}, (1.5, 0.8, 0.3, 0.1))]
    tracker.finish_experiment(
        eid, pareto_front=pareto,
        best_params={"fast": 10, "slow": 50},
        best_score=1.5, notes="winner", status="completed",
    )

    meta_path = os.path.join(tracker.root, eid, "meta.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["status"] == "completed"
    assert meta["finished_at"] is not None
    assert meta["best_params"] == {"fast": 10, "slow": 50}
    assert meta["best_score"] == 1.5

    pareto_path = os.path.join(tracker.root, eid, "pareto.json")
    assert os.path.isfile(pareto_path)
    with open(pareto_path, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved[0]["params"] == {"fast": 10, "slow": 50}
    assert list(saved[0]["fitness"]) == [1.5, 0.8, 0.3, 0.1]

    notes_path = os.path.join(tracker.root, eid, "notes.md")
    assert os.path.isfile(notes_path)


def test_load_experiment_returns_complete(tmp_path):
    tracker = _make_tracker(tmp_path)
    eid = _start_basic(tracker)

    tracker.log_generation(eid, gen=0, best_fit=(1.5, 0.8, 0.3, 0.1),
                           median_fit=(1.0, 0.5, 0.2, 0.2),
                           n_evaluated=50, pareto_size=10)
    tracker.log_generation(eid, gen=1, best_fit=(1.7, 0.9, 0.35, 0.09),
                           median_fit=(1.1, 0.55, 0.25, 0.18),
                           n_evaluated=50, pareto_size=12)

    pareto = [
        ({"fast": 10, "slow": 50}, (1.7, 0.9, 0.35, 0.09)),
        ({"fast": 12, "slow": 60}, (1.6, 0.85, 0.32, 0.10)),
    ]
    tracker.finish_experiment(
        eid, pareto_front=pareto,
        best_params={"fast": 10, "slow": 50},
        best_score=1.7, notes="all good",
    )

    result = tracker.load_experiment(eid)

    assert isinstance(result, ExperimentResult)
    assert isinstance(result.meta, ExperimentMeta)
    assert result.meta.experiment_id == eid
    assert result.meta.status == "completed"

    assert len(result.generations) == 2
    assert isinstance(result.generations[0], GenerationLog)
    assert result.generations[0].generation == 0
    assert result.generations[1].generation == 1
    assert result.generations[1].best_fitness == (1.7, 0.9, 0.35, 0.09)

    assert len(result.pareto_front) == 2
    p0_params, p0_fit = result.pareto_front[0]
    assert p0_params == {"fast": 10, "slow": 50}
    assert p0_fit == (1.7, 0.9, 0.35, 0.09)

    assert result.best_params == {"fast": 10, "slow": 50}
    assert result.best_score == 1.7
    assert result.notes == "all good"

    with pytest.raises(FileNotFoundError):
        tracker.load_experiment("does_not_exist")


def test_list_experiments_filter(tmp_path):
    tracker = _make_tracker(tmp_path)
    e_ga = tracker.start_experiment(
        name="ga_run", optimizer="ga", strategy_class="SMA",
        asset="SPY", period_start="2015-01-01", period_end="2020-12-31",
        config={}, seed=1,
    )
    e_bayes = tracker.start_experiment(
        name="bo_run", optimizer="bayes", strategy_class="SMA",
        asset="SPY", period_start="2015-01-01", period_end="2020-12-31",
        config={}, seed=2,
    )
    e_ga_other = tracker.start_experiment(
        name="ga_run_other_strat", optimizer="ga", strategy_class="Bollinger",
        asset="SPY", period_start="2015-01-01", period_end="2020-12-31",
        config={}, seed=3,
    )
    tracker.finish_experiment(e_ga, status="completed",
                              best_params={"x": 1}, best_score=1.0)
    # leave e_bayes and e_ga_other in 'running' state

    all_ = tracker.list_experiments()
    assert len(all_) == 3

    only_ga = tracker.list_experiments(optimizer="ga")
    assert {m.experiment_id for m in only_ga} == {e_ga, e_ga_other}

    only_sma = tracker.list_experiments(strategy_class="SMA")
    assert {m.experiment_id for m in only_sma} == {e_ga, e_bayes}

    only_running = tracker.list_experiments(status="running")
    assert {m.experiment_id for m in only_running} == {e_bayes, e_ga_other}

    only_completed = tracker.list_experiments(status="completed")
    assert [m.experiment_id for m in only_completed] == [e_ga]

    combo = tracker.list_experiments(optimizer="ga", strategy_class="SMA")
    assert [m.experiment_id for m in combo] == [e_ga]


def test_compare_experiments_dataframe(tmp_path):
    tracker = _make_tracker(tmp_path)
    e1 = _start_basic(tracker, name="e1", seed=1)
    e2 = _start_basic(tracker, name="e2", seed=2)

    tracker.log_generation(e1, gen=0, best_fit=(1.5,), median_fit=(1.0,),
                           n_evaluated=10, pareto_size=3)
    tracker.finish_experiment(e1, pareto_front=[({"a": 1}, (1.5,))],
                              best_params={"a": 1}, best_score=1.5)
    tracker.finish_experiment(e2, pareto_front=[({"a": 2}, (2.0,))],
                              best_params={"a": 2}, best_score=2.0)

    df = tracker.compare_experiments([e1, e2])
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2

    expected_cols = {
        "experiment_id", "name", "optimizer", "strategy_class", "asset",
        "status", "seed", "started_at", "finished_at", "runtime_s",
        "best_score", "best_fitness_last_gen", "pareto_size", "n_generations",
        "config",
    }
    assert expected_cols.issubset(set(df.columns))

    by_id = {row["experiment_id"]: row for _, row in df.iterrows()}
    assert by_id[e1]["best_score"] == 1.5
    assert by_id[e2]["best_score"] == 2.0
    assert by_id[e1]["n_generations"] == 1
    assert by_id[e2]["n_generations"] == 0
    # runtime_s is a non-negative number (might be 0 on fast machines)
    assert by_id[e1]["runtime_s"] is not None
    assert by_id[e1]["runtime_s"] >= 0


def test_best_experiment_selects_top(tmp_path):
    tracker = _make_tracker(tmp_path)

    e_low = _start_basic(tracker, name="low")
    e_mid = _start_basic(tracker, name="mid")
    e_high = _start_basic(tracker, name="high")

    tracker.finish_experiment(e_low, best_params={"a": 1}, best_score=0.5)
    tracker.finish_experiment(e_mid, best_params={"a": 2}, best_score=1.5)
    tracker.finish_experiment(e_high, best_params={"a": 3}, best_score=2.5)

    # 'running' experiment should be ignored
    e_running = _start_basic(tracker, name="running")
    tracker.log_generation(e_running, gen=0, best_fit=(99.0,),
                           median_fit=(0.0,), n_evaluated=1, pareto_size=1)

    best = tracker.best_experiment(metric="best_score")
    assert best is not None
    assert best.meta.experiment_id == e_high
    assert best.best_score == 2.5

    # no completed bayes runs → None
    assert tracker.best_experiment(optimizer="bayes") is None

    # filter by strategy_class still works
    best_filtered = tracker.best_experiment(
        optimizer="ga", strategy_class="SMAStrategy", metric="best_score",
    )
    assert best_filtered is not None
    assert best_filtered.meta.experiment_id == e_high

    with pytest.raises(ValueError):
        tracker.best_experiment(metric="not_a_metric")


def test_status_transitions(tmp_path):
    tracker = _make_tracker(tmp_path)
    eid = _start_basic(tracker)

    # initially running
    meta_path = os.path.join(tracker.root, eid, "meta.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["status"] == "running"
    assert meta["finished_at"] is None

    tracker.finish_experiment(eid, best_params={"a": 1}, best_score=1.0)

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["status"] == "completed"
    assert meta["finished_at"] is not None

    # finishing with status='failed' is also supported
    eid_fail = _start_basic(tracker, name="bad_run")
    tracker.finish_experiment(eid_fail, status="failed")
    with open(os.path.join(tracker.root, eid_fail, "meta.json"), "r", encoding="utf-8") as f:
        meta_f = json.load(f)
    assert meta_f["status"] == "failed"


def test_new_experiment_id_format():
    """Experiment IDs combine a high-resolution UTC timestamp and an 8-hex
    uuid suffix. The timestamp prefix gives wall-clock-ordered IDs and
    extra entropy beyond uuid alone, so two concurrent calls inside the
    same microsecond on different machines still differ.
    """
    from aurora.registry.experiments import _new_experiment_id

    n = 5_000
    ids = {_new_experiment_id() for _ in range(n)}
    assert len(ids) == n
    for x in ids:
        ts, hex_part = x.split("_", 1)
        assert len(ts) == 21  # YYYYMMDDTHHMMSS + 6 microseconds
        assert len(hex_part) == 8
        int(hex_part, 16)


def test_start_experiment_no_overwrite_on_collision(tmp_path, monkeypatch):
    """If two parallel calls land on the same experiment_id, the second
    must allocate a fresh id rather than overwriting the first's
    meta.json. ``os.makedirs(exist_ok=False)`` makes the directory
    create itself the atomic check that closes the prior TOCTOU window.
    """
    from aurora.registry import experiments as exp_mod

    # First two calls return the same id; subsequent calls fall through
    # to genuine random ids. The retry loop must therefore allocate a
    # fresh id on the second call.
    fake_ids = ["fixed_id_1234567890ab"] * 2 + [f"a{n:031x}" for n in range(100)]
    it = iter(fake_ids)

    def _fake() -> str:
        return next(it)

    monkeypatch.setattr(exp_mod, "_new_experiment_id", _fake)
    tracker = _make_tracker(tmp_path)

    eid_a = _start_basic(tracker, name="A")
    eid_b = _start_basic(tracker, name="B")
    assert eid_a != eid_b
    # both meta.json files exist with the right name
    meta_a = json.load(open(os.path.join(tracker.root, eid_a, "meta.json"), "r", encoding="utf-8"))
    meta_b = json.load(open(os.path.join(tracker.root, eid_b, "meta.json"), "r", encoding="utf-8"))
    assert meta_a["name"] == "A"
    assert meta_b["name"] == "B"
