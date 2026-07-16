from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from aurora.research.stock_protocol.postselection import (
    build_robustness_plan,
    execute_robustness_task,
    merge_robustness_tasks,
)


def _returns() -> pd.DataFrame:
    dates = pd.bdate_range("1995-01-03", periods=3_024)
    phase = np.arange(len(dates), dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "stock_alpha": 0.0005 + np.sin(phase / 11.0) * 0.004,
            "stock_beta": 0.0003 + np.cos(phase / 17.0) * 0.005,
        }
    )


def _trades() -> pd.DataFrame:
    rows = []
    symbols = ("AAA", "BBB", "CCC", "DDD")
    for candidate_index, candidate_id in enumerate(("stock_alpha", "stock_beta")):
        for index in range(80):
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "symbol": symbols[index % len(symbols)],
                    "entry_date": pd.Timestamp("1995-01-03")
                    + pd.offsets.BDay(index * 5),
                    "net_return": 0.01 + candidate_index * 0.001 + (index % 7) * 0.001,
                }
            )
    return pd.DataFrame(rows)


def test_robustness_plan_contains_360_unique_real_tasks():
    plan = build_robustness_plan(_returns(), _trades(), task_count=360)

    assert plan["task_count"] == 360
    assert len(plan["matrix_a"]) == 180
    assert len(plan["matrix_b"]) == 180
    assert len({task["task_id"] for task in plan["tasks"]}) == 360
    assert {
        "circular_block_bootstrap",
        "deflated_sharpe",
        "cscv_pbo",
        "leave_one_decade_out",
        "leave_one_symbol_out",
    } <= {task["method"] for task in plan["tasks"]}
    assert all(task["input_hash"] == plan["input_hash"] for task in plan["tasks"])
    assert plan["locked_opened"] is False
    assert plan["data_end"] == "2015-12-31"


def test_robustness_plan_rejects_locked_dates():
    returns = _returns()
    returns.loc[len(returns)] = [pd.Timestamp("2021-01-04"), 0.01, 0.02]

    with pytest.raises(ValueError, match="locked"):
        build_robustness_plan(returns, _trades(), task_count=360)


def test_bootstrap_task_records_real_samples(tmp_path):
    returns = _returns()
    trades = _trades()
    plan = build_robustness_plan(returns, trades, task_count=360)
    task_index = next(
        index
        for index, task in enumerate(plan["tasks"])
        if task["method"] == "circular_block_bootstrap"
    )
    plan_path = tmp_path / "plan.json"
    returns_path = tmp_path / "returns.csv"
    trades_path = tmp_path / "trades.csv"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    returns.to_csv(returns_path, index=False)
    trades.to_csv(trades_path, index=False)

    result_path = execute_robustness_task(
        plan_path=plan_path,
        returns_path=returns_path,
        trades_path=trades_path,
        task_index=task_index,
        output_root=tmp_path / "task-output",
    )

    result = json.loads(result_path.read_text(encoding="utf-8"))
    samples = pd.read_csv(result_path.parent / "samples.csv")
    assert result["method"] == "circular_block_bootstrap"
    assert result["n_observations"] == len(returns)
    assert result["sample_count"] == 100
    assert result["seed"] >= 0
    assert len(samples) == 100
    assert samples["sample_hash"].nunique() > 1
    assert result["input_hash"] == plan["input_hash"]
    assert result["locked_opened"] is False


def test_robustness_merge_requires_all_tasks_and_applies_fdr(tmp_path):
    returns = _returns()
    trades = _trades()
    plan = build_robustness_plan(returns, trades, task_count=12)
    plan_path = tmp_path / "plan.json"
    returns_path = tmp_path / "returns.csv"
    trades_path = tmp_path / "trades.csv"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    returns.to_csv(returns_path, index=False)
    trades.to_csv(trades_path, index=False)
    task_root = tmp_path / "tasks"
    for index in range(12):
        execute_robustness_task(
            plan_path=plan_path,
            returns_path=returns_path,
            trades_path=trades_path,
            task_index=index,
            output_root=task_root,
        )

    outputs = merge_robustness_tasks(
        plan_path=plan_path,
        tasks_root=task_root,
        output_root=tmp_path / "merged",
    )

    tests = pd.read_csv(outputs["statistical_tests"])
    summary = json.loads(outputs["summary"].read_text(encoding="utf-8"))
    assert len(tests) == 12
    assert "fdr_pvalue" in tests
    assert tests.loc[tests["pvalue"].notna(), "fdr_pvalue"].between(0, 1).all()
    assert summary["tasks_expected"] == 12
    assert summary["tasks_found"] == 12
    assert summary["partial"] is False
    assert summary["locked_opened"] is False

    next((task_root / "task=0000").glob("result.json")).unlink()
    with pytest.raises(ValueError, match="missing robustness task"):
        merge_robustness_tasks(
            plan_path=plan_path,
            tasks_root=task_root,
            output_root=tmp_path / "broken",
        )
