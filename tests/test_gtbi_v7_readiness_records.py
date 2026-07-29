from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from infra.gtbi_v7_readiness.controller import (
    BootstrapOperation,
    ReadinessValidationError,
    validate_bootstrap_operation,
    validate_task_event_chain,
)
from infra.gtbi_v7_readiness.records import RECORD_SCHEMAS, schema_document
from infra.gtbi_v7_readiness.structure import load_master_plan_model

ROOT = Path(__file__).resolve().parents[1]


def _task_event(
    *,
    sequence: int,
    previous_status: str | None,
    new_status: str,
    previous_digest: str | None,
) -> dict:
    row = {
        "schema_version": "readiness_task_event_v1",
        "event_id": f"PREV7-0000-event-{sequence}",
        "transaction_id": "BOOTSTRAP_FOUNDATION_TXN-1",
        "task_id": "PREV7-0000",
        "task_attempt_id_or_null": None,
        "event_sequence": sequence,
        "previous_status_or_null": previous_status,
        "new_status": new_status,
        "actor_id": "fixture-actor",
        "actor_role": "Implementer",
        "transitioned_at_utc": "2026-07-29T12:00:00Z",
        "evaluated_commit_sha": "a" * 40,
        "expected_task_version": sequence,
        "dependency_snapshot_digest": "sha256:" + "1" * 64,
        "gate_snapshot_digest": "sha256:" + "2" * 64,
        "evidence_digest_or_null": None,
        "alternative_completion_receipt_set_digest_or_null": None,
        "previous_task_event_digest_or_null": previous_digest,
        "event_digest": "",
    }
    row["event_digest"] = domain_digest(
        "GTBI_READINESS_TASK_EVENT_V1",
        row,
        omit_top_level_fields=("event_digest",),
    )
    return row


def test_master_plan_model_has_complete_matrix_and_gate_assignment() -> None:
    model = load_master_plan_model(ROOT / "docs/plans/gtbi-v7-master-plan.md")
    assert len(model.tasks) == 110
    assert len(model.gates) == 15
    assert len(model.primary_gate_by_task) == 110
    assert model.primary_gate_by_task["PREV7-0308"] == "G3B"
    assert model.primary_gate_by_task["PREV7-0913"] == "G9"


def test_all_ten_readiness_schemas_are_canonical_valid_json_schema() -> None:
    schema_root = ROOT / "config/gtbi/schemas/readiness"
    assert len(RECORD_SCHEMAS) == 10
    for record_schema in RECORD_SCHEMAS:
        path = schema_root / f"{record_schema.schema_id}.schema.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload == schema_document(record_schema)
        assert path.read_bytes() == canonical_bytes(payload) + b"\n"
        jsonschema.Draft202012Validator.check_schema(payload)


def test_bootstrap_controller_accepts_only_closed_emergency_scope() -> None:
    validate_bootstrap_operation(
        BootstrapOperation(
            operation="append_task_event",
            transaction_id="BOOTSTRAP_FOUNDATION_TXN-1",
            task_id="PREV7-0012",
        )
    )
    with pytest.raises(ReadinessValidationError, match="not allowed"):
        validate_bootstrap_operation(
            BootstrapOperation(
                operation="append_task_event",
                transaction_id="BOOTSTRAP_FOUNDATION_TXN-1",
                task_id="PREV7-0806",
            )
        )
    with pytest.raises(ReadinessValidationError, match="cannot green"):
        validate_bootstrap_operation(
            BootstrapOperation(
                operation="freeze_inventory",
                transaction_id="NO_GO_CLOSE-1",
                proposed_gate_status="green",
            )
        )


def test_task_event_chain_accepts_legal_transition_and_rejects_mutation() -> None:
    genesis = _task_event(
        sequence=0,
        previous_status=None,
        new_status="blocked",
        previous_digest=None,
    )
    ready = _task_event(
        sequence=1,
        previous_status="blocked",
        new_status="ready",
        previous_digest=genesis["event_digest"],
    )
    validate_task_event_chain([genesis, ready])
    ready["actor_id"] = "mutated"
    with pytest.raises(ReadinessValidationError, match="digest mismatch"):
        validate_task_event_chain([genesis, ready])


def test_terminal_task_event_cannot_reopen() -> None:
    genesis = _task_event(
        sequence=0,
        previous_status=None,
        new_status="cancelled",
        previous_digest=None,
    )
    reopened = _task_event(
        sequence=1,
        previous_status="cancelled",
        new_status="blocked",
        previous_digest=genesis["event_digest"],
    )
    with pytest.raises(ReadinessValidationError, match="illegal transition"):
        validate_task_event_chain([genesis, reopened])
