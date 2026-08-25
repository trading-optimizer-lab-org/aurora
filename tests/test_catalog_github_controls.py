from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import re
import subprocess
import sys
import importlib

import jsonschema
import pytest

from scripts import audit_catalog_github_controls as github_audit_runner
from aurora.infra.sp500_megarun.catalog_execution_protocol import PROTOCOL_COMMON_PATHS
from aurora.infra.sp500_megarun.catalog_github_controls import (
    AUDITOR_SECRET_CONSUMER,
    CatalogGithubAuditorV1,
    CatalogGithubControlsV1,
    audit_catalog_github_controls,
    bootstrap_controls_prepared,
    build_github_controls_mutation_plan,
    github_controls_state_sha256,
    load_catalog_github_auditor,
    load_catalog_github_controls,
)
from scripts.audit_catalog_github_controls import (
    AppReadOnlyClient,
    _active_artifact_inventory,
    _auditor_installation_token_request,
    _auditor_provider_permissions,
    _billing_actions_storage_evidence,
    _billing_usage_endpoint,
    _campaign_storage_projection,
    _paginate_list_rows,
    _paginate_list_rows_stable,
    _paginate_object_rows,
    _paginate_object_rows_stable,
    _package_inventory_endpoint,
    _reported_shared_storage_evidence,
    _retry_transient_snapshot_collection,
)
from scripts.apply_catalog_github_controls import apply_cache_retention_transaction


ROOT = Path(__file__).resolve().parents[1]
CONTROLS = ROOT / "config/catalog_github_controls_v1.json"
AUDITOR = ROOT / "config/catalog_github_auditor_v1.json"
NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
HEAVY_PATH = ".github/workflows/synthetic-catalog-engine.yml"


def load_desired_controls() -> CatalogGithubControlsV1:
    return load_catalog_github_controls(CONTROLS)


def load_desired_auditor() -> CatalogGithubAuditorV1:
    return load_catalog_github_auditor(AUDITOR)


def _budget_rows(desired: CatalogGithubControlsV1) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, budget in enumerate(desired.billing.required_zero_budgets, start=1):
        row = budget.model_dump(mode="json")
        row["id"] = index
        rows.append(row)
    return rows


def _safe_heavy_workflow() -> dict[str, object]:
    return {
        "name": "Synthetic sealed heavy engine",
        "on": {"workflow_call": {"inputs": {}}},
        "permissions": {"contents": "read"},
        "jobs": {
            "engine": {
                "uses": "./.github/workflows/catalog-optimized-worker.yml",
                "with": {"sealed_request_sha256": "${{ inputs.request_sha256 }}"},
            }
        },
    }


def _safe_issue_writer_workflow(job_ids: tuple[str, ...]) -> dict[str, object]:
    return {
        "name": "Synthetic bounded issue writers",
        "on": {"workflow_call": {"inputs": {}}},
        "permissions": {"contents": "read"},
        "jobs": {
            job_id: {
                "runs-on": "ubuntu-24.04",
                "permissions": {"issues": "write"},
                "steps": [],
            }
            for job_id in job_ids
        },
    }


def protected_snapshots() -> dict[str, object]:
    desired = load_desired_controls()
    auditor = load_desired_auditor()
    budgets = _budget_rows(desired)
    snapshot: dict[str, object] = {
        "observer_context": "bootstrap_local",
        "runtime_provenance": {
            "caller_workflow": ".github/workflows/catalog-run-controller.yml",
            "caller_job": "live_controls_audit_before_reserve",
            "purpose": "admission",
            "audit_context_sha256": "d" * 64,
            "protected_commit_sha": "a" * 40,
            "verified": True,
        },
        "observed_at": NOW.isoformat().replace("+00:00", "Z"),
        "github_api_observed_at": NOW.isoformat().replace("+00:00", "Z"),
        "repository": {
            "id": 123456,
            "node_id": "R_kgDOAurora",
            "full_name": "trading-optimizer-lab-org/aurora",
            "owner": {
                "login": "trading-optimizer-lab-org",
                "type": "Organization",
            },
            "visibility": "public",
            "private": False,
            "default_branch": "main",
            "default_branch_sha": "a" * 40,
        },
        "branch_protection": desired.branch_protection.model_dump(mode="json"),
        "actions_permissions": desired.actions.model_dump(mode="json"),
        "environment": desired.environment.model_dump(mode="json"),
        "labels": [desired.issue_labels.terminal.model_dump(mode="json")],
        "budgets": budgets,
        "budget_details": deepcopy(budgets),
        "cache_settings": {
            "storage_limit_gb": 10,
            "enterprise_retention_days": desired.billing.repository_cache_retention_days,
            "organization_retention_days": desired.billing.repository_cache_retention_days,
            "repository_retention_days": desired.billing.repository_cache_retention_days,
        },
        "storage": {
            "telemetry_complete": True,
            "artifacts_pagination_complete": True,
            "packages_pagination_complete": True,
            "caches_pagination_complete": True,
            "writer_inventory_complete": True,
            "shared_allowance_bytes": 53_687_091_200,
            "reported_shared_use_bytes": 10_000_000_000,
            "artifact_inventory_bytes": 4_000_000_000,
            "package_inventory_bytes": 5_000_000_000,
            "unreflected_upload_bytes": 1_000_000_000,
            "reported_cache_use_bytes": 1_000_000_000,
            "cache_inventory_bytes": 1_100_000_000,
            "pending_cache_bytes": 100_000_000,
            "projected_campaign_artifact_bytes": 2_000_000_000,
            "projected_campaign_cache_bytes": 500_000_000,
            "paid_runner_minutes": 0,
            "estimated_paid_actions_cost": 0,
            "billing_snapshot_complete": True,
        },
        "workflow_documents": {
            HEAVY_PATH: _safe_heavy_workflow(),
            ".github/workflows/catalog-run-controller.yml": _safe_issue_writer_workflow(
                (
                    "issue_tamper_guard",
                    "reserve",
                    "report_nonexecuting_decision",
                    "record_running",
                    "record_nonterminal_wait",
                    "finalize",
                )
            ),
            ".github/workflows/catalog-request-reconciler.yml": _safe_issue_writer_workflow(
                ("call_controller",)
            ),
            ".github/workflows/catalog-ledger-guard.yml": _safe_issue_writer_workflow(
                ("record_tamper_incident",)
            ),
            ".github/workflows/catalog-run-watchdog.yml": _safe_issue_writer_workflow(
                ("call_controller",)
            ),
        },
        "workflow_source_sha256s": {
            HEAVY_PATH: "b" * 64,
            ".github/workflows/catalog-run-controller.yml": "b" * 64,
            ".github/workflows/catalog-request-reconciler.yml": "b" * 64,
            ".github/workflows/catalog-ledger-guard.yml": "b" * 64,
            ".github/workflows/catalog-run-watchdog.yml": "b" * 64,
        },
        "active_runs": [],
        "runs_pagination_complete": True,
        "jobs_pagination_complete": True,
        "request_actor_permissions": {
            "login": "aurora-catalog-requester[bot]",
            "kind": "GitHubApp",
            "repository_administration": "none",
            "repository_actions": "none",
            "repository_contents": "none",
            "repository_issues": "write",
        },
        "local_agent": {
            "actor": "gomez5757",
            "has_admin": False,
            "can_read_requester_credential": False,
            "can_read_auditor_credential": False,
            "broker_acl_verified": True,
            "process_environment_verified": True,
        },
        "auditor_installation": None,
        "auditor_secret_consumer_workflows": [
            AUDITOR_SECRET_CONSUMER
        ],
        "auditor_runtime_callers": [
            {
                "caller_workflow": ".github/workflows/catalog-run-controller.yml",
                "caller_job": "live_controls_audit_before_reserve",
                "purpose": "admission",
            },
            {
                "caller_workflow": ".github/workflows/catalog-run-controller.yml",
                "caller_job": "live_controls_audit_before_terminal",
                "purpose": "terminal",
            },
            {
                "caller_workflow": ".github/workflows/catalog-artifact-keeper.yml",
                "caller_job": "live_controls_audit_before_maintenance",
                "purpose": "maintenance",
            },
            {
                "caller_workflow": (
                    ".github/workflows/catalog-live-controls-qualification.yml"
                ),
                "caller_job": "qualify_live_admission_controls",
                "purpose": "admission",
            },
            {
                "caller_workflow": (
                    ".github/workflows/catalog-live-controls-qualification.yml"
                ),
                "caller_job": "qualify_live_terminal_controls",
                "purpose": "terminal",
            },
        ],
        "authority_anchor_verified": True,
        "pagination_complete": True,
        "api_version_verified": True,
    }
    return {"desired": desired, "auditor": auditor, "snapshots": snapshot}


def mutated_protection_snapshots(mutation: str) -> dict[str, object]:
    inputs = protected_snapshots()
    snapshot = inputs["snapshots"]
    assert isinstance(snapshot, dict)
    branch = snapshot["branch_protection"]
    actions = snapshot["actions_permissions"]
    assert isinstance(branch, dict) and isinstance(actions, dict)
    if mutation == "admins_not_enforced":
        branch["enforce_admins"] = False
    elif mutation == "force_push_allowed":
        branch["allow_force_pushes"] = True
    elif mutation == "delete_allowed":
        branch["allow_deletions"] = True
    elif mutation == "pull_request_not_required":
        branch["require_pull_request"] = False
    elif mutation == "strict_status_checks_off":
        branch["strict_status_checks"] = False
    elif mutation == "conversation_resolution_off":
        branch["required_conversation_resolution"] = False
    elif mutation == "workflow_dispatch_present":
        workflows = snapshot["workflow_documents"]
        assert isinstance(workflows, dict)
        workflows[HEAVY_PATH]["on"]["workflow_dispatch"] = {}
    elif mutation == "actions_default_write":
        actions["default_workflow_permissions"] = "write"
    elif mutation == "actions_can_approve":
        actions["can_approve_pull_request_reviews"] = True
    elif mutation == "repository_private":
        snapshot["repository"]["visibility"] = "private"
        snapshot["repository"]["private"] = True
    elif mutation == "environment_missing":
        snapshot["environment"] = None
    elif mutation == "environment_any_branch":
        snapshot["environment"]["protected_branches_only"] = False
    elif mutation == "terminal_label_missing":
        snapshot["labels"] = []
    elif mutation == "terminal_label_drift":
        snapshot["labels"][0]["color"] = "ffffff"
    elif mutation == "paid_runner_allowed":
        actions["larger_runners_allowed"] = True
    elif mutation == "zero_actions_budget_missing":
        snapshot["budgets"] = [
            row for row in snapshot["budgets"] if row["budget_product_sku"] != "actions"
        ]
    elif mutation == "zero_actions_storage_budget_missing":
        snapshot["budgets"] = [
            row
            for row in snapshot["budgets"]
            if row["budget_product_sku"] != "actions_storage"
        ]
    elif mutation == "zero_cache_storage_budget_missing":
        snapshot["budgets"] = [
            row
            for row in snapshot["budgets"]
            if row["budget_product_sku"] != "actions_cache_storage"
        ]
    elif mutation == "budget_wrong_repository":
        snapshot["budgets"][0]["budget_entity_name"] = "aurora-copy"
    elif mutation == "actions_budget_does_not_stop":
        snapshot["budgets"][0]["prevent_further_usage"] = False
    elif mutation == "cache_limit_above_10_gb":
        snapshot["cache_settings"]["storage_limit_gb"] = 20
    elif mutation == "cache_retention_below_90_days":
        snapshot["cache_settings"]["repository_retention_days"] = 89
    elif mutation == "request_actor_admin":
        snapshot["request_actor_permissions"]["repository_administration"] = "write"
    elif mutation == "local_agent_admin":
        snapshot["local_agent"]["has_admin"] = True
    elif mutation == "local_agent_requester_key":
        snapshot["local_agent"]["can_read_requester_credential"] = True
    elif mutation == "local_agent_auditor_key":
        snapshot["local_agent"]["can_read_auditor_credential"] = True
    else:
        raise AssertionError(mutation)
    return inputs


def test_exact_protected_state_passes() -> None:
    receipt = audit_catalog_github_controls(**protected_snapshots())
    assert receipt.status == "ready"
    assert receipt.failed_controls == ()
    assert len(receipt.receipt_sha256) == 64
    assert receipt.observer_context == "bootstrap_local"
    assert receipt.audit_use_context == "controller_admission"


def test_auditor_secret_consumer_is_the_reusable_workflow_without_composite() -> None:
    expected = ".github/workflows/catalog-live-controls-audit.yml"
    composite = ".github/actions/catalog-live-controls-audit/action.yml"
    schema_text = (ROOT / "schemas/catalog_github_controls_v1.schema.json").read_text(
        "utf-8"
    )
    schema = json.loads(schema_text)

    assert AUDITOR_SECRET_CONSUMER == expected
    assert load_desired_controls().auditor.only_token_consumer_workflow == expected
    assert schema["$defs"]["auditor"]["properties"][
        "only_token_consumer_workflow"
    ]["const"] == expected
    assert composite not in CONTROLS.read_text("utf-8")
    assert composite not in schema_text
    assert composite not in PROTOCOL_COMMON_PATHS
    assert expected in PROTOCOL_COMMON_PATHS


def test_auditor_runtime_topology_requires_exactly_five_callers() -> None:
    inputs = protected_snapshots()
    snapshots = inputs["snapshots"]
    assert isinstance(snapshots, dict)
    callers = snapshots["auditor_runtime_callers"]
    assert isinstance(callers, list)
    callers.pop()

    receipt = audit_catalog_github_controls(**inputs)

    assert receipt.status == "blocked"
    assert "CATALOG_AUDITOR_TOPOLOGY_INVALID" in receipt.failed_controls


def test_auditor_runtime_topology_rejects_an_extra_caller() -> None:
    inputs = protected_snapshots()
    snapshots = inputs["snapshots"]
    assert isinstance(snapshots, dict)
    callers = snapshots["auditor_runtime_callers"]
    assert isinstance(callers, list)
    callers.append(
        {
            "caller_workflow": ".github/workflows/catalog-run-controller.yml",
            "caller_job": "unexpected_auditor_call",
            "purpose": "admission",
        }
    )

    receipt = audit_catalog_github_controls(**inputs)

    assert receipt.status == "blocked"
    assert "CATALOG_AUDITOR_TOPOLOGY_INVALID" in receipt.failed_controls


def test_missing_permitted_writer_blocks_closed_topology() -> None:
    inputs = protected_snapshots()
    snapshots = inputs["snapshots"]
    assert isinstance(snapshots, dict)
    workflows = snapshots["workflow_documents"]
    assert isinstance(workflows, dict)
    controller = workflows[".github/workflows/catalog-run-controller.yml"]
    assert isinstance(controller, dict)
    jobs = controller["jobs"]
    assert isinstance(jobs, dict)
    del jobs["finalize"]

    receipt = audit_catalog_github_controls(**inputs)

    assert receipt.status == "blocked"
    assert "ISSUES_WRITE_TOPOLOGY_EXACT" in receipt.failed_controls


def test_controller_writer_allowlist_has_exactly_six_schema_items() -> None:
    payload = json.loads(CONTROLS.read_text("utf-8"))
    schema = json.loads(
        (ROOT / "schemas/catalog_github_controls_v1.schema.json").read_text("utf-8")
    )
    expected = [
        "issue_tamper_guard",
        "reserve",
        "report_nonexecuting_decision",
        "record_running",
        "record_nonterminal_wait",
        "finalize",
    ]
    observed = payload["entrypoints"]["issues_write_job_allowlist"][
        ".github/workflows/catalog-run-controller.yml"
    ]
    schema_node = schema["$defs"]["issues_write_job_allowlist"]["properties"][
        ".github/workflows/catalog-run-controller.yml"
    ]
    assert observed == expected
    assert schema_node["minItems"] == 6
    assert schema_node["maxItems"] == 6


def test_cache_retention_matches_the_90_day_hierarchy_minimum() -> None:
    desired = load_desired_controls()
    assert desired.billing.repository_cache_retention_days == 90


@pytest.mark.parametrize(
    "mutation,control",
    [
        ("admins_not_enforced", "MAIN_ADMINS_ENFORCED"),
        ("force_push_allowed", "MAIN_FORCE_PUSH_FORBIDDEN"),
        ("delete_allowed", "MAIN_DELETE_FORBIDDEN"),
        ("pull_request_not_required", "MAIN_PULL_REQUEST_REQUIRED"),
        ("strict_status_checks_off", "MAIN_STRICT_STATUS_CHECKS_REQUIRED"),
        ("conversation_resolution_off", "MAIN_CONVERSATIONS_MUST_RESOLVE"),
        ("workflow_dispatch_present", "HEAVY_DIRECT_DISPATCH_FORBIDDEN"),
        ("actions_default_write", "DEFAULT_TOKEN_READ_ONLY"),
        ("actions_can_approve", "ACTIONS_PR_APPROVAL_FORBIDDEN"),
        ("repository_private", "PUBLIC_REPOSITORY_REQUIRED"),
        ("environment_missing", "CATALOG_ENVIRONMENT_REQUIRED"),
        ("environment_any_branch", "CATALOG_ENVIRONMENT_MAIN_ONLY"),
        ("terminal_label_missing", "CATALOG_TERMINAL_LABEL_REQUIRED"),
        ("terminal_label_drift", "CATALOG_TERMINAL_LABEL_EXACT"),
        ("paid_runner_allowed", "PAID_RUNNER_FORBIDDEN"),
        ("zero_actions_budget_missing", "ZERO_ACTIONS_SPEND_BUDGET_REQUIRED"),
        (
            "zero_actions_storage_budget_missing",
            "ZERO_ACTIONS_STORAGE_BUDGET_REQUIRED",
        ),
        (
            "zero_cache_storage_budget_missing",
            "ZERO_CACHE_STORAGE_BUDGET_REQUIRED",
        ),
        ("budget_wrong_repository", "ZERO_BUDGET_REPOSITORY_SCOPE_EXACT"),
        ("actions_budget_does_not_stop", "ZERO_ACTIONS_SPEND_STOP_REQUIRED"),
        ("cache_limit_above_10_gb", "FREE_CACHE_STORAGE_LIMIT_REQUIRED"),
        ("cache_retention_below_90_days", "CACHE_RETENTION_POLICY_REQUIRED"),
        ("request_actor_admin", "REQUEST_ACTOR_NON_ADMIN"),
        ("local_agent_admin", "AGENT_ADMIN_CREDENTIAL_EXPOSED"),
        ("local_agent_requester_key", "AGENT_REQUESTER_CREDENTIAL_EXPOSED"),
        ("local_agent_auditor_key", "AGENT_AUDITOR_CREDENTIAL_EXPOSED"),
    ],
)
def test_every_control_drift_blocks(mutation: str, control: str) -> None:
    receipt = audit_catalog_github_controls(
        **mutated_protection_snapshots(mutation)
    )
    assert receipt.status == "blocked"
    assert control in receipt.failed_controls


@pytest.mark.parametrize("entity", ["aurora", "trading-optimizer-lab-org/aurora"])
def test_documented_budget_repository_forms_are_canonicalized(entity: str) -> None:
    inputs = protected_snapshots()
    for collection in ("budgets", "budget_details"):
        for row in inputs["snapshots"][collection]:
            row["budget_entity_name"] = entity
    assert audit_catalog_github_controls(**inputs).status == "ready"


def test_similarly_named_budget_repository_is_rejected() -> None:
    inputs = protected_snapshots()
    for row in inputs["snapshots"]["budgets"]:
        row["budget_entity_name"] = "trading-optimizer-lab-org/aurora-copy"
    receipt = audit_catalog_github_controls(**inputs)
    assert "ZERO_BUDGET_REPOSITORY_SCOPE_EXACT" in receipt.failed_controls


def test_active_heavy_run_inventory_is_complete_and_authority_bound() -> None:
    inputs = protected_snapshots()
    snapshot = inputs["snapshots"]
    snapshot["active_runs"] = [
        {
            "run_id": 1,
            "workflow_path": HEAVY_PATH,
            "status": "in_progress",
            "authority_bound": True,
            "protected_commit_matches": True,
            "sealed_identifiers_match": True,
            "writer_provenance_verified": True,
            "current_engine_owner": True,
        },
        {
            "run_id": 2,
            "workflow_path": HEAVY_PATH,
            "status": "completed",
            "authority_bound": False,
            "protected_commit_matches": False,
            "sealed_identifiers_match": False,
            "writer_provenance_verified": False,
            "current_engine_owner": False,
        },
    ]
    receipt = audit_catalog_github_controls(**inputs)
    assert receipt.status == "ready"
    assert receipt.unmanaged_active_heavy_run_ids == ()

    snapshot["active_runs"].append(
        {
            "run_id": 101,
            "workflow_path": HEAVY_PATH,
            "status": "queued",
            "authority_bound": False,
            "protected_commit_matches": True,
            "sealed_identifiers_match": False,
            "writer_provenance_verified": False,
            "current_engine_owner": False,
        }
    )
    blocked = audit_catalog_github_controls(**inputs)
    assert "CATALOG_UNMANAGED_HEAVY_RUN_ACTIVE" in blocked.failed_controls
    assert blocked.unmanaged_active_heavy_run_ids == (101,)


def test_single_member_repository_policy_does_not_require_second_reviewer() -> None:
    protection = load_desired_controls().branch_protection
    assert protection.require_pull_request is True
    assert protection.required_approving_review_count == 0
    assert protection.require_code_owner_reviews is False
    assert protection.require_last_push_approval is False
    assert protection.strict_status_checks is True
    assert protection.required_status_checks == (
        "GTBI V7 stage-two required",
        "catalog-controller-policy",
    )


def test_enterprise_billing_control_plane_matches_repository_owner() -> None:
    desired = load_desired_controls()
    assert desired.billing.budget_control_plane.scope == "enterprise"
    assert desired.billing.budget_control_plane.enterprise == "trading-optimizer-lab"
    assert desired.billing.budget_control_plane.organization == "trading-optimizer-lab-org"
    assert desired.billing.included_shared_storage_bytes == 50 * 1024**3


def test_auditor_app_is_read_only() -> None:
    desired = load_desired_auditor()
    assert desired.required_repository_permissions == {
        "actions": "read",
        "administration": "read",
        "contents": "read",
        "environments": "read",
        "issues": "read",
        "metadata": "read",
        "packages": "read",
        "variables": "read",
    }
    assert desired.required_organization_permissions == {"administration": "read"}
    assert desired.required_enterprise_permissions == {"enterprise_billing": "read"}
    assert desired.enterprise_billing_token_environment_secret == (
        "AURORA_CATALOG_ENTERPRISE_BILLING_TOKEN"
    )
    assert desired.enterprise_cache_verifier_token_environment_secret == (
        "AURORA_CATALOG_ENTERPRISE_CACHE_VERIFIER_TOKEN"
    )
    assert desired.required_enterprise_billing_token_scopes == (
        "manage_billing:enterprise",
    )
    assert desired.required_enterprise_cache_verifier_token_scopes == (
        "admin:enterprise",
    )
    assert set(
        (
            desired.private_key_environment_secret,
            desired.enterprise_billing_token_environment_secret,
            desired.enterprise_cache_verifier_token_environment_secret,
            desired.package_inventory_token_environment_secret,
        )
    ) == {
        "AURORA_CATALOG_AUDITOR_PRIVATE_KEY",
        "AURORA_CATALOG_ENTERPRISE_BILLING_TOKEN",
        "AURORA_CATALOG_ENTERPRISE_CACHE_VERIFIER_TOKEN",
        "AURORA_CATALOG_PACKAGE_INVENTORY_TOKEN",
    }
    assert desired.package_inventory_token_environment_secret == (
        "AURORA_CATALOG_PACKAGE_INVENTORY_TOKEN"
    )
    assert desired.required_package_inventory_token_scopes == ("read:packages",)
    assert not any(value == "write" for value in desired.required_repository_permissions.values())


@pytest.mark.parametrize(
    ("scope_field", "wrong_scope"),
    [
        ("required_enterprise_billing_token_scopes", ["admin:enterprise"]),
        (
            "required_enterprise_cache_verifier_token_scopes",
            ["manage_billing:enterprise"],
        ),
    ],
)
def test_auditor_rejects_cross_assigned_enterprise_scopes(
    scope_field: str, wrong_scope: list[str]
) -> None:
    payload = json.loads(AUDITOR.read_text("utf-8"))
    payload[scope_field] = wrong_scope
    schema = json.loads(
        (ROOT / "schemas/catalog_github_auditor_v1.schema.json").read_text("utf-8")
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)
    with pytest.raises(ValueError, match="scope contract must be exact"):
        CatalogGithubAuditorV1.model_validate(payload)


def test_schemas_are_closed_and_validate_checked_contracts() -> None:
    for config_name, schema_name in (
        ("catalog_github_controls_v1.json", "catalog_github_controls_v1.schema.json"),
        ("catalog_github_auditor_v1.json", "catalog_github_auditor_v1.schema.json"),
    ):
        payload = json.loads((ROOT / "config" / config_name).read_text("utf-8"))
        schema = json.loads((ROOT / "schemas" / schema_name).read_text("utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(payload, schema)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**payload, "unsafe": True}, schema)
        for node in _object_schema_nodes(schema):
            assert node.get("additionalProperties") is False


def _object_schema_nodes(value: object) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    if isinstance(value, dict):
        if value.get("type") == "object":
            found.append(value)
        for child in value.values():
            found.extend(_object_schema_nodes(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_object_schema_nodes(child))
    return found


def _lock_packages(path: Path) -> dict[str, tuple[str, frozenset[str]]]:
    text = path.read_text("utf-8")
    starts = list(re.finditer(r"(?m)^([a-z0-9][a-z0-9._-]*)==([^ \\\r\n]+)", text))
    result: dict[str, tuple[str, frozenset[str]]] = {}
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        block = text[match.start() : end]
        hashes = frozenset(re.findall(r"--hash=sha256:([0-9a-f]{64})", block))
        assert hashes, match.group(1)
        result[match.group(1)] = (match.group(2), hashes)
    assert result
    assert not re.search(r"(?im)(?:^|\s)(?:-e |--editable|https?://|git\+|--extra-index)", text)
    return result


def test_production_and_test_locks_are_hash_pinned_and_consistent() -> None:
    production = _lock_packages(ROOT / "requirements/catalog-controller-linux-py311.lock")
    testing = _lock_packages(ROOT / "requirements/catalog-controller-test-linux-py311.lock")
    assert production.items() <= testing.items()
    assert "pytest" not in production
    assert "pytest" in testing


def test_apply_plan_is_deterministic_and_dry_run_data_only() -> None:
    inputs = mutated_protection_snapshots("admins_not_enforced")
    receipt = audit_catalog_github_controls(**inputs)
    first = build_github_controls_mutation_plan(
        desired=inputs["desired"],
        receipt=receipt,
    )
    second = build_github_controls_mutation_plan(
        desired=inputs["desired"],
        receipt=receipt,
    )
    assert first == second
    assert first.current_receipt_sha256 == receipt.receipt_sha256
    assert first.mutations
    assert all(mutation.method in {"PUT", "POST", "PATCH"} for mutation in first.mutations)


def test_controls_state_sha_ignores_observation_envelope_but_detects_drift() -> None:
    inputs = mutated_protection_snapshots("admins_not_enforced")
    snapshot = inputs["snapshots"]
    assert isinstance(snapshot, dict)
    storage = snapshot["storage"]
    assert isinstance(storage, dict)
    storage["billing_storage_period_average_bytes"] = 1_000
    storage["billing_storage_period_elapsed_seconds"] = 10
    first = audit_catalog_github_controls(**inputs)

    shifted = deepcopy(inputs)
    shifted_snapshot = shifted["snapshots"]
    assert isinstance(shifted_snapshot, dict)
    later = NOW + timedelta(seconds=30)
    shifted_snapshot["observed_at"] = later.isoformat().replace("+00:00", "Z")
    shifted_snapshot["github_api_observed_at"] = later.isoformat().replace(
        "+00:00", "Z"
    )
    shifted_storage = shifted_snapshot["storage"]
    assert isinstance(shifted_storage, dict)
    shifted_storage["billing_storage_period_average_bytes"] = 900
    shifted_storage["billing_storage_period_elapsed_seconds"] = 20
    second = audit_catalog_github_controls(**shifted)

    assert first.receipt_sha256 != second.receipt_sha256
    assert github_controls_state_sha256(first) == github_controls_state_sha256(
        second
    )

    drifted = deepcopy(shifted)
    drifted_snapshot = drifted["snapshots"]
    assert isinstance(drifted_snapshot, dict)
    cache_settings = drifted_snapshot["cache_settings"]
    assert isinstance(cache_settings, dict)
    cache_settings["repository_retention_days"] = 89
    changed = audit_catalog_github_controls(**drifted)
    assert github_controls_state_sha256(first) != github_controls_state_sha256(
        changed
    )


def test_budget_drift_blocks_without_creating_or_changing_budgets() -> None:
    inputs = mutated_protection_snapshots("zero_actions_budget_missing")
    receipt = audit_catalog_github_controls(**inputs)
    plan = build_github_controls_mutation_plan(
        desired=inputs["desired"],
        receipt=receipt,
    )
    assert receipt.status == "blocked"
    assert not any(
        mutation.method == "POST" or "/settings/billing/budgets" in mutation.endpoint
        for mutation in plan.mutations
    )


def test_auditor_routes_enterprise_billing_to_a_separate_token() -> None:
    client = AppReadOnlyClient(
        api_version="2026-03-10",
        repository="trading-optimizer-lab-org/aurora",
        auditor=load_desired_auditor(),
    )
    client._repository_token = "repository-token"
    client._enterprise_billing_token = "enterprise-billing-token"
    client._enterprise_cache_verifier_token = "enterprise-cache-verifier-token"
    client._package_token = "package-token"
    assert client._token_for_endpoint("/repos/trading-optimizer-lab-org/aurora") == (
        "repository-token"
    )
    assert client._token_for_endpoint(
        "/enterprises/trading-optimizer-lab/settings/billing/budgets"
    ) == "enterprise-billing-token"
    assert client._token_for_endpoint(
        "/enterprises/trading-optimizer-lab/actions/cache/retention-limit"
    ) == "enterprise-cache-verifier-token"
    assert client._token_for_endpoint(
        "/organizations/287229438/packages?package_type=container"
    ) == "package-token"
    assert client._token_for_endpoint(
        "/orgs/trading-optimizer-lab-org/packages?package_type=npm"
    ) == "package-token"
    assert client._token_for_endpoint(
        "/organizations/287229438/packages?package_type=nuget&per_page=100&page=2"
    ) == "package-token"
    with pytest.raises(ValueError, match="CATALOG_AUDITOR_ENDPOINT_INVALID"):
        client._token_for_endpoint(
            "/organizations/287229438/packages?package_type=container&per_page=50"
        )
    with pytest.raises(ValueError, match="CATALOG_AUDITOR_ENDPOINT_INVALID"):
        client._token_for_endpoint("/enterprises/other/settings/billing/budgets")
    for endpoint in (
        "/enterprises/trading-optimizer-lab/actions/cache/retention-limit/",
        "/enterprises/trading-optimizer-lab/actions/cache/retention-limit?x=1",
        "/enterprises/trading-optimizer-lab/actions/runners",
        "/enterprises/trading-optimizer-lab/settings/secret",
    ):
        with pytest.raises(ValueError, match="CATALOG_AUDITOR_ENDPOINT_INVALID"):
            client._token_for_endpoint(endpoint)


def test_auditor_clears_both_enterprise_tokens_on_exit() -> None:
    client = AppReadOnlyClient(
        api_version="2026-03-10",
        repository="trading-optimizer-lab-org/aurora",
        auditor=load_desired_auditor(),
    )
    client._enterprise_billing_token = "enterprise-billing-token"
    client._enterprise_cache_verifier_token = "enterprise-cache-verifier-token"
    client.__exit__()
    assert client._enterprise_billing_token is None
    assert client._enterprise_cache_verifier_token is None


def test_auditor_provider_permissions_match_the_created_github_app() -> None:
    assert _auditor_provider_permissions(load_desired_auditor()) == {
        "actions": "read",
        "actions_variables": "read",
        "administration": "read",
        "contents": "read",
        "environments": "read",
        "issues": "read",
        "metadata": "read",
        "organization_administration": "read",
        "packages": "read",
    }


def test_auditor_token_keeps_org_inventory_without_expanding_installation() -> None:
    request = _auditor_installation_token_request(load_desired_auditor())
    assert set(request) == {"permissions"}
    assert request["permissions"] == _auditor_provider_permissions(
        load_desired_auditor()
    )


def test_live_snapshot_retries_only_bounded_transient_pagination_drift() -> None:
    attempts = 0
    sleeps: list[float] = []

    def collect() -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ValueError("CATALOG_GITHUB_PAGINATION_UNSTABLE")
        return {"stable": True}

    assert _retry_transient_snapshot_collection(
        collect, sleep=sleeps.append
    ) == {"stable": True}
    assert attempts == 3
    assert sleeps == [2.0, 2.0]


def test_live_snapshot_does_not_retry_non_transient_errors() -> None:
    attempts = 0

    def collect() -> dict[str, object]:
        nonlocal attempts
        attempts += 1
        raise ValueError("CATALOG_AUDITOR_PERMISSIONS_INVALID")

    with pytest.raises(ValueError, match="CATALOG_AUDITOR_PERMISSIONS_INVALID"):
        _retry_transient_snapshot_collection(collect, sleep=lambda _: None)
    assert attempts == 1


def test_package_inventory_uses_githubs_canonical_organization_route() -> None:
    assert _package_inventory_endpoint(287229438, "container") == (
        "/organizations/287229438/packages?package_type=container"
    )
    with pytest.raises(ValueError, match="CATALOG_GITHUB_ORGANIZATION_ID_INVALID"):
        _package_inventory_endpoint(0, "container")


def test_bootstrap_controls_mode_defers_only_identity_and_live_capacity() -> None:
    inputs = protected_snapshots()
    snapshot = inputs["snapshots"]
    snapshot["local_agent"]["has_admin"] = True
    snapshot["local_agent"]["broker_acl_verified"] = False
    receipt = audit_catalog_github_controls(**inputs)
    assert bootstrap_controls_prepared(receipt)

    drifted = mutated_protection_snapshots("admins_not_enforced")
    drifted_receipt = audit_catalog_github_controls(**drifted)
    assert not bootstrap_controls_prepared(drifted_receipt)


def test_storage_pagination_is_complete_when_only_optional_telemetry_is_missing() -> None:
    storage = {
        "telemetry_complete": False,
        "artifacts_pagination_complete": True,
        "packages_pagination_complete": True,
        "caches_pagination_complete": True,
        "writer_inventory_complete": True,
    }

    assert github_audit_runner._storage_pagination_complete(storage)


def test_final_observation_uses_the_last_github_response_time() -> None:
    github_date = datetime(2026, 8, 24, 16, 7, 22, tzinfo=UTC)

    observed_at, github_api_observed_at = (
        github_audit_runner._final_observation_timestamps(github_date)
    )

    assert observed_at == "2026-08-24T16:07:22Z"
    assert github_api_observed_at == observed_at


def test_verified_zero_mutation_dry_run_needs_only_one_fresh_snapshot(
    tmp_path: Path, monkeypatch, request
) -> None:
    original_aurora_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "aurora" or name.startswith("aurora.")
    }

    def restore_import_identity() -> None:
        for name in tuple(sys.modules):
            if name == "aurora" or name.startswith("aurora."):
                del sys.modules[name]
        sys.modules.update(original_aurora_modules)
        sys.modules.pop("scripts.apply_catalog_github_controls", None)

    request.addfinalizer(restore_import_identity)
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    github_apply_runner = importlib.import_module(
        "scripts.apply_catalog_github_controls"
    )
    inputs = protected_snapshots()
    receipt = audit_catalog_github_controls(**inputs)
    plan = build_github_controls_mutation_plan(
        desired=inputs["desired"],
        receipt=receipt,
    )
    assert not plan.mutations
    dry_run = {
        "schema_version": "1",
        "mode": "dry_run",
        "repository": "trading-optimizer-lab-org/aurora",
        "before_receipt": receipt.model_dump(mode="json"),
        "current_receipt_sha256": receipt.receipt_sha256,
        "current_state_sha256": github_controls_state_sha256(receipt),
        "plan_sha256": plan.plan_sha256,
        "mutations": [],
        "api_responses": [],
        "after_receipt": None,
    }
    dry_path = tmp_path / "dry.json"
    github_audit_runner.write_json(dry_path, dry_run)
    output = tmp_path / "apply.json"
    calls = 0

    def fresh_snapshot(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return deepcopy(inputs["snapshots"])

    monkeypatch.setattr(github_apply_runner, "_live_snapshot", fresh_snapshot)

    result = github_apply_runner.main(
        [
            "--repo-root",
            str(ROOT),
            "--output",
            str(output),
            "--apply",
            "--bootstrap-controls-only",
            "--verified-dry-run",
            str(dry_path),
            "--expected-current-state-sha",
            dry_run["current_state_sha256"],
            "--confirm",
            "CATALOG_GITHUB_CONTROLS_V1",
        ]
    )

    applied = json.loads(output.read_text("utf-8"))
    assert result == 0
    assert calls == 1
    assert applied["mutations"] == []
    assert applied["after_receipt"]["status"] == "ready"


def test_apply_tool_binds_live_audit_to_observed_default_branch() -> None:
    source = (ROOT / "scripts/apply_catalog_github_controls.py").read_text("utf-8")
    assert 'protected_commit_sha="0" * 40' not in source
    assert 'protected_commit_sha=observed_default_sha' in source
    assert '"--bootstrap-controls-only"' in source
    assert '"current_state_sha256"' in source
    assert '"--expected-current-state-sha"' in source


def test_apply_tool_pins_imports_to_its_exact_source_checkout() -> None:
    source = (ROOT / "scripts/apply_catalog_github_controls.py").read_text("utf-8")
    pin = source.index("\n_pin_aurora_source_checkout()\n")
    catalog_import = source.index(
        "from aurora.infra.sp500_megarun.catalog_github_controls import"
    )
    assert pin < catalog_import
    assert '"__editable___aurora_"' in source
    assert 'name.startswith("aurora.")' in source
    assert 'spec_from_file_location(\n        "aurora"' in source
    assert "submodule_search_locations=[str(ROOT)]" in source


def test_branch_mutation_uses_the_github_rest_shape() -> None:
    inputs = mutated_protection_snapshots("admins_not_enforced")
    receipt = audit_catalog_github_controls(**inputs)
    plan = build_github_controls_mutation_plan(
        desired=inputs["desired"],
        receipt=receipt,
    )
    branch = next(
        mutation
        for mutation in plan.mutations
        if mutation.endpoint.endswith("/branches/main/protection")
    )
    assert branch.body["required_status_checks"] == {
        "strict": True,
        "contexts": [
            "GTBI V7 stage-two required",
            "catalog-controller-policy",
        ],
    }
    assert branch.body["required_pull_request_reviews"] == {
        "dismiss_stale_reviews": False,
        "require_code_owner_reviews": False,
        "required_approving_review_count": 0,
        "require_last_push_approval": False,
    }


def _write_snapshot_directory(path: Path) -> None:
    inputs = protected_snapshots()
    snapshot = inputs["snapshots"]
    assert isinstance(snapshot, dict)
    path.mkdir()
    (path / "normalized_snapshot.json").write_text(
        json.dumps(snapshot, sort_keys=True),
        encoding="utf-8",
    )


def test_snapshot_audit_cli_is_read_only_and_writes_valid_receipt(
    tmp_path: Path,
) -> None:
    snapshot_dir = tmp_path / "snapshot"
    output = tmp_path / "receipt.json"
    _write_snapshot_directory(snapshot_dir)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/audit_catalog_github_controls.py"),
            "--snapshot-dir",
            str(snapshot_dir),
            "--desired",
            str(CONTROLS),
            "--auditor",
            str(AUDITOR),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(output.read_text("utf-8"))
    assert receipt["status"] == "ready"
    assert len(receipt["receipt_sha256"]) == 64
    assert "private_key" not in output.read_text("utf-8").casefold()


def test_apply_cli_is_dry_run_by_default(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshot"
    output = tmp_path / "plan.json"
    _write_snapshot_directory(snapshot_dir)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/apply_catalog_github_controls.py"),
            "--snapshot-dir",
            str(snapshot_dir),
            "--desired",
            str(CONTROLS),
            "--auditor",
            str(AUDITOR),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    plan = json.loads(output.read_text("utf-8"))
    assert plan["mode"] == "dry_run"
    assert plan["mutations"] == []


def test_apply_cli_rejects_stale_expected_state_before_mutation(
    tmp_path: Path,
) -> None:
    snapshot_dir = tmp_path / "snapshot"
    output = tmp_path / "plan.json"
    _write_snapshot_directory(snapshot_dir)
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/apply_catalog_github_controls.py"),
            "--snapshot-dir",
            str(snapshot_dir),
            "--desired",
            str(CONTROLS),
            "--auditor",
            str(AUDITOR),
            "--output",
            str(output),
            "--apply",
            "--expected-current-state-sha",
            "0" * 64,
            "--confirm",
            "CATALOG_GITHUB_CONTROLS_V1",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "CATALOG_GITHUB_CONTROLS_STALE" in result.stderr
    failure = json.loads(output.read_text("utf-8"))
    assert failure["mode"] == "failed"
    assert failure["error_code"] == "CATALOG_GITHUB_CONTROLS_STALE"
    assert failure["failure_after_receipt"]["status"] == "ready"
    assert failure["failure_snapshot_error"] is None


def test_github_auditor_receipt_requires_exact_read_only_installation() -> None:
    inputs = protected_snapshots()
    snapshot = inputs["snapshots"]
    assert isinstance(snapshot, dict)
    snapshot["observer_context"] = "github_auditor"
    snapshot["local_agent"] = {}
    snapshot["runtime_provenance"] = {
        "caller_workflow": ".github/workflows/catalog-live-controls-qualification.yml",
        "caller_job": "qualify_live_admission_controls",
        "purpose": "admission",
        "audit_context_sha256": "d" * 64,
        "protected_commit_sha": "a" * 40,
        "verified": True,
    }
    auditor = inputs["auditor"]
    assert isinstance(auditor, CatalogGithubAuditorV1)
    snapshot["auditor_installation"] = {
        "repository_permissions": dict(auditor.required_repository_permissions),
        "organization_permissions": dict(auditor.required_organization_permissions),
        "enterprise_permissions": dict(auditor.required_enterprise_permissions),
        "repositories": [auditor.repository],
        "token_minted_in_process": True,
        "fixed_get_endpoints_only": True,
        "enterprise_billing_credential_kind": "classic_pat",
        "enterprise_billing_credential_scopes": list(
            auditor.required_enterprise_billing_token_scopes
        ),
        "enterprise_billing_get_only": True,
        "enterprise_billing_write_blocked_by_client": True,
        "enterprise_cache_verifier_credential_kind": "classic_pat",
        "enterprise_cache_verifier_credential_scopes": list(
            auditor.required_enterprise_cache_verifier_token_scopes
        ),
        "enterprise_cache_verifier_get_only": True,
        "enterprise_cache_verifier_write_blocked_by_client": True,
        "package_credential_kind": "oauth_device_token",
        "package_credential_scopes": list(
            auditor.required_package_inventory_token_scopes
        ),
        "package_write_blocked_by_client": True,
    }
    receipt = audit_catalog_github_controls(**inputs)
    assert receipt.status == "ready"
    assert receipt.local_agent_actor is None
    assert receipt.local_agent_has_admin is None
    assert receipt.audit_use_context == "live_qualification_admission"
    assert receipt.audit_context_sha256 == "d" * 64
    assert receipt.protected_commit_sha == "a" * 40
    assert receipt.caller_workflow == (
        ".github/workflows/catalog-live-controls-qualification.yml"
    )
    assert receipt.caller_job == "qualify_live_admission_controls"


def test_incomplete_storage_telemetry_blocks_without_estimating_headroom() -> None:
    inputs = protected_snapshots()
    snapshot = inputs["snapshots"]
    assert isinstance(snapshot, dict)
    snapshot["storage"]["packages_pagination_complete"] = False
    receipt = audit_catalog_github_controls(**inputs)
    assert "CATALOG_FREE_STORAGE_TELEMETRY_UNAVAILABLE" in receipt.failed_controls
    assert receipt.free_artifact_storage_headroom is None


def test_billing_storage_evidence_uses_the_current_daily_repository_period() -> None:
    payload = {
        "usageItems": [
            {
                "date": "2026-08-21T00:00:00Z",
                "product": "actions",
                "sku": "Actions storage",
                "quantity": 1_200.0,
                "unitType": "GigabyteHours",
                "repositoryName": "aurora",
            },
            {
                "date": "2026-08-21T00:00:00Z",
                "product": "actions",
                "sku": "Actions storage",
                "quantity": 9_999.0,
                "unitType": "GigabyteHours",
                "repositoryName": "another-repository",
            },
            {
                "date": "2026-08-20T00:00:00Z",
                "product": "actions",
                "sku": "Actions storage",
                "quantity": 2_400.0,
                "unitType": "GigabyteHours",
                "repositoryName": "aurora",
            },
        ]
    }

    evidence = _billing_actions_storage_evidence(
        payload,
        repository_name="aurora",
        observed_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
        included_shared_storage_bytes=50 * 1024**3,
    )

    assert evidence == {
        "billing_storage_period_evidence_complete": True,
        "billing_storage_period_started_at": "2026-08-21T00:00:00Z",
        "billing_storage_quantity_gigabyte_hours": 1_200.0,
        "billing_storage_period_elapsed_seconds": 43_200,
        "billing_storage_period_average_bytes": 100_000_000_000,
        "billing_storage_period_average_exceeds_allowance": True,
    }


def test_billing_storage_evidence_never_pretends_an_old_or_malformed_row_is_current() -> None:
    stale = {
        "usageItems": [
            {
                "date": "2026-08-20T00:00:00Z",
                "product": "actions",
                "sku": "Actions storage",
                "quantity": 2_400.0,
                "unitType": "GigabyteHours",
                "repositoryName": "aurora",
            }
        ]
    }
    malformed = deepcopy(stale)
    malformed["usageItems"][0]["date"] = "not-a-date"

    for payload in (stale, malformed, {"usageItems": []}):
        evidence = _billing_actions_storage_evidence(
            payload,
            repository_name="aurora",
            observed_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
            included_shared_storage_bytes=50 * 1024**3,
        )
        assert evidence["billing_storage_period_evidence_complete"] is False
        assert evidence["billing_storage_period_average_bytes"] is None
        assert evidence["billing_storage_period_average_exceeds_allowance"] is None


def test_billing_usage_endpoint_is_bound_to_the_observed_month() -> None:
    assert _billing_usage_endpoint(
        "trading-optimizer-lab-org",
        datetime(2026, 8, 21, 12, 0, tzinfo=UTC),
    ) == (
        "/organizations/trading-optimizer-lab-org/settings/billing/usage"
        "?year=2026&month=8"
    )


def test_active_artifact_inventory_excludes_expired_objects() -> None:
    rows, complete = _active_artifact_inventory(
        (
            {"id": 1, "size_in_bytes": 10, "expired": False},
            {"id": 2, "size_in_bytes": 999, "expired": True},
        )
    )

    assert complete is True
    assert rows == ({"id": 1, "size_in_bytes": 10, "expired": False},)


@pytest.mark.parametrize(
    "row",
    (
        {"id": 1, "size_in_bytes": 10},
        {"id": 1, "size_in_bytes": 10, "expired": "false"},
        {"id": 1, "size_in_bytes": True, "expired": False},
        {"id": 1, "size_in_bytes": -1, "expired": False},
    ),
)
def test_active_artifact_inventory_fails_closed_on_unknown_shape(
    row: dict[str, object],
) -> None:
    rows, complete = _active_artifact_inventory((row,))

    assert rows == ()
    assert complete is False


def test_complete_active_inventory_is_safe_current_storage_fallback() -> None:
    evidence = _reported_shared_storage_evidence(
        explicit_shared=None,
        billing_fresh=True,
        billing_period_complete=True,
        inventory_complete=True,
        artifact_inventory_bytes=39_000,
        package_inventory_bytes=1_000,
    )

    assert evidence == {
        "reported_shared_use_bytes": 40_000,
        "billing_snapshot_complete": True,
        "reported_shared_use_source": "complete_active_inventory",
    }


def test_current_storage_fallback_requires_fresh_billing_and_complete_inventory() -> None:
    for updates in (
        {"billing_fresh": False},
        {"billing_period_complete": False},
        {"inventory_complete": False},
    ):
        values = {
            "explicit_shared": None,
            "billing_fresh": True,
            "billing_period_complete": True,
            "inventory_complete": True,
            "artifact_inventory_bytes": 39_000,
            "package_inventory_bytes": 1_000,
            **updates,
        }
        evidence = _reported_shared_storage_evidence(**values)
        assert evidence["billing_snapshot_complete"] is False
        assert evidence["reported_shared_use_source"] == "unavailable"


def test_bootstrap_qualification_uses_zero_campaign_projection() -> None:
    projection = _campaign_storage_projection(
        qualification={"status": "blocked"},
        caller_workflow=(
            ".github/workflows/catalog-live-controls-qualification.yml"
        ),
        caller_job="qualify_live_admission_controls",
        purpose="admission",
    )

    assert projection == (0, 0, True)


def test_controller_admission_requires_promoted_campaign_projection() -> None:
    projection = _campaign_storage_projection(
        qualification={"status": "blocked"},
        caller_workflow=".github/workflows/catalog-run-controller.yml",
        caller_job="live_controls_audit_before_reserve",
        purpose="admission",
    )

    assert projection == (0, 0, False)


def test_keeper_accepts_the_protected_90_day_cache_policy() -> None:
    from scripts.run_catalog_artifact_keeper import _validate_controls_receipt

    inputs = protected_snapshots()
    snapshots = inputs["snapshots"]
    assert isinstance(snapshots, dict)
    snapshots["observer_context"] = "github_auditor"
    snapshots["local_agent"] = {}
    snapshots["runtime_provenance"].update(
        {
            "caller_workflow": ".github/workflows/catalog-artifact-keeper.yml",
            "caller_job": "live_controls_audit_before_maintenance",
            "purpose": "maintenance",
        }
    )
    auditor = inputs["auditor"]
    assert isinstance(auditor, CatalogGithubAuditorV1)
    snapshots["auditor_installation"] = {
        "repository_permissions": dict(auditor.required_repository_permissions),
        "organization_permissions": dict(auditor.required_organization_permissions),
        "enterprise_permissions": dict(auditor.required_enterprise_permissions),
        "repositories": [auditor.repository],
        "token_minted_in_process": True,
        "fixed_get_endpoints_only": True,
        "enterprise_billing_credential_kind": "classic_pat",
        "enterprise_billing_credential_scopes": list(
            auditor.required_enterprise_billing_token_scopes
        ),
        "enterprise_billing_get_only": True,
        "enterprise_billing_write_blocked_by_client": True,
        "enterprise_cache_verifier_credential_kind": "classic_pat",
        "enterprise_cache_verifier_credential_scopes": list(
            auditor.required_enterprise_cache_verifier_token_scopes
        ),
        "enterprise_cache_verifier_get_only": True,
        "enterprise_cache_verifier_write_blocked_by_client": True,
        "package_credential_kind": "oauth_device_token",
        "package_credential_scopes": list(
            auditor.required_package_inventory_token_scopes
        ),
        "package_write_blocked_by_client": True,
    }
    receipt = audit_catalog_github_controls(**inputs).model_dump(mode="json")

    checked = _validate_controls_receipt(
        receipt,
        repository="trading-optimizer-lab-org/aurora",
        protected_commit_sha="a" * 40,
    )

    assert checked["enterprise_cache_retention_days"] == 90
    assert checked["organization_cache_retention_days"] == 90
    assert checked["repository_cache_retention_days"] == 90


def _set_cache_retention(snapshot: dict[str, object], *values: object) -> None:
    settings = snapshot["cache_settings"]
    assert isinstance(settings, dict)
    settings["enterprise_retention_days"] = values[0]
    settings["organization_retention_days"] = values[1]
    settings["repository_retention_days"] = values[2]


def test_cache_config_uses_validated_organization_id_and_90_days() -> None:
    desired = load_desired_controls()
    assert desired.billing.budget_control_plane.organization_id == 287229438
    assert desired.billing.repository_cache_storage_limit_gb == 10
    assert desired.billing.repository_cache_retention_days == 90


def test_cache_retention_hierarchy_at_or_above_90_is_ready() -> None:
    inputs = protected_snapshots()
    snapshots = inputs["snapshots"]
    assert isinstance(snapshots, dict)
    _set_cache_retention(snapshots, 90, 91, 100)
    receipt = audit_catalog_github_controls(**inputs)
    assert receipt.status == "ready"
    assert receipt.enterprise_cache_retention_days == 90
    assert receipt.organization_cache_retention_days == 91
    assert receipt.repository_cache_retention_days == 100


def test_cache_retention_below_minimum_plans_exactly_three_puts_in_order() -> None:
    inputs = protected_snapshots()
    snapshots = inputs["snapshots"]
    assert isinstance(snapshots, dict)
    _set_cache_retention(snapshots, 89, 90, 90)
    receipt = audit_catalog_github_controls(**inputs)
    plan = build_github_controls_mutation_plan(
        desired=inputs["desired"], receipt=receipt
    )
    retention = [m for m in plan.mutations if "cache/retention-limit" in m.endpoint]
    assert [(m.method, m.endpoint.rsplit("/actions", 1)[0]) for m in retention] == [
        ("PUT", "/enterprises/trading-optimizer-lab"),
        ("PUT", "/organizations/287229438"),
        ("PUT", "/repos/trading-optimizer-lab-org/aurora"),
    ]
    assert len(retention) == 3


def test_cache_retention_above_minimum_is_preserved_in_plan_bodies() -> None:
    inputs = protected_snapshots()
    snapshots = inputs["snapshots"]
    assert isinstance(snapshots, dict)
    _set_cache_retention(snapshots, 91, 89, 120)
    receipt = audit_catalog_github_controls(**inputs)
    plan = build_github_controls_mutation_plan(
        desired=inputs["desired"], receipt=receipt
    )
    retention = [m for m in plan.mutations if "cache/retention-limit" in m.endpoint]
    assert [m.body["max_cache_retention_days"] for m in retention] == [91, 90, 120]


@pytest.mark.parametrize("unknown", [True, None, "90", 0])
def test_unknown_cache_retention_blocks_without_retention_mutations(unknown: object) -> None:
    inputs = protected_snapshots()
    snapshots = inputs["snapshots"]
    assert isinstance(snapshots, dict)
    _set_cache_retention(snapshots, unknown, 90, 90)
    receipt = audit_catalog_github_controls(**inputs)
    plan = build_github_controls_mutation_plan(
        desired=inputs["desired"], receipt=receipt
    )
    assert receipt.status == "blocked"
    assert "CACHE_RETENTION_UNKNOWN" in receipt.failed_controls
    assert not [m for m in plan.mutations if "cache/retention-limit" in m.endpoint]


def test_storage_limit_drift_never_plans_storage_put() -> None:
    inputs = protected_snapshots()
    snapshots = inputs["snapshots"]
    assert isinstance(snapshots, dict)
    snapshots["cache_settings"]["storage_limit_gb"] = 20
    _set_cache_retention(snapshots, 89, 89, 89)
    plan = build_github_controls_mutation_plan(
        desired=inputs["desired"],
        receipt=audit_catalog_github_controls(**inputs),
    )
    assert not any("cache/storage-limit" in m.endpoint for m in plan.mutations)


class _RetentionTransactionClient:
    def __init__(
        self,
        values: dict[str, int],
        *,
        fail_readback: str | None = None,
        fail_put: set[str] | None = None,
        fail_rollback: set[str] | None = None,
    ) -> None:
        self.values = dict(values)
        self.originals = dict(values)
        self.calls: list[tuple[str, str, object]] = []
        self.fail_readback = fail_readback
        self.readback_failed = False
        self.fail_put = fail_put or set()
        self.fail_rollback = fail_rollback or set()

    def get(self, endpoint: str) -> object:
        self.calls.append(("GET", endpoint, None))
        if (
            self.fail_readback == endpoint
            and not self.readback_failed
            and sum(call[0] == "GET" and call[1] == endpoint for call in self.calls) > 1
        ):
            self.readback_failed = True
            raise ValueError("readback failed")
        return {"max_cache_retention_days": self.values[endpoint]}

    def mutate(self, *, method: str, endpoint: str, body: dict[str, object]) -> object:
        self.calls.append((method, endpoint, body))
        target = int(body["max_cache_retention_days"])
        if endpoint in self.fail_put and target != self.originals[endpoint]:
            raise ValueError("put failed")
        if (
            endpoint in self.fail_rollback
            and target == self.originals[endpoint]
            and self.values[endpoint] != self.originals[endpoint]
        ):
            raise ValueError("rollback failed")
        self.values[endpoint] = target
        return {}


def _retention_receipt(values: tuple[int, int, int]):
    inputs = protected_snapshots()
    snapshots = inputs["snapshots"]
    assert isinstance(snapshots, dict)
    _set_cache_retention(snapshots, *values)
    return inputs["desired"], audit_catalog_github_controls(**inputs)


def test_retention_transaction_uses_exact_get_put_get_order() -> None:
    desired, receipt = _retention_receipt((89, 90, 120))
    plan = build_github_controls_mutation_plan(desired=desired, receipt=receipt)
    endpoints = [
        mutation.endpoint
        for mutation in plan.mutations
        if "cache/retention-limit" in mutation.endpoint
    ]
    client = _RetentionTransactionClient(
        dict(zip(endpoints, (89, 90, 120), strict=True))
    )

    responses = apply_cache_retention_transaction(
        client, desired=desired, receipt=receipt, plan=plan
    )

    assert [client.values[endpoint] for endpoint in endpoints] == [90, 90, 120]
    assert [response["readback"] for response in responses] == [90, 90, 120]
    assert [(call[0], call[1]) for call in client.calls] == [
        ("GET", endpoints[0]),
        ("GET", endpoints[1]),
        ("GET", endpoints[2]),
        ("GET", endpoints[0]),
        ("PUT", endpoints[0]),
        ("GET", endpoints[0]),
        ("GET", endpoints[1]),
        ("PUT", endpoints[1]),
        ("GET", endpoints[1]),
        ("GET", endpoints[2]),
        ("PUT", endpoints[2]),
        ("GET", endpoints[2]),
    ]


def test_retention_transaction_rejects_a_mixed_plan_before_any_api_call() -> None:
    inputs = mutated_protection_snapshots("admins_not_enforced")
    snapshots = inputs["snapshots"]
    assert isinstance(snapshots, dict)
    _set_cache_retention(snapshots, 89, 89, 89)
    receipt = audit_catalog_github_controls(**inputs)
    plan = build_github_controls_mutation_plan(
        desired=inputs["desired"], receipt=receipt
    )
    client = _RetentionTransactionClient({})

    with pytest.raises(ValueError, match="CATALOG_CACHE_RETENTION_PLAN_INVALID"):
        apply_cache_retention_transaction(
            client, desired=inputs["desired"], receipt=receipt, plan=plan
        )

    assert client.calls == []


def test_retention_transaction_is_get_put_get_and_rolls_back_level_one_on_level_two_failure() -> None:
    desired, receipt = _retention_receipt((89, 89, 89))
    plan = build_github_controls_mutation_plan(desired=desired, receipt=receipt)
    endpoints = [m.endpoint for m in plan.mutations if "cache/retention-limit" in m.endpoint]
    client = _RetentionTransactionClient({endpoint: 89 for endpoint in endpoints}, fail_put={endpoints[1]})
    with pytest.raises(ValueError, match="CATALOG_CACHE_RETENTION_TRANSACTION_FAILED"):
        apply_cache_retention_transaction(client, desired=desired, receipt=receipt, plan=plan)
    assert client.values[endpoints[0]] == 89
    assert client.values[endpoints[1]] == 89
    assert [(c[0], c[1]) for c in client.calls] == [
        ("GET", endpoints[0]), ("GET", endpoints[1]), ("GET", endpoints[2]),
        ("GET", endpoints[0]), ("PUT", endpoints[0]), ("GET", endpoints[0]),
        ("GET", endpoints[1]), ("PUT", endpoints[1]),
        ("PUT", endpoints[1]), ("GET", endpoints[1]),
        ("PUT", endpoints[0]), ("GET", endpoints[0]),
    ]


def test_retention_transaction_readback_failure_rolls_back_all_mutated_levels() -> None:
    desired, receipt = _retention_receipt((89, 89, 89))
    plan = build_github_controls_mutation_plan(desired=desired, receipt=receipt)
    endpoints = [m.endpoint for m in plan.mutations if "cache/retention-limit" in m.endpoint]
    client = _RetentionTransactionClient({endpoint: 89 for endpoint in endpoints}, fail_readback=endpoints[1])
    with pytest.raises(ValueError, match="CATALOG_CACHE_RETENTION_TRANSACTION_FAILED"):
        apply_cache_retention_transaction(client, desired=desired, receipt=receipt, plan=plan)
    assert all(client.values[endpoint] == 89 for endpoint in endpoints)


def test_retention_transaction_reports_rollback_failure_and_attempts_remaining_rollbacks() -> None:
    desired, receipt = _retention_receipt((89, 89, 89))
    plan = build_github_controls_mutation_plan(desired=desired, receipt=receipt)
    endpoints = [m.endpoint for m in plan.mutations if "cache/retention-limit" in m.endpoint]
    client = _RetentionTransactionClient(
        {endpoint: 89 for endpoint in endpoints},
        fail_put={endpoints[2]},
        fail_rollback={endpoints[0]},
    )
    with pytest.raises(ValueError, match="CATALOG_CACHE_RETENTION_ROLLBACK_FAILED"):
        apply_cache_retention_transaction(client, desired=desired, receipt=receipt, plan=plan)
    rollback_puts = [
        call
        for call in client.calls
        if call[0] == "PUT"
        and isinstance(call[2], dict)
        and call[2]["max_cache_retention_days"] == 89
    ]
    assert [call[1] for call in rollback_puts] == [
        endpoints[2],
        endpoints[1],
        endpoints[0],
    ]


def test_retention_transaction_detects_concurrent_raise_before_put() -> None:
    desired, receipt = _retention_receipt((89, 89, 89))
    plan = build_github_controls_mutation_plan(desired=desired, receipt=receipt)
    endpoints = [
        mutation.endpoint
        for mutation in plan.mutations
        if "cache/retention-limit" in mutation.endpoint
    ]

    class ConcurrentRaiseClient(_RetentionTransactionClient):
        def get(self, endpoint: str) -> object:
            if endpoint == endpoints[1] and sum(
                call[0] == "GET" and call[1] == endpoint for call in self.calls
            ) == 1:
                self.values[endpoint] = 120
            return super().get(endpoint)

    client = ConcurrentRaiseClient({endpoint: 89 for endpoint in endpoints})

    with pytest.raises(
        ValueError, match="CATALOG_CACHE_RETENTION_TRANSACTION_FAILED"
    ):
        apply_cache_retention_transaction(
            client, desired=desired, receipt=receipt, plan=plan
        )

    assert client.values[endpoints[0]] == 89
    assert client.values[endpoints[1]] == 120
    assert not any(
        call[0] == "PUT"
        and call[1] == endpoints[1]
        and call[2]["max_cache_retention_days"] == 90
        for call in client.calls
    )


class _PagedClient:
    def __init__(self, pages: dict[str, object]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    def get(self, endpoint: str) -> object:
        self.requested.append(endpoint)
        return deepcopy(self.pages[endpoint])


class _SequentialPagedClient:
    def __init__(self, pages: dict[str, list[object]]) -> None:
        self.pages = pages
        self.positions = {endpoint: 0 for endpoint in pages}
        self.requested: list[str] = []

    def get(self, endpoint: str) -> object:
        self.requested.append(endpoint)
        position = self.positions[endpoint]
        self.positions[endpoint] = position + 1
        return deepcopy(self.pages[endpoint][position])


def test_stable_object_pagination_requires_two_identical_complete_scans() -> None:
    client = _PagedClient(
        {
            "/items?per_page=100&page=1": {
                "total_count": 2,
                "items": [{"id": 1}, {"id": 2}],
            }
        }
    )

    rows, complete = _paginate_object_rows_stable(
        client,
        "/items",
        root="items",
        max_pages=1,
    )

    assert rows == ({"id": 1}, {"id": 2})
    assert complete is True
    assert len(client.requested) == 2


def test_stable_object_pagination_rejects_change_with_same_total() -> None:
    first_page = {
        "total_count": 101,
        "items": [{"id": value} for value in range(1, 101)],
    }
    client = _SequentialPagedClient(
        {
            "/items?per_page=100&page=1": [first_page, first_page],
            "/items?per_page=100&page=2": [
                {"total_count": 101, "items": [{"id": 101}]},
                {"total_count": 101, "items": [{"id": 102}]},
            ],
        }
    )

    with pytest.raises(ValueError, match="CATALOG_GITHUB_PAGINATION_UNSTABLE"):
        _paginate_object_rows_stable(
            client,
            "/items",
            root="items",
            max_pages=2,
        )


def test_stable_object_pagination_never_completes_after_incomplete_second_scan() -> None:
    first_page = {
        "total_count": 101,
        "items": [{"id": value} for value in range(1, 101)],
    }
    client = _SequentialPagedClient(
        {
            "/items?per_page=100&page=1": [first_page, first_page],
            "/items?per_page=100&page=2": [
                {"total_count": 101, "items": [{"id": 101}]},
                {
                    "total_count": 101,
                    "items": [{"id": value} for value in range(101, 201)],
                },
            ],
        }
    )

    rows, complete = _paginate_object_rows_stable(
        client,
        "/items",
        root="items",
        max_pages=2,
    )

    assert len(rows) in (101, 200)
    assert complete is False


def test_stable_list_pagination_requires_two_identical_complete_scans() -> None:
    client = _PagedClient(
        {
            "/rows?per_page=100&page=1": [{"id": 1}, {"id": 2}],
        }
    )

    rows, complete = _paginate_list_rows_stable(client, "/rows", max_pages=1)

    assert rows == ({"id": 1}, {"id": 2})
    assert complete is True
    assert len(client.requested) == 2


def test_live_auditor_fully_paginates_object_rows_without_duplicates() -> None:
    client = _PagedClient(
        {
            "/items?per_page=100&page=1": {
                "total_count": 205,
                "items": [{"id": value} for value in range(1, 101)],
            },
            "/items?per_page=100&page=2": {
                "total_count": 205,
                "items": [{"id": value} for value in range(101, 201)],
            },
            "/items?per_page=100&page=3": {
                "total_count": 205,
                "items": [{"id": value} for value in range(201, 206)],
            },
        }
    )
    rows, complete = _paginate_object_rows(
        client,
        "/items",
        root="items",
        max_pages=3,
    )
    assert complete is True
    assert [row["id"] for row in rows] == list(range(1, 206))
    assert len(client.requested) == 3


def test_live_auditor_stops_at_its_bound_and_never_claims_complete() -> None:
    client = _PagedClient(
        {
            "/items?per_page=100&page=1": {
                "total_count": 201,
                "items": [{"id": value} for value in range(1, 101)],
            }
        }
    )
    rows, complete = _paginate_object_rows(
        client,
        "/items",
        root="items",
        max_pages=1,
    )
    assert len(rows) == 100
    assert complete is False


def test_live_auditor_paginates_plain_lists_and_rejects_duplicate_ids() -> None:
    client = _PagedClient(
        {
            "/rows?per_page=100&page=1": [{"id": 1}, {"id": 2}],
            "/rows?per_page=100&page=2": [],
        }
    )
    rows, complete = _paginate_list_rows(client, "/rows", max_pages=2)
    assert rows == ({"id": 1}, {"id": 2})
    assert complete is True

    duplicate = _PagedClient(
        {"/rows?per_page=100&page=1": [{"id": 1}, {"id": 1}]}
    )
    with pytest.raises(ValueError, match="CATALOG_GITHUB_PAGINATION_DUPLICATE"):
        _paginate_list_rows(duplicate, "/rows", max_pages=1)
