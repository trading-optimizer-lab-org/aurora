from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from aurora.research.stock_protocol.postselection import (
    build_robustness_plan,
    execute_robustness_task,
    merge_robustness_tasks,
)
from scripts.run_stock_protocol_scientific_postselection import (
    _filter_statistically_eligible_candidates,
    freeze_robustness_snapshot,
    holdout_result_row,
    prepare_postselection_inputs,
)

from aurora.research.stock_protocol.layers import freeze_snapshot, load_snapshot
from aurora.research.stock_protocol.manifest import load_protocol_manifest


MANIFEST = Path(__file__).resolve().parents[1] / "config" / "stock_protocol_36_tests.yaml"


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


def _staggered_returns() -> pd.DataFrame:
    dates = pd.bdate_range("1995-01-03", periods=600)
    phase = np.arange(len(dates), dtype=float)
    frame = pd.DataFrame({"date": dates, "stock_alpha": np.nan, "stock_beta": np.nan})
    frame.loc[:399, "stock_alpha"] = 0.0005 + np.sin(phase[:400] / 11.0) * 0.004
    frame.loc[200:, "stock_beta"] = 0.0003 + np.cos(phase[200:] / 17.0) * 0.005
    return frame


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


def test_robustness_accepts_staggered_candidate_histories_without_zero_fill(tmp_path):
    returns = _staggered_returns()
    trades = _trades()
    plan = build_robustness_plan(returns, trades, task_count=360)

    assert plan["observation_counts"] == {"stock_alpha": 400, "stock_beta": 400}
    assert plan["cscv_complete_observations"] == 200
    assert plan["cscv_candidate_ids"] == ["stock_alpha", "stock_beta"]

    task_index = next(
        index
        for index, task in enumerate(plan["tasks"])
        if task["method"] == "circular_block_bootstrap"
        and task["parameters"]["candidate_id"] == "stock_beta"
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
    assert result["n_observations"] == 400


def test_prepare_excludes_short_histories_without_zero_fill():
    dates = pd.bdate_range("2014-01-01", periods=300)
    returns = pd.DataFrame(
        {
            "date": dates,
            "stock_alpha": 0.001,
            "stock_beta": 0.002,
            "stock_short": np.nan,
        }
    )
    returns.loc[:211, "stock_short"] = 0.003
    trades = pd.DataFrame(
        {
            "candidate_id": ["stock_alpha", "stock_beta", "stock_short"],
            "symbol": ["AAA", "BBB", "CCC"],
            "entry_date": [dates[10], dates[20], dates[30]],
            "net_return": [0.05, 0.04, 0.03],
        }
    )
    decisions = [
        {"candidate_id": candidate, "parameters": {}}
        for candidate in ("stock_alpha", "stock_beta", "stock_short")
    ]


def test_prepare_uses_full_frozen_development_history_for_robustness(
    tmp_path, monkeypatch
):
    import scripts.run_stock_protocol_scientific_postselection as runner

    manifest = SimpleNamespace(
        locked_opened=False,
        data_end="2020-12-31",
        research_start="1995-01-01",
        policy_hash="policy-hash",
    )
    audit = SimpleNamespace(
        locked_opened=False,
        locked_rows=0,
        dataset_hash="dataset-hash",
        to_json=lambda: {"dataset_hash": "dataset-hash"},
    )
    panel = SimpleNamespace(audit=audit)
    decisions = [
        {"candidate_id": candidate, "parameters": {"candidate": candidate}}
        for candidate in ("stock_alpha", "stock_beta")
    ]

    def result(candidate, periods):
        dates = pd.bdate_range("2014-01-01", periods=periods)
        equity = pd.DataFrame(
            {"date": dates, "equity": 100_000.0 * (1.0002 ** np.arange(periods))}
        )
        trades = pd.DataFrame(
            {
                "symbol": ["AAA"],
                "entry_date": [dates[10]],
                "net_return": [0.02],
            }
        )
        yearly = pd.DataFrame(
            {"candidate_id": [candidate], "year": [2014], "return": [0.05]}
        )
        return SimpleNamespace(
            status="evaluated",
            equity_curve=equity,
            trade_ledger=trades,
            position_ledger=pd.DataFrame(),
            yearly=yearly,
            metrics={"sharpe": 0.5},
            result_row=lambda: {"candidate_id": candidate, "status": "evaluated"},
        )

    monkeypatch.setattr(runner, "load_protocol_manifest", lambda _: manifest)
    monkeypatch.setattr(runner, "read_pack", lambda *_: panel)
    monkeypatch.setattr(runner, "load_snapshot", lambda *_args, **_kwargs: {"decisions": decisions})
    monkeypatch.setattr(
        runner,
        "evaluate_development_walk_forward",
        lambda _panel, spec, **_kwargs: SimpleNamespace(
            result=result(spec["candidate"], 212), folds=[object()]
        ),
    )
    monkeypatch.setattr(
        runner,
        "evaluate_spec",
        lambda _panel, spec, **_kwargs: result(spec["candidate"], 500),
    )
    captured = {}

    def fake_plan(returns, trades, *, task_count):
        captured["returns"] = returns.copy()
        captured["trades"] = trades.copy()
        return {
            "matrix_a": list(range(task_count // 2)),
            "matrix_b": list(range(task_count // 2, task_count)),
        }

    monkeypatch.setattr(runner, "build_robustness_plan", fake_plan)

    def fake_freeze(*, output_path, **_kwargs):
        output_path.write_text("{}", encoding="utf-8")
        return output_path

    monkeypatch.setattr(runner, "freeze_snapshot", fake_freeze)
    outputs = prepare_postselection_inputs(
        manifest_path=tmp_path / "manifest.yaml",
        pack_root=tmp_path / "pack",
        costs_snapshot_path=tmp_path / "costs.json",
        output_root=tmp_path / "out",
        task_count=12,
    )

    assert captured["returns"]["stock_alpha"].notna().sum() == 500
    assert captured["returns"]["stock_beta"].notna().sum() == 500
    walk_forward = pd.read_csv(outputs["walk_forward_results"])
    assert walk_forward["walk_forward_folds"].eq(1).all()
    data_audit = json.loads(outputs["data_audit"].read_text(encoding="utf-8"))
    assert data_audit["robustness_input_mode"] == "full_development_frozen_spec"
    assert data_audit["full_development_used_for_selection"] is False

    clean_returns, clean_trades, clean_decisions, excluded, counts = (
        _filter_statistically_eligible_candidates(returns, trades, decisions)
    )

    assert list(clean_returns) == ["date", "stock_alpha", "stock_beta"]
    assert set(clean_trades["candidate_id"]) == {"stock_alpha", "stock_beta"}
    assert {item["candidate_id"] for item in clean_decisions} == {
        "stock_alpha",
        "stock_beta",
    }
    assert counts["stock_short"] == 212
    assert excluded.to_dict("records") == [
        {
            "candidate_id": "stock_short",
            "development_observations": 212,
            "minimum_required_observations": 252,
            "closed_trades": 1,
            "reason": "insufficient_development_observations",
            "locked_opened": False,
        }
    ]


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


def test_robustness_snapshot_is_frozen_before_holdout(tmp_path):
    manifest = load_protocol_manifest(MANIFEST)
    input_artifact = tmp_path / "cost_results.csv"
    pd.DataFrame({"candidate_id": ["stock_alpha", "stock_beta"]}).to_csv(
        input_artifact, index=False
    )
    costs_snapshot = freeze_snapshot(
        layer="costs",
        input_artifact=input_artifact,
        output_path=tmp_path / "costs_snapshot.json",
        policy_hash=manifest.policy_hash,
        dataset_hash="dataset-hash",
        date_start="1995-01-01",
        date_end="2015-12-31",
        universe="current_universe_backfill",
        decisions=[
            {
                "candidate_id": candidate_id,
                "parameters": {
                    "signal_test_id": 1,
                    "signal_variant": {"lookback": 252, "skip": 21},
                    "selection": {"kind": "top_n", "value": 1},
                    "entry": {"kind": "immediate_next_open", "max_wait_sessions": 0},
                    "exit": {"kind": "none", "holding_sessions": 63},
                    "portfolio": {"sizing": "equal"},
                    "cost_bps": 10,
                    "horizon_sessions": 63,
                },
                "validation_metrics": {"cagr": 0.1},
            }
            for candidate_id in ("stock_alpha", "stock_beta")
        ],
    )
    walk_forward_artifact = tmp_path / "walk_forward_results.csv"
    pd.DataFrame({"candidate_id": ["stock_alpha", "stock_beta"]}).to_csv(
        walk_forward_artifact, index=False
    )
    walk_forward_snapshot = freeze_snapshot(
        layer="walk_forward",
        input_artifact=walk_forward_artifact,
        output_path=tmp_path / "walk_forward_snapshot.json",
        policy_hash=manifest.policy_hash,
        dataset_hash="dataset-hash",
        date_start="1995-01-01",
        date_end="2015-12-31",
        universe="current_universe_backfill",
        decisions=load_snapshot(
            costs_snapshot,
            expected_layer="costs",
            expected_policy_hash=manifest.policy_hash,
            expected_dataset_hash="dataset-hash",
        )["decisions"],
    )
    robustness_path = tmp_path / "robustness_results.csv"
    pd.DataFrame(
        {
            "candidate_id": ["stock_alpha", "stock_beta"],
            "robust_pass": [True, False],
            "bootstrap_sharpe_p05": [0.2, -0.1],
            "deflated_sharpe_probability": [0.98, 0.70],
            "cscv_pbo_max": [0.3, 0.3],
        }
    ).to_csv(robustness_path, index=False)

    frozen_path = freeze_robustness_snapshot(
        manifest_path=MANIFEST,
        walk_forward_snapshot_path=walk_forward_snapshot,
        robustness_results_path=robustness_path,
        output_path=tmp_path / "robustness_snapshot.json",
    )

    frozen = load_snapshot(
        frozen_path,
        expected_layer="robustness",
        expected_policy_hash=manifest.policy_hash,
        expected_dataset_hash="dataset-hash",
    )
    assert {item["candidate_id"] for item in frozen["decisions"]} == {
        "stock_alpha",
        "stock_beta",
    }
    assert frozen["date_end"] == "2015-12-31"
    assert frozen["locked_opened"] is False
    assert [
        item["validation_metrics"]["robust_pass"]
        for item in frozen["decisions"]
    ] == [True, False]


def test_holdout_row_cannot_claim_selection_or_repeat_evaluation():
    row = holdout_result_row(
        candidate_id="stock_alpha",
        status="evaluated",
        metrics={"cagr": 0.1, "sharpe": 0.8},
    )

    assert row["period_start"] == "2016-01-01"
    assert row["period_end"] == "2020-12-31"
    assert row["evaluation_count"] == 1
    assert row["selection_used"] is False
    assert row["locked_opened"] is False
