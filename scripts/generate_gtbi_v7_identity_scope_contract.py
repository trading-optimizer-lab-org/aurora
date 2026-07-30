"""Generate the owner-controlled GTBI V7 identity and scope receipt."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from infra.gtbi_v7_readiness.canonical import (
    canonical_bytes,
    domain_digest,
    raw_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"
ADR = ROOT / "docs/adr/0003-gtbi-v7-identity.md"
RECEIPT = READINESS / "v7_identity_scope_receipt.json"
MANIFEST = READINESS / "transition_manifests/g1a-identity-close-v1.json"
OWNER_ACTOR_ID = "github-user:271768688"

TASK_ORDER = ("PREV7-0101", "PREV7-0102", "PREV7-0103")
TASK_TERMINAL_REASONS = {
    "PREV7-0101": "unified_v7_target_owner_accepted",
    "PREV7-0102": "v7_identity_and_exclusions_adr_accepted",
    "PREV7-0103": "v7_scope_and_non_goals_owner_accepted",
}
IN_SCOPE = [
    "github_only_scientific_execution",
    "exact_v6_scientific_equivalence",
    "four_runner_cpu_measured_use",
    "deterministic_1_2_4_worker_execution",
    "reusable_features_and_computations",
    "safe_deduplication",
    "cost_and_memory_aware_scheduling",
    "efficient_checkpoints_artifacts_and_hierarchical_merges",
    "selective_recovery",
    "runtime_and_scientific_diagnostics",
    "master_plan_repository_workflow_and_evidence_governance",
]
NON_GOALS = [
    "change_entry_or_exit_economics",
    "change_train_validation_or_locked_boundaries",
    "use_2021_or_later_in_train_or_validation",
    "relax_final_filters_or_change_final_ranking",
    "convert_to_clean_portfolio_v7",
    "replace_exact_v6_reference_with_new_baseline",
    "authorize_smoke_campaign_or_full_run",
    "accept_local_research_output_as_canonical_evidence",
]


def _canonical_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if path.read_bytes() != canonical_bytes(payload) + b"\n":
        raise ValueError(f"{path.name} is not canonical JSON")
    return payload


def build_receipt() -> dict[str, Any]:
    owner_decisions = _canonical_payload(READINESS / "owner_decisions.json")
    g0_receipt = _canonical_payload(
        READINESS / "g0_state_transition_reconciliation_receipt.json"
    )
    if g0_receipt["post_apply_state"]["g0_gate_status"] != "green":
        raise ValueError("G0 is not reconciled as green")
    if g0_receipt["verified_properties"]["locked_data_accessed"]:
        raise ValueError("G0 reconciliation accessed locked data")

    adr_text = ADR.read_text(encoding="utf-8")
    required_adr_values = {
        "Status: `ACCEPTED_OWNER_CONTROLLED`",
        "product=GTBI V7 Performance Engine",
        "reference_engine=GTBI Fast Strict V6",
        "clean_portfolio_in_scope=false",
        "scientific_change_allowed=false",
        "full_run_authorized=false",
        "train_end=2010-12-31",
        "validation_start=2011-01-01",
        "validation_end=2020-12-31",
        "locked_start=2021-01-01",
        "execution_environment=GitHub Actions",
    }
    missing = sorted(value for value in required_adr_values if value not in adr_text)
    if missing:
        raise ValueError(f"identity ADR is incomplete: {missing}")

    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_identity_scope_receipt_v1",
        "decision_id": "g1a-v7-identity-v1",
        "recorded_at_utc": "2026-07-30T18:00:00Z",
        "owner_actor_id": OWNER_ACTOR_ID,
        "owner_decision_source": (
            "direct_repository_owner_instruction_to_unify_v7_and_"
            "current_readiness_work"
        ),
        "product": "GTBI V7 Performance Engine",
        "reference_engine": "GTBI Fast Strict V6",
        "scientific_change_allowed": False,
        "clean_portfolio_in_scope": False,
        "execution_environment": "GitHub Actions",
        "historical_boundaries": {
            "train_end": "2010-12-31",
            "validation_start": "2011-01-01",
            "validation_end": "2020-12-31",
            "historical_exclusion_start": "2021-01-01",
            "locked_start": "2021-01-01",
        },
        "in_scope": IN_SCOPE,
        "non_goals": NON_GOALS,
        "task_acceptance": {
            "PREV7-0101": "accepted_owner_controlled",
            "PREV7-0102": "implemented_and_accepted_owner_controlled",
            "PREV7-0103": "accepted_owner_controlled",
        },
        "identity_adr": {
            "path": "docs/adr/0003-gtbi-v7-identity.md",
            "sha256": raw_sha256(ADR),
        },
        "owner_decisions": {
            "path": "docs/readiness/gtbi-v7/owner_decisions.json",
            "sha256": raw_sha256(READINESS / "owner_decisions.json"),
            "execution_status": owner_decisions["execution_status"],
        },
        "g0_reconciliation": {
            "path": (
                "docs/readiness/gtbi-v7/"
                "g0_state_transition_reconciliation_receipt.json"
            ),
            "sha256": raw_sha256(
                READINESS / "g0_state_transition_reconciliation_receipt.json"
            ),
            "receipt_digest": g0_receipt["receipt_digest"],
        },
        "full_run_authorized": False,
        "locked_data_accessed": False,
        "scientific_work_performed": False,
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_IDENTITY_SCOPE_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def _expected_results() -> dict[str, str]:
    with (READINESS / "task_status.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        return {
            row["id"]: row["expected_result"]
            for row in csv.DictReader(handle)
        }


def _evidence_set(paths: tuple[str, ...]) -> list[dict[str, str]]:
    return [
        {"path": path, "sha256": raw_sha256(ROOT / path)}
        for path in paths
    ]


def build_manifest() -> dict[str, Any]:
    expected_results = _expected_results()
    evidence_paths = (
        "docs/readiness/gtbi-v7/v7_identity_scope_receipt.json",
        "docs/readiness/gtbi-v7/owner_decisions.json",
        (
            "docs/readiness/gtbi-v7/"
            "g0_state_transition_reconciliation_receipt.json"
        ),
    )
    with (READINESS / "gate_status.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        gate_rows = {
            row["gate_id"]: row
            for row in csv.DictReader(handle)
        }
    g0_inventory = gate_rows["G0"]["inventory_snapshot_digest_or_null"]
    manifest: dict[str, Any] = {
        "schema_version": "gtbi_v7_readiness_transition_manifest_v1",
        "manifest_id": "g1a-identity-close-v1",
        "transaction_id": "G1A_CLOSE-1",
        "requested_at_utc": "2026-07-30T18:00:00Z",
        "actor_id": OWNER_ACTOR_ID,
        "actor_role": "repository_owner",
        "expected_base_ref": "refs/heads/main",
        "expected_base_sha_mode": "runtime_default_branch_head",
        "task_actions": [
            {
                "task_id": task_id,
                "target_status": "done",
                "evidence_paths": list(evidence_paths),
                "evidence_sha256": [
                    raw_sha256(ROOT / path) for path in evidence_paths
                ],
                "terminal_reason": TASK_TERMINAL_REASONS[task_id],
                "notes": (
                    "Owner-controlled G1A identity acceptance; no scientific "
                    "execution or locked-data access."
                ),
                "files_touched": list(evidence_paths),
                "expected_result": expected_results[task_id],
                "alternative_completion_receipt_set_digest_or_null": None,
            }
            for task_id in TASK_ORDER
        ],
        "branch_actions": [],
        "gate_actions": [
            {
                "gate_id": "G1A",
                "target_status": "green",
                "selected_branch_id_or_null": None,
                "inventory_snapshot_digest": g0_inventory,
                "evidence_bundle_digest": domain_digest(
                    "GTBI_V7_G1A_EVIDENCE_BUNDLE_V1",
                    _evidence_set(evidence_paths),
                ),
            }
        ],
        "owner_directive_digest": raw_sha256(
            READINESS / "owner_simplification_directive.json"
        ),
        "manifest_digest": "",
    }
    manifest["manifest_digest"] = domain_digest(
        "GTBI_V7_READINESS_TRANSITION_MANIFEST_V1",
        manifest,
        omit_top_level_fields=("manifest_digest",),
    )
    return manifest


def main() -> int:
    RECEIPT.write_bytes(canonical_bytes(build_receipt()) + b"\n")
    MANIFEST.write_bytes(canonical_bytes(build_manifest()) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
