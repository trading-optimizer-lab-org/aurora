"""Dynamic no-empty-job plans and strict scientific layer merges."""

from __future__ import annotations

import json
import inspect
from pathlib import Path

import pytest

import scripts.run_stock_protocol_scientific_pipeline as pipeline_module

from aurora.research.stock_protocol.manifest import load_protocol_manifest
from scripts.run_stock_protocol_scientific_pipeline import (
    merge_layer_tasks,
    plan_layer,
)


MANIFEST = Path(__file__).resolve().parents[1] / "config" / "stock_protocol_36_tests.yaml"


def test_task_evaluation_uses_memory_bounded_pack_walk_forward():
    source = inspect.getsource(pipeline_module.evaluate_task)
    assert "evaluate_development_walk_forward_from_pack" in source
    assert "read_pack(" not in source


def test_signal_plan_contains_only_real_unique_tasks(tmp_path: Path):
    path = plan_layer(
        manifest_path=MANIFEST,
        layer="signal",
        output_path=tmp_path / "signal_specs.json",
        dataset_hash="dataset-hash",
        previous_snapshot_path=None,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["layer"] == "signal"
    assert payload["task_count"] == len(payload["specs"])
    assert payload["task_count"] > 0
    assert len({spec["candidate_id"] for spec in payload["specs"]}) == payload["task_count"]
    assert payload["matrix_a"]
    assert max(payload["matrix_a"]) < payload["task_count"]
    assert payload["matrix_b"] == [] or max(payload["matrix_b"]) < payload["task_count"]
    assert len(payload["matrix_a"]) <= 180
    assert len(payload["matrix_b"]) <= 180


def _task_row(candidate_id: str, cagr: float, drawdown: float) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "spec_json": json.dumps(
            {
                "signal_test_id": 1,
                "signal_variant": {"lookback": 252, "skip": 21},
                "selection": {"kind": "top_n", "value": 1},
                "entry": {"kind": "immediate_next_open", "max_wait_sessions": 0},
                "exit": {"kind": "none", "holding_sessions": 20},
                "portfolio": {"sizing": "equal"},
                "cost_bps": 10,
                "horizon_sessions": 20,
            },
            sort_keys=True,
        ),
        "status": "evaluated",
        "cagr": cagr,
        "sortino": 1.5 if cagr > 0.1 else 0.8,
        "calmar": 1.0 if cagr > 0.1 else 0.4,
        "return_per_capital_day": 0.001 if cagr > 0.1 else 0.0004,
        "max_drawdown": drawdown,
        "expected_shortfall_5": -0.03 if cagr > 0.1 else -0.06,
        "turnover": 2.0 if cagr > 0.1 else 7.0,
        "average_days_invested": 40.0 if cagr > 0.1 else 80.0,
        "total_costs": 100.0 if cagr > 0.1 else 400.0,
        "horizon_sessions": 20,
        "cost_bps": 10,
        "dataset_hash": "dataset-hash",
        "policy_hash": load_protocol_manifest(MANIFEST).policy_hash,
        "locked_opened": False,
        "data_end": "2020-12-31",
        "evaluation_start": "1995-01-01",
        "evaluation_end": "2015-12-31",
    }


def _write_plan(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "layer": "signal",
                "dataset_hash": "dataset-hash",
                "locked_opened": False,
                "task_count": 2,
                "specs": [
                    {"candidate_id": "good", "spec": json.loads(_task_row("good", 0.15, -0.15)["spec_json"])},
                    {"candidate_id": "bad", "spec": json.loads(_task_row("bad", 0.08, -0.30)["spec_json"])},
                ],
            }
        ),
        encoding="utf-8",
    )


def test_merge_requires_every_planned_task_and_freezes_real_pareto(tmp_path: Path):
    plan = tmp_path / "plan.json"
    _write_plan(plan)
    tasks = tmp_path / "tasks"
    for index, row in enumerate((_task_row("good", 0.15, -0.15), _task_row("bad", 0.08, -0.30))):
        target = tasks / f"task={index:04d}"
        target.mkdir(parents=True)
        (target / "result.json").write_text(json.dumps(row), encoding="utf-8")

    result = merge_layer_tasks(
        manifest_path=MANIFEST,
        layer="signal",
        plan_path=plan,
        tasks_root=tasks,
        output_root=tmp_path / "merged",
    )

    snapshot = json.loads(result["snapshot"].read_text(encoding="utf-8"))
    assert [item["candidate_id"] for item in snapshot["decisions"]] == ["good"]
    assert result["results"].is_file()
    assert result["audit"].is_file()
    audit = json.loads(result["audit"].read_text(encoding="utf-8"))
    assert audit["planned_tasks"] == audit["found_tasks"] == 2
    assert audit["partial"] is False


def test_merge_fails_if_any_planned_task_is_missing(tmp_path: Path):
    plan = tmp_path / "plan.json"
    _write_plan(plan)
    target = tmp_path / "tasks" / "task=0000"
    target.mkdir(parents=True)
    (target / "result.json").write_text(
        json.dumps(_task_row("good", 0.15, -0.15)), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="missing task"):
        merge_layer_tasks(
            manifest_path=MANIFEST,
            layer="signal",
            plan_path=plan,
            tasks_root=tmp_path / "tasks",
            output_root=tmp_path / "merged",
        )
