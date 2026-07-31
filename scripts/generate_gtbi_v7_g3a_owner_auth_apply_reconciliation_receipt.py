"""Reconcile the owner-auth G3A controller apply with merged readiness state."""

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
SOURCE = READINESS / "g3a_owner_auth_state_controller_apply_receipt.json"
DESTINATION = (
    READINESS / "g3a_owner_auth_state_transition_reconciliation_receipt.json"
)
OWNER_AUTH_RECEIPT = READINESS / "g3a_owner_auth_completion_receipt.json"

OWNER_AUTH_COUNTS = {
    "attempt_event_count": 86,
    "gate_count": 15,
    "gate_event_count": 19,
    "task_count": 110,
    "task_event_count": 195,
}
OWNER_AUTH_STATUS_COUNTS = {
    "blocked": 88,
    "cancelled": 1,
    "done": 21,
}
OWNER_AUTH_TASK_IDS = ("PREV7-0204", "PREV7-0210")
OWNER_AUTH_DIGEST = (
    "sha256:cd54bb51bfcbfbfef25b06f660de427dc37500955ce8d92dd52f1a3ca14ba5c5"
)
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
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def validate_application() -> dict[str, Any]:
    """Validate the raw receipt and append-only owner-auth G3A projection."""
    source = _canonical_json(SOURCE)
    expected_digest = domain_digest(
        "GTBI_V7_STATE_CONTROLLER_RECEIPT_V1",
        source,
        omit_top_level_fields=("receipt_digest",),
    )
    if source["receipt_digest"] != expected_digest:
        raise ValueError("owner-auth G3A controller receipt digest mismatch")
    if source["manifest_id"] != "g3a-owner-auth-close-v1":
        raise ValueError("owner-auth G3A manifest mismatch")
    if source["transaction_id"] != "G3A_CLOSE-2":
        raise ValueError("owner-auth G3A transaction mismatch")
    if set(source["output_sha256"]) != EXPECTED_OUTPUT_PATHS:
        raise ValueError("owner-auth G3A output allowlist mismatch")
    if source["scientific_work_performed"]:
        raise ValueError("owner-auth G3A unexpectedly performed science")
    if source["locked_data_accessed"]:
        raise ValueError("owner-auth G3A unexpectedly accessed locked data")
    if source["arbitrary_command_execution_supported"]:
        raise ValueError("owner-auth G3A allowed arbitrary commands")

    current = validate_current_readiness_records(ROOT)
    for key, minimum in OWNER_AUTH_COUNTS.items():
        if int(current[key]) < minimum:
            raise ValueError(f"current readiness state predates owner auth: {key}")

    owner_auth_receipt = _canonical_json(OWNER_AUTH_RECEIPT)
    if owner_auth_receipt["receipt_digest"] != OWNER_AUTH_DIGEST:
        raise ValueError("owner-auth completion receipt digest mismatch")

    task_rows = {
        row["id"]: row for row in _csv_rows(READINESS / "task_status.csv")
    }
    for task_id in OWNER_AUTH_TASK_IDS:
        task = task_rows[task_id]
        if task["status"] != "done":
            raise ValueError(f"owner-auth task is not done: {task_id}")
        if task["alternative_completion_receipt_set_digest"] != OWNER_AUTH_DIGEST:
            raise ValueError(f"owner-auth task digest mismatch: {task_id}")

    gate_rows = {
        row["gate_id"]: row for row in _csv_rows(READINESS / "gate_status.csv")
    }
    g3a = gate_rows["G3A"]
    expected_gate = {
        "blocking_reason": "",
        "evidence_bundle_digest": OWNER_AUTH_DIGEST,
        "evaluated_commit_sha": source["base_sha"],
        "selected_branch_id_or_null": "APP_PRIVATE_KEY_IMPORT",
        "status": "green",
    }
    for field, expected in expected_gate.items():
        if g3a[field] != expected:
            raise ValueError(f"owner-auth G3A gate field mismatch: {field}")

    branches = _csv_rows(READINESS / "conditional_branch_registry.csv")
    selected = [
        row
        for row in branches
        if row["task_id"] == "PREV7-0204"
        and row["branch_id"] == "APP_PRIVATE_KEY_IMPORT"
    ]
    if len(selected) != 1:
        raise ValueError("owner-auth branch selection is missing or duplicated")
    if selected[0]["selected_successor"] != "owner_controlled_ephemeral_github_token":
        raise ValueError("owner-auth selected successor mismatch")
    if selected[0]["decision_receipt_digest"] != OWNER_AUTH_DIGEST:
        raise ValueError("owner-auth branch receipt mismatch")

    task_events = [
        event
        for event in _jsonl_rows(READINESS / "task_events.jsonl")
        if event["transaction_id"] == source["transaction_id"]
    ]
    expected_sequences = {
        task_id: ["ready", "in_progress", "review", "done"]
        for task_id in OWNER_AUTH_TASK_IDS
    }
    actual_sequences = {
        task_id: [
            event["new_status"]
            for event in task_events
            if event["task_id"] == task_id
        ]
        for task_id in OWNER_AUTH_TASK_IDS
    }
    if actual_sequences != expected_sequences:
        raise ValueError("owner-auth task event sequence mismatch")

    gate_events = [
        event
        for event in _jsonl_rows(READINESS / "gate_events.jsonl")
        if event["transaction_id"] == source["transaction_id"]
    ]
    if len(gate_events) != 1 or gate_events[0]["new_status"] != "green":
        raise ValueError("owner-auth G3A gate event mismatch")

    exact_projection = all(
        int(current[key]) == value for key, value in OWNER_AUTH_COUNTS.items()
    )
    if exact_projection:
        for relative, expected in source["output_sha256"].items():
            if raw_sha256(ROOT / relative) != expected:
                raise ValueError(f"owner-auth G3A output hash mismatch: {relative}")
        status_counts = Counter(row["status"] for row in task_rows.values())
        if dict(status_counts) != OWNER_AUTH_STATUS_COUNTS:
            raise ValueError("owner-auth G3A task status counts mismatch")

    return {
        "append_only_owner_auth_history_preserved": True,
        "exact_owner_auth_projection": exact_projection,
    }


def build_receipt() -> dict[str, Any]:
    source = _canonical_json(SOURCE)
    validation = validate_application()
    receipt: dict[str, Any] = {
        "schema_version": (
            "gtbi_v7_g3a_owner_auth_apply_reconciliation_receipt_v1"
        ),
        "repository": "trading-optimizer-lab-org/aurora",
        "workflow_name": "GTBI V7 Readiness State Controller",
        "workflow_file": "gtbi-v7-readiness-state-controller.yml",
        "event": "workflow_dispatch",
        "mode": "apply",
        "manifest_id": source["manifest_id"],
        "run_id": 30636646934,
        "run_url": (
            "https://github.com/trading-optimizer-lab-org/aurora/"
            "actions/runs/30636646934"
        ),
        "run_status": "completed",
        "run_conclusion": "success",
        "head_sha": source["base_sha"],
        "created_at_utc": "2026-07-31T13:58:42Z",
        "updated_at_utc": "2026-07-31T13:59:06Z",
        "duration_seconds": 24,
        "artifact": {
            "id": 8795603809,
            "name": (
                "gtbi-v7-state-controller-"
                "g3a-owner-auth-close-v1-30636646934"
            ),
            "size_in_bytes": 1090,
            "archive_digest": (
                "sha256:"
                "c53056983cf8c06573eb49abe30c92c07b124e5f20098206e46cdf2f3a357911"
            ),
            "expires_at_utc": "2026-10-29T13:58:44Z",
        },
        "source_receipt_path": (
            "docs/readiness/gtbi-v7/"
            "g3a_owner_auth_state_controller_apply_receipt.json"
        ),
        "source_receipt_file_sha256": raw_sha256(SOURCE),
        "source_receipt_digest": source["receipt_digest"],
        "state_pull_request": {
            "number": 51,
            "url": "https://github.com/trading-optimizer-lab-org/aurora/pull/51",
            "merged_at_utc": "2026-07-31T14:28:13Z",
            "merge_sha": "67f5374c4bae8dea4055d5c80160959e4c5af5a7",
        },
        "validation_pull_requests": [
            {
                "number": 50,
                "url": "https://github.com/trading-optimizer-lab-org/aurora/pull/50",
                "merged_at_utc": "2026-07-31T13:57:02Z",
                "merge_sha": "dfb68f34b5f9746325cf43317b134bb1ab6326aa",
            },
            {
                "number": 52,
                "url": "https://github.com/trading-optimizer-lab-org/aurora/pull/52",
                "merged_at_utc": "2026-07-31T14:02:39Z",
                "merge_sha": "8cd164027456690674bbcb30cac0212b0700afb2",
            },
            {
                "number": 53,
                "url": "https://github.com/trading-optimizer-lab-org/aurora/pull/53",
                "merged_at_utc": "2026-07-31T14:08:31Z",
                "merge_sha": "eac2c208e7c820f1f93e9a25ab1f5e2e29c1643b",
            },
            {
                "number": 54,
                "url": "https://github.com/trading-optimizer-lab-org/aurora/pull/54",
                "merged_at_utc": "2026-07-31T14:12:57Z",
                "merge_sha": "8ff1e621a1b13b46dfd42a793df6fca6107d83c3",
            },
        ],
        "post_apply_state": {
            "counts": OWNER_AUTH_COUNTS,
            "task_status_counts": OWNER_AUTH_STATUS_COUNTS,
            "g3a_gate_status": "green",
            "g3a_blocking_reason": "",
            "remaining_g3a_tasks": [],
        },
        "verified_properties": {
            "append_only_owner_auth_history_preserved": validation[
                "append_only_owner_auth_history_preserved"
            ],
            "arbitrary_command_execution_supported": False,
            "exact_owner_auth_projection_at_state_merge": True,
            "github_only": True,
            "locked_data_accessed": False,
            "owner_controlled": True,
            "scientific_work_performed": False,
            "state_merged": True,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_G3A_OWNER_AUTH_APPLY_RECONCILIATION_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def main() -> int:
    DESTINATION.write_bytes(canonical_bytes(build_receipt()) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
