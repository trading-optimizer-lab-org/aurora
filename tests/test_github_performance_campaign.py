from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aurora.infra.github_performance.campaign import (
    CampaignPhase,
    CampaignStateIntegrityError,
    CampaignTransitionError,
    assert_recovery_protocol_compatible,
    begin_merge_only,
    initialize_campaign_state,
    load_latest_campaign_state,
    replan_campaign_state,
    resume_campaign_state,
    transition_campaign_state,
    write_campaign_state,
)


NOW = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
SHA = {
    "spec": "1" * 64,
    "units": "2" * 64,
    "completed": "3" * 64,
    "plan": "4" * 64,
    "request": "5" * 64,
    "protocol": "6" * 64,
    "decision": "7" * 64,
    "components": "8" * 64,
    "failures": "9" * 64,
    "replan": "a" * 64,
}


def _initial():
    return initialize_campaign_state(
        campaign_id="campaign-1",
        scientific_contract_sha256=SHA["spec"],
        logical_unit_manifest_sha256=SHA["units"],
        logical_unit_count=10,
        active_plan_sha256=SHA["plan"],
        authority_id="authority-1",
        request_sha256=SHA["request"],
        protected_commit_sha="b" * 40,
        execution_protocol_sha256=SHA["protocol"],
        controller_decision_sha256=SHA["decision"],
        component_store_manifest_sha256=SHA["components"],
        failure_history_manifest_sha256=SHA["failures"],
        created_at=NOW,
    )


def _executing():
    return transition_campaign_state(
        _initial(),
        phase=CampaignPhase.EXECUTING,
        created_at=NOW,
    )


def _replanning():
    recovering = transition_campaign_state(
        _executing(),
        phase=CampaignPhase.RECOVERING,
        completed_unit_count=4,
        completed_unit_manifest_sha256=SHA["completed"],
        pending_unit_count=6,
        created_at=NOW,
    )
    return transition_campaign_state(
        recovering,
        phase=CampaignPhase.REPLANNING,
        created_at=NOW,
    )


def test_campaign_state_versions_are_monotonic_and_immutable(
    tmp_path: Path,
) -> None:
    initial = _initial()
    first = write_campaign_state(initial, tmp_path)
    executing = transition_campaign_state(
        initial,
        phase=CampaignPhase.EXECUTING,
        created_at=NOW,
    )
    second = write_campaign_state(executing, tmp_path)

    assert first.name == "campaign_state_v000000.json"
    assert second.name == "campaign_state_v000001.json"
    assert load_latest_campaign_state(tmp_path) == executing
    with pytest.raises(
        CampaignStateIntegrityError,
        match="immutable state already exists",
    ):
        write_campaign_state(executing, tmp_path)


def test_campaign_latest_pointer_hash_is_verified(tmp_path: Path) -> None:
    write_campaign_state(_initial(), tmp_path)
    pointer_path = tmp_path / "campaign_state_latest.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["state_sha256"] = "f" * 64
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")

    with pytest.raises(
        CampaignStateIntegrityError,
        match="state hash mismatch",
    ):
        load_latest_campaign_state(tmp_path)


def test_resume_repairs_interruption_after_immutable_state_write(
    tmp_path: Path,
) -> None:
    initial = _initial()
    write_campaign_state(initial, tmp_path)
    executing = transition_campaign_state(
        initial,
        phase=CampaignPhase.EXECUTING,
        created_at=NOW,
    )
    orphan = tmp_path / "campaign_state_v000001.json"
    orphan.write_text(
        executing.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    resumed = resume_campaign_state(tmp_path, campaign_id="campaign-1")

    assert resumed == executing
    assert load_latest_campaign_state(tmp_path) == executing


def test_replan_changes_only_operational_partitioning() -> None:
    previous = _replanning()
    replanned = replan_campaign_state(
        previous,
        new_plan_sha256="5" * 64,
        logical_unit_manifest_sha256=SHA["units"],
        completed_unit_manifest_sha256=SHA["completed"],
        operational_overrides={
            "batch_size": 20,
            "checkpoint_interval_seconds": 30,
        },
        replan_receipt_sha256=SHA["replan"],
        created_at=NOW,
    )

    assert replanned.scientific_contract_sha256 == SHA["spec"]
    assert replanned.logical_unit_manifest_sha256 == SHA["units"]
    assert replanned.completed_unit_manifest_sha256 == SHA["completed"]
    assert replanned.completed_unit_count == 4
    assert replanned.pending_unit_count == 6
    assert replanned.active_plan_sha256 == "5" * 64
    assert replanned.phase is CampaignPhase.RECOVERING
    assert replanned.replan_receipt_sha256 == SHA["replan"]

    with pytest.raises(
        CampaignTransitionError,
        match="logical unit manifest",
    ):
        replan_campaign_state(
            previous,
            new_plan_sha256="5" * 64,
            logical_unit_manifest_sha256="9" * 64,
            completed_unit_manifest_sha256=SHA["completed"],
            operational_overrides={},
            replan_receipt_sha256=SHA["replan"],
            created_at=NOW,
        )


def test_merge_only_reuses_verified_sources_and_schedules_no_compute() -> None:
    ready = transition_campaign_state(
        _executing(),
        phase=CampaignPhase.READY_TO_MERGE,
        completed_unit_count=10,
        completed_unit_manifest_sha256=SHA["completed"],
        pending_unit_count=0,
        verified_source_artifacts=("artifact-a", "artifact-b"),
        created_at=NOW,
    )

    merge = begin_merge_only(
        ready,
        source_artifacts=("artifact-a", "artifact-b"),
        created_at=NOW,
    )

    assert merge.phase is CampaignPhase.MERGING
    assert merge.merge_only is True
    assert merge.compute_scheduled is False
    assert merge.verified_source_artifacts == (
        "artifact-a",
        "artifact-b",
    )


def test_merge_only_can_branch_from_completed_verified_campaign() -> None:
    ready = transition_campaign_state(
        _executing(),
        phase=CampaignPhase.READY_TO_MERGE,
        completed_unit_count=10,
        completed_unit_manifest_sha256=SHA["completed"],
        pending_unit_count=0,
        verified_source_artifacts=("artifact-a", "artifact-b"),
        created_at=NOW,
    )
    merging = transition_campaign_state(
        ready,
        phase=CampaignPhase.MERGING,
        created_at=NOW,
    )
    verifying = transition_campaign_state(
        merging,
        phase=CampaignPhase.VERIFYING,
        created_at=NOW,
    )
    completed = transition_campaign_state(
        verifying,
        phase=CampaignPhase.COMPLETED,
        created_at=NOW,
    )

    merge = begin_merge_only(
        completed,
        source_artifacts=("artifact-b", "artifact-a"),
        created_at=NOW,
    )

    assert merge.phase is CampaignPhase.MERGING
    assert merge.previous_state_sha256 == completed.state_sha256
    assert merge.version == completed.version + 1
    assert merge.completed_unit_manifest_sha256 == (
        completed.completed_unit_manifest_sha256
    )
    assert merge.completed_unit_count == completed.completed_unit_count
    assert merge.pending_unit_count == 0
    assert merge.merge_only is True
    assert merge.compute_scheduled is False
    assert merge.active_attempt_ids == ()
    assert merge.verified_source_artifacts == (
        "artifact-a",
        "artifact-b",
    )


def test_transition_rejects_completed_count_regression() -> None:
    progressed = transition_campaign_state(
        _executing(),
        phase=CampaignPhase.RECOVERING,
        completed_unit_count=4,
        completed_unit_manifest_sha256=SHA["completed"],
        pending_unit_count=6,
        created_at=NOW,
    )
    with pytest.raises(CampaignTransitionError, match="cannot regress"):
        transition_campaign_state(
            progressed,
            phase=CampaignPhase.RECOVERING,
            completed_unit_count=3,
            pending_unit_count=7,
            created_at=NOW,
        )


def test_completed_campaign_requires_legal_chain_and_every_unit() -> None:
    with pytest.raises(CampaignTransitionError, match="illegal campaign transition"):
        transition_campaign_state(
            _initial(),
            phase=CampaignPhase.COMPLETED,
            created_at=NOW,
        )

    ready = transition_campaign_state(
        _executing(),
        phase=CampaignPhase.READY_TO_MERGE,
        completed_unit_count=10,
        completed_unit_manifest_sha256=SHA["completed"],
        pending_unit_count=0,
        created_at=NOW,
    )
    merging = transition_campaign_state(
        ready,
        phase=CampaignPhase.MERGING,
        created_at=NOW,
    )
    verifying = transition_campaign_state(
        merging,
        phase=CampaignPhase.VERIFYING,
        created_at=NOW,
    )
    completed = transition_campaign_state(
        verifying,
        phase=CampaignPhase.COMPLETED,
        created_at=NOW,
    )
    assert completed.completed_unit_count == completed.logical_unit_count
    assert completed.pending_unit_count == 0


def test_authority_bindings_are_mandatory_and_immutable() -> None:
    state = _executing()
    assert state.authority_id == "authority-1"
    assert state.request_sha256 == SHA["request"]
    assert state.protected_commit_sha == "b" * 40
    assert state.execution_protocol_sha256 == SHA["protocol"]
    assert state.controller_decision_sha256 == SHA["decision"]
    assert state.component_store_manifest_sha256 == SHA["components"]
    assert state.failure_history_manifest_sha256 == SHA["failures"]


def test_only_the_closed_campaign_transition_graph_is_legal() -> None:
    with pytest.raises(CampaignTransitionError, match="illegal campaign transition"):
        transition_campaign_state(
            _initial(),
            phase=CampaignPhase.READY_TO_MERGE,
            completed_unit_count=10,
            completed_unit_manifest_sha256=SHA["completed"],
            pending_unit_count=0,
            created_at=NOW,
        )
    recovering = transition_campaign_state(
        _executing(),
        phase=CampaignPhase.RECOVERING,
        created_at=NOW,
    )
    waiting = transition_campaign_state(
        recovering,
        phase=CampaignPhase.WAITING_RETRY,
        retry_not_before=NOW + timedelta(minutes=5),
        created_at=NOW,
    )
    assert waiting.compute_scheduled is False
    assert waiting.retry_not_before == NOW + timedelta(minutes=5)
    resumed = transition_campaign_state(
        waiting,
        phase=CampaignPhase.RECOVERING,
        created_at=NOW + timedelta(minutes=5),
    )
    assert resumed.retry_not_before is None


def test_active_plan_changes_only_with_explicit_replan_receipt() -> None:
    with pytest.raises(CampaignTransitionError, match="replan receipt"):
        transition_campaign_state(
            _executing(),
            phase=CampaignPhase.RECOVERING,
            active_plan_sha256="c" * 64,
            created_at=NOW,
        )


def test_recovery_protocol_mismatch_blocks_without_guessing_compatibility() -> None:
    assert_recovery_protocol_compatible(
        authority_protocol_sha256=SHA["protocol"],
        current_protocol_sha256=SHA["protocol"],
    )
    with pytest.raises(
        CampaignTransitionError,
        match="CATALOG_RECOVERY_PROTOCOL_MISMATCH",
    ):
        assert_recovery_protocol_compatible(
            authority_protocol_sha256=SHA["protocol"],
            current_protocol_sha256="d" * 64,
        )
