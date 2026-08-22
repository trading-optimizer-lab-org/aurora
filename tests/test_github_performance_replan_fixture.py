from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

from aurora.infra.github_performance.campaign import (
    CampaignPhase,
    initialize_campaign_state,
    load_latest_campaign_state,
    transition_campaign_state,
    write_campaign_state,
)
from aurora.infra.github_performance.contracts import (
    AttemptManifest,
    TerminalState,
    UnitAttemptRecord,
)
from aurora.infra.github_performance.merge_planner import (
    write_shard_attempt_manifest,
    write_unit_attempt_manifest,
)
from aurora.infra.github_performance.replan_fixture import (
    build_replan_fixture,
)
from aurora.infra.github_performance.shard_planner import (
    sha256_file,
    weighted_lpt,
    write_work_unit_manifest,
)
from github_performance_helpers import make_unit


def _json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            (
                payload.model_dump(mode="json")
                if hasattr(payload, "model_dump")
                else payload
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _source_attempts(plan_root: Path, attempts_root: Path) -> None:
    plan = json.loads(
        (plan_root / "balanced_shard_plan.json").read_text(
            encoding="utf-8"
        )
    )
    for shard in plan["shards"]:
        shard_id = str(shard["shard_id"])
        assignment = pq.read_table(
            plan_root / str(shard["assignment_member"])
        )
        attempt_id = f"source-{shard_id}"
        rows = tuple(
            UnitAttemptRecord(
                unit_key=str(unit_key),
                shard_id=shard_id,
                attempt_id=attempt_id,
                state=TerminalState.COMPLETED,
                output_sha256=hashlib.sha256(
                    str(unit_key).encode("utf-8")
                ).hexdigest(),
                reason_code=None,
            )
            for unit_key in assignment.column("unit_key").to_pylist()
        )
        root = attempts_root / shard_id
        units = write_unit_attempt_manifest(
            rows,
            root / "unit_attempts.parquet",
        )
        manifest = AttemptManifest(
            shard_id=shard_id,
            attempt_id=attempt_id,
            state=TerminalState.COMPLETED,
            spec_hash="1" * 64,
            policy_hash="2" * 64,
            snapshot_hash="3" * 64,
            code_sha="4" * 40,
            dependency_lock_sha256="5" * 64,
            capacity_profile_sha256="6" * 64,
            output_sha256="7" * 64,
            reason_code=None,
            artifact_name=f"source-{shard_id}",
            unit_attempts_path=units.name,
            unit_attempts_sha256=sha256_file(units),
            checkpoint_artifact=None,
            completed_unit_count=len(rows),
            output_rows=len(rows),
            output_bytes=100,
            runtime_access_ledger_path="runtime.parquet",
            runtime_access_ledger_sha256="8" * 64,
            metric_inputs_path="metrics.parquet",
            metric_inputs_sha256="9" * 64,
        )
        _json(root / "shard_attempt_manifest.json", manifest)
        write_shard_attempt_manifest(
            (manifest,),
            root / "shard_attempt_manifest.parquet",
        )


def test_replan_fixture_preserves_science_and_leaves_only_pending_units(
    tmp_path: Path,
) -> None:
    plan_root = tmp_path / "plan"
    manifest = write_work_unit_manifest(
        (make_unit(index) for index in range(8)),
        plan_root / "work_units.parquet",
    )
    plan = weighted_lpt(manifest, 2, plan_root)
    _json(plan_root / "balanced_shard_plan.json", plan)
    _json(plan_root / "work_unit_manifest.json", manifest)

    state_root = tmp_path / "source-state"
    created_at = datetime(2026, 7, 26, tzinfo=timezone.utc)
    initial = initialize_campaign_state(
        campaign_id="replan-fixture",
        scientific_contract_sha256="a" * 64,
        logical_unit_manifest_sha256=manifest.sha256,
        logical_unit_count=manifest.unit_count,
        active_plan_sha256=plan.plan_sha256,
        authority_id="authority-replan-fixture",
        request_sha256="b" * 64,
        protected_commit_sha="c" * 40,
        execution_protocol_sha256="d" * 64,
        controller_decision_sha256="e" * 64,
        component_store_manifest_sha256="f" * 64,
        failure_history_manifest_sha256="1" * 64,
        created_at=created_at,
    )
    write_campaign_state(initial, state_root)
    executing = transition_campaign_state(
        initial,
        phase=CampaignPhase.EXECUTING,
        created_at=created_at,
    )
    write_campaign_state(executing, state_root)
    attempts_root = tmp_path / "source-attempts"
    _source_attempts(plan_root, attempts_root)

    report_path = build_replan_fixture(
        source_plan_root=plan_root,
        source_state_root=state_root,
        source_attempts_root=attempts_root,
        output_root=tmp_path / "fixture",
        artifact_prefix="fixture",
        created_at=created_at,
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    state = load_latest_campaign_state(tmp_path / "fixture" / "state")
    assert report["failure_reasons"] == [
        "OUT_OF_MEMORY",
        "DISK_EXHAUSTED",
    ]
    assert report["completed_unit_count"] == 4
    assert report["pending_unit_count"] == 4
    assert state.phase is CampaignPhase.REPLANNING
    assert state.scientific_contract_sha256 == "a" * 64
    assert state.logical_unit_manifest_sha256 == manifest.sha256
    assert state.active_plan_sha256 == plan.plan_sha256
    assert state.completed_unit_count == 4
    assert state.pending_unit_count == 4
    assert len(state.verified_source_artifacts) == 2
