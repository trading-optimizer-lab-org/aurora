"""Generate truthful pre-genesis blockers and a bounded cancellation proposal."""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.canonical import canonical_bytes, raw_sha256  # noqa: E402

READINESS = ROOT / "docs/readiness/gtbi-v7"
INVENTORY = ROOT / "docs/project_inventory"
V6_RUN_ID = 29162930823
V6_ARTIFACT_ID = 8251391531
V6_EXPIRES_AT = "2026-08-10T18:16:37Z"
NORMAL_PRESERVATION_SAFETY_DEADLINE = "2026-08-03T18:16:37Z"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(payload) + b"\n")


def _parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )


def generate() -> tuple[dict, dict]:
    quality = _read_json(READINESS / "master_plan_quality_status.json")
    inventory = _read_json(INVENTORY / "audit_metadata.json")
    owner_decisions = _read_json(READINESS / "owner_decisions.json")
    provider_terms = _read_json(READINESS / "provider_terms_inventory.json")
    preservation_lease = _read_json(
        READINESS / "v6_preservation_lease_public_receipt.json"
    )
    inventory_attempt = _read_json(
        READINESS / "inventory_github_actions_attempt_receipt.json"
    )
    decisions = owner_decisions["decisions"]
    audited_at = _parse_utc(inventory["audited_at_utc"])
    expires_at = _parse_utc(V6_EXPIRES_AT)
    safety_deadline = _parse_utc(NORMAL_PRESERVATION_SAFETY_DEADLINE)

    with (INVENTORY / "artifacts_critical.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        artifacts = list(csv.DictReader(handle))
    v6_rows = [
        row for row in artifacts if int(row["artifact_id"]) == V6_ARTIFACT_ID
    ]
    v6_verified = (
        len(v6_rows) == 1
        and v6_rows[0]["expired"] == "false"
        and v6_rows[0]["metadata_match"] == "true"
    )

    blockers: list[dict] = []
    status = {
        "schema_version": "gtbi_v7_pre_genesis_status_v1",
        "observed_at_utc": inventory["audited_at_utc"],
        "repository": inventory["repository"],
        "default_branch_sha": inventory["default_branch_sha"],
        "master_plan_sha256": quality["reviewed_master_plan_sha256"],
        "master_plan_quality_status": quality["status"],
        "execution_status": "TECHNICAL_PREPARATION_ALLOWED",
        "formal_genesis_complete": False,
        "technical_preparation_may_continue": True,
        "v6_artifact": {
            "run_id": V6_RUN_ID,
            "artifact_id": V6_ARTIFACT_ID,
            "verified_available": v6_verified,
            "expires_at_utc": V6_EXPIRES_AT,
            "seconds_until_expiry_at_observation": max(
                0, int((expires_at - audited_at).total_seconds())
            ),
            "normal_preservation_safety_deadline_utc": (
                NORMAL_PRESERVATION_SAFETY_DEADLINE
            ),
            "seconds_until_normal_safety_deadline_at_observation": max(
                0, int((safety_deadline - audited_at).total_seconds())
            ),
        },
        "v6_preservation_lease": {
            "status": preservation_lease["status"],
            "artifact_id": preservation_lease["lease_artifact"]["id"],
            "expires_at_utc": preservation_lease["lease_artifact"][
                "expires_at_utc"
            ],
            "source_archive_digest": preservation_lease[
                "preservation_result"
            ]["source_archive_digest"],
            "source_size_bytes": preservation_lease["preservation_result"][
                "source_size_bytes"
            ],
            "github_only": preservation_lease["github_only"],
            "requires_local_machine": preservation_lease[
                "requires_local_machine"
            ],
            "historical_receipt_effect": preservation_lease["formal_g0_effect"],
            "formal_g0_effect": "accepted_by_owner_as_sufficient",
        },
        "packages_inventory": {
            "status": "owner_waived_pending_interactive_oauth",
            "read_packages_authorized_by_owner": decisions[
                "github_permissions"
            ]["read_packages_authorized_by_owner"],
            "oauth_grant_status": decisions["github_permissions"][
                "read_packages_oauth_grant_status"
            ],
            "public_packages_page_checked": True,
            "public_packages_observed": 0,
            "private_packages_verified": False,
            "gate_effect": "non_blocking",
            "last_github_actions_attempt": {
                "run_id": inventory_attempt["run_id"],
                "status": inventory_attempt["status"],
                "artifact_id": inventory_attempt["artifact"]["id"],
                "packages_status": inventory_attempt["packages"][
                    "overall_status"
                ],
            },
        },
        "blockers": blockers,
        "future_gate_prerequisites": [
            {
                "prerequisite_id": "G2-TIINGO-CREDENTIAL-AND-CAPACITY",
                "required_for": ["new_v7_data_snapshot", "v7_scientific_execution"],
                "state": "pending_before_scientific_execution",
                "facts": {
                    "selected_provider": provider_terms[
                        "selected_future_v7_provider"
                    ],
                    "owner_acceptance": provider_terms["owner_acceptance"],
                    "authorization": provider_terms[
                        "v7_full_data_authorization"
                    ],
                    "credential_env_var": "AU_TIINGO_API_TOKEN",
                    "credential_present_in_repository": False,
                    "monthly_unique_symbol_limit": 500,
                    "full_universe_may_not_silently_change": True,
                },
                "required_action": (
                    "add the Tiingo token as a GitHub secret and approve an exact "
                    "universe/capacity schedule before creating a new snapshot"
                ),
            }
        ],
    }

    with (INVENTORY / "runs_active.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        active_runs = list(csv.DictReader(handle))
    candidates = []
    for row in active_runs:
        run_id = int(row["id"])
        if run_id == V6_RUN_ID:
            continue
        if row["status"] != "queued":
            continue
        candidates.append(
            {
                "run_id": run_id,
                "name": row["name"],
                "workflow_id": int(row["workflow_id"]),
                "status_at_inventory": row["status"],
                "head_branch": row["head_branch"],
                "head_sha": row["head_sha"],
                "created_at_utc": row["created_at"],
                "html_url": row["html_url"],
                "candidate_reason": "legacy_duplicate_queued_capacity_waste",
                "preservation_or_canonical_evidence_publisher": False,
            }
        )
    candidates.sort(key=lambda row: row["run_id"])
    cancellation = {
        "schema_version": "gtbi_v7_legacy_run_cancellation_manifest_v1",
        "generated_from_inventory_snapshot_digest": inventory["snapshot_digest"],
        "inventory_observed_at_utc": inventory["audited_at_utc"],
        "repository": inventory["repository"],
        "candidate_count": len(candidates),
        "excluded_run_ids": [V6_RUN_ID],
        "approval_state": "pending_exact_manifest_approval",
        "approved_by_actor_id": None,
        "approved_at_utc": None,
        "cancellation_executed": False,
        "candidates": candidates,
    }
    cancellation["manifest_payload_sha256"] = raw_sha256(
        canonical_bytes(cancellation)
    )

    _write_json(READINESS / "pre_genesis_status.json", status)
    _write_json(
        READINESS / "legacy_run_cancellation_candidates.json", cancellation
    )
    return status, cancellation


def main() -> int:
    status, cancellation = generate()
    print(
        json.dumps(
            {
                "execution_status": status["execution_status"],
                "blocker_count": len(status["blockers"]),
                "v6_artifact_verified": status["v6_artifact"][
                    "verified_available"
                ],
                "legacy_cancellation_candidates": cancellation[
                    "candidate_count"
                ],
                "cancellation_approval_state": cancellation["approval_state"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
