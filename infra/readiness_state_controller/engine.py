"""Deterministic, closed-scope readiness transition projection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import domain_digest, raw_sha256
from infra.gtbi_v7_readiness.controller import (
    validate_attempt_event_chain,
    validate_gate_event_chain,
    validate_task_event_chain,
)
from infra.gtbi_v7_readiness.records import (
    RECORD_SCHEMAS,
    read_csv,
    read_jsonl,
    write_csv,
    write_jsonl,
)
from infra.readiness_state_controller.policy import (
    COMMIT_SHA_RE,
    READINESS_PREFIX,
    StateControllerError,
    validate_transition_manifest,
)

MUTABLE_FILENAMES = (
    "task_status.csv",
    "task_events.jsonl",
    "task_attempts.jsonl",
    "task_planning_inputs.csv",
    "task_delivery_manifest.csv",
    "conditional_branch_registry.csv",
    "gate_status.csv",
    "gate_events.jsonl",
)
TASK_PATH = ("ready", "in_progress", "review", "done")
ATTEMPT_PATH = ("created", "in_progress", "review", "succeeded")
CANCELLED_ATTEMPT_PATH = ("created", "cancelled")
CONTROLLER_VERSION = "gtbi_v7_readiness_state_controller_v1"


@dataclass(frozen=True)
class TransitionProjection:
    """In-memory projection and its deterministic receipt."""

    records: dict[str, list[dict[str, Any]]]
    receipt: dict[str, Any]


def _schema_by_filename() -> dict[str, Any]:
    return {schema.filename: schema for schema in RECORD_SCHEMAS}


def _load_records(root: Path) -> dict[str, list[dict[str, Any]]]:
    schemas = _schema_by_filename()
    readiness = root / "docs/readiness/gtbi-v7"
    records: dict[str, list[dict[str, Any]]] = {}
    for filename in MUTABLE_FILENAMES:
        schema = schemas[filename]
        path = readiness / filename
        records[filename] = (
            read_csv(path, schema)
            if schema.record_format == "csv"
            else read_jsonl(path, schema)
        )
    return records


def _parse_json_field(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _indexed(
    rows: list[dict[str, Any]],
    key: str,
) -> dict[str, dict[str, Any]]:
    return {str(row[key]): row for row in rows}


def _event_time(requested_at: str, offset: int) -> str:
    try:
        parsed = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StateControllerError("invalid requested_at_utc") from exc
    if parsed.tzinfo is None:
        raise StateControllerError("requested_at_utc must include a timezone")
    value = parsed.astimezone(timezone.utc) + timedelta(microseconds=offset)
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _verify_evidence(
    root: Path,
    action: dict[str, Any],
) -> str:
    observed: list[dict[str, str]] = []
    for relative, expected in zip(
        action["evidence_paths"],
        action["evidence_sha256"],
        strict=True,
    ):
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise StateControllerError(
                f"{action['task_id']}: evidence is not a regular file: "
                f"{relative}"
            )
        actual = raw_sha256(path)
        if actual != expected:
            raise StateControllerError(
                f"{action['task_id']}: evidence digest mismatch: {relative}"
            )
        observed.append({"path": relative, "sha256": actual})
    return domain_digest("GTBI_V7_TASK_EVIDENCE_SET_V1", observed)


def _last_by_identity(
    rows: list[dict[str, Any]],
    identity: str,
    value: str,
) -> dict[str, Any]:
    matches = [row for row in rows if str(row[identity]) == value]
    if not matches:
        raise StateControllerError(f"missing event history for {value}")
    return matches[-1]


def _task_event(
    *,
    task: dict[str, Any],
    previous: dict[str, Any],
    new_status: str,
    sequence: int,
    attempt_id: str | None,
    manifest: dict[str, Any],
    evidence_digest: str,
    timestamp: str,
    base_sha: str,
) -> dict[str, Any]:
    row = {
        "schema_version": "readiness_task_event_v1",
        "event_id": (
            f"{task['id']}-{manifest['manifest_id']}-{sequence:04d}"
        ),
        "transaction_id": manifest["transaction_id"],
        "task_id": task["id"],
        "task_attempt_id_or_null": attempt_id,
        "event_sequence": sequence,
        "previous_status_or_null": previous["new_status"],
        "new_status": new_status,
        "actor_id": manifest["actor_id"],
        "actor_role": manifest["actor_role"],
        "transitioned_at_utc": timestamp,
        "evaluated_commit_sha": base_sha,
        "expected_task_version": sequence,
        "dependency_snapshot_digest": domain_digest(
            "GTBI_V7_TASK_DEPENDENCY_SNAPSHOT_V1",
            sorted(_parse_json_field(task["dependencies"])),
        ),
        "gate_snapshot_digest": previous["gate_snapshot_digest"],
        "evidence_digest_or_null": (
            evidence_digest if new_status in {"review", "done"} else None
        ),
        "alternative_completion_receipt_set_digest_or_null": (
            task["alternative_completion_receipt_set_digest"] or None
        ),
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
    task: dict[str, Any],
    previous: dict[str, Any] | None,
    status: str,
    version: int,
    attempt_id: str,
    attempt_sequence: int,
    action: dict[str, Any],
    manifest: dict[str, Any],
    evidence_digest: str,
    timestamp: str,
    created_at: str,
    started_at: str | None,
    ended_at: str | None,
    base_sha: str,
) -> dict[str, Any]:
    row = {
        "schema_version": "readiness_attempt_event_v1",
        "task_id": task["id"],
        "task_attempt_id": attempt_id,
        "attempt_sequence": attempt_sequence,
        "actor_id": manifest["actor_id"],
        "actor_role": manifest["actor_role"],
        "previous_attempt_status_or_null": (
            None if previous is None else previous["attempt_status"]
        ),
        "attempt_status": status,
        "expected_attempt_version": version,
        "created_at_utc": created_at,
        "started_at_utc_or_null": started_at,
        "ended_at_utc_or_null": ended_at,
        "input_digest": domain_digest(
            "GTBI_V7_READINESS_ATTEMPT_INPUT_V1",
            {
                "action": action,
                "base_sha": base_sha,
                "manifest_digest": manifest["manifest_digest"],
            },
        ),
        "authorization_receipt_set_digest_or_null": manifest[
            "owner_directive_digest"
        ],
        "evidence_digest_or_null": (
            evidence_digest
            if status in {"review", "succeeded"}
            else None
        ),
        "terminal_reason_or_null": (
            action["terminal_reason"]
            if status in {"succeeded", "cancelled"}
            else None
        ),
        "transition_receipt_digest": domain_digest(
            "GTBI_V7_READINESS_ATTEMPT_TRANSITION_V1",
            {
                "attempt_id": attempt_id,
                "status": status,
                "timestamp": timestamp,
                "version": version,
            },
        ),
        "transitioned_at_utc": timestamp,
        "evaluated_commit_sha": base_sha,
        "event_id": f"{attempt_id}-{version:04d}",
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


def _dependencies_terminal(
    task: dict[str, Any],
    tasks: dict[str, dict[str, Any]],
) -> bool:
    for dependency in _parse_json_field(task["dependencies"]):
        row = tasks.get(str(dependency))
        if row is None or row["status"] not in {"done", "cancelled"}:
            return False
        if (
            row["status"] == "cancelled"
            and not row["alternative_completion_receipt_set_digest"]
        ):
            return False
    return True


def _apply_task(
    *,
    records: dict[str, list[dict[str, Any]]],
    action: dict[str, Any],
    manifest: dict[str, Any],
    root: Path,
    base_sha: str,
    offset: int,
) -> int:
    tasks = _indexed(records["task_status.csv"], "id")
    task = tasks.get(action["task_id"])
    if task is None:
        raise StateControllerError(f"unknown task: {action['task_id']}")
    if task["status"] in {"done", "cancelled"}:
        raise StateControllerError(f"{task['id']}: task is already terminal")
    if not _dependencies_terminal(task, tasks):
        raise StateControllerError(f"{task['id']}: dependencies are not terminal")

    evidence_digest = _verify_evidence(root, action)
    alternative = action[
        "alternative_completion_receipt_set_digest_or_null"
    ]
    if action["target_status"] == "cancelled" and alternative is None:
        raise StateControllerError(
            f"{task['id']}: cancellation requires alternative completion"
        )
    task["alternative_completion_receipt_set_digest"] = alternative or ""

    attempt_sequence = int(task["next_attempt_sequence"])
    attempt_id = f"{task['id']}-attempt-{attempt_sequence:04d}"
    attempt_statuses = (
        ATTEMPT_PATH
        if action["target_status"] == "done"
        else CANCELLED_ATTEMPT_PATH
    )
    attempt_previous: dict[str, Any] | None = None
    created_at = _event_time(manifest["requested_at_utc"], offset)
    for version, status in enumerate(attempt_statuses):
        timestamp = _event_time(
            manifest["requested_at_utc"],
            offset + version,
        )
        attempt_previous = _attempt_event(
            task=task,
            previous=attempt_previous,
            status=status,
            version=version,
            attempt_id=attempt_id,
            attempt_sequence=attempt_sequence,
            action=action,
            manifest=manifest,
            evidence_digest=evidence_digest,
            timestamp=timestamp,
            created_at=created_at,
            started_at=(
                None
                if status == "created"
                else _event_time(manifest["requested_at_utc"], offset + 1)
            ),
            ended_at=(
                timestamp if status in {"succeeded", "cancelled"} else None
            ),
            base_sha=base_sha,
        )
        records["task_attempts.jsonl"].append(attempt_previous)
    offset += len(attempt_statuses)

    task_previous = _last_by_identity(
        records["task_events.jsonl"],
        "task_id",
        task["id"],
    )
    sequence = int(task["task_version"])
    statuses = (
        TASK_PATH
        if action["target_status"] == "done"
        else ("cancelled",)
    )
    started_at = ""
    completed_at = ""
    for status in statuses:
        timestamp = _event_time(manifest["requested_at_utc"], offset)
        task_previous = _task_event(
            task=task,
            previous=task_previous,
            new_status=status,
            sequence=sequence,
            attempt_id=None if status == "ready" else attempt_id,
            manifest=manifest,
            evidence_digest=evidence_digest,
            timestamp=timestamp,
            base_sha=base_sha,
        )
        records["task_events.jsonl"].append(task_previous)
        if status == "in_progress":
            started_at = timestamp
        if status in {"done", "cancelled"}:
            completed_at = timestamp
        sequence += 1
        offset += 1

    task.update(
        {
            "current_attempt_id": attempt_id,
            "next_attempt_sequence": attempt_sequence + 1,
            "task_version": sequence,
            "status": action["target_status"],
            "blocking_reason": "",
            "evidence_paths": action["evidence_paths"],
            "evidence_sha256": action["evidence_sha256"],
            "approved_by": manifest["actor_id"],
            "approved_at": completed_at,
            "approval_receipt_set_digest": manifest[
                "owner_directive_digest"
            ],
            "started_at": started_at or completed_at,
            "completed_at": completed_at,
            "notes": action["notes"],
            "base_sha": base_sha,
            "head_sha": base_sha,
            "merge_sha": base_sha,
            "files_touched": action["files_touched"],
            "expected_result": action["expected_result"],
            "planning_state": "complete",
            "planning_blocker_code_or_null": "",
            "external_lead_time_hours": "0",
            "provider_or_hiring_lead_time_hours": "0",
            "estimated_cost_entries_by_domain": {
                "github_actions": {
                    "maximum_incremental_net_spend_usd": 0,
                    "owner_authorized": True,
                }
            },
        }
    )

    planning = _indexed(
        records["task_planning_inputs.csv"],
        "task_id",
    )[task["id"]]
    planning.update(
        {
            "external_lead_time_hours": "0",
            "planning_state": "complete",
            "planning_blocker_code_or_null": "",
            "provider_or_hiring_lead_time_hours": "0",
            "estimated_cost_entries_by_domain": task[
                "estimated_cost_entries_by_domain"
            ],
            "approved_at_utc": completed_at,
        }
    )
    delivery = _indexed(
        records["task_delivery_manifest.csv"],
        "task_id",
    )[task["id"]]
    delivery.update(
        {
            "base_sha": base_sha,
            "working_branch": (
                f"gtbi-readiness-state/{manifest['manifest_id']}"
            ),
            "planned_files": action["files_touched"],
            "expected_result": action["expected_result"],
            "merge_dependency": (
                f"transition-manifest:{manifest['manifest_id']}"
            ),
            "rollback_command_or_manifest": (
                "append-only correction manifest"
            ),
        }
    )
    return offset


def _apply_branches(
    records: dict[str, list[dict[str, Any]]],
    manifest: dict[str, Any],
) -> None:
    rows = {
        (str(row["branch_id"]), str(row["task_id"])): row
        for row in records["conditional_branch_registry.csv"]
    }
    tasks = _indexed(records["task_status.csv"], "id")
    for action in manifest["branch_actions"]:
        key = (action["branch_id"], action["task_id"])
        row = rows.get(key)
        if row is None:
            raise StateControllerError(f"unknown branch decision: {key}")
        task = tasks[action["task_id"]]
        if task["status"] not in {"done", "cancelled"}:
            raise StateControllerError(
                f"{action['branch_id']}: task is not terminal"
            )
        row.update(
            {
                "predicate_evidence_digest": action[
                    "predicate_evidence_digest"
                ],
                "selected_successor": action["selected_successor"],
                "unselected_alternative_completion": (
                    "owner_controlled_alternative_complete"
                ),
                "decision_actor_id": manifest["actor_id"],
                "decision_receipt_digest": action[
                    "decision_receipt_digest"
                ],
            }
        )


def _apply_gates(
    *,
    records: dict[str, list[dict[str, Any]]],
    manifest: dict[str, Any],
    base_sha: str,
    offset: int,
) -> int:
    gates = _indexed(records["gate_status.csv"], "gate_id")
    tasks = _indexed(records["task_status.csv"], "id")
    for action in manifest["gate_actions"]:
        gate = gates.get(action["gate_id"])
        if gate is None:
            raise StateControllerError(f"unknown gate: {action['gate_id']}")
        required = _parse_json_field(gate["evaluated_required_task_ids"])
        for task_id in required:
            task = tasks[str(task_id)]
            if task["status"] not in {"done", "cancelled"}:
                raise StateControllerError(
                    f"{gate['gate_id']}: required task {task_id} is not terminal"
                )
            if (
                task["status"] == "cancelled"
                and not task[
                    "alternative_completion_receipt_set_digest"
                ]
            ):
                raise StateControllerError(
                    f"{gate['gate_id']}: cancelled task {task_id} "
                    "has no alternative completion"
                )

        previous = _last_by_identity(
            records["gate_events.jsonl"],
            "gate_id",
            gate["gate_id"],
        )
        timestamp = _event_time(manifest["requested_at_utc"], offset)
        event = {
            "schema_version": "readiness_gate_event_v1",
            "event_id": (
                f"{gate['gate_id']}-{manifest['manifest_id']}-"
                f"{int(gate['gate_version']):04d}"
            ),
            "transaction_id": manifest["transaction_id"],
            "gate_id": gate["gate_id"],
            "gate_attempt_id": (
                f"{gate['gate_id']}-attempt-"
                f"{int(gate['gate_version']):04d}"
            ),
            "previous_status_or_null": previous["new_status"],
            "new_status": action["target_status"],
            "expected_gate_version": int(gate["gate_version"]),
            "previous_gate_event_digest_or_null": previous["event_digest"],
            "required_task_id_set_digest": gate[
                "required_task_id_set_digest"
            ],
            "required_condition_digest": gate[
                "required_condition_digest"
            ],
            "selected_branch_id_or_null": action[
                "selected_branch_id_or_null"
            ],
            "inventory_snapshot_digest_or_null": action[
                "inventory_snapshot_digest"
            ],
            "evidence_bundle_digest": action["evidence_bundle_digest"],
            "actor_id": manifest["actor_id"],
            "actor_role": manifest["actor_role"],
            "transitioned_at_utc": timestamp,
            "evaluated_commit_sha": base_sha,
            "event_digest": "",
        }
        event["event_digest"] = domain_digest(
            "GTBI_READINESS_GATE_EVENT_V1",
            event,
            omit_top_level_fields=("event_digest",),
        )
        records["gate_events.jsonl"].append(event)
        gate.update(
            {
                "gate_attempt_id": event["gate_attempt_id"],
                "gate_version": int(gate["gate_version"]) + 1,
                "status": action["target_status"],
                "selected_branch_id_or_null": (
                    action["selected_branch_id_or_null"] or ""
                ),
                "inventory_snapshot_digest_or_null": action[
                    "inventory_snapshot_digest"
                ],
                "evidence_bundle_digest": action[
                    "evidence_bundle_digest"
                ],
                "blocking_reason": "",
                "evaluated_at_utc": timestamp,
                "evaluated_commit_sha": base_sha,
            }
        )
        offset += 1
    return offset


def build_transition_projection(
    repository_root: Path,
    manifest: dict[str, Any],
    *,
    base_sha: str,
) -> TransitionProjection:
    """Build and validate the exact state projection without writing it."""
    validate_transition_manifest(manifest)
    if not COMMIT_SHA_RE.fullmatch(base_sha):
        raise StateControllerError("invalid base commit SHA")
    root = repository_root.resolve()
    records = _load_records(root)
    offset = 1
    for action in manifest["task_actions"]:
        offset = _apply_task(
            records=records,
            action=action,
            manifest=manifest,
            root=root,
            base_sha=base_sha,
            offset=offset,
        )
    _apply_branches(records, manifest)
    _apply_gates(
        records=records,
        manifest=manifest,
        base_sha=base_sha,
        offset=offset,
    )
    validate_task_event_chain(records["task_events.jsonl"])
    validate_attempt_event_chain(records["task_attempts.jsonl"])
    validate_gate_event_chain(records["gate_events.jsonl"])

    output_digests: dict[str, str] = {}
    schemas = _schema_by_filename()
    import tempfile

    with tempfile.TemporaryDirectory(
        prefix="gtbi-v7-state-projection-"
    ) as temporary:
        directory = Path(temporary)
        for filename in MUTABLE_FILENAMES:
            schema = schemas[filename]
            path = directory / filename
            if schema.record_format == "csv":
                write_csv(path, schema.fields, records[filename])
            else:
                write_jsonl(path, records[filename])
            output_digests[f"{READINESS_PREFIX}{filename}"] = raw_sha256(
                path
            )

    receipt = {
        "schema_version": "gtbi_v7_state_controller_receipt_v1",
        "controller_version": CONTROLLER_VERSION,
        "manifest_id": manifest["manifest_id"],
        "manifest_digest": manifest["manifest_digest"],
        "transaction_id": manifest["transaction_id"],
        "base_ref": manifest["expected_base_ref"],
        "base_sha": base_sha,
        "actor_id": manifest["actor_id"],
        "task_actions_applied": [
            {
                "task_id": action["task_id"],
                "target_status": action["target_status"],
            }
            for action in manifest["task_actions"]
        ],
        "branch_actions_applied": [
            {
                "branch_id": action["branch_id"],
                "task_id": action["task_id"],
            }
            for action in manifest["branch_actions"]
        ],
        "gate_actions_applied": [
            {
                "gate_id": action["gate_id"],
                "target_status": action["target_status"],
            }
            for action in manifest["gate_actions"]
        ],
        "output_sha256": output_digests,
        "scientific_work_performed": False,
        "locked_data_accessed": False,
        "arbitrary_command_execution_supported": False,
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_STATE_CONTROLLER_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return TransitionProjection(records=records, receipt=receipt)


def write_transition_projection(
    repository_root: Path,
    projection: TransitionProjection,
) -> list[Path]:
    """Write only the closed mutable readiness-record allowlist."""
    root = repository_root.resolve()
    readiness = root / "docs/readiness/gtbi-v7"
    schemas = _schema_by_filename()
    written: list[Path] = []
    for filename in MUTABLE_FILENAMES:
        schema = schemas[filename]
        path = readiness / filename
        if schema.record_format == "csv":
            write_csv(path, schema.fields, projection.records[filename])
        else:
            write_jsonl(path, projection.records[filename])
        written.append(path)
    return written


__all__ = [
    "CONTROLLER_VERSION",
    "MUTABLE_FILENAMES",
    "TransitionProjection",
    "build_transition_projection",
    "write_transition_projection",
]
