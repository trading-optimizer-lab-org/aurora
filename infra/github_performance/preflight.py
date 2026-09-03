"""Preflight validation and immutable contract freezing for future runs."""

from __future__ import annotations

import hashlib
import importlib.resources
import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from aurora.infra.github_performance.contracts import (
    CapacityProfile,
    PerformanceContract,
    PreflightReport,
    RunSpec,
    RuntimeEvidence,
    Violation,
    canonical_sha256,
    deep_thaw_json,
)
from aurora.infra.sp500_megarun.catalog_campaign_registry import (
    CatalogCampaignRegistryV1,
)


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
FRAMEWORK_WORKFLOW = "./.github/workflows/_aurora-future-run-v3.yml"
FRAMEWORK_WORKFLOW_PATH = ".github/workflows/_aurora-future-run-v3.yml"
GITHUB_WORKFLOW_DIRECTORY_PREFIX = ".github" + "/workflows/"
HEAVY_WORKFLOW_MARKERS = (
    "backtest",
    "research",
    # Match complete optimization terms.  The shorter ``optim`` substring
    # also matches the repository owner in protected checkout URLs.
    "optimize",
    "optimized",
    "optimization",
    "robust",
    "sweep",
    "search",
    "campaign",
    "nightly",
    "mass-download",
    "mass_download",
    "merge-group",
    "merge_group",
    "run-shard",
    "run_shard",
    "fanout",
)
DERIVED_EVIDENCE_PATHS = (
    ("identity", "code_sha", "code_sha", "CODE_SHA_MISMATCH"),
    (
        "identity",
        "workflow_sha256",
        "workflow_sha256",
        "WORKFLOW_SHA256_MISMATCH",
    ),
    ("policy", "policy_hash", "policy_hash", "POLICY_HASH_MISMATCH"),
    (
        "execution",
        "dependency_lock_sha256",
        "dependency_lock_sha256",
        "DEPENDENCY_LOCK_SHA256_MISMATCH",
    ),
    (
        "execution",
        "environment_sha256",
        "environment_sha256",
        "ENVIRONMENT_SHA256_MISMATCH",
    ),
    (
        "performance",
        "capacity_profile_sha256",
        "capacity_profile_sha256",
        "CAPACITY_PROFILE_SHA256_MISMATCH",
    ),
    (
        "data",
        "manifest_sha256",
        "data_manifest_sha256",
        "DATA_MANIFEST_SHA256_MISMATCH",
    ),
    ("data", "snapshot_hash", "snapshot_hash", "SNAPSHOT_HASH_MISMATCH"),
    (
        "metrics",
        "contract_sha256",
        "metric_contract_sha256",
        "METRIC_CONTRACT_SHA256_MISMATCH",
    ),
)
USER_OWNED_REQUIRED_PATHS = (
    ("identity", "campaign_id"),
    ("identity", "run_type"),
    ("identity", "code_ref"),
    ("identity", "workflow"),
    ("identity", "deadline_utc"),
    ("objective", "description"),
    ("objective", "success_criteria"),
    ("objective", "negative_result_criteria"),
    ("objective", "technical_failure_criteria"),
    ("policy", "train_start"),
    ("policy", "train_end"),
    ("policy", "validation_start"),
    ("policy", "validation_end"),
    ("policy", "locked_start"),
    ("policy", "decision_timezone"),
    ("policy", "decision_timestamp_rule"),
    ("policy", "execution_timestamp_rule"),
    ("policy", "market_calendar"),
    ("data", "manifest"),
    ("data", "schema_version"),
    ("data", "max_date"),
    ("data", "required_datasets"),
    ("data", "total_return_policy"),
    ("data", "corporate_actions_policy"),
    ("data", "delisting_policy"),
    ("data", "fx_policy"),
    ("data", "cash_yield_policy"),
    ("execution", "shard_seed_formula"),
    ("execution", "python_version"),
    ("execution", "runner_image"),
    ("artifacts", "final_name"),
    ("metrics", "contract_path"),
    ("metrics", "return_type"),
    ("metrics", "return_basis"),
    ("metrics", "annualization_rule"),
    ("metrics", "risk_free_source"),
    ("metrics", "undefined_metric_policy"),
)


class PreflightError(RuntimeError):
    """Raised when immutable runtime evidence conflicts with the request."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class DuplicateYamlKey(ValueError):
    """Raised for ambiguous YAML mappings."""


class GitHubSafeLoader(yaml.SafeLoader):
    """YAML loader with GitHub-compatible booleans and duplicate detection."""


GitHubSafeLoader.yaml_implicit_resolvers = deepcopy(
    yaml.SafeLoader.yaml_implicit_resolvers
)
for first_character, resolvers in GitHubSafeLoader.yaml_implicit_resolvers.items():
    GitHubSafeLoader.yaml_implicit_resolvers[first_character] = [
        pair for pair in resolvers if pair[0] != "tag:yaml.org,2002:bool"
    ]
GitHubSafeLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def _construct_unique_mapping(
    loader: GitHubSafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    output: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in output:
            line = key_node.start_mark.line + 1
            raise DuplicateYamlKey(f"duplicate key {key!r} at line {line}")
        output[key] = loader.construct_object(value_node, deep=deep)
    return output


GitHubSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _package_text(relative_path: str) -> str:
    root = importlib.resources.files("aurora")
    return root.joinpath(*relative_path.split("/")).read_text(encoding="utf-8")


def _package_json(relative_path: str) -> dict[str, Any]:
    payload = json.loads(_package_text(relative_path))
    if not isinstance(payload, dict):
        raise TypeError(f"{relative_path} must contain a JSON object")
    return payload


def _load_yaml_mapping(path: Path) -> Mapping[str, Any]:
    payload = yaml.load(path.read_text(encoding="utf-8"), Loader=GitHubSafeLoader)
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a YAML mapping")
    return payload


def load_github_yaml(path: Path) -> Mapping[str, Any]:
    """Load one workflow without YAML-1.1 corrupting the `on` key."""

    return _load_yaml_mapping(Path(path))


def _get(payload: Mapping[str, Any], path: Sequence[str]) -> Any:
    value: Any = payload
    for component in path:
        if not isinstance(value, Mapping) or component not in value:
            return None
        value = value[component]
    return value


def _violation(
    code: str,
    path: Sequence[str],
    message: str,
    severity: str = "error",
) -> Violation:
    return Violation(
        code=code,
        path=".".join(path),
        message=message,
        severity=severity,
    )


def _semantic_violations(payload: Mapping[str, Any]) -> list[Violation]:
    violations: list[Violation] = []
    for path in USER_OWNED_REQUIRED_PATHS:
        value = _get(payload, path)
        if value is None or value == "" or value == [] or value == {}:
            violations.append(
                _violation("REQUIRED_VALUE_EMPTY", path, "required value is empty")
            )
    if _get(payload, ("execution", "local_runs_allowed")) is not False:
        violations.append(
            _violation(
                "LOCAL_EXECUTION_ALLOWED",
                ("execution", "local_runs_allowed"),
                "future runs must execute in GitHub Actions",
            )
        )
    if _get(payload, ("performance", "larger_runners_allowed")) is not False:
        violations.append(
            _violation(
                "LARGER_RUNNER_FORBIDDEN",
                ("performance", "larger_runners_allowed"),
                "only standard runners are allowed",
            )
        )
    planner_max = _get(payload, ("performance", "planner_max_jobs"))
    if not isinstance(planner_max, int) or planner_max > 360:
        violations.append(
            _violation(
                "CONCURRENCY_CEILING_EXCEEDED",
                ("performance", "planner_max_jobs"),
                "planner_max_jobs must not exceed 360",
            )
        )
    matrix_max = _get(payload, ("performance", "matrix_max_jobs"))
    execution_matrix_max = _get(payload, ("execution", "max_matrix_jobs"))
    if matrix_max != 256 or execution_matrix_max != 256:
        violations.append(
            _violation(
                "MATRIX_CEILING_INVALID",
                ("performance", "matrix_max_jobs"),
                "matrix ceilings must equal the confirmed limit of 256",
            )
        )
    if _get(payload, ("policy", "locked_opened")) is not False:
        violations.append(
            _violation(
                "LOCKED_OPENED",
                ("policy", "locked_opened"),
                "locked data must remain closed",
            )
        )
    if _get(payload, ("policy", "validation_used_for_selection")) is not False:
        violations.append(
            _violation(
                "VALIDATION_USED_FOR_SELECTION",
                ("policy", "validation_used_for_selection"),
                "validation must remain report-only",
            )
        )
    violations.extend(_date_violations(payload))
    return violations


def _date_violations(payload: Mapping[str, Any]) -> list[Violation]:
    names = ("train_start", "train_end", "validation_start", "validation_end", "locked_start")
    parsed: dict[str, date] = {}
    violations: list[Violation] = []
    for name in names:
        raw = _get(payload, ("policy", name))
        if not isinstance(raw, str) or not raw:
            continue
        try:
            parsed[name] = date.fromisoformat(raw)
        except ValueError:
            violations.append(
                _violation("DATE_INVALID", ("policy", name), "date must be ISO YYYY-MM-DD")
            )
    if len(parsed) == len(names):
        periods_are_strict = (
            parsed["train_start"] < parsed["train_end"]
            < parsed["validation_start"] < parsed["validation_end"]
            < parsed["locked_start"]
        )
        if not periods_are_strict:
            violations.append(
                _violation(
                    "PERIOD_ORDER_INVALID",
                    ("policy",),
                    "train, validation, and locked periods must be strictly ordered",
                )
            )
        if parsed["validation_end"] >= parsed["locked_start"]:
            violations.append(
                _violation(
                    "LOCKED_BOUNDARY_INVALID",
                    ("policy", "locked_start"),
                    "locked must begin after validation",
                )
            )
    max_date = _get(payload, ("data", "max_date"))
    validation_end = parsed.get("validation_end")
    if isinstance(max_date, str) and max_date and validation_end is not None:
        try:
            if date.fromisoformat(max_date) > validation_end:
                violations.append(
                    _violation(
                        "DATA_AFTER_VALIDATION",
                        ("data", "max_date"),
                        "input data extends beyond validation",
                    )
                )
        except ValueError:
            violations.append(
                _violation("DATE_INVALID", ("data", "max_date"), "date must be ISO YYYY-MM-DD")
            )
    return violations


def validate_run_spec(spec_path: Path) -> PreflightReport:
    """Validate syntax, schema, hard policy, capacity, and user-owned values."""

    violations: list[Violation] = []
    try:
        payload = _load_yaml_mapping(Path(spec_path))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return PreflightReport(
            valid=False,
            spec_hash=None,
            violations=(
                _violation("SPEC_PARSE_FAILED", (), str(exc)),
            ),
        )
    schema = _package_json("config/schemas/github_run_spec_v3.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path)):
        violations.append(
            _violation(
                "SCHEMA_VALIDATION",
                tuple(str(component) for component in error.path),
                error.message,
            )
        )
    violations.extend(_semantic_violations(payload))
    profile = CapacityProfile.model_validate(
        _package_json("config/github_capacity_profile.json")
    )
    if profile.standard_concurrency_ceiling != 360 or profile.matrix_job_ceiling != 256:
        violations.append(
            _violation(
                "CAPACITY_PROFILE_INVALID",
                ("performance",),
                "packaged capacity profile does not match confirmed limits",
            )
        )
    spec_hash: str | None = None
    try:
        spec_hash = canonical_sha256(payload)
    except (TypeError, ValueError):
        violations.append(
            _violation("SPEC_NOT_CANONICAL", (), "spec cannot be encoded as canonical JSON")
        )
    valid = not any(item.severity == "error" for item in violations)
    return PreflightReport(
        valid=valid,
        spec_hash=spec_hash,
        violations=tuple(violations),
    )


def resolve_run_spec(
    requested: RunSpec,
    runtime_evidence: RuntimeEvidence,
) -> RunSpec:
    """Fill blank derived fields and reject conflicting supplied evidence."""

    payload = deep_thaw_json(requested)
    evidence = deep_thaw_json(runtime_evidence)
    for section, field, evidence_field, mismatch_code in DERIVED_EVIDENCE_PATHS:
        requested_value = payload[section][field]
        observed_value = evidence[evidence_field]
        if requested_value not in ("", observed_value):
            raise PreflightError(
                mismatch_code,
                f"{section}.{field} conflicts with observed runtime evidence",
            )
        payload[section][field] = observed_value
    return RunSpec.model_validate(payload)


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(deep_thaw_json(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def write_preflight_report(
    report: PreflightReport,
    output_dir: Path,
) -> Path:
    return _write_json(Path(output_dir) / "preflight_report.json", report)


def freeze_resolved_contract(
    spec: RunSpec,
    runtime_evidence: RuntimeEvidence,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Write the only spec and performance contract accepted downstream."""

    resolved = resolve_run_spec(spec, runtime_evidence)
    resolved_hash = canonical_sha256(resolved)
    performance = resolved.performance
    execution = resolved.execution
    policy = resolved.policy
    data = resolved.data
    metrics = resolved.metrics
    identity = resolved.identity
    contract = PerformanceContract(
        resolved_spec_sha256=resolved_hash,
        code_sha=identity["code_sha"],
        workflow_sha256=identity["workflow_sha256"],
        policy_hash=policy["policy_hash"],
        snapshot_hash=data["snapshot_hash"],
        data_manifest_sha256=data["manifest_sha256"],
        metric_contract_sha256=metrics["contract_sha256"],
        dependency_lock_sha256=execution["dependency_lock_sha256"],
        capacity_profile_sha256=performance["capacity_profile_sha256"],
        environment_sha256=execution["environment_sha256"],
        standard_runner_only=performance["runner_label"] == "ubuntu-24.04",
        locked_opened=policy["locked_opened"],
        validation_used_for_selection=policy["validation_used_for_selection"],
        larger_runners_allowed=performance["larger_runners_allowed"],
        artifact_transport_mode=performance["transport_mode"],
        planner_min_jobs=performance["planner_min_jobs"],
        planner_max_jobs=performance["planner_max_jobs"],
        planner_job_count_search=performance["planner_job_count_search"],
        planner_large_unit_threshold=performance["planner_large_unit_threshold"],
        planner_exact_lpt_candidates_max=performance[
            "planner_exact_lpt_candidates_max"
        ],
        matrix_job_ceiling=performance["matrix_max_jobs"],
        standard_concurrency_ceiling=performance[
            "confirmed_standard_concurrency"
        ],
        runner_label=performance["runner_label"],
        max_memory_pct=resolved.resources["max_memory_pct"],
        min_free_disk_gb=resolved.resources["min_free_disk_gb"],
        merge_fan_in=performance["merge_fan_in"],
        target_setup_fraction_max=performance["target_setup_fraction_max"],
        target_checkpoint_fraction_max=performance[
            "target_checkpoint_fraction_max"
        ],
    )
    root = Path(output_dir)
    resolved_path = _write_json(root / "resolved_run_spec.json", resolved)
    contract_path = _write_json(root / "performance_contract.json", contract)
    return resolved_path, contract_path


def _iter_uses(workflow: Mapping[str, Any]) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, Mapping):
        return output
    for job_name, job in jobs.items():
        if not isinstance(job, Mapping):
            continue
        if isinstance(job.get("uses"), str):
            output.append((f"jobs.{job_name}.uses", job["uses"]))
        steps = job.get("steps", ())
        if not isinstance(steps, Sequence) or isinstance(steps, str):
            continue
        for index, step in enumerate(steps):
            if isinstance(step, Mapping) and isinstance(step.get("uses"), str):
                output.append((f"jobs.{job_name}.steps.{index}.uses", step["uses"]))
    return output


CATALOG_CONTROLLER_WORKFLOW = ".github/workflows/catalog-run-controller.yml"
CATALOG_FAST_CONTROLLER_WORKFLOW = ".github/workflows/catalog-fast-controller.yml"
CATALOG_PREPARATION_WORKFLOW = ".github/workflows/catalog-prepare-one.yml"
CATALOG_RECOVERY_WORKFLOW = ".github/workflows/catalog-recovery-wave.yml"
CATALOG_WATCHDOG_WORKFLOW = ".github/workflows/catalog-run-watchdog.yml"
CATALOG_KEEPER_WORKFLOW = ".github/workflows/catalog-artifact-keeper.yml"
CATALOG_LIVE_AUDIT_ACTION = ".github/actions/catalog-live-controls-audit/action.yml"
CATALOG_KEEPER_AUDIT_CONTEXT_SHA256 = (
    "0b90c2b50f081b48eb3b173b907eab0015973e536db2e8e195ff8f95b69bec42"
)
CATALOG_LIVE_AUDIT_CALLERS = frozenset(
    {
        (
            ".github/workflows/catalog-run-controller.yml",
            "live_controls_audit_before_reserve",
            "admission",
        ),
        (
            ".github/workflows/catalog-run-controller.yml",
            "live_controls_audit_before_terminal",
            "terminal",
        ),
        (
            ".github/workflows/catalog-live-controls-qualification.yml",
            "qualify_live_admission_controls",
            "admission",
        ),
        (
            ".github/workflows/catalog-live-controls-qualification.yml",
            "qualify_live_terminal_controls",
            "terminal",
        ),
        (
            CATALOG_KEEPER_WORKFLOW,
            "live_controls_audit_before_maintenance",
            "maintenance",
        ),
    }
)
CATALOG_LIVE_AUDIT_CREDENTIAL_NAMES = frozenset(
    {
        "AURORA_CATALOG_AUDITOR_APP_ID",
        "AURORA_CATALOG_AUDITOR_PRIVATE_KEY",
        "AURORA_CATALOG_ENTERPRISE_BILLING_TOKEN",
        "AURORA_CATALOG_ENTERPRISE_CACHE_VERIFIER_TOKEN",
        "AURORA_CATALOG_PACKAGE_INVENTORY_TOKEN",
    }
)
CATALOG_ACTIVE_ENGINE_WORKFLOWS = {
    "optimized_catalog_v1": ".github/workflows/catalog-optimized-run.yml",
}
CATALOG_PRODUCTION_WORKER_WORKFLOWS = frozenset(
    {
        ".github/workflows/catalog-component-worker.yml",
        ".github/workflows/catalog-optimized-worker.yml",
        CATALOG_RECOVERY_WORKFLOW,
    }
)
CATALOG_LEGACY_INACTIVE_WORKFLOWS = frozenset(
    {
        ".github/workflows/sp500-atlas-calibration.yml",
        ".github/workflows/sp500-atlas-controller.yml",
        ".github/workflows/sp500-atlas-pilot.yml",
        ".github/workflows/sp500-atlas-postrun.yml",
        ".github/workflows/sp500-atlas-run.yml",
        ".github/workflows/sp500-atlas-segment.yml",
        ".github/workflows/sp500-catalog-optimization-qualification.yml",
        ".github/workflows/sp500-strategy-catalog-overnight.yml",
    }
)
CATALOG_NONPRODUCTION_TRIGGER_EXEMPTIONS = frozenset(
    {
        ".github/workflows/catalog-controller-policy-check.yml",
        ".github/workflows/catalog-controller-qualification.yml",
        ".github/workflows/catalog-live-controls-qualification.yml",
        ".github/workflows/catalog-capacity-calibration.yml",
        CATALOG_KEEPER_WORKFLOW,
        ".github/workflows/catalog-future-architecture.yml",
    }
)
CATALOG_SEALED_IDENTIFIERS = frozenset(
    {
        "request_sha256",
        "authority_id",
        "campaign_id",
        "science_sha256",
        "execution_plan_sha256",
        "execution_protocol_sha256",
        "protected_commit_sha",
        "decision_sha256",
    }
)
_CATALOG_PUBLIC_HEAVY_TRIGGERS = frozenset(
    {
        "workflow_dispatch",
        "schedule",
        "repository_dispatch",
        "push",
        "pull_request",
        "pull_request_target",
        "issues",
        "issue_comment",
    }
)
_CATALOG_HEAVY_EXECUTABLE_MARKERS = (
    "build_sp500_component_store",
    "run_catalog_recipe_worker_guarded",
    "run_sp500_optimized_recipe_worker",
    "reduce_sp500_optimized_catalog_run",
    "run_sp500_strategy_catalog_shard",
    "run_sp500_atlas_worker",
    "reduce_sp500_atlas_run",
    "merge_sp500_atlas",
    "benchmark_catalog_scale",
    "catalog-optimized-run.yml",
    "catalog-component-worker.yml",
    "catalog-optimized-worker.yml",
)
_CATALOG_NESTED_DISPATCH_MARKERS = (
    "gh workflow run",
    "/dispatches",
    "repository_dispatch",
)
_CATALOG_UNTRUSTED_ISSUE_EXPRESSIONS = (
    "github.event.issue.body",
    "github.event.issue.title",
    "github.event.issue.user",
    "github.event.issue.labels",
)


@dataclass(frozen=True)
class CatalogWorkflowTopologyItemV1:
    path: str
    triggers: tuple[str, ...]
    heavy: bool
    role: str
    engine_id: str | None
    callers: tuple[str, ...]
    workflow_call_inputs: tuple[str, ...]


@dataclass(frozen=True)
class CatalogWorkflowTopologyReceiptV1:
    status: str
    inventory: tuple[CatalogWorkflowTopologyItemV1, ...]
    violations: tuple[Violation, ...]
    inventory_sha256: str
    receipt_sha256: str


def _catalog_workflow_triggers(workflow: Mapping[str, Any]) -> tuple[str, ...]:
    event = workflow.get("on", {})
    if isinstance(event, str):
        return (event,)
    if isinstance(event, Sequence) and not isinstance(event, (str, bytes)):
        return tuple(sorted(str(item) for item in event))
    if isinstance(event, Mapping):
        return tuple(sorted(str(item) for item in event))
    return ()


def _catalog_workflow_call_inputs(workflow: Mapping[str, Any]) -> tuple[str, ...]:
    event = workflow.get("on", {})
    if not isinstance(event, Mapping):
        return ()
    call = event.get("workflow_call", {})
    if not isinstance(call, Mapping):
        return ()
    inputs = call.get("inputs", {})
    if not isinstance(inputs, Mapping):
        return ()
    return tuple(sorted(str(item) for item in inputs))


def _catalog_executable_text(workflow: Mapping[str, Any]) -> str:
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, Mapping):
        return ""
    values: list[str] = []
    for job in jobs.values():
        if not isinstance(job, Mapping):
            continue
        if isinstance(job.get("uses"), str):
            values.append(job["uses"])
        for step in job.get("steps", ()):
            if not isinstance(step, Mapping):
                continue
            for key in ("uses", "run"):
                if isinstance(step.get(key), str):
                    values.append(step[key])
    return "\n".join(values).casefold()


def _catalog_role(
    path: str,
    workflow: Mapping[str, Any],
    engine_by_path: Mapping[str, str],
) -> tuple[bool, str, str | None]:
    if path == CATALOG_KEEPER_WORKFLOW:
        return True, "keeper_maintenance", None
    if path in engine_by_path:
        return True, "active_engine", engine_by_path[path]
    if path in CATALOG_PRODUCTION_WORKER_WORKFLOWS:
        return True, "production_worker", "optimized_catalog_v1"
    if path in CATALOG_LEGACY_INACTIVE_WORKFLOWS:
        return True, "inactive_legacy", None
    executable = _catalog_executable_text(workflow)
    heavy = any(marker in executable for marker in _CATALOG_HEAVY_EXECUTABLE_MARKERS)
    if not heavy:
        return False, "control_or_lightweight", None
    if path in CATALOG_NONPRODUCTION_TRIGGER_EXEMPTIONS:
        return True, "nonproduction_qualification", None
    return True, "inactive_helper", None


def _catalog_local_workflow_target(value: str) -> str | None:
    local_prefix = "./.github" + "/workflows/"
    if not value.startswith(local_prefix):
        return None
    if "${{" in value or "@" in value:
        return None
    return value[2:]


def _catalog_violation(code: str, path: str, message: str) -> Violation:
    return _violation(code, (path,), message)


def _catalog_canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _catalog_job_needs(job: Mapping[str, Any]) -> set[str]:
    needs = job.get("needs", ())
    if isinstance(needs, str):
        return {needs}
    if isinstance(needs, Sequence) and not isinstance(needs, (str, bytes)):
        return {str(item) for item in needs}
    return set()


def _validate_catalog_live_audit_topology(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    repo_root: Path,
) -> list[Violation]:
    governed_callers = {
        path for path, _job, _purpose in CATALOG_LIVE_AUDIT_CALLERS
    }
    if not governed_callers.intersection(documents):
        return []

    violations: list[Violation] = []
    action_path = repo_root / CATALOG_LIVE_AUDIT_ACTION
    try:
        action = load_github_yaml(action_path)
    except (OSError, ValueError, TypeError):
        action = {}
    expected_inputs = {
        "purpose",
        "caller-workflow",
        "caller-job",
        "protected-commit-sha",
        "audit-context-sha256",
        "qualification-replay-directory",
        "auditor-app-id",
        "auditor-private-key",
        "enterprise-billing-token",
        "enterprise-cache-verifier-token",
        "package-inventory-token",
    }
    expected_outputs = {
        "receipt_artifact_name",
        "receipt_sha256",
        "receipt_status",
    }
    runs = action.get("runs") if isinstance(action, Mapping) else None
    if (
        not isinstance(action, Mapping)
        or set(action.get("inputs", {})) != expected_inputs
        or set(action.get("outputs", {})) != expected_outputs
        or not isinstance(runs, Mapping)
        or runs.get("using") != "composite"
    ):
        violations.append(
            _catalog_violation(
                "CATALOG_LIVE_AUDIT_CONTRACT_INVALID",
                CATALOG_LIVE_AUDIT_ACTION,
                "the protected composite auditor contract is missing or open-ended",
            )
        )

    steps = runs.get("steps") if isinstance(runs, Mapping) else None
    step_rows = (
        list(steps)
        if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes))
        else []
    )
    provenance = step_rows[0] if step_rows and isinstance(step_rows[0], Mapping) else None
    provenance_run = str(provenance.get("run", "")) if provenance else ""
    provenance_env = provenance.get("env") if provenance else None
    required_provenance_env = {
        "EXPECTED_PURPOSE": "${{ inputs.purpose }}",
        "EXPECTED_CALLER_WORKFLOW": "${{ inputs.caller-workflow }}",
        "EXPECTED_CALLER_JOB": "${{ inputs.caller-job }}",
        "EXPECTED_PROTECTED_COMMIT_SHA": "${{ inputs.protected-commit-sha }}",
        "EXPECTED_AUDIT_CONTEXT_SHA256": "${{ inputs.audit-context-sha256 }}",
        "ACTUAL_WORKFLOW_REF": "${{ github.workflow_ref }}",
        "ACTUAL_WORKFLOW_SHA": "${{ github.workflow_sha }}",
        "ACTUAL_EVENT_NAME": "${{ github.event_name }}",
        "ACTUAL_REF": "${{ github.ref }}",
        "ACTUAL_SHA": "${{ github.sha }}",
        "ACTUAL_REPOSITORY": "${{ github.repository }}",
    }
    required_provenance_markers = {
        'repository="trading-optimizer-lab-org/aurora"',
        '[[ "$ACTUAL_REPOSITORY" == "$repository" ]]',
        '[[ "$EXPECTED_PROTECTED_COMMIT_SHA" =~ ^[0-9a-f]{40}$ ]]',
        '[[ "$EXPECTED_AUDIT_CONTEXT_SHA256" =~ ^[0-9a-f]{64}$ ]]',
        '[[ "$ACTUAL_WORKFLOW_SHA" == "$EXPECTED_PROTECTED_COMMIT_SHA" ]]',
        '[[ "$ACTUAL_REF" == "refs/heads/main" ]]',
        '[[ "$ACTUAL_SHA" == "$EXPECTED_PROTECTED_COMMIT_SHA" ]]',
        "catalog-run-controller.yml@refs/heads/main",
        "catalog-live-controls-qualification.yml@refs/heads/main",
        "catalog-artifact-keeper.yml@refs/heads/main",
        "catalog-run-watchdog.yml@refs/heads/main",
        "catalog-request-reconciler.yml@refs/heads/main",
        "CATALOG_AUDIT_CALLER_EVENT_INVALID",
    }
    if (
        not isinstance(provenance, Mapping)
        or provenance.get("id") != "provenance"
        or provenance.get("shell") != "bash"
        or provenance_env != required_provenance_env
        or not all(marker in provenance_run for marker in required_provenance_markers)
    ):
        violations.append(
            _catalog_violation(
                "CATALOG_LIVE_AUDIT_PROVENANCE_INCOMPLETE",
                CATALOG_LIVE_AUDIT_ACTION,
                "caller repository, commit, event, and nested provenance are not closed",
            )
        )

    required_logical_callers = {
        "admission:.github/workflows/catalog-run-controller.yml:live_controls_audit_before_reserve",
        "terminal:.github/workflows/catalog-run-controller.yml:live_controls_audit_before_terminal",
        "admission:.github/workflows/catalog-live-controls-qualification.yml:qualify_live_admission_controls",
        "terminal:.github/workflows/catalog-live-controls-qualification.yml:qualify_live_terminal_controls",
        "maintenance:.github/workflows/catalog-artifact-keeper.yml:live_controls_audit_before_maintenance",
    }
    if not all(marker in provenance_run for marker in required_logical_callers):
        violations.append(
            _catalog_violation(
                "CATALOG_LIVE_AUDIT_CALLER_JOB_NOT_VALIDATED",
                CATALOG_LIVE_AUDIT_ACTION,
                "purpose, logical caller workflow, and caller job are not bound exactly",
            )
        )

    if any(
        "${{ inputs." in str(step.get("run", ""))
        for step in step_rows
        if isinstance(step, Mapping)
    ):
        violations.append(
            _catalog_violation(
                "CATALOG_LIVE_AUDIT_INPUT_IN_SHELL",
                CATALOG_LIVE_AUDIT_ACTION,
                "action inputs must enter shell only through the environment",
            )
        )

    observed_callers: set[tuple[str, str, str]] = set()
    credential_consumers: set[tuple[str, str]] = set()
    credential_inputs = {
        "auditor-app-id": "${{ vars.AURORA_CATALOG_AUDITOR_APP_ID }}",
        "auditor-private-key": "${{ secrets.AURORA_CATALOG_AUDITOR_PRIVATE_KEY }}",
        "enterprise-billing-token": "${{ secrets.AURORA_CATALOG_ENTERPRISE_BILLING_TOKEN }}",
        "enterprise-cache-verifier-token": "${{ secrets.AURORA_CATALOG_ENTERPRISE_CACHE_VERIFIER_TOKEN }}",
        "package-inventory-token": "${{ secrets.AURORA_CATALOG_PACKAGE_INVENTORY_TOKEN }}",
    }
    target = f"./{CATALOG_LIVE_AUDIT_ACTION.removesuffix('/action.yml')}"
    for workflow_path in governed_callers:
        workflow = documents.get(workflow_path)
        if not isinstance(workflow, Mapping):
            continue
        jobs = workflow.get("jobs")
        if not isinstance(jobs, Mapping):
            continue
        for job_id, job in jobs.items():
            if not isinstance(job, Mapping):
                continue
            rendered_job = json.dumps(job, sort_keys=True)
            found_credentials = {
                name
                for name in CATALOG_LIVE_AUDIT_CREDENTIAL_NAMES
                if name in rendered_job
            }
            if found_credentials:
                credential_consumers.add((workflow_path, str(job_id)))
            job_steps = job.get("steps")
            rows = (
                list(job_steps)
                if isinstance(job_steps, Sequence)
                and not isinstance(job_steps, (str, bytes))
                else []
            )
            action_steps = [
                step
                for step in rows
                if isinstance(step, Mapping) and step.get("uses") == target
            ]
            if not action_steps:
                continue
            audit_step = action_steps[0]
            inputs = audit_step.get("with")
            purpose = inputs.get("purpose") if isinstance(inputs, Mapping) else None
            observed_callers.add((workflow_path, str(job_id), str(purpose)))
            checkout = rows[0] if rows and isinstance(rows[0], Mapping) else None
            checkout_with = checkout.get("with") if isinstance(checkout, Mapping) else None
            expected_ref = (
                inputs.get("protected-commit-sha")
                if isinstance(inputs, Mapping)
                else None
            )
            if (
                len(action_steps) != 1
                or not isinstance(inputs, Mapping)
                or inputs.get("caller-workflow") != workflow_path
                or inputs.get("caller-job") != str(job_id)
                or any(inputs.get(key) != value for key, value in credential_inputs.items())
                or job.get("environment") != "catalog-production"
                or job.get("runs-on") != "ubuntu-24.04"
                or job.get("timeout-minutes") != 30
                or job.get("permissions") != {"actions": "read", "contents": "read"}
                or not isinstance(checkout, Mapping)
                or not str(checkout.get("uses", "")).startswith("actions/checkout@")
                or not isinstance(checkout_with, Mapping)
                or checkout_with.get("ref") != expected_ref
                or checkout_with.get("persist-credentials") is not False
            ):
                violations.append(
                    _catalog_violation(
                        "CATALOG_LIVE_AUDIT_CALLER_PRIVILEGED",
                        workflow_path,
                        f"caller job {job_id} is outside the protected action envelope",
                    )
                )
    if observed_callers != set(CATALOG_LIVE_AUDIT_CALLERS):
        violations.append(
            _catalog_violation(
                "CATALOG_LIVE_AUDIT_CALLERS_INVALID",
                CATALOG_LIVE_AUDIT_ACTION,
                "the composite auditor must have exactly the five protected callers",
            )
        )
    expected_consumers = {
        (path, job) for path, job, _purpose in CATALOG_LIVE_AUDIT_CALLERS
    }
    if credential_consumers != expected_consumers:
        violations.append(
            _catalog_violation(
                "CATALOG_LIVE_AUDIT_SECRET_FANOUT",
                CATALOG_LIVE_AUDIT_ACTION,
                "auditor credentials must be referenced by exactly five protected jobs",
            )
        )
    return violations


def validate_catalog_workflow_topology(
    *, repo_root: Path, registry: CatalogCampaignRegistryV1
) -> CatalogWorkflowTopologyReceiptV1:
    """Validate the complete catalog call graph and return a sealed receipt.

    The validator deliberately uses repository paths and executable workflow
    content, never an issue-supplied workflow name.  Unknown or malformed
    catalog topology is reported as a blocking violation.
    """

    root = Path(repo_root).resolve()
    workflow_dir = root / ".github/workflows"
    violations: list[Violation] = []
    documents: dict[str, Mapping[str, Any]] = {}
    for workflow_path in sorted(workflow_dir.glob("*.y*ml")):
        relative = workflow_path.relative_to(root).as_posix()
        try:
            documents[relative] = load_github_yaml(workflow_path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            violations.append(
                _catalog_violation(
                    "CATALOG_WORKFLOW_PARSE_FAILED", relative, str(exc)
                )
            )

    violations.extend(
        _validate_catalog_live_audit_topology(documents, repo_root=root)
    )

    active_engine_ids = {
        campaign.engine_id for campaign in registry.campaigns if campaign.active
    }
    unknown_engines = active_engine_ids - set(CATALOG_ACTIVE_ENGINE_WORKFLOWS)
    for engine_id in sorted(unknown_engines):
        violations.append(
            _catalog_violation(
                "CATALOG_ENGINE_UNREGISTERED",
                engine_id,
                "active registry engine has no fixed workflow",
            )
        )
    engine_by_path = {
        path: engine_id
        for engine_id, path in CATALOG_ACTIVE_ENGINE_WORKFLOWS.items()
        if engine_id in active_engine_ids
    }

    callers: dict[str, set[str]] = {path: set() for path in documents}
    for caller_path, workflow in documents.items():
        for yaml_path, uses in _iter_uses(workflow):
            if not yaml_path.endswith(".uses") or not yaml_path.count(".steps.") == 0:
                continue
            if "${{" in uses:
                violations.append(
                    _catalog_violation(
                        "CATALOG_DYNAMIC_WORKFLOW_TARGET",
                        caller_path,
                        f"dynamic reusable workflow target at {yaml_path}",
                    )
                )
                continue
            target = _catalog_local_workflow_target(uses)
            if target is None:
                if uses.endswith((".yml", ".yaml")) or "/.github/workflows/" in uses:
                    violations.append(
                        _catalog_violation(
                            "CATALOG_REMOTE_WORKFLOW_TARGET",
                            caller_path,
                            f"remote reusable workflow target at {yaml_path}",
                        )
                    )
                continue
            if target not in documents:
                governed_reference = any(
                    marker in f"{caller_path}\n{target}".casefold()
                    for marker in ("catalog", "atlas")
                )
                if governed_reference:
                    violations.append(
                        _catalog_violation(
                            "CATALOG_LOCAL_WORKFLOW_MISSING",
                            caller_path,
                            f"missing reusable workflow {target}",
                        )
                    )
                continue
            callers[target].add(caller_path)

    items: list[CatalogWorkflowTopologyItemV1] = []
    roles: dict[str, tuple[bool, str, str | None]] = {}
    for path, workflow in documents.items():
        roles[path] = _catalog_role(path, workflow, engine_by_path)
        heavy, role, engine_id = roles[path]
        items.append(
            CatalogWorkflowTopologyItemV1(
                path=path,
                triggers=_catalog_workflow_triggers(workflow),
                heavy=heavy,
                role=role,
                engine_id=engine_id,
                callers=tuple(sorted(callers[path])),
                workflow_call_inputs=_catalog_workflow_call_inputs(workflow),
            )
        )

    for item in items:
        if not item.heavy:
            continue
        workflow = documents[item.path]
        public = set(item.triggers) & _CATALOG_PUBLIC_HEAVY_TRIGGERS
        public_entrypoint = item.path in {
            CATALOG_CONTROLLER_WORKFLOW,
            CATALOG_FAST_CONTROLLER_WORKFLOW,
            CATALOG_WATCHDOG_WORKFLOW,
            CATALOG_KEEPER_WORKFLOW,
        }
        if (
            public
            and item.path not in CATALOG_NONPRODUCTION_TRIGGER_EXEMPTIONS
            and not public_entrypoint
        ):
            violations.append(
                _catalog_violation(
                    "CATALOG_HEAVY_PUBLIC_TRIGGER",
                    item.path,
                    f"heavy catalog workflow has public triggers {sorted(public)}",
                )
            )
        if item.role in {"active_engine", "production_worker"}:
            if set(item.triggers) != {"workflow_call"}:
                violations.append(
                    _catalog_violation(
                        "CATALOG_HEAVY_NOT_WORKFLOW_CALL_ONLY",
                        item.path,
                        "production compute must be workflow_call only",
                    )
                )
            missing = CATALOG_SEALED_IDENTIFIERS - set(item.workflow_call_inputs)
            if missing:
                violations.append(
                    _catalog_violation(
                        "CATALOG_SEALED_INPUTS_MISSING",
                        item.path,
                        f"missing sealed identifiers {sorted(missing)}",
                    )
                )
            forbidden_inputs = {
                name
                for name in item.workflow_call_inputs
                if any(
                    marker in name.casefold()
                    for marker in (
                        "path",
                        "workflow",
                        "command",
                        "runner",
                        "artifact_name",
                        "data_boundary",
                    )
                )
            }
            if forbidden_inputs:
                violations.append(
                    _catalog_violation(
                        "CATALOG_ARBITRARY_ENGINE_INPUT",
                        item.path,
                        f"forbidden engine inputs {sorted(forbidden_inputs)}",
                    )
                )
            permissions = workflow.get("permissions")
            if permissions != {"actions": "read", "contents": "read"}:
                violations.append(
                    _catalog_violation(
                        "CATALOG_ENGINE_PERMISSIONS_INVALID",
                        item.path,
                        "production compute permissions must be exactly read-only",
                    )
                )
            jobs = workflow.get("jobs", {})
            if isinstance(jobs, Mapping):
                for job_id, job in jobs.items():
                    if not isinstance(job, Mapping) or "runs-on" not in job:
                        continue
                    if job.get("runs-on") != "ubuntu-24.04":
                        violations.append(
                            _catalog_violation(
                                "CATALOG_PAID_OR_UNSAFE_RUNNER",
                                item.path,
                                f"job {job_id} does not use ubuntu-24.04",
                            )
                        )
                    if job.get("environment") != "catalog-production":
                        violations.append(
                            _catalog_violation(
                                "CATALOG_ENVIRONMENT_MISSING",
                                item.path,
                                f"job {job_id} lacks catalog-production",
                            )
                        )
                    steps = job.get("steps", ())
                    checkout_refs = {
                        step.get("with", {}).get("ref")
                        for step in steps
                        if isinstance(step, Mapping)
                        and isinstance(step.get("uses"), str)
                        and step["uses"].startswith("actions/checkout@")
                        and isinstance(step.get("with"), Mapping)
                    }
                    if "${{ inputs.protected_commit_sha }}" not in checkout_refs:
                        violations.append(
                            _catalog_violation(
                                "CATALOG_PROTECTED_COMMIT_NOT_ENFORCED",
                                item.path,
                                f"job {job_id} does not check out the sealed commit",
                            )
                        )

        if item.role == "keeper_maintenance":
            event = workflow.get("on")
            if event != {
                "schedule": [{"cron": "17 3 * * 0"}],
                "workflow_dispatch": {},
            }:
                violations.append(
                    _catalog_violation(
                        "CATALOG_KEEPER_TRIGGER_INVALID",
                        item.path,
                        "keeper must have only the fixed weekly schedule and input-free manual qualification trigger",
                    )
                )
            if workflow.get("permissions") != {
                "actions": "read",
                "contents": "read",
                "issues": "read",
            }:
                violations.append(
                    _catalog_violation(
                        "CATALOG_KEEPER_PERMISSIONS_INVALID",
                        item.path,
                        "keeper top-level permissions must be exactly read-only",
                    )
                )
            if "env" in workflow:
                violations.append(
                    _catalog_violation(
                        "CATALOG_KEEPER_GLOBAL_ENV_FORBIDDEN",
                        item.path,
                        "keeper cannot receive repository-selected environment data",
                    )
                )
            jobs = workflow.get("jobs")
            required_job_ids = {
                "live_controls_audit_before_maintenance",
                "inventory_and_preserve",
            }
            if not isinstance(jobs, Mapping) or set(jobs) != required_job_ids:
                violations.append(
                    _catalog_violation(
                        "CATALOG_KEEPER_JOB_TOPOLOGY_INVALID",
                        item.path,
                        "keeper must contain only the fixed audit and preservation jobs",
                    )
                )
            else:
                audit = jobs["live_controls_audit_before_maintenance"]
                expected_audit_inputs = {
                    "purpose": "maintenance",
                    "caller-workflow": CATALOG_KEEPER_WORKFLOW,
                    "caller-job": "live_controls_audit_before_maintenance",
                    "protected-commit-sha": "${{ github.sha }}",
                    "audit-context-sha256": CATALOG_KEEPER_AUDIT_CONTEXT_SHA256,
                }
                audit_steps = audit.get("steps") if isinstance(audit, Mapping) else None
                audit_rows = (
                    list(audit_steps)
                    if isinstance(audit_steps, Sequence)
                    and not isinstance(audit_steps, (str, bytes))
                    else []
                )
                action_step = next(
                    (
                        step
                        for step in audit_rows
                        if isinstance(step, Mapping)
                        and step.get("uses")
                        == "./.github/actions/catalog-live-controls-audit"
                    ),
                    None,
                )
                action_inputs = (
                    action_step.get("with")
                    if isinstance(action_step, Mapping)
                    else None
                )
                if (
                    not isinstance(audit, Mapping)
                    or "uses" in audit
                    or audit.get("runs-on") != "ubuntu-24.04"
                    or audit.get("timeout-minutes") != 30
                    or audit.get("environment") != "catalog-production"
                    or audit.get("permissions")
                    != {"actions": "read", "contents": "read"}
                    or not isinstance(action_inputs, Mapping)
                    or any(
                        action_inputs.get(key) != value
                        for key, value in expected_audit_inputs.items()
                    )
                ):
                    violations.append(
                        _catalog_violation(
                            "CATALOG_KEEPER_AUDIT_CALL_INVALID",
                            item.path,
                            "keeper maintenance audit call is not the fixed pure call",
                        )
                    )
                preservation = jobs["inventory_and_preserve"]
                if (
                    not isinstance(preservation, Mapping)
                    or preservation.get("needs")
                    != "live_controls_audit_before_maintenance"
                    or preservation.get("runs-on") != "ubuntu-24.04"
                    or preservation.get("timeout-minutes") != 20
                    or preservation.get("permissions")
                    != {
                        "actions": "read",
                        "contents": "read",
                        "issues": "read",
                    }
                    or "environment" in preservation
                    or "secrets" in preservation
                ):
                    violations.append(
                        _catalog_violation(
                            "CATALOG_KEEPER_PRESERVATION_JOB_INVALID",
                            item.path,
                            "keeper preservation job exceeds its fixed read-only envelope",
                        )
                    )
            keeper_executable = _catalog_executable_text(workflow)
            forbidden_keeper_markers = (
                "plan_sp500_optimized_catalog_run",
                "catalog-optimized-run.yml",
                "catalog-component-worker.yml",
                "catalog-optimized-worker.yml",
                "build_sp500_component_store",
                "run_catalog_recipe_worker_guarded",
                "run_sp500_optimized_recipe_worker",
                "reduce_sp500_optimized_catalog_run",
                "catalog-recovery-wave.yml",
                "workflow_dispatch",
                "--method post",
                "--method patch",
                "--method delete",
                "-x post",
                "-x patch",
                "-x delete",
            )
            found = tuple(
                marker
                for marker in forbidden_keeper_markers
                if marker in keeper_executable
            )
            if found:
                violations.append(
                    _catalog_violation(
                        "CATALOG_KEEPER_MUTATION_OR_SCIENCE_PATH",
                        item.path,
                        f"keeper contains forbidden paths {list(found)}",
                    )
                )

        executable = _catalog_executable_text(workflow)
        if any(marker in executable for marker in _CATALOG_NESTED_DISPATCH_MARKERS):
            violations.append(
                _catalog_violation(
                    "CATALOG_NESTED_DISPATCH",
                    item.path,
                    "workflow contains a nested dispatch escape",
                )
            )
        if any(marker in executable for marker in _CATALOG_UNTRUSTED_ISSUE_EXPRESSIONS):
            violations.append(
                _catalog_violation(
                    "CATALOG_UNTRUSTED_ISSUE_DATAFLOW",
                    item.path,
                    "untrusted issue text reaches executable workflow data",
                )
            )

    for path, workflow in documents.items():
        for yaml_path, uses in _iter_uses(workflow):
            if uses.startswith("./"):
                continue
            action, separator, revision = uses.rpartition("@")
            if (
                not separator
                or not action
                or not FULL_SHA_RE.fullmatch(revision)
            ):
                if "catalog" in path or "atlas" in path:
                    violations.append(
                        _catalog_violation(
                            "CATALOG_ACTION_NOT_PINNED",
                            path,
                            f"external action at {yaml_path} is not full-SHA pinned",
                        )
                    )

        if path != CATALOG_KEEPER_WORKFLOW:
            executable = _catalog_executable_text(workflow)
            jobs = workflow.get("jobs", {})
            maintenance_call = False
            if isinstance(jobs, Mapping):
                maintenance_call = any(
                    isinstance(job, Mapping)
                    and isinstance(job.get("with"), Mapping)
                    and job["with"].get("purpose") == "maintenance"
                    for job in jobs.values()
                )
            keeper_execution = any(
                marker in executable
                for marker in (
                    "python scripts/run_catalog_artifact_keeper.py",
                    "python -m scripts.run_catalog_artifact_keeper",
                )
            )
            if maintenance_call or keeper_execution:
                violations.append(
                    _catalog_violation(
                        "CATALOG_SECOND_MAINTENANCE_PATH",
                        path,
                        "only the fixed catalog artifact keeper may run maintenance",
                    )
                )

    for engine_id in sorted(active_engine_ids):
        engine_path = CATALOG_ACTIVE_ENGINE_WORKFLOWS.get(engine_id)
        if engine_path is None or engine_path not in documents:
            violations.append(
                _catalog_violation(
                    "CATALOG_ENGINE_WORKFLOW_MISSING",
                    engine_id,
                    "active engine workflow is missing",
                )
            )
            continue
        allowed_callers = {
            CATALOG_CONTROLLER_WORKFLOW,
            CATALOG_FAST_CONTROLLER_WORKFLOW,
            CATALOG_PREPARATION_WORKFLOW,
            CATALOG_RECOVERY_WORKFLOW,
        }
        actual_callers = callers[engine_path]
        if not actual_callers or not actual_callers <= allowed_callers:
            violations.append(
                _catalog_violation(
                    "CATALOG_ENGINE_CALLER_INVALID",
                    engine_path,
                    f"engine callers are {sorted(actual_callers)}",
                )
            )
        engine = documents[engine_path]
        engine_jobs = engine.get("jobs", {})
        engine_text = json.dumps(
            engine,
            sort_keys=True,
            separators=(",", ":"),
        ).casefold()
        if (
            not isinstance(engine_jobs, Mapping)
            or engine_text.count("build the one locked runtime store") != 1
        ):
            violations.append(
                _catalog_violation(
                    "CATALOG_RUNTIME_ONCE_INVARIANT_MISSING",
                    engine_path,
                    "active engine must prepare one exact runtime at most once",
                )
            )
            continue
        component_jobs = {
            str(job_id): job
            for job_id, job in engine_jobs.items()
            if isinstance(job, Mapping)
            and job.get("uses")
            == "./.github/workflows/catalog-component-worker.yml"
        }
        recipe_jobs = {
            str(job_id): job
            for job_id, job in engine_jobs.items()
            if isinstance(job, Mapping)
            and job.get("uses")
            == "./.github/workflows/catalog-optimized-worker.yml"
        }
        verifier = engine_jobs.get("verify_component_store")
        group_reducer = engine_jobs.get("reduce_groups")
        final_reducer = engine_jobs.get("reduce")
        if (
            not component_jobs
            or not recipe_jobs
            or not isinstance(verifier, Mapping)
            or not set(component_jobs).issubset(_catalog_job_needs(verifier))
            or any(
                "prepare_runtime_and_inputs" not in _catalog_job_needs(job)
                for job in component_jobs.values()
            )
            or any(
                "verify_component_store" not in _catalog_job_needs(job)
                for job in recipe_jobs.values()
            )
        ):
            violations.append(
                _catalog_violation(
                    "CATALOG_COMPONENTS_BEFORE_RECIPES_INVARIANT_MISSING",
                    engine_path,
                    "active engine does not seal global components before recipes",
                )
            )
        required_routes = {
            "worker_id",
            "descriptor_bundle_artifact",
            "descriptor_member",
            "descriptor_sha256",
        }
        if any(
            not isinstance(job.get("with"), Mapping)
            or not required_routes.issubset(job["with"])
            for job in (*component_jobs.values(), *recipe_jobs.values())
        ):
            violations.append(
                _catalog_violation(
                    "CATALOG_EXACT_PAYLOAD_ROUTE_INVARIANT_MISSING",
                    engine_path,
                    "active engine workers lack compact exact payload routes",
                )
            )
        if (
            not isinstance(group_reducer, Mapping)
            or not isinstance(group_reducer.get("strategy"), Mapping)
            or group_reducer["strategy"].get("max-parallel", 16) > 15
            or "reduction_matrix"
            not in str(group_reducer["strategy"].get("matrix", ""))
            or not isinstance(final_reducer, Mapping)
            or "reduce_groups" not in _catalog_job_needs(final_reducer)
            or "reduction_artifact_pattern"
            not in json.dumps(final_reducer, sort_keys=True)
            or "catalog-checkpoint-*"
            in json.dumps(final_reducer, sort_keys=True).casefold()
        ):
            violations.append(
                _catalog_violation(
                    "CATALOG_BOUNDED_REDUCTION_INVARIANT_MISSING",
                    engine_path,
                    "active engine does not use sealed bounded reduction groups",
                )
            )

        worker = documents.get(".github/workflows/catalog-optimized-worker.yml")
        if not isinstance(worker, Mapping):
            violations.append(
                _catalog_violation(
                    "CATALOG_RECIPE_WORKER_MISSING",
                    engine_path,
                    "active engine recipe worker is missing",
                )
            )
        else:
            worker_text = json.dumps(worker, sort_keys=True).casefold()
            evaluate = worker.get("jobs", {}).get("evaluate", {})
            steps = evaluate.get("steps", ()) if isinstance(evaluate, Mapping) else ()
            compute_steps = {
                str(step.get("id")): step
                for step in steps
                if isinstance(step, Mapping)
                and str(step.get("id", "")).startswith("compute_")
            }
            upload_steps = {
                str(step.get("id")): step
                for step in steps
                if isinstance(step, Mapping)
                and str(step.get("id", "")).startswith("upload_")
            }
            durable_chain = any(
                isinstance(step, Mapping) and step.get("id") == "durable_chain"
                for step in steps
            )
            checkpoint_chain_valid = (
                set(compute_steps) == {f"compute_{slot}" for slot in range(1, 9)}
                and set(upload_steps)
                == {f"upload_{slot}" for slot in range(1, 9)}
                and durable_chain
                and all(
                    f"steps.upload_{slot - 1}.outputs['artifact-id'] != ''"
                    in str(compute_steps[f"compute_{slot}"].get("if", ""))
                    and f"steps.upload_{slot - 1}.outputs['artifact-digest'] != ''"
                    in str(compute_steps[f"compute_{slot}"].get("if", ""))
                    for slot in range(2, 9)
                )
            )
            component_escape = any(
                marker in worker_text
                for marker in (
                    "build-component",
                    "compute-component",
                    "component fallback",
                    "allow-component-miss",
                )
            )
            if component_escape or not checkpoint_chain_valid:
                violations.append(
                    _catalog_violation(
                        "CATALOG_SELECTIVE_RECOVERY_INVARIANT_MISSING",
                        engine_path,
                        "active engine worker has a component escape or unsafe checkpoints",
                    )
                )

    worker_allowed_callers = {
        ".github/workflows/catalog-optimized-run.yml",
        CATALOG_RECOVERY_WORKFLOW,
    }
    for worker_path in sorted(CATALOG_PRODUCTION_WORKER_WORKFLOWS & documents.keys()):
        if not callers[worker_path] or not callers[worker_path] <= worker_allowed_callers:
            violations.append(
                _catalog_violation(
                    "CATALOG_WORKER_CALLER_INVALID",
                    worker_path,
                    f"worker callers are {sorted(callers[worker_path])}",
                )
            )

    ordered_items = tuple(sorted(items, key=lambda item: item.path))
    inventory_payload = [asdict(item) for item in ordered_items]
    inventory_sha256 = _catalog_canonical_hash(inventory_payload)
    ordered_violations = tuple(
        sorted(violations, key=lambda item: (item.code, item.path, item.message))
    )
    receipt_status: str = "ready" if not ordered_violations else "blocked"
    receipt_payload = {
        "status": receipt_status,
        "inventory_sha256": inventory_sha256,
        "violations": [item.model_dump(mode="json") for item in ordered_violations],
    }
    return CatalogWorkflowTopologyReceiptV1(
        status=receipt_status,
        inventory=ordered_items,
        violations=ordered_violations,
        inventory_sha256=inventory_sha256,
        receipt_sha256=_catalog_canonical_hash(receipt_payload),
    )


def load_legacy_workflow_allowlist(
    path: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, str]:
    """Load immutable workflow hashes from original and authorized adoptions."""

    if path is None:
        payload = _package_json("config/legacy_workflow_allowlist.json")
        root = Path.cwd() if repo_root is None else Path(repo_root)
    else:
        allowlist_path = Path(path)
        payload = json.loads(allowlist_path.read_text(encoding="utf-8"))
        root = (
            Path(repo_root)
            if repo_root is not None
            else allowlist_path.resolve().parents[1]
        )
    schema_version = payload.get("schema_version")
    if schema_version not in {"1", "2"}:
        raise ValueError("legacy workflow allowlist schema is unsupported")
    adoption_commit = payload.get("adoption_commit")
    if (
        not isinstance(adoption_commit, str)
        or not FULL_SHA_RE.fullmatch(adoption_commit)
    ):
        raise ValueError("legacy workflow adoption commit is invalid")
    authorized_adoptions: dict[str, tuple[int, str]] = {}
    if schema_version == "2":
        adoption_rows = payload.get("authorized_adoptions")
        if not isinstance(adoption_rows, list) or not adoption_rows:
            raise ValueError("authorized workflow adoptions are missing")
        for adoption in adoption_rows:
            if not isinstance(adoption, Mapping):
                raise ValueError("authorized workflow adoption is invalid")
            commit = adoption.get("adoption_commit")
            workflow_count = adoption.get("workflow_count")
            workflows_sha256 = adoption.get("workflows_sha256")
            authorization = adoption.get("authorization_receipt")
            if (
                not isinstance(commit, str)
                or not FULL_SHA_RE.fullmatch(commit)
                or commit == adoption_commit
                or not isinstance(workflow_count, int)
                or isinstance(workflow_count, bool)
                or workflow_count <= 0
                or not isinstance(workflows_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", workflows_sha256)
                or not isinstance(authorization, Mapping)
                or commit in authorized_adoptions
            ):
                raise ValueError("authorized workflow adoption is invalid")
            receipt_path = authorization.get("path")
            receipt_sha256 = authorization.get("sha256")
            actor_id = authorization.get("actor_id")
            scope = authorization.get("scope")
            if (
                not isinstance(receipt_path, str)
                or not receipt_path.startswith("docs/readiness/")
                or not isinstance(receipt_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", receipt_sha256)
                or not isinstance(actor_id, str)
                or not actor_id
                or not isinstance(scope, str)
                or not scope
            ):
                raise ValueError("workflow adoption authorization is invalid")
            receipt = (root.resolve() / receipt_path).resolve()
            if not receipt.is_relative_to(root.resolve()) or not receipt.is_file():
                raise ValueError("workflow adoption receipt is unavailable")
            receipt_bytes = receipt.read_bytes().replace(b"\r\n", b"\n").replace(
                b"\r", b"\n"
            )
            if hashlib.sha256(receipt_bytes).hexdigest() != receipt_sha256:
                raise ValueError("workflow adoption receipt digest mismatches")
            receipt_payload = json.loads(receipt_bytes)
            scopes = receipt_payload.get("authorization_scope")
            if (
                receipt_payload.get("accepted") is not True
                or receipt_payload.get("baseline_commit_sha") != commit
                or receipt_payload.get("owner_actor_id") != actor_id
                or receipt_payload.get("adopted_workflow_count") != workflow_count
                or receipt_payload.get("adopted_workflows_sha256")
                != workflows_sha256
                or receipt_payload.get("preserves_future_framework_enforcement")
                is not True
                or not isinstance(scopes, list)
                or scope not in scopes
            ):
                raise ValueError("workflow adoption receipt binding is invalid")
            authorized_adoptions[commit] = (workflow_count, workflows_sha256)
    elif "authorized_adoptions" in payload:
        raise ValueError("authorized workflow adoptions require schema 2")
    rows = payload.get("workflows")
    if not isinstance(rows, list):
        raise ValueError("legacy workflow allowlist rows are missing")
    allowlist: dict[str, str] = {}
    adopted_rows: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("legacy workflow allowlist row is invalid")
        workflow_path = row.get("path")
        digest = row.get("sha256")
        row_adoption_commit = row.get("adoption_commit", adoption_commit)
        if (
            not isinstance(workflow_path, str)
            or not workflow_path.startswith(GITHUB_WORKFLOW_DIRECTORY_PREFIX)
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not isinstance(row_adoption_commit, str)
            or not FULL_SHA_RE.fullmatch(row_adoption_commit)
            or (
                row_adoption_commit != adoption_commit
                and row_adoption_commit not in authorized_adoptions
            )
        ):
            raise ValueError("legacy workflow allowlist entry is invalid")
        if workflow_path in allowlist:
            raise ValueError("duplicate legacy workflow allowlist path")
        allowlist[workflow_path] = digest
        if row_adoption_commit != adoption_commit:
            adopted_rows.setdefault(row_adoption_commit, []).append(
                {"path": workflow_path, "sha256": digest}
            )
    if set(adopted_rows) != set(authorized_adoptions):
        raise ValueError("authorized workflow adoption rows mismatch")
    for commit, (expected_count, expected_digest) in authorized_adoptions.items():
        adopted = sorted(adopted_rows[commit], key=lambda item: item["path"])
        if (
            len(adopted) != expected_count
            or _catalog_canonical_hash(adopted) != expected_digest
        ):
            raise ValueError("authorized workflow adoption digest mismatches")
    return allowlist


def load_legacy_workflow_migrations(
    path: Path | None = None,
    repo_root: Path | None = None,
) -> dict[str, dict[str, str]]:
    """Load explicit, receipt-bound changes to frozen legacy workflows."""

    if path is None:
        payload = _package_json("config/legacy_workflow_migrations.json")
        root = Path.cwd() if repo_root is None else Path(repo_root)
    else:
        migration_path = Path(path)
        payload = json.loads(migration_path.read_text(encoding="utf-8"))
        root = (
            Path(repo_root)
            if repo_root is not None
            else migration_path.resolve().parents[1]
        )
    if payload.get("schema_version") != "1":
        raise ValueError("legacy workflow migration schema is unsupported")
    authorization = payload.get("authorization_receipt")
    if not isinstance(authorization, Mapping):
        raise ValueError("legacy workflow migration authorization is missing")
    receipt_path = authorization.get("path")
    receipt_digest = authorization.get("sha256")
    actor_id = authorization.get("actor_id")
    scope = authorization.get("scope")
    if (
        not isinstance(receipt_path, str)
        or not receipt_path.startswith("docs/readiness/")
        or not isinstance(receipt_digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", receipt_digest)
        or not isinstance(actor_id, str)
        or not actor_id
        or not isinstance(scope, str)
        or not scope
    ):
        raise ValueError("legacy workflow migration authorization is invalid")
    receipt = (root.resolve() / receipt_path).resolve()
    if not receipt.is_relative_to(root.resolve()) or not receipt.is_file():
        raise ValueError("legacy workflow migration receipt is unavailable")
    receipt_bytes = receipt.read_bytes()
    canonical_receipt = receipt_bytes.replace(b"\r\n", b"\n").replace(
        b"\r", b"\n"
    )
    if hashlib.sha256(canonical_receipt).hexdigest() != receipt_digest:
        raise ValueError("legacy workflow migration receipt digest mismatches")

    rows = payload.get("migrations")
    if not isinstance(rows, list):
        raise ValueError("legacy workflow migration rows are missing")
    migrations: dict[str, dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("legacy workflow migration row is invalid")
        workflow_path = row.get("path")
        previous_digest = row.get("previous_sha256")
        replacement_digest = row.get("replacement_sha256")
        reason = row.get("reason")
        if (
            not isinstance(workflow_path, str)
            or not workflow_path.startswith(GITHUB_WORKFLOW_DIRECTORY_PREFIX)
            or not isinstance(previous_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", previous_digest)
            or not isinstance(replacement_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", replacement_digest)
            or previous_digest == replacement_digest
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ValueError("legacy workflow migration entry is invalid")
        if workflow_path in migrations:
            raise ValueError("duplicate legacy workflow migration path")
        migrations[workflow_path] = {
            "previous_sha256": previous_digest,
            "replacement_sha256": replacement_digest,
            "reason": reason,
            "authorization_actor_id": actor_id,
            "authorization_scope": scope,
            "authorization_receipt_path": receipt_path,
            "authorization_receipt_sha256": receipt_digest,
        }
    return migrations


def classify_workflow(
    path: Path,
    allowlist: Mapping[str, str],
    repo_root: Path | None = None,
    migrations: Mapping[str, Mapping[str, str]] | None = None,
) -> str:
    """Classify a workflow by path and canonical repository bytes.

    Git stores text workflows with LF line endings, while a Windows checkout
    may materialize the same file with CRLF. Normalize line endings only; every
    other byte remains covered by the adoption digest.
    """

    workflow_path = Path(path).resolve()
    root = (
        Path(repo_root).resolve()
        if repo_root is not None
        else workflow_path.parents[2]
    )
    try:
        relative = workflow_path.relative_to(root).as_posix()
    except ValueError:
        relative = workflow_path.as_posix()
    expected = allowlist.get(relative)
    if expected is None:
        return "future"
    workflow_bytes = workflow_path.read_bytes()
    canonical_bytes = workflow_bytes.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    observed = hashlib.sha256(canonical_bytes).hexdigest()
    if observed == expected:
        return "legacy"
    migration = (migrations or {}).get(relative)
    if (
        migration is not None
        and migration.get("previous_sha256") == expected
        and migration.get("replacement_sha256") == observed
    ):
        return "migrated_legacy"
    return "modified_legacy"


def _iter_scalar_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        output: list[str] = []
        for child in value.values():
            output.extend(_iter_scalar_strings(child))
        return output
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        output = []
        for child in value:
            output.extend(_iter_scalar_strings(child))
        return output
    return []


def _calls_future_framework(workflow: Mapping[str, Any]) -> bool:
    return any(
        uses == FRAMEWORK_WORKFLOW
        for _, uses in _iter_uses(workflow)
    )


FRAMEWORK_INTERNAL_WORKFLOW_PATHS = frozenset(
    {
        ".github/workflows/_aurora-merge-level-v3.yml",
        ".github/workflows/_aurora-recovery-plan-v3.yml",
        ".github/workflows/_aurora-retry-shard-v3.yml",
        ".github/workflows/gtbi-v7-new-reference-worker.yml",
        ".github/workflows/github-performance-merge-only.yml",
        ".github/workflows/github-performance-replan.yml",
        # Serial read-only control-plane inventory. It is intentionally not a
        # scientific workload and cannot use the sharded research framework.
        ".github/workflows/aurora-maintenance-inventory.yml",
    }
)


def _is_heavy_workflow(
    workflow: Mapping[str, Any],
    path: Path,
) -> bool:
    if _calls_future_framework(workflow):
        return True
    jobs = workflow.get("jobs", {})
    if isinstance(jobs, Mapping):
        for job in jobs.values():
            if not isinstance(job, Mapping):
                continue
            strategy = job.get("strategy")
            if isinstance(strategy, Mapping) and (
                "matrix" in strategy or "max-parallel" in strategy
            ):
                return True
            timeout = job.get("timeout-minutes")
            if isinstance(timeout, (int, float)) and timeout > 60:
                return True
    searchable = " ".join(
        [Path(path).name, *_iter_scalar_strings(jobs)]
    ).lower()
    return any(
        re.search(
            rf"(?<![A-Za-z0-9]){re.escape(marker)}(?![A-Za-z0-9])",
            searchable,
        )
        for marker in HEAVY_WORKFLOW_MARKERS
    )


def validate_workflow_policy(
    path: Path,
    repo_root: Path,
    allowlist: Mapping[str, str] | None = None,
    migrations: Mapping[str, Mapping[str, str]] | None = None,
) -> list[Violation]:
    """Apply grandfathering and the future heavy-workflow framework rule."""

    active_allowlist = (
        dict(allowlist)
        if allowlist is not None
        else load_legacy_workflow_allowlist()
    )
    classification = classify_workflow(
        path,
        active_allowlist,
        repo_root,
        migrations,
    )
    if classification in {"legacy", "migrated_legacy"}:
        return []
    if classification == "modified_legacy":
        return [
            _violation(
                "LEGACY_WORKFLOW_MODIFIED",
                (),
                "legacy workflow bytes changed after framework adoption",
            )
        ]
    violations = validate_future_workflow(path, repo_root)
    try:
        workflow = load_github_yaml(Path(path))
    except (OSError, ValueError, yaml.YAMLError):
        return violations
    relative = Path(path).resolve().relative_to(
        Path(repo_root).resolve()
    ).as_posix()
    if (
        relative != FRAMEWORK_WORKFLOW_PATH
        and relative not in FRAMEWORK_INTERNAL_WORKFLOW_PATHS
        and _is_heavy_workflow(workflow, path)
        and not _calls_future_framework(workflow)
    ):
        violations.append(
            _violation(
                "FUTURE_HEAVY_WORKFLOW_BYPASSES_FRAMEWORK",
                ("jobs",),
                "new heavy workflows must call _aurora-future-run-v3.yml",
            )
        )
    return violations


def validate_future_workflow(
    path: Path,
    repo_root: Path,
) -> list[Violation]:
    """Statically validate one newly introduced or modified heavy workflow."""

    try:
        workflow = load_github_yaml(Path(path))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [_violation("WORKFLOW_PARSE_FAILED", (), str(exc))]
    violations: list[Violation] = []
    uses_entries = _iter_uses(workflow)
    heavy = _is_heavy_workflow(workflow, path)
    action_lock = _package_json("config/official_actions_lock.json")
    for yaml_path, uses in uses_entries:
        if uses.startswith("./"):
            root = Path(repo_root).resolve()
            target = (root / uses[2:]).resolve()
            if not target.is_relative_to(root):
                violations.append(
                    _violation(
                        "LOCAL_REFERENCE_OUTSIDE_REPO",
                        tuple(yaml_path.split(".")),
                        f"local reference escapes the repository: {uses}",
                    )
                )
                continue
            reference_exists = target.is_file() or (
                target.is_dir()
                and (
                    (target / "action.yml").is_file()
                    or (target / "action.yaml").is_file()
                )
            )
            if not reference_exists:
                violations.append(
                    _violation(
                        "LOCAL_REFERENCE_MISSING",
                        tuple(yaml_path.split(".")),
                        f"local action or workflow does not exist: {uses}",
                    )
                )
            continue
        if uses.startswith("docker://"):
            violations.append(
                _violation(
                    "ACTION_NOT_PINNED",
                    tuple(yaml_path.split(".")),
                    "container actions are not allowed in future heavy workflows",
                )
            )
            continue
        action, separator, revision = uses.rpartition("@")
        if not separator or not FULL_SHA_RE.fullmatch(revision):
            violations.append(
                _violation(
                    "ACTION_NOT_PINNED",
                    tuple(yaml_path.split(".")),
                    f"external action must use a full commit SHA: {uses}",
                )
            )
            continue
        approved = action_lock.get(action)
        if approved is not None and revision != approved:
            violations.append(
                _violation(
                    "ACTION_SHA_NOT_APPROVED",
                    tuple(yaml_path.split(".")),
                    f"{action} does not match config/official_actions_lock.json",
                )
            )
    triggers = workflow.get("on", {})
    if isinstance(triggers, str):
        trigger_names = {triggers}
    elif isinstance(triggers, Sequence) and not isinstance(triggers, str):
        trigger_names = set(triggers)
    elif isinstance(triggers, Mapping):
        trigger_names = set(triggers)
    else:
        trigger_names = set()
    if heavy and trigger_names.intersection({"push", "pull_request"}):
        violations.append(
            _violation(
                "HEAVY_AUTOMATIC_TRIGGER",
                ("on",),
                "heavy future workflows must be manual or reusable",
            )
        )
    jobs = workflow.get("jobs", {})
    if isinstance(jobs, Mapping):
        for name, job in jobs.items():
            if not isinstance(job, Mapping) or "runs-on" not in job:
                continue
            if job["runs-on"] != "ubuntu-24.04":
                violations.append(
                    _violation(
                        "NONSTANDARD_RUNNER",
                        ("jobs", str(name), "runs-on"),
                        "future workflows must use ubuntu-24.04 standard runners",
                    )
                )
    return violations
