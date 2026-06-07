from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.merge_paper_sharpe2_overnight import merge_overnight


def test_overnight_workflow_uses_360_jobs_without_aqr() -> None:
    workflow = Path(".github/workflows/paper-sharpe2-overnight-360jobs.yml").read_text(encoding="utf-8")
    assert workflow.count("max-parallel: 180") == 14
    assert "paper_aqr" not in workflow.lower()
    assert "aqr-factor" not in workflow.lower()
    assert "--total-stages 720" in workflow
    assert "--total-stages 1080" in workflow
    assert "path: ${{ env.CBOE_DIR }}/shards/stage_*" in workflow
    assert "path: ${{ env.ENSEMBLE_DIR }}/shards/stage_*" in workflow
    assert "path: ${{ env.SPY_DIR }}/shards/stage_*" in workflow
    assert "paper-sharpe2-overnight-360jobs-results" in workflow


def test_overnight_aggregator_accepts_only_policy_clean_sharpe2(tmp_path: Path) -> None:
    root = tmp_path / "overnight"
    cboe_final = root / "cboe_vix_sentiment_deep" / "final"
    cboe_final.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "candidate_id": "good",
                "paper_title": "Paper A",
                "source_rule_summary": "Rule A",
                "paper_strategy_type": "template_replicable",
                "traded_asset": "SPY",
                "frequency": "daily",
                "train_sharpe": 2.1,
                "validation_sharpe": 2.2,
                "locked_opened": False,
                "validation_used_for_selection": False,
                "uses_individual_stocks": False,
                "paper_exact_replication_claimed": False,
                "lookahead_audit": "lag 1",
            },
            {
                "candidate_id": "bad_locked",
                "paper_title": "Paper B",
                "source_rule_summary": "Rule B",
                "paper_strategy_type": "template_replicable",
                "traded_asset": "SPY",
                "frequency": "daily",
                "train_sharpe": 3.0,
                "validation_sharpe": 3.0,
                "locked_opened": True,
                "validation_used_for_selection": False,
                "uses_individual_stocks": False,
                "paper_exact_replication_claimed": False,
                "lookahead_audit": "invalid",
            },
        ]
    ).to_csv(cboe_final / "paper_cboe_sentiment_leaderboard.csv", index=False)
    (cboe_final / "paper_cboe_sentiment_summary.json").write_text(
        json.dumps({"campaign": "cboe_vix_sentiment_deep", "locked_opened": False}),
        encoding="utf-8",
    )

    merge_overnight(root)
    accepted = pd.read_csv(root / "final" / "accepted_strategies.csv")
    summary = json.loads((root / "final" / "overnight_summary.json").read_text(encoding="utf-8"))
    assert accepted["strategy_id"].tolist() == ["good"]
    assert summary["accepted_count"] == 1
    assert summary["locked_opened"] is False
    assert summary["validation_used_for_selection"] is False
