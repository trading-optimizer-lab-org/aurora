"""Reconcile PREV7-0302 controller output with merged readiness state."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest, raw_sha256
from infra.gtbi_v7_readiness.controller import validate_current_readiness_records

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"
SOURCE = READINESS / "g2_provider_terms_state_controller_apply_receipt.json"
DESTINATION = READINESS / "g2_provider_terms_state_transition_reconciliation_receipt.json"
ACCEPTANCE = READINESS / "g2_provider_terms_acceptance_receipt.json"
EXPECTED_COUNTS = {
    "attempt_event_count": 110,
    "gate_count": 15,
    "gate_event_count": 19,
    "task_count": 110,
    "task_event_count": 219,
}
EXPECTED_STATUS_COUNTS = {"blocked": 82, "cancelled": 1, "done": 27}
EXPECTED_FINAL_EVENT_DIGEST = (
    "sha256:4fd25a61bc20ebd7b242929232a8f0ee807671a44a152d04a1f57dcf3c25beb0"
)
ACCEPTANCE_DIGEST = (
    "sha256:81143497524cdafa7dfc85c99c5a648e8c29c11bd5629961b8c7e49ceb398b56"
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
    if source["manifest_id"] != "g2-provider-terms-acceptance-v1":
        raise ValueError("manifest mismatch")
    if source["transaction_id"] != "G2_CLOSE-4":
        raise ValueError("transaction mismatch")
    if source["scientific_work_performed"] or source["locked_data_accessed"]:
        raise ValueError("provider transition crossed a scientific boundary")
    if source["arbitrary_command_execution_supported"]:
        raise ValueError("controller allowed arbitrary commands")

    acceptance = _canonical_json(ACCEPTANCE)
    if acceptance["receipt_digest"] != ACCEPTANCE_DIGEST:
        raise ValueError("provider acceptance receipt digest mismatch")
    if acceptance["current_provider_download_required"]:
        raise ValueError("provider acceptance unexpectedly requires a download")
    if acceptance["current_v7_data_input"] != "owner_supplied_frozen_local_data_lake":
        raise ValueError("provider acceptance does not select the frozen local data lake")
    if acceptance["scientific_boundaries"] != {
        "locked_data_accessed": False,
        "locked_start": "2021-01-01",
        "provider_download_performed": False,
        "scientific_processing_performed": False,
    }:
        raise ValueError("provider acceptance scientific boundary mismatch")

    current = validate_current_readiness_records(ROOT)
    for key, minimum in EXPECTED_COUNTS.items():
        if int(current[key]) < minimum:
            raise ValueError(f"readiness state predates PREV7-0302: {key}")

    tasks = {row["id"]: row for row in _csv_rows(READINESS / "task_status.csv")}
    task = tasks["PREV7-0302"]
    if task["status"] != "done":
        raise ValueError("PREV7-0302 is not done")
    if task["alternative_completion_receipt_set_digest"] != ACCEPTANCE_DIGEST:
        raise ValueError("PREV7-0302 acceptance digest mismatch")
    if task["base_sha"] != source["base_sha"]:
        raise ValueError("PREV7-0302 base SHA mismatch")

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
        if event["task_id"] == "PREV7-0302"
        and event["transaction_id"] == source["transaction_id"]
    ]
    if [event["new_status"] for event in transition_events] != [
        "ready",
        "in_progress",
        "review",
        "done",
    ]:
        raise ValueError("PREV7-0302 transition event chain mismatch")
    if transition_events[-1]["event_digest"] != EXPECTED_FINAL_EVENT_DIGEST:
        raise ValueError("PREV7-0302 final event digest mismatch")
    if transition_events[-1]["evaluated_commit_sha"] != source["base_sha"]:
        raise ValueError("PREV7-0302 final event base SHA mismatch")
    return {
        "historical_projection_verified": True,
        "task_status": task["status"],
    }


def build_receipt() -> dict[str, Any]:
    source = _canonical_json(SOURCE)
    validation = validate_application()
    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_g2_provider_terms_apply_reconciliation_receipt_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "manifest_id": source["manifest_id"],
        "transaction_id": source["transaction_id"],
        "run_id": 30688229265,
        "run_url": "https://github.com/trading-optimizer-lab-org/aurora/actions/runs/30688229265",
        "run_conclusion": "success",
        "created_at_utc": "2026-08-01T06:41:40Z",
        "updated_at_utc": "2026-08-01T06:41:54Z",
        "duration_seconds": 14,
        "artifact": {
            "id": 8814702964,
            "name": "gtbi-v7-state-controller-g2-provider-terms-acceptance-v1-30688229265",
            "size_in_bytes": 1039,
            "archive_digest": "sha256:d2ed9e97d66e0e139db3e4c92a5c665c6800278d2c1c2bb7accbff14d3364784",
            "expires_at_utc": "2026-10-30T06:41:41Z",
        },
        "source_receipt_file_sha256": raw_sha256(SOURCE),
        "source_receipt_digest": source["receipt_digest"],
        "acceptance_receipt_digest": ACCEPTANCE_DIGEST,
        "implementation_pull_request": {
            "number": 74,
            "merge_sha": "42c1ea844692de30c5ab52519ebce6c6638df988",
            "merged_at_utc": "2026-08-01T06:40:48Z",
        },
        "state_pull_request": {
            "number": 75,
            "merge_sha": "bb81b7f468b9ee537d4cc187883b89e8a5929adc",
            "merged_at_utc": "2026-08-01T08:05:39Z",
        },
        "post_apply_state": {
            "counts": EXPECTED_COUNTS,
            "task_status_counts": EXPECTED_STATUS_COUNTS,
            "prev7_0302_status": validation["task_status"],
        },
        "verified_properties": {
            "exact_projection_at_state_merge": validation[
                "historical_projection_verified"
            ],
            "current_input_is_frozen_local_data_lake": True,
            "github_only_controller": True,
            "locked_data_accessed": False,
            "provider_download_performed": False,
            "scientific_work_performed": False,
            "state_merged": True,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_G2_PROVIDER_TERMS_APPLY_RECONCILIATION_RECEIPT_V1",
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
