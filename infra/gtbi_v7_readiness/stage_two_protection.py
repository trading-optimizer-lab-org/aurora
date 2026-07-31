"""Owner-controlled stage-two GitHub protection contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from infra.gtbi_v7_readiness.canonical import domain_digest
from infra.gtbi_v7_readiness.g3a_governance import (
    CANONICAL_SOURCE_ENVIRONMENTS,
    LOCKED_DENY_ENVIRONMENT,
    REPOSITORY,
    REPOSITORY_OWNER_ACTOR_ID,
    REPOSITORY_OWNER_ID,
    source_environment_api_payload,
)

REQUIRED_CHECK_CONTEXT = "GTBI V7 stage-two required"
GITHUB_ACTIONS_APP_ID = 15_368


@dataclass(frozen=True)
class StageTwoEvaluation:
    ready: bool
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "blockers": list(self.blockers)}


def build_policy() -> dict[str, Any]:
    policy: dict[str, Any] = {
        "schema_version": "gtbi_v7_owner_controlled_stage_two_policy_v1",
        "repository": REPOSITORY,
        "branch": "main",
        "owner_actor_id": REPOSITORY_OWNER_ACTOR_ID,
        "owner_github_login": "gomez5757",
        "owner_github_id": REPOSITORY_OWNER_ID,
        "required_status_checks": [
            {
                "context": REQUIRED_CHECK_CONTEXT,
                "app_id": GITHUB_ACTIONS_APP_ID,
            }
        ],
        "required_status_checks_strict": True,
        "required_pull_request": True,
        "required_approving_review_count": 0,
        "require_code_owner_reviews": False,
        "require_last_push_approval": False,
        "dismiss_stale_reviews": False,
        "enforce_admins": True,
        "required_conversation_resolution": True,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "environment_names": list(CANONICAL_SOURCE_ENVIRONMENTS),
        "environment_approval_model": "verified_repository_owner",
        "external_reviewers_required": False,
        "incremental_net_spend_usd": 0,
        "locked_start": "2021-01-01",
        "locked_access_enabled": False,
        "scientific_processing_performed": False,
        "policy_digest": "",
    }
    policy["policy_digest"] = domain_digest(
        "GTBI_V7_OWNER_CONTROLLED_STAGE_TWO_POLICY_V1",
        policy,
        omit_top_level_fields=("policy_digest",),
    )
    return policy


def branch_protection_api_payload() -> dict[str, Any]:
    policy = build_policy()
    return {
        "required_status_checks": {
            "strict": policy["required_status_checks_strict"],
            "checks": policy["required_status_checks"],
        },
        "enforce_admins": policy["enforce_admins"],
        "required_pull_request_reviews": {
            "dismiss_stale_reviews": policy["dismiss_stale_reviews"],
            "require_code_owner_reviews": policy["require_code_owner_reviews"],
            "required_approving_review_count": policy["required_approving_review_count"],
            "require_last_push_approval": policy["require_last_push_approval"],
        },
        "restrictions": None,
        "required_linear_history": False,
        "allow_force_pushes": policy["allow_force_pushes"],
        "allow_deletions": policy["allow_deletions"],
        "block_creations": False,
        "required_conversation_resolution": policy["required_conversation_resolution"],
        "lock_branch": False,
        "allow_fork_syncing": False,
    }


def _environment_valid(item: Mapping[str, Any]) -> bool:
    name = str(item.get("name", ""))
    expected = source_environment_api_payload(name)
    if item.get("deployment_branch_policy") != expected["deployment_branch_policy"]:
        return False
    if int(item.get("secret_count", -1)) != 0:
        return False
    reviewers = item.get("reviewers") or []
    if name == LOCKED_DENY_ENVIRONMENT:
        return reviewers == [] and int(item.get("custom_branch_policy_count", -1)) == 0
    return (
        reviewers == [{"type": "User", "id": REPOSITORY_OWNER_ID, "login": "gomez5757"}]
        and item.get("prevent_self_review") is False
    )


def evaluate_live_state(snapshot: Mapping[str, Any]) -> StageTwoEvaluation:
    blockers: list[str] = []
    branch = snapshot.get("branch_protection") or {}
    checks = branch.get("required_status_checks") or {}
    reviews = branch.get("required_pull_request_reviews") or {}
    expected_checks = build_policy()["required_status_checks"]
    if checks.get("strict") is not True:
        blockers.append("required_status_checks_not_strict")
    if checks.get("checks") != expected_checks:
        blockers.append("required_status_checks_mismatch")
    if int(reviews.get("required_approving_review_count", -1)) != 0:
        blockers.append("human_approval_count_not_owner_controlled")
    if reviews.get("require_code_owner_reviews") is not False:
        blockers.append("blocking_code_owner_review_enabled")
    if reviews.get("require_last_push_approval") is not False:
        blockers.append("blocking_last_push_approval_enabled")
    for field, expected in (
        ("enforce_admins", True),
        ("required_conversation_resolution", True),
        ("allow_force_pushes", False),
        ("allow_deletions", False),
    ):
        value = branch.get(field)
        if isinstance(value, Mapping):
            value = value.get("enabled")
        if value is not expected:
            blockers.append(f"branch_{field}_mismatch")

    environments = snapshot.get("environments") or []
    by_name = {str(item.get("name")): item for item in environments}
    if set(by_name) != set(CANONICAL_SOURCE_ENVIRONMENTS):
        blockers.append("environment_set_mismatch")
    for name in CANONICAL_SOURCE_ENVIRONMENTS:
        if name in by_name and not _environment_valid(by_name[name]):
            blockers.append(f"environment_policy_mismatch:{name}")

    if snapshot.get("codeowners_valid") is not True:
        blockers.append("codeowners_not_valid")
    if snapshot.get("required_check_observed") is not True:
        blockers.append("required_check_not_observed")
    return StageTwoEvaluation(not blockers, tuple(blockers))
