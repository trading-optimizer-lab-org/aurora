from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import global_technical_buy_indicator as gtbi
from scripts import gtbi_fast_strict as planner


def _candidate(
    strategy_id: str,
    *,
    shard_id: int,
    slot_in_shard: int,
    stop_loss_pct: float,
    concept_id: str,
) -> gtbi.ExternalStrategyCandidate:
    config = gtbi.IndicatorConfig(
        family="minervini_sepa",
        stop_loss_pct=stop_loss_pct,
        max_holding_days=30,
    )
    payload = {
        "strategy_id": strategy_id,
        "shard_id": shard_id,
        "slot_in_shard": slot_in_shard,
        "concept_id": concept_id,
        "market_overlay_id": "market",
        "trend_profile_id": "trend",
        "rs_profile_id": "rs",
        "exit_profile_id": "exit",
        "aggression_id": "normal",
    }
    return gtbi.ExternalStrategyCandidate(payload, config, (), ())


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    frame = pd.DataFrame(rows)
    frame.to_csv(path, index=False)


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    canonical = _candidate(
        "canonical-ok",
        shard_id=0,
        slot_in_shard=0,
        stop_loss_pct=0.08,
        concept_id="canonical-concept",
    )
    alias = _candidate(
        "alias-ok",
        shard_id=2,
        slot_in_shard=7,
        stop_loss_pct=0.08,
        concept_id="alias-concept",
    )
    rejected = _candidate(
        "canonical-reject",
        shard_id=3,
        slot_in_shard=9,
        stop_loss_pct=0.12,
        concept_id="reject-concept",
    )
    candidates = [canonical, alias, rejected]
    monkeypatch.setattr(
        gtbi,
        "load_external_strategy_candidates",
        lambda *args, **kwargs: candidates,
    )

    canonical_root = tmp_path / "canonical"
    canonical_root.mkdir()
    _write_csv(
        canonical_root / "leaderboard.csv",
        [
            {
                "candidate_id": "canonical-ok",
                "score": 12.5,
                "adjusted_return_time_risk": 3.5,
                "strict_quality_pass": True,
                "strategy_id": "canonical-ok",
                "shard_id": 99,
                "slot_in_shard": 99,
                "concept_id": "worker-metadata",
            }
        ],
    )
    _write_csv(
        canonical_root / "early_rejected_strategies.csv",
        [
            {
                "strategy_id": "canonical-reject",
                "reason": "final_filter",
                "split": "validation",
                "year": 2011,
                "actual": 0.9,
                "threshold": 1.05,
                "stage": "final_filter_irreversible",
            }
        ],
    )
    _write_csv(
        canonical_root / "yearly_trade_performance.csv",
        [
            {
                "candidate_id": "canonical-ok",
                "split": "validation",
                "year": 2011,
                "trades": 150,
                "avg_trade_return_pct": 1.2,
            },
            {
                "candidate_id": "canonical-ok",
                "split": "validation",
                "year": 2012,
                "trades": 160,
                "avg_trade_return_pct": 1.3,
            },
        ],
    )
    _write_csv(
        canonical_root / "timing_diagnostics.csv",
        [
            {"strategy_id": "canonical-ok", "result_status": "evaluated", "seconds_total": 10.0},
            {"strategy_id": "canonical-reject", "result_status": "early_rejected", "seconds_total": 8.0},
        ],
    )

    alias_map = tmp_path / "alias_map.csv"
    ok_hash = planner.economic_evaluation_hash(canonical)
    reject_hash = planner.economic_evaluation_hash(rejected)
    _write_csv(
        alias_map,
        [
            {
                "strategy_id": "canonical-ok",
                "evaluation_hash": ok_hash,
                "canonical_strategy_id": "canonical-ok",
                "source_shard_id": 0,
                "source_slot_in_shard": 0,
                "global_slot": 0,
                "worker_id": 0,
            },
            {
                "strategy_id": "alias-ok",
                "evaluation_hash": ok_hash,
                "canonical_strategy_id": "canonical-ok",
                "source_shard_id": 2,
                "source_slot_in_shard": 7,
                "global_slot": 407,
                "worker_id": 0,
            },
            {
                "strategy_id": "canonical-reject",
                "evaluation_hash": reject_hash,
                "canonical_strategy_id": "canonical-reject",
                "source_shard_id": 3,
                "source_slot_in_shard": 9,
                "global_slot": 609,
                "worker_id": 1,
            },
        ],
    )
    campaign = tmp_path / "campaign_manifest.json"
    campaign_payload = {
        "campaign_fingerprint": "campaign-fp",
        "inputs": {
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "locked_start": "2021-01-01",
            "min_market_cap": 2_000_000_000,
        },
    }
    campaign.write_text(json.dumps(campaign_payload), encoding="utf-8")
    (canonical_root / "campaign_manifest.json").write_text(
        json.dumps(campaign_payload),
        encoding="utf-8",
    )
    pack = tmp_path / "pack"
    pack.mkdir()
    return {
        "canonical_root": canonical_root,
        "alias_map": alias_map,
        "campaign": campaign,
        "pack": pack,
        "output": tmp_path / "expanded",
    }


def test_consistent_duplicate_validator_accepts_identical_rows() -> None:
    frame = pd.DataFrame(
        [
            {"candidate_id": "same", "score": 1.0, "value": float("nan")},
            {"candidate_id": "same", "score": 1.0, "value": float("nan")},
        ]
    )

    gtbi._assert_consistent_duplicate_rows(frame, ["candidate_id"], label="leaderboard")


def test_consistent_duplicate_validator_rejects_conflicting_strategy_row() -> None:
    frame = pd.DataFrame(
        [
            {"candidate_id": "same", "score": 1.0},
            {"candidate_id": "same", "score": 2.0},
        ]
    )

    with pytest.raises(ValueError, match="conflicting duplicate leaderboard"):
        gtbi._assert_consistent_duplicate_rows(frame, ["candidate_id"], label="leaderboard")


def test_consistent_duplicate_validator_rejects_conflicting_detail_row() -> None:
    frame = pd.DataFrame(
        [
            {"candidate_id": "same", "split": "validation", "year": 2011, "trades": 100},
            {"candidate_id": "same", "split": "validation", "year": 2011, "trades": 101},
        ]
    )

    with pytest.raises(ValueError, match="conflicting duplicate yearly"):
        gtbi._assert_consistent_duplicate_rows(
            frame,
            ["candidate_id", "split", "year"],
            label="yearly",
        )


def test_expand_aliases_restores_identity_metadata_and_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import gtbi_fast_strict_results as results

    paths = _fixture(tmp_path, monkeypatch)
    summary = results.expand_canonical_results(
        canonical_results_root=paths["canonical_root"],
        alias_map_path=paths["alias_map"],
        original_pack_path=paths["pack"],
        campaign_manifest_path=paths["campaign"],
        output_dir=paths["output"],
        expected_alias_count=3,
    )

    leaderboard = pd.read_csv(paths["output"] / "leaderboard_job_aliases.csv")
    rejected = pd.read_csv(paths["output"] / "early_rejected_strategies_job_aliases.csv")
    yearly = pd.read_csv(paths["output"] / "yearly_trade_performance_job_aliases.csv")
    timing = pd.read_csv(paths["output"] / "timing_diagnostics_job_aliases.csv")
    dedupe = pd.read_csv(paths["output"] / "dedupe_map_job_aliases.csv")

    assert set(leaderboard["candidate_id"]) == {"canonical-ok", "alias-ok"}
    alias_row = leaderboard.loc[leaderboard["candidate_id"] == "alias-ok"].iloc[0]
    assert alias_row["score"] == 12.5
    assert alias_row["strategy_id"] == "alias-ok"
    assert alias_row["shard_id"] == 2
    assert alias_row["slot_in_shard"] == 7
    assert alias_row["concept_id"] == "alias-concept"
    assert rejected["strategy_id"].tolist() == ["canonical-reject"]
    assert len(yearly) == 4
    assert set(yearly["candidate_id"]) == {"canonical-ok", "alias-ok"}
    assert len(timing) == 3
    assert len(dedupe) == 3
    assert summary["total_aliases"] == 3
    assert summary["leaderboard_rows"] + summary["early_rejected_rows"] == 3
    assert summary["timeout_rows"] == 0
    assert summary["synthetic_missing_timeout_rows"] == 0


def test_expand_aliases_rejects_campaign_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import gtbi_fast_strict_results as results

    paths = _fixture(tmp_path, monkeypatch)
    (paths["canonical_root"] / "campaign_manifest.json").write_text(
        json.dumps({"campaign_fingerprint": "wrong"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="campaign fingerprint mismatch"):
        results.expand_canonical_results(
            canonical_results_root=paths["canonical_root"],
            alias_map_path=paths["alias_map"],
            original_pack_path=paths["pack"],
            campaign_manifest_path=paths["campaign"],
            output_dir=paths["output"],
            expected_alias_count=3,
        )


@pytest.mark.parametrize("failure", ["unknown", "mixed", "duplicate-slot"])
def test_expand_aliases_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    from scripts import gtbi_fast_strict_results as results

    paths = _fixture(tmp_path, monkeypatch)
    aliases = pd.read_csv(paths["alias_map"])
    if failure == "unknown":
        aliases.loc[0, "canonical_strategy_id"] = "unknown-canonical"
    elif failure == "mixed":
        early = pd.read_csv(paths["canonical_root"] / "early_rejected_strategies.csv")
        early = pd.concat(
            [
                early,
                pd.DataFrame(
                    [{"strategy_id": "canonical-ok", "reason": "also-rejected"}]
                ),
            ],
            ignore_index=True,
        )
        early.to_csv(paths["canonical_root"] / "early_rejected_strategies.csv", index=False)
    else:
        aliases.loc[1, "global_slot"] = aliases.loc[0, "global_slot"]
    aliases.to_csv(paths["alias_map"], index=False)

    with pytest.raises(ValueError):
        results.expand_canonical_results(
            canonical_results_root=paths["canonical_root"],
            alias_map_path=paths["alias_map"],
            original_pack_path=paths["pack"],
            campaign_manifest_path=paths["campaign"],
            output_dir=paths["output"],
            expected_alias_count=3,
        )
