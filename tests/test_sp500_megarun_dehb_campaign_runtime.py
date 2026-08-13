from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "config" / "sp500_megarun_dehb_campaign_v1.json"


@pytest.fixture(scope="module")
def campaign():
    from aurora.infra.sp500_megarun.dehb_campaign_contract import (
        load_and_validate_campaign_contract,
    )

    return load_and_validate_campaign_contract(CONTRACT_PATH)


def test_shard_matrices_cover_360_jobs_once(campaign) -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_runtime import build_shard_matrices

    matrices = build_shard_matrices(campaign)
    rows = [row for shard in "ABC" for row in matrices[shard]["include"]]

    assert {key: len(value["include"]) for key, value in matrices.items()} == {
        "A": 120,
        "B": 120,
        "C": 120,
    }
    assert sorted(row["job_index"] for row in rows) == list(range(360))
    assert len({row["job_id"] for row in rows}) == 360
    assert all(row["shard_id"] in "ABC" for row in rows)
    assert all(len(row["islands"]) == 2 for row in rows)
    assert all(island["n_workers"] == 4 for row in rows for island in row["islands"])


def test_restart_payload_is_deterministic_diverse_and_closed(campaign) -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_runtime import build_job_payload

    original = build_job_payload(campaign, job_index=17, wave=0, restart_ordinal=0)
    repeated = build_job_payload(campaign, job_index=17, wave=0, restart_ordinal=0)
    restarted = build_job_payload(campaign, job_index=17, wave=1, restart_ordinal=1)

    assert original == repeated
    assert original["job_id"] == "J018"
    assert original["validation_opened"] is False
    assert original["locked_opened"] is False
    assert original["train_partition"] == "train_snapshot_1993_2010"
    assert len(original["payload_sha256"]) == 64
    assert [row["restart_seed"] for row in original["islands"]] != [
        row["restart_seed"] for row in restarted["islands"]
    ]
    assert all(0 <= row["restart_seed"] < 2**32 for row in restarted["islands"])


def test_job_payload_binds_the_exact_launch_contract(campaign) -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_runtime import build_job_payload

    launch_sha256 = "f" * 64
    payload = build_job_payload(
        campaign,
        job_index=0,
        wave=0,
        restart_ordinal=0,
        launch_contract_sha256=launch_sha256,
    )

    assert payload["launch_contract_sha256"] == launch_sha256
    assert len(payload["payload_sha256"]) == 64


def test_next_wave_matrix_can_resume_one_island_and_restart_another(campaign) -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_runtime import build_shard_matrices

    initial = build_shard_matrices(campaign, wave=0, restart_ordinal=0)
    resumed = build_shard_matrices(
        campaign,
        wave=1,
        restart_ordinal=1,
        island_restart_ordinals={"F001-R1": 0},
        resume_island_ids={"F001-R1"},
    )
    first_initial = initial["A"]["include"][0]
    first_resumed = resumed["A"]["include"][0]
    old = next(row for row in first_initial["islands"] if row["island_id"] == "F001-R1")
    continued = next(row for row in first_resumed["islands"] if row["island_id"] == "F001-R1")
    restarted = next(row for row in first_resumed["islands"] if row["island_id"] != "F001-R1")

    assert continued["restart_ordinal"] == 0
    assert continued["restart_seed"] == old["restart_seed"]
    assert continued["resume_from_previous_wave"] is True
    assert restarted["restart_ordinal"] == 1
    assert restarted["resume_from_previous_wave"] is False


def test_append_only_event_ledger_verifies_chain_and_detects_tampering(
    campaign,
    tmp_path: Path,
) -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_runtime import (
        append_ledger_event,
        verify_event_ledger,
    )

    ledger = tmp_path / "events.jsonl"
    first = append_ledger_event(
        ledger,
        campaign_sha256=campaign.sha256,
        event={"type": "island_started", "island_id": "F001-R1"},
    )
    second = append_ledger_event(
        ledger,
        campaign_sha256=campaign.sha256,
        event={"type": "checkpoint_saved", "evaluations": 128},
    )

    verified = verify_event_ledger(ledger, campaign_sha256=campaign.sha256)
    assert verified["record_count"] == 2
    assert verified["tail_hash"] == second["event_hash"]
    assert second["previous_hash"] == first["event_hash"]

    rows = ledger.read_text("utf-8").splitlines()
    changed = json.loads(rows[0])
    changed["event"]["island_id"] = "F999-R9"
    rows[0] = json.dumps(changed, sort_keys=True)
    ledger.write_text("\n".join(rows) + "\n", "utf-8")
    with pytest.raises(ValueError, match="LEDGER_EVENT_HASH_MISMATCH"):
        verify_event_ledger(ledger, campaign_sha256=campaign.sha256)


def _worker_result(
    campaign,
    *,
    job_index: int,
    wave: int = 0,
    fingerprint: str | None = None,
    replicate_override: int | None = None,
) -> dict[str, Any]:
    from aurora.infra.sp500_megarun.dehb_campaign_runtime import build_job_payload

    payload = build_job_payload(
        campaign,
        job_index=job_index,
        wave=wave,
        restart_ordinal=wave,
    )
    islands = []
    for assignment in payload["islands"]:
        replicate = int(assignment["replicate"])
        if replicate_override is not None:
            replicate = replicate_override
        islands.append(
            {
                "island_id": assignment["island_id"],
                "lane_id": assignment["lane_id"],
                "replicate": replicate,
                "restart_ordinal": assignment["restart_ordinal"],
                "status": "completed",
                "evaluations": 640,
                "full_fidelity_evaluations": 3,
                "physical_evaluations": 200,
                "full_fidelity_physical_evaluations": 2,
                "cache_hits": 440,
                "determinism_audit_passed": True,
                "determinism_audit_physical_evaluations": 2,
                "checkpoint_sha256": "a" * 64,
                "champion": None
                if fingerprint is None
                else {
                    "strategy_fingerprint": fingerprint,
                    "full_fidelity": True,
                    "train_feasible": True,
                    "robustness_passed": True,
                    "archive_key": [0.0, -0.25, -0.60, -0.15],
                    "annualized_strategy_return": 0.25,
                    "weekly_spy_beat_rate": 0.60,
                },
            }
        )
    return {
        "schema_version": 1,
        "campaign_contract_sha256": campaign.sha256,
        "job_payload_sha256": payload["payload_sha256"],
        "job_id": payload["job_id"],
        "job_index": payload["job_index"],
        "wave": wave,
        "validation_opened": False,
        "locked_opened": False,
        "islands": islands,
    }


def test_controller_retries_missing_or_failed_jobs(campaign) -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_runtime import controller_decision

    results = [_worker_result(campaign, job_index=index) for index in range(359)]
    decision = controller_decision(campaign, results, wave=0)

    assert decision["action"] == "retry_jobs"
    assert decision["retry_job_indices"] == [359]
    assert decision["terminal_no_strategy"] is False


def test_controller_opens_diverse_next_wave_instead_of_no_strategy(campaign) -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_runtime import controller_decision

    results = [_worker_result(campaign, job_index=index, wave=4) for index in range(360)]
    decision = controller_decision(campaign, results, wave=4)

    assert decision["action"] == "dispatch_next_wave"
    assert decision["next_wave"] == 5
    assert decision["next_restart_ordinal"] == 5
    assert decision["terminal_no_strategy"] is False


def test_controller_resumes_sliced_population_but_restarts_plateaued_ones(campaign) -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_runtime import controller_decision

    results = [_worker_result(campaign, job_index=index) for index in range(360)]
    paused_island = str(results[0]["islands"][0]["island_id"])
    plateaued_island = str(results[0]["islands"][1]["island_id"])
    results[0]["islands"][0]["status"] = "paused_at_runner_slice"
    results[0]["islands"][0]["full_fidelity_evaluations"] = 0
    results[0]["islands"][0]["full_fidelity_physical_evaluations"] = 0
    decision = controller_decision(campaign, results, wave=0)

    assert decision["action"] == "dispatch_next_wave"
    assert paused_island in decision["resume_island_ids"]
    assert decision["next_island_restart_ordinals"][paused_island] == 0
    assert plateaued_island not in decision["resume_island_ids"]
    assert decision["next_island_restart_ordinals"][plateaued_island] == 1
    assert decision["terminal_no_strategy"] is False


def test_controller_never_freezes_from_local_champions_without_global_review(
    campaign,
) -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_runtime import controller_decision

    results = [_worker_result(campaign, job_index=index) for index in range(360)]
    # F001-R1 lives in J001 and F001-R3 in J121 under the frozen pairing.
    results[0] = _worker_result(campaign, job_index=0, fingerprint="winner")
    results[120] = _worker_result(campaign, job_index=120, fingerprint="winner")
    decision = controller_decision(campaign, results, wave=0)

    assert decision["action"] == "dispatch_next_wave"
    assert decision["validation_opened"] is False
    assert decision["locked_opened"] is False


def test_controller_global_gate_cannot_freeze_with_pending_60_gate_matrix(campaign) -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_runtime import controller_decision

    results = [_worker_result(campaign, job_index=index) for index in range(360)]
    decision = controller_decision(
        campaign,
        results,
        wave=0,
        global_robustness={
            "campaign_contract_sha256": campaign.sha256,
            "eligible_finalists": [
                {
                    "strategy_fingerprint": "winner",
                    "position_fingerprint": "p" * 64,
                    "lane_id": "F001",
                    "archive_key": [0.0, -0.2, -0.6, -0.1],
                    "seed_consensus": 3,
                    "supporting_islands": ["F001-R1", "F001-R2", "F001-R3"],
                    "all_60_gates_passed": False,
                    "train_freeze_eligible": False,
                }
            ],
            "validation_opened": False,
            "locked_opened": False,
        },
    )
    assert decision["action"] == "dispatch_next_wave"
    assert decision["terminal_no_strategy"] is False


def test_controller_freezes_only_after_all_train_gates_and_global_review(campaign) -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_runtime import controller_decision

    results = [_worker_result(campaign, job_index=index) for index in range(360)]
    decision = controller_decision(
        campaign,
        results,
        wave=0,
        global_robustness={
            "campaign_contract_sha256": campaign.sha256,
            "eligible_finalists": [
                {
                    "strategy_fingerprint": "winner",
                    "position_fingerprint": "p" * 64,
                    "lane_id": "F001",
                    "archive_key": [0.0, -0.2, -0.6, -0.1],
                    "seed_consensus": 3,
                    "supporting_islands": ["F001-R1", "F001-R2", "F001-R3"],
                    "all_60_gates_passed": False,
                    "train_freeze_eligible": True,
                }
            ],
            "validation_opened": False,
            "locked_opened": False,
        },
    )

    assert decision["action"] == "freeze_train_candidate"
    assert decision["strategy_fingerprint"] == "winner"
    assert decision["train_robustness_gates_passed"] is True
    assert decision["validation_gates_49_54_pending"] is True
    assert decision["validation_opened"] is False
    assert decision["locked_opened"] is False


def test_checkpoint_envelope_is_bound_to_campaign_island_and_closed_data(campaign) -> None:
    from aurora.infra.sp500_megarun.dehb_campaign_runtime import (
        build_checkpoint_envelope,
        validate_checkpoint_envelope,
    )

    envelope = build_checkpoint_envelope(
        campaign,
        island_id="F001-R1",
        wave=3,
        restart_ordinal=3,
        evaluations=256,
        dehb_state_sha256="b" * 64,
        ledger_tail_hash="c" * 64,
        launch_contract_sha256="d" * 64,
    )

    validate_checkpoint_envelope(
        campaign,
        envelope,
        expected_island_id="F001-R1",
        expected_launch_contract_sha256="d" * 64,
    )
    assert envelope["validation_opened"] is False
    assert envelope["locked_opened"] is False
    assert len(envelope["checkpoint_envelope_sha256"]) == 64

    changed = dict(envelope)
    changed["validation_opened"] = True
    with pytest.raises(ValueError, match="CHECKPOINT_BOUNDARY_OPEN"):
        validate_checkpoint_envelope(campaign, changed, expected_island_id="F001-R1")

    with pytest.raises(ValueError, match="CHECKPOINT_LAUNCH_CONTRACT_MISMATCH"):
        validate_checkpoint_envelope(
            campaign,
            envelope,
            expected_island_id="F001-R1",
            expected_launch_contract_sha256="e" * 64,
        )
