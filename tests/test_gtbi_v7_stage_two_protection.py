from __future__ import annotations

import json
from pathlib import Path

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from infra.gtbi_v7_readiness.g3a_governance import (
    CANONICAL_SOURCE_ENVIRONMENTS,
    LOCKED_DENY_ENVIRONMENT,
    REPOSITORY_OWNER_ID,
    source_environment_api_payload,
)
from infra.gtbi_v7_readiness.stage_two_protection import (
    GITHUB_ACTIONS_APP_ID,
    REQUIRED_CHECK_CONTEXT,
    branch_protection_api_payload,
    build_policy,
    evaluate_live_state,
)
from scripts.validate_gtbi_v7_stage_two_contract import validate

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config/gtbi/governance/stage_two_owner_controlled_protection.json"
WORKFLOW = ROOT / ".github/workflows/gtbi-v7-stage-two-required.yml"


def _environment(name: str) -> dict:
    expected = source_environment_api_payload(name)
    locked = name == LOCKED_DENY_ENVIRONMENT
    return {
        "name": name,
        "deployment_branch_policy": expected["deployment_branch_policy"],
        "reviewers": []
        if locked
        else [
            {
                "type": "User",
                "id": REPOSITORY_OWNER_ID,
                "login": "gomez5757",
            }
        ],
        "prevent_self_review": False,
        "custom_branch_policy_count": 0,
        "secret_count": 0,
    }


def _snapshot() -> dict:
    return {
        "branch_protection": {
            "required_status_checks": {
                "strict": True,
                "checks": [
                    {
                        "context": REQUIRED_CHECK_CONTEXT,
                        "app_id": GITHUB_ACTIONS_APP_ID,
                    }
                ],
            },
            "required_pull_request_reviews": {
                "required_approving_review_count": 0,
                "require_code_owner_reviews": False,
                "require_last_push_approval": False,
            },
            "enforce_admins": {"enabled": True},
            "required_conversation_resolution": {"enabled": True},
            "allow_force_pushes": {"enabled": False},
            "allow_deletions": {"enabled": False},
        },
        "environments": [_environment(name) for name in CANONICAL_SOURCE_ENVIRONMENTS],
        "codeowners_valid": True,
        "required_check_observed": True,
    }


def test_policy_is_canonical_and_digest_bound() -> None:
    policy = build_policy()
    assert policy["policy_digest"] == domain_digest(
        "GTBI_V7_OWNER_CONTROLLED_STAGE_TWO_POLICY_V1",
        policy,
        omit_top_level_fields=("policy_digest",),
    )
    checked = json.loads(POLICY.read_text(encoding="utf-8"))
    assert POLICY.read_bytes() == canonical_bytes(checked) + b"\n"
    assert checked == policy


def test_stage_two_is_owner_controlled_and_zero_cost() -> None:
    policy = build_policy()
    assert policy["external_reviewers_required"] is False
    assert policy["required_approving_review_count"] == 0
    assert policy["require_code_owner_reviews"] is False
    assert policy["incremental_net_spend_usd"] == 0
    assert policy["locked_access_enabled"] is False
    assert policy["scientific_processing_performed"] is False


def test_branch_payload_prevents_deadlock_and_destructive_pushes() -> None:
    payload = branch_protection_api_payload()
    assert payload["required_status_checks"] == {
        "strict": True,
        "checks": [{"context": REQUIRED_CHECK_CONTEXT, "app_id": GITHUB_ACTIONS_APP_ID}],
    }
    assert payload["required_pull_request_reviews"]["required_approving_review_count"] == 0
    assert payload["enforce_admins"] is True
    assert payload["allow_force_pushes"] is False
    assert payload["allow_deletions"] is False


def test_matching_live_state_is_ready() -> None:
    evaluation = evaluate_live_state(_snapshot())
    assert evaluation.ready is True
    assert evaluation.blockers == ()


def test_missing_required_check_fails_closed() -> None:
    snapshot = _snapshot()
    snapshot["branch_protection"]["required_status_checks"]["checks"] = []
    evaluation = evaluate_live_state(snapshot)
    assert evaluation.ready is False
    assert "required_status_checks_mismatch" in evaluation.blockers


def test_human_review_deadlock_is_rejected() -> None:
    snapshot = _snapshot()
    snapshot["branch_protection"]["required_pull_request_reviews"][
        "required_approving_review_count"
    ] = 1
    evaluation = evaluate_live_state(snapshot)
    assert "human_approval_count_not_owner_controlled" in evaluation.blockers


def test_locked_environment_cannot_gain_access() -> None:
    snapshot = _snapshot()
    locked = next(
        item for item in snapshot["environments"] if item["name"] == LOCKED_DENY_ENVIRONMENT
    )
    locked["reviewers"] = [{"type": "User", "id": REPOSITORY_OWNER_ID, "login": "gomez5757"}]
    evaluation = evaluate_live_state(snapshot)
    assert f"environment_policy_mismatch:{LOCKED_DENY_ENVIRONMENT}" in (evaluation.blockers)


def test_required_workflow_is_unconditional_for_pull_requests() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in text
    assert "paths:" not in text
    assert f"name: {REQUIRED_CHECK_CONTEXT}" in text
    assert "runs-on: ubuntu-24.04" in text
    assert "self-hosted" not in text
    assert "C:\\" not in text


def test_dependency_free_contract_validator_accepts_repository() -> None:
    report = validate()
    assert report["valid"] is True
    assert report["errors"] == []
