"""Pure, fail-closed GitHub controls for autonomous catalog campaigns.

This module deliberately contains no network or subprocess access.  Adapters
collect fixed snapshots; this module validates them and emits a deterministic,
content-hashed receipt.  The receipt hash is an integrity checksum, not a
cryptographic signature.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from .catalog_request_contract import FrozenModel


Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
CommitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
RepositoryName = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"),
]

AUDITOR_SECRET_CONSUMER = ".github/workflows/catalog-live-controls-audit.yml"
AUDITOR_CALLER_TOPOLOGY = (
    (
        ".github/workflows/catalog-run-controller.yml",
        "live_controls_audit_before_reserve",
        "admission",
        "controller_admission",
    ),
    (
        ".github/workflows/catalog-run-controller.yml",
        "live_controls_audit_before_terminal",
        "terminal",
        "controller_terminal",
    ),
    (
        ".github/workflows/catalog-artifact-keeper.yml",
        "live_controls_audit_before_maintenance",
        "maintenance",
        "keeper_maintenance",
    ),
    (
        ".github/workflows/catalog-live-controls-qualification.yml",
        "qualify_live_admission_controls",
        "admission",
        "live_qualification_admission",
    ),
    (
        ".github/workflows/catalog-live-controls-qualification.yml",
        "qualify_live_terminal_controls",
        "terminal",
        "live_qualification_terminal",
    ),
)

_AUDIT_CONTEXT_BY_CALLER = {
    (workflow, job, purpose): context
    for workflow, job, purpose, context in AUDITOR_CALLER_TOPOLOGY
}
_ACTIVE_RUN_STATES = {"queued", "in_progress", "waiting", "pending"}
_DIRECT_HEAVY_TRIGGERS = {
    "workflow_dispatch",
    "schedule",
    "repository_dispatch",
    "push",
    "pull_request",
    "issues",
    "issue_comment",
}
_HEAVY_MARKERS = (
    "catalog-optimized-worker",
    "catalog_component_worker",
    "catalog-component-worker",
    "build_sp500_component_store",
    "merge_sp500_component_store",
    "run_sp500_optimized_recipe_worker",
    "reduce_sp500_optimized_catalog_run",
    "verify_sp500_optimized_run",
    "run_sp500_atlas_worker",
    "reduce_sp500_atlas_run",
    "merge_sp500_atlas",
    "sp500-atlas-run.yml",
    "run_sp500_strategy_catalog_shard",
    "benchmark_catalog_scale",
    "catalog planner",
    "catalog_planner",
    "catalog-planner",
)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _canonical_bytes(value: object) -> bytes:
    if isinstance(value, FrozenModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


class RepositoryIdentityV1(FrozenModel):
    full_name: RepositoryName
    owner_type: Literal["Organization"]
    visibility: Literal["public"]


class AuditFreshnessV1(FrozenModel):
    maximum_age_seconds: int = Field(ge=1)
    maximum_future_skew_seconds: int = Field(ge=0)
    time_source: Literal["github_api_date_header"]
    expired_admission_action: Literal["defer_without_authority"]
    expired_terminal_action: Literal["refresh_without_compute"]


class BranchProtectionV1(FrozenModel):
    enforce_admins: bool
    require_pull_request: bool
    required_approving_review_count: int = Field(ge=0)
    require_code_owner_reviews: bool
    dismiss_stale_reviews: bool
    require_last_push_approval: bool
    strict_status_checks: bool
    required_conversation_resolution: bool
    required_linear_history: bool
    allow_force_pushes: bool
    allow_deletions: bool
    required_status_checks: tuple[str, ...]


class ActionsControlsV1(FrozenModel):
    default_workflow_permissions: Literal["read", "write"]
    can_approve_pull_request_reviews: bool
    standard_github_hosted_only: bool
    larger_runners_allowed: bool
    self_hosted_runners_allowed: bool


class BudgetAlertingV1(FrozenModel):
    will_alert: bool
    alert_recipients: tuple[str, ...]


class ZeroBudgetV1(FrozenModel):
    budget_scope: Literal["repository"]
    budget_entity_name: str
    budget_type: Literal["ProductPricing", "SkuPricing"]
    budget_product_sku: Literal[
        "actions", "actions_storage", "actions_cache_storage"
    ]
    budget_amount: int = Field(ge=0)
    prevent_further_usage: bool
    budget_alerting: BudgetAlertingV1


class BudgetControlPlaneV1(FrozenModel):
    scope: Literal["enterprise"]
    enterprise_slug: str
    repository_entity_name: RepositoryName


class BillingControlsV1(FrozenModel):
    budget_control_plane: BudgetControlPlaneV1
    required_zero_budgets: tuple[ZeroBudgetV1, ...]
    included_shared_storage_bytes: int = Field(ge=1)
    repository_cache_storage_limit_gb: int = Field(ge=0)
    repository_cache_retention_days: int = Field(ge=1)
    artifact_and_packages_reporting_lag_hours: int = Field(ge=0)
    cache_reporting_lag_minutes: int = Field(ge=0)
    artifact_storage_safety_fraction: float = Field(ge=0.0, le=1.0)
    cache_storage_safety_fraction: float = Field(ge=0.0, le=1.0)
    paid_actions_usage_allowed: bool


class EnvironmentControlsV1(FrozenModel):
    name: str
    protected_branches_only: bool
    required_reviewers: tuple[str, ...]


class TerminalLabelV1(FrozenModel):
    name: str
    color: str
    description: str


class IssueLabelsV1(FrozenModel):
    terminal: TerminalLabelV1


class AuditorReferenceV1(FrozenModel):
    config_path: str
    app_id_variable: str
    private_key_environment_secret: str
    only_token_consumer_workflow: str


class CatalogEntrypointsV1(FrozenModel):
    public_controller: str
    request_reconciler: str
    ledger_guard: str
    authority_watchdog: str
    issues_write_workflow_allowlist: tuple[str, ...]
    issues_write_must_be_job_scoped: bool
    issues_write_job_allowlist: Mapping[str, tuple[str, ...]]
    fixed_nonproduction_trigger_exemptions: tuple[str, ...]
    scheduled_read_only_maintenance_allowlist: tuple[str, ...]
    heavy_workflows_must_be_workflow_call_only: bool


class CatalogGithubControlsV1(FrozenModel):
    schema_version: Literal["1"]
    github_api_version: str
    repository_identity: RepositoryIdentityV1
    default_branch: str
    audit_freshness: AuditFreshnessV1
    branch_protection: BranchProtectionV1
    actions: ActionsControlsV1
    billing: BillingControlsV1
    environment: EnvironmentControlsV1
    issue_labels: IssueLabelsV1
    auditor: AuditorReferenceV1
    entrypoints: CatalogEntrypointsV1

    @model_validator(mode="after")
    def _require_closed_budget_set(self) -> "CatalogGithubControlsV1":
        expected = {
            ("ProductPricing", "actions"),
            ("SkuPricing", "actions_storage"),
            ("SkuPricing", "actions_cache_storage"),
        }
        actual = {
            (budget.budget_type, budget.budget_product_sku)
            for budget in self.billing.required_zero_budgets
        }
        if len(self.billing.required_zero_budgets) != 3 or actual != expected:
            raise ValueError("catalog zero-budget set must be exact")
        return self


class CatalogGithubAuditorV1(FrozenModel):
    schema_version: Literal["1"]
    repository: RepositoryName
    expected_app_slug: str | None
    public_key_sha256: Sha256 | None
    required_repository_permissions: Mapping[str, Literal["read"]]
    required_organization_permissions: Mapping[str, Literal["read"]]
    required_enterprise_permissions: Mapping[str, Literal["read"]]
    forbidden_write_permissions: tuple[str, ...]
    private_key_environment_secret: str
    app_id_variable: str

    @model_validator(mode="after")
    def _require_read_only(self) -> "CatalogGithubAuditorV1":
        if any(
            value != "read"
            for value in (
                *self.required_repository_permissions.values(),
                *self.required_organization_permissions.values(),
                *self.required_enterprise_permissions.values(),
            )
        ):
            raise ValueError("auditor permissions must be read-only")
        return self


AuditUseContext = Literal[
    "controller_admission",
    "controller_terminal",
    "keeper_maintenance",
    "live_qualification_admission",
    "live_qualification_terminal",
]


class _CatalogGithubControlsReceiptBaseV1(FrozenModel):
    schema_version: Literal["1"]
    status: Literal["ready", "blocked"]
    repository: RepositoryName
    observed_default_branch_sha: CommitSha
    observed_repository_visibility: str
    checked_controls: tuple[str, ...]
    failed_controls: tuple[str, ...]
    heavy_workflow_inventory: tuple[Mapping[str, object], ...]
    active_heavy_run_inventory: tuple[Mapping[str, object], ...]
    unmanaged_active_heavy_run_ids: tuple[int, ...]
    request_actor_permissions: Mapping[str, object]
    actions_zero_spend_budgets: tuple[Mapping[str, object], ...]
    actions_billing_usage_snapshot: Mapping[str, object]
    free_artifact_storage_headroom: int | None = Field(ge=0)
    free_cache_storage_headroom: int | None = Field(ge=0)
    repository_cache_storage_limit_gb: int | None = Field(ge=0)
    repository_cache_retention_days: int | None = Field(ge=0)
    projected_campaign_artifact_bytes: int | None = Field(ge=0)
    projected_campaign_cache_bytes: int | None = Field(ge=0)
    local_agent_actor: str | None
    local_agent_has_admin: bool | None
    auditor_installation_proof: Mapping[str, object] | None
    audit_use_context: AuditUseContext
    observed_at: datetime
    github_api_observed_at: datetime
    source_snapshot_sha256: Sha256
    receipt_sha256: Sha256

    @field_validator("observed_at", "github_api_observed_at")
    @classmethod
    def _require_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("audit timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _require_consistent_hash_and_status(
        self,
    ) -> "_CatalogGithubControlsReceiptBaseV1":
        if self.status == "ready" and self.failed_controls:
            raise ValueError("ready controls receipt cannot contain failures")
        if self.status == "blocked" and not self.failed_controls:
            raise ValueError("blocked controls receipt requires a failure")
        if tuple(sorted(set(self.failed_controls))) != self.failed_controls:
            raise ValueError("failed controls must be unique and sorted")
        payload = self.model_dump(mode="json", exclude={"receipt_sha256"})
        if _sha256(payload) != self.receipt_sha256:
            raise ValueError("catalog controls receipt hash mismatch")
        return self


class BootstrapCatalogGithubControlsReceiptV1(
    _CatalogGithubControlsReceiptBaseV1
):
    observer_context: Literal["bootstrap_local"]
    local_agent_actor: str
    local_agent_has_admin: bool
    auditor_installation_proof: None = None


class AuditorCatalogGithubControlsReceiptV1(_CatalogGithubControlsReceiptBaseV1):
    observer_context: Literal["github_auditor"]
    local_agent_actor: None = None
    local_agent_has_admin: None = None
    auditor_installation_proof: Mapping[str, object]


CatalogGithubControlsReceiptV1 = (
    BootstrapCatalogGithubControlsReceiptV1
    | AuditorCatalogGithubControlsReceiptV1
)


class GithubControlMutationV1(FrozenModel):
    order: int = Field(ge=1)
    method: Literal["PUT", "POST", "PATCH"]
    endpoint: str
    body: Mapping[str, object]
    reason_codes: tuple[str, ...]


class CatalogGithubControlsMutationPlanV1(FrozenModel):
    schema_version: Literal["1"]
    repository: RepositoryName
    current_receipt_sha256: Sha256
    mutations: tuple[GithubControlMutationV1, ...]
    plan_sha256: Sha256

    @model_validator(mode="after")
    def _require_plan_hash(self) -> "CatalogGithubControlsMutationPlanV1":
        payload = self.model_dump(mode="json", exclude={"plan_sha256"})
        if _sha256(payload) != self.plan_sha256:
            raise ValueError("catalog GitHub mutation plan hash mismatch")
        return self


def _load_json(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_nonfinite,
    )


def load_catalog_github_controls(path: Path) -> CatalogGithubControlsV1:
    try:
        return CatalogGithubControlsV1.model_validate(_load_json(path))
    except Exception as exc:
        raise ValueError(f"CATALOG_GITHUB_CONTROLS_INVALID: {exc}") from None


def load_catalog_github_auditor(path: Path) -> CatalogGithubAuditorV1:
    try:
        return CatalogGithubAuditorV1.model_validate(_load_json(path))
    except Exception as exc:
        raise ValueError(f"CATALOG_GITHUB_AUDITOR_INVALID: {exc}") from None


def _trigger_names(workflow: Mapping[str, object]) -> tuple[str, ...]:
    trigger = workflow.get("on", {})
    if isinstance(trigger, str):
        return (trigger,)
    if isinstance(trigger, list):
        return tuple(sorted(str(item) for item in trigger))
    if isinstance(trigger, Mapping):
        return tuple(sorted(str(item) for item in trigger))
    return ()


def _executable_workflow_text(workflow: Mapping[str, object]) -> str:
    executable: list[str] = []
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, Mapping):
        return ""
    for job in jobs.values():
        if not isinstance(job, Mapping):
            continue
        if "uses" in job:
            executable.append(str(job["uses"]))
        steps = job.get("steps", ())
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            executable.extend(str(step[key]) for key in ("uses", "run") if key in step)
    return "\n".join(executable).casefold()


def inventory_heavy_workflows(
    workflow_documents: Mapping[str, Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    """Classify every supplied workflow from executable content, not filename."""

    inventory: list[Mapping[str, object]] = []
    for path in sorted(workflow_documents):
        workflow = workflow_documents[path]
        executable = _executable_workflow_text(workflow)
        markers = tuple(marker for marker in _HEAVY_MARKERS if marker in executable)
        triggers = _trigger_names(workflow)
        inventory.append(
            {
                "path": path,
                "heavy": bool(markers),
                "matched_markers": markers,
                "triggers": triggers,
                "direct_heavy_triggers": tuple(
                    trigger
                    for trigger in triggers
                    if trigger in _DIRECT_HEAVY_TRIGGERS
                ),
            }
        )
    return tuple(inventory)


def jobs_with_issues_write(
    workflow_documents: Mapping[str, Mapping[str, object]],
) -> tuple[tuple[str, str], ...]:
    """Return workflow/job pairs that effectively request ``issues: write``."""

    writers: list[tuple[str, str]] = []
    for path in sorted(workflow_documents):
        workflow = workflow_documents[path]
        top_permissions = workflow.get("permissions", {})
        top_write = isinstance(top_permissions, Mapping) and (
            top_permissions.get("issues") == "write"
        )
        jobs = workflow.get("jobs", {})
        if not isinstance(jobs, Mapping):
            continue
        for job_name, job in jobs.items():
            if not isinstance(job, Mapping):
                continue
            permissions = job.get("permissions")
            job_write = isinstance(permissions, Mapping) and (
                permissions.get("issues") == "write"
            )
            if top_write or job_write:
                writers.append((path, str(job_name)))
    return tuple(writers)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _canonical_budget_entity(value: object, repository: str) -> str | None:
    owner, name = repository.split("/", maxsplit=1)
    if value in {name, f"{owner}/{name}"}:
        return repository
    return None


def _budget_sku(row: Mapping[str, object]) -> str | None:
    singular = row.get("budget_product_sku")
    plural = row.get("budget_product_skus")
    if singular is not None and plural is not None:
        return None
    if isinstance(singular, str):
        return singular
    if isinstance(plural, list) and len(plural) == 1 and isinstance(plural[0], str):
        return plural[0]
    return None


def _normalized_budget_contract(
    row: Mapping[str, object],
    repository: str,
) -> Mapping[str, object] | None:
    sku = _budget_sku(row)
    entity = _canonical_budget_entity(row.get("budget_entity_name"), repository)
    budget_id = row.get("id")
    alerting = row.get("budget_alerting")
    if (
        sku is None
        or entity is None
        or not isinstance(budget_id, str | int)
        or not isinstance(alerting, Mapping)
    ):
        return None
    return {
        "id": budget_id,
        "budget_scope": row.get("budget_scope"),
        "budget_entity_name": entity,
        "budget_type": row.get("budget_type"),
        "budget_product_sku": sku,
        "budget_amount": row.get("budget_amount"),
        "prevent_further_usage": row.get("prevent_further_usage"),
        "budget_alerting": dict(alerting),
    }


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence_of_mappings(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _auditor_proof_is_exact(
    proof: Mapping[str, object],
    auditor: CatalogGithubAuditorV1,
) -> bool:
    repository_permissions = proof.get("repository_permissions")
    organization_permissions = proof.get("organization_permissions")
    enterprise_permissions = proof.get("enterprise_permissions")
    repositories = proof.get("repositories")
    if repository_permissions != dict(auditor.required_repository_permissions):
        return False
    if organization_permissions != dict(auditor.required_organization_permissions):
        return False
    if enterprise_permissions != dict(auditor.required_enterprise_permissions):
        return False
    if repositories != [auditor.repository]:
        return False
    if proof.get("token_minted_in_process") is not True:
        return False
    if proof.get("fixed_get_endpoints_only") is not True:
        return False
    permissions = {
        **_mapping(repository_permissions),
        **_mapping(organization_permissions),
        **_mapping(enterprise_permissions),
    }
    return not any(value == "write" for value in permissions.values())


def audit_catalog_github_controls(
    *,
    desired: CatalogGithubControlsV1,
    auditor: CatalogGithubAuditorV1,
    snapshots: Mapping[str, object],
) -> CatalogGithubControlsReceiptV1:
    """Compare one complete normalized snapshot against the protected contract."""

    desired = CatalogGithubControlsV1.model_validate(
        desired.model_dump(mode="json")
    )
    auditor = CatalogGithubAuditorV1.model_validate(auditor.model_dump(mode="json"))
    failures: list[str] = []
    checked: list[str] = []

    def check(control: str, condition: bool) -> None:
        checked.append(control)
        if not condition:
            failures.append(control)

    repository = _mapping(snapshots.get("repository"))
    observed_repository = str(repository.get("full_name", desired.repository_identity.full_name))
    check(
        "PUBLIC_REPOSITORY_REQUIRED",
        observed_repository == desired.repository_identity.full_name
        and _mapping(repository.get("owner")).get("type")
        == desired.repository_identity.owner_type
        and repository.get("visibility") == desired.repository_identity.visibility
        and repository.get("private") is False,
    )
    check("MAIN_DEFAULT_BRANCH_REQUIRED", repository.get("default_branch") == desired.default_branch)
    observed_sha = str(repository.get("default_branch_sha", ""))
    check("PROTECTED_HEAD_SHA_REQUIRED", bool(re.fullmatch(r"[0-9a-f]{40}", observed_sha)))
    if not re.fullmatch(r"[0-9a-f]{40}", observed_sha):
        observed_sha = "0" * 40

    branch = _mapping(snapshots.get("branch_protection"))
    branch_checks = (
        ("MAIN_ADMINS_ENFORCED", branch.get("enforce_admins") is True),
        ("MAIN_PULL_REQUEST_REQUIRED", branch.get("require_pull_request") is True),
        (
            "MAIN_APPROVAL_POLICY_EXACT",
            branch.get("required_approving_review_count")
            == desired.branch_protection.required_approving_review_count
            and branch.get("require_code_owner_reviews")
            == desired.branch_protection.require_code_owner_reviews
            and branch.get("dismiss_stale_reviews")
            == desired.branch_protection.dismiss_stale_reviews
            and branch.get("require_last_push_approval")
            == desired.branch_protection.require_last_push_approval,
        ),
        ("MAIN_STRICT_STATUS_CHECKS_REQUIRED", branch.get("strict_status_checks") is True),
        (
            "MAIN_STATUS_CHECKS_EXACT",
            tuple(branch.get("required_status_checks", ()))
            == desired.branch_protection.required_status_checks,
        ),
        (
            "MAIN_CONVERSATIONS_MUST_RESOLVE",
            branch.get("required_conversation_resolution") is True,
        ),
        ("MAIN_LINEAR_HISTORY_REQUIRED", branch.get("required_linear_history") is True),
        ("MAIN_FORCE_PUSH_FORBIDDEN", branch.get("allow_force_pushes") is False),
        ("MAIN_DELETE_FORBIDDEN", branch.get("allow_deletions") is False),
    )
    for control, condition in branch_checks:
        check(control, condition)

    actions = _mapping(snapshots.get("actions_permissions"))
    check(
        "DEFAULT_TOKEN_READ_ONLY",
        actions.get("default_workflow_permissions")
        == desired.actions.default_workflow_permissions,
    )
    check(
        "ACTIONS_PR_APPROVAL_FORBIDDEN",
        actions.get("can_approve_pull_request_reviews") is False,
    )
    check(
        "STANDARD_GITHUB_HOSTED_RUNNER_REQUIRED",
        actions.get("standard_github_hosted_only") is True,
    )
    check(
        "PAID_RUNNER_FORBIDDEN",
        actions.get("larger_runners_allowed") is False
        and actions.get("self_hosted_runners_allowed") is False,
    )

    environment = snapshots.get("environment")
    check(
        "CATALOG_ENVIRONMENT_REQUIRED",
        isinstance(environment, Mapping)
        and environment.get("name") == desired.environment.name,
    )
    environment_map = _mapping(environment)
    check(
        "CATALOG_ENVIRONMENT_MAIN_ONLY",
        environment_map.get("name") == desired.environment.name
        and environment_map.get("protected_branches_only") is True
        and tuple(environment_map.get("required_reviewers", ()))
        == desired.environment.required_reviewers,
    )

    labels = _sequence_of_mappings(snapshots.get("labels"))
    expected_label = desired.issue_labels.terminal.model_dump(mode="json")
    matching_labels = tuple(
        label for label in labels if label.get("name") == expected_label["name"]
    )
    check("CATALOG_TERMINAL_LABEL_REQUIRED", len(matching_labels) == 1)
    check(
        "CATALOG_TERMINAL_LABEL_EXACT",
        len(matching_labels) == 1
        and {
            "name": matching_labels[0].get("name"),
            "color": str(matching_labels[0].get("color", "")).lower(),
            "description": matching_labels[0].get("description"),
        }
        == expected_label,
    )

    budgets = _sequence_of_mappings(snapshots.get("budgets"))
    budget_details = _sequence_of_mappings(snapshots.get("budget_details"))
    desired_by_sku = {
        budget.budget_product_sku: budget
        for budget in desired.billing.required_zero_budgets
    }
    observed_by_sku: dict[str, list[Mapping[str, object]]] = {}
    rows_with_expected_sku_but_wrong_entity: list[Mapping[str, object]] = []
    for row in budgets:
        sku = _budget_sku(row)
        entity = _canonical_budget_entity(
            row.get("budget_entity_name"),
            desired.repository_identity.full_name,
        )
        if sku in desired_by_sku and entity == desired.repository_identity.full_name:
            observed_by_sku.setdefault(sku, []).append(row)
        elif sku in desired_by_sku and entity is None:
            rows_with_expected_sku_but_wrong_entity.append(row)
    target_budgets = tuple(
        row for rows in observed_by_sku.values() for row in rows
    )
    target_ids = {row.get("id") for row in target_budgets}
    target_details = tuple(
        row for row in budget_details if row.get("id") in target_ids
    )
    check(
        "ZERO_BUDGET_REPOSITORY_SCOPE_EXACT",
        not rows_with_expected_sku_but_wrong_entity
        or all(len(observed_by_sku.get(sku, ())) == 1 for sku in desired_by_sku),
    )
    budget_reason = {
        "actions": "ZERO_ACTIONS_SPEND_BUDGET_REQUIRED",
        "actions_storage": "ZERO_ACTIONS_STORAGE_BUDGET_REQUIRED",
        "actions_cache_storage": "ZERO_CACHE_STORAGE_BUDGET_REQUIRED",
    }
    normalized_budgets: list[Mapping[str, object]] = []
    for sku, expected in desired_by_sku.items():
        rows = observed_by_sku.get(sku, [])
        exact = len(rows) == 1
        if exact:
            row = rows[0]
            exact = (
                row.get("budget_scope") == expected.budget_scope
                and _canonical_budget_entity(
                    row.get("budget_entity_name"),
                    desired.repository_identity.full_name,
                )
                == desired.repository_identity.full_name
                and row.get("budget_type") == expected.budget_type
                and row.get("budget_amount") == expected.budget_amount
                and row.get("prevent_further_usage")
                == expected.prevent_further_usage
                and _mapping(row.get("budget_alerting"))
                == expected.budget_alerting.model_dump(mode="json")
            )
        check(budget_reason[sku], exact)
        if rows:
            normalized_budgets.append(dict(rows[0]))
        if sku == "actions":
            check(
                "ZERO_ACTIONS_SPEND_STOP_REQUIRED",
                len(rows) == 1 and rows[0].get("prevent_further_usage") is True,
            )
    normalized_list = tuple(
        _normalized_budget_contract(
            row,
            desired.repository_identity.full_name,
        )
        for row in target_budgets
    )
    normalized_details = tuple(
        _normalized_budget_contract(
            row,
            desired.repository_identity.full_name,
        )
        for row in target_details
    )
    list_ids = [row.get("id") for row in target_budgets]
    detail_ids = [row.get("id") for row in target_details]
    check(
        "ZERO_BUDGET_DETAIL_CROSSCHECK_REQUIRED",
        len(target_budgets) == 3
        and len(target_details) == 3
        and len(set(list_ids)) == 3
        and set(list_ids) == set(detail_ids)
        and None not in normalized_list
        and None not in normalized_details
        and set(_canonical_bytes(item) for item in normalized_list)
        == set(_canonical_bytes(item) for item in normalized_details),
    )

    cache = _mapping(snapshots.get("cache_settings"))
    cache_limit = cache.get("storage_limit_gb")
    cache_retention = cache.get("retention_days")
    check(
        "FREE_CACHE_STORAGE_LIMIT_REQUIRED",
        cache_limit == desired.billing.repository_cache_storage_limit_gb,
    )
    check(
        "CACHE_RETENTION_POLICY_REQUIRED",
        cache_retention == desired.billing.repository_cache_retention_days,
    )

    storage = _mapping(snapshots.get("storage"))
    completeness_keys = (
        "telemetry_complete",
        "artifacts_pagination_complete",
        "packages_pagination_complete",
        "caches_pagination_complete",
        "writer_inventory_complete",
        "billing_snapshot_complete",
    )
    storage_complete = all(storage.get(key) is True for key in completeness_keys)
    numeric_keys = (
        "shared_allowance_bytes",
        "reported_shared_use_bytes",
        "artifact_inventory_bytes",
        "package_inventory_bytes",
        "unreflected_upload_bytes",
        "reported_cache_use_bytes",
        "cache_inventory_bytes",
        "pending_cache_bytes",
        "projected_campaign_artifact_bytes",
        "projected_campaign_cache_bytes",
        "paid_runner_minutes",
        "estimated_paid_actions_cost",
    )
    numeric_storage = all(
        isinstance(storage.get(key), int)
        and not isinstance(storage.get(key), bool)
        and int(storage[key]) >= 0
        for key in numeric_keys
    )
    allowance_exact = (
        storage.get("shared_allowance_bytes")
        == desired.billing.included_shared_storage_bytes
    )
    check(
        "CATALOG_FREE_STORAGE_TELEMETRY_UNAVAILABLE",
        storage_complete and numeric_storage and allowance_exact,
    )
    artifact_headroom: int | None = None
    cache_headroom: int | None = None
    if (
        storage_complete
        and numeric_storage
        and allowance_exact
        and isinstance(cache_limit, int)
    ):
        allowance = int(storage["shared_allowance_bytes"])
        reconciled = max(
            int(storage["reported_shared_use_bytes"]),
            int(storage["artifact_inventory_bytes"])
            + int(storage["package_inventory_bytes"]),
        )
        artifact_headroom = int(
            allowance
            - reconciled
            - int(storage["unreflected_upload_bytes"])
            - allowance * desired.billing.artifact_storage_safety_fraction
            - int(storage["projected_campaign_artifact_bytes"])
        )
        cache_limit_bytes = cache_limit * 1_000_000_000
        cache_headroom = int(
            cache_limit_bytes
            - max(
                int(storage["reported_cache_use_bytes"]),
                int(storage["cache_inventory_bytes"]),
            )
            - int(storage["pending_cache_bytes"])
            - cache_limit_bytes * desired.billing.cache_storage_safety_fraction
            - int(storage["projected_campaign_cache_bytes"])
        )
    check(
        "CATALOG_ARTIFACT_STORAGE_HEADROOM_SUFFICIENT",
        artifact_headroom is not None and artifact_headroom >= 0,
    )
    check(
        "CATALOG_CACHE_STORAGE_HEADROOM_SUFFICIENT",
        cache_headroom is not None and cache_headroom >= 0,
    )
    if artifact_headroom is not None and artifact_headroom < 0:
        artifact_headroom = None
    if cache_headroom is not None and cache_headroom < 0:
        cache_headroom = None
    check(
        "ZERO_PAID_ACTIONS_USAGE_REQUIRED",
        storage.get("paid_runner_minutes") == 0
        and storage.get("estimated_paid_actions_cost") == 0
        and desired.billing.paid_actions_usage_allowed is False,
    )

    workflow_documents_raw = snapshots.get("workflow_documents")
    workflow_documents = (
        workflow_documents_raw
        if isinstance(workflow_documents_raw, Mapping)
        and all(isinstance(value, Mapping) for value in workflow_documents_raw.values())
        else {}
    )
    heavy_inventory = inventory_heavy_workflows(workflow_documents)  # type: ignore[arg-type]
    heavy_paths = {
        str(row["path"]) for row in heavy_inventory if row.get("heavy") is True
    }
    public_heavy_entrypoints = {
        desired.entrypoints.public_controller,
        desired.entrypoints.authority_watchdog,
    }
    exempt_heavy_triggers = public_heavy_entrypoints | set(
        desired.entrypoints.fixed_nonproduction_trigger_exemptions
    )
    direct_dispatch = any(
        "workflow_dispatch" in row.get("direct_heavy_triggers", ())
        for row in heavy_inventory
        if row.get("heavy") is True
        and row.get("path") not in exempt_heavy_triggers
    )
    other_direct = any(
        set(row.get("direct_heavy_triggers", ())) - {"workflow_dispatch"}
        for row in heavy_inventory
        if row.get("heavy") is True
        and row.get("path") not in public_heavy_entrypoints
        and row.get("path")
        not in desired.entrypoints.fixed_nonproduction_trigger_exemptions
    )
    check("HEAVY_DIRECT_DISPATCH_FORBIDDEN", not direct_dispatch)
    check("HEAVY_DIRECT_TRIGGER_FORBIDDEN", not other_direct)

    writers = jobs_with_issues_write(workflow_documents)  # type: ignore[arg-type]
    allowed_writers = {
        (path, job)
        for path, jobs in desired.entrypoints.issues_write_job_allowlist.items()
        for job in jobs
    }
    check("ISSUES_WRITE_TOPOLOGY_EXACT", set(writers) <= allowed_writers)

    source_hashes = _mapping(snapshots.get("workflow_source_sha256s"))
    check(
        "WORKFLOW_INVENTORY_COMPLETE",
        bool(workflow_documents)
        and set(workflow_documents) == set(source_hashes)
        and all(re.fullmatch(r"[0-9a-f]{64}", str(value)) for value in source_hashes.values()),
    )

    active_runs = _sequence_of_mappings(snapshots.get("active_runs"))
    unmanaged_ids: list[int] = []
    for run in active_runs:
        if run.get("status") not in _ACTIVE_RUN_STATES:
            continue
        if run.get("workflow_path") not in heavy_paths:
            continue
        bound = all(
            run.get(key) is True
            for key in (
                "authority_bound",
                "protected_commit_matches",
                "sealed_identifiers_match",
                "writer_provenance_verified",
                "current_engine_owner",
            )
        )
        if not bound and isinstance(run.get("run_id"), int):
            unmanaged_ids.append(int(run["run_id"]))
    check(
        "CATALOG_UNMANAGED_HEAVY_RUN_ACTIVE",
        not unmanaged_ids
        and snapshots.get("runs_pagination_complete") is True
        and snapshots.get("jobs_pagination_complete") is True,
    )

    request_actor = _mapping(snapshots.get("request_actor_permissions"))
    check(
        "REQUEST_ACTOR_NON_ADMIN",
        request_actor.get("kind") == "GitHubApp"
        and request_actor.get("repository_administration") == "none"
        and request_actor.get("repository_actions") == "none"
        and request_actor.get("repository_contents") == "none"
        and request_actor.get("repository_issues") == "write",
    )

    observer_context = snapshots.get("observer_context")
    if observer_context not in {"bootstrap_local", "github_auditor"}:
        observer_context = "bootstrap_local"
        check("CATALOG_OBSERVER_CONTEXT_VALID", False)
    else:
        check("CATALOG_OBSERVER_CONTEXT_VALID", True)

    provenance = _mapping(snapshots.get("runtime_provenance"))
    caller = (
        provenance.get("caller_workflow"),
        provenance.get("caller_job"),
        provenance.get("purpose"),
    )
    audit_context = _AUDIT_CONTEXT_BY_CALLER.get(caller)
    check(
        "CATALOG_AUDIT_CALLER_PROVENANCE_VERIFIED",
        provenance.get("verified") is True and audit_context is not None,
    )
    if audit_context is None:
        audit_context = "controller_admission"

    consumer_workflows = snapshots.get("auditor_secret_consumer_workflows")
    callers = _sequence_of_mappings(snapshots.get("auditor_runtime_callers"))
    normalized_callers = {
        (
            item.get("caller_workflow"),
            item.get("caller_job"),
            item.get("purpose"),
        )
        for item in callers
    }
    topology_valid = (
        consumer_workflows == [AUDITOR_SECRET_CONSUMER]
        and len(normalized_callers) == len(callers)
        and normalized_callers <= set(_AUDIT_CONTEXT_BY_CALLER)
    )
    check("CATALOG_AUDITOR_TOPOLOGY_INVALID", topology_valid)

    local_agent = _mapping(snapshots.get("local_agent"))
    auditor_installation = snapshots.get("auditor_installation")
    if observer_context == "bootstrap_local":
        local_actor = local_agent.get("actor")
        local_admin = local_agent.get("has_admin")
        check(
            "LOCAL_AGENT_CAPABILITY_AUDIT_COMPLETE",
            isinstance(local_actor, str)
            and isinstance(local_admin, bool)
            and local_agent.get("broker_acl_verified") is True
            and local_agent.get("process_environment_verified") is True,
        )
        check("AGENT_ADMIN_CREDENTIAL_EXPOSED", local_admin is False)
        check(
            "AGENT_REQUESTER_CREDENTIAL_EXPOSED",
            local_agent.get("can_read_requester_credential") is False,
        )
        check(
            "AGENT_AUDITOR_CREDENTIAL_EXPOSED",
            local_agent.get("can_read_auditor_credential") is False,
        )
        check("CATALOG_AUDITOR_INSTALLATION_EXACT", auditor_installation is None)
        auditor_proof: Mapping[str, object] | None = None
    else:
        local_actor = None
        local_admin = None
        check("LOCAL_AGENT_FIELDS_FORBIDDEN_IN_AUDITOR", not local_agent)
        proof = _mapping(auditor_installation)
        exact_proof = _auditor_proof_is_exact(proof, auditor)
        check("CATALOG_AUDITOR_INSTALLATION_EXACT", exact_proof)
        auditor_proof = proof

    check("CATALOG_AUTHORITY_ANCHOR_INVALID", snapshots.get("authority_anchor_verified") is True)
    check(
        "CATALOG_SNAPSHOT_PAGINATION_COMPLETE",
        snapshots.get("pagination_complete") is True,
    )
    check("CATALOG_API_VERSION_VERIFIED", snapshots.get("api_version_verified") is True)

    observed_at = _parse_time(snapshots.get("observed_at"))
    github_at = _parse_time(snapshots.get("github_api_observed_at"))
    freshness_valid = observed_at is not None and github_at is not None
    if freshness_valid:
        delta = (observed_at - github_at).total_seconds()
        freshness_valid = (
            delta <= desired.audit_freshness.maximum_age_seconds
            and delta >= -desired.audit_freshness.maximum_future_skew_seconds
        )
    check("CATALOG_AUDIT_FRESHNESS_REQUIRED", freshness_valid)
    if observed_at is None:
        observed_at = datetime(1970, 1, 1, tzinfo=UTC)
    if github_at is None:
        github_at = datetime(1970, 1, 1, tzinfo=UTC)

    source_snapshot_sha256 = _sha256(snapshots)
    failed_controls = tuple(sorted(set(failures)))
    payload: dict[str, Any] = {
        "schema_version": "1",
        "status": "ready" if not failed_controls else "blocked",
        "repository": desired.repository_identity.full_name,
        "observed_default_branch_sha": observed_sha,
        "observed_repository_visibility": str(repository.get("visibility", "unknown")),
        "checked_controls": tuple(checked),
        "failed_controls": failed_controls,
        "heavy_workflow_inventory": heavy_inventory,
        "active_heavy_run_inventory": active_runs,
        "unmanaged_active_heavy_run_ids": tuple(sorted(set(unmanaged_ids))),
        "request_actor_permissions": dict(request_actor),
        "actions_zero_spend_budgets": tuple(normalized_budgets),
        "actions_billing_usage_snapshot": dict(storage),
        "free_artifact_storage_headroom": artifact_headroom,
        "free_cache_storage_headroom": cache_headroom,
        "repository_cache_storage_limit_gb": cache_limit if isinstance(cache_limit, int) else None,
        "repository_cache_retention_days": cache_retention if isinstance(cache_retention, int) else None,
        "projected_campaign_artifact_bytes": storage.get("projected_campaign_artifact_bytes") if numeric_storage else None,
        "projected_campaign_cache_bytes": storage.get("projected_campaign_cache_bytes") if numeric_storage else None,
        "local_agent_actor": local_actor,
        "local_agent_has_admin": local_admin,
        "auditor_installation_proof": auditor_proof,
        "observer_context": observer_context,
        "audit_use_context": audit_context,
        "observed_at": observed_at,
        "github_api_observed_at": github_at,
        "source_snapshot_sha256": source_snapshot_sha256,
    }
    hash_payload = {
        key: (value.isoformat().replace("+00:00", "Z") if isinstance(value, datetime) else value)
        for key, value in payload.items()
    }
    payload["receipt_sha256"] = _sha256(hash_payload)
    if observer_context == "github_auditor":
        return AuditorCatalogGithubControlsReceiptV1.model_validate(payload)
    return BootstrapCatalogGithubControlsReceiptV1.model_validate(payload)


def build_github_controls_mutation_plan(
    *,
    desired: CatalogGithubControlsV1,
    receipt: CatalogGithubControlsReceiptV1,
) -> CatalogGithubControlsMutationPlanV1:
    """Create an ordered data-only plan; this function can never mutate GitHub."""

    repository = desired.repository_identity.full_name
    failures = set(receipt.failed_controls)
    mutations: list[GithubControlMutationV1] = []

    groups: tuple[tuple[set[str], str, str, Mapping[str, object]], ...] = (
        (
            {
                "MAIN_ADMINS_ENFORCED",
                "MAIN_PULL_REQUEST_REQUIRED",
                "MAIN_APPROVAL_POLICY_EXACT",
                "MAIN_STRICT_STATUS_CHECKS_REQUIRED",
                "MAIN_STATUS_CHECKS_EXACT",
                "MAIN_CONVERSATIONS_MUST_RESOLVE",
                "MAIN_LINEAR_HISTORY_REQUIRED",
                "MAIN_FORCE_PUSH_FORBIDDEN",
                "MAIN_DELETE_FORBIDDEN",
            },
            "PUT",
            f"/repos/{repository}/branches/{desired.default_branch}/protection",
            {
                "required_status_checks": {
                    "strict": desired.branch_protection.strict_status_checks,
                    "contexts": list(
                        desired.branch_protection.required_status_checks
                    ),
                },
                "enforce_admins": desired.branch_protection.enforce_admins,
                "required_pull_request_reviews": {
                    "dismiss_stale_reviews": (
                        desired.branch_protection.dismiss_stale_reviews
                    ),
                    "require_code_owner_reviews": (
                        desired.branch_protection.require_code_owner_reviews
                    ),
                    "required_approving_review_count": (
                        desired.branch_protection.required_approving_review_count
                    ),
                    "require_last_push_approval": (
                        desired.branch_protection.require_last_push_approval
                    ),
                },
                "restrictions": None,
                "required_linear_history": (
                    desired.branch_protection.required_linear_history
                ),
                "allow_force_pushes": (
                    desired.branch_protection.allow_force_pushes
                ),
                "allow_deletions": desired.branch_protection.allow_deletions,
                "required_conversation_resolution": (
                    desired.branch_protection.required_conversation_resolution
                ),
            },
        ),
        (
            {"DEFAULT_TOKEN_READ_ONLY", "ACTIONS_PR_APPROVAL_FORBIDDEN"},
            "PUT",
            f"/repos/{repository}/actions/permissions/workflow",
            {
                "default_workflow_permissions": desired.actions.default_workflow_permissions,
                "can_approve_pull_request_reviews": desired.actions.can_approve_pull_request_reviews,
            },
        ),
        (
            {"CATALOG_ENVIRONMENT_REQUIRED", "CATALOG_ENVIRONMENT_MAIN_ONLY"},
            "PUT",
            f"/repos/{repository}/environments/{desired.environment.name}",
            {
                "wait_timer": 0,
                "prevent_self_review": False,
                "reviewers": [],
                "deployment_branch_policy": {
                    "protected_branches": True,
                    "custom_branch_policies": False,
                },
            },
        ),
    )
    for reasons, method, endpoint, body in groups:
        matched = tuple(sorted(reasons & failures))
        if matched:
            mutations.append(
                GithubControlMutationV1(
                    order=len(mutations) + 1,
                    method=method,
                    endpoint=endpoint,
                    body=body,
                    reason_codes=matched,
                )
            )
    if "CATALOG_TERMINAL_LABEL_REQUIRED" in failures:
        mutations.append(
            GithubControlMutationV1(
                order=len(mutations) + 1,
                method="POST",
                endpoint=f"/repos/{repository}/labels",
                body=desired.issue_labels.terminal.model_dump(mode="json"),
                reason_codes=(
                    "CATALOG_TERMINAL_LABEL_EXACT",
                    "CATALOG_TERMINAL_LABEL_REQUIRED",
                ),
            )
        )
    elif "CATALOG_TERMINAL_LABEL_EXACT" in failures:
        mutations.append(
            GithubControlMutationV1(
                order=len(mutations) + 1,
                method="PATCH",
                endpoint=(
                    f"/repos/{repository}/labels/"
                    f"{desired.issue_labels.terminal.name}"
                ),
                body=desired.issue_labels.terminal.model_dump(mode="json"),
                reason_codes=("CATALOG_TERMINAL_LABEL_EXACT",),
            )
        )
    if "FREE_CACHE_STORAGE_LIMIT_REQUIRED" in failures:
        mutations.append(
            GithubControlMutationV1(
                order=len(mutations) + 1,
                method="PUT",
                endpoint=f"/repos/{repository}/actions/cache/storage-limit",
                body={
                    "max_cache_size_gb": (
                        desired.billing.repository_cache_storage_limit_gb
                    )
                },
                reason_codes=("FREE_CACHE_STORAGE_LIMIT_REQUIRED",),
            )
        )
    if "CACHE_RETENTION_POLICY_REQUIRED" in failures:
        mutations.append(
            GithubControlMutationV1(
                order=len(mutations) + 1,
                method="PUT",
                endpoint=f"/repos/{repository}/actions/cache/retention-limit",
                body={
                    "max_cache_retention_days": (
                        desired.billing.repository_cache_retention_days
                    )
                },
                reason_codes=("CACHE_RETENTION_POLICY_REQUIRED",),
            )
        )
    budget_failures = {
        "ZERO_ACTIONS_SPEND_BUDGET_REQUIRED",
        "ZERO_ACTIONS_STORAGE_BUDGET_REQUIRED",
        "ZERO_CACHE_STORAGE_BUDGET_REQUIRED",
        "ZERO_BUDGET_REPOSITORY_SCOPE_EXACT",
        "ZERO_ACTIONS_SPEND_STOP_REQUIRED",
        "ZERO_BUDGET_DETAIL_CROSSCHECK_REQUIRED",
    }
    if failures & budget_failures:
        for budget in desired.billing.required_zero_budgets:
            mutations.append(
                GithubControlMutationV1(
                    order=len(mutations) + 1,
                    method="POST",
                    endpoint=(
                        f"/enterprises/{desired.billing.budget_control_plane.enterprise_slug}/"
                        "settings/billing/budgets"
                    ),
                    body=budget.model_dump(mode="json"),
                    reason_codes=tuple(sorted(failures & budget_failures)),
                )
            )

    plan_payload = {
        "schema_version": "1",
        "repository": repository,
        "current_receipt_sha256": receipt.receipt_sha256,
        "mutations": tuple(item.model_dump(mode="json") for item in mutations),
    }
    return CatalogGithubControlsMutationPlanV1(
        **plan_payload,
        plan_sha256=_sha256(plan_payload),
    )


__all__ = [
    "AUDITOR_CALLER_TOPOLOGY",
    "AUDITOR_SECRET_CONSUMER",
    "AuditorCatalogGithubControlsReceiptV1",
    "BootstrapCatalogGithubControlsReceiptV1",
    "CatalogGithubAuditorV1",
    "CatalogGithubControlsMutationPlanV1",
    "CatalogGithubControlsReceiptV1",
    "CatalogGithubControlsV1",
    "GithubControlMutationV1",
    "audit_catalog_github_controls",
    "build_github_controls_mutation_plan",
    "inventory_heavy_workflows",
    "jobs_with_issues_write",
    "load_catalog_github_auditor",
    "load_catalog_github_controls",
]
