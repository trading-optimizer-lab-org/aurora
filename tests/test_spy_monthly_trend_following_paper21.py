from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from scripts.run_spy_monthly_trend_following_paper21 import (
    LOCKED_START,
    build_signal,
    exact_configs,
    metrics,
    run_merge,
)


def test_workflow_is_manual_355_jobs() -> None:
    path = Path(".github/workflows/spy-monthly-trend-following-paper21-355jobs.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "SPY Monthly Trend Following Paper21 355 Jobs"
    assert "workflow_dispatch" in data[True]
    assert "push" not in data[True]
    text = path.read_text(encoding="utf-8")
    assert "range(355)" in text
    assert "max-parallel: 178" in text
    assert "max-parallel: 177" in text
    assert "spy-monthly-trend-following-paper21-355jobs-results" in text


def test_exact_configs_include_three_requested_rules() -> None:
    configs = exact_configs()
    assert any(c["family"] == "breakout_daily_high" and c["daily_window"] == 250 for c in configs)
    assert any(c["family"] == "ma_monthly_close" and c["monthly_window"] == 10 for c in configs)
    assert any(c["family"] == "ma_monthly_close" and c["monthly_window"] == 12 for c in configs)
    assert any(c["family"] == "ma_daily_close" and c["daily_window"] == 200 for c in configs)


def test_signals_are_monthly_and_no_locked() -> None:
    daily_idx = pd.date_range("1998-01-01", periods=900, freq="B")
    daily = pd.Series(np.linspace(100.0, 160.0, len(daily_idx)), index=daily_idx)
    monthly = daily.resample("ME").last()
    for params in exact_configs():
        signal = build_signal(params, daily, monthly)
        assert not signal.empty
        assert signal.index.max() < LOCKED_START
        assert signal.dropna().isin([True, False]).all()


def test_daily_derived_signals_align_to_monthly_calendar() -> None:
    daily_idx = pd.date_range("1999-01-04", periods=700, freq="B")
    daily = pd.Series(np.linspace(100.0, 180.0, len(daily_idx)), index=daily_idx)
    monthly = daily.resample("ME").last()
    monthly = monthly.iloc[2:]
    params = {
        "family": "breakout_daily_high",
        "daily_window": 250,
        "monthly_window": 12,
        "confirm_months": 1,
        "buffer": 0.0,
        "cash_source": "tbill",
        "lag_months": 1,
    }
    signal = build_signal(params, daily, monthly)
    assert signal.index.equals(monthly.index)
    assert signal.dropna().isin([True, False]).all()


def test_metrics_are_finite_for_positive_path() -> None:
    idx = pd.date_range("2000-01-31", periods=36, freq="ME")
    values = pd.Series([0.01] * len(idx), index=idx)
    out = metrics(values)
    assert out["cagr"] > 0.0
    assert np.isfinite(out["sharpe"])
    assert out["final_nav"] > 1.0


def test_merge_finds_nested_github_artifact_layout(tmp_path: Path) -> None:
    stage_dir = tmp_path / "shards" / "spy-monthly-trend-following-paper21-stage-7" / "stage_007"
    stage_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "strategy_id": "test_strategy",
                "family": "ma_monthly_close",
                "validation_score": 2.0,
                "train_score": 1.0,
                "validation_sharpe": 1.4,
                "train_sharpe": 1.1,
                "validation_cagr": 0.12,
                "validation_mdd": -0.15,
                "train_cagr": 0.10,
            }
        ]
    ).to_csv(stage_dir / "candidates.csv", index=False)
    (stage_dir / "shard_summary.json").write_text(
        json.dumps({"stage": 7, "candidates": 1}),
        encoding="utf-8",
    )

    run_merge(tmp_path)

    summary = json.loads((tmp_path / "final" / "summary.json").read_text(encoding="utf-8"))
    assert summary["stages_reported"] == 1
    assert summary["candidates"] == 1
