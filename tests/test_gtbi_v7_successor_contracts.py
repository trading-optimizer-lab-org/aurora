from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from infra.gtbi_v7_readiness.successor_contracts import (
    SuccessorContractError,
    schema_inventory,
    validate_v7_result_artifact,
)


def _artifact(root: Path) -> Path:
    root.mkdir()
    leaderboard = pd.DataFrame(
        [
            {
                "candidate_id": "one",
                "strategy_id": "one",
                "family": "gtbi_long_hold",
                "score": 1.0,
                "locked_opened": False,
                "train_profit_factor": 1.2,
                "validation_profit_factor": 1.3,
                "adjusted_return_time_risk": 0.1,
                "strict_quality_pass": False,
            }
        ]
    )
    leaderboard.to_csv(root / "leaderboard.csv", index=False)
    leaderboard.iloc[0:0].to_csv(root / "filtered_leaderboard.csv", index=False)
    pd.DataFrame(
        [
            {
                "candidate_id": "one",
                "split": "validation",
                "year": 2020,
                "trades": 10,
                "avg_trade_return_pct": 1.0,
                "median_trade_return_pct": 0.5,
                "win_rate": 0.6,
                "profit_factor": 1.3,
                "avg_holding_days": 20.0,
            }
        ]
    ).to_csv(root / "yearly_trade_performance.csv", index=False)
    pd.DataFrame(columns=["strategy_id", "reason"]).to_csv(
        root / "early_rejected_strategies.csv", index=False
    )
    (root / "top_indicator_rules.jsonl").write_text(
        json.dumps(
            {
                "candidate_id": "one",
                "strategy_id": "one",
                "external_strategy": {},
                "config": {},
                "score": 1.0,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "summary.json").write_text(
        json.dumps(
            {
                "campaign_id": "gtbi_v7_new_reference_v1",
                "github_only_run": True,
                "requires_local_machine": False,
                "locked_start": "2021-01-01",
                "locked_authorized": False,
                "locked_data_accessed": False,
                "train_end": "2010-12-31",
                "validation_start": "2011-01-01",
                "validation_end": "2020-12-31",
                "total_strategies_requested": 72000,
                "total_strategies_loaded": 72000,
                "total_strategies_evaluated": 1,
                "total_strategies_early_rejected": 0,
                "total_terminal_identities": 72000,
                "leaderboard_rows": 1,
                "best_candidate_id": "one",
            }
        ),
        encoding="utf-8",
    )
    return root


def test_successor_result_contract_reconciles_real_rows(tmp_path: Path) -> None:
    receipt = validate_v7_result_artifact(_artifact(tmp_path / "artifact"))
    assert receipt["valid"] is True
    assert receipt["leaderboard_rows"] == 1
    assert receipt["maximum_result_year"] == 2020


def test_successor_result_contract_rejects_best_outside_leaderboard(tmp_path: Path) -> None:
    root = _artifact(tmp_path / "artifact")
    summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
    summary["best_candidate_id"] = "missing"
    (root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(SuccessorContractError, match="best_candidate_id"):
        validate_v7_result_artifact(root)


def test_successor_result_contract_rejects_locked_year(tmp_path: Path) -> None:
    root = _artifact(tmp_path / "artifact")
    yearly = pd.read_csv(root / "yearly_trade_performance.csv")
    yearly.loc[0, "year"] = 2021
    yearly.to_csv(root / "yearly_trade_performance.csv", index=False)
    with pytest.raises(Exception, match="2020"):
        validate_v7_result_artifact(root)


def test_versioned_result_schemas_are_registered() -> None:
    inventory = schema_inventory()
    assert len(inventory) == 4
    assert all(row["sha256"].startswith("sha256:") for row in inventory)
