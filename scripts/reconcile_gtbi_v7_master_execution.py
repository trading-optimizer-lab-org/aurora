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
SUCCESSOR_AUTHORIZATION = MASTER_READINESS / "canonical_successor_authorization.json"
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
    financial = receipt.get("financial_closure", {})
    if financial.get("maximum_incremental_net_spend_usd") != 0:
        raise ValueError("no-go closure permits incremental spend")
    if financial.get("current_actions_net_amount_usd") != 0:
        raise ValueError("no-go closure records a non-zero Actions cost")
    if financial.get("unreconciled_cost_domains") != []:
        raise ValueError("no-go closure leaves an unreconciled cost domain")
    if financial.get("terminal_financial_exception_required") is not False:
        raise ValueError("no-go closure requires an unresolved financial exception")
    resources = receipt.get("resource_inventory", {})
    if resources.get("billable_resources_created") != 0:
        raise ValueError("no-go closure created a billable resource")
    if resources.get("temporary_cloud_resources_created") != 0:
        raise ValueError("no-go closure left temporary cloud resources")
    if resources.get("self_hosted_runners_created") != 0:
        raise ValueError("no-go closure created self-hosted runners")
    if resources.get("controller_artifact_retained_under_approved_evidence_policy") is not True:
        raise ValueError("controller evidence is not retained under approved policy")
    if resources.get("github_repository_retained_as_canonical_evidence") is not True:
        raise ValueError("canonical repository evidence is not retained")
    if not resources.get("retained_evidence_entries"):
        raise ValueError("no-go closure has no retained-evidence manifest")
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


def _validate_successor_authorization(
    successor: dict[str, Any], no_go: dict[str, Any], summary: dict[str, Any]
) -> None:
    expected = domain_digest(
        "GTBI_V7_CANONICAL_SUCCESSOR_AUTHORIZATION_V1",
        successor,
        omit_top_level_fields=("receipt_digest",),
    )
    if successor.get("receipt_digest") != expected:
        raise ValueError("canonical-successor authorization digest mismatch")
    if successor.get("master_plan", {}).get("sha256") != raw_sha256(MASTER_PLAN):
        raise ValueError("canonical-successor authorization is not plan-bound")
    historical = successor.get("historical_v6_lineage", {})
    if historical.get("terminal_state") != "NO_GO_CLOSED":
        raise ValueError("successor authorization reopens historical V6")
    if historical.get("receipt_digest") != no_go.get("receipt_digest"):
        raise ValueError("successor authorization changed historical closure")
    if historical.get("reopened") is not False:
        raise ValueError("successor authorization reopens historical V6")
    canonical = successor.get("canonical_successor", {})
    if canonical.get("campaign_id") != summary.get("campaign_id"):
        raise ValueError("successor authorization campaign mismatch")
    if canonical.get("terminal_strategy_identities") != 72_000:
        raise ValueError("successor authorization lacks complete accounting")
    boundaries = successor.get("scientific_boundaries", {})
    if boundaries.get("locked_authorized") is not False:
        raise ValueError("successor authorization opens locked")
    if boundaries.get("locked_data_accessed") is not False:
        raise ValueError("successor authorization records locked access")
    if boundaries.get("maximum_incremental_net_spend_usd") != 0:
        raise ValueError("successor authorization changes the cost cap")


def build_reconciliation() -> dict[str, Any]:
    no_go = _canonical_json(NO_GO_RECEIPT)
    authorization = _canonical_json(AUTHORIZATION)
    summary = _canonical_json(FINAL_SUMMARY)
    preservation = _canonical_json(PRESERVATION_RECEIPT)
    successor = _canonical_json(SUCCESSOR_AUTHORIZATION)
    _validate_no_go(no_go)
    _validate_independent_campaign(authorization, summary, preservation, no_go)
    _validate_successor_authorization(successor, no_go, summary)

    tasks = _csv_rows(MASTER_READINESS / "task_status.csv")
    gates = _csv_rows(MASTER_READINESS / "gate_status.csv")
    tasks_by_id = {row["id"]: row for row in tasks}
    gates_by_id = {row["gate_id"]: row for row in gates}
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

    terminal_requirements = {
        "prev7_0000_done": tasks_by_id["PREV7-0000"]["status"] == "done",
        "g0_green": gates_by_id["G0"]["status"] == "green",
        "no_successful_g7_or_full_claimed": (
            no_go["resource_inventory"]["v7_g7_or_full_scientific_runs_dispatched"]
            == 0
        ),
        "exact_no_go_controller_receipt_verified": True,
        "resources_absent_or_retained_under_approved_policy": (
            no_go["resource_inventory"]["billable_resources_created"] == 0
            and no_go["resource_inventory"]["temporary_cloud_resources_created"]
            == 0
            and no_go["resource_inventory"][
                "controller_artifact_retained_under_approved_evidence_policy"
            ]
            is True
        ),
        "all_cost_domains_reconciled": (
            no_go["financial_closure"]["unreconciled_cost_domains"] == []
            and no_go["financial_closure"]["current_actions_net_amount_usd"] == 0
        ),
    }
    if not all(terminal_requirements.values()):
        raise ValueError("NO_GO_CLOSED completion requirements are not satisfied")

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
            "version": "7.1",
            "active_generation": "GTBI_V7_CANONICAL_SUCCESSOR_1",
        },
        "formal_projection": {
            "task_count": len(tasks),
            "task_counts": task_counts,
            "gate_count": len(gates),
            "gate_counts": gate_counts,
            "terminal_no_go_does_not_green_pending_gates": True,
        },
        "historical_v6_terminal_path": {
            "terminal_state": "NO_GO_CLOSED",
            "plan_completion_definition": "section_24_NO_GO_CLOSED",
            "requirements": terminal_requirements,
            "requirements_satisfied": True,
            "successful_readiness_path_completed": False,
            "scientific_success": False,
            "reopened": False,
            "scientific_lineage_status": "historical_reference_only",
        },
        "active_successor_path": {
            "generation_id": "GTBI_V7_CANONICAL_SUCCESSOR_1",
            "state": "AUTHORIZED_RECONCILIATION_ACTIVE",
            "target_terminal_state": "COMPLETED_CLEAN",
            "authorization_receipt_digest": successor["receipt_digest"],
            "historical_v6_reopened": False,
            "v6_equivalence_claim_allowed": False,
            "downstream_applicable_tasks_required": True,
            "downstream_tasks_may_transition_only_after_gate_evidence": True,
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
            "blocks_selected_terminal_state": True,
            "classification": "required_canonical_successor_completion_scope",
            "repository_inventory_and_reorganization": "pending",
            "legacy_retirement": "pending_decision_no_v7_candidate_passed_filters",
            "repository_wide_modernization": "pending",
            "may_not_reopen_v6_equivalent_scientific_path": True,
            "active_successor_must_reach_completed_clean": True,
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
