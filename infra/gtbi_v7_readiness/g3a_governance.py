"""Owner-controlled minimum GitHub governance for GTBI V7 gate G3A."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .canonical import domain_digest

REPOSITORY = "trading-optimizer-lab-org/aurora"
REPOSITORY_OWNER_ID = 271768688
REPOSITORY_OWNER_ACTOR_ID = "github-user:271768688"

G3A_BASELINE_TASK_IDS = (
    "PREV7-0202",
    "PREV7-0205",
    "PREV7-0206",
)
G3A_APP_TASK_IDS = ("PREV7-0204", "PREV7-0210")

OWNER_REVIEW_ENVIRONMENTS = (
    "gtbi-assets-read",
    "gtbi-assets-primary-publish",
    "gtbi-assets-mirror-publish",
    "gtbi-result-validate",
    "gtbi-dispatch",
    "gtbi-scientific-review",
    "gtbi-workflow-review",
    "gtbi-acceptable-use-review",
    "gtbi-security-review",
    "gtbi-full-authorization",
    "gtbi-security-control",
    "gtbi-environment-policy-control",
    "gtbi-repository-retire",
)
LOCKED_DENY_ENVIRONMENT = "gtbi-forward-locked"
CANONICAL_SOURCE_ENVIRONMENTS = (
    *OWNER_REVIEW_ENVIRONMENTS,
    LOCKED_DENY_ENVIRONMENT,
)


class G3AGovernanceError(ValueError):
    """The observed GitHub state does not satisfy the declared baseline."""


@dataclass(frozen=True)
class BaselineEvaluation:
    task_completion: dict[str, bool]
    app_installation_count: int
    environment_count: int
    g3a_ready: bool
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_completion": self.task_completion,
            "app_installation_count": self.app_installation_count,
            "environment_count": self.environment_count,
            "g3a_ready": self.g3a_ready,
            "blockers": list(self.blockers),
        }


def expected_environment_policy(name: str) -> dict[str, Any]:
    """Return the exact owner-controlled policy for one source environment."""
    if name == LOCKED_DENY_ENVIRONMENT:
        return {
            "name": name,
            "wait_timer": 0,
            "prevent_self_review": False,
            "reviewers": [],
            "deployment_branch_policy": {
                "protected_branches": False,
                "custom_branch_policies": True,
            },
            "expected_custom_branch_policy_count": 0,
            "locked_access_enabled": False,
            "credential_classes": [],
        }
    if name not in OWNER_REVIEW_ENVIRONMENTS:
        raise G3AGovernanceError(f"unknown canonical environment: {name}")
    return {
        "name": name,
        "wait_timer": 0,
        "prevent_self_review": False,
        "reviewers": [
            {
                "type": "User",
                "id": REPOSITORY_OWNER_ID,
            }
        ],
        "deployment_branch_policy": {
            "protected_branches": True,
            "custom_branch_policies": False,
        },
        "expected_custom_branch_policy_count": 0,
        "locked_access_enabled": False,
        "credential_classes": [],
    }


def expected_environment_registry() -> list[dict[str, Any]]:
    return [
        expected_environment_policy(name)
        for name in CANONICAL_SOURCE_ENVIRONMENTS
    ]


def build_g3a_policy() -> dict[str, Any]:
    """Build the deterministic owner-controlled G3A baseline contract."""
    payload: dict[str, Any] = {
        "schema_version": "gtbi_v7_g3a_minimum_governance_policy_v1",
        "repository": REPOSITORY,
        "owner_actor_id": REPOSITORY_OWNER_ACTOR_ID,
        "maximum_incremental_net_spend_usd": 0,
        "branch_protection": {
            "branch": "main",
            "pull_request_required": True,
            "required_approving_review_count": 0,
            "required_status_checks": [],
            "required_status_checks_strict": True,
            "enforce_admins": True,
            "allow_force_pushes": False,
            "allow_deletions": False,
            "required_conversation_resolution": True,
            "bypass_actor_count": 0,
        },
        "actions": {
            "default_workflow_permissions": "read",
            "can_approve_pull_request_reviews": False,
            "workflow_runtime": "github_hosted_only",
            "workflow_adoption_policy": (
                "immutable_legacy_allowlist_and_fail_closed_future_policy"
            ),
            "new_or_changed_action_references_must_be_sha_pinned": True,
            "mutable_action_tags_allowed": False,
        },
        "security": {
            "dependabot_security_updates": "enabled",
            "code_scanning_default_setup": "configured",
            "code_scanning_languages": ["actions", "python"],
            "secret_scanning": "enabled",
            "secret_scanning_non_provider_patterns": "enabled",
            "secret_scanning_push_protection": "enabled",
            "secret_scanning_validity_checks": "enabled",
        },
        "canonical_source_environments": expected_environment_registry(),
        "github_apps": {
            "installation_required_for_g3a": True,
            "definition_and_installation_tasks": list(G3A_APP_TASK_IDS),
            "installation_state": "pending_provider_web_authorization",
            "must_not_be_reported_complete_without_live_ids": True,
        },
        "scientific_boundaries": {
            "locked_start": "2021-01-01",
            "locked_access_enabled": False,
            "scientific_processing_performed": False,
            "local_research_run_performed": False,
        },
        "policy_digest": "",
    }
    payload["policy_digest"] = domain_digest(
        "GTBI_V7_G3A_MINIMUM_GOVERNANCE_POLICY_V1",
        payload,
        omit_top_level_fields=("policy_digest",),
    )
    return payload


def _reviewer_ids(environment: Mapping[str, Any]) -> set[int]:
    ids: set[int] = set()
    for rule in environment.get("protection_rules", []):
        if rule.get("type") != "required_reviewers":
            continue
        for reviewer in rule.get("reviewers", []):
            entity = reviewer.get("reviewer") or {}
            if entity.get("type") == "User" and entity.get("id") is not None:
                ids.add(int(entity["id"]))
    return ids


def _wait_timer(environment: Mapping[str, Any]) -> int:
    for rule in environment.get("protection_rules", []):
        if rule.get("type") == "wait_timer":
            return int(rule.get("wait_timer", 0))
    return 0


def _prevent_self_review(environment: Mapping[str, Any]) -> bool:
    for rule in environment.get("protection_rules", []):
        if rule.get("type") == "required_reviewers":
            return bool(rule.get("prevent_self_review", False))
    return False


def environment_matches_policy(
    environment: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    custom_branch_policy_count: int,
    secret_count: int,
) -> bool:
    branch_policy = environment.get("deployment_branch_policy") or {}
    expected_branch_policy = expected["deployment_branch_policy"]
    actual_reviewers = _reviewer_ids(environment)
    expected_reviewers = {
        int(item["id"]) for item in expected.get("reviewers", [])
    }
    return all(
        (
            environment.get("name") == expected["name"],
            _wait_timer(environment) == expected["wait_timer"],
            _prevent_self_review(environment)
            == expected["prevent_self_review"],
            actual_reviewers == expected_reviewers,
            bool(branch_policy.get("protected_branches"))
            == expected_branch_policy["protected_branches"],
            bool(branch_policy.get("custom_branch_policies"))
            == expected_branch_policy["custom_branch_policies"],
            custom_branch_policy_count
            == expected["expected_custom_branch_policy_count"],
            secret_count == 0,
        )
    )


def _branch_protection_matches(
    observed: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> bool:
    reviews = observed.get("required_pull_request_reviews") or {}
    checks = observed.get("required_status_checks") or {}
    bypass = reviews.get("bypass_pull_request_allowances") or {}
    bypass_count = sum(
        len(bypass.get(key) or ())
        for key in ("apps", "teams", "users")
    )
    return all(
        (
            bool(observed.get("required_pull_request_reviews")),
            int(reviews.get("required_approving_review_count", -1))
            == expected["required_approving_review_count"],
            bool(checks.get("strict"))
            == expected["required_status_checks_strict"],
            list(checks.get("checks") or ())
            == expected["required_status_checks"],
            bool((observed.get("enforce_admins") or {}).get("enabled"))
            == expected["enforce_admins"],
            bool((observed.get("allow_force_pushes") or {}).get("enabled"))
            == expected["allow_force_pushes"],
            bool((observed.get("allow_deletions") or {}).get("enabled"))
            == expected["allow_deletions"],
            bool(
                (
                    observed.get("required_conversation_resolution")
                    or {}
                ).get("enabled")
            )
            == expected["required_conversation_resolution"],
            bypass_count == expected["bypass_actor_count"],
        )
    )


def _security_matches(
    repository: Mapping[str, Any],
    code_scanning: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> bool:
    security = repository.get("security_and_analysis") or {}
    return all(
        (
            (security.get("dependabot_security_updates") or {}).get("status")
            == expected["dependabot_security_updates"],
            code_scanning.get("state")
            == expected["code_scanning_default_setup"],
            sorted(code_scanning.get("languages") or ())
            == expected["code_scanning_languages"],
            (security.get("secret_scanning") or {}).get("status")
            == expected["secret_scanning"],
            (
                security.get("secret_scanning_non_provider_patterns")
                or {}
            ).get("status")
            == expected["secret_scanning_non_provider_patterns"],
            (
                security.get("secret_scanning_push_protection") or {}
            ).get("status")
            == expected["secret_scanning_push_protection"],
            (
                security.get("secret_scanning_validity_checks") or {}
            ).get("status")
            == expected["secret_scanning_validity_checks"],
        )
    )


def _actions_matches(
    workflow_permissions: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    workflow_policy_valid: bool,
) -> bool:
    return all(
        (
            workflow_permissions.get("default_workflow_permissions")
            == expected["default_workflow_permissions"],
            bool(
                workflow_permissions.get(
                    "can_approve_pull_request_reviews",
                    True,
                )
            )
            == expected["can_approve_pull_request_reviews"],
            workflow_policy_valid,
        )
    )


def evaluate_live_state(
    snapshot: Mapping[str, Any],
    *,
    workflow_policy_valid: bool,
) -> BaselineEvaluation:
    """Evaluate one API snapshot without mutating GitHub."""
    policy = build_g3a_policy()
    blockers: list[str] = []

    branch_ok = _branch_protection_matches(
        snapshot["branch_protection"],
        policy["branch_protection"],
    )
    if not branch_ok:
        blockers.append("stage_one_main_protection_mismatch")

    actions_ok = _actions_matches(
        snapshot["workflow_permissions"],
        policy["actions"],
        workflow_policy_valid=workflow_policy_valid,
    )
    if not actions_ok:
        blockers.append("actions_policy_mismatch")

    security_ok = _security_matches(
        snapshot["repository"],
        snapshot["code_scanning_default_setup"],
        policy["security"],
    )
    if not security_ok:
        blockers.append("security_baseline_mismatch")

    environments_by_name = {
        item["name"]: item for item in snapshot.get("environments", [])
    }
    environment_counts = snapshot.get("environment_auxiliary_counts", {})
    missing_or_invalid_environments: list[str] = []
    for expected in policy["canonical_source_environments"]:
        name = expected["name"]
        observed = environments_by_name.get(name)
        counts = environment_counts.get(name, {})
        if observed is None or not environment_matches_policy(
            observed,
            expected,
            custom_branch_policy_count=int(
                counts.get("custom_branch_policy_count", 0)
            ),
            secret_count=int(counts.get("secret_count", 0)),
        ):
            missing_or_invalid_environments.append(name)
    if missing_or_invalid_environments:
        blockers.append(
            "canonical_source_environments_missing_or_invalid:"
            + ",".join(missing_or_invalid_environments)
        )

    installation_count = len(snapshot.get("app_installations", []))
    if installation_count == 0:
        blockers.append("source_github_app_installations_missing")
    else:
        blockers.append("source_github_app_contract_not_yet_verified")

    task_completion = {
        "PREV7-0202": branch_ok,
        "PREV7-0204": False,
        "PREV7-0205": actions_ok,
        "PREV7-0206": security_ok,
        "PREV7-0210": False,
    }
    return BaselineEvaluation(
        task_completion=task_completion,
        app_installation_count=installation_count,
        environment_count=len(environments_by_name),
        g3a_ready=all(task_completion.values()),
        blockers=tuple(blockers),
    )


def source_environment_api_payload(name: str) -> dict[str, Any]:
    """Return the provider API body without repository-local metadata."""
    policy = expected_environment_policy(name)
    return {
        "wait_timer": policy["wait_timer"],
        "prevent_self_review": policy["prevent_self_review"],
        "reviewers": policy["reviewers"],
        "deployment_branch_policy": policy["deployment_branch_policy"],
    }


def validate_task_completion(
    evaluation: BaselineEvaluation,
    task_ids: Sequence[str],
) -> None:
    incomplete = [
        task_id
        for task_id in task_ids
        if not evaluation.task_completion.get(task_id, False)
    ]
    if incomplete:
        raise G3AGovernanceError(
            "G3A tasks are not satisfied: " + ", ".join(incomplete)
        )
