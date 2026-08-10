from __future__ import annotations

import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "config" / "sp500_megarun_dehb_campaign_v1.json"


def test_campaign_contract_freezes_exact_inputs_and_closed_boundaries() -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_contract import (
        load_and_validate_campaign_contract,
    )

    contract = load_and_validate_campaign_contract(CONTRACT_PATH)

    assert contract.data_contract_file_sha256 == (
        "9b2a971c1d1ad0374ad63e03e03c91127bf634e0ed822195c06180140acfa2c8"
    )
    assert contract.feature_contract_sha256 == (
        "58dd6dba2857223c2040ef383b7ec0513b957675f4ba104ffc408ab5f47ad62c"
    )
    assert contract.dehb_lock_domain_sha256 == (
        "89617c4ca6fe54739804e039177c61b8a62933b921cd65617d93fce634a06734"
    )
    assert contract.train_source_run_id == "31354839628"
    assert contract.train_partition == "train_snapshot_1993_2010"
    assert contract.search_start == "1998-01-01"
    assert contract.search_end == "2010-12-31"
    assert contract.validation_opened is False
    assert contract.locked_opened is False
    assert contract.validation_partition_mounted is False
    assert contract.locked_partition_mounted is False


def test_campaign_schedule_is_exactly_720_unique_islands_in_360_jobs() -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_contract import (
        build_island_schedule,
        load_and_validate_campaign_contract,
    )

    contract = load_and_validate_campaign_contract(CONTRACT_PATH)
    schedule = build_island_schedule(contract)
    islands = [island for job in schedule for island in job.islands]

    assert len(schedule) == 360
    assert {job.shard_id for job in schedule} == {"A", "B", "C"}
    assert all(sum(job.shard_id == shard for job in schedule) == 120 for shard in "ABC")
    assert all(len(job.islands) == 2 for job in schedule)
    assert len(islands) == 720
    assert len({island.island_id for island in islands}) == 720
    assert len({island.seed for island in islands}) == 720
    assert all(0 <= island.seed < 2**32 for island in islands)
    assert {island.lane_id for island in islands} == {
        f"F{index:03d}" for index in range(1, 241)
    }
    assert all(
        sum(island.lane_id == lane_id for island in islands) == 3
        for lane_id in {island.lane_id for island in islands}
    )
    assert all(island.n_workers == 4 for island in islands)


def test_fidelities_are_exact_nested_and_full_fidelity_covers_every_train_year() -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_contract import (
        load_and_validate_campaign_contract,
    )

    contract = load_and_validate_campaign_contract(CONTRACT_PATH)

    assert tuple(item.budget for item in contract.fidelities) == (1, 3, 9, 27)
    assert contract.eta == 3
    for previous, current in zip(contract.fidelities, contract.fidelities[1:]):
        assert set(previous.years) < set(current.years)
        assert previous.bootstrap_paths < current.bootstrap_paths
    assert contract.fidelities[-1].years == tuple(range(1998, 2011))
    assert contract.fidelities[-1].bootstrap_paths == 2048
    assert contract.fidelities[-1].parameter_neighbors == 24
    assert contract.fidelities[-1].temporal_perturbations == 5


def test_objective_and_plateau_policy_match_the_requested_scientific_order() -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_contract import (
        load_and_validate_campaign_contract,
        plateau_action,
    )

    contract = load_and_validate_campaign_contract(CONTRACT_PATH)

    assert contract.annual_gates == (
        "strategy_total_return_gt_zero",
        "strategy_total_return_gt_spy",
    )
    assert contract.objective_order == (
        "annual_gate_feasibility",
        "annualized_strategy_return",
        "weekly_spy_beat_rate",
        "annualized_alpha",
    )
    assert contract.no_global_time_limit is True
    assert contract.terminal_no_strategy_allowed is False
    assert contract.island_slice_minutes == 135
    assert contract.job_timeout_minutes == 330
    assert contract.island_slice_minutes * 2 + contract.setup_and_upload_reserve_minutes <= contract.job_timeout_minutes
    assert plateau_action(
        contract,
        completed_since_improvement=127,
        minutes_since_improvement=1_000,
    ) == "continue_population"
    assert plateau_action(
        contract,
        completed_since_improvement=512,
        minutes_since_improvement=30,
    ) == "checkpoint_and_restart_diverse_population"
    assert plateau_action(
        contract,
        completed_since_improvement=128,
        minutes_since_improvement=120,
    ) == "checkpoint_and_restart_diverse_population"

    forbidden = {"sharpe", "drawdown", "cost"}
    gate_text = " ".join(contract.annual_gates).lower()
    assert not any(name in gate_text for name in forbidden)


def test_contract_rejects_open_or_mounted_validation_and_locked_data(tmp_path: Path) -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_contract import (
        CampaignContractError,
        load_and_validate_campaign_contract,
    )

    original = json.loads(CONTRACT_PATH.read_text("utf-8"))
    mutations = (
        ("validation_opened", True),
        ("locked_opened", True),
        ("validation_partition_mounted", True),
        ("locked_partition_mounted", True),
    )
    for field, value in mutations:
        payload = json.loads(json.dumps(original))
        payload["boundaries"][field] = value
        path = tmp_path / f"{field}.json"
        path.write_text(json.dumps(payload), "utf-8")
        with pytest.raises(CampaignContractError, match="BOUNDARY_MUST_REMAIN_CLOSED"):
            load_and_validate_campaign_contract(path)


def test_campaign_manifest_is_deterministic_and_hash_bound() -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_contract import (
        build_campaign_manifest,
        load_and_validate_campaign_contract,
    )

    contract = load_and_validate_campaign_contract(CONTRACT_PATH)
    first = build_campaign_manifest(contract)
    second = build_campaign_manifest(contract)

    assert first == second
    assert first["campaign_contract_sha256"] == contract.sha256
    assert len(first["manifest_sha256"]) == 64
    assert first["job_count"] == 360
    assert first["island_count"] == 720
    assert first["validation_opened"] is False
    assert first["locked_opened"] is False


def test_campaign_bindings_match_the_actual_frozen_repository_files() -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_contract import (
        load_and_validate_campaign_contract,
        validate_campaign_bindings,
    )

    contract = load_and_validate_campaign_contract(CONTRACT_PATH)
    receipt = validate_campaign_bindings(contract, repo_root=REPO_ROOT)

    assert receipt["verified"] is True
    assert receipt["data_contract_file_sha256"] == contract.data_contract_file_sha256
    assert receipt["data_contract_canonical_sha256"] == contract.data_contract_canonical_sha256
    assert receipt["feature_contract_sha256"] == contract.feature_contract_sha256
    assert receipt["dehb_lock_domain_sha256"] == contract.dehb_lock_domain_sha256
