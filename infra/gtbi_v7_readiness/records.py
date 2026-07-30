"""Schemas and deterministic I/O for GTBI V7 readiness records."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import canonical_bytes

TASK_STATUS_FIELDS = (
    "id",
    "current_attempt_id",
    "next_attempt_sequence",
    "task_version",
    "title",
    "gate",
    "priority",
    "owner_role",
    "owner_actor_id",
    "status",
    "dependencies",
    "exact_inputs",
    "entry_conditions",
    "blocking_reason",
    "github_issue",
    "pull_request",
    "exact_outputs",
    "acceptance_criteria",
    "evidence_paths",
    "evidence_sha256",
    "evidence_classification",
    "private_evidence_id",
    "redaction_review",
    "acceptance_workflow",
    "acceptance_run_id",
    "rollback",
    "approved_by",
    "approved_at",
    "required_approver_roles",
    "approval_receipt_set_digest",
    "alternative_completion_receipt_set_digest",
    "activation_condition",
    "alternative_completion",
    "cancel_condition",
    "superseded_by",
    "rollback_trigger",
    "started_at",
    "completed_at",
    "notes",
    "repository_id",
    "base_ref",
    "base_sha",
    "working_branch",
    "head_sha",
    "merge_sha",
    "files_touched",
    "acceptance_command",
    "expected_result",
    "merge_dependency",
    "estimated_work_hours",
    "estimated_elapsed_hours",
    "external_lead_time_hours",
    "planning_state",
    "planning_blocker_code_or_null",
    "planned_start_utc",
    "due_at_utc",
    "latest_start_utc",
    "schedule_owner_actor_id",
    "required_participant_role_ids",
    "required_participant_actor_ids",
    "participant_availability_manifest_digest",
    "participant_max_concurrent_tasks_by_actor",
    "review_lead_time_hours",
    "provider_or_hiring_lead_time_hours",
    "budget_currency",
    "estimated_cost_entries_by_domain",
)

GATE_DEFINITION_FIELDS = (
    "gate_id",
    "prerequisite_gate_ids",
    "required_task_ids",
    "required_condition",
    "branch_policy",
    "gate_definition_digest",
)

GATE_STATUS_FIELDS = (
    "gate_id",
    "gate_attempt_id",
    "gate_version",
    "status",
    "prerequisite_gate_ids",
    "gate_definition_digest",
    "evaluated_required_task_ids",
    "required_task_id_set_digest",
    "required_condition_digest",
    "selected_branch_id_or_null",
    "inventory_snapshot_digest_or_null",
    "evidence_bundle_digest",
    "blocking_reason",
    "evaluated_at_utc",
    "evaluated_commit_sha",
)

TASK_EVENT_FIELDS = (
    "schema_version",
    "event_id",
    "transaction_id",
    "task_id",
    "task_attempt_id_or_null",
    "event_sequence",
    "previous_status_or_null",
    "new_status",
    "actor_id",
    "actor_role",
    "transitioned_at_utc",
    "evaluated_commit_sha",
    "expected_task_version",
    "dependency_snapshot_digest",
    "gate_snapshot_digest",
    "evidence_digest_or_null",
    "alternative_completion_receipt_set_digest_or_null",
    "previous_task_event_digest_or_null",
    "event_digest",
)

TASK_ATTEMPT_FIELDS = (
    "schema_version",
    "task_id",
    "task_attempt_id",
    "attempt_sequence",
    "actor_id",
    "actor_role",
    "previous_attempt_status_or_null",
    "attempt_status",
    "expected_attempt_version",
    "created_at_utc",
    "started_at_utc_or_null",
    "ended_at_utc_or_null",
    "input_digest",
    "authorization_receipt_set_digest_or_null",
    "evidence_digest_or_null",
    "terminal_reason_or_null",
    "transition_receipt_digest",
    "transitioned_at_utc",
    "evaluated_commit_sha",
    "event_id",
    "previous_attempt_event_digest_or_null",
    "event_digest",
)

GATE_EVENT_FIELDS = (
    "schema_version",
    "event_id",
    "transaction_id",
    "gate_id",
    "gate_attempt_id",
    "previous_status_or_null",
    "new_status",
    "expected_gate_version",
    "previous_gate_event_digest_or_null",
    "required_task_id_set_digest",
    "required_condition_digest",
    "selected_branch_id_or_null",
    "inventory_snapshot_digest_or_null",
    "evidence_bundle_digest",
    "actor_id",
    "actor_role",
    "transitioned_at_utc",
    "evaluated_commit_sha",
    "event_digest",
)

CONDITIONAL_BRANCH_FIELDS = (
    "branch_id",
    "task_id",
    "predicate_schema_digest",
    "predicate_evidence_digest",
    "selected_successor",
    "unselected_alternative_completion",
    "invalidated_evidence_classes",
    "affected_gates",
    "decision_actor_id",
    "decision_receipt_digest",
)

TASK_DEFINITION_FIELDS = (
    "task_id",
    "task_definition_digest",
    "title",
    "gate",
    "priority",
    "owner_role",
    "dependencies",
    "required_approver_roles",
    "approval_policy_digest",
    "required_evidence_classification",
    "exact_inputs",
    "entry_conditions",
    "exact_outputs",
    "acceptance_criteria",
    "activation_condition",
    "alternative_completion",
    "cancel_condition",
    "rollback",
    "rollback_trigger",
    "repository_id",
    "planned_files",
    "acceptance_command",
    "expected_result",
    "merge_dependency",
    "estimated_work_hours",
    "estimated_elapsed_hours",
    "external_lead_time_hours",
    "planning_state",
    "planning_blocker_code_or_null",
    "planned_start_utc",
    "due_at_utc",
    "latest_start_utc",
    "schedule_owner_role",
    "required_participant_role_ids",
    "required_participant_actor_ids",
    "participant_availability_manifest_digest",
    "participant_max_concurrent_tasks_by_actor",
    "review_lead_time_hours",
    "provider_or_hiring_lead_time_hours",
    "budget_currency",
    "estimated_cost_entries_by_domain",
)

TASK_PLANNING_FIELDS = (
    "task_id",
    "estimated_work_hours",
    "estimated_elapsed_hours",
    "external_lead_time_hours",
    "planning_state",
    "planning_blocker_code_or_null",
    "earliest_start_utc",
    "due_at_utc",
    "schedule_owner_role",
    "required_participant_role_ids",
    "required_participant_actor_ids",
    "participant_availability_manifest_digest",
    "participant_max_concurrent_tasks_by_actor",
    "review_lead_time_hours",
    "provider_or_hiring_lead_time_hours",
    "budget_currency",
    "estimated_cost_entries_by_domain",
    "estimate_basis_digest",
    "approved_at_utc",
)

TASK_DELIVERY_FIELDS = (
    "task_id",
    "repository_id",
    "base_ref",
    "base_sha",
    "working_branch",
    "planned_files",
    "acceptance_command",
    "expected_result",
    "acceptance_workflow",
    "merge_dependency",
    "rollback_command_or_manifest",
)


@dataclass(frozen=True)
class RecordSchema:
    schema_id: str
    filename: str
    record_format: str
    fields: tuple[str, ...]
    primary_key: tuple[str, ...]
    integer_fields: tuple[str, ...] = ()
    nullable_fields: tuple[str, ...] = ()


RECORD_SCHEMAS = (
    RecordSchema(
        "task_status_v1",
        "task_status.csv",
        "csv",
        TASK_STATUS_FIELDS,
        ("id",),
        ("next_attempt_sequence", "task_version"),
    ),
    RecordSchema(
        "gate_status_v1",
        "gate_status.csv",
        "csv",
        GATE_STATUS_FIELDS,
        ("gate_id",),
        ("gate_version",),
    ),
    RecordSchema(
        "gate_definition_v1",
        "gate_definitions.csv",
        "csv",
        GATE_DEFINITION_FIELDS,
        ("gate_id",),
    ),
    RecordSchema(
        "readiness_task_event_v1",
        "task_events.jsonl",
        "jsonl",
        TASK_EVENT_FIELDS,
        ("event_id",),
        ("event_sequence", "expected_task_version"),
        tuple(field for field in TASK_EVENT_FIELDS if field.endswith("_or_null")),
    ),
    RecordSchema(
        "readiness_attempt_event_v1",
        "task_attempts.jsonl",
        "jsonl",
        TASK_ATTEMPT_FIELDS,
        ("event_id",),
        ("attempt_sequence", "expected_attempt_version"),
        tuple(field for field in TASK_ATTEMPT_FIELDS if field.endswith("_or_null")),
    ),
    RecordSchema(
        "readiness_gate_event_v1",
        "gate_events.jsonl",
        "jsonl",
        GATE_EVENT_FIELDS,
        ("event_id",),
        ("expected_gate_version",),
        tuple(field for field in GATE_EVENT_FIELDS if field.endswith("_or_null")),
    ),
    RecordSchema(
        "conditional_branch_registry_v1",
        "conditional_branch_registry.csv",
        "csv",
        CONDITIONAL_BRANCH_FIELDS,
        ("branch_id", "task_id"),
    ),
    RecordSchema(
        "task_definition_v1",
        "task_definitions.csv",
        "csv",
        TASK_DEFINITION_FIELDS,
        ("task_id",),
    ),
    RecordSchema(
        "task_planning_input_v1",
        "task_planning_inputs.csv",
        "csv",
        TASK_PLANNING_FIELDS,
        ("task_id",),
    ),
    RecordSchema(
        "task_delivery_manifest_v1",
        "task_delivery_manifest.csv",
        "csv",
        TASK_DELIVERY_FIELDS,
        ("task_id",),
    ),
)


def schema_document(schema: RecordSchema) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for field in schema.fields:
        logical_type: dict[str, Any] = {"type": "integer"} if (
            field in schema.integer_fields
        ) else {"type": "string"}
        if field in schema.nullable_fields:
            logical_type = {"anyOf": [logical_type, {"type": "null"}]}
        properties[field] = logical_type
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://aurora.invalid/schemas/readiness/{schema.schema_id}",
        "title": schema.schema_id,
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": list(schema.fields),
            "properties": properties,
        },
        "x-record-format": schema.record_format,
        "x-filename": schema.filename,
        "x-header-order": list(schema.fields),
        "x-primary-key": list(schema.primary_key),
        "x-canonical-order": "lexicographic_by_primary_key",
    }


def write_schema_documents(root: Path) -> list[Path]:
    destination = root / "config/gtbi/schemas/readiness"
    destination.mkdir(parents=True, exist_ok=True)
    output: list[Path] = []
    for schema in RECORD_SCHEMAS:
        path = destination / f"{schema.schema_id}.schema.json"
        path.write_bytes(canonical_bytes(schema_document(schema)) + b"\n")
        output.append(path)
    return output


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            if set(row) != set(fields):
                missing = sorted(set(fields) - set(row))
                extra = sorted(set(row) - set(fields))
                raise ValueError(f"{path.name}: missing={missing}, extra={extra}")
            writer.writerow(
                {
                    field: (
                        canonical_bytes(value).decode("utf-8")
                        if isinstance(value, (dict, list))
                        else "" if value is None else value
                    )
                    for field, value in row.items()
                }
            )


def read_csv(path: Path, schema: RecordSchema) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != schema.fields:
            raise ValueError(
                f"{path.name}: header mismatch, expected {schema.fields!r}, "
                f"got {tuple(reader.fieldnames or ())!r}"
            )
        rows = list(reader)
    keys = [tuple(row[field] for field in schema.primary_key) for row in rows]
    if keys != sorted(keys):
        raise ValueError(f"{path.name}: rows are not ordered by primary key")
    if len(keys) != len(set(keys)):
        raise ValueError(f"{path.name}: duplicate primary key")
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(canonical_bytes(row) + b"\n" for row in rows))


def read_jsonl(path: Path, schema: RecordSchema) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_bytes().splitlines(), 1):
        row = json.loads(line)
        if tuple(row) == schema.fields:
            # Canonical JSON orders object keys, so field insertion order is not
            # semantically relevant. This branch only avoids an unnecessary set.
            pass
        if set(row) != set(schema.fields):
            raise ValueError(f"{path.name}:{number}: exact field set mismatch")
        if line != canonical_bytes(row):
            raise ValueError(f"{path.name}:{number}: non-canonical JSON")
        rows.append(row)
    keys = [tuple(row[field] for field in schema.primary_key) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError(f"{path.name}: duplicate primary key")
    return rows
