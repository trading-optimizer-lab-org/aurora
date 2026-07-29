"""Preflight validation and immutable contract freezing for future runs."""

from __future__ import annotations

import hashlib
import importlib.resources
import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
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


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
FRAMEWORK_WORKFLOW = "./.github/workflows/_aurora-future-run-v3.yml"
FRAMEWORK_WORKFLOW_PATH = ".github/workflows/_aurora-future-run-v3.yml"
HEAVY_WORKFLOW_MARKERS = (
    "backtest",
    "research",
    "optim",
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


def load_legacy_workflow_allowlist(
    path: Path | None = None,
) -> dict[str, str]:
    """Load and validate the immutable adoption-time workflow hashes."""

    if path is None:
        payload = _package_json("config/legacy_workflow_allowlist.json")
    else:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1":
        raise ValueError("legacy workflow allowlist schema is unsupported")
    adoption_commit = payload.get("adoption_commit")
    if (
        not isinstance(adoption_commit, str)
        or not FULL_SHA_RE.fullmatch(adoption_commit)
    ):
        raise ValueError("legacy workflow adoption commit is invalid")
    rows = payload.get("workflows")
    if not isinstance(rows, list):
        raise ValueError("legacy workflow allowlist rows are missing")
    allowlist: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("legacy workflow allowlist row is invalid")
        workflow_path = row.get("path")
        digest = row.get("sha256")
        if (
            not isinstance(workflow_path, str)
            or not workflow_path.startswith(".github/workflows/")
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise ValueError("legacy workflow allowlist entry is invalid")
        if workflow_path in allowlist:
            raise ValueError("duplicate legacy workflow allowlist path")
        allowlist[workflow_path] = digest
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
            or not workflow_path.startswith(".github/workflows/")
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
        ".github/workflows/github-performance-merge-only.yml",
        ".github/workflows/github-performance-replan.yml",
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
    return any(marker in searchable for marker in HEAVY_WORKFLOW_MARKERS)


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
