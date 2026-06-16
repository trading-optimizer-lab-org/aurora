from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from scripts.run_spy_weekly_noleverage_50ideas import IDEA_SPECS as V1_IDEAS
from scripts.run_spy_weekly_noleverage_50ideas_v2 import (
    IDEA_SPECS,
    LOCKED_START,
    VALIDATION_END,
    build_weekly_panel,
    choose_discrete_positions_train_only,
    final_merge,
    position_policy_audit,
    run_shard,
    synthetic_weekly_panel,
)

pytestmark = pytest.mark.filterwarnings("ignore::pandas.errors.PerformanceWarning")


def test_v2_workflow_is_manual_nightly_until_0700() -> None:
    path = Path(".github/workflows/spy-weekly-noleverage-50ideas-v2-nightly-until-0700.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "SPY Weekly No-Leverage 50 Ideas V2 Nightly Until 0700"
    assert "workflow_dispatch" in data[True]
    assert "push" not in data[True]
    text = path.read_text(encoding="utf-8")
    assert "2026-06-17T07:00:00+02:00" in text
    assert "range(360)" in text
    assert "max-parallel: 180" in text
    assert "spy-weekly-noleverage-50ideas-v2-nightly-until-0700-results" in text


def test_v2_has_exactly_50_unique_new_ideas() -> None:
    v2_ids = [item["idea_id"] for item in IDEA_SPECS]
    v1_ids = {item["idea_id"] for item in V1_IDEAS}
    assert len(v2_ids) == 50
    assert len(set(v2_ids)) == 50
    assert set(v2_ids).isdisjoint(v1_ids)
    assert "weekly_return_autocorr_regime" in v2_ids
    assert "weekly_regime_transition_vote" in v2_ids


def test_v2_feature_panel_contains_new_shifted_feature_families() -> None:
    enriched = synthetic_weekly_panel(periods=1500)
    expected = {
        "autocorr_4w",
        "realized_skew_13w",
        "return_entropy_8w",
        "streak_age",
        "vol_of_vol_13w",
        "qqq_beta_26w",
        "spy_tlt_corr_26w",
        "sector_dispersion_4w",
        "time_since_high_52w",
        "multi_asset_disagreement",
    }
    assert expected.issubset(set(enriched.columns))
    assert enriched.index.max() >= LOCKED_START


def test_v2_discrete_position_selector_train_only() -> None:
    train_scores = np.r_[np.linspace(-2.0, -0.5, 40), np.zeros(20), np.linspace(0.5, 2.0, 40)]
    validation_scores = np.array([100.0, 200.0, -300.0, 0.0])
    scores = np.r_[train_scores, validation_scores]
    spy_returns = np.r_[np.where(train_scores > 0, 0.02, np.where(train_scores < 0, -0.02, 0.0)), [0.5, -0.5, 0.5, -0.5]]
    train_mask = np.array([True] * len(train_scores) + [False] * len(validation_scores))

    positions, metrics, fit = choose_discrete_positions_train_only(scores, spy_returns, train_mask, min_side_pct=0.05)

    assert set(np.unique(positions)).issubset({-1.0, 0.0, 1.0})
    assert np.any(positions == 0.0)
    assert fit["fitted_on_train_only"] is True
    assert abs(float(fit["threshold"])) < 10.0
    assert metrics["profit_factor"] > 1.0


def test_v2_policy_and_smoke_keep_locked_out_of_shards(tmp_path: Path) -> None:
    output_dir = tmp_path / "spy_weekly_noleverage_v2"
    output_dir.mkdir()
    panel = synthetic_weekly_panel(periods=1500)
    panel.loc[panel.index <= VALIDATION_END].to_csv(output_dir / "weekly_panel_no_locked.csv", index_label="timestamp")
    panel.to_csv(output_dir / "weekly_panel_all.csv", index_label="timestamp")

    ok = position_policy_audit(np.array([-1.0, 0.0, 1.0, 0.0]))
    assert ok["policy_pass"] is True
    assert ok["max_abs_position"] == 1.0

    run_shard(
        output_dir,
        stage=0,
        configs_per_stage=80,
        time_budget_minutes=0.02,
        top_per_stage=20,
        cost_bps=1.0,
    )
    final_merge(output_dir, locked_retest_top_n=30, cost_bps=1.0)

    shard_summary = pd.read_json(output_dir / "shards" / "stage_000" / "shard_summary.json", typ="series")
    assert shard_summary["locked_opened"] is False
    final = output_dir / "final"
    locked = pd.read_csv(final / "locked_results.csv")
    assert not locked.empty
    assert (locked["locked_opened"] == True).all()  # noqa: E712
    assert (locked["validation_used_for_selection"] == False).all()  # noqa: E712
