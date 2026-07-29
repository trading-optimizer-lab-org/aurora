"""Deterministic provisional genesis records for the GTBI V7 plan."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import (
    canonical_bytes,
    domain_digest,
    raw_sha256,
)
from infra.gtbi_v7_readiness.controller import (
    validate_gate_event_chain,
    validate_task_event_chain,
)
from infra.gtbi_v7_readiness.records import (
    CONDITIONAL_BRANCH_FIELDS,
    GATE_DEFINITION_FIELDS,
    GATE_EVENT_FIELDS,
    GATE_STATUS_FIELDS,
    RECORD_SCHEMAS,
    TASK_ATTEMPT_FIELDS,
    TASK_DEFINITION_FIELDS,
    TASK_DELIVERY_FIELDS,
    TASK_EVENT_FIELDS,
    TASK_PLANNING_FIELDS,
    TASK_STATUS_FIELDS,
    read_csv,
    read_jsonl,
    write_csv,
    write_jsonl,
)
from infra.gtbi_v7_readiness.structure import MasterPlanModel, load_master_plan_model

OWNER_ACTOR_ID = "github-user:271768688"
REPOSITORY_ID = "trading-optimizer-lab-org/aurora"
WORKING_BRANCH = "codex/gtbi-v7-master-plan-bootstrap"
GENESIS_TRANSACTION_ID = "BOOTSTRAP_FOUNDATION_TXN-1"
PLANNING_BLOCKER = "COST_ESTIMATE_NOT_FROZEN"

BRANCH_TASKS: dict[str, tuple[str, ...]] = {
    "V6_FINAL_SOURCE": ("PREV7-0003",),
    "EMERGENCY_ESCROW": ("PREV7-0012",),
    "V6_INPUT_IDENTITY": ("PREV7-0307",),
    "G0_BOOTSTRAP_DISPOSITION": ("PREV7-0011",),
    "PR20_DISPOSITION": ("PREV7-0502",),
    "LOCAL_ADMINISTRATION": (
        "PREV7-0402",
        "PREV7-0403",
        "PREV7-0404",
        "PREV7-0405",
        "PREV7-0406",
        "PREV7-0407",
    ),
    "EXECUTION_TOPOLOGY": ("PREV7-0309",),
    "CAPACITY_TOPOLOGY": ("PREV7-0309",),
    "FORWARD_LOCK": ("PREV7-0504",),
    "G7_DISPOSITION": ("PREV7-0715",),
    "ABANDONED_DISPATCH_BOUNDARY": ("PREV7-0914",),
    "APP_PRIVATE_KEY_IMPORT": ("PREV7-0204", "PREV7-0308"),
}

FULL_DISPOSITION_SUCCESSORS: dict[str, str] = {
    "PREV7-0815": "PREV7-0910",
    "PREV7-0808": "PREV7-0910",
    "PREV7-0810": "PREV7-0910",
    "PREV7-0811": "PREV7-0910",
    "PREV7-0812": "PREV7-0910",
    "PREV7-0813": "PREV7-0910",
    "PREV7-0310": "PREV7-0910",
    "PREV7-0801": "PREV7-0910",
    "PREV7-0805": "PREV7-0910",
    "PREV7-0802": "PREV7-0910",
    "PREV7-0803": "PREV7-0910",
    "PREV7-0809": "PREV7-0910",
    "PREV7-0816": "PREV7-0910",
    "PREV7-0804": "PREV7-0910",
    "PREV7-0807": "PREV7-0910",
    "PREV7-0806": "PREV7-0914",
    "PREV7-0901": "PREV7-0914",
    "PREV7-0902": "PREV7-0914",
    "PREV7-0904": "PREV7-0914",
    "PREV7-0905": "PREV7-0910",
    "PREV7-0906": "PREV7-0911",
    "PREV7-0907": "PREV7-0912",
    "PREV7-0903": "PREV7-0912",
    "PREV7-0910": "PREV7-0905",
    "PREV7-0914": "PREV7-0904",
    "PREV7-0911": "PREV7-0906",
    "PREV7-0912": "PREV7-0907",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _payload_digest(value: Any) -> str:
    return raw_sha256(canonical_bytes(value))


def _role(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _branch_rows(model: MasterPlanModel) -> list[dict[str, Any]]:
    known_tasks = {task.task_id for task in model.tasks}
    rows: list[dict[str, Any]] = []
    for branch_id, task_ids in BRANCH_TASKS.items():
        predicate = {
            "branch_id": branch_id,
            "decision_state": "not_yet_decided_blocked",
        }
        for task_id in task_ids:
            if task_id not in known_tasks:
                raise ValueError(f"{branch_id}: unknown task {task_id}")
            rows.append(
                {
                    "branch_id": branch_id,
                    "task_id": task_id,
                    "predicate_schema_digest": _payload_digest(predicate),
                    "predicate_evidence_digest": "",
                    "selected_successor": "",
                    "unselected_alternative_completion": (
                        "decision_not_yet_selected"
                    ),
                    "invalidated_evidence_classes": [],
                    "affected_gates": [
                        model.primary_gate_by_task[task_id]
                    ],
                    "decision_actor_id": "",
                    "decision_receipt_digest": "",
                }
            )
    predicate = {
        "branch_id": "FULL_DISPOSITION",
        "decision_state": "not_yet_decided_blocked",
    }
    for task_id, successor in FULL_DISPOSITION_SUCCESSORS.items():
        if task_id not in known_tasks or successor not in known_tasks:
            raise ValueError(
                f"FULL_DISPOSITION: unknown mapping {task_id} -> {successor}"
            )
        rows.append(
            {
                "branch_id": "FULL_DISPOSITION",
                "task_id": task_id,
                "predicate_schema_digest": _payload_digest(predicate),
                "predicate_evidence_digest": "",
                "selected_successor": "",
                "unselected_alternative_completion": successor,
                "invalidated_evidence_classes": [],
                "affected_gates": [
                    model.primary_gate_by_task[task_id],
                    model.primary_gate_by_task[successor],
                ],
                "decision_actor_id": "",
                "decision_receipt_digest": "",
            }
        )
    return sorted(rows, key=lambda row: (row["branch_id"], row["task_id"]))


def build_initial_records(repository_root: Path) -> dict[str, list[dict[str, Any]]]:
    """Build a truthful, blocked projection without claiming genesis completion."""
    root = repository_root.resolve()
    readiness = root / "docs/readiness/gtbi-v7"
    plan_path = root / "docs/plans/gtbi-v7-master-plan.md"
    model = load_master_plan_model(plan_path)
    directive = _read_json(readiness / "owner_simplification_directive.json")
    inventory = _read_json(root / "docs/project_inventory/audit_metadata.json")
    role_registry_path = (
        root
        / "config/gtbi/fixtures/v7/governance/"
        "role_registry_v1.owner_controlled.json"
    )
    observed_at = str(directive["effective_at_utc"])
    base_sha = str(inventory["default_branch_sha"])
    role_registry_digest = raw_sha256(role_registry_path)
    estimate_basis_digest = raw_sha256(plan_path)
    actor_concurrency = {OWNER_ACTOR_ID: 1}

    gate_definitions: list[dict[str, Any]] = []
    for gate in model.gates:
        row = {
            "gate_id": gate.gate_id,
            "prerequisite_gate_ids": sorted(gate.prerequisite_gate_ids),
            "required_task_ids": sorted(gate.required_task_ids),
            "required_condition": gate.required_condition,
            "branch_policy": (
                "conditional_branch_registry.csv; "
                "owner_simplification_directive_v1"
            ),
            "gate_definition_digest": "",
        }
        row["gate_definition_digest"] = domain_digest(
            "GTBI_GATE_DEFINITION_V1",
            row,
            omit_top_level_fields=("gate_definition_digest",),
        )
        gate_definitions.append(row)
    gate_definitions.sort(key=lambda row: row["gate_id"])
    gate_definition_by_id = {
        row["gate_id"]: row for row in gate_definitions
    }

    planning_rows: list[dict[str, Any]] = []
    task_definitions: list[dict[str, Any]] = []
    task_statuses: list[dict[str, Any]] = []
    task_events: list[dict[str, Any]] = []
    delivery_rows: list[dict[str, Any]] = []
    for task in model.tasks:
        gate_id = model.primary_gate_by_task[task.task_id]
        participant_roles = [_role(task.owner_role)]
        participant_actors = [OWNER_ACTOR_ID]
        planning = {
            "task_id": task.task_id,
            "estimated_work_hours": "",
            "estimated_elapsed_hours": "",
            "external_lead_time_hours": "",
            "planning_state": "blocked_missing_price",
            "planning_blocker_code_or_null": PLANNING_BLOCKER,
            "earliest_start_utc": "",
            "due_at_utc": "",
            "schedule_owner_role": _role(task.owner_role),
            "required_participant_role_ids": participant_roles,
            "required_participant_actor_ids": participant_actors,
            "participant_availability_manifest_digest": role_registry_digest,
            "participant_max_concurrent_tasks_by_actor": actor_concurrency,
            "review_lead_time_hours": "",
            "provider_or_hiring_lead_time_hours": "",
            "budget_currency": "USD",
            "estimated_cost_entries_by_domain": {},
            "estimate_basis_digest": estimate_basis_digest,
            "approved_at_utc": "",
        }
        planning_rows.append(planning)

        definition = {
            "task_id": task.task_id,
            "task_definition_digest": "",
            "title": task.required_output,
            "gate": gate_id,
            "priority": task.priority,
            "owner_role": task.owner_role,
            "dependencies": sorted(task.dependencies),
            "required_approver_roles": [],
            "approval_policy_digest": _payload_digest(
                {
                    "policy": "owner_controlled",
                    "owner_actor_id": OWNER_ACTOR_ID,
                }
            ),
            "required_evidence_classification": (
                "provisional_git_bootstrap"
            ),
            "exact_inputs": "",
            "entry_conditions": "",
            "exact_outputs": task.required_output,
            "acceptance_criteria": "",
            "activation_condition": "",
            "alternative_completion": "",
            "cancel_condition": "",
            "rollback": "",
            "rollback_trigger": "",
            "repository_id": REPOSITORY_ID,
            "planned_files": [],
            "acceptance_command": "",
            "expected_result": task.required_output,
            "merge_dependency": "",
            "estimated_work_hours": "",
            "estimated_elapsed_hours": "",
            "external_lead_time_hours": "",
            "planning_state": planning["planning_state"],
            "planning_blocker_code_or_null": planning[
                "planning_blocker_code_or_null"
            ],
            "planned_start_utc": "",
            "due_at_utc": "",
            "latest_start_utc": "",
            "schedule_owner_role": planning["schedule_owner_role"],
            "required_participant_role_ids": participant_roles,
            "required_participant_actor_ids": participant_actors,
            "participant_availability_manifest_digest": (
                role_registry_digest
            ),
            "participant_max_concurrent_tasks_by_actor": actor_concurrency,
            "review_lead_time_hours": "",
            "provider_or_hiring_lead_time_hours": "",
            "budget_currency": "USD",
            "estimated_cost_entries_by_domain": {},
        }
        definition["task_definition_digest"] = domain_digest(
            "GTBI_TASK_DEFINITION_V1",
            definition,
            omit_top_level_fields=("task_definition_digest",),
        )
        task_definitions.append(definition)

        status = {
            "id": task.task_id,
            "current_attempt_id": "",
            "next_attempt_sequence": 1,
            "task_version": 1,
            "title": task.required_output,
            "gate": gate_id,
            "priority": task.priority,
            "owner_role": task.owner_role,
            "owner_actor_id": OWNER_ACTOR_ID,
            "status": "blocked",
            "dependencies": sorted(task.dependencies),
            "exact_inputs": "",
            "entry_conditions": "",
            "blocking_reason": PLANNING_BLOCKER,
            "github_issue": "",
            "pull_request": (
                "https://github.com/trading-optimizer-lab-org/aurora/"
                "pull/21"
            ),
            "exact_outputs": task.required_output,
            "acceptance_criteria": "",
            "evidence_paths": [],
            "evidence_sha256": [],
            "evidence_classification": "provisional_git_bootstrap",
            "private_evidence_id": "",
            "redaction_review": "not_required_owner_controlled",
            "acceptance_workflow": "gtbi-v7-master-plan-quality.yml",
            "acceptance_run_id": "",
            "rollback": "",
            "approved_by": "",
            "approved_at": "",
            "required_approver_roles": [],
            "approval_receipt_set_digest": "",
            "alternative_completion_receipt_set_digest": "",
            "activation_condition": "",
            "alternative_completion": "",
            "cancel_condition": "",
            "superseded_by": "",
            "rollback_trigger": "",
            "started_at": "",
            "completed_at": "",
            "notes": (
                "Initial blocked projection; no completion or approval "
                "is claimed."
            ),
            "repository_id": REPOSITORY_ID,
            "base_ref": "refs/heads/main",
            "base_sha": base_sha,
            "working_branch": WORKING_BRANCH,
            "head_sha": "",
            "merge_sha": "",
            "files_touched": [],
            "acceptance_command": "",
            "expected_result": task.required_output,
            "merge_dependency": "",
            "estimated_work_hours": "",
            "estimated_elapsed_hours": "",
            "external_lead_time_hours": "",
            "planning_state": planning["planning_state"],
            "planning_blocker_code_or_null": planning[
                "planning_blocker_code_or_null"
            ],
            "planned_start_utc": "",
            "due_at_utc": "",
            "latest_start_utc": "",
            "schedule_owner_actor_id": OWNER_ACTOR_ID,
            "required_participant_role_ids": participant_roles,
            "required_participant_actor_ids": participant_actors,
            "participant_availability_manifest_digest": (
                role_registry_digest
            ),
            "participant_max_concurrent_tasks_by_actor": actor_concurrency,
            "review_lead_time_hours": "",
            "provider_or_hiring_lead_time_hours": "",
            "budget_currency": "USD",
            "estimated_cost_entries_by_domain": {},
        }
        task_statuses.append(status)

        event = {
            "schema_version": "readiness_task_event_v1",
            "event_id": f"{task.task_id}-genesis-0000",
            "transaction_id": GENESIS_TRANSACTION_ID,
            "task_id": task.task_id,
            "task_attempt_id_or_null": None,
            "event_sequence": 0,
            "previous_status_or_null": None,
            "new_status": "blocked",
            "actor_id": OWNER_ACTOR_ID,
            "actor_role": "repository_owner",
            "transitioned_at_utc": observed_at,
            "evaluated_commit_sha": base_sha,
            "expected_task_version": 0,
            "dependency_snapshot_digest": _payload_digest(
                sorted(task.dependencies)
            ),
            "gate_snapshot_digest": gate_definition_by_id[gate_id][
                "gate_definition_digest"
            ],
            "evidence_digest_or_null": None,
            "alternative_completion_receipt_set_digest_or_null": None,
            "previous_task_event_digest_or_null": None,
            "event_digest": "",
        }
        event["event_digest"] = domain_digest(
            "GTBI_READINESS_TASK_EVENT_V1",
            event,
            omit_top_level_fields=("event_digest",),
        )
        task_events.append(event)

        delivery_rows.append(
            {
                "task_id": task.task_id,
                "repository_id": REPOSITORY_ID,
                "base_ref": "refs/heads/main",
                "base_sha": base_sha,
                "working_branch": WORKING_BRANCH,
                "planned_files": [],
                "acceptance_command": "",
                "expected_result": task.required_output,
                "acceptance_workflow": "gtbi-v7-master-plan-quality.yml",
                "merge_dependency": "",
                "rollback_command_or_manifest": "",
            }
        )

    gate_statuses: list[dict[str, Any]] = []
    gate_events: list[dict[str, Any]] = []
    inventory_digest = str(inventory["snapshot_digest"])
    empty_evidence_digest = _payload_digest([])
    for gate_definition in gate_definitions:
        gate_id = gate_definition["gate_id"]
        required_task_ids = gate_definition["required_task_ids"]
        required_task_set_digest = _payload_digest(required_task_ids)
        required_condition_digest = _payload_digest(
            gate_definition["required_condition"]
        )
        gate_statuses.append(
            {
                "gate_id": gate_id,
                "gate_attempt_id": f"{gate_id}-attempt-0000",
                "gate_version": 1,
                "status": "red",
                "prerequisite_gate_ids": gate_definition[
                    "prerequisite_gate_ids"
                ],
                "gate_definition_digest": gate_definition[
                    "gate_definition_digest"
                ],
                "evaluated_required_task_ids": required_task_ids,
                "required_task_id_set_digest": required_task_set_digest,
                "required_condition_digest": required_condition_digest,
                "selected_branch_id_or_null": "",
                "inventory_snapshot_digest_or_null": inventory_digest,
                "evidence_bundle_digest": empty_evidence_digest,
                "blocking_reason": "required_tasks_not_done",
                "evaluated_at_utc": observed_at,
                "evaluated_commit_sha": base_sha,
            }
        )
        gate_event = {
            "schema_version": "readiness_gate_event_v1",
            "event_id": f"{gate_id}-genesis-0000",
            "transaction_id": GENESIS_TRANSACTION_ID,
            "gate_id": gate_id,
            "gate_attempt_id": f"{gate_id}-attempt-0000",
            "previous_status_or_null": None,
            "new_status": "red",
            "expected_gate_version": 0,
            "previous_gate_event_digest_or_null": None,
            "required_task_id_set_digest": required_task_set_digest,
            "required_condition_digest": required_condition_digest,
            "selected_branch_id_or_null": None,
            "inventory_snapshot_digest_or_null": inventory_digest,
            "evidence_bundle_digest": empty_evidence_digest,
            "actor_id": OWNER_ACTOR_ID,
            "actor_role": "repository_owner",
            "transitioned_at_utc": observed_at,
            "evaluated_commit_sha": base_sha,
            "event_digest": "",
        }
        gate_event["event_digest"] = domain_digest(
            "GTBI_READINESS_GATE_EVENT_V1",
            gate_event,
            omit_top_level_fields=("event_digest",),
        )
        gate_events.append(gate_event)

    return {
        "task_status.csv": sorted(task_statuses, key=lambda row: row["id"]),
        "gate_status.csv": sorted(
            gate_statuses, key=lambda row: row["gate_id"]
        ),
        "gate_definitions.csv": gate_definitions,
        "task_events.jsonl": sorted(
            task_events, key=lambda row: row["task_id"]
        ),
        "task_attempts.jsonl": [],
        "gate_events.jsonl": sorted(
            gate_events, key=lambda row: row["gate_id"]
        ),
        "conditional_branch_registry.csv": _branch_rows(model),
        "task_definitions.csv": sorted(
            task_definitions, key=lambda row: row["task_id"]
        ),
        "task_planning_inputs.csv": sorted(
            planning_rows, key=lambda row: row["task_id"]
        ),
        "task_delivery_manifest.csv": sorted(
            delivery_rows, key=lambda row: row["task_id"]
        ),
    }


def write_initial_records(repository_root: Path) -> list[Path]:
    """Write all ten canonical projections and return their paths."""
    root = repository_root.resolve()
    destination = root / "docs/readiness/gtbi-v7"
    records = build_initial_records(root)
    schema_by_filename = {
        schema.filename: schema for schema in RECORD_SCHEMAS
    }
    paths: list[Path] = []
    for filename, rows in records.items():
        schema = schema_by_filename[filename]
        path = destination / filename
        if schema.record_format == "csv":
            write_csv(path, schema.fields, rows)
        else:
            write_jsonl(path, rows)
        paths.append(path)
    return paths


def validate_initial_records(repository_root: Path) -> None:
    """Validate exact coverage, projections, chains and fail-closed state."""
    root = repository_root.resolve()
    destination = root / "docs/readiness/gtbi-v7"
    model = load_master_plan_model(
        root / "docs/plans/gtbi-v7-master-plan.md"
    )
    schema_by_filename = {
        schema.filename: schema for schema in RECORD_SCHEMAS
    }
    actual: dict[str, list[dict[str, Any]]] = {}
    for filename, schema in schema_by_filename.items():
        path = destination / filename
        if not path.is_file():
            raise ValueError(f"missing readiness record {filename}")
        actual[filename] = (
            read_csv(path, schema)
            if schema.record_format == "csv"
            else read_jsonl(path, schema)
        )

    task_ids = sorted(task.task_id for task in model.tasks)
    gate_ids = sorted(gate.gate_id for gate in model.gates)
    for filename, key in (
        ("task_status.csv", "id"),
        ("task_definitions.csv", "task_id"),
        ("task_planning_inputs.csv", "task_id"),
        ("task_delivery_manifest.csv", "task_id"),
    ):
        if [row[key] for row in actual[filename]] != task_ids:
            raise ValueError(f"{filename}: task coverage mismatch")
    for filename, key in (
        ("gate_status.csv", "gate_id"),
        ("gate_definitions.csv", "gate_id"),
    ):
        if [row[key] for row in actual[filename]] != gate_ids:
            raise ValueError(f"{filename}: gate coverage mismatch")
    if any(row["status"] != "blocked" for row in actual["task_status.csv"]):
        raise ValueError("initial tasks must all be blocked")
    if any(row["status"] != "red" for row in actual["gate_status.csv"]):
        raise ValueError("initial gates must all be red")
    if actual["task_attempts.jsonl"]:
        raise ValueError("blocked genesis must not fabricate task attempts")
    if len(actual["task_events.jsonl"]) != len(task_ids):
        raise ValueError("task genesis event coverage mismatch")
    if len(actual["gate_events.jsonl"]) != len(gate_ids):
        raise ValueError("gate genesis event coverage mismatch")
    validate_task_event_chain(actual["task_events.jsonl"])
    validate_gate_event_chain(actual["gate_events.jsonl"])

    expected = build_initial_records(root)
    with tempfile.TemporaryDirectory(prefix="gtbi-v7-readiness-") as temp_dir:
        temporary_root = Path(temp_dir)
        for filename, expected_rows in expected.items():
            schema = schema_by_filename[filename]
            if schema.record_format == "csv":
                temporary = temporary_root / filename
                write_csv(temporary, schema.fields, expected_rows)
                expected_bytes = temporary.read_bytes()
                if (destination / filename).read_bytes() != expected_bytes:
                    raise ValueError(
                        f"{filename}: deterministic projection drift"
                    )
            elif actual[filename] != expected_rows:
                raise ValueError(
                    f"{filename}: deterministic projection drift"
                )


__all__ = [
    "BRANCH_TASKS",
    "FULL_DISPOSITION_SUCCESSORS",
    "build_initial_records",
    "validate_initial_records",
    "write_initial_records",
]
