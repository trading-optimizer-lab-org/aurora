from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from scripts.run_spy_weekly_noleverage_50ideas import IDEA_SPECS as V1_IDEAS
from scripts.run_spy_weekly_noleverage_50ideas_v2 import IDEA_SPECS as V2_IDEAS
from scripts.run_spy_weekly_noleverage_global_random import (
    CAMPAIGN_ID,
    GLOBAL_RANDOM_IDEA_SPECS,
    LOCKED_START,
    VALIDATION_END,
    final_merge,
    position_policy_audit,
    run_shard,
    synthetic_weekly_panel,
)

pytestmark = pytest.mark.filterwarnings("ignore::pandas.errors.PerformanceWarning")


def test_global_random_workflow_is_manual_until_19_jun_0700() -> None:
    path = Path(".github/workflows/spy-weekly-noleverage-global-random-nightly-until-0700.yml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["name"] == "SPY Weekly No-Leverage Global Random Nightly Until 0700"
    assert "workflow_dispatch" in data[True]
    assert "push" not in data[True]
    text = path.read_text(encoding="utf-8")
    assert "2026-06-19T07:00:00+02:00" in text
    assert "range(360)" in text
    assert "max-parallel: 180" in text
    assert "spy-weekly-noleverage-global-random-nightly-until-0700-results" in text


def test_global_random_specs_are_many_unique_and_not_v1_v2() -> None:
    ids = [item["idea_id"] for item in GLOBAL_RANDOM_IDEA_SPECS]
    old_ids = {item["idea_id"] for item in V1_IDEAS} | {item["idea_id"] for item in V2_IDEAS}
    assert len(ids) == 96
    assert len(set(ids)) == 96
    assert set(ids).isdisjoint(old_ids)
    assert all(item["idea_id"].startswith("global_random_") for item in GLOBAL_RANDOM_IDEA_SPECS)


def test_global_random_policy_is_spy_only_discrete_and_no_leverage() -> None:
    ok = position_policy_audit(np.array([-1.0, 0.0, 1.0, 0.0]))
    bad = position_policy_audit(np.array([-1.0, 0.0, 1.5]))
    assert CAMPAIGN_ID == "spy_weekly_noleverage_global_random_nightly_until_0700"
    assert ok["policy_pass"] is True
    assert ok["max_abs_position"] == 1.0
    assert ok["unique_positions"] == "-1|0|1"
    assert bad["policy_pass"] is False


def test_global_random_smoke_shard_and_merge_keep_locked_out_of_selection(tmp_path: Path) -> None:
    output_dir = tmp_path / CAMPAIGN_ID
    output_dir.mkdir()
    panel = synthetic_weekly_panel(periods=1500)
    panel.loc[panel.index <= VALIDATION_END].to_csv(output_dir / "weekly_panel_no_locked.csv", index_label="timestamp")
    panel.to_csv(output_dir / "weekly_panel_all.csv", index_label="timestamp")

    run_shard(
        output_dir,
        stage=0,
        configs_per_stage=90,
        time_budget_minutes=0.02,
        top_per_stage=25,
        cost_bps=1.0,
    )
    final_merge(output_dir, locked_retest_top_n=30, cost_bps=1.0)

    shard_summary = pd.read_json(output_dir / "shards" / "stage_000" / "shard_summary.json", typ="series")
    assert shard_summary["locked_opened"] is False
    assert shard_summary["validation_used_for_selection"] is False
    final = output_dir / "final"
    policy = pd.read_json(final / "position_policy_audit.json", typ="series")
    assert policy["traded_asset"] == "SPY"
    assert policy["cash_allowed"] is True
    assert policy["leverage_allowed"] is False
    assert policy["max_abs_position"] == 1.0
    locked = pd.read_csv(final / "locked_results.csv")
    assert not locked.empty
    assert (locked["locked_opened"] == True).all()  # noqa: E712
    assert (locked["validation_used_for_selection"] == False).all()  # noqa: E712
    assert panel.index.max() >= LOCKED_START
