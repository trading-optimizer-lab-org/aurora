"""Deterministic PR-1 reconciliation for the first formal readiness task."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import domain_digest
from infra.gtbi_v7_readiness.controller import (
    validate_attempt_event_chain,
    validate_current_readiness_records,
    validate_task_event_chain,
)
from infra.gtbi_v7_readiness.genesis import (
    build_initial_records,
    validate_initial_records,
)
from infra.gtbi_v7_readiness.post_merge import validate_pr1_merge_receipt
from infra.gtbi_v7_readiness.records import (
    RECORD_SCHEMAS,
    read_csv,
    read_jsonl,
    write_csv,
    write_jsonl,
)

TASK_ID = "PREV7-0000"
ATTEMPT_ID = "PREV7-0000-attempt-0001"
TRANSACTION_ID = "BOOTSTRAP_FOUNDATION_TXN-1"
OWNER_ACTOR_ID = "github-user:271768688"
MUTABLE_FILENAMES = (
    "task_status.csv",
    "task_events.jsonl",
    "task_attempts.jsonl",
    "task_planning_inputs.csv",
    "task_delivery_manifest.csv",
)


class FormalGenesisValidationError(ValueError):
    """Raised when the deterministic formal-genesis projection drifts."""


def _timestamp(value: str, microseconds: int) -> str:
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    return (
        parsed + timedelta(microseconds=microseconds)
    ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _task_event(
    *,
    previous: dict[str, Any],
    sequence: int,
    new_status: str,
    timestamp: str,
    receipt: dict[str, Any],
    attempt_id: str | None,
) -> dict[str, Any]:
    row = {
        "schema_version": "readiness_task_event_v1",
        "event_id": f"{TASK_ID}-pr1-reconciliation-{sequence:04d}",
        "transaction_id": TRANSACTION_ID,
        "task_id": TASK_ID,
        "task_attempt_id_or_null": attempt_id,
        "event_sequence": sequence,
        "previous_status_or_null": previous["new_status"],
        "new_status": new_status,
        "actor_id": OWNER_ACTOR_ID,
        "actor_role": "repository_owner",
        "transitioned_at_utc": timestamp,
        "evaluated_commit_sha": receipt["merge_sha"],
        "expected_task_version": sequence,
        "dependency_snapshot_digest": previous[
            "dependency_snapshot_digest"
        ],
        "gate_snapshot_digest": previous["gate_snapshot_digest"],
        "evidence_digest_or_null": receipt["receipt_digest"],
        "alternative_completion_receipt_set_digest_or_null": None,
        "previous_task_event_digest_or_null": previous["event_digest"],
        "event_digest": "",
    }
    row["event_digest"] = domain_digest(
        "GTBI_READINESS_TASK_EVENT_V1",
        row,
        omit_top_level_fields=("event_digest",),
    )
    return row


def _attempt_event(
    *,
    previous: dict[str, Any] | None,
    status: str,
    version: int,
    timestamp: str,
    created_at: str,
    started_at: str | None,
    ended_at: str | None,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    input_digest = domain_digest(
        "GTBI_V7_PREV7_0000_ATTEMPT_INPUT_V1",
        {
            "base_sha": receipt["base_sha"],
            "head_sha": receipt["head_sha"],
            "master_plan_sha256": receipt["master_plan_sha256"],
            "merge_sha": receipt["merge_sha"],
        },
    )
    transition_receipt = domain_digest(
        "GTBI_V7_PREV7_0000_ATTEMPT_TRANSITION_V1",
        {
            "attempt_id": ATTEMPT_ID,
            "attempt_status": status,
            "evidence_digest": receipt["receipt_digest"],
            "transitioned_at_utc": timestamp,
            "version": version,
        },
    )
    row = {
        "schema_version": "readiness_attempt_event_v1",
        "task_id": TASK_ID,
        "task_attempt_id": ATTEMPT_ID,
        "attempt_sequence": 1,
        "actor_id": OWNER_ACTOR_ID,
        "actor_role": "repository_owner",
        "previous_attempt_status_or_null": (
            None if previous is None else previous["attempt_status"]
        ),
        "attempt_status": status,
        "expected_attempt_version": version,
        "created_at_utc": created_at,
        "started_at_utc_or_null": started_at,
        "ended_at_utc_or_null": ended_at,
        "input_digest": input_digest,
        "authorization_receipt_set_digest_or_null": receipt[
            "owner_decisions_sha256"
        ],
        "evidence_digest_or_null": (
            receipt["receipt_digest"] if status in {"review", "succeeded"} else None
        ),
        "terminal_reason_or_null": (
            "pr1_merged_with_all_checks_success"
            if status == "succeeded"
            else None
        ),
        "transition_receipt_digest": transition_receipt,
        "transitioned_at_utc": timestamp,
        "evaluated_commit_sha": receipt["merge_sha"],
        "event_id": f"{ATTEMPT_ID}-{version:04d}",
        "previous_attempt_event_digest_or_null": (
            None if previous is None else previous["event_digest"]
        ),
        "event_digest": "",
    }
    row["event_digest"] = domain_digest(
        "GTBI_READINESS_ATTEMPT_EVENT_V1",
        row,
        omit_top_level_fields=("event_digest",),
    )
    return row


def build_formal_genesis_records(
    repository_root: Path,
) -> dict[str, list[dict[str, Any]]]:
    """Build current records by extending, never rewriting, the initial events."""
    root = repository_root.resolve()
    receipt = validate_pr1_merge_receipt(root)
    records = build_initial_records(root)
    merged_at = str(receipt["merged_at_utc"])
    times = [_timestamp(merged_at, offset) for offset in range(1, 9)]

    task_events = list(records["task_events.jsonl"])
    previous = next(
        row for row in task_events if row["task_id"] == TASK_ID
    )
    for sequence, status in enumerate(
        ("ready", "in_progress", "review", "done"),
        start=1,
    ):
        previous = _task_event(
            previous=previous,
            sequence=sequence,
            new_status=status,
            timestamp=times[sequence - 1],
            receipt=receipt,
            attempt_id=None if status == "ready" else ATTEMPT_ID,
        )
        task_events.append(previous)
    records["task_events.jsonl"] = task_events

    attempts: list[dict[str, Any]] = []
    previous_attempt: dict[str, Any] | None = None
    for version, status in enumerate(
        ("created", "in_progress", "review", "succeeded")
    ):
        previous_attempt = _attempt_event(
            previous=previous_attempt,
            status=status,
            version=version,
            timestamp=times[version + 4],
            created_at=times[4],
            started_at=None if version == 0 else times[5],
            ended_at=times[7] if status == "succeeded" else None,
            receipt=receipt,
        )
        attempts.append(previous_attempt)
    records["task_attempts.jsonl"] = attempts

    zero_cost = {
        "github_actions": {
            "basis": "owner_current_net_actions_cost",
            "maximum_incremental_net_spend_usd": 0,
            "receipt": (
                "docs/readiness/gtbi-v7/"
                "billing_baseline_public_receipt.json"
            ),
        }
    }
    evidence_paths = [
        (
            "docs/readiness/gtbi-v7/"
            "pr1_merge_reconciliation_receipt.json"
        ),
        "docs/readiness/gtbi-v7/master_plan_quality_status.json",
    ]
    task_rows = records["task_status.csv"]
    task = next(row for row in task_rows if row["id"] == TASK_ID)
    task.update(
        {
            "current_attempt_id": ATTEMPT_ID,
            "next_attempt_sequence": 2,
            "task_version": 5,
            "status": "done",
            "blocking_reason": "",
            "evidence_paths": evidence_paths,
            "evidence_sha256": [receipt["receipt_digest"]],
            "acceptance_run_id": "30522231612",
            "approved_by": OWNER_ACTOR_ID,
            "approved_at": times[7],
            "started_at": times[1],
            "completed_at": times[7],
            "base_sha": receipt["base_sha"],
            "head_sha": receipt["head_sha"],
            "merge_sha": receipt["merge_sha"],
            "files_touched": [
                "docs/plans/gtbi-v7-master-plan.md",
                "docs/readiness/gtbi-v7",
                "infra/gtbi_v7_readiness",
                ".github/workflows/gtbi-v7-master-plan-quality.yml",
            ],
            "acceptance_command": (
                "python scripts/"
                "validate_gtbi_v7_pr1_merge_reconciliation.py"
            ),
            "merge_dependency": (
                "https://github.com/"
                "trading-optimizer-lab-org/aurora/pull/21"
            ),
            "estimated_work_hours": "19.14",
            "estimated_elapsed_hours": "19.14",
            "external_lead_time_hours": "0",
            "planning_state": "complete",
            "planning_blocker_code_or_null": "",
            "planned_start_utc": "2026-07-29T12:18:33Z",
            "due_at_utc": receipt["merged_at_utc"],
            "latest_start_utc": receipt["merged_at_utc"],
            "review_lead_time_hours": "0.22",
            "provider_or_hiring_lead_time_hours": "0",
            "estimated_cost_entries_by_domain": zero_cost,
            "notes": (
                "PR-1 merged and reconciled against exact plan bytes, "
                "successful CI and the owner-authorized zero-cost model."
            ),
        }
    )

    planning = next(
        row
        for row in records["task_planning_inputs.csv"]
        if row["task_id"] == TASK_ID
    )
    planning.update(
        {
            "estimated_work_hours": "19.14",
            "estimated_elapsed_hours": "19.14",
            "external_lead_time_hours": "0",
            "planning_state": "complete",
            "planning_blocker_code_or_null": "",
            "earliest_start_utc": "2026-07-29T12:18:33Z",
            "due_at_utc": receipt["merged_at_utc"],
            "review_lead_time_hours": "0.22",
            "provider_or_hiring_lead_time_hours": "0",
            "estimated_cost_entries_by_domain": zero_cost,
            "approved_at_utc": times[7],
        }
    )

    delivery = next(
        row
        for row in records["task_delivery_manifest.csv"]
        if row["task_id"] == TASK_ID
    )
    delivery.update(
        {
            "base_sha": receipt["base_sha"],
            "working_branch": "codex/gtbi-v7-master-plan-bootstrap",
            "planned_files": task["files_touched"],
            "acceptance_command": task["acceptance_command"],
            "expected_result": "PREV7-0000_merge_evidence_complete",
            "merge_dependency": task["merge_dependency"],
            "rollback_command_or_manifest": (
                "append-only correction receipt; never rewrite PR-1 evidence"
            ),
        }
    )
    return records


def _write_mutable_records(
    repository_root: Path,
    records: dict[str, list[dict[str, Any]]],
) -> list[Path]:
    root = repository_root.resolve()
    readiness = root / "docs/readiness/gtbi-v7"
    schema_by_filename = {
        schema.filename: schema for schema in RECORD_SCHEMAS
    }
    paths: list[Path] = []
    for filename in MUTABLE_FILENAMES:
        schema = schema_by_filename[filename]
        path = readiness / filename
        if schema.record_format == "csv":
            write_csv(path, schema.fields, records[filename])
        else:
            write_jsonl(path, records[filename])
        paths.append(path)
    return paths


def write_formal_genesis_records(repository_root: Path) -> list[Path]:
    """Apply the deterministic PR-1 transition, idempotently."""
    root = repository_root.resolve()
    try:
        current = validate_current_readiness_records(root)
    except (ValueError, KeyError):
        current = None
    if current is not None and TASK_ID in current["terminal_task_ids"]:
        return [
            root / "docs/readiness/gtbi-v7" / filename
            for filename in MUTABLE_FILENAMES
        ]
    try:
        validate_formal_genesis_records(root)
    except (FormalGenesisValidationError, ValueError):
        validate_initial_records(root)
    else:
        return [
            root / "docs/readiness/gtbi-v7" / filename
            for filename in MUTABLE_FILENAMES
        ]
    records = build_formal_genesis_records(root)
    paths = _write_mutable_records(root, records)
    validate_formal_genesis_records(root)
    return paths


def validate_formal_genesis_records(
    repository_root: Path,
) -> dict[str, Any]:
    """Require exact current projections and valid append-only chains."""
    root = repository_root.resolve()
    receipt = validate_pr1_merge_receipt(root)
    expected = build_formal_genesis_records(root)
    readiness = root / "docs/readiness/gtbi-v7"
    schema_by_filename = {
        schema.filename: schema for schema in RECORD_SCHEMAS
    }
    with tempfile.TemporaryDirectory(prefix="gtbi-v7-formal-genesis-") as temp:
        temporary = Path(temp)
        for filename in MUTABLE_FILENAMES:
            schema = schema_by_filename[filename]
            generated = temporary / filename
            if schema.record_format == "csv":
                write_csv(generated, schema.fields, expected[filename])
            else:
                write_jsonl(generated, expected[filename])
            if (readiness / filename).read_bytes() != generated.read_bytes():
                raise FormalGenesisValidationError(
                    f"{filename}: formal-genesis projection drift"
                )

    task_events = read_jsonl(
        readiness / "task_events.jsonl",
        schema_by_filename["task_events.jsonl"],
    )
    attempts = read_jsonl(
        readiness / "task_attempts.jsonl",
        schema_by_filename["task_attempts.jsonl"],
    )
    validate_task_event_chain(task_events)
    validate_attempt_event_chain(attempts)
    statuses = read_csv(
        readiness / "task_status.csv",
        schema_by_filename["task_status.csv"],
    )
    completed = [row["id"] for row in statuses if row["status"] == "done"]
    if completed != [TASK_ID]:
        raise FormalGenesisValidationError(
            f"unexpected completed tasks: {completed}"
        )
    return {
        "formal_genesis_complete": True,
        "completed_task_ids": completed,
        "merge_sha": receipt["merge_sha"],
        "task_event_rows": len(task_events),
        "task_attempt_rows": len(attempts),
    }


__all__ = [
    "ATTEMPT_ID",
    "FormalGenesisValidationError",
    "MUTABLE_FILENAMES",
    "TASK_ID",
    "build_formal_genesis_records",
    "validate_formal_genesis_records",
    "write_formal_genesis_records",
]
