from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from scripts.run_spy_weekly_noleverage_50ideas import (
    IDEA_SPECS,
    LOCKED_START,
    VALIDATION_END,
    choose_discrete_positions_train_only,
    final_merge,
    position_policy_audit,
    run_shard,
    synthetic_weekly_panel,
)

pytestmark = pytest.mark.filterwarnings("ignore::pandas.errors.PerformanceWarning")


def test_workflow_is_manual_nightly_until_0700() -> None:
    path = Path(".github/workflows/spy-weekly-noleverage-50ideas-nightly-until-0700.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "SPY Weekly No-Leverage 50 Ideas Nightly Until 0700"
    assert "workflow_dispatch" in data[True]
    assert "push" not in data[True]
    text = path.read_text(encoding="utf-8")
    assert "2026-06-17T07:00:00+02:00" in text
    assert "range(360)" in text
    assert "max-parallel: 180" in text
    assert "spy-weekly-noleverage-50ideas-nightly-until-0700-results" in text


def test_exactly_50_unique_idea_specs() -> None:
    idea_ids = [item["idea_id"] for item in IDEA_SPECS]
    assert len(idea_ids) == 50
    assert len(set(idea_ids)) == 50
    assert "weekly_failed_breakout_reversal" in idea_ids
    assert "weekly_post_gain_week_behavior" in idea_ids


def test_discrete_position_selector_uses_train_only_and_allows_cash() -> None:
    train_scores = np.r_[np.linspace(-2.0, -0.5, 40), np.zeros(20), np.linspace(0.5, 2.0, 40)]
    validation_scores = np.array([100.0, 200.0, -300.0, 0.0])
    scores = np.r_[train_scores, validation_scores]
    spy_returns = np.r_[np.where(train_scores > 0, 0.02, np.where(train_scores < 0, -0.02, 0.0)), [0.5, -0.5, 0.5, -0.5]]
    train_mask = np.array([True] * len(train_scores) + [False] * len(validation_scores))

    positions, metrics, fit = choose_discrete_positions_train_only(scores, spy_returns, train_mask, min_side_pct=0.05)

    assert set(np.unique(positions)).issubset({-1.0, 0.0, 1.0})
    assert np.any(positions == 0.0)
    assert abs(float(fit["threshold"])) < 10.0
    assert fit["fitted_on_train_only"] is True
    assert metrics["profit_factor"] > 1.0


def test_position_policy_rejects_leverage_and_non_spy_shape() -> None:
    ok = position_policy_audit(np.array([-1.0, 0.0, 1.0, 0.0]))
    bad = position_policy_audit(np.array([-1.0, 0.0, 1.25]))
    assert ok["policy_pass"] is True
    assert ok["max_abs_position"] == 1.0
    assert ok["unique_positions"] == "-1|0|1"
    assert bad["policy_pass"] is False


def test_synthetic_smoke_runs_shard_and_final_merge_without_locked_selection(tmp_path: Path) -> None:
    output_dir = tmp_path / "spy_weekly_noleverage"
    output_dir.mkdir()
    panel = synthetic_weekly_panel(periods=1500)
    panel.loc[panel.index <= VALIDATION_END].to_csv(output_dir / "weekly_panel_no_locked.csv", index_label="timestamp")
    panel.to_csv(output_dir / "weekly_panel_all.csv", index_label="timestamp")

    run_shard(
        output_dir,
        stage=0,
        configs_per_stage=80,
        time_budget_minutes=0.02,
        top_per_stage=20,
        cost_bps=1.0,
    )
    final_merge(output_dir, locked_retest_top_n=30, cost_bps=1.0)

    final = output_dir / "final"
    assert (final / "leaderboard.csv").exists()
    assert (final / "locked_results.csv").exists()
    policy = pd.read_json(final / "position_policy_audit.json", typ="series")
    assert policy["traded_asset"] == "SPY"
    assert policy["leverage_allowed"] is False
    assert policy["cash_allowed"] is True
    locked = pd.read_csv(final / "locked_results.csv")
    assert not locked.empty
    assert (locked["locked_opened"] == True).all()  # noqa: E712
    assert (locked["validation_used_for_selection"] == False).all()  # noqa: E712
    assert panel.index.max() >= LOCKED_START
