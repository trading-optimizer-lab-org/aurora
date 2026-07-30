"""Fail-closed readiness event validation and bootstrap controller policy."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from infra.gtbi_v7_readiness.canonical import domain_digest, require_digest
from infra.gtbi_v7_readiness.records import (
    RECORD_SCHEMAS,
    read_csv,
    read_jsonl,
)

BOOTSTRAP_TASK_ALLOWLIST = frozenset(
    {
        "PREV7-0000",
        "PREV7-0001",
        "PREV7-0002",
        "PREV7-0006",
        "PREV7-0009",
        "PREV7-0011",
        "PREV7-0012",
    }
)
BOOTSTRAP_OPERATION_ALLOWLIST = frozenset(
    {
        "append_task_event",
        "freeze_inventory",
        "record_teardown_receipt",
        "record_cost_receipt",
    }
)
TASK_TRANSITIONS = {
    "blocked": frozenset({"ready", "cancelled"}),
    "ready": frozenset({"in_progress", "blocked", "cancelled"}),
    "in_progress": frozenset({"review", "blocked", "cancelled"}),
    "review": frozenset({"done", "in_progress", "blocked", "cancelled"}),
    "done": frozenset(),
    "cancelled": frozenset(),
}
GATE_TRANSITIONS = {
    "red": frozenset({"red", "green", "not_applicable"}),
    "green": frozenset({"green", "red"}),
    "not_applicable": frozenset({"not_applicable", "red"}),
}
ATTEMPT_TRANSITIONS = {
    "created": frozenset({"in_progress", "cancelled"}),
    "in_progress": frozenset({"review", "failed", "cancelled"}),
    "review": frozenset({"succeeded", "in_progress", "failed", "cancelled"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}
_NO_GO_TXN_RE = re.compile(r"^NO_GO_CLOSE-[1-9][0-9]*$")
_BOOTSTRAP_TXN_RE = re.compile(
    r"^(?:BOOTSTRAP_FOUNDATION_TXN-1|BOOTSTRAP_FOUNDATION_CLOSE-[1-9][0-9]*)$"
)


class ReadinessValidationError(ValueError):
    """Raised when a readiness record or operation fails closed."""


@dataclass(frozen=True)
class BootstrapOperation:
    operation: str
    transaction_id: str
    task_id: str | None = None
    proposed_gate_status: str | None = None


def validate_bootstrap_operation(operation: BootstrapOperation) -> None:
    if operation.operation not in BOOTSTRAP_OPERATION_ALLOWLIST:
        raise ReadinessValidationError(
            f"bootstrap operation is not allowed: {operation.operation}"
        )
    if operation.task_id is not None and (
        operation.task_id not in BOOTSTRAP_TASK_ALLOWLIST
    ):
        raise ReadinessValidationError(
            f"bootstrap task is not allowed: {operation.task_id}"
        )
    if operation.proposed_gate_status == "green":
        raise ReadinessValidationError("bootstrap controller cannot green a gate")
    if not (
        _NO_GO_TXN_RE.fullmatch(operation.transaction_id)
        or _BOOTSTRAP_TXN_RE.fullmatch(operation.transaction_id)
    ):
        raise ReadinessValidationError(
            "transaction is outside the closed bootstrap namespace"
        )
    if operation.operation == "append_task_event" and operation.task_id is None:
        raise ReadinessValidationError("task event operation requires task_id")


def _validate_chain(
    rows: Iterable[dict[str, Any]],
    *,
    identity_field: str,
    status_field: str,
    predecessor_status_field: str,
    predecessor_digest_field: str,
    sequence_field: str | None,
    digest_field: str,
    domain: str,
    transitions: dict[str, frozenset[str]],
) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    event_ids: set[str] = set()
    for row in rows:
        event_id = str(row["event_id"])
        if event_id in event_ids:
            raise ReadinessValidationError(f"duplicate event_id {event_id}")
        event_ids.add(event_id)
        grouped[str(row[identity_field])].append(row)

    for identity, events in grouped.items():
        previous: dict[str, Any] | None = None
        for index, row in enumerate(events):
            if row[status_field] not in transitions:
                raise ReadinessValidationError(
                    f"{identity}: unknown status {row[status_field]}"
                )
            if sequence_field is not None and int(row[sequence_field]) != index:
                raise ReadinessValidationError(
                    f"{identity}: expected sequence {index}"
                )
            previous_status = row[predecessor_status_field]
            previous_digest = row[predecessor_digest_field]
            if previous is None:
                if previous_status is not None or previous_digest is not None:
                    raise ReadinessValidationError(
                        f"{identity}: genesis predecessor must be null"
                    )
            else:
                if previous_status != previous[status_field]:
                    raise ReadinessValidationError(
                        f"{identity}: predecessor status mismatch"
                    )
                if previous_digest != previous[digest_field]:
                    raise ReadinessValidationError(
                        f"{identity}: predecessor digest mismatch"
                    )
                if row[status_field] not in transitions[previous[status_field]]:
                    raise ReadinessValidationError(
                        f"{identity}: illegal transition "
                        f"{previous[status_field]} -> {row[status_field]}"
                    )
            expected = domain_digest(
                domain, row, omit_top_level_fields=(digest_field,)
            )
            require_digest(str(row[digest_field]))
            if row[digest_field] != expected:
                raise ReadinessValidationError(f"{identity}: event digest mismatch")
            previous = row


def validate_task_event_chain(rows: Iterable[dict[str, Any]]) -> None:
    _validate_chain(
        rows,
        identity_field="task_id",
        status_field="new_status",
        predecessor_status_field="previous_status_or_null",
        predecessor_digest_field="previous_task_event_digest_or_null",
        sequence_field="event_sequence",
        digest_field="event_digest",
        domain="GTBI_READINESS_TASK_EVENT_V1",
        transitions=TASK_TRANSITIONS,
    )


def validate_gate_event_chain(rows: Iterable[dict[str, Any]]) -> None:
    _validate_chain(
        rows,
        identity_field="gate_id",
        status_field="new_status",
        predecessor_status_field="previous_status_or_null",
        predecessor_digest_field="previous_gate_event_digest_or_null",
        sequence_field=None,
        digest_field="event_digest",
        domain="GTBI_READINESS_GATE_EVENT_V1",
        transitions=GATE_TRANSITIONS,
    )


def validate_attempt_event_chain(rows: Iterable[dict[str, Any]]) -> None:
    _validate_chain(
        rows,
        identity_field="task_attempt_id",
        status_field="attempt_status",
        predecessor_status_field="previous_attempt_status_or_null",
        predecessor_digest_field="previous_attempt_event_digest_or_null",
        sequence_field=None,
        digest_field="event_digest",
        domain="GTBI_READINESS_ATTEMPT_EVENT_V1",
        transitions=ATTEMPT_TRANSITIONS,
    )


def validate_current_readiness_records(
    repository_root: Path,
) -> dict[str, Any]:
    """Validate append-only chains and their current CSV projections."""
    root = repository_root.resolve()
    readiness = root / "docs/readiness/gtbi-v7"
    schemas = {schema.filename: schema for schema in RECORD_SCHEMAS}
    task_rows = read_csv(
        readiness / "task_status.csv",
        schemas["task_status.csv"],
    )
    gate_rows = read_csv(
        readiness / "gate_status.csv",
        schemas["gate_status.csv"],
    )
    task_events = read_jsonl(
        readiness / "task_events.jsonl",
        schemas["task_events.jsonl"],
    )
    attempt_events = read_jsonl(
        readiness / "task_attempts.jsonl",
        schemas["task_attempts.jsonl"],
    )
    gate_events = read_jsonl(
        readiness / "gate_events.jsonl",
        schemas["gate_events.jsonl"],
    )
    validate_task_event_chain(task_events)
    validate_attempt_event_chain(attempt_events)
    validate_gate_event_chain(gate_events)

    task_events_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in task_events:
        task_events_by_id[str(event["task_id"])].append(event)
    attempts_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in attempt_events:
        attempts_by_task[str(event["task_id"])].append(event)
    status_by_id = {str(row["id"]): row for row in task_rows}
    for task_id, task in status_by_id.items():
        events = task_events_by_id.get(task_id, [])
        if not events:
            raise ReadinessValidationError(
                f"{task_id}: missing task event chain"
            )
        if task["status"] != events[-1]["new_status"]:
            raise ReadinessValidationError(
                f"{task_id}: status projection mismatch"
            )
        if int(task["task_version"]) != len(events):
            raise ReadinessValidationError(
                f"{task_id}: task version projection mismatch"
            )
        task_attempts = attempts_by_task.get(task_id, [])
        sequences = {
            int(event["attempt_sequence"]) for event in task_attempts
        }
        expected_next = max(sequences, default=0) + 1
        if int(task["next_attempt_sequence"]) != expected_next:
            raise ReadinessValidationError(
                f"{task_id}: next attempt sequence mismatch"
            )
        if task_attempts:
            if task["current_attempt_id"] != task_attempts[-1][
                "task_attempt_id"
            ]:
                raise ReadinessValidationError(
                    f"{task_id}: current attempt projection mismatch"
                )
        elif task["current_attempt_id"]:
            raise ReadinessValidationError(
                f"{task_id}: projected attempt has no event chain"
            )

    gate_events_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in gate_events:
        gate_events_by_id[str(event["gate_id"])].append(event)
    for gate in gate_rows:
        gate_id = str(gate["gate_id"])
        events = gate_events_by_id.get(gate_id, [])
        if not events:
            raise ReadinessValidationError(
                f"{gate_id}: missing gate event chain"
            )
        if gate["status"] != events[-1]["new_status"]:
            raise ReadinessValidationError(
                f"{gate_id}: gate status projection mismatch"
            )
        if int(gate["gate_version"]) != len(events):
            raise ReadinessValidationError(
                f"{gate_id}: gate version projection mismatch"
            )
        if gate["gate_attempt_id"] != events[-1]["gate_attempt_id"]:
            raise ReadinessValidationError(
                f"{gate_id}: gate attempt projection mismatch"
            )

    for task in task_rows:
        if task["status"] not in {"done", "cancelled"}:
            continue
        for dependency in json.loads(task["dependencies"]):
            dependency_row = status_by_id[str(dependency)]
            if dependency_row["status"] not in {"done", "cancelled"}:
                raise ReadinessValidationError(
                    f"{task['id']}: terminal task has open dependency "
                    f"{dependency}"
                )

    return {
        "task_count": len(task_rows),
        "task_event_count": len(task_events),
        "attempt_event_count": len(attempt_events),
        "gate_count": len(gate_rows),
        "gate_event_count": len(gate_events),
        "terminal_task_ids": [
            row["id"]
            for row in task_rows
            if row["status"] in {"done", "cancelled"}
        ],
    }
