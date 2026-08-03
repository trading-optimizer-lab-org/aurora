"""Freeze the owner-authorized canonical GTBI V7 successor identity."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.canonical import (  # noqa: E402
    canonical_bytes,
    domain_digest,
    raw_sha256,
)

PLAN = ROOT / "docs/plans/gtbi-v7-master-plan.md"
READINESS = ROOT / "docs/readiness/gtbi-v7"
NEW_REFERENCE = ROOT / "docs/readiness/gtbi-v7-new-reference"
NO_GO = READINESS / "no_go_close_receipt.json"
CAMPAIGN_AUTHORIZATION = NEW_REFERENCE / "campaign_authorization.json"
FINAL_SUMMARY = NEW_REFERENCE / "final_summary.json"
PRESERVATION = NEW_REFERENCE / "preservation_receipt.json"
PR1_MERGE_RECEIPT = READINESS / "pr1_merge_reconciliation_receipt.json"
DESTINATION = READINESS / "canonical_successor_authorization.json"


def _canonical_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if path.read_bytes() != canonical_bytes(payload) + b"\n":
        raise ValueError(f"{path.name} is not canonical JSON")
    return payload


def build_authorization() -> dict[str, Any]:
    plan_text = PLAN.read_text(encoding="utf-8")
    no_go = _canonical_json(NO_GO)
    campaign = _canonical_json(CAMPAIGN_AUTHORIZATION)
    summary = _canonical_json(FINAL_SUMMARY)
    preservation = _canonical_json(PRESERVATION)
    pr1_merge_receipt = _canonical_json(PR1_MERGE_RECEIPT)

    if "## Canonical Successor Amendment" not in plan_text:
        raise ValueError("master plan has no canonical-successor amendment")
    if no_go["terminal_state"] != "NO_GO_CLOSED":
        raise ValueError("historical V6-equivalent lineage is not closed")
    if campaign["campaign_id"] != "gtbi_v7_new_reference_v1":
        raise ValueError("unexpected successor campaign")
    if campaign["status"] != "authorized_historical_preparation":
        raise ValueError("successor campaign was not authorized before execution")
    if "full_72000_historical_train_validation_campaign" not in campaign[
        "authorized_scope"
    ]:
        raise ValueError("full successor campaign was not pre-authorized")
    if summary["campaign_id"] != campaign["campaign_id"]:
        raise ValueError("campaign summary identity mismatch")
    if summary["total_terminal_identities"] != 72_000:
        raise ValueError("successor campaign does not close 72,000 identities")
    if summary["total_jobs_failed"] != 0 or summary["total_strategies_failed"] != 0:
        raise ValueError("successor campaign has unresolved failures")
    if summary["timeout_rows"] != 0 or summary["unsupported_rows"] != 0:
        raise ValueError("successor campaign has unresolved terminal categories")
    if summary.get("filtered_candidates", 0) != 0:
        raise ValueError("successor adoption requires a separate selection-bias review")
    if summary["merge_recovery_run_id"] != preservation["run_id"]:
        raise ValueError("preservation is not bound to final recovery")
    campaign_boundaries = campaign["scientific_boundaries"]
    for payload in (campaign_boundaries, summary, preservation):
        if payload["locked_authorized"] is not False:
            raise ValueError("successor evidence authorized locked access")
        if payload["locked_data_accessed"] is not False:
            raise ValueError("successor evidence accessed locked data")

    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_canonical_successor_authorization_v1",
        "repository": "trading-optimizer-lab-org/aurora",
        "recorded_at_utc": "2026-08-02T18:20:00Z",
        "owner_actor_id": "github-user:271768688",
        "owner_github_login": "gomez5757",
        "owner_decision": "authorize_existing_independent_v7_as_canonical_successor_and_continue_to_completed_clean",
        "authorization_source": {
            "kind": "direct_repository_owner_instruction_in_codex_task",
            "thread_id": "019e27d1-48e8-7633-8bb2-da1b0c2cebf6",
            "question": "authorize replacing exact V6 equivalence with the independent V7 as canonical reference and continue to COMPLETED_CLEAN",
            "answer": "si",
        },
        "master_plan": {
            "path": PLAN.relative_to(ROOT).as_posix(),
            "sha256": raw_sha256(PLAN),
            "version": "7.1",
            "active_generation": "GTBI_V7_CANONICAL_SUCCESSOR_1",
        },
        "historical_v6_lineage": {
            "classification": "historical_reference_only",
            "terminal_state": "NO_GO_CLOSED",
            "receipt_digest": no_go["receipt_digest"],
            "reopened": False,
            "equivalence_claim_allowed": False,
        },
        "historical_pr1_bootstrap": {
            "master_plan_sha256": pr1_merge_receipt["master_plan_sha256"],
            "master_plan_git_blob_id": pr1_merge_receipt[
                "master_plan_git_blob_id"
            ],
            "pr1_merge_receipt_digest": pr1_merge_receipt["receipt_digest"],
            "immutable_historical_record": True,
        },
        "canonical_successor": {
            "campaign_id": campaign["campaign_id"],
            "product_identity": campaign["product_identity"],
            "campaign_authorization_digest": campaign["receipt_digest"],
            "campaign_authorization_sha256": raw_sha256(CAMPAIGN_AUTHORIZATION),
            "campaign_authorized_at_utc": campaign["authorized_at_utc"],
            "frozen_data_release": campaign["frozen_data_release"],
            "source_scientific_commit_sha": summary[
                "source_scientific_commit_sha"
            ],
            "source_full_run_id": summary["source_full_run_id"],
            "final_recovery_run_id": summary["merge_recovery_run_id"],
            "final_summary_sha256": raw_sha256(FINAL_SUMMARY),
            "preservation_receipt_digest": preservation["receipt_digest"],
            "preservation_receipt_sha256": raw_sha256(PRESERVATION),
            "terminal_strategy_identities": summary["total_terminal_identities"],
            "passing_candidate_count": 0,
        },
        "adoption_safety": {
            "campaign_pre_authorized_before_execution": True,
            "frozen_input_identity_preceded_execution": True,
            "all_requested_strategy_identities_terminal": True,
            "passing_candidate_selection_used_for_adoption": False,
            "scientific_outputs_rewritten": False,
            "rerun_required_for_identity_promotion": False,
            "future_gate_reconciliation_required": True,
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
            "survivorship_biased_reference": True,
            "retrospectively_adjusted_reference": True,
            "point_in_time_claim_allowed": False,
            "v6_equivalence_claim_allowed": False,
        },
        "state_transition_policy": {
            "g2_and_later_may_re_evaluate_under_successor_identity": True,
            "later_gates_remain_fail_closed_until_individually_verified": True,
            "retired_v6_only_requirements_are_not_successor_dependencies": True,
            "target_terminal_state": "COMPLETED_CLEAN",
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_CANONICAL_SUCCESSOR_AUTHORIZATION_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def main() -> int:
    DESTINATION.write_bytes(canonical_bytes(build_authorization()) + b"\n")
    print(DESTINATION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
