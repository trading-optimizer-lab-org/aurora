"""Reconcile PREV7-0301 controller application with merged readiness state."""

from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest, raw_sha256
from infra.gtbi_v7_readiness.controller import validate_current_readiness_records

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"
SOURCE = READINESS / "g2_retention_policy_state_controller_apply_receipt.json"
DESTINATION = READINESS / "g2_retention_policy_state_transition_reconciliation_receipt.json"
RETENTION_RECEIPT = READINESS / "g2_retention_policy_receipt.json"
RETENTION_DIGEST = "sha256:2eca09e6d984adc6ceaf2afa343168bd5800bab4ef67d03db1bccecaedd21dbe"
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
MINIMUM_COUNTS = {
    "attempt_event_count": 106,
    "gate_count": 15,
    "gate_event_count": 19,
    "task_count": 110,
    "task_event_count": 215,
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
    source = _canonical_json(SOURCE)
    if source["receipt_digest"] != domain_digest(
        "GTBI_V7_STATE_CONTROLLER_RECEIPT_V1",
        source,
        omit_top_level_fields=("receipt_digest",),
    ):
        raise ValueError("retention controller receipt digest mismatch")
    if source["manifest_id"] != "g2-retention-policy-v1":
        raise ValueError("retention controller manifest mismatch")
    if source["transaction_id"] != "G2_CLOSE-2":
        raise ValueError("retention controller transaction mismatch")
    if source["task_actions_applied"] != [
        {"target_status": "done", "task_id": "PREV7-0301"}
    ]:
        raise ValueError("retention controller task action mismatch")
    if set(source["output_sha256"]) != EXPECTED_OUTPUT_PATHS:
        raise ValueError("retention controller output allowlist mismatch")
    if source["scientific_work_performed"] or source["locked_data_accessed"]:
        raise ValueError("retention transition touched science or locked data")
    if source["arbitrary_command_execution_supported"]:
        raise ValueError("retention transition allowed arbitrary commands")

    policy_receipt = _canonical_json(RETENTION_RECEIPT)
    if policy_receipt["receipt_digest"] != RETENTION_DIGEST:
        raise ValueError("retention policy receipt digest mismatch")

    current = validate_current_readiness_records(ROOT)
    for key, minimum in MINIMUM_COUNTS.items():
        if int(current[key]) < minimum:
            raise ValueError(f"current readiness state predates retention: {key}")

    task_rows = {row["id"]: row for row in _csv_rows(READINESS / "task_status.csv")}
    task = task_rows["PREV7-0301"]
    if task["status"] != "done":
        raise ValueError("PREV7-0301 is not done")
    if task["alternative_completion_receipt_set_digest"] != RETENTION_DIGEST:
        raise ValueError("PREV7-0301 evidence digest mismatch")

    events = [
        event
        for event in _jsonl_rows(READINESS / "task_events.jsonl")
        if event["transaction_id"] == source["transaction_id"]
        and event["task_id"] == "PREV7-0301"
    ]
    if [event["new_status"] for event in events] != [
        "ready",
        "in_progress",
        "review",
        "done",
    ]:
        raise ValueError("PREV7-0301 task event sequence mismatch")

    exact_projection = all(int(current[key]) == value for key, value in MINIMUM_COUNTS.items())
    if exact_projection:
        for relative, expected in source["output_sha256"].items():
            if raw_sha256(ROOT / relative) != expected:
                raise ValueError(f"retention output hash mismatch: {relative}")
    return {
        "append_only_retention_history_preserved": True,
        "exact_retention_projection": exact_projection,
        "task_status_counts": dict(Counter(row["status"] for row in task_rows.values())),
    }


def build_receipt() -> dict[str, Any]:
    source = _canonical_json(SOURCE)
    validation = validate_application()
    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_retention_policy_apply_reconciliation_receipt_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "workflow_name": "GTBI V7 Readiness State Controller",
        "workflow_file": "gtbi-v7-readiness-state-controller.yml",
        "event": "workflow_dispatch",
        "mode": "apply",
        "manifest_id": source["manifest_id"],
        "run_id": 30657437294,
        "run_url": "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/30657437294",
        "run_status": "completed",
        "run_conclusion": "success",
        "head_sha": source["base_sha"],
        "created_at_utc": "2026-07-31T19:00:37Z",
        "updated_at_utc": "2026-07-31T19:00:51Z",
        "duration_seconds": 14,
        "artifact": {
            "id": 8803788440,
            "name": "gtbi-v7-state-controller-g2-retention-policy-v1-30657437294",
            "size_in_bytes": 1036,
            "archive_digest": "sha256:2438f0567231ded8dd74de57531e4fe2d55d8443c15dfb2b83480259df85c277",
            "expires_at_utc": "2026-10-29T19:00:39Z",
        },
        "source_receipt_path": SOURCE.relative_to(ROOT).as_posix(),
        "source_receipt_file_sha256": raw_sha256(SOURCE),
        "source_receipt_digest": source["receipt_digest"],
        "state_pull_request": {
            "number": 70,
            "url": "https://github.com/trading-optimizer-lab-org/aurora/pull/70",
            "merged_at_utc": "2026-07-31T19:29:17Z",
            "merge_sha": "e6115a05c56d1227ad4402ca46e776296403d21d",
        },
        "post_apply_state": {
            "minimum_counts": MINIMUM_COUNTS,
            "task_status_counts": validation["task_status_counts"],
            "prev7_0301_status": "done",
            "g2_gate_status": "red",
        },
        "verified_properties": {
            "append_only_retention_history_preserved": validation[
                "append_only_retention_history_preserved"
            ],
            "arbitrary_command_execution_supported": False,
            "github_only": True,
            "locked_data_accessed": False,
            "owner_controlled": True,
            "scientific_work_performed": False,
            "state_merged": True,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_RETENTION_POLICY_APPLY_RECONCILIATION_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def main() -> int:
    DESTINATION.write_bytes(canonical_bytes(build_receipt()) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
