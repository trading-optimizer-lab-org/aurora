from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import validate_gtbi_fast_strict_artifact as validator


FINGERPRINT = "c" * 64


def _artifact(tmp_path: Path) -> Path:
    root = tmp_path / "result"
    root.mkdir()
    pd.DataFrame([{"candidate_id": "one", "score": 1.0}]).to_csv(root / "leaderboard.csv", index=False)
    pd.DataFrame([{"strategy_id": "two", "reason": "strict_filter"}]).to_csv(
        root / "early_rejected_strategies.csv", index=False
    )
    for name in (
        "timeout_strategies.csv",
        "runtime_errors.csv",
        "unsupported_strategies.csv",
        "slow_deferred_strategies.csv",
    ):
        pd.DataFrame(columns=["strategy_id", "reason"]).to_csv(root / name, index=False)
    pd.DataFrame(
        [
            {"strategy_id": "one", "canonical_strategy_id": "one"},
            {"strategy_id": "two", "canonical_strategy_id": "one"},
        ]
    ).to_csv(root / "dedupe_map.csv", index=False)
    pd.DataFrame([{"candidate_id": "one", "split": "validation", "year": 2011}]).to_csv(
        root / "yearly_trade_performance.csv", index=False
    )
    summary = {
        "campaign_fingerprint": FINGERPRINT,
        "github_only_run": True,
        "requires_local_machine": False,
        "strict_final_pass": True,
        "fill_missing_timeouts_enabled": False,
        "synthetic_missing_timeout_rows": 0,
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
        "total_strategies_requested": 2,
        "total_strategies_loaded": 2,
        "total_strategies_evaluated": 1,
        "total_strategies_early_rejected": 1,
        "total_strategies_timed_out": 0,
        "total_strategies_runtime_error": 0,
        "total_strategies_unsupported": 0,
        "total_strategies_slow_deferred": 0,
        "best_candidate_id": "one",
    }
    (root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (root / "campaign_manifest.json").write_text(
        json.dumps({"campaign_fingerprint": FINGERPRINT}), encoding="utf-8"
    )
    (root / "_SUCCESS").write_text(FINGERPRINT + "\n", encoding="utf-8")
    return root


def test_validator_accepts_exact_complete_artifact(tmp_path: Path) -> None:
    root = _artifact(tmp_path)

    result = validator.validate_artifact(root, expected_strategy_count=2)

    assert result["valid"] is True
    assert result["terminal_count"] == 2
    assert result["leaderboard_rows"] == 1
    assert result["early_rejected_rows"] == 1


@pytest.mark.parametrize(
    "mutation, message",
    [
        ("best_missing", "best_candidate_id"),
        ("summary_count", "leaderboard row count"),
        ("duplicate_terminal", "duplicate terminal"),
        ("failure_row", "timeout_strategies"),
        ("locked_changed", "locked_start"),
        ("success_missing", "_SUCCESS"),
        ("fingerprint_mismatch", "fingerprint"),
        ("synthetic", "synthetic_missing_timeout_rows"),
    ],
)
def test_validator_fails_closed_on_inconsistent_artifact(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    root = _artifact(tmp_path)
    summary_path = root / "summary.json"
    summary = json.loads(summary_path.read_text())
    if mutation == "best_missing":
        summary["best_candidate_id"] = "absent"
    elif mutation == "summary_count":
        summary["total_strategies_evaluated"] = 2
    elif mutation == "duplicate_terminal":
        pd.DataFrame([{"strategy_id": "one", "reason": "strict_filter"}]).to_csv(
            root / "early_rejected_strategies.csv", index=False
        )
    elif mutation == "failure_row":
        pd.DataFrame([{"strategy_id": "bad", "reason": "timeout"}]).to_csv(
            root / "timeout_strategies.csv", index=False
        )
    elif mutation == "locked_changed":
        summary["locked_start"] = "2022-01-01"
    elif mutation == "success_missing":
        (root / "_SUCCESS").unlink()
    elif mutation == "fingerprint_mismatch":
        (root / "campaign_manifest.json").write_text(
            json.dumps({"campaign_fingerprint": "d" * 64}), encoding="utf-8"
        )
    elif mutation == "synthetic":
        summary["synthetic_missing_timeout_rows"] = 1
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        validator.validate_artifact(root, expected_strategy_count=2)
