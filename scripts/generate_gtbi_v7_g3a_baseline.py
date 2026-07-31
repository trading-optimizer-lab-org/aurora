"""Apply, capture and freeze the owner-controlled GTBI V7 G3A baseline."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping
from urllib.parse import quote

from infra.gtbi_v7_readiness.canonical import (
    canonical_bytes,
    domain_digest,
    raw_sha256,
)
from infra.gtbi_v7_readiness.g3a_governance import (
    CANONICAL_SOURCE_ENVIRONMENTS,
    G3A_BASELINE_TASK_IDS,
    REPOSITORY,
    REPOSITORY_OWNER_ACTOR_ID,
    build_g3a_policy,
    evaluate_live_state,
    source_environment_api_payload,
    validate_task_completion,
)

ROOT = Path(__file__).resolve().parents[1]
READINESS = ROOT / "docs/readiness/gtbi-v7"
POLICY = ROOT / "config/gtbi/governance/g3a_minimum_governance_policy.json"
RECEIPT = READINESS / "g3a_github_live_receipt.json"
MANIFEST = (
    READINESS
    / "transition_manifests/g3a-minimum-governance-close-v1.json"
)


class GitHubCommandError(RuntimeError):
    """A required GitHub API command failed."""


def _run(
    args: list[str],
    *,
    input_bytes: bytes | None = None,
    allow_not_found: bool = False,
) -> str:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace")
        if allow_not_found and "HTTP 404" in stderr:
            return ""
        raise GitHubCommandError(
            f"command failed ({completed.returncode}): "
            f"{' '.join(args)}\n{stderr}"
        )
    return completed.stdout.decode("utf-8")


def _gh_json(
    endpoint: str,
    *,
    method: str = "GET",
    body: Mapping[str, Any] | None = None,
    allow_not_found: bool = False,
) -> Any:
    args = ["gh", "api"]
    if method != "GET":
        args.extend(["--method", method])
    args.append(endpoint)
    input_bytes = None
    if body is not None:
        args.extend(["--input", "-"])
        input_bytes = canonical_bytes(body)
    raw = _run(
        args,
        input_bytes=input_bytes,
        allow_not_found=allow_not_found,
    )
    if not raw:
        return None
    return json.loads(raw)


def apply_source_environments() -> None:
    for name in CANONICAL_SOURCE_ENVIRONMENTS:
        _gh_json(
            f"/repos/{REPOSITORY}/environments/{quote(name, safe='')}",
            method="PUT",
            body=source_environment_api_payload(name),
        )


def _environment_snapshot(name: str) -> tuple[dict[str, Any], dict[str, int]]:
    encoded = quote(name, safe="")
    environment = _gh_json(
        f"/repos/{REPOSITORY}/environments/{encoded}"
    )
    branch_policies = _gh_json(
        (
            f"/repos/{REPOSITORY}/environments/{encoded}/"
            "deployment-branch-policies"
        ),
        allow_not_found=True,
    )
    secrets = _gh_json(
        f"/repos/{REPOSITORY}/environments/{encoded}/secrets",
        allow_not_found=True,
    )
    counts = {
        "custom_branch_policy_count": int(
            (branch_policies or {}).get("total_count", 0)
        ),
        "secret_count": int((secrets or {}).get("total_count", 0)),
    }
    return environment, counts


def capture_live_snapshot() -> dict[str, Any]:
    environments: list[dict[str, Any]] = []
    auxiliary_counts: dict[str, dict[str, int]] = {}
    for name in CANONICAL_SOURCE_ENVIRONMENTS:
        environment, counts = _environment_snapshot(name)
        environments.append(environment)
        auxiliary_counts[name] = counts
    installations = _gh_json(
        "/orgs/trading-optimizer-lab-org/installations"
    )
    return {
        "repository": _gh_json(f"/repos/{REPOSITORY}"),
        "branch_protection": _gh_json(
            f"/repos/{REPOSITORY}/branches/main/protection"
        ),
        "workflow_permissions": _gh_json(
            f"/repos/{REPOSITORY}/actions/permissions/workflow"
        ),
        "code_scanning_default_setup": _gh_json(
            f"/repos/{REPOSITORY}/code-scanning/default-setup"
        ),
        "environments": environments,
        "environment_auxiliary_counts": auxiliary_counts,
        "app_installations": (installations or {}).get(
            "installations",
            [],
        ),
    }


def _workflow_policy_report() -> dict[str, Any]:
    raw = _run(
        [
            sys.executable,
            "scripts/validate_github_workflow_policy.py",
            "--repo-root",
            ".",
            "--allowlist",
            "config/legacy_workflow_allowlist.json",
            "--migrations",
            "config/legacy_workflow_migrations.json",
        ]
    )
    return json.loads(raw)


def _compact_environment(
    environment: Mapping[str, Any],
    counts: Mapping[str, int],
) -> dict[str, Any]:
    branch_policy = environment.get("deployment_branch_policy") or {}
    reviewers: list[dict[str, Any]] = []
    wait_timer = 0
    prevent_self_review = False
    for rule in environment.get("protection_rules", []):
        if rule.get("type") == "required_reviewers":
            prevent_self_review = bool(rule.get("prevent_self_review"))
            for item in rule.get("reviewers", []):
                reviewer = item.get("reviewer") or {}
                reviewers.append(
                    {
                        "type": reviewer.get("type"),
                        "id": reviewer.get("id"),
                        "login": reviewer.get("login"),
                    }
                )
        elif rule.get("type") == "wait_timer":
            wait_timer = int(rule.get("wait_timer", 0))
    return {
        "id": environment.get("id"),
        "name": environment.get("name"),
        "wait_timer": wait_timer,
        "prevent_self_review": prevent_self_review,
        "reviewers": reviewers,
        "deployment_branch_policy": {
            "protected_branches": bool(
                branch_policy.get("protected_branches")
            ),
            "custom_branch_policies": bool(
                branch_policy.get("custom_branch_policies")
            ),
        },
        "custom_branch_policy_count": int(
            counts.get("custom_branch_policy_count", 0)
        ),
        "secret_count": int(counts.get("secret_count", 0)),
    }


def build_live_receipt(
    snapshot: Mapping[str, Any],
    workflow_policy_report: Mapping[str, Any],
    *,
    observed_at_utc: str,
) -> dict[str, Any]:
    policy = build_g3a_policy()
    evaluation = evaluate_live_state(
        snapshot,
        workflow_policy_valid=bool(workflow_policy_report["valid"]),
    )
    repository = snapshot["repository"]
    security = repository.get("security_and_analysis") or {}
    branch = snapshot["branch_protection"]
    reviews = branch.get("required_pull_request_reviews") or {}
    checks = branch.get("required_status_checks") or {}
    receipt: dict[str, Any] = {
        "schema_version": "gtbi_v7_g3a_github_live_receipt_v1",
        "repository": REPOSITORY,
        "repository_id": repository["id"],
        "default_branch": repository["default_branch"],
        "observed_at_utc": observed_at_utc,
        "policy": {
            "path": (
                "config/gtbi/governance/"
                "g3a_minimum_governance_policy.json"
            ),
            "policy_digest": policy["policy_digest"],
        },
        "branch_protection": {
            "pull_request_required": bool(
                branch.get("required_pull_request_reviews")
            ),
            "required_approving_review_count": int(
                reviews.get("required_approving_review_count", -1)
            ),
            "required_status_checks_strict": bool(checks.get("strict")),
            "required_status_checks": list(checks.get("checks") or []),
            "enforce_admins": bool(
                (branch.get("enforce_admins") or {}).get("enabled")
            ),
            "allow_force_pushes": bool(
                (branch.get("allow_force_pushes") or {}).get("enabled")
            ),
            "allow_deletions": bool(
                (branch.get("allow_deletions") or {}).get("enabled")
            ),
            "required_conversation_resolution": bool(
                (
                    branch.get("required_conversation_resolution") or {}
                ).get("enabled")
            ),
        },
        "actions": {
            **snapshot["workflow_permissions"],
            "workflow_policy_valid": bool(
                workflow_policy_report["valid"]
            ),
            "workflow_count": int(
                workflow_policy_report["workflow_count"]
            ),
            "workflow_policy_report_digest": domain_digest(
                "GTBI_V7_WORKFLOW_POLICY_REPORT_V1",
                workflow_policy_report,
            ),
        },
        "security": {
            "dependabot_security_updates": (
                security.get("dependabot_security_updates") or {}
            ).get("status"),
            "code_scanning_default_setup": snapshot[
                "code_scanning_default_setup"
            ],
            "secret_scanning": (
                security.get("secret_scanning") or {}
            ).get("status"),
            "secret_scanning_non_provider_patterns": (
                security.get("secret_scanning_non_provider_patterns") or {}
            ).get("status"),
            "secret_scanning_push_protection": (
                security.get("secret_scanning_push_protection") or {}
            ).get("status"),
            "secret_scanning_validity_checks": (
                security.get("secret_scanning_validity_checks") or {}
            ).get("status"),
        },
        "canonical_source_environments": [
            _compact_environment(
                environment,
                snapshot["environment_auxiliary_counts"][
                    environment["name"]
                ],
            )
            for environment in snapshot["environments"]
        ],
        "source_github_apps": {
            "installation_count": len(snapshot["app_installations"]),
            "installations": [
                {
                    "id": item.get("id"),
                    "app_id": item.get("app_id"),
                    "app_slug": item.get("app_slug"),
                    "repository_selection": item.get(
                        "repository_selection"
                    ),
                    "suspended_at": item.get("suspended_at"),
                }
                for item in snapshot["app_installations"]
            ],
            "status": (
                "installed"
                if snapshot["app_installations"]
                else "pending_provider_web_authorization"
            ),
        },
        "evaluation": evaluation.as_dict(),
        "scientific_boundaries": {
            "locked_start": "2021-01-01",
            "locked_data_accessed": False,
            "scientific_processing_performed": False,
            "local_research_run_performed": False,
        },
        "receipt_digest": "",
    }
    receipt["receipt_digest"] = domain_digest(
        "GTBI_V7_G3A_GITHUB_LIVE_RECEIPT_V1",
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
            if row["id"] in G3A_BASELINE_TASK_IDS
        }


def _evidence_sha256(paths: tuple[str, ...]) -> list[str]:
    return [raw_sha256(ROOT / path) for path in paths]


def build_transition_manifest(
    receipt: Mapping[str, Any],
    *,
    requested_at_utc: str,
) -> dict[str, Any]:
    completion = receipt["evaluation"]["task_completion"]
    for task_id in G3A_BASELINE_TASK_IDS:
        if not completion[task_id]:
            raise GitHubCommandError(
                f"cannot close {task_id}; live baseline is not satisfied"
            )
    expected_results = _expected_results()
    common_paths = (
        "docs/readiness/gtbi-v7/g3a_github_live_receipt.json",
        "docs/readiness/gtbi-v7/owner_simplification_directive.json",
    )
    task_paths = {
        "PREV7-0202": common_paths,
        "PREV7-0205": common_paths,
        "PREV7-0206": common_paths,
    }
    manifest: dict[str, Any] = {
        "schema_version": "gtbi_v7_readiness_transition_manifest_v1",
        "manifest_id": "g3a-minimum-governance-close-v1",
        "transaction_id": "G3A_CLOSE-1",
        "requested_at_utc": requested_at_utc,
        "actor_id": REPOSITORY_OWNER_ACTOR_ID,
        "actor_role": "repository_owner",
        "expected_base_ref": "refs/heads/main",
        "expected_base_sha_mode": "runtime_default_branch_head",
        "task_actions": [
            {
                "task_id": task_id,
                "target_status": "done",
                "evidence_paths": list(task_paths[task_id]),
                "evidence_sha256": _evidence_sha256(
                    task_paths[task_id]
                ),
                "terminal_reason": {
                    "PREV7-0202": "stage_one_main_protection_verified",
                    "PREV7-0205": (
                        "pinned_actions_and_minimum_permissions_verified"
                    ),
                    "PREV7-0206": "github_security_baseline_verified",
                }[task_id],
                "notes": (
                    "Live GitHub state and repository policy satisfy this "
                    "minimum G3A task without scientific work, locked access "
                    "or incremental spend. Source App tasks remain blocked "
                    "until provider web authorization returns live IDs."
                ),
                "files_touched": list(task_paths[task_id]),
                "expected_result": expected_results[task_id],
                "alternative_completion_receipt_set_digest_or_null": None,
            }
            for task_id in G3A_BASELINE_TASK_IDS
        ],
        "branch_actions": [],
        "gate_actions": [],
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply-environments",
        action="store_true",
        help="Create or update only the canonical source environments.",
    )
    parser.add_argument(
        "--observed-at-utc",
        default=None,
        help="Stable timestamp for deterministic regeneration.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.apply_environments:
        apply_source_environments()
    workflow_report = _workflow_policy_report()
    snapshot = capture_live_snapshot()
    evaluation = evaluate_live_state(
        snapshot,
        workflow_policy_valid=bool(workflow_report["valid"]),
    )
    validate_task_completion(evaluation, G3A_BASELINE_TASK_IDS)
    observed_at_utc = args.observed_at_utc or datetime.now(
        timezone.utc
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    policy = build_g3a_policy()
    POLICY.parent.mkdir(parents=True, exist_ok=True)
    POLICY.write_bytes(canonical_bytes(policy) + b"\n")
    receipt = build_live_receipt(
        snapshot,
        workflow_report,
        observed_at_utc=observed_at_utc,
    )
    RECEIPT.write_bytes(canonical_bytes(receipt) + b"\n")
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_bytes(
        canonical_bytes(
            build_transition_manifest(
                receipt,
                requested_at_utc=observed_at_utc,
            )
        )
        + b"\n"
    )
    print(json.dumps(receipt["evaluation"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
