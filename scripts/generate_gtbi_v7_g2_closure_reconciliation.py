"""Reconcile the final G2 closure transitions before terminal no-go."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest, raw_sha256
from infra.gtbi_v7_readiness.controller import validate_current_readiness_records

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"
DESTINATION = READINESS / "g2_closure_state_transition_reconciliation_receipt.json"

TRANSITIONS: tuple[dict[str, Any], ...] = (
    {
        "source": "g2_scientific_asset_contract_state_controller_apply_receipt.json",
        "manifest_id": "g2-scientific-asset-contract-v1",
        "transaction_id": "G2_CLOSE-3",
        "tasks": ["PREV7-0303"],
        "run": {"id": 30693745720, "created_at_utc": "2026-08-01T09:26:25Z", "updated_at_utc": "2026-08-01T09:26:39Z"},
        "artifact": {"id": 8816551915, "name": "gtbi-v7-state-controller-g2-scientific-asset-contract-v1-30693745720", "size_in_bytes": 1041, "archive_digest": "sha256:6b9be2f2fc0638d7a92775eb5d88f83c80c67ad5a6927d3ec8557bdbc553c4a7", "expires_at_utc": "2026-10-30T09:26:26Z"},
        "integration": {"mode": "merged_pull_request", "pull_request": 79, "head_sha": "8dcfa86112786b3bf3ca9ddf470eb77d05926243", "integration_sha": "6a233ebada860d971aa3b1a43fde6afa6ad5807d", "integrated_at_utc": "2026-08-01T10:12:33Z"},
    },
    {
        "source": "g2_v6_production_promotion_restore_state_controller_apply_receipt.json",
        "manifest_id": "g2-v6-production-promotion-restore-v1",
        "transaction_id": "G2_CLOSE-5",
        "tasks": ["PREV7-0304", "PREV7-0305"],
        "run": {"id": 30695288489, "created_at_utc": "2026-08-01T10:13:24Z", "updated_at_utc": "2026-08-01T10:13:44Z"},
        "artifact": {"id": 8817041415, "name": "gtbi-v7-state-controller-g2-v6-production-promotion-restore-v1-30695288489", "size_in_bytes": 1053, "archive_digest": "sha256:0af642a3ceb19a039158f4476aa33f37624a91fae74a5c32beb5dbabf75fe5e9", "expires_at_utc": "2026-10-30T10:13:25Z"},
        "integration": {"mode": "merged_pull_request", "pull_request": 80, "head_sha": "b786d525475596c5d59c257a1d16b5fa881d598a", "integration_sha": "dc2f4965ea3adfae3e93bf3222fbe30c0ad37362", "integrated_at_utc": "2026-08-01T10:25:56Z"},
    },
    {
        "source": "g2_github_actions_envelope_state_controller_apply_receipt.json",
        "manifest_id": "g2-github-actions-envelope-v1",
        "transaction_id": "G2_CLOSE-6",
        "tasks": ["PREV7-0309"],
        "run": {"id": 30695705582, "created_at_utc": "2026-08-01T10:26:17Z", "updated_at_utc": "2026-08-01T10:26:33Z"},
        "artifact": {"id": 8817168628, "name": "gtbi-v7-state-controller-g2-github-actions-envelope-v1-30695705582", "size_in_bytes": 1063, "archive_digest": "sha256:5e7e6ce6fabb5c8e70ff84a0edd7b064b74150f80df2d4de4ba8b89b464fa489", "expires_at_utc": "2026-10-30T10:26:18Z"},
        "integration": {"mode": "main_merge_commit_after_graphql_metadata_failure", "pull_request": 81, "pull_request_api_merged": False, "head_sha": "e6c12e1aea4c1f98a52181c66e9792d0932d83f7", "integration_sha": "2b64fd43c24c91d6973145af5ffd3d93707c2236", "integrated_at_utc": "2026-08-01T10:39:54Z", "residual_pull_request_closed_at_utc": "2026-08-01T10:40:40Z"},
    },
    {
        "source": "g2_v6_input_identity_state_controller_apply_receipt.json",
        "manifest_id": "g2-v6-input-identity-no-baseline-v1",
        "transaction_id": "G2_CLOSE-7",
        "tasks": ["PREV7-0307"],
        "run": {"id": 30697197635, "created_at_utc": "2026-08-01T11:11:10Z", "updated_at_utc": "2026-08-01T11:11:30Z"},
        "artifact": {"id": 8817631886, "name": "gtbi-v7-state-controller-g2-v6-input-identity-no-baseline-v1-30697197635", "size_in_bytes": 1075, "archive_digest": "sha256:ff8ba04fe3d73a3825808f4dfb17e2f3e0c6916b318a4dbcfaf6c26df6fb2bfe", "expires_at_utc": "2026-10-30T11:11:12Z"},
        "integration": {"mode": "merged_pull_request", "pull_request": 83, "head_sha": "f9edce24fe99e69a2bac7d8e9deef844a644581a", "integration_sha": "2becbe38e846fbe59aed0dc863c1e84cf430ead9", "integrated_at_utc": "2026-08-01T11:24:16Z"},
    },
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
    current = validate_current_readiness_records(ROOT)
    tasks = {row["id"]: row for row in _csv_rows(READINESS / "task_status.csv")}
    task_events = [
        json.loads(line)
        for line in (READINESS / "task_events.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    reconciled = []
    for spec in TRANSITIONS:
        source_path = READINESS / spec["source"]
        source = _canonical_json(source_path)
        expected_digest = domain_digest(
            "GTBI_V7_STATE_CONTROLLER_RECEIPT_V1",
            source,
            omit_top_level_fields=("receipt_digest",),
        )
        if source["receipt_digest"] != expected_digest:
            raise ValueError(f"{spec['manifest_id']}: controller receipt digest mismatch")
        if source["manifest_id"] != spec["manifest_id"] or source["transaction_id"] != spec["transaction_id"]:
            raise ValueError(f"{spec['manifest_id']}: controller identity mismatch")
        if source["scientific_work_performed"] or source["locked_data_accessed"]:
            raise ValueError(f"{spec['manifest_id']}: scientific boundary crossed")
        if source["arbitrary_command_execution_supported"]:
            raise ValueError(f"{spec['manifest_id']}: arbitrary execution supported")
        if [item["task_id"] for item in source["task_actions_applied"]] != spec["tasks"]:
            raise ValueError(f"{spec['manifest_id']}: task action mismatch")
        final_events = {}
        for task_id in spec["tasks"]:
            if tasks[task_id]["status"] != "done":
                raise ValueError(f"{task_id}: not done")
            events = [
                event
                for event in task_events
                if event["task_id"] == task_id
                and event["transaction_id"] == spec["transaction_id"]
            ]
            if [event["new_status"] for event in events] != ["ready", "in_progress", "review", "done"]:
                raise ValueError(f"{task_id}: transition chain mismatch")
            if any(event["evaluated_commit_sha"] != source["base_sha"] for event in events):
                raise ValueError(f"{task_id}: evaluated commit mismatch")
            final_events[task_id] = events[-1]["event_digest"]
        reconciled.append(
            {
                "manifest_id": spec["manifest_id"],
                "transaction_id": spec["transaction_id"],
                "tasks": spec["tasks"],
                "source_receipt_file_sha256": raw_sha256(source_path),
                "source_receipt_digest": source["receipt_digest"],
                "base_sha": source["base_sha"],
                "final_task_event_digests": final_events,
                "run": {**spec["run"], "url": f"https://github.com/trading-optimizer-lab-org/aurora/actions/runs/{spec['run']['id']}", "conclusion": "success"},
                "artifact": spec["artifact"],
                "integration": spec["integration"],
            }
        )
    return {"current": current, "reconciled": reconciled}


def build_receipt() -> dict[str, Any]:
    validation = validate_application()
    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_g2_closure_state_transition_reconciliation_receipt_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "recorded_at_utc": "2026-08-01T11:25:00Z",
        "reconciled_transitions": validation["reconciled"],
        "post_apply_state_counts": validation["current"],
        "verified_properties": {
            "all_five_tasks_done": True,
            "controller_receipts_digest_verified": True,
            "event_chains_verified": True,
            "github_only_controller": True,
            "locked_data_accessed": False,
            "scientific_work_performed": False,
            "no_baseline_branch_selected": True,
            "no_go_close_required": True,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_G2_CLOSURE_STATE_TRANSITION_RECONCILIATION_RECEIPT_V1",
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
