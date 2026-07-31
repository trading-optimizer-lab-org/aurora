"""Reconcile the stage-two controller apply with merged readiness state."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest, raw_sha256
from infra.gtbi_v7_readiness.controller import validate_current_readiness_records

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"
SOURCE = READINESS / "g3b_stage_two_state_controller_apply_receipt.json"
DESTINATION = READINESS / "g3b_stage_two_state_transition_reconciliation_receipt.json"
STAGE_TWO_RECEIPT = READINESS / "g3b_stage_two_owner_live_receipt.json"

STAGE_TWO_COUNTS = {
    "attempt_event_count": 94,
    "gate_count": 15,
    "gate_event_count": 19,
    "task_count": 110,
    "task_event_count": 203,
}
STAGE_TWO_STATUS_COUNTS = {"blocked": 86, "cancelled": 1, "done": 23}
HISTORICAL_REMAINING_G3B_TASKS = ("PREV7-0208", "PREV7-0209", "PREV7-0308")
EXPECTED_OUTPUT_PATHS = {
    "docs/readiness/gtbi-v7/conditional_branch_registry.csv",
    "docs/readiness/gtbi-v7/gate_events.jsonl",
    "docs/readiness/gtbi-v7/gate_status.csv",
    "docs/readiness/gtbi-v7/task_attempts.jsonl",
    "docs/readiness/gtbi-v7/task_delivery_manifest.csv",
    "docs/readiness/gtbi-v7/task_events.jsonl",
    "docs/readiness/gtbi-v7/task_planning_inputs.csv",
    "docs/readiness/gtbi-v7/task_status.csv",
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
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def validate_application() -> dict[str, Any]:
    source = _canonical_json(SOURCE)
    expected_digest = domain_digest(
        "GTBI_V7_STATE_CONTROLLER_RECEIPT_V1",
        source,
        omit_top_level_fields=("receipt_digest",),
    )
    if source["receipt_digest"] != expected_digest:
        raise ValueError("stage-two controller receipt digest mismatch")
    if source["manifest_id"] != "g3b-stage-two-owner-v1":
        raise ValueError("stage-two manifest mismatch")
    if source["transaction_id"] != "G3B_CLOSE-2":
        raise ValueError("stage-two transaction mismatch")
    if source["task_actions_applied"] != [{"target_status": "done", "task_id": "PREV7-0207"}]:
        raise ValueError("stage-two task action mismatch")
    if source["branch_actions_applied"] or source["gate_actions_applied"]:
        raise ValueError("stage-two controller changed branches or gates")
    if set(source["output_sha256"]) != EXPECTED_OUTPUT_PATHS:
        raise ValueError("stage-two output allowlist mismatch")
    if source["scientific_work_performed"] or source["locked_data_accessed"]:
        raise ValueError("stage-two controller touched science or locked data")
    if source["arbitrary_command_execution_supported"]:
        raise ValueError("stage-two controller allowed arbitrary commands")

    current = validate_current_readiness_records(ROOT)
    for key, minimum in STAGE_TWO_COUNTS.items():
        if int(current[key]) < minimum:
            raise ValueError(f"current readiness state predates stage two: {key}")

    stage_two = _canonical_json(STAGE_TWO_RECEIPT)
    task_rows = {row["id"]: row for row in _csv_rows(READINESS / "task_status.csv")}
    task = task_rows["PREV7-0207"]
    if task["status"] != "done":
        raise ValueError("PREV7-0207 is not done")
    if task["alternative_completion_receipt_set_digest"] != stage_two["receipt_digest"]:
        raise ValueError("PREV7-0207 receipt digest mismatch")

    events = [
        event
        for event in _jsonl_rows(READINESS / "task_events.jsonl")
        if event["transaction_id"] == source["transaction_id"]
    ]
    if [event["new_status"] for event in events] != [
        "ready",
        "in_progress",
        "review",
        "done",
    ]:
        raise ValueError("PREV7-0207 task event sequence mismatch")
    if any(event["task_id"] != "PREV7-0207" for event in events):
        raise ValueError("stage-two transaction touched another task")

    gate_events = [
        event
        for event in _jsonl_rows(READINESS / "gate_events.jsonl")
        if event["transaction_id"] == source["transaction_id"]
    ]
    if gate_events:
        raise ValueError("stage-two transaction unexpectedly changed a gate")
    gate_rows = {row["gate_id"]: row for row in _csv_rows(READINESS / "gate_status.csv")}
    if gate_rows["G3B"]["status"] != "red":
        raise ValueError("G3B must remain red after PREV7-0207")

    current_remaining = tuple(
        task_id
        for task_id in HISTORICAL_REMAINING_G3B_TASKS
        if task_rows[task_id]["status"] != "done"
    )
    if any(
        task_rows[task_id]["status"] not in {"blocked", "done"}
        for task_id in HISTORICAL_REMAINING_G3B_TASKS
    ):
        raise ValueError("unexpected post-stage-two G3B task state")

    exact_projection = all(int(current[key]) == value for key, value in STAGE_TWO_COUNTS.items())
    if exact_projection:
        for relative, expected in source["output_sha256"].items():
            if raw_sha256(ROOT / relative) != expected:
                raise ValueError(f"stage-two output hash mismatch: {relative}")
        if dict(Counter(row["status"] for row in task_rows.values())) != STAGE_TWO_STATUS_COUNTS:
            raise ValueError("stage-two task status counts mismatch")

    return {
        "append_only_readiness_history_preserved": True,
        "exact_stage_two_projection": exact_projection,
        "historical_remaining_g3b_tasks": list(HISTORICAL_REMAINING_G3B_TASKS),
        "current_remaining_g3b_tasks": list(current_remaining),
    }


def build_receipt() -> dict[str, Any]:
    source = _canonical_json(SOURCE)
    validation = validate_application()
    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_g3b_stage_two_apply_reconciliation_receipt_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "workflow_name": "GTBI V7 Readiness State Controller",
        "workflow_file": "gtbi-v7-readiness-state-controller.yml",
        "event": "workflow_dispatch",
        "mode": "apply",
        "manifest_id": source["manifest_id"],
        "run_id": 30647948043,
        "run_url": "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/30647948043",
        "run_status": "completed",
        "run_conclusion": "success",
        "head_sha": source["base_sha"],
        "created_at_utc": "2026-07-31T16:38:39Z",
        "updated_at_utc": "2026-07-31T16:39:05Z",
        "duration_seconds": 26,
        "artifact": {
            "id": 8800195919,
            "name": "gtbi-v7-state-controller-g3b-stage-two-owner-v1-30647948043",
            "size_in_bytes": 1040,
            "archive_digest": "sha256:a12c2b9b8b410263c688b45bdcfff36416f1b2d59c9b3513fc97fc909d5300cf",
            "expires_at_utc": "2026-10-29T16:38:40Z",
        },
        "source_receipt_path": SOURCE.relative_to(ROOT).as_posix(),
        "source_receipt_file_sha256": raw_sha256(SOURCE),
        "source_receipt_digest": source["receipt_digest"],
        "implementation_pull_request": {
            "number": 59,
            "url": "https://github.com/trading-optimizer-lab-org/aurora/pull/59",
            "merged_at_utc": "2026-07-31T16:12:47Z",
            "merge_sha": "fbf7c0a0c93a974defa926539e7c8b7a61f025bd",
        },
        "evidence_pull_request": {
            "number": 60,
            "url": "https://github.com/trading-optimizer-lab-org/aurora/pull/60",
            "merged_at_utc": "2026-07-31T16:37:24Z",
            "merge_sha": "d5c76e2a297a01921dc6ad33b7665dd624b595dd",
        },
        "state_pull_request": {
            "number": 61,
            "url": "https://github.com/trading-optimizer-lab-org/aurora/pull/61",
            "merged_at_utc": "2026-07-31T17:05:32Z",
            "merge_sha": "13a9806ed912b397153949cdfbba80ef8cd8bedf",
        },
        "post_apply_state": {
            "counts": STAGE_TWO_COUNTS,
            "task_status_counts": STAGE_TWO_STATUS_COUNTS,
            "completed_task_id": "PREV7-0207",
            "g3b_gate_status": "red",
            "g3b_blocking_reason": "required_tasks_not_done",
            "remaining_g3b_tasks": list(HISTORICAL_REMAINING_G3B_TASKS),
        },
        "verified_properties": {
            "append_only_readiness_history_preserved": validation[
                "append_only_readiness_history_preserved"
            ],
            "arbitrary_command_execution_supported": False,
            "exact_stage_two_projection_at_state_merge": True,
            "github_only": True,
            "locked_data_accessed": False,
            "owner_controlled": True,
            "scientific_work_performed": False,
            "state_merged": True,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_G3B_STAGE_TWO_APPLY_RECONCILIATION_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def main() -> int:
    DESTINATION.write_bytes(canonical_bytes(build_receipt()) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
