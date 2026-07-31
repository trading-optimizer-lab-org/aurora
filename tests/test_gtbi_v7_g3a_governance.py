"""Tests for the owner-controlled GTBI V7 minimum GitHub baseline."""

from __future__ import annotations

import json
from pathlib import Path

from infra.gtbi_v7_readiness.canonical import canonical_bytes, domain_digest
from infra.gtbi_v7_readiness.g3a_governance import (
    CANONICAL_SOURCE_ENVIRONMENTS,
    G3A_BASELINE_TASK_IDS,
    LOCKED_DENY_ENVIRONMENT,
    REPOSITORY_OWNER_ID,
    build_g3a_policy,
    evaluate_live_state,
    source_environment_api_payload,
)
from infra.readiness_state_controller.policy import validate_transition_manifest
from scripts.generate_gtbi_v7_g3a_baseline import (
    MANIFEST,
    POLICY,
    RECEIPT,
    build_live_receipt,
)
from scripts.generate_gtbi_v7_g3a_apply_reconciliation_receipt import (
    DESTINATION as G3A_RECONCILIATION,
    SOURCE as G3A_APPLY_SOURCE,
    build_receipt as build_g3a_apply_receipt,
    validate_application as validate_g3a_application,
)

ROOT = Path(__file__).resolve().parents[1]


def _environment(name: str) -> dict:
    payload = source_environment_api_payload(name)
    protection_rules = []
    if payload["reviewers"]:
        protection_rules.append(
            {
                "type": "required_reviewers",
                "prevent_self_review": False,
                "reviewers": [
                    {
                        "type": "User",
                        "reviewer": {
                            "type": "User",
                            "id": REPOSITORY_OWNER_ID,
                            "login": "gomez5757",
                        },
                    }
                ],
            }
        )
    return {
        "id": 1000 + CANONICAL_SOURCE_ENVIRONMENTS.index(name),
        "name": name,
        "protection_rules": protection_rules,
        "deployment_branch_policy": payload["deployment_branch_policy"],
    }


def _snapshot(*, installations: list[dict] | None = None) -> dict:
    environments = [_environment(name) for name in CANONICAL_SOURCE_ENVIRONMENTS]
    return {
        "repository": {
            "id": 1232647748,
            "default_branch": "main",
            "security_and_analysis": {
                "dependabot_security_updates": {"status": "enabled"},
                "secret_scanning": {"status": "enabled"},
                "secret_scanning_non_provider_patterns": {
                    "status": "enabled"
                },
                "secret_scanning_push_protection": {"status": "enabled"},
                "secret_scanning_validity_checks": {"status": "enabled"},
            },
        },
        "branch_protection": {
            "required_pull_request_reviews": {
                "required_approving_review_count": 0,
                "bypass_pull_request_allowances": {
                    "apps": [],
                    "teams": [],
                    "users": [],
                },
            },
            "required_status_checks": {
                "strict": True,
                "checks": [],
            },
            "enforce_admins": {"enabled": True},
            "allow_force_pushes": {"enabled": False},
            "allow_deletions": {"enabled": False},
            "required_conversation_resolution": {"enabled": True},
        },
        "workflow_permissions": {
            "default_workflow_permissions": "read",
            "can_approve_pull_request_reviews": False,
        },
        "code_scanning_default_setup": {
            "state": "configured",
            "languages": ["actions", "python"],
            "query_suite": "default",
        },
        "environments": environments,
        "environment_auxiliary_counts": {
            name: {
                "custom_branch_policy_count": 0,
                "secret_count": 0,
            }
            for name in CANONICAL_SOURCE_ENVIRONMENTS
        },
        "app_installations": installations or [],
    }


def _workflow_report() -> dict:
    return {
        "schema_version": "1",
        "valid": True,
        "workflow_count": 113,
        "workflows": [],
    }


def test_g3a_policy_is_canonical_and_digest_bound() -> None:
    policy = build_g3a_policy()
    assert policy["policy_digest"] == domain_digest(
        "GTBI_V7_G3A_MINIMUM_GOVERNANCE_POLICY_V1",
        policy,
        omit_top_level_fields=("policy_digest",),
    )
    assert policy["scientific_boundaries"] == {
        "locked_start": "2021-01-01",
        "locked_access_enabled": False,
        "scientific_processing_performed": False,
        "local_research_run_performed": False,
    }


def test_locked_environment_is_deny_all_and_has_no_credentials() -> None:
    payload = source_environment_api_payload(LOCKED_DENY_ENVIRONMENT)
    assert payload["reviewers"] == []
    assert payload["deployment_branch_policy"] == {
        "protected_branches": False,
        "custom_branch_policies": True,
    }
    expected = next(
        item
        for item in build_g3a_policy()["canonical_source_environments"]
        if item["name"] == LOCKED_DENY_ENVIRONMENT
    )
    assert expected["expected_custom_branch_policy_count"] == 0
    assert expected["credential_classes"] == []
    assert expected["locked_access_enabled"] is False


def test_baseline_tasks_pass_without_faking_source_app_tasks() -> None:
    evaluation = evaluate_live_state(
        _snapshot(),
        workflow_policy_valid=True,
    )
    assert {
        task_id: evaluation.task_completion[task_id]
        for task_id in G3A_BASELINE_TASK_IDS
    } == {task_id: True for task_id in G3A_BASELINE_TASK_IDS}
    assert evaluation.task_completion["PREV7-0204"] is False
    assert evaluation.task_completion["PREV7-0210"] is False
    assert evaluation.g3a_ready is False
    assert "source_github_app_installations_missing" in evaluation.blockers


def test_unrelated_live_installation_cannot_complete_source_app_tasks() -> None:
    snapshot = _snapshot(
        installations=[
            {
                "id": 9001,
                "app_id": 8001,
                "app_slug": "gtbi-test",
                "repository_selection": "selected",
                "suspended_at": None,
            }
        ]
    )
    evaluation = evaluate_live_state(
        snapshot,
        workflow_policy_valid=True,
    )
    assert evaluation.task_completion["PREV7-0204"] is False
    assert evaluation.task_completion["PREV7-0210"] is False
    assert evaluation.g3a_ready is False
    assert "source_github_app_contract_not_yet_verified" in evaluation.blockers


def test_missing_environment_keeps_installation_task_incomplete() -> None:
    snapshot = _snapshot(
        installations=[
            {
                "id": 9001,
                "app_id": 8001,
                "app_slug": "gtbi-test",
                "repository_selection": "selected",
                "suspended_at": None,
            }
        ]
    )
    snapshot["environments"] = snapshot["environments"][:-1]
    evaluation = evaluate_live_state(
        snapshot,
        workflow_policy_valid=True,
    )
    assert evaluation.task_completion["PREV7-0204"] is False
    assert evaluation.task_completion["PREV7-0210"] is False
    assert evaluation.g3a_ready is False


def test_environment_reviewer_policy_checks_self_review_setting() -> None:
    snapshot = _snapshot()
    snapshot["environments"][0]["protection_rules"][0][
        "prevent_self_review"
    ] = True
    evaluation = evaluate_live_state(
        snapshot,
        workflow_policy_valid=True,
    )
    assert evaluation.task_completion["PREV7-0210"] is False
    assert any(
        blocker.startswith(
            "canonical_source_environments_missing_or_invalid:"
        )
        for blocker in evaluation.blockers
    )


def test_live_receipt_keeps_locked_and_science_closed() -> None:
    receipt = build_live_receipt(
        _snapshot(),
        _workflow_report(),
        observed_at_utc="2026-07-30T22:30:00Z",
    )
    assert receipt["receipt_digest"] == domain_digest(
        "GTBI_V7_G3A_GITHUB_LIVE_RECEIPT_V1",
        receipt,
        omit_top_level_fields=("receipt_digest",),
    )
    assert receipt["evaluation"]["task_completion"]["PREV7-0204"] is False
    assert receipt["source_github_apps"]["installation_count"] == 0
    assert receipt["scientific_boundaries"] == {
        "locked_start": "2021-01-01",
        "locked_data_accessed": False,
        "scientific_processing_performed": False,
        "local_research_run_performed": False,
    }


def test_checked_g3a_policy_matches_generator() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert POLICY.read_bytes() == canonical_bytes(policy) + b"\n"
    assert policy == build_g3a_policy()


def test_checked_live_receipt_and_transition_are_consistent() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert RECEIPT.read_bytes() == canonical_bytes(receipt) + b"\n"
    assert MANIFEST.read_bytes() == canonical_bytes(manifest) + b"\n"
    assert receipt["evaluation"]["g3a_ready"] is False
    assert receipt["source_github_apps"]["status"] == (
        "pending_provider_web_authorization"
    )
    assert receipt["scientific_boundaries"]["locked_data_accessed"] is False
    validate_transition_manifest(manifest)
    assert [item["task_id"] for item in manifest["task_actions"]] == list(
        G3A_BASELINE_TASK_IDS
    )
    assert manifest["gate_actions"] == []


def test_g3a_workflows_use_github_hosted_runners_only() -> None:
    workflows = (
        ROOT / ".github/workflows/gtbi-v7-master-plan-quality.yml",
        ROOT / ".github/workflows/gtbi-v7-readiness-state-controller.yml",
        ROOT / ".github/workflows/gtbi-v7-inventory.yml",
    )
    for path in workflows:
        text = path.read_text(encoding="utf-8")
        assert "self-hosted" not in text
        assert "runs-on: ubuntu-" in text


def test_g3a_apply_receipt_is_canonical_and_reconciled() -> None:
    source = json.loads(G3A_APPLY_SOURCE.read_text(encoding="utf-8"))
    assert G3A_APPLY_SOURCE.read_bytes() == canonical_bytes(source) + b"\n"
    assert source["receipt_digest"] == domain_digest(
        "GTBI_V7_STATE_CONTROLLER_RECEIPT_V1",
        source,
        omit_top_level_fields=("receipt_digest",),
    )

    validation = validate_g3a_application()
    assert validation["append_only_g3a_history_preserved"] is True
    assert validation["exact_g3a_projection"] is True

    expected = build_g3a_apply_receipt()
    assert G3A_RECONCILIATION.read_bytes() == canonical_bytes(expected) + b"\n"
    assert expected["post_apply_state"] == {
        "counts": {
            "attempt_event_count": 78,
            "gate_count": 15,
            "gate_event_count": 18,
            "task_count": 110,
            "task_event_count": 187,
        },
        "task_status_counts": {
            "blocked": 90,
            "cancelled": 1,
            "done": 19,
        },
        "g3a_gate_status": "red",
        "g3a_blocking_reason": "required_tasks_not_done",
        "remaining_g3a_tasks": ["PREV7-0204", "PREV7-0210"],
    }
    assert expected["verified_properties"] == {
        "append_only_g3a_history_preserved": True,
        "arbitrary_command_execution_supported": False,
        "exact_g3a_projection": True,
        "locked_data_accessed": False,
        "owner_controlled": True,
        "scientific_work_performed": False,
        "state_merged": True,
    }
