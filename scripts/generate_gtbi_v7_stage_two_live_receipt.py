"""Capture and freeze the live owner-controlled stage-two state."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infra.gtbi_v7_readiness.canonical import (
    canonical_bytes,
    domain_digest,
    raw_sha256,
)
from infra.gtbi_v7_readiness.g3a_governance import REPOSITORY
from infra.gtbi_v7_readiness.stage_two_protection import (
    REQUIRED_CHECK_CONTEXT,
    evaluate_live_state,
)
from scripts.configure_gtbi_v7_stage_two_protection import (
    _gh_json,
    capture_live_snapshot,
)

READINESS = ROOT / "docs/readiness/gtbi-v7"
POLICY = ROOT / "config/gtbi/governance/stage_two_owner_controlled_protection.json"
OWNER_DIRECTIVE = READINESS / "owner_simplification_directive.json"
OWNER_DECISIONS = READINESS / "owner_decisions.json"
CODEOWNERS = ROOT / ".github/CODEOWNERS"
RECEIPT = READINESS / "g3b_stage_two_owner_live_receipt.json"
MANIFEST = READINESS / "transition_manifests/g3b-stage-two-owner-v1.json"
WORKFLOW_PATH = ".github/workflows/gtbi-v7-stage-two-required.yml"


def _task_expected_result() -> str:
    with (READINESS / "task_status.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        rows = list(csv.DictReader(handle))
    return next(row["expected_result"] for row in rows if row["id"] == "PREV7-0207")


def capture_verified_live_snapshot() -> dict[str, Any]:
    snapshot = capture_live_snapshot()
    codeowners = _gh_json(f"/repos/{REPOSITORY}/codeowners/errors?ref=main")
    branch = _gh_json(f"/repos/{REPOSITORY}/branches/main")
    runs = _gh_json(
        f"/repos/{REPOSITORY}/actions/workflows/"
        "gtbi-v7-stage-two-required.yml/runs?branch=main&status=success&per_page=1"
    )
    workflow_runs = (runs or {}).get("workflow_runs", [])
    run = workflow_runs[0] if workflow_runs else None
    snapshot["codeowners_valid"] = (codeowners or {}).get("errors") == []
    snapshot["required_check_observed"] = bool(
        run
        and run.get("head_sha") == branch["commit"]["sha"]
        and run.get("conclusion") == "success"
    )
    snapshot["main_sha"] = branch["commit"]["sha"]
    snapshot["required_check_run"] = run
    return snapshot


def _compact_branch(branch: Mapping[str, Any]) -> dict[str, Any]:
    checks = branch.get("required_status_checks") or {}
    reviews = branch.get("required_pull_request_reviews") or {}

    def enabled(name: str) -> bool:
        value = branch.get(name) or {}
        return bool(value.get("enabled"))

    return {
        "required_status_checks_strict": bool(checks.get("strict")),
        "required_status_checks": list(checks.get("checks") or []),
        "required_approving_review_count": int(reviews.get("required_approving_review_count", -1)),
        "require_code_owner_reviews": bool(reviews.get("require_code_owner_reviews")),
        "require_last_push_approval": bool(reviews.get("require_last_push_approval")),
        "dismiss_stale_reviews": bool(reviews.get("dismiss_stale_reviews")),
        "enforce_admins": enabled("enforce_admins"),
        "required_conversation_resolution": enabled("required_conversation_resolution"),
        "allow_force_pushes": enabled("allow_force_pushes"),
        "allow_deletions": enabled("allow_deletions"),
    }


def build_receipt(
    snapshot: Mapping[str, Any],
    *,
    observed_at_utc: str,
) -> dict[str, Any]:
    evaluation = evaluate_live_state(snapshot)
    if not evaluation.ready:
        raise ValueError(f"stage-two state is not ready: {evaluation.blockers}")
    run = snapshot["required_check_run"]
    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_owner_controlled_stage_two_live_receipt_v1",
        "repository": REPOSITORY,
        "task_id": "PREV7-0207",
        "observed_at_utc": observed_at_utc,
        "main_sha": snapshot["main_sha"],
        "owner_actor_id": "github-user:271768688",
        "owner_github_login": "gomez5757",
        "policy_path": POLICY.relative_to(ROOT).as_posix(),
        "policy_file_sha256": raw_sha256(POLICY),
        "owner_directive_digest": raw_sha256(OWNER_DIRECTIVE),
        "owner_decisions_digest": raw_sha256(OWNER_DECISIONS),
        "codeowners_path": CODEOWNERS.relative_to(ROOT).as_posix(),
        "codeowners_sha256": raw_sha256(CODEOWNERS),
        "codeowners_valid": bool(snapshot["codeowners_valid"]),
        "branch_protection": _compact_branch(snapshot["branch_protection"]),
        "required_check": {
            "context": REQUIRED_CHECK_CONTEXT,
            "workflow_path": WORKFLOW_PATH,
            "run_id": int(run["id"]),
            "run_url": run["html_url"],
            "head_sha": run["head_sha"],
            "status": run["status"],
            "conclusion": run["conclusion"],
        },
        "environments": list(snapshot["environments"]),
        "evaluation": evaluation.as_dict(),
        "owner_controlled_model": True,
        "external_reviewers_required": False,
        "incremental_net_spend_usd": 0,
        "scientific_boundaries": {
            "locked_start": "2021-01-01",
            "locked_data_accessed": False,
            "scientific_processing_performed": False,
            "local_research_run_performed": False,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_OWNER_CONTROLLED_STAGE_TWO_LIVE_RECEIPT_V1",
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
        OWNER_DIRECTIVE.relative_to(ROOT).as_posix(),
        OWNER_DECISIONS.relative_to(ROOT).as_posix(),
    ]
    manifest: dict[str, Any] = {
        "schema_version": "gtbi_v7_readiness_transition_manifest_v1",
        "manifest_id": "g3b-stage-two-owner-v1",
        "transaction_id": "G3B_CLOSE-2",
        "requested_at_utc": requested_at_utc,
        "actor_id": "github-user:271768688",
        "actor_role": "repository_owner",
        "expected_base_ref": "refs/heads/main",
        "expected_base_sha_mode": "runtime_default_branch_head",
        "task_actions": [
            {
                "task_id": "PREV7-0207",
                "target_status": "done",
                "evidence_paths": evidence_paths,
                "evidence_sha256": [raw_sha256(ROOT / path) for path in evidence_paths],
                "terminal_reason": "owner_controlled_stage_two_protection_verified",
                "notes": (
                    "Live GitHub main protection requires the unconditional "
                    "owner-approved automated check. Human approvals remain "
                    "non-blocking under the owner directive. Locked access "
                    "remains closed and incremental spend is zero."
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observed-at-utc", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    observed_at_utc = args.observed_at_utc or datetime.now(timezone.utc).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")
    snapshot = capture_verified_live_snapshot()
    receipt = build_receipt(snapshot, observed_at_utc=observed_at_utc)
    RECEIPT.write_bytes(canonical_bytes(receipt) + b"\n")
    manifest = build_transition_manifest(
        receipt,
        requested_at_utc=observed_at_utc,
    )
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_bytes(canonical_bytes(manifest) + b"\n")
    print(json.dumps(receipt["evaluation"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
