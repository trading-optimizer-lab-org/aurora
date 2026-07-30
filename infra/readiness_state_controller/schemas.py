"""JSON Schema contracts for closed readiness-controller messages."""

from __future__ import annotations

from typing import Any

SHA256_PATTERN = "^sha256:[0-9a-f]{64}$"
COMMIT_PATTERN = "^[0-9a-f]{40}$"


def _closed_object(
    properties: dict[str, Any],
    *,
    required: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(required or tuple(properties)),
        "properties": properties,
    }


def transition_manifest_schema() -> dict[str, Any]:
    digest = {"type": "string", "pattern": SHA256_PATTERN}
    readiness_path = {
        "type": "string",
        "pattern": "^docs/readiness/gtbi-v7/[A-Za-z0-9._/-]+$",
    }
    task_action = _closed_object(
        {
            "task_id": {
                "type": "string",
                "pattern": "^PREV7-[0-9]{4}$",
            },
            "target_status": {"enum": ["done", "cancelled"]},
            "evidence_paths": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": readiness_path,
            },
            "evidence_sha256": {
                "type": "array",
                "minItems": 1,
                "items": digest,
            },
            "terminal_reason": {"type": "string", "minLength": 1},
            "notes": {"type": "string"},
            "files_touched": {
                "type": "array",
                "items": readiness_path,
            },
            "expected_result": {"type": "string", "minLength": 1},
            "alternative_completion_receipt_set_digest_or_null": {
                "anyOf": [digest, {"type": "null"}]
            },
        }
    )
    branch_action = _closed_object(
        {
            "branch_id": {"type": "string", "minLength": 1},
            "task_id": {
                "type": "string",
                "pattern": "^PREV7-[0-9]{4}$",
            },
            "selected_successor": {"type": "string", "minLength": 1},
            "predicate_evidence_digest": digest,
            "decision_receipt_digest": digest,
        }
    )
    gate_action = _closed_object(
        {
            "gate_id": {
                "type": "string",
                "pattern": "^G(?:0|1A|1B|2|3A|3B|4|5|6|7|8|9|9X|10)$",
            },
            "target_status": {"enum": ["green", "not_applicable"]},
            "selected_branch_id_or_null": {
                "anyOf": [{"type": "string"}, {"type": "null"}]
            },
            "inventory_snapshot_digest": digest,
            "evidence_bundle_digest": digest,
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "https://aurora.invalid/schemas/readiness/"
            "gtbi_v7_readiness_transition_manifest_v1"
        ),
        "title": "gtbi_v7_readiness_transition_manifest_v1",
        **_closed_object(
            {
                "schema_version": {
                    "const": "gtbi_v7_readiness_transition_manifest_v1"
                },
                "manifest_id": {
                    "type": "string",
                    "pattern": "^[a-z0-9][a-z0-9_-]{0,63}$",
                },
                "transaction_id": {
                    "type": "string",
                    "pattern": (
                        "^G(?:0|1A|1B|2|3A|3B|4|5|6|7|8|9|9X|10)"
                        "_CLOSE-[1-9][0-9]*$"
                    ),
                },
                "requested_at_utc": {
                    "type": "string",
                    "format": "date-time",
                },
                "actor_id": {"type": "string", "minLength": 1},
                "actor_role": {"const": "repository_owner"},
                "expected_base_ref": {"const": "refs/heads/main"},
                "expected_base_sha_mode": {
                    "const": "runtime_default_branch_head"
                },
                "task_actions": {
                    "type": "array",
                    "minItems": 1,
                    "items": task_action,
                },
                "branch_actions": {
                    "type": "array",
                    "items": branch_action,
                },
                "gate_actions": {
                    "type": "array",
                    "items": gate_action,
                },
                "owner_directive_digest": digest,
                "manifest_digest": digest,
            }
        ),
    }


def state_controller_receipt_schema() -> dict[str, Any]:
    task = _closed_object(
        {
            "task_id": {
                "type": "string",
                "pattern": "^PREV7-[0-9]{4}$",
            },
            "target_status": {"enum": ["done", "cancelled"]},
        }
    )
    branch = _closed_object(
        {
            "branch_id": {"type": "string", "minLength": 1},
            "task_id": {
                "type": "string",
                "pattern": "^PREV7-[0-9]{4}$",
            },
        }
    )
    gate = _closed_object(
        {
            "gate_id": {"type": "string", "minLength": 2},
            "target_status": {"enum": ["green", "not_applicable"]},
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "https://aurora.invalid/schemas/readiness/"
            "gtbi_v7_state_controller_receipt_v1"
        ),
        "title": "gtbi_v7_state_controller_receipt_v1",
        **_closed_object(
            {
                "schema_version": {
                    "const": "gtbi_v7_state_controller_receipt_v1"
                },
                "controller_version": {
                    "const": "gtbi_v7_readiness_state_controller_v1"
                },
                "manifest_id": {"type": "string", "minLength": 1},
                "manifest_digest": {
                    "type": "string",
                    "pattern": SHA256_PATTERN,
                },
                "transaction_id": {"type": "string", "minLength": 1},
                "base_ref": {"const": "refs/heads/main"},
                "base_sha": {
                    "type": "string",
                    "pattern": COMMIT_PATTERN,
                },
                "actor_id": {"type": "string", "minLength": 1},
                "task_actions_applied": {
                    "type": "array",
                    "items": task,
                },
                "branch_actions_applied": {
                    "type": "array",
                    "items": branch,
                },
                "gate_actions_applied": {
                    "type": "array",
                    "items": gate,
                },
                "output_sha256": {
                    "type": "object",
                    "minProperties": 1,
                    "additionalProperties": {
                        "type": "string",
                        "pattern": SHA256_PATTERN,
                    },
                },
                "scientific_work_performed": {"const": False},
                "locked_data_accessed": {"const": False},
                "arbitrary_command_execution_supported": {"const": False},
                "receipt_digest": {
                    "type": "string",
                    "pattern": SHA256_PATTERN,
                },
            }
        ),
    }


def schema_documents() -> dict[str, dict[str, Any]]:
    return {
        "gtbi_v7_readiness_transition_manifest_v1.schema.json": (
            transition_manifest_schema()
        ),
        "gtbi_v7_state_controller_receipt_v1.schema.json": (
            state_controller_receipt_schema()
        ),
    }


__all__ = [
    "schema_documents",
    "state_controller_receipt_schema",
    "transition_manifest_schema",
]
