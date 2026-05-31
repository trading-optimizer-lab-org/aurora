from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from aurora.research.sp500_weekly_hedge_search import (
    SP500WeeklyHedgeConfig,
    candidate_id_from_spec,
    choose_train_size,
    evaluate_spec,
    hedge_train_score,
    merge_stage_rows,
    portfolio_metrics,
    run_stage,
)


def _dataset() -> dict[str, object]:
    idx = pd.date_range("2020-01-03", periods=80, freq="W-FRI")
    spy = np.resize(np.array([0.03, -0.04, 0.02, -0.03], dtype=float), len(idx))
    tlt = np.where(spy < 0.0, 0.025, 0.002)
    xle = np.where(spy < 0.0, -0.020, 0.020)
    asset_returns = pd.DataFrame({"SPY": spy, "TLT": tlt, "XLE": xle}, index=idx)
    features = pd.DataFrame(
        {
            "SPY__ret_1w": spy,
            "TLT__ret_1w": tlt,
            "XLE__ret_1w": xle,
            "macro__stress": np.where(spy < 0.0, 1.0, -1.0),
        },
        index=idx,
    )
    return {
        "train_x": features.iloc[:50],
        "valid_x": features.iloc[50:],
        "train_asset_returns": asset_returns.iloc[:50],
        "valid_asset_returns": asset_returns.iloc[50:],
        "train_spy_returns": asset_returns["SPY"].iloc[:50].to_numpy(dtype=float),
        "valid_spy_returns": asset_returns["SPY"].iloc[50:].to_numpy(dtype=float),
        "train_index": pd.DatetimeIndex(idx[:50]),
        "valid_index": pd.DatetimeIndex(idx[50:]),
        "feature_names": tuple(features.columns),
        "asset_symbols": ("SPY", "TLT", "XLE"),
    }


def test_score_prefers_strategy_that_gains_when_spy_falls_and_does_not_lose_when_spy_rises() -> None:
    idx = pd.date_range("2020-01-03", periods=8, freq="W-FRI")
    spy = np.array([0.03, -0.04, 0.02, -0.03, 0.01, -0.02, 0.02, -0.01])
    good = np.where(spy < 0.0, 0.02, 0.003)
    bad = np.where(spy < 0.0, -0.02, 0.010)
    assert hedge_train_score(portfolio_metrics(good, spy, idx, size=1.0)) > hedge_train_score(
        portfolio_metrics(bad, spy, idx, size=1.0)
    )


def test_size_is_chosen_only_from_train() -> None:
    idx = pd.date_range("2020-01-03", periods=8, freq="W-FRI")
    config = SP500WeeklyHedgeConfig(size_grid=(0.5, 1.0, 2.0, 5.0))
    train_base = np.full(len(idx), 0.01)
    valid_base = np.full(len(idx), -0.02)
    spy = np.full(len(idx), -0.01)
    size, train_metrics = choose_train_size(train_base, spy, idx, config)
    valid_metrics = portfolio_metrics(valid_base, spy, idx, size=size)
    assert size == 5.0
    assert train_metrics["final_nav"] > 1.0
    assert valid_metrics["final_nav"] < 1.0


def test_evaluate_spec_allows_short_asset_weights_and_keeps_validation_report_only() -> None:
    config = SP500WeeklyHedgeConfig(size_grid=(1.0,), top_rows_per_stage=5)
    spec = {
        "method": "dehb_real",
        "route": "weekly_hedge_linear",
        "features": ("macro__stress",),
        "signal_weights": (1.0,),
        "threshold": 0.0,
        "assets": ("XLE",),
        "asset_weights": (-1.0,),
        "iteration": 0,
        "stage": 0,
    }
    row = evaluate_spec(_dataset(), config, spec)
    assert row["method"] == "dehb_real"
    assert row["allows_short"] is True
    assert row["validation_used_for_selection"] is False
    assert row["locked_opened"] is False
    assert float(row["short_gross_weight"]) > 0.0
    assert "XLE:-1" in row["asset_weights"]


def test_run_stage_uses_dehb_real_only() -> None:
    config = SP500WeeklyHedgeConfig(top_rows_per_stage=10, size_grid=(1.0,), random_seed=7)
    rows, meta, audit = run_stage(
        config,
        stage=0,
        total_stages=3,
        time_budget_minutes=0.001,
        wave=2,
        total_waves=6,
        dataset=_dataset(),
    )
    assert rows
    assert {row["method"] for row in rows} == {"dehb_real"}
    assert {row["wave"] for row in rows} == {2}
    assert {row["total_waves"] for row in rows} == {6}
    assert meta["method"] == "dehb_real"
    assert meta["wave"] == 2
    assert meta["total_waves"] == 6
    assert audit["locked_opened"] is False


def test_wave_changes_seed_but_not_candidate_identity_contract() -> None:
    config = SP500WeeklyHedgeConfig(top_rows_per_stage=5, size_grid=(1.0,), random_seed=11)
    _, meta0, _ = run_stage(
        config,
        stage=0,
        total_stages=2,
        time_budget_minutes=0.001,
        wave=0,
        total_waves=6,
        dataset=_dataset(),
    )
    _, meta1, _ = run_stage(
        config,
        stage=0,
        total_stages=2,
        time_budget_minutes=0.001,
        wave=1,
        total_waves=6,
        dataset=_dataset(),
    )
    assert meta0["seed"] != meta1["seed"]
    spec = {
        "method": "dehb_real",
        "route": "weekly_hedge_linear",
        "features": ("macro__stress",),
        "signal_weights": (1.0,),
        "threshold": 0.0,
        "assets": ("TLT",),
        "asset_weights": (1.0,),
        "iteration": 0,
        "stage_bucket": 0,
        "engine": "dehb_real",
        "can_short": True,
    }
    assert candidate_id_from_spec(spec) == candidate_id_from_spec(dict(spec))
    rows, _, _ = run_stage(
        config,
        stage=0,
        total_stages=2,
        time_budget_minutes=0.001,
        wave=1,
        total_waves=6,
        dataset=_dataset(),
    )
    assert rows
    assert all("wave" not in json.loads(row["rule"]) for row in rows)


def test_merge_dedupes_by_candidate_id() -> None:
    a = pd.DataFrame([{"candidate_id": "x", "train_score": 1.0}, {"candidate_id": "y", "train_score": 2.0}])
    b = pd.DataFrame([{"candidate_id": "x", "train_score": 3.0}])
    merged = merge_stage_rows([a, b])
    assert len(merged) == 2
    assert float(merged.loc[merged["candidate_id"] == "x", "train_score"].iloc[0]) == 3.0


def test_workflow_shapes_for_1wave_and_6waves_are_comparable() -> None:
    one = Path(".github/workflows/sp500-weekly-hedge-dehb-1wave-80jobs-1h.yml")
    six = Path(".github/workflows/sp500-weekly-hedge-dehb-6waves-80jobs-1h.yml")
    one_data = yaml.safe_load(one.read_text(encoding="utf-8"))
    six_data = yaml.safe_load(six.read_text(encoding="utf-8"))
    assert one_data["env"]["EXPECTED_JOBS"] == "80"
    assert one_data["env"]["WAVES"] == "1"
    assert one_data["env"]["JOBS_PER_WAVE"] == "80"
    assert one_data["env"]["ASSUMED_EFFECTIVE_PARALLELISM"] == "180"
    assert one_data["jobs"]["wave_0"]["strategy"]["max-parallel"] == 500
    assert len(one_data["jobs"]["wave_0"]["strategy"]["matrix"]["stage"]) == 80
    assert six_data["env"]["EXPECTED_JOBS"] == "480"
    assert six_data["env"]["WAVES"] == "6"
    assert six_data["env"]["JOBS_PER_WAVE"] == "80"
    assert six_data["env"]["ASSUMED_EFFECTIVE_PARALLELISM"] == "180"
    for wave in range(6):
        job = six_data["jobs"][f"wave_{wave}"]
        assert job["strategy"]["max-parallel"] == 500
        assert len(job["strategy"]["matrix"]["stage"]) == 80
    for text in (one.read_text(encoding="utf-8"), six.read_text(encoding="utf-8")):
        assert "genetic" not in text
        assert "github_ml" not in text
        assert "beam" not in text
        assert "bandit" not in text


def test_stage_script_smoke_with_synthetic_dataset(tmp_path: Path) -> None:
    out = tmp_path / "out"
    cmd = [
        sys.executable,
        "scripts/run_sp500_weekly_hedge_dehb_stage.py",
        "--synthetic-smoke",
        "--wave",
        "1",
        "--total-waves",
        "2",
        "--stage",
        "0",
        "--total-stages",
        "2",
        "--time-budget-minutes",
        "0.001",
        "--output-dir",
        str(out),
        "--top-rows-per-stage",
        "5",
    ]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    meta = json.loads(completed.stdout)
    assert meta["wave"] == 1
    assert meta["total_waves"] == 2
    assert meta["locked_opened"] is False
    assert meta["validation_used_for_selection"] is False
    assert list(out.glob("*_wave_1_stage_0.csv"))
