from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from scripts.run_spy_weekly_global_random_yearly_outperformance import (
    ARTIFACT_NAME,
    CAMPAIGN_ID,
    FILTER_TRAIN_YEARLY_GE_SPY_AND_CALMAR_GE_SPY,
    TRAIN_YEARLY_CALMAR_ARTIFACT_NAME,
    VALIDATION_END,
    calmar_ratio,
    merge,
    relaxed_acceptance,
    run_shard,
    synthetic_weekly_panel,
    yearly_outperformance,
)

pytestmark = pytest.mark.filterwarnings("ignore::pandas.errors.PerformanceWarning")


def test_relaxed_acceptance_removes_validation_trade_and_exposure_filters() -> None:
    train = {"total_return": 0.01}
    validation = {"total_return": 0.01, "profit_factor": 1.05}

    assert relaxed_acceptance(train, validation) is True


def test_yearly_outperformance_requires_every_calendar_year_to_beat_spy() -> None:
    index = pd.date_range("2019-01-04", periods=110, freq="W-FRI")
    mask = np.ones(len(index), dtype=bool)
    spy = np.full(len(index), 0.001)
    strategy = np.full(len(index), 0.002)

    passed = yearly_outperformance(index, strategy, spy, mask)
    assert passed["pass"] is True
    assert passed["years"] == "2019|2020|2021"
    assert passed["min_excess"] > 0

    strategy[index.year == 2020] = 0.0
    failed = yearly_outperformance(index, strategy, spy, mask)
    assert failed["pass"] is False
    assert failed["min_excess"] < 0


def test_yearly_outperformance_can_accept_equal_train_years() -> None:
    index = pd.date_range("2019-01-04", periods=110, freq="W-FRI")
    mask = np.ones(len(index), dtype=bool)
    spy = np.full(len(index), 0.001)
    strategy = spy.copy()

    strict = yearly_outperformance(index, strategy, spy, mask)
    inclusive = yearly_outperformance(index, strategy, spy, mask, inclusive=True)

    assert strict["pass"] is False
    assert inclusive["pass"] is True
    assert inclusive["min_excess"] == pytest.approx(0.0)


def test_calmar_ratio_matches_cagr_over_drawdown() -> None:
    returns = np.array([0.10, -0.05, 0.04, 0.03])
    nav = np.cumprod(1.0 + returns)
    total_return = float(nav[-1] - 1.0)
    mdd = float(np.min(nav / np.maximum.accumulate(nav) - 1.0))
    years = len(returns) / 52.0
    expected = ((1.0 + total_return) ** (1.0 / years) - 1.0) / abs(mdd)

    assert calmar_ratio(returns) == pytest.approx(expected)


def test_yearly_outperformance_workflow_is_manual_full_replay() -> None:
    path = Path(".github/workflows/spy-weekly-global-random-yearly-outperformance.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "SPY Weekly Global Random Yearly Outperformance"
    assert "workflow_dispatch" in data[True]
    assert "push" not in data[True]

    text = path.read_text(encoding="utf-8")
    assert "range(360)" in text
    assert "max-parallel: 180" in text
    assert "27809257841" in text
    assert ARTIFACT_NAME in text


def test_train_yearly_calmar_workflow_is_manual_full_replay() -> None:
    path = Path(".github/workflows/spy-weekly-global-random-train-yearly-calmar.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "SPY Weekly Global Random Train Yearly Calmar"
    assert "workflow_dispatch" in data[True]
    assert "push" not in data[True]

    text = path.read_text(encoding="utf-8")
    assert "range(360)" in text
    assert "max-parallel: 180" in text
    assert "27809257841" in text
    assert TRAIN_YEARLY_CALMAR_ARTIFACT_NAME in text
    assert FILTER_TRAIN_YEARLY_GE_SPY_AND_CALMAR_GE_SPY in text


def test_yearly_outperformance_smoke_shard_and_merge_keep_locked_closed(tmp_path: Path) -> None:
    output_dir = tmp_path / CAMPAIGN_ID
    output_dir.mkdir()
    panel = synthetic_weekly_panel(periods=1500)
    panel.loc[panel.index <= VALIDATION_END].to_csv(output_dir / "weekly_panel_no_locked.csv", index_label="timestamp")

    run_shard(
        output_dir,
        stage=0,
        configs_per_stage=25,
        time_budget_minutes=0.01,
        cost_bps=1.0,
    )
    merge(output_dir)

    final = output_dir / "final"
    summary = json.loads((final / "summary.json").read_text(encoding="utf-8"))
    policy = json.loads((final / "position_policy_audit.json").read_text(encoding="utf-8"))
    yearly = pd.read_csv(final / "yearly_outperform.csv")

    assert summary["campaign_id"] == CAMPAIGN_ID
    assert summary["filters_removed"] == ["validation_trades_min_40", "validation_abs_exposure_015_090"]
    assert summary["locked_opened"] is False
    assert summary["validation_used_for_selection"] is False
    assert policy["traded_asset"] == "SPY"
    assert policy["leverage_allowed"] is False
    assert policy["locked_opened"] is False
    assert "train_min_annual_excess_vs_spy" in yearly.columns


def test_train_yearly_calmar_smoke_shard_and_merge_keep_locked_closed(tmp_path: Path) -> None:
    output_dir = tmp_path / f"{CAMPAIGN_ID}_train_calmar"
    output_dir.mkdir()
    panel = synthetic_weekly_panel(periods=1500)
    panel.loc[panel.index <= VALIDATION_END].to_csv(output_dir / "weekly_panel_no_locked.csv", index_label="timestamp")

    run_shard(
        output_dir,
        stage=0,
        configs_per_stage=25,
        time_budget_minutes=0.01,
        cost_bps=1.0,
        filter_mode=FILTER_TRAIN_YEARLY_GE_SPY_AND_CALMAR_GE_SPY,
    )
    merge(output_dir, filter_mode=FILTER_TRAIN_YEARLY_GE_SPY_AND_CALMAR_GE_SPY)

    final = output_dir / "final"
    summary = json.loads((final / "summary.json").read_text(encoding="utf-8"))
    policy = json.loads((final / "position_policy_audit.json").read_text(encoding="utf-8"))
    yearly = pd.read_csv(final / "yearly_outperform.csv")

    assert summary["filter_mode"] == FILTER_TRAIN_YEARLY_GE_SPY_AND_CALMAR_GE_SPY
    assert summary["locked_opened"] is False
    assert policy["filter_mode"] == FILTER_TRAIN_YEARLY_GE_SPY_AND_CALMAR_GE_SPY
    assert policy["locked_opened"] is False
    assert "train_calmar_excess_vs_spy" in yearly.columns
