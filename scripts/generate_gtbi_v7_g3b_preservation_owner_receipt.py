"""Capture the owner-approved GitHub preservation lease for PREV7-0208."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.canonical import (  # noqa: E402
    canonical_bytes,
    domain_digest,
    raw_sha256,
)

REPOSITORY = "trading-optimizer-lab-org/aurora"
ARTIFACT_ID = 8728621585
RUN_ID = 30463490346
READINESS = ROOT / "docs/readiness/gtbi-v7"
LEASE_RECEIPT = READINESS / "v6_preservation_lease_public_receipt.json"
OWNER_DECISIONS = READINESS / "owner_decisions.json"
OWNER_DIRECTIVE = READINESS / "owner_simplification_directive.json"
RESTORE_SCRIPT = ROOT / "scripts/restore_gtbi_v6_artifact.py"
PRESERVATION_WORKFLOW = (
    ROOT / ".github/workflows/global-technical-buy-indicator-external-pack-360jobs.yml"
)
RECEIPT = READINESS / "g3b_preservation_owner_live_receipt.json"
MANIFEST = READINESS / "transition_manifests/g3b-preservation-owner-v1.json"


def _gh_json(endpoint: str) -> dict[str, Any]:
    result = subprocess.run(
        ["gh", "api", endpoint],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def capture_live_snapshot() -> dict[str, Any]:
    return {
        "artifact": _gh_json(f"repos/{REPOSITORY}/actions/artifacts/{ARTIFACT_ID}"),
        "run": _gh_json(f"repos/{REPOSITORY}/actions/runs/{RUN_ID}"),
    }


def _task_expected_result() -> str:
    with (READINESS / "task_status.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return next(row["expected_result"] for row in rows if row["id"] == "PREV7-0208")


def _validate_snapshot(snapshot: Mapping[str, Any], observed_at_utc: str) -> list[str]:
    blockers: list[str] = []
    artifact = snapshot["artifact"]
    run = snapshot["run"]
    lease = json.loads(LEASE_RECEIPT.read_text(encoding="utf-8"))
    decisions = json.loads(OWNER_DECISIONS.read_text(encoding="utf-8"))["decisions"]

    expected_artifact = lease["lease_artifact"]
    comparisons = {
        "artifact_id": (artifact.get("id"), expected_artifact["id"]),
        "artifact_name": (artifact.get("name"), expected_artifact["name"]),
        "artifact_size": (artifact.get("size_in_bytes"), expected_artifact["size_bytes"]),
        "artifact_digest": (artifact.get("digest"), expected_artifact["digest"]),
        "artifact_expiry": (artifact.get("expires_at"), expected_artifact["expires_at_utc"]),
        "run_id": (run.get("id"), lease["run"]["id"]),
        "run_head_sha": (run.get("head_sha"), lease["run"]["head_sha"]),
    }
    blockers.extend(name for name, values in comparisons.items() if values[0] != values[1])
    if artifact.get("expired") is not False:
        blockers.append("artifact_expired")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        blockers.append("preservation_run_not_successful")
    if observed_at_utc >= expected_artifact["expires_at_utc"]:
        blockers.append("lease_not_live_at_observation")
    preservation = decisions["preservation"]
    if preservation["github_v6_preservation_lease"] != "accepted_as_sufficient":
        blockers.append("owner_has_not_accepted_lease")
    if preservation["external_copy_required"] is not False:
        blockers.append("owner_decision_requires_external_copy")
    if lease["locked_or_scientific_processing_performed"] is not False:
        blockers.append("preservation_run_touched_science_or_locked")
    if lease["github_only"] is not True or lease["requires_local_machine"] is not False:
        blockers.append("preservation_not_github_only")
    workflow_text = PRESERVATION_WORKFLOW.read_text(encoding="utf-8")
    if "__preserve_v6_artifact__" not in workflow_text:
        blockers.append("preservation_workflow_mode_missing")
    if "require_github_only_execution" not in RESTORE_SCRIPT.read_text(encoding="utf-8"):
        blockers.append("restore_local_run_guard_missing")
    return sorted(blockers)


def build_receipt(
    snapshot: Mapping[str, Any],
    *,
    observed_at_utc: str,
) -> dict[str, Any]:
    blockers = _validate_snapshot(snapshot, observed_at_utc)
    if blockers:
        raise ValueError(f"preservation lease is not ready: {blockers}")
    artifact = snapshot["artifact"]
    run = snapshot["run"]
    lease = json.loads(LEASE_RECEIPT.read_text(encoding="utf-8"))
    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_g3b_owner_preservation_live_receipt_v1",
        "repository": REPOSITORY,
        "task_id": "PREV7-0208",
        "observed_at_utc": observed_at_utc,
        "owner_actor_id": "github-user:271768688",
        "owner_github_login": "gomez5757",
        "owner_directive_digest": raw_sha256(OWNER_DIRECTIVE),
        "owner_decisions_digest": raw_sha256(OWNER_DECISIONS),
        "source_lease_receipt_path": LEASE_RECEIPT.relative_to(ROOT).as_posix(),
        "source_lease_receipt_sha256": raw_sha256(LEASE_RECEIPT),
        "source_archive": lease["preservation_result"],
        "lease_artifact": {
            "id": artifact["id"],
            "name": artifact["name"],
            "size_in_bytes": artifact["size_in_bytes"],
            "digest": artifact["digest"],
            "created_at_utc": artifact["created_at"],
            "expires_at_utc": artifact["expires_at"],
            "expired": artifact["expired"],
        },
        "preservation_run": {
            "id": run["id"],
            "url": run["html_url"],
            "head_sha": run["head_sha"],
            "status": run["status"],
            "conclusion": run["conclusion"],
            "workflow_path": run["path"],
        },
        "restore_procedure": {
            "script_path": RESTORE_SCRIPT.relative_to(ROOT).as_posix(),
            "script_sha256": raw_sha256(RESTORE_SCRIPT),
            "workflow_path": PRESERVATION_WORKFLOW.relative_to(ROOT).as_posix(),
            "workflow_sha256": raw_sha256(PRESERVATION_WORKFLOW),
            "local_execution_blocked": True,
            "synthetic_reconstruction_tested": True,
            "part_digest_verification": True,
            "archive_digest_verification": True,
            "member_manifest_verification": True,
        },
        "evaluation": {"ready": True, "blockers": []},
        "owner_controlled_model": True,
        "external_copy_required": False,
        "incremental_net_spend_usd": 0,
        "github_only": True,
        "requires_local_machine": False,
        "scientific_boundaries": {
            "locked_start": "2021-01-01",
            "locked_data_accessed": False,
            "scientific_processing_performed": False,
            "local_research_run_performed": False,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_G3B_OWNER_PRESERVATION_LIVE_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    return receipt


def build_transition_manifest(
    receipt: Mapping[str, Any],
    *,
    requested_at_utc: str,
) -> dict[str, Any]:
    evidence_paths = [
        RECEIPT.relative_to(ROOT).as_posix(),
        LEASE_RECEIPT.relative_to(ROOT).as_posix(),
        OWNER_DIRECTIVE.relative_to(ROOT).as_posix(),
        OWNER_DECISIONS.relative_to(ROOT).as_posix(),
    ]
    manifest: dict[str, Any] = {
        "schema_version": "gtbi_v7_readiness_transition_manifest_v1",
        "manifest_id": "g3b-preservation-owner-v1",
        "transaction_id": "G3B_CLOSE-3",
        "requested_at_utc": requested_at_utc,
        "actor_id": "github-user:271768688",
        "actor_role": "repository_owner",
        "expected_base_ref": "refs/heads/main",
        "expected_base_sha_mode": "runtime_default_branch_head",
        "task_actions": [
            {
                "task_id": "PREV7-0208",
                "target_status": "done",
                "evidence_paths": evidence_paths,
                "evidence_sha256": [raw_sha256(ROOT / path) for path in evidence_paths],
                "terminal_reason": "owner_accepted_github_preservation_lease_verified",
                "notes": (
                    "The owner accepted the live GitHub preservation lease as sufficient. "
                    "The restore procedure is digest-bound and GitHub-only; no external "
                    "custodian, locked access, scientific work or incremental spend is required."
                ),
                "files_touched": evidence_paths,
                "expected_result": _task_expected_result(),
                "alternative_completion_receipt_set_digest_or_null": receipt["receipt_digest"],
            }
        ],
        "branch_actions": [],
        "gate_actions": [],
        "owner_directive_digest": raw_sha256(OWNER_DIRECTIVE),
        "manifest_digest": "",
    }
    manifest["manifest_digest"] = domain_digest(
        "GTBI_V7_READINESS_TRANSITION_MANIFEST_V1",
        manifest,
        omit_top_level_fields=("manifest_digest",),
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observed-at-utc", default=None)
    args = parser.parse_args(argv)
    observed_at_utc = args.observed_at_utc or datetime.now(timezone.utc).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")
    receipt = build_receipt(capture_live_snapshot(), observed_at_utc=observed_at_utc)
    RECEIPT.write_bytes(canonical_bytes(receipt) + b"\n")
    manifest = build_transition_manifest(receipt, requested_at_utc=observed_at_utc)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_bytes(canonical_bytes(manifest) + b"\n")
    print(json.dumps(receipt["evaluation"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
