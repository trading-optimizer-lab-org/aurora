"""Reconcile the successful G1A controller apply with merged readiness state."""

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
SOURCE = READINESS / "g1a_state_controller_apply_receipt.json"
DESTINATION = (
    READINESS / "g1a_state_transition_reconciliation_receipt.json"
)

G1A_COUNTS = {
    "attempt_event_count": 62,
    "gate_count": 15,
    "gate_event_count": 17,
    "task_count": 110,
    "task_event_count": 171,
}
G1A_STATUS_COUNTS = {
    "blocked": 94,
    "cancelled": 1,
    "done": 15,
}
G1A_TASK_STATUSES = {
    "PREV7-0101": "done",
    "PREV7-0102": "done",
    "PREV7-0103": "done",
}
G1A_GATE_FIELDS = {
    "evidence_bundle_digest": (
        "sha256:"
        "4485b44ad8702662072d8b936d4d13b7adfbfdebb66cfc7a961903dfa74e2394"
    ),
    "evaluated_commit_sha": "74c3c2137783d5a9ce83884ba57f0c86a8dca498",
    "gate_attempt_id": "G1A-attempt-0001",
    "inventory_snapshot_digest_or_null": (
        "sha256:"
        "3a93d655520be90818b81df0179cdbde35ca82aea4229292806619758ed300be"
    ),
    "selected_branch_id_or_null": "",
    "status": "green",
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
    """Validate the raw receipt and its append-only G1A state projection."""
    source = _canonical_json(SOURCE)
    expected_digest = domain_digest(
        "GTBI_V7_STATE_CONTROLLER_RECEIPT_V1",
        source,
        omit_top_level_fields=("receipt_digest",),
    )
    if source["receipt_digest"] != expected_digest:
        raise ValueError("G1A controller receipt digest mismatch")
    if source["scientific_work_performed"]:
        raise ValueError("G1A controller unexpectedly performed scientific work")
    if source["locked_data_accessed"]:
        raise ValueError("G1A controller unexpectedly accessed locked data")
    if source["arbitrary_command_execution_supported"]:
        raise ValueError("G1A controller unexpectedly allowed arbitrary commands")

    current = validate_current_readiness_records(ROOT)
    for key, minimum in G1A_COUNTS.items():
        if int(current[key]) < minimum:
            raise ValueError(f"current readiness state predates G1A: {key}")

    task_rows = {
        row["id"]: row
        for row in _csv_rows(READINESS / "task_status.csv")
    }
    for task_id, expected_status in G1A_TASK_STATUSES.items():
        if task_rows[task_id]["status"] != expected_status:
            raise ValueError(f"{task_id} no longer preserves G1A status")

    gate_rows = {
        row["gate_id"]: row
        for row in _csv_rows(READINESS / "gate_status.csv")
    }
    g1a_gate = gate_rows["G1A"]
    for field, expected in G1A_GATE_FIELDS.items():
        if g1a_gate[field] != expected:
            raise ValueError(f"G1A gate field mismatch: {field}")

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
        raise ValueError("G1A applied task events do not match the receipt")

    gate_events = _jsonl_rows(READINESS / "gate_events.jsonl")
    matching_gate_events = [
        event
        for event in gate_events
        if event["transaction_id"] == source["transaction_id"]
    ]
    if len(matching_gate_events) != 1:
        raise ValueError("expected exactly one G1A gate event")
    if matching_gate_events[0]["new_status"] != "green":
        raise ValueError("G1A gate event is not green")

    exact_g1a_projection = all(
        int(current[key]) == value for key, value in G1A_COUNTS.items()
    )
    if exact_g1a_projection:
        for relative, expected in source["output_sha256"].items():
            if raw_sha256(ROOT / relative) != expected:
                raise ValueError(f"G1A output hash mismatch: {relative}")

    status_counts = Counter(row["status"] for row in task_rows.values())
    if exact_g1a_projection and dict(status_counts) != G1A_STATUS_COUNTS:
        raise ValueError("G1A task status counts mismatch")

    return {
        "append_only_g1a_history_preserved": True,
        "exact_g1a_projection": exact_g1a_projection,
        "g1a_counts": G1A_COUNTS,
        "g1a_status_counts": G1A_STATUS_COUNTS,
    }


def build_receipt() -> dict[str, Any]:
    source = _canonical_json(SOURCE)
    validation = validate_application()
    receipt: dict[str, Any] = {
        "schema_version": (
            "gtbi_v7_g1a_apply_reconciliation_receipt_v1"
        ),
        "repository": "trading-optimizer-lab-org/aurora",
        "workflow_name": "GTBI V7 Readiness State Controller",
        "workflow_file": "gtbi-v7-readiness-state-controller.yml",
        "event": "workflow_dispatch",
        "mode": "apply",
        "manifest_id": source["manifest_id"],
        "run_id": 30567649344,
        "run_url": (
            "https://github.com/trading-optimizer-lab-org/aurora/"
            "actions/runs/30567649344"
        ),
        "run_status": "completed",
        "run_conclusion": "success",
        "head_sha": source["base_sha"],
        "created_at_utc": "2026-07-30T17:49:02Z",
        "updated_at_utc": "2026-07-30T17:49:15Z",
        "duration_seconds": 13,
        "artifact": {
            "id": 8769470293,
            "name": (
                "gtbi-v7-state-controller-"
                "g1a-identity-close-v1-30567649344"
            ),
            "size_in_bytes": 1067,
            "archive_digest": (
                "sha256:"
                "6f703387ad232fdeb05956a1a5423b693646895b562ed579a9796398e027fd7e"
            ),
            "expires_at_utc": "2026-10-28T17:49:04Z",
        },
        "source_receipt_path": (
            "docs/readiness/gtbi-v7/"
            "g1a_state_controller_apply_receipt.json"
        ),
        "source_receipt_file_sha256": raw_sha256(SOURCE),
        "source_receipt_digest": source["receipt_digest"],
        "state_pull_request": {
            "number": 38,
            "url": (
                "https://github.com/trading-optimizer-lab-org/"
                "aurora/pull/38"
            ),
            "merged_at_utc": "2026-07-30T18:04:33Z",
            "merge_sha": "aca9ef1c4c43020daa834b2935b3cc9919048caa",
        },
        "validation_pull_requests": [
            {
                "number": 37,
                "url": (
                    "https://github.com/trading-optimizer-lab-org/"
                    "aurora/pull/37"
                ),
                "merged_at_utc": "2026-07-30T17:48:39Z",
                "merge_sha": (
                    "74c3c2137783d5a9ce83884ba57f0c86a8dca498"
                ),
            }
        ],
        "post_apply_state": {
            "counts": validation["g1a_counts"],
            "task_status_counts": validation["g1a_status_counts"],
            "g0_gate_status": "green",
            "g1a_gate_status": "green",
            "other_gate_status_counts": {"red": 13},
        },
        "verified_properties": {
            "append_only_g1a_history_preserved": validation[
                "append_only_g1a_history_preserved"
            ],
            "arbitrary_command_execution_supported": False,
            "locked_data_accessed": False,
            "owner_controlled": True,
            "scientific_work_performed": False,
            "state_merged": True,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_G1A_APPLY_RECONCILIATION_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def main() -> int:
    DESTINATION.write_bytes(canonical_bytes(build_receipt()) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
