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


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    canonical = _candidate("canonical-ok", shard_id=0, slot_in_shard=0, stop_loss_pct=0.08, concept_id="canonical")
    alias = _candidate("alias-ok", shard_id=1, slot_in_shard=0, stop_loss_pct=0.08, concept_id="alias")
    rejected = _candidate("canonical-reject", shard_id=2, slot_in_shard=0, stop_loss_pct=0.12, concept_id="rejected")
    monkeypatch.setattr(gtbi, "load_external_strategy_candidates", lambda *args, **kwargs: [canonical, alias, rejected])

    plan = tmp_path / "plan"
    plan.mkdir()
    alias_map = plan / "alias_map.csv"
    pd.DataFrame(
        [
            {"strategy_id": "canonical-ok", "evaluation_hash": planner.economic_evaluation_hash(canonical), "canonical_strategy_id": "canonical-ok", "source_shard_id": 0, "source_slot_in_shard": 0, "global_slot": 0, "worker_id": 0},
            {"strategy_id": "alias-ok", "evaluation_hash": planner.economic_evaluation_hash(canonical), "canonical_strategy_id": "canonical-ok", "source_shard_id": 1, "source_slot_in_shard": 0, "global_slot": 200, "worker_id": 0},
            {"strategy_id": "canonical-reject", "evaluation_hash": planner.economic_evaluation_hash(rejected), "canonical_strategy_id": "canonical-reject", "source_shard_id": 2, "source_slot_in_shard": 0, "global_slot": 400, "worker_id": 1},
        ]
    ).to_csv(alias_map, index=False)
    worker_manifest = plan / "worker_manifest.csv"
    pd.DataFrame(
        [
            {"evaluation_hash": planner.economic_evaluation_hash(canonical), "canonical_strategy_id": "canonical-ok", "source_shard_id": 0, "source_slot_in_shard": 0, "global_slot": 0, "worker_id": 0},
            {"evaluation_hash": planner.economic_evaluation_hash(rejected), "canonical_strategy_id": "canonical-reject", "source_shard_id": 2, "source_slot_in_shard": 0, "global_slot": 400, "worker_id": 1},
        ]
    ).to_csv(worker_manifest, index=False)
    original_pack = tmp_path / "original-pack"
    original_pack.mkdir()
    fingerprint = "campaign-fingerprint"
    campaign = {
        "campaign_fingerprint": fingerprint,
        "inputs": {
            "strategy_pack_digest": planner.strategy_pack_digest(original_pack),
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "locked_start": "2021-01-01",
            "min_market_cap": 2_000_000_000,
        },
        "counts": {"candidate_count": 3, "unique_economic_groups": 2, "worker_count": 2},
        "artifacts": [_record(alias_map, plan), _record(worker_manifest, plan)],
    }
    (plan / "campaign_manifest.json").write_text(json.dumps(campaign), encoding="utf-8")
    (plan / "block_matrix.json").write_text(
        json.dumps({"include": [{"block_id": 0, "worker_ids": [0]}, {"block_id": 1, "worker_ids": [1]}]}),
        encoding="utf-8",
    )

    blocks = tmp_path / "blocks"
    _block(
        blocks,
        block_id=0,
        worker_id=0,
        fingerprint=fingerprint,
        leaderboard=[{"candidate_id": "canonical-ok", "score": 10.0, "strict_quality_pass": True}],
        early_rejected=[],
    )
    _block(
        blocks,
        block_id=1,
        worker_id=1,
        fingerprint=fingerprint,
        leaderboard=[],
        early_rejected=[{"strategy_id": "canonical-reject", "reason": "final_filter"}],
    )
    return {"plan": plan, "blocks": blocks, "original_pack": original_pack, "output": tmp_path / "final"}


def test_final_reducer_verifies_provenance_expands_light_rows_and_publishes_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import merge_gtbi_fast_strict_final as final

    paths = _fixture(tmp_path, monkeypatch)
    summary = final.merge_final_results(
        plan_root=paths["plan"],
        blocks_root=paths["blocks"],
        original_pack_path=paths["original_pack"],
        output_dir=paths["output"],
        expected_alias_count=3,
        expected_block_count=2,
        expected_worker_count=2,
    )

    aliases = pd.read_csv(paths["output"] / "aliases" / "leaderboard_job_aliases.csv")
    hashes = pd.read_csv(paths["output"] / "aliases" / "dedupe_map_job_aliases.csv")
    heavy_aliases = pd.read_csv(paths["output"] / "canonical_trade_detail_alias_map.csv")
    assert set(aliases["candidate_id"]) == {"canonical-ok", "alias-ok"}
    assert set(hashes) >= {"economic_hash", "canonical_hash", "signal_hash", "exit_hash"}
    assert len(heavy_aliases) == 3
    assert summary["total_terminal_identities"] == 3
    assert summary["train_end"] == "2010-12-31"
    assert summary["min_market_cap"] == 2_000_000_000
    assert (paths["output"] / "_SUCCESS").is_file()
    from scripts import validate_gtbi_fast_strict_artifact as validator

    assert validator.validate_artifact(paths["output"], expected_strategy_count=3)["valid"] is True


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
