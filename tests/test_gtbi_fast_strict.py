from __future__ import annotations

import csv
import hashlib
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
        "expected_unique_group_count": None,
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
        "expected_unique_group_count": None,
        "worker_count": 2,
    }
    with (tmp_path / "output" / "worker_manifest.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    grouped = next(row for row in rows if row["canonical_strategy_id"] == "representative")
    assert grouped["global_slot"] == "1"


def test_plan_validates_and_records_expected_unique_group_count(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    candidates = [
        _candidate("alias", shard_id=0, slot_in_shard=0),
        _candidate("canonical", shard_id=0, slot_in_shard=1),
        _candidate("second", shard_id=0, slot_in_shard=2, stop_loss_pct=0.12),
        _candidate("third", shard_id=0, slot_in_shard=3, stop_loss_pct=0.14),
    ]
    monkeypatch.setattr(strict.gtbi, "load_external_strategy_candidates", _load_fixture(candidates))

    with pytest.raises(ValueError, match="unique economic group count"):
        strict.create_campaign_plan(**_plan_inputs(tmp_path, expected_unique_group_count=4))

    manifest = strict.create_campaign_plan(
        **_plan_inputs(
            tmp_path,
            output_dir=tmp_path / "valid-output",
            expected_unique_group_count=3,
        )
    )
    assert manifest["counts"]["expected_unique_group_count"] == 3


def test_cli_defaults_to_3600_expected_unique_groups() -> None:
    args = strict._parser().parse_args(
        [
            "pack",
            "output",
            "--data-run-identity",
            "data-run",
            "--universe-identity",
            "universe",
            "--dependency-lock-identity",
            "lock",
        ]
    )

    assert strict.DEFAULT_EXPECTED_UNIQUE_GROUP_COUNT == 3_600
    assert args.expected_unique_group_count == 3_600


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
    assert set(matrix_a) == {"include"}
    assert set(matrix_b) == {"include"}
    assert set(blocks) == {"include"}
    assert [row["worker_id"] for row in matrix_a["include"]] == [0, 1]
    assert matrix_b["include"] == []
    assert blocks["include"] == [{"block_id": 0, "worker_ids": [0, 1]}]


def test_lpt_uses_positive_cost_and_preserves_raw_score(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    candidates = [
        _candidate("positive", shard_id=0, slot_in_shard=0, stop_loss_pct=0.10),
        _candidate("zero", shard_id=0, slot_in_shard=1, stop_loss_pct=0.11),
        _candidate("negative-a", shard_id=0, slot_in_shard=2, stop_loss_pct=0.12),
        _candidate("negative-b", shard_id=0, slot_in_shard=3, stop_loss_pct=0.13),
    ]
    raw_scores = {"positive": 2.0, "zero": 0.0, "negative-a": -5.0, "negative-b": -6.0}

    def estimate(payload: dict[str, object], *, optimized_evaluation_mode: str) -> tuple[float, str]:
        return raw_scores[str(payload["strategy_id"])], "fixture"

    monkeypatch.setattr(strict.gtbi, "load_external_strategy_candidates", _load_fixture(candidates))
    monkeypatch.setattr(strict.gtbi, "_estimated_cost_score", estimate)

    strict.create_campaign_plan(**_plan_inputs(tmp_path))

    with (tmp_path / "output" / "worker_manifest.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert sorted(float(row["raw_cost_score"]) for row in rows) == [-6.0, -5.0, 0.0, 2.0]
    assert sorted(float(row["scheduling_cost"]) for row in rows) == [1.0, 1.0, 1.0, 2.0]
    assert sorted(sum(row["worker_id"] == worker_id for row in rows) for worker_id in {"0", "1"}) == [2, 2]


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
    assert [row["worker_id"] for row in matrix_a["include"]] == list(range(180))
    assert [row["worker_id"] for row in matrix_b["include"]] == list(range(180, 360))
    assert [block["worker_ids"] for block in blocks["include"]] == [
        list(range(start, start + 18)) for start in range(0, 360, 18)
    ]


def test_campaign_manifest_declares_sha256_and_size_for_every_worker_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidates = [
        _candidate("first", shard_id=0, slot_in_shard=0),
        _candidate("second", shard_id=0, slot_in_shard=1, stop_loss_pct=0.12),
    ]
    monkeypatch.setattr(strict.gtbi, "load_external_strategy_candidates", _load_fixture(candidates))

    manifest = strict.create_campaign_plan(
        **_plan_inputs(tmp_path, worker_count=2, expected_strategy_count=2)
    )

    expected_paths = {
        "canonical_pack/strategies_shard_000.jsonl",
        "canonical_pack/strategies_shard_001.jsonl",
        "alias_map.csv",
        "worker_manifest.csv",
        "matrix_a.json",
        "matrix_b.json",
        "block_matrix.json",
    }
    assert {artifact["path"] for artifact in manifest["artifacts"]} == expected_paths
    for artifact in manifest["artifacts"]:
        path = tmp_path / "output" / artifact["path"]
        content = path.read_bytes()
        assert artifact["size_bytes"] == len(content)
        assert artifact["sha256"] == hashlib.sha256(content).hexdigest()


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


@pytest.mark.parametrize(
    "candidate, message",
    [
        (_candidate("", shard_id=0, slot_in_shard=0), "strategy_id must not be empty"),
        (_candidate("bad-shard", shard_id=360, slot_in_shard=0), "source_shard_id"),
        (_candidate("bad-slot", shard_id=0, slot_in_shard=200), "source_slot_in_shard"),
    ],
)
def test_plan_rejects_invalid_source_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    candidate: gtbi.ExternalStrategyCandidate,
    message: str,
) -> None:
    monkeypatch.setattr(strict.gtbi, "load_external_strategy_candidates", _load_fixture([candidate]))

    with pytest.raises(ValueError, match=message):
        strict.create_campaign_plan(**_plan_inputs(tmp_path, worker_count=1, expected_strategy_count=1))


def test_plan_rejects_candidate_with_unsupported_rules(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    candidate = replace(
        _candidate("unsupported", shard_id=0, slot_in_shard=0),
        unsupported_rules=("entry_rules.unknown_rule",),
    )
    monkeypatch.setattr(strict.gtbi, "load_external_strategy_candidates", _load_fixture([candidate]))

    with pytest.raises(ValueError, match="unsupported rules"):
        strict.create_campaign_plan(**_plan_inputs(tmp_path, worker_count=1, expected_strategy_count=1))


def test_plan_rejects_output_directory_that_already_contains_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = _candidate("one", shard_id=0, slot_in_shard=0)
    monkeypatch.setattr(strict.gtbi, "load_external_strategy_candidates", _load_fixture([candidate]))
    output = tmp_path / "output"
    (output / "stale").mkdir(parents=True)
    stale_file = output / "stale" / "old-plan.json"
    stale_file.write_text("stale", encoding="utf-8")

    with pytest.raises(ValueError, match="output directory already contains files"):
        strict.create_campaign_plan(**_plan_inputs(tmp_path, worker_count=1, expected_strategy_count=1))

    assert stale_file.read_text(encoding="utf-8") == "stale"


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
    monkeypatch.setattr(strict.gtbi, "load_external_strategy_candidates", _load_fixture([_candidate("one", shard_id=0, slot_in_shard=0)]))
    with pytest.raises(ValueError, match="candidate count"):
        strict.create_campaign_plan(**_plan_inputs(tmp_path, worker_count=1, expected_strategy_count=2))
    with pytest.raises(ValueError, match="empty"):
        strict.create_campaign_plan(**_plan_inputs(tmp_path, worker_count=2, expected_strategy_count=1))
