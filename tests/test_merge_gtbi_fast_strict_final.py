# mypy: ignore-errors
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts import global_technical_buy_indicator as gtbi
from scripts import gtbi_fast_strict as planner


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha(path),
        "size_bytes": path.stat().st_size,
    }


def _candidate(
    strategy_id: str,
    *,
    shard_id: int,
    slot_in_shard: int,
    stop_loss_pct: float,
    concept_id: str,
) -> gtbi.ExternalStrategyCandidate:
    return gtbi.ExternalStrategyCandidate(
        {
            "strategy_id": strategy_id,
            "shard_id": shard_id,
            "slot_in_shard": slot_in_shard,
            "concept_id": concept_id,
            "market_overlay_id": "market",
            "trend_profile_id": "trend",
            "rs_profile_id": "rs",
            "exit_profile_id": "exit",
            "aggression_id": "normal",
        },
        gtbi.IndicatorConfig(
            family="minervini_sepa",
            stop_loss_pct=stop_loss_pct,
            max_holding_days=30,
        ),
        (),
        (),
    )


def _block(
    root: Path,
    *,
    block_id: int,
    worker_id: int,
    fingerprint: str,
    leaderboard: list[dict[str, object]],
    early_rejected: list[dict[str, object]],
) -> None:
    block = root / f"block-{block_id:02d}"
    block.mkdir(parents=True)
    suffix = f"{block_id:02d}"
    files: list[Path] = []
    for name, rows in (
        ("leaderboard", leaderboard),
        ("early_rejected_strategies", early_rejected),
        ("yearly_trade_performance", [{"candidate_id": "canonical-ok", "split": "validation", "year": 2011, "trades": 2}]),
        ("timing_diagnostics", [{"strategy_id": "canonical-ok", "result_status": "evaluated"}]),
    ):
        path = block / f"{name}_job_block_{suffix}.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        files.append(path)
    summary = block / f"summary_job_block_{suffix}.json"
    summary.write_text(
        json.dumps(
            {
                "campaign_fingerprint": fingerprint,
                "block_id": block_id,
                "worker_ids": [worker_id],
                "total_strategies_loaded": 1,
                "total_strategies_evaluated": len(leaderboard),
                "total_strategies_early_rejected": len(early_rejected),
                "total_strategies_timed_out": 0,
                "total_strategies_runtime_error": 0,
                "total_strategies_unsupported": 0,
                "total_strategies_slow_deferred": 0,
            }
        ),
        encoding="utf-8",
    )
    files.append(summary)
    (block / "block_manifest.json").write_text(
        json.dumps(
            {
                "campaign_fingerprint": fingerprint,
                "block_id": block_id,
                "worker_ids": [worker_id],
                "canonical_group_count": 1,
                "files": [_record(path, block) for path in files],
            }
        ),
        encoding="utf-8",
    )


def _add_block_csv(block: Path, name: str, rows: list[dict[str, object]]) -> None:
    path = block / name
    pd.DataFrame(rows).to_csv(path, index=False)
    manifest_path = block / "block_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(_record(path, block))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _add_block_jsonl(block: Path, name: str, lines: list[str]) -> None:
    path = block / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest_path = block / "block_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(_record(path, block))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _refresh_plan_inventory(plan: Path) -> None:
    campaign_path = plan / "campaign_manifest.json"
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    artifacts = [
        _record(plan / str(record["path"]), plan)
        for record in campaign["artifacts"]
    ]
    artifacts.sort(key=lambda record: str(record["path"]))
    campaign["artifacts"] = artifacts
    campaign["campaign_fingerprint"] = planner.campaign_fingerprint(
        **campaign["inputs"],
        artifact_inventory=artifacts,
        plan_content=campaign["plan_content"],
    )
    campaign_path.write_text(json.dumps(campaign), encoding="utf-8")


def _fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    second_evaluated: bool = False,
    all_early_rejected: bool = False,
) -> dict[str, Path]:
    canonical = _candidate("canonical-ok", shard_id=0, slot_in_shard=0, stop_loss_pct=0.08, concept_id="canonical")
    alias = _candidate("alias-ok", shard_id=1, slot_in_shard=0, stop_loss_pct=0.08, concept_id="alias")
    rejected = _candidate("canonical-reject", shard_id=2, slot_in_shard=0, stop_loss_pct=0.12, concept_id="rejected")
    monkeypatch.setattr(gtbi, "load_external_strategy_candidates", lambda *args, **kwargs: [canonical, alias, rejected])

    plan = tmp_path / "plan"
    plan.mkdir()
    alias_map = plan / "alias_map.csv"
    pd.DataFrame(
        [
            {"strategy_id": "canonical-ok", "evaluation_hash": planner.economic_evaluation_hash(canonical), "signal_hash": planner.signal_evaluation_hash(canonical), "exit_hash": planner.exit_evaluation_hash(canonical), "canonical_strategy_id": "canonical-ok", "source_shard_id": 0, "source_slot_in_shard": 0, "global_slot": 0, "worker_id": 0},
            {"strategy_id": "alias-ok", "evaluation_hash": planner.economic_evaluation_hash(canonical), "signal_hash": planner.signal_evaluation_hash(alias), "exit_hash": planner.exit_evaluation_hash(alias), "canonical_strategy_id": "canonical-ok", "source_shard_id": 1, "source_slot_in_shard": 0, "global_slot": 200, "worker_id": 0},
            {"strategy_id": "canonical-reject", "evaluation_hash": planner.economic_evaluation_hash(rejected), "signal_hash": planner.signal_evaluation_hash(rejected), "exit_hash": planner.exit_evaluation_hash(rejected), "canonical_strategy_id": "canonical-reject", "source_shard_id": 2, "source_slot_in_shard": 0, "global_slot": 400, "worker_id": 1},
        ]
    ).to_csv(alias_map, index=False)
    worker_manifest = plan / "worker_manifest.csv"
    pd.DataFrame(
        [
            {"evaluation_hash": planner.economic_evaluation_hash(canonical), "signal_hash": planner.signal_evaluation_hash(canonical), "exit_hash": planner.exit_evaluation_hash(canonical), "canonical_strategy_id": "canonical-ok", "source_shard_id": 0, "source_slot_in_shard": 0, "global_slot": 0, "worker_id": 0},
            {"evaluation_hash": planner.economic_evaluation_hash(rejected), "signal_hash": planner.signal_evaluation_hash(rejected), "exit_hash": planner.exit_evaluation_hash(rejected), "canonical_strategy_id": "canonical-reject", "source_shard_id": 2, "source_slot_in_shard": 0, "global_slot": 400, "worker_id": 1},
        ]
    ).to_csv(worker_manifest, index=False)
    original_pack = tmp_path / "original-pack"
    original_pack.mkdir()
    (plan / "block_matrix.json").write_text(
        json.dumps({"include": [{"block_id": 0, "worker_ids": [0]}, {"block_id": 1, "worker_ids": [1]}]}),
        encoding="utf-8",
    )
    inputs = {
        "code_sha": "test-code",
        "strategy_pack_digest": planner.strategy_pack_digest(original_pack),
        "data_run_identity": "test-data",
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
        "min_market_cap": 2_000_000_000,
        "execution_mode": "optimized_evaluation_v5_event_first",
        "universe_identity": "test-universe",
        "dependency_lock_identity": "test-lock",
    }
    counts = {"candidate_count": 3, "unique_economic_groups": 2, "worker_count": 2}
    plan_content = {"assignments": {}, "bundle_assignments": {}, "counts": counts}
    artifacts = [_record(alias_map, plan), _record(worker_manifest, plan), _record(plan / "block_matrix.json", plan)]
    artifacts.sort(key=lambda record: str(record["path"]))
    fingerprint = planner.campaign_fingerprint(
        **inputs,
        artifact_inventory=artifacts,
        plan_content=plan_content,
    )
    campaign = {
        "campaign_fingerprint": fingerprint,
        "inputs": inputs,
        "counts": counts,
        "assignments": {},
        "bundle_assignments": {},
        "plan_content": plan_content,
        "artifacts": artifacts,
    }
    (plan / "campaign_manifest.json").write_text(json.dumps(campaign), encoding="utf-8")

    blocks = tmp_path / "blocks"
    _block(
        blocks,
        block_id=0,
        worker_id=0,
        fingerprint=fingerprint,
        leaderboard=[] if all_early_rejected else [{"candidate_id": "canonical-ok", "score": 10.0, "adjusted_return_time_risk": 2.0, "strict_quality_pass": True}],
        early_rejected=[{"strategy_id": "canonical-ok", "reason": "final_filter"}] if all_early_rejected else [],
    )
    _block(
        blocks,
        block_id=1,
        worker_id=1,
        fingerprint=fingerprint,
        leaderboard=[{"candidate_id": "canonical-reject", "score": 20.0, "adjusted_return_time_risk": 7.0, "strict_quality_pass": True}] if second_evaluated else [],
        early_rejected=[] if second_evaluated else [{"strategy_id": "canonical-reject", "reason": "final_filter"}],
    )
    return {"plan": plan, "blocks": blocks, "original_pack": original_pack, "output": tmp_path / "final"}


def test_final_reducer_verifies_provenance_expands_light_rows_and_publishes_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import merge_gtbi_fast_strict_final as final

    paths = _fixture(tmp_path, monkeypatch, second_evaluated=True)
    _add_block_csv(paths["blocks"] / "block-00", "top_trades_sample_job_block_00.csv", [{"candidate_id": "canonical-ok", "return_pct": 2.0}])
    _add_block_csv(paths["blocks"] / "block-00", "family_summary_job_block_00.csv", [{"family": "minervini_sepa", "best_score": 10.0}])
    _add_block_jsonl(paths["blocks"] / "block-00", "top_indicator_rules_job_block_00.jsonl", ['{"candidate_id":"canonical-ok"}'])
    summary = final.merge_final_results(
        plan_root=paths["plan"],
        blocks_root=paths["blocks"],
        original_pack_path=paths["original_pack"],
        output_dir=paths["output"],
        expected_alias_count=3,
        expected_block_count=2,
        expected_worker_count=2,
    )

    aliases = pd.read_csv(paths["output"] / "leaderboard.csv")
    hashes = pd.read_csv(paths["output"] / "dedupe_map.csv")
    heavy_aliases = pd.read_csv(paths["output"] / "canonical_trade_detail_alias_map.csv")
    assert aliases["candidate_id"].tolist() == ["canonical-reject", "alias-ok", "canonical-ok"]
    assert set(hashes) >= {"economic_hash", "canonical_hash", "signal_hash", "exit_hash"}
    assert len(heavy_aliases) == 3
    assert summary["total_terminal_identities"] == 3
    assert summary["train_end"] == "2010-12-31"
    assert summary["min_market_cap"] == 2_000_000_000
    assert summary["best_candidate_id"] == "canonical-reject"
    assert summary["best_adjusted_return_time_risk"] == 7.0
    assert summary["total_jobs_requested"] == 2
    assert summary["total_jobs_completed"] == 2
    assert summary["total_jobs_failed"] == 0
    assert summary["candidate_timeout_seconds"] == 0
    assert summary["optimized_evaluation_mode"] == "optimized_evaluation_v6_fast_strict"
    assert (paths["output"] / "_SUCCESS").is_file()
    assert (paths["output"] / "filtered_leaderboard.csv").is_file()
    assert (paths["output"] / "timing_diagnostics.csv").is_file()
    assert (paths["output"] / "job_manifest.csv").is_file()
    assert (paths["output"] / "top_trades_sample.csv").is_file()
    assert (paths["output"] / "family_summary.csv").is_file()
    assert (paths["output"] / "top_indicator_rules.jsonl").is_file()
    assert not (paths["output"] / "aliases").exists()
    from scripts import validate_gtbi_fast_strict_artifact as validator

    assert validator.validate_artifact(paths["output"], expected_strategy_count=3)["valid"] is True


def test_final_reducer_streams_large_canonical_csvs_without_loading_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import merge_gtbi_fast_strict_final as final

    paths = _fixture(tmp_path, monkeypatch, second_evaluated=True)
    _add_block_csv(
        paths["blocks"] / "block-00",
        "ticker_trade_summary_job_block_00.csv",
        [{"candidate_id": "canonical-ok", "symbol": "AAA", "trades": 2}],
    )
    _add_block_csv(
        paths["blocks"] / "block-01",
        "ticker_trade_summary_job_block_01.csv",
        [{"candidate_id": "canonical-reject", "symbol": "BBB", "trades": 3}],
    )
    original_read = final.results._read_csv

    def guarded_read(path: Path, *args: object, **kwargs: object) -> pd.DataFrame:
        if Path(path).name.startswith("ticker_trade_summary_job_block_"):
            raise AssertionError("large canonical CSV was loaded into memory")
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(final.results, "_read_csv", guarded_read)
    final.merge_final_results(
        plan_root=paths["plan"],
        blocks_root=paths["blocks"],
        original_pack_path=paths["original_pack"],
        output_dir=paths["output"],
        expected_alias_count=3,
        expected_block_count=2,
        expected_worker_count=2,
    )

    streamed = pd.read_csv(paths["output"] / "canonical_results/ticker_trade_summary.csv")
    assert streamed.to_dict("records") == [
        {"candidate_id": "canonical-ok", "symbol": "AAA", "trades": 2},
        {"candidate_id": "canonical-reject", "symbol": "BBB", "trades": 3},
    ]


def test_final_reducer_rejects_worker_repeated_across_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import merge_gtbi_fast_strict_final as final

    paths = _fixture(tmp_path, monkeypatch)
    (paths["plan"] / "block_matrix.json").write_text(
        json.dumps({"include": [{"block_id": 0, "worker_ids": [0, 1]}, {"block_id": 1, "worker_ids": [1]}]}),
        encoding="utf-8",
    )
    block_zero = paths["blocks"] / "block-00" / "block_manifest.json"
    payload = json.loads(block_zero.read_text(encoding="utf-8"))
    payload["worker_ids"] = [0, 1]
    block_zero.write_text(json.dumps(payload), encoding="utf-8")
    _refresh_plan_inventory(paths["plan"])

    with pytest.raises(ValueError, match="exactly once"):
        final.merge_final_results(
            plan_root=paths["plan"],
            blocks_root=paths["blocks"],
            original_pack_path=paths["original_pack"],
            output_dir=paths["output"],
            expected_alias_count=3,
            expected_block_count=2,
            expected_worker_count=2,
        )


def test_final_reducer_rejects_failure_rows_listed_by_a_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import merge_gtbi_fast_strict_final as final

    paths = _fixture(tmp_path, monkeypatch)
    block = paths["blocks"] / "block-00"
    failure = block / "timeout_strategies_job_block_00.csv"
    pd.DataFrame([{"strategy_id": "canonical-ok", "reason": "timeout"}]).to_csv(failure, index=False)
    manifest_path = block / "block_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(_record(failure, block))
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="failure rows"):
        final.merge_final_results(
            plan_root=paths["plan"],
            blocks_root=paths["blocks"],
            original_pack_path=paths["original_pack"],
            output_dir=paths["output"],
            expected_alias_count=3,
            expected_block_count=2,
            expected_worker_count=2,
        )
    assert not paths["output"].exists()


def test_final_reducer_rejects_tampered_recomputable_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import merge_gtbi_fast_strict_final as final

    paths = _fixture(tmp_path, monkeypatch)
    campaign_path = paths["plan"] / "campaign_manifest.json"
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    campaign["plan_content"]["bundle_assignments"] = {"tampered": 0}
    campaign_path.write_text(json.dumps(campaign), encoding="utf-8")

    with pytest.raises(ValueError, match="fingerprint"):
        final.merge_final_results(
            plan_root=paths["plan"],
            blocks_root=paths["blocks"],
            original_pack_path=paths["original_pack"],
            output_dir=paths["output"],
            expected_alias_count=3,
            expected_block_count=2,
            expected_worker_count=2,
        )


def test_final_reducer_allows_all_early_rejected_campaign(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import merge_gtbi_fast_strict_final as final
    from scripts import validate_gtbi_fast_strict_artifact as validator

    paths = _fixture(tmp_path, monkeypatch, all_early_rejected=True)
    summary = final.merge_final_results(
        plan_root=paths["plan"],
        blocks_root=paths["blocks"],
        original_pack_path=paths["original_pack"],
        output_dir=paths["output"],
        expected_alias_count=3,
        expected_block_count=2,
        expected_worker_count=2,
    )

    assert summary["best_candidate_id"] is None
    assert summary["best_adjusted_return_time_risk"] is None
    assert validator.validate_artifact(paths["output"], expected_strategy_count=3)["valid"] is True
