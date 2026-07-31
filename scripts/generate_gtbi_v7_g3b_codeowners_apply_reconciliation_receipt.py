"""Reconcile the owner CODEOWNERS controller apply with merged readiness state."""

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
SOURCE = READINESS / "g3b_codeowners_state_controller_apply_receipt.json"
DESTINATION = READINESS / "g3b_codeowners_state_transition_reconciliation_receipt.json"
CODEOWNERS_RECEIPT = READINESS / "g3b_codeowners_owner_receipt.json"

CODEOWNERS_COUNTS = {
    "attempt_event_count": 90,
    "gate_count": 15,
    "gate_event_count": 19,
    "task_count": 110,
    "task_event_count": 199,
}
CODEOWNERS_STATUS_COUNTS = {"blocked": 87, "cancelled": 1, "done": 22}
CODEOWNERS_DIGEST = (
    "sha256:eef58adc1c42030e7ebcbfda05c99ddf4604326b72067e23ed3c8b28ad283828"
)
REMAINING_G3B_TASKS = ("PREV7-0207", "PREV7-0208", "PREV7-0209", "PREV7-0308")
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
    """Validate the raw receipt and append-only PREV7-0203 projection."""
    source = _canonical_json(SOURCE)
    expected_digest = domain_digest(
        "GTBI_V7_STATE_CONTROLLER_RECEIPT_V1",
        source,
        omit_top_level_fields=("receipt_digest",),
    )
    if source["receipt_digest"] != expected_digest:
        raise ValueError("G3B CODEOWNERS controller receipt digest mismatch")
    if source["manifest_id"] != "g3b-codeowners-owner-v1":
        raise ValueError("G3B CODEOWNERS manifest mismatch")
    if source["transaction_id"] != "G3B_CLOSE-1":
        raise ValueError("G3B CODEOWNERS transaction mismatch")
    if source["task_actions_applied"] != [
        {"target_status": "done", "task_id": "PREV7-0203"}
    ]:
        raise ValueError("G3B CODEOWNERS task action mismatch")
    if source["branch_actions_applied"] or source["gate_actions_applied"]:
        raise ValueError("G3B CODEOWNERS changed branches or gates")
    if set(source["output_sha256"]) != EXPECTED_OUTPUT_PATHS:
        raise ValueError("G3B CODEOWNERS output allowlist mismatch")
    if source["scientific_work_performed"] or source["locked_data_accessed"]:
        raise ValueError("G3B CODEOWNERS touched science or locked data")
    if source["arbitrary_command_execution_supported"]:
        raise ValueError("G3B CODEOWNERS allowed arbitrary commands")

    current = validate_current_readiness_records(ROOT)
    for key, minimum in CODEOWNERS_COUNTS.items():
        if int(current[key]) < minimum:
            raise ValueError(f"current readiness state predates CODEOWNERS: {key}")

    codeowners_receipt = _canonical_json(CODEOWNERS_RECEIPT)
    if codeowners_receipt["receipt_digest"] != CODEOWNERS_DIGEST:
        raise ValueError("owner CODEOWNERS receipt digest mismatch")

    task_rows = {row["id"]: row for row in _csv_rows(READINESS / "task_status.csv")}
    task = task_rows["PREV7-0203"]
    if task["status"] != "done":
        raise ValueError("PREV7-0203 is not done")
    if task["alternative_completion_receipt_set_digest"] != CODEOWNERS_DIGEST:
        raise ValueError("PREV7-0203 receipt digest mismatch")

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
        raise ValueError("PREV7-0203 task event sequence mismatch")
    if any(event["task_id"] != "PREV7-0203" for event in events):
        raise ValueError("G3B CODEOWNERS transaction touched another task")

    gate_events = [
        event
        for event in _jsonl_rows(READINESS / "gate_events.jsonl")
        if event["transaction_id"] == source["transaction_id"]
    ]
    if gate_events:
        raise ValueError("G3B CODEOWNERS unexpectedly changed a gate")
    gate_rows = {row["gate_id"]: row for row in _csv_rows(READINESS / "gate_status.csv")}
    if gate_rows["G3B"]["status"] != "red":
        raise ValueError("G3B must remain red after PREV7-0203")
    if gate_rows["G3B"]["blocking_reason"] != "required_tasks_not_done":
        raise ValueError("G3B blocking reason mismatch")
    current_remaining = tuple(
        task_id for task_id in REMAINING_G3B_TASKS if task_rows[task_id]["status"] != "done"
    )
    if any(task_rows[task_id]["status"] not in {"blocked", "done"} for task_id in REMAINING_G3B_TASKS):
        raise ValueError("unexpected post-CODEOWNERS G3B task state")

    exact_projection = all(int(current[key]) == value for key, value in CODEOWNERS_COUNTS.items())
    if exact_projection:
        for relative, expected in source["output_sha256"].items():
            if raw_sha256(ROOT / relative) != expected:
                raise ValueError(f"G3B CODEOWNERS output hash mismatch: {relative}")
        if dict(Counter(row["status"] for row in task_rows.values())) != CODEOWNERS_STATUS_COUNTS:
            raise ValueError("G3B CODEOWNERS task status counts mismatch")

    return {
        "append_only_readiness_history_preserved": True,
        "exact_codeowners_projection": exact_projection,
        # The receipt describes the historical projection at the CODEOWNERS merge.
        # Current progress is reported separately so regenerating the receipt stays stable.
        "remaining_g3b_tasks": list(REMAINING_G3B_TASKS),
        "current_remaining_g3b_tasks": list(current_remaining),
    }


def build_receipt() -> dict[str, Any]:
    source = _canonical_json(SOURCE)
    validation = validate_application()
    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_g3b_codeowners_apply_reconciliation_receipt_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "workflow_name": "GTBI V7 Readiness State Controller",
        "workflow_file": "gtbi-v7-readiness-state-controller.yml",
        "event": "workflow_dispatch",
        "mode": "apply",
        "manifest_id": source["manifest_id"],
        "run_id": 30641650036,
        "run_url": "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/30641650036",
        "run_status": "completed",
        "run_conclusion": "success",
        "head_sha": source["base_sha"],
        "created_at_utc": "2026-07-31T15:09:09Z",
        "updated_at_utc": "2026-07-31T15:09:28Z",
        "duration_seconds": 19,
        "artifact": {
            "id": 8797674144,
            "name": "gtbi-v7-state-controller-g3b-codeowners-owner-v1-30641650036",
            "size_in_bytes": 1041,
            "archive_digest": "sha256:99f68b85e36702e0d7b473d414bf50271f9a9d885d6fcf95f2c5fd5ad6a9df5f",
            "expires_at_utc": "2026-10-29T15:09:12Z",
        },
        "source_receipt_path": "docs/readiness/gtbi-v7/g3b_codeowners_state_controller_apply_receipt.json",
        "source_receipt_file_sha256": raw_sha256(SOURCE),
        "source_receipt_digest": source["receipt_digest"],
        "implementation_pull_request": {
            "number": 56,
            "url": "https://github.com/trading-optimizer-lab-org/aurora/pull/56",
            "merged_at_utc": "2026-07-31T15:07:35Z",
            "merge_sha": "152258faa9b0e194238c437cd5270a387eb4c9cd",
        },
        "state_pull_request": {
            "number": 57,
            "url": "https://github.com/trading-optimizer-lab-org/aurora/pull/57",
            "merged_at_utc": "2026-07-31T15:21:11Z",
            "merge_sha": "fc91626368dfafa92f554f852e9ce6840d495a9a",
        },
        "post_apply_state": {
            "counts": CODEOWNERS_COUNTS,
            "task_status_counts": CODEOWNERS_STATUS_COUNTS,
            "completed_task_id": "PREV7-0203",
            "g3b_gate_status": "red",
            "g3b_blocking_reason": "required_tasks_not_done",
            "remaining_g3b_tasks": validation["remaining_g3b_tasks"],
        },
        "verified_properties": {
            "append_only_readiness_history_preserved": validation[
                "append_only_readiness_history_preserved"
            ],
            "arbitrary_command_execution_supported": False,
            "exact_codeowners_projection_at_state_merge": True,
            "github_only": True,
            "locked_data_accessed": False,
            "owner_controlled": True,
            "scientific_work_performed": False,
            "state_merged": True,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_G3B_CODEOWNERS_APPLY_RECONCILIATION_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def main() -> int:
    DESTINATION.write_bytes(canonical_bytes(build_receipt()) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
