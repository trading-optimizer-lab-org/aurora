"""Reconcile the G3A baseline controller apply with merged readiness state."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import (
    canonical_bytes,
    domain_digest,
    raw_sha256,
)
from infra.gtbi_v7_readiness.controller import (
    validate_current_readiness_records,
)

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"
SOURCE = READINESS / "g3a_state_controller_apply_receipt.json"
DESTINATION = READINESS / "g3a_state_transition_reconciliation_receipt.json"

G3A_COUNTS = {
    "attempt_event_count": 78,
    "gate_count": 15,
    "gate_event_count": 18,
    "task_count": 110,
    "task_event_count": 187,
}
G3A_STATUS_COUNTS = {
    "blocked": 90,
    "cancelled": 1,
    "done": 19,
}
G3A_TASK_STATUSES = {
    "PREV7-0202": "done",
    "PREV7-0204": "blocked",
    "PREV7-0205": "done",
    "PREV7-0206": "done",
    "PREV7-0210": "blocked",
}


def _canonical_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if path.read_bytes() != canonical_bytes(payload) + b"\n":
        raise ValueError(f"{path.name} is not canonical JSON")
    return payload


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def validate_application() -> dict[str, Any]:
    """Validate the raw receipt and append-only partial G3A projection."""
    source = _canonical_json(SOURCE)
    expected_digest = domain_digest(
        "GTBI_V7_STATE_CONTROLLER_RECEIPT_V1",
        source,
        omit_top_level_fields=("receipt_digest",),
    )
    if source["receipt_digest"] != expected_digest:
        raise ValueError("G3A controller receipt digest mismatch")
    if source["scientific_work_performed"]:
        raise ValueError("G3A controller unexpectedly performed science")
    if source["locked_data_accessed"]:
        raise ValueError("G3A controller unexpectedly accessed locked data")
    if source["arbitrary_command_execution_supported"]:
        raise ValueError("G3A controller allowed arbitrary commands")

    current = validate_current_readiness_records(ROOT)
    for key, minimum in G3A_COUNTS.items():
        if int(current[key]) < minimum:
            raise ValueError(f"current readiness state predates G3A: {key}")

    task_rows = {
        row["id"]: row for row in _csv_rows(READINESS / "task_status.csv")
    }
    for task_id, expected_status in G3A_TASK_STATUSES.items():
        if task_rows[task_id]["status"] != expected_status:
            raise ValueError(f"G3A task status mismatch: {task_id}")

    gate_rows = {
        row["gate_id"]: row
        for row in _csv_rows(READINESS / "gate_status.csv")
    }
    if gate_rows["G3A"]["status"] != "red":
        raise ValueError("partial G3A baseline must not make the gate green")
    if gate_rows["G3A"]["blocking_reason"] != "required_tasks_not_done":
        raise ValueError("G3A blocker no longer identifies incomplete tasks")

    task_events = _jsonl_rows(READINESS / "task_events.jsonl")
    applied_task_statuses = {
        event["task_id"]: event["new_status"]
        for event in task_events
        if event["transaction_id"] == source["transaction_id"]
    }
    expected_actions = {
        action["task_id"]: action["target_status"]
        for action in source["task_actions_applied"]
    }
    if applied_task_statuses != expected_actions:
        raise ValueError("G3A task events do not match the controller receipt")

    gate_events = _jsonl_rows(READINESS / "gate_events.jsonl")
    if any(
        event["transaction_id"] == source["transaction_id"]
        for event in gate_events
    ):
        raise ValueError("partial G3A baseline unexpectedly changed the gate")

    exact_projection = all(
        int(current[key]) == value for key, value in G3A_COUNTS.items()
    )
    if exact_projection:
        for relative, expected in source["output_sha256"].items():
            if raw_sha256(ROOT / relative) != expected:
                raise ValueError(f"G3A output hash mismatch: {relative}")
        status_counts = Counter(row["status"] for row in task_rows.values())
        if dict(status_counts) != G3A_STATUS_COUNTS:
            raise ValueError("G3A task status counts mismatch")

    return {
        "append_only_g3a_history_preserved": True,
        "exact_g3a_projection": exact_projection,
        "g3a_counts": G3A_COUNTS,
        "g3a_status_counts": G3A_STATUS_COUNTS,
    }


def build_receipt() -> dict[str, Any]:
    source = _canonical_json(SOURCE)
    validation = validate_application()
    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_g3a_apply_reconciliation_receipt_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "workflow_name": "GTBI V7 Readiness State Controller",
        "workflow_file": "gtbi-v7-readiness-state-controller.yml",
        "event": "workflow_dispatch",
        "mode": "apply",
        "manifest_id": source["manifest_id"],
        "run_id": 30631724300,
        "run_url": (
            "https://github.com/trading-optimizer-lab-org/aurora/"
            "actions/runs/30631724300"
        ),
        "run_status": "completed",
        "run_conclusion": "success",
        "head_sha": source["base_sha"],
        "created_at_utc": "2026-07-31T12:44:28Z",
        "updated_at_utc": "2026-07-31T12:44:52Z",
        "duration_seconds": 24,
        "artifact": {
            "id": 8793598906,
            "name": (
                "gtbi-v7-state-controller-"
                "g3a-minimum-governance-close-v1-30631724300"
            ),
            "size_in_bytes": 1055,
            "archive_digest": (
                "sha256:"
                "0154060e10ea566f4485fdc7630c4f48fea60ea9b987e9ead80240da7e7eba56"
            ),
            "expires_at_utc": "2026-10-29T12:44:29Z",
        },
        "source_receipt_path": (
            "docs/readiness/gtbi-v7/g3a_state_controller_apply_receipt.json"
        ),
        "source_receipt_file_sha256": raw_sha256(SOURCE),
        "source_receipt_digest": source["receipt_digest"],
        "state_pull_request": {
            "number": 47,
            "url": "https://github.com/trading-optimizer-lab-org/aurora/pull/47",
            "merged_at_utc": "2026-07-31T12:58:53Z",
            "merge_sha": "fe3feb3b8b145586693a394adfacf65ca076c489",
        },
        "validation_pull_requests": [
            {
                "number": 44,
                "url": (
                    "https://github.com/trading-optimizer-lab-org/aurora/"
                    "pull/44"
                ),
                "merged_at_utc": "2026-07-31T12:16:42Z",
                "merge_sha": "13dedd551560ef1661fef3dcb5d12d9cc917536d",
            },
            {
                "number": 46,
                "url": (
                    "https://github.com/trading-optimizer-lab-org/aurora/"
                    "pull/46"
                ),
                "merged_at_utc": "2026-07-31T12:43:53Z",
                "merge_sha": "469a74f28bb6ade4a8331b7b43a20f871ba6074e",
            },
        ],
        "post_apply_state": {
            "counts": validation["g3a_counts"],
            "task_status_counts": validation["g3a_status_counts"],
            "g3a_gate_status": "red",
            "g3a_blocking_reason": "required_tasks_not_done",
            "remaining_g3a_tasks": ["PREV7-0204", "PREV7-0210"],
        },
        "verified_properties": {
            "append_only_g3a_history_preserved": validation[
                "append_only_g3a_history_preserved"
            ],
            "arbitrary_command_execution_supported": False,
            "exact_g3a_projection": validation["exact_g3a_projection"],
            "locked_data_accessed": False,
            "owner_controlled": True,
            "scientific_work_performed": False,
            "state_merged": True,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_G3A_APPLY_RECONCILIATION_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def main() -> int:
    DESTINATION.write_bytes(canonical_bytes(build_receipt()) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
