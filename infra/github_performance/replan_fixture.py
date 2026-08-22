"""Build a GitHub-only OOM/disk fixture for pending-unit replan proof."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

from aurora.infra.github_performance.campaign import (
    CampaignPhase,
    load_latest_campaign_state,
    transition_campaign_state,
    write_campaign_state,
)
from aurora.infra.github_performance.contracts import (
    AttemptManifest,
    ShardPlan,
    TerminalState,
    UnitAttemptRecord,
    deep_thaw_json,
)
from aurora.infra.github_performance.merge_planner import (
    write_shard_attempt_manifest,
    write_unit_attempt_manifest,
)
from aurora.infra.github_performance.recovery import (
    build_terminal_unit_evidence_from_paths,
)
from aurora.infra.github_performance.shard_planner import sha256_file


DEFAULT_FAILURE_REASONS = ("OUT_OF_MEMORY", "DISK_EXHAUSTED")


def _atomic_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            deep_thaw_json(payload),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _source_attempts(root: Path) -> dict[str, tuple[AttemptManifest, Path]]:
    attempts: dict[str, tuple[AttemptManifest, Path]] = {}
    for manifest_path in sorted(
        Path(root).rglob("shard_attempt_manifest.json")
    ):
        manifest = AttemptManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        if manifest.state is not TerminalState.COMPLETED:
            continue
        if manifest.shard_id in attempts:
            raise ValueError(
                f"multiple completed source attempts for {manifest.shard_id}"
            )
        attempts[manifest.shard_id] = (manifest, manifest_path.parent)
    return attempts


def build_replan_fixture(
    *,
    source_plan_root: Path,
    source_state_root: Path,
    source_attempts_root: Path,
    output_root: Path,
    artifact_prefix: str,
    failure_reasons: Sequence[str] = DEFAULT_FAILURE_REASONS,
    completed_fraction: float = 0.5,
    created_at: datetime | None = None,
) -> Path:
    """Create bound partial evidence and a replanning campaign state."""

    if not 0.0 < completed_fraction < 1.0:
        raise ValueError("completed_fraction must be between zero and one")
    reasons = tuple(str(reason) for reason in failure_reasons)
    if not reasons:
        raise ValueError("at least one failure reason is required")

    source_plan_root = Path(source_plan_root)
    source_state_root = Path(source_state_root)
    source_attempts_root = Path(source_attempts_root)
    output_root = Path(output_root)
    plan = ShardPlan.model_validate_json(
        (
            source_plan_root / "balanced_shard_plan.json"
        ).read_text(encoding="utf-8")
    )
    shards = tuple(sorted(plan.shards, key=lambda item: item.shard_id))
    if len(shards) != len(reasons):
        raise ValueError(
            "fixture requires one source shard per failure reason"
        )
    source_by_shard = _source_attempts(source_attempts_root)

    attempt_paths: list[Path] = []
    unit_attempt_paths: list[Path] = []
    shard_reports: list[dict[str, object]] = []
    for index, (shard, reason) in enumerate(zip(shards, reasons, strict=True)):
        source = source_by_shard.get(shard.shard_id)
        if source is None:
            raise ValueError(
                f"completed source attempt missing for {shard.shard_id}"
            )
        source_manifest, source_directory = source
        if source_manifest.unit_attempts_path is None:
            raise ValueError("source attempt has no unit evidence")
        source_units = source_directory / source_manifest.unit_attempts_path
        if (
            source_manifest.unit_attempts_sha256 is None
            or sha256_file(source_units)
            != source_manifest.unit_attempts_sha256
        ):
            raise ValueError("source unit evidence hash mismatch")
        rows = tuple(
            UnitAttemptRecord.model_validate(row)
            for row in pq.read_table(source_units).to_pylist()
        )
        if len(rows) != shard.unit_count or len(rows) < 2:
            raise ValueError("fixture source shard has invalid unit count")
        completed_count = max(1, int(len(rows) * completed_fraction))
        completed_count = min(completed_count, len(rows) - 1)
        attempt_id = f"fixture-{index:03d}"
        artifact_name = (
            f"{artifact_prefix}-shard-{shard.shard_id}-a-{attempt_id}"
        )
        artifact_root = output_root / "artifacts" / artifact_name
        fixture_rows = tuple(
            UnitAttemptRecord(
                unit_key=row.unit_key,
                shard_id=shard.shard_id,
                attempt_id=attempt_id,
                state=(
                    TerminalState.COMPLETED
                    if row_index < completed_count
                    else TerminalState.FAILED_TECHNICAL
                ),
                output_sha256=(
                    row.output_sha256
                    if row_index < completed_count
                    else None
                ),
                reason_code=(
                    None if row_index < completed_count else reason
                ),
            )
            for row_index, row in enumerate(rows)
        )
        unit_path = write_unit_attempt_manifest(
            fixture_rows,
            artifact_root / "unit_attempts.parquet",
        )
        manifest = source_manifest.model_copy(
            update={
                "attempt_id": attempt_id,
                "state": TerminalState.FAILED_TECHNICAL,
                "output_sha256": None,
                "reason_code": reason,
                "artifact_name": artifact_name,
                "unit_attempts_path": unit_path.name,
                "unit_attempts_sha256": sha256_file(unit_path),
                "checkpoint_artifact": None,
                "completed_unit_count": completed_count,
                "output_rows": completed_count,
                "output_bytes": 0,
                "runtime_access_ledger_path": None,
                "runtime_access_ledger_sha256": None,
                "metric_inputs_path": None,
                "metric_inputs_sha256": None,
            }
        )
        attempt_path = _atomic_json(
            artifact_root / "shard_attempt_manifest.json",
            manifest,
        )
        write_shard_attempt_manifest(
            (manifest,),
            artifact_root / "shard_attempt_manifest.parquet",
        )
        attempt_paths.append(attempt_path)
        unit_attempt_paths.append(unit_path)
        shard_reports.append(
            {
                "shard_id": shard.shard_id,
                "reason_code": reason,
                "source_attempt_id": source_manifest.attempt_id,
                "fixture_attempt_id": attempt_id,
                "artifact_name": artifact_name,
                "completed_unit_count": completed_count,
                "pending_unit_count": len(rows) - completed_count,
            }
        )

    evidence = build_terminal_unit_evidence_from_paths(
        attempt_paths,
        unit_attempt_paths,
    )
    state_root = output_root / "state"
    shutil.copytree(source_state_root, state_root, dirs_exist_ok=True)
    previous = load_latest_campaign_state(state_root)
    pending = previous.logical_unit_count - evidence.unit_count
    if pending <= 0:
        raise ValueError("fixture must leave pending units")
    now = created_at or datetime.now(timezone.utc)
    recovering = transition_campaign_state(
        previous,
        phase=CampaignPhase.RECOVERING,
        completed_unit_count=evidence.unit_count,
        completed_unit_manifest_sha256=evidence.unit_manifest_sha256,
        pending_unit_count=pending,
        verified_source_artifacts=evidence.source_artifacts,
        active_attempt_ids=tuple(
            f"fixture-{index:03d}" for index in range(len(shards))
        ),
        wave=previous.wave + 1,
        hard_failure_reason=",".join(reasons),
        created_at=now,
    )
    write_campaign_state(recovering, state_root)
    state = transition_campaign_state(
        recovering,
        phase=CampaignPhase.REPLANNING,
        created_at=now,
    )
    state_path = write_campaign_state(state, state_root)
    return _atomic_json(
        output_root / "replan_fixture.json",
        {
            "schema_version": "1",
            "campaign_state": state_path.name,
            "campaign_state_sha256": state.state_sha256,
            "scientific_contract_sha256": (
                state.scientific_contract_sha256
            ),
            "logical_unit_manifest_sha256": (
                state.logical_unit_manifest_sha256
            ),
            "active_plan_sha256": state.active_plan_sha256,
            "completed_unit_manifest_sha256": (
                state.completed_unit_manifest_sha256
            ),
            "completed_unit_count": state.completed_unit_count,
            "pending_unit_count": state.pending_unit_count,
            "failure_reasons": reasons,
            "verified_source_artifacts": evidence.source_artifacts,
            "shards": shard_reports,
        },
    )
