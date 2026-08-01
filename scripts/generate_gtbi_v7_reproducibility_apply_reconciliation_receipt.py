"""Reconcile PREV7-0306 controller output with merged readiness state."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest, raw_sha256
from infra.gtbi_v7_readiness.controller import validate_current_readiness_records

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"
SOURCE = READINESS / "g2_reproducibility_state_controller_apply_receipt.json"
DESTINATION = READINESS / "g2_reproducibility_state_transition_reconciliation_receipt.json"
CLASSIFICATION = READINESS / "g2_reproducibility_classification_receipt.json"
EXPECTED_COUNTS = {
    "attempt_event_count": 102,
    "gate_count": 15,
    "gate_event_count": 19,
    "task_count": 110,
    "task_event_count": 211,
}
EXPECTED_STATUS_COUNTS = {"blocked": 84, "cancelled": 1, "done": 25}
EXPECTED_FINAL_EVENT_DIGEST = (
    "sha256:9735fafb8c6385fe8a888903e8d795f3a6d2efb881038bfdd3fe8b6747faba9f"
)
CLASSIFICATION_DIGEST = (
    "sha256:89855d0d629b5d0b975eb7a507a8070637c6715cd7d7c620444adaf922b474f0"
)


def _canonical_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if path.read_bytes() != canonical_bytes(payload) + b"\n":
        raise ValueError(f"{path.name} is not canonical JSON")
    return payload


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def validate_application() -> dict[str, Any]:
    source = _canonical_json(SOURCE)
    if source["receipt_digest"] != domain_digest(
        "GTBI_V7_STATE_CONTROLLER_RECEIPT_V1",
        source,
        omit_top_level_fields=("receipt_digest",),
    ):
        raise ValueError("controller receipt digest mismatch")
    if source["manifest_id"] != "g2-reproducibility-classification-v1":
        raise ValueError("manifest mismatch")
    if source["transaction_id"] != "G2_CLOSE-1":
        raise ValueError("transaction mismatch")
    if source["scientific_work_performed"] or source["locked_data_accessed"]:
        raise ValueError("reproducibility transition crossed a scientific boundary")
    if source["arbitrary_command_execution_supported"]:
        raise ValueError("controller allowed arbitrary commands")

    classification = _canonical_json(CLASSIFICATION)
    if classification["receipt_digest"] != CLASSIFICATION_DIGEST:
        raise ValueError("classification receipt digest mismatch")
    current = validate_current_readiness_records(ROOT)
    for key, minimum in EXPECTED_COUNTS.items():
        if int(current[key]) < minimum:
            raise ValueError(f"readiness state predates PREV7-0306: {key}")

    tasks = {row["id"]: row for row in _csv_rows(READINESS / "task_status.csv")}
    task = tasks["PREV7-0306"]
    if task["status"] != "done":
        raise ValueError("PREV7-0306 is not done")
    if task["alternative_completion_receipt_set_digest"] != CLASSIFICATION_DIGEST:
        raise ValueError("PREV7-0306 classification digest mismatch")
    if task["base_sha"] != source["base_sha"]:
        raise ValueError("PREV7-0306 base SHA mismatch")

    task_events = [
        json.loads(line)
        for line in (READINESS / "task_events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    transition_events = [
        event
        for event in task_events
        if event["task_id"] == "PREV7-0306"
        and event["transaction_id"] == source["transaction_id"]
    ]
    if [event["new_status"] for event in transition_events] != [
        "ready",
        "in_progress",
        "review",
        "done",
    ]:
        raise ValueError("PREV7-0306 transition event chain mismatch")
    if transition_events[-1]["event_digest"] != EXPECTED_FINAL_EVENT_DIGEST:
        raise ValueError("PREV7-0306 final event digest mismatch")
    if transition_events[-1]["evaluated_commit_sha"] != source["base_sha"]:
        raise ValueError("PREV7-0306 final event base SHA mismatch")
    return {
        "historical_projection_verified": True,
        "task_status": task["status"],
    }


def build_receipt() -> dict[str, Any]:
    source = _canonical_json(SOURCE)
    validation = validate_application()
    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_g2_reproducibility_apply_reconciliation_receipt_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "manifest_id": source["manifest_id"],
        "transaction_id": source["transaction_id"],
        "run_id": 30654371157,
        "run_url": "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/30654371157",
        "run_conclusion": "success",
        "created_at_utc": "2026-07-31T18:14:30Z",
        "updated_at_utc": "2026-07-31T18:14:50Z",
        "duration_seconds": 20,
        "artifact": {
            "id": 8802623837,
            "name": "gtbi-v7-state-controller-g2-reproducibility-classification-v1-30654371157",
            "size_in_bytes": 1045,
            "archive_digest": "sha256:effdffe8ef61a1ff26e380329d36633620844a8422b54c63d6ee3f5e942ab846",
            "expires_at_utc": "2026-10-29T18:14:32Z",
        },
        "source_receipt_file_sha256": raw_sha256(SOURCE),
        "source_receipt_digest": source["receipt_digest"],
        "classification_receipt_digest": CLASSIFICATION_DIGEST,
        "implementation_pull_requests": [
            {
                "number": 64,
                "merge_sha": "19c1b4830a7b2aa901d83ce6f9217b3cada33e74",
                "merged_at_utc": "2026-07-31T17:50:48Z",
            },
            {
                "number": 65,
                "merge_sha": "9beb98c960f9356fe706c1f987cd3d336dbd5781",
                "merged_at_utc": "2026-07-31T18:13:37Z",
            },
        ],
        "state_pull_request": {
            "number": 67,
            "merge_sha": "1483f3b556839616e1cf82b5c307392e5f2ebfaa",
            "merged_at_utc": "2026-07-31T18:25:01Z",
        },
        "post_apply_state": {
            "counts": EXPECTED_COUNTS,
            "task_status_counts": EXPECTED_STATUS_COUNTS,
            "prev7_0306_status": validation["task_status"],
        },
        "verified_properties": {
            "exact_projection_at_state_merge": validation[
                "historical_projection_verified"
            ],
            "github_only": True,
            "locked_data_accessed": False,
            "scientific_work_performed": False,
            "state_merged": True,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_G2_REPRODUCIBILITY_APPLY_RECONCILIATION_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def main() -> int:
    DESTINATION.write_bytes(canonical_bytes(build_receipt()) + b"\n")
    print(f"wrote {DESTINATION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
