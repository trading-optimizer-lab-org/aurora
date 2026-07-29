"""Fail-closed readiness event validation and bootstrap controller policy."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from infra.gtbi_v7_readiness.canonical import domain_digest, require_digest

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
