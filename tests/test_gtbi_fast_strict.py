from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts import global_technical_buy_indicator as gtbi
from scripts import gtbi_fast_strict as strict


def _candidate(
    strategy_id: str,
    *,
    shard_id: int,
    slot_in_shard: int,
    stop_loss_pct: float = 0.08,
    concept_id: str = "baseline",
    metadata: str = "research-a",
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
        "research_metadata": metadata,
        "exit_rules": {"stop_loss_pct": stop_loss_pct},
    }
    return gtbi.ExternalStrategyCandidate(payload, config, (), ())


def _plan_inputs(tmp_path: Path, **overrides: object) -> dict[str, object]:
    pack = tmp_path / "pack"
    pack.mkdir(exist_ok=True)
    (pack / "fixture.jsonl").write_text("{}\n", encoding="utf-8")
    inputs: dict[str, object] = {
        "pack_path": pack,
        "output_dir": tmp_path / "output",
        "worker_count": 2,
        "expected_strategy_count": 4,
        "code_sha": "code-sha",
        "data_run_identity": "data-run-1",
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
        "min_market_cap": 2_000_000_000,
        "execution_mode": "optimized_evaluation_v5_event_first",
        "universe_identity": "us-equities-v1",
        "dependency_lock_identity": "lock-sha",
    }
    inputs.update(overrides)
    return inputs


def _load_fixture(candidates: list[gtbi.ExternalStrategyCandidate]):
    def load(*args: object, **kwargs: object) -> list[gtbi.ExternalStrategyCandidate]:
        return list(candidates)

    return load


def test_economic_hash_ignores_identity_and_research_metadata() -> None:
    first = _candidate("one", shard_id=0, slot_in_shard=1, metadata="first")
    second = _candidate("two", shard_id=7, slot_in_shard=2, metadata="second")

    assert strict.economic_evaluation_hash(first) == strict.economic_evaluation_hash(second)


def test_economic_hash_changes_when_effective_exit_changes() -> None:
    baseline = _candidate("one", shard_id=0, slot_in_shard=0)
    changed_stop = _candidate("two", shard_id=0, slot_in_shard=1, stop_loss_pct=0.12)
    changed_exit = replace(baseline, config=replace(baseline.config, max_holding_days=31))

    assert strict.economic_evaluation_hash(baseline) != strict.economic_evaluation_hash(changed_stop)
    assert strict.economic_evaluation_hash(baseline) != strict.economic_evaluation_hash(changed_exit)


@pytest.mark.parametrize(
    "changed",
    [
        {"code_sha": "other-code"},
        {"strategy_pack_digest": "other-pack"},
        {"data_run_identity": "other-data"},
        {"train_end": "2010-12-30"},
        {"validation_start": "2011-01-02"},
        {"validation_end": "2020-12-30"},
        {"locked_start": "2021-01-02"},
        {"min_market_cap": 3_000_000_000},
        {"execution_mode": "other-mode"},
        {"universe_identity": "other-universe"},
        {"dependency_lock_identity": "other-lock"},
    ],
)
def test_campaign_fingerprint_changes_for_every_bound_input(changed: dict[str, object]) -> None:
    base = {
        "code_sha": "code-sha",
        "strategy_pack_digest": "pack-sha",
        "data_run_identity": "data-run-1",
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
        "min_market_cap": 2_000_000_000,
        "execution_mode": "optimized_evaluation_v5_event_first",
        "universe_identity": "us-equities-v1",
        "dependency_lock_identity": "lock-sha",
    }

    assert strict.campaign_fingerprint(**base) != strict.campaign_fingerprint(**(base | changed))


def test_strategy_pack_digest_uses_sorted_relative_paths_and_bytes(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    (pack / "z").mkdir(parents=True)
    (pack / "a").mkdir()
    (pack / "z" / "row.jsonl").write_bytes(b"z")
    (pack / "a" / "row.jsonl").write_bytes(b"a")

    digest = strict.strategy_pack_digest(pack)
    (pack / "a" / "row.jsonl").write_bytes(b"changed")

    assert digest != strict.strategy_pack_digest(pack)


def test_plan_groups_deterministically_and_keeps_lowest_global_slot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    candidates = [
        _candidate("late", shard_id=0, slot_in_shard=4),
        _candidate("representative", shard_id=0, slot_in_shard=1),
        _candidate("other", shard_id=1, slot_in_shard=0, stop_loss_pct=0.12),
        _candidate("third", shard_id=1, slot_in_shard=1, stop_loss_pct=0.14),
    ]
    monkeypatch.setattr(strict.gtbi, "load_external_strategy_candidates", _load_fixture(candidates))

    manifest = strict.create_campaign_plan(**_plan_inputs(tmp_path))

    assert manifest["counts"] == {
        "candidate_count": 4,
        "unique_economic_groups": 3,
        "worker_count": 2,
    }
    with (tmp_path / "output" / "worker_manifest.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    grouped = next(row for row in rows if row["canonical_strategy_id"] == "representative")
    assert grouped["global_slot"] == "1"


def test_plan_uses_deterministic_lpt_and_exact_matrix_boundaries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    candidates = [
        _candidate("slow", shard_id=0, slot_in_shard=0, concept_id="q_stair_step_reclaim"),
        _candidate("medium", shard_id=0, slot_in_shard=1, concept_id="keltner_pullback_reclaim", stop_loss_pct=0.10),
        _candidate("fast", shard_id=0, slot_in_shard=2, concept_id="baseline", stop_loss_pct=0.12),
        _candidate("other", shard_id=0, slot_in_shard=3, concept_id="baseline", stop_loss_pct=0.14),
    ]
    monkeypatch.setattr(strict.gtbi, "load_external_strategy_candidates", _load_fixture(candidates))

    first = strict.create_campaign_plan(**_plan_inputs(tmp_path))
    second = strict.create_campaign_plan(**_plan_inputs(tmp_path, output_dir=tmp_path / "output-second"))

    assert first["assignments"] == second["assignments"]
    assert first["assignments"][strict.economic_evaluation_hash(candidates[0])] == 0
    matrix_a = json.loads((tmp_path / "output" / "matrix_a.json").read_text(encoding="utf-8"))
    matrix_b = json.loads((tmp_path / "output" / "matrix_b.json").read_text(encoding="utf-8"))
    blocks = json.loads((tmp_path / "output" / "block_matrix.json").read_text(encoding="utf-8"))
    assert [row["worker_id"] for row in matrix_a["workers"]] == [0, 1]
    assert matrix_b["workers"] == []
    assert blocks["blocks"] == [{"block_id": 0, "worker_ids": [0, 1]}]


def test_default_matrix_and_block_boundaries_cover_all_360_workers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    candidates = [
        _candidate(f"strategy-{index}", shard_id=index // 200, slot_in_shard=index % 200, stop_loss_pct=0.01 + index / 1_000)
        for index in range(360)
    ]
    monkeypatch.setattr(strict.gtbi, "load_external_strategy_candidates", _load_fixture(candidates))

    strict.create_campaign_plan(**_plan_inputs(tmp_path, worker_count=360, expected_strategy_count=360))

    matrix_a = json.loads((tmp_path / "output" / "matrix_a.json").read_text(encoding="utf-8"))
    matrix_b = json.loads((tmp_path / "output" / "matrix_b.json").read_text(encoding="utf-8"))
    blocks = json.loads((tmp_path / "output" / "block_matrix.json").read_text(encoding="utf-8"))
    assert [row["worker_id"] for row in matrix_a["workers"]] == list(range(180))
    assert [row["worker_id"] for row in matrix_b["workers"]] == list(range(180, 360))
    assert [block["worker_ids"] for block in blocks["blocks"]] == [list(range(start, start + 18)) for start in range(0, 360, 18)]


@pytest.mark.parametrize(
    "candidates, message",
    [
        ([_candidate("duplicate", shard_id=0, slot_in_shard=0), _candidate("duplicate", shard_id=0, slot_in_shard=1)], "duplicate strategy_id"),
        ([_candidate("one", shard_id=0, slot_in_shard=0), _candidate("two", shard_id=0, slot_in_shard=0)], "duplicate global_slot"),
    ],
)
def test_plan_rejects_duplicate_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, candidates: list[gtbi.ExternalStrategyCandidate], message: str) -> None:
    monkeypatch.setattr(strict.gtbi, "load_external_strategy_candidates", _load_fixture(candidates))

    with pytest.raises(ValueError, match=message):
        strict.create_campaign_plan(**_plan_inputs(tmp_path, worker_count=1, expected_strategy_count=2))


def test_plan_preserves_source_identity_in_canonical_payload_and_alias_map(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    candidates = [
        _candidate("canonical", shard_id=3, slot_in_shard=7),
        _candidate("second", shard_id=3, slot_in_shard=8, stop_loss_pct=0.12),
    ]
    monkeypatch.setattr(strict.gtbi, "load_external_strategy_candidates", _load_fixture(candidates))

    strict.create_campaign_plan(**_plan_inputs(tmp_path, worker_count=2, expected_strategy_count=2))

    rows = []
    for path in sorted((tmp_path / "output" / "canonical_pack").glob("*.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    canonical = next(row for row in rows if row["strategy_id"] == "canonical")
    assert canonical["source_shard_id"] == 3
    assert canonical["source_slot_in_shard"] == 7
    assert canonical["shard_id"] in {0, 1}
    assert canonical["slot_in_shard"] == 0
    with (tmp_path / "output" / "alias_map.csv").open(newline="", encoding="utf-8") as handle:
        aliases = list(csv.DictReader(handle))
    assert aliases[0].keys() == {
        "strategy_id",
        "evaluation_hash",
        "canonical_strategy_id",
        "source_shard_id",
        "source_slot_in_shard",
        "global_slot",
        "worker_id",
    }


def test_plan_rejects_wrong_candidate_count_empty_worker_and_out_of_range_slot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(strict.gtbi, "load_external_strategy_candidates", _load_fixture([_candidate("one", shard_id=0, slot_in_shard=72_000)]))
    with pytest.raises(ValueError, match="source_slot_in_shard"):
        strict.create_campaign_plan(**_plan_inputs(tmp_path, worker_count=1, expected_strategy_count=1))

    monkeypatch.setattr(strict.gtbi, "load_external_strategy_candidates", _load_fixture([_candidate("one", shard_id=0, slot_in_shard=0)]))
    with pytest.raises(ValueError, match="candidate count"):
        strict.create_campaign_plan(**_plan_inputs(tmp_path, worker_count=1, expected_strategy_count=2))
    with pytest.raises(ValueError, match="empty"):
        strict.create_campaign_plan(**_plan_inputs(tmp_path, worker_count=2, expected_strategy_count=1))
