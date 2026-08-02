"""Reconcile the closed V6-equivalent plan and independent V7 campaign."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.canonical import (
    canonical_bytes,
    domain_digest,
    raw_sha256,
)

MASTER_READINESS = ROOT / "docs/readiness/gtbi-v7"
NEW_REFERENCE_READINESS = ROOT / "docs/readiness/gtbi-v7-new-reference"
MASTER_PLAN = ROOT / "docs/plans/gtbi-v7-master-plan.md"
NO_GO_RECEIPT = MASTER_READINESS / "no_go_close_receipt.json"
AUTHORIZATION = NEW_REFERENCE_READINESS / "campaign_authorization.json"
FINAL_SUMMARY = NEW_REFERENCE_READINESS / "final_summary.json"
PRESERVATION_RECEIPT = NEW_REFERENCE_READINESS / "preservation_receipt.json"
DESTINATION = MASTER_READINESS / "master_plan_execution_reconciliation.json"


def _canonical_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    if path.read_bytes() != canonical_bytes(payload) + b"\n":
        raise ValueError(f"JSON is not canonical: {path}")
    return payload


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _plain_digest(payload: dict[str, Any], field: str) -> str:
    value = dict(payload)
    supplied = str(value.pop(field, ""))
    expected = "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()
    if supplied != expected:
        raise ValueError(f"{field} mismatch")
    return supplied


def _validate_no_go(receipt: dict[str, Any]) -> None:
    expected = domain_digest(
        "GTBI_V7_NO_GO_CLOSE_CONTROLLER_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    if receipt.get("receipt_digest") != expected:
        raise ValueError("no-go receipt digest mismatch")
    if receipt.get("terminal_state") != "NO_GO_CLOSED":
        raise ValueError("V6-equivalent plan is not terminally closed")
    if receipt.get("no_go_close_id") != "NO_GO_CLOSE-1":
        raise ValueError("unexpected no-go close generation")
    boundaries = receipt.get("scientific_boundaries", {})
    expected_boundaries = {
        "locked_start": "2021-01-01",
        "locked_data_accessed": False,
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "scientific_processing_performed": False,
        "strategy_evaluation_performed": False,
        "provider_download_performed": False,
    }
    if boundaries != expected_boundaries:
        raise ValueError("no-go scientific boundaries changed")
    if receipt.get("financial_closure", {}).get(
        "maximum_incremental_net_spend_usd"
    ) != 0:
        raise ValueError("no-go closure permits incremental spend")
    if receipt.get("run") != {
        "id": 30698392125,
        "url": (
            "https://github.com/trading-optimizer-lab-org/aurora/"
            "actions/runs/30698392125"
        ),
        "github_only": True,
        "requires_local_machine": False,
    }:
        raise ValueError("no-go run identity mismatch")


def _validate_independent_campaign(
    authorization: dict[str, Any],
    summary: dict[str, Any],
    preservation: dict[str, Any],
    no_go: dict[str, Any],
) -> None:
    if authorization.get("separate_from_v6") is not True:
        raise ValueError("new-reference campaign is not separate from V6")
    if authorization.get("v6_reproduction_claim_allowed") is not False:
        raise ValueError("new-reference campaign permits a V6 claim")
    closure = authorization.get("v6_terminal_closure", {})
    if closure.get("receipt_digest") != no_go.get("receipt_digest"):
        raise ValueError("campaign authorization is not bound to no-go closure")
    if summary.get("campaign_id") != "gtbi_v7_new_reference_v1":
        raise ValueError("unexpected campaign ID")
    if summary.get("separate_from_v6") is not True:
        raise ValueError("final result is not separate from V6")
    if summary.get("v6_equivalence_claim_allowed") is not False:
        raise ValueError("final result permits a V6 equivalence claim")
    for key in ("github_only_run", "strict_final_pass"):
        if summary.get(key) is not True:
            raise ValueError(f"final result is not complete: {key}")
    for key in (
        "requires_local_machine",
        "locked_authorized",
        "locked_data_accessed",
    ):
        if summary.get(key) is not False:
            raise ValueError(f"final result boundary changed: {key}")
    expected_dates = {
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "historical_exclusion_start": "2021-01-01",
    }
    for key, expected in expected_dates.items():
        if summary.get(key) != expected:
            raise ValueError(f"final result date changed: {key}")
    if int(summary.get("total_terminal_identities", 0)) != 72_000:
        raise ValueError("final result does not cover 72,000 terminal identities")
    if int(summary.get("total_jobs_completed", 0)) != 360:
        raise ValueError("final result does not contain 360 completed jobs")
    if int(summary.get("total_jobs_failed", -1)) != 0:
        raise ValueError("final result contains failed jobs")
    if int(summary.get("total_strategies_timed_out", -1)) != 0:
        raise ValueError("final result contains timeouts")
    _plain_digest(preservation, "receipt_digest")
    if preservation.get("run_id") != summary.get("merge_recovery_run_id"):
        raise ValueError("preservation run is not the final recovery run")
    if preservation.get("commit_sha") != summary.get("merge_recovery_commit_sha"):
        raise ValueError("preservation commit is not the final recovery commit")
    if preservation.get("locked_authorized") is not False:
        raise ValueError("preservation authorized locked access")
    if preservation.get("locked_data_accessed") is not False:
        raise ValueError("preservation accessed locked data")
    files = preservation.get("files", [])
    if files != [
        {
            "name": "gtbi-v7-new-reference-results.tar.gz",
            "sha256": (
                "sha256:ea9c245ff4136f21fee71f4f6b43a65a3059c21d7f8262892b3769d3182946f0"
            ),
            "size_bytes": 836492524,
        }
    ]:
        raise ValueError("preserved result identity changed")


def build_reconciliation() -> dict[str, Any]:
    no_go = _canonical_json(NO_GO_RECEIPT)
    authorization = _canonical_json(AUTHORIZATION)
    summary = _canonical_json(FINAL_SUMMARY)
    preservation = _canonical_json(PRESERVATION_RECEIPT)
    _validate_no_go(no_go)
    _validate_independent_campaign(authorization, summary, preservation, no_go)

    tasks = _csv_rows(MASTER_READINESS / "task_status.csv")
    gates = _csv_rows(MASTER_READINESS / "gate_status.csv")
    task_counts = {
        status: sum(row["status"] == status for row in tasks)
        for status in ("done", "cancelled", "blocked")
    }
    gate_counts = {
        status: sum(row["status"] == status for row in gates)
        for status in ("green", "red")
    }
    if len(tasks) != 110 or task_counts != {
        "done": 32,
        "cancelled": 1,
        "blocked": 77,
    }:
        raise ValueError("formal task projection changed without reconciliation")
    if len(gates) != 15 or gate_counts != {"green": 4, "red": 11}:
        raise ValueError("formal gate projection changed without reconciliation")

    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_master_execution_reconciliation_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "recorded_at_utc": "2026-08-02T17:05:00Z",
        "master_plan": {
            "path": MASTER_PLAN.relative_to(ROOT).as_posix(),
            "sha256": raw_sha256(MASTER_PLAN),
            "v6_equivalent_terminal_state": "NO_GO_CLOSED",
            "scientific_success": False,
            "no_go_close_id": no_go["no_go_close_id"],
            "no_go_run_id": no_go["run"]["id"],
            "no_go_receipt_digest": no_go["receipt_digest"],
        },
        "formal_projection": {
            "task_count": len(tasks),
            "task_counts": task_counts,
            "gate_count": len(gates),
            "gate_counts": gate_counts,
            "terminal_no_go_does_not_green_pending_gates": True,
        },
        "independent_new_reference_campaign": {
            "campaign_id": summary["campaign_id"],
            "status": "completed_historical_and_preserved",
            "separate_from_v6": True,
            "v6_equivalence_claim_allowed": False,
            "source_full_run_id": summary["source_full_run_id"],
            "final_recovery_run_id": summary["merge_recovery_run_id"],
            "scientific_commit_sha": summary["source_scientific_commit_sha"],
            "preservation_commit_sha": summary["merge_recovery_commit_sha"],
            "terminal_strategy_identities": summary["total_terminal_identities"],
            "passing_candidate_count": summary.get("filtered_candidates", 0),
            "preservation_release": preservation["release_tag"],
            "preservation_receipt_digest": preservation["receipt_digest"],
        },
        "scientific_boundaries": {
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "locked_start": "2021-01-01",
            "locked_authorized": False,
            "locked_data_accessed": False,
            "github_only": True,
            "requires_local_machine": False,
            "maximum_incremental_net_spend_usd": 0,
        },
        "remaining_administrative_scope": {
            "repository_inventory_and_reorganization": "pending",
            "legacy_retirement": "pending_decision_no_v7_candidate_passed_filters",
            "repository_wide_modernization": "pending",
            "may_not_reopen_v6_equivalent_scientific_path": True,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_MASTER_EXECUTION_RECONCILIATION_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def main() -> int:
    receipt = build_reconciliation()
    DESTINATION.write_bytes(canonical_bytes(receipt) + b"\n")
    print(DESTINATION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
