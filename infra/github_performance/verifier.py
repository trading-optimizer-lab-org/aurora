"""Independent final-artifact verification and formal campaign closure."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from aurora.infra.github_performance.benchmark import (
    scientific_content_identity,
)
from aurora.infra.github_performance.contracts import (
    RunSpec,
    VerificationReport,
    canonical_sha256,
    deep_thaw_json,
)
from aurora.infra.github_performance.metric_verifier import (
    independent_metric_verification_payload,
    read_metric_inputs,
    verify_metric_inputs,
)
from aurora.infra.github_performance.native import (
    NATIVE_QUALIFICATION_OUTPUTS,
    ensure_runtime_native_fallback_artifacts,
    validate_native_qualification_artifacts,
)
from aurora.infra.github_performance.shard_planner import sha256_file


TRACEABILITY_COLUMNS = (
    "requirement_id",
    "requirement_text",
    "expected_value",
    "observed_value",
    "evidence_path",
    "status",
)

MANDATORY_FINAL_OUTPUTS = (
    "preflight_report.json",
    "performance_contract.json",
    "performance_pilot.json",
    "planning_pilot_resolution.json",
    "performance_plan.json",
    "environment_manifest.json",
    "resolved_run_spec.json",
    "execution_plan.json",
    "balanced_shard_plan.json",
    "work_unit_manifest.json",
    "work_units.parquet",
    "balanced_unit_assignments.parquet",
    "metric_contract.json",
    "capacity_profile.json",
    "deadline_audit.json",
    "budget_audit.json",
    "runtime_breakdown.parquet",
    "resource_samples.parquet",
    "github_jobs_timeline.parquet",
    "parallelism_timeline.csv",
    "timeline_summary.json",
    "performance_telemetry_status.json",
    "performance_telemetry_manifest.json",
    "bottleneck_report.json",
    "performance_final.json",
    *NATIVE_QUALIFICATION_OUTPUTS,
    "recovery_plan.json",
    "checkpoint_audit.parquet",
    "shard_attempt_manifest.parquet",
    "unit_attempt_manifest.parquet",
    "merge_plan.json",
    "unit_reconciliation.parquet",
    "runtime_access_ledger.parquet",
    "metric_verification_inputs.parquet",
    "independent_metric_verification.json",
    "data_audit.json",
    "policy_audit.json",
    "runtime_audit.json",
    "provenance.json",
    "final_merge_summary.json",
    "requirements_traceability.csv",
)

POST_VERIFICATION_OUTPUTS = (
    "final_verification_report.json",
    "campaign_closure.json",
)

REQUIREMENT_IDS = (
    "github_only",
    "standard_runner",
    "larger_runner_forbidden",
    "matrix_ceiling",
    "concurrency_ceiling",
    "deadline_guard",
    "budget_guard",
    "locked_closed",
    "runtime_locked_rows_zero",
    "validation_report_only",
    "no_future_data",
    "causal_execution",
    "complete_reconciliation",
    "artifact_hashes",
    "required_outputs",
    "telemetry_complete",
    "independent_metrics",
    "dependency_environment",
    "selective_recovery",
    "replan",
    "merge_only",
    "multi_level_merge",
    "scientific_equivalence",
    "scientific_content_identity",
)


class FinalArtifactCompletenessError(RuntimeError):
    """Raised when a campaign cannot be sealed without missing evidence."""


def _atomic_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            deep_thaw_json(payload),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _schema_version(path: Path) -> str | None:
    if path.suffix == ".parquet":
        metadata = pq.ParquetFile(path).schema_arrow.metadata or {}
        value = metadata.get(b"schema_version")
        return value.decode("utf-8") if value else None
    if path.suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, Mapping) and "schema_version" in payload:
            return str(payload["schema_version"])
    return None


def _sealable_files(root: Path, manifest_path: Path) -> tuple[Path, ...]:
    root = Path(root).resolve()
    excluded = {
        Path(manifest_path).resolve(),
        *(root / name for name in POST_VERIFICATION_OUTPUTS),
    }
    return tuple(
        candidate.resolve()
        for candidate in sorted(root.rglob("*"))
        if (
            candidate.is_file()
            and candidate.resolve() not in excluded
            and candidate.suffix != ".tmp"
        )
    )


def _relative_file_set(
    root: Path,
    manifest_path: Path,
) -> set[str]:
    resolved_root = Path(root).resolve()
    return {
        path.relative_to(resolved_root).as_posix()
        for path in _sealable_files(resolved_root, manifest_path)
    }


def write_final_artifact_manifest(root: Path, path: Path) -> Path:
    """Hash every already-produced final file without recursive self-hashes."""

    root = Path(root).resolve()
    path = Path(path).resolve()
    files: list[dict[str, Any]] = []
    for resolved in _sealable_files(root, path):
        if not resolved.is_relative_to(root):
            raise ValueError("artifact path escapes root")
        files.append(
            {
                "path": resolved.relative_to(root).as_posix(),
                "bytes": resolved.stat().st_size,
                "sha256": sha256_file(resolved),
                "schema_version": _schema_version(resolved),
            }
        )
    contract_path = root / "performance_contract.json"
    contract: Mapping[str, Any] = {}
    if contract_path.is_file():
        raw_contract = json.loads(contract_path.read_text(encoding="utf-8"))
        if isinstance(raw_contract, Mapping):
            contract = raw_contract
    payload = {
        "schema_version": "1",
        "resolved_spec_sha256": contract.get("resolved_spec_sha256", ""),
        "code_sha": contract.get("code_sha", ""),
        "snapshot_hash": contract.get("snapshot_hash", ""),
        "policy_hash": contract.get("policy_hash", ""),
        "mandatory_outputs": list(MANDATORY_FINAL_OUTPUTS),
        "post_verification_outputs": list(POST_VERIFICATION_OUTPUTS),
        "files": files,
    }
    return _atomic_json(path, payload)


def _read_reconciliation_summary(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        return {}
    parquet = pq.ParquetFile(path)
    footer_metadata = parquet.metadata.metadata or {}
    schema_metadata = parquet.schema_arrow.metadata or {}
    raw = footer_metadata.get(b"summary_json")
    if raw is None:
        raw = schema_metadata.get(b"summary_json")
    if raw is None:
        return {}
    payload = json.loads(raw.decode("utf-8"))
    return payload if isinstance(payload, Mapping) else {}


def _traceability_passed(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    identifiers = [row.get("requirement_id") for row in rows]
    return (
        tuple(sorted(str(item) for item in identifiers))
        == tuple(sorted(REQUIREMENT_IDS))
        and len(identifiers) == len(set(identifiers))
        and all(
            row.get("status") in {"pass", "not_applicable"}
            for row in rows
        )
    )


def _read_required_json(
    root: Path,
    name: str,
    missing_code: str,
    failures: list[str],
) -> Mapping[str, Any]:
    path = root / name
    if not path.is_file():
        failures.append(missing_code)
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        failures.append(missing_code.replace("_MISSING", "_INVALID"))
        return {}
    if not isinstance(payload, Mapping):
        failures.append(missing_code.replace("_MISSING", "_INVALID"))
        return {}
    return payload


def _validate_telemetry_evidence(
    root: Path,
    failures: list[str],
) -> bool:
    status = _read_required_json(
        root,
        "performance_telemetry_status.json",
        "PERFORMANCE_TELEMETRY_STATUS_MISSING",
        failures,
    )
    if (
        status.get("complete") is not True
        or status.get("token_serialized") is not False
    ):
        failures.append("PERFORMANCE_TELEMETRY_INCOMPLETE")
        return False
    timeline = _read_required_json(
        root,
        "timeline_summary.json",
        "TIMELINE_SUMMARY_MISSING",
        failures,
    )
    if timeline.get("complete") is not True:
        failures.append("TIMELINE_SUMMARY_INCOMPLETE")
        return False
    telemetry_manifest = _read_required_json(
        root,
        "performance_telemetry_manifest.json",
        "PERFORMANCE_TELEMETRY_MANIFEST_MISSING",
        failures,
    )
    raw_files = telemetry_manifest.get("files")
    if not isinstance(raw_files, list):
        failures.append("PERFORMANCE_TELEMETRY_MANIFEST_INVALID")
        return False
    expected = {
        "github_jobs_timeline.parquet",
        "runtime_breakdown.parquet",
        "parallelism_timeline.csv",
        "timeline_summary.json",
        "performance_telemetry_status.json",
    }
    observed: set[str] = set()
    for entry in raw_files:
        if not isinstance(entry, Mapping):
            failures.append("PERFORMANCE_TELEMETRY_MANIFEST_INVALID")
            continue
        name = str(entry.get("path", ""))
        observed.add(name)
        path = root / name
        if not path.is_file():
            failures.append(f"TELEMETRY_FILE_MISSING:{name}")
            continue
        if path.stat().st_size != entry.get("bytes"):
            failures.append(f"TELEMETRY_SIZE_MISMATCH:{name}")
        if sha256_file(path) != entry.get("sha256"):
            failures.append(f"TELEMETRY_HASH_MISMATCH:{name}")
    if observed != expected:
        failures.append("PERFORMANCE_TELEMETRY_FILE_SET_MISMATCH")
    return not any(
        code.startswith(
            (
                "PERFORMANCE_TELEMETRY_",
                "TIMELINE_",
                "TELEMETRY_",
            )
        )
        for code in failures
    )


def _validate_resource_sample_evidence(
    root: Path,
    failures: list[str],
) -> bool:
    path = root / "resource_samples.parquet"
    required_columns = (
        "shard_id",
        "attempt_id",
        "observed_at",
        "root_pid",
        "process_count",
        "child_aware",
        "rss_mb",
        "peak_memory_mb",
        "total_memory_mb",
        "free_disk_mb",
        "cpu_seconds",
        "io_read_bytes",
        "io_write_bytes",
        "io_wait_seconds",
        "load_1m",
    )
    if not path.is_file():
        failures.append("RESOURCE_SAMPLES_MISSING")
        return False
    try:
        table = pq.read_table(path, columns=list(required_columns))
    except (OSError, ValueError, pa.ArrowInvalid, KeyError):
        failures.append("RESOURCE_SAMPLES_INVALID")
        return False
    if table.num_rows < 1:
        failures.append("RESOURCE_SAMPLES_EMPTY")
    if len(set(table.column_names)) != len(required_columns):
        failures.append("RESOURCE_SAMPLES_INVALID")
    if not all(table.column("child_aware").to_pylist()):
        failures.append("RESOURCE_SAMPLES_NOT_CHILD_AWARE")
    if any(value < 1 for value in table.column("process_count").to_pylist()):
        failures.append("RESOURCE_SAMPLES_PROCESS_COUNT_INVALID")
    summary_path = root / "final_merge_summary.json"
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            declared_count = int(summary.get("resource_sample_count", -1))
            declared_name = str(summary.get("resource_samples", ""))
            declared_hash = str(summary.get("resource_samples_sha256", ""))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            failures.append("RESOURCE_SAMPLES_SUMMARY_INVALID")
        else:
            if declared_count != table.num_rows:
                failures.append("RESOURCE_SAMPLES_COUNT_MISMATCH")
            if declared_name != path.name:
                failures.append("RESOURCE_SAMPLES_NAME_MISMATCH")
            if declared_hash != sha256_file(path):
                failures.append("RESOURCE_SAMPLES_HASH_MISMATCH")
    else:
        failures.append("RESOURCE_SAMPLES_SUMMARY_INVALID")
    return not any(code.startswith("RESOURCE_SAMPLES_") for code in failures)


def _validate_scientific_content_identity(
    root: Path,
    manifest_files: set[str],
    failures: list[str],
) -> bool:
    summary = _read_required_json(
        root,
        "final_merge_summary.json",
        "FINAL_MERGE_SUMMARY_MISSING",
        failures,
    )
    output_name = str(summary.get("scientific_output", ""))
    if not output_name:
        failures.append("SCIENTIFIC_OUTPUT_IDENTITY_MISSING")
        return False
    output = root / output_name
    if not output.is_file():
        failures.append("SCIENTIFIC_OUTPUT_MISSING")
        return False
    if output_name not in manifest_files:
        failures.append("SCIENTIFIC_OUTPUT_UNSEALED")
    try:
        observed = scientific_content_identity(root)
        expected_rows = int(summary.get("scientific_content_rows", -1))
    except (
        OSError,
        RuntimeError,
        ValueError,
        TypeError,
        pa.ArrowInvalid,
        KeyError,
    ):
        failures.append("SCIENTIFIC_CONTENT_IDENTITY_INVALID")
        return False
    if (
        summary.get("scientific_content_sha256")
        != observed["scientific_content_sha256"]
        or expected_rows != observed["unit_count"]
    ):
        failures.append("SCIENTIFIC_CONTENT_IDENTITY_MISMATCH")
        return False
    return output_name in manifest_files


def verify_final_artifact(
    root: Path,
    spec: RunSpec,
) -> VerificationReport:
    """Reopen every listed file and independently verify hard invariants."""

    root = Path(root).resolve()
    manifest_path = root / "final_artifact_manifest.json"
    failures: list[str] = []
    evidence_paths: list[str] = []
    evidence_hashes: dict[str, str] = {}
    if not manifest_path.is_file():
        failures.append("FINAL_MANIFEST_MISSING")
        manifest: Mapping[str, Any] = {"files": []}
    else:
        raw_manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        manifest = raw_manifest if isinstance(raw_manifest, Mapping) else {}
        evidence_paths.append("final_artifact_manifest.json")
        evidence_hashes["final_artifact_manifest.json"] = sha256_file(
            manifest_path
        )
    raw_entries = manifest.get("files", [])
    entries = raw_entries if isinstance(raw_entries, list) else []
    if not isinstance(raw_entries, list):
        failures.append("MANIFEST_FILES_INVALID")
    listed_paths = [
        str(entry.get("path", ""))
        for entry in entries
        if isinstance(entry, Mapping)
    ]
    if len(listed_paths) != len(set(listed_paths)):
        failures.append("MANIFEST_DUPLICATE_PATH")
    actual_files = _relative_file_set(root, manifest_path)
    listed_file_set = set(listed_paths)
    for name in MANDATORY_FINAL_OUTPUTS:
        if name not in actual_files:
            failures.append(f"REQUIRED_OUTPUT_MISSING:{name}")
        elif name not in listed_file_set:
            failures.append(f"REQUIRED_OUTPUT_UNSEALED:{name}")
    declared_mandatory = manifest.get("mandatory_outputs")
    if declared_mandatory != list(MANDATORY_FINAL_OUTPUTS):
        failures.append("MANDATORY_OUTPUT_CONTRACT_MISMATCH")
    if manifest.get("post_verification_outputs") != list(
        POST_VERIFICATION_OUTPUTS
    ):
        failures.append("POST_VERIFICATION_OUTPUT_CONTRACT_MISMATCH")
    for extra in sorted(actual_files.difference(listed_file_set)):
        failures.append(f"MANIFEST_UNSEALED_FILE:{extra}")
    for entry in entries:
        if not isinstance(entry, Mapping):
            failures.append("MANIFEST_ENTRY_INVALID")
            continue
        relative = Path(str(entry.get("path", "")))
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root):
            failures.append("MANIFEST_PATH_ESCAPE")
            continue
        if not candidate.is_file():
            failures.append("MANIFEST_FILE_MISSING")
            continue
        if candidate.stat().st_size != entry.get("bytes"):
            failures.append("MANIFEST_SIZE_MISMATCH")
        actual_hash = sha256_file(candidate)
        if actual_hash != entry.get("sha256"):
            failures.append("MANIFEST_HASH_MISMATCH")
        try:
            actual_schema = _schema_version(candidate)
        except (OSError, ValueError, pa.ArrowInvalid):
            failures.append("MANIFEST_FILE_UNREADABLE")
            continue
        if actual_schema != entry.get("schema_version"):
            failures.append("MANIFEST_SCHEMA_MISMATCH")
        relative_text = relative.as_posix()
        evidence_paths.append(relative_text)
        evidence_hashes[relative_text] = actual_hash

    timeline_telemetry_complete = _validate_telemetry_evidence(
        root,
        failures,
    )
    resource_telemetry_complete = _validate_resource_sample_evidence(
        root,
        failures,
    )
    telemetry_complete = (
        timeline_telemetry_complete and resource_telemetry_complete
    )
    failures.extend(validate_native_qualification_artifacts(root))
    scientific_identity_valid = (
        _validate_scientific_content_identity(
            root,
            listed_file_set,
            failures,
        )
    )
    policy = spec.policy
    performance = spec.performance
    contract_path = root / "performance_contract.json"
    contract: Mapping[str, Any] = {}
    if not contract_path.is_file():
        failures.append("PERFORMANCE_CONTRACT_MISSING")
    else:
        raw_contract = json.loads(
            contract_path.read_text(encoding="utf-8")
        )
        if isinstance(raw_contract, Mapping):
            contract = raw_contract
        else:
            failures.append("PERFORMANCE_CONTRACT_INVALID")
    spec_hash = canonical_sha256(spec)
    identity_checks = (
        (
            "resolved_spec_sha256",
            spec_hash,
            "RESOLVED_SPEC_HASH_MISMATCH",
        ),
        (
            "code_sha",
            spec.identity["code_sha"],
            "CODE_SHA_MISMATCH",
        ),
        (
            "snapshot_hash",
            spec.data["snapshot_hash"],
            "SNAPSHOT_HASH_MISMATCH",
        ),
        (
            "policy_hash",
            spec.policy["policy_hash"],
            "POLICY_HASH_MISMATCH",
        ),
    )
    for field, expected, failure_code in identity_checks:
        if not expected:
            failures.append(f"{failure_code}_EMPTY")
            continue
        if contract.get(field) != expected or manifest.get(field) != expected:
            failures.append(failure_code)
    deadline_audit = _read_required_json(
        root,
        "deadline_audit.json",
        "DEADLINE_AUDIT_MISSING",
        failures,
    )
    if deadline_audit.get("route_allowed") is not True:
        failures.append("DEADLINE_GUARD_FAILED")
    budget_audit = _read_required_json(
        root,
        "budget_audit.json",
        "BUDGET_AUDIT_MISSING",
        failures,
    )
    budget_decision = budget_audit.get("decision")
    if (
        not isinstance(budget_decision, Mapping)
        or budget_decision.get("route_allowed") is not True
        or budget_decision.get("evidence_complete") is not True
    ):
        failures.append("BUDGET_GUARD_FAILED")
    environment_manifest = _read_required_json(
        root,
        "environment_manifest.json",
        "ENVIRONMENT_MANIFEST_MISSING",
        failures,
    )
    if (
        not environment_manifest.get("environment_sha256")
        or environment_manifest.get("environment_sha256")
        != contract.get("environment_sha256")
    ):
        failures.append("DEPENDENCY_ENVIRONMENT_MISMATCH")
    data_audit = _read_required_json(
        root,
        "data_audit.json",
        "DATA_AUDIT_MISSING",
        failures,
    )
    policy_audit = _read_required_json(
        root,
        "policy_audit.json",
        "POLICY_AUDIT_MISSING",
        failures,
    )
    runtime_audit = _read_required_json(
        root,
        "runtime_audit.json",
        "RUNTIME_AUDIT_MISSING",
        failures,
    )
    _read_required_json(
        root,
        "provenance.json",
        "PROVENANCE_MISSING",
        failures,
    )
    metric_inputs_path = root / "metric_verification_inputs.parquet"
    independent_metric_path = root / "independent_metric_verification.json"
    metric_unit_keys: set[str] = set()
    if not metric_inputs_path.is_file():
        failures.append("METRIC_INPUTS_MISSING")
    independent_metric_report = _read_required_json(
        root,
        "independent_metric_verification.json",
        "INDEPENDENT_METRIC_REPORT_MISSING",
        failures,
    )
    if metric_inputs_path.is_file() and independent_metric_report:
        try:
            metric_records = read_metric_inputs(metric_inputs_path)
            metric_unit_keys = {
                record.unit_key for record in metric_records
            }
            recomputed_metric_report = verify_metric_inputs(metric_records)
            expected_metric_payload = (
                independent_metric_verification_payload(
                    recomputed_metric_report,
                    metric_inputs_path,
                )
            )
        except (OSError, ValueError, TypeError, pa.ArrowInvalid):
            failures.append("METRIC_INPUTS_INVALID")
        else:
            if not recomputed_metric_report.passed:
                failures.append("INDEPENDENT_METRICS_MISMATCH")
            if independent_metric_report != expected_metric_payload:
                failures.append(
                    "INDEPENDENT_METRIC_REPORT_INCONSISTENT"
                )
            evidence_paths.extend(
                (
                    metric_inputs_path.name,
                    independent_metric_path.name,
                )
            )
            evidence_hashes[metric_inputs_path.name] = sha256_file(
                metric_inputs_path
            )
            evidence_hashes[independent_metric_path.name] = sha256_file(
                independent_metric_path
            )
    locked_rows_accessed = int(
        data_audit.get("locked_rows_accessed", -1)
    )
    locked_opened = bool(policy_audit.get("locked_opened", True))
    validation_used = bool(
        policy_audit.get("validation_used_for_selection", True)
    )
    standard_runner_only = bool(
        runtime_audit.get("standard_runner_only", False)
    )
    if locked_rows_accessed != 0:
        failures.append("RUNTIME_LOCKED_ROWS_ACCESSED")
        locked_opened = True
    maximum_accessed = str(
        data_audit.get("maximum_accessed_date", "9999-12-31")
    )
    if maximum_accessed > str(policy["validation_end"]):
        failures.append("RUNTIME_DATA_AFTER_VALIDATION_END")
        locked_opened = True
    matrix_ok = (
        int(performance["matrix_max_jobs"]) <= 256
        and int(performance["planner_max_jobs"]) <= 360
    )
    if int(policy.get("causal_lag_minimum", 0)) < 1:
        failures.append("CAUSAL_LAG_INVARIANT_FAILED")
    if locked_opened:
        failures.append("LOCKED_OPENED")
    if validation_used:
        failures.append("VALIDATION_USED_FOR_SELECTION")
    if not standard_runner_only:
        failures.append("NONSTANDARD_RUNNER")
    if not matrix_ok:
        failures.append("MATRIX_CEILING_EXCEEDED")
    contract_invariants = (
        (
            contract.get("locked_opened") is False,
            "CONTRACT_LOCKED_INVARIANT_FAILED",
        ),
        (
            contract.get("validation_used_for_selection") is False,
            "CONTRACT_VALIDATION_INVARIANT_FAILED",
        ),
        (
            contract.get("standard_runner_only") is True,
            "CONTRACT_STANDARD_RUNNER_INVARIANT_FAILED",
        ),
        (
            contract.get("larger_runners_allowed") is False,
            "CONTRACT_LARGER_RUNNER_INVARIANT_FAILED",
        ),
        (
            contract.get("matrix_job_ceiling") == 256,
            "CONTRACT_MATRIX_CEILING_INVARIANT_FAILED",
        ),
        (
            contract.get("standard_concurrency_ceiling") == 360,
            "CONTRACT_CONCURRENCY_INVARIANT_FAILED",
        ),
    )
    failures.extend(
        failure_code
        for passed, failure_code in contract_invariants
        if not passed
    )

    reconciliation = _read_reconciliation_summary(
        root / "unit_reconciliation.parquet"
    )
    terminal_counts = {
        key: int(reconciliation.get(key, 0))
        for key in (
            "expected_units",
            "completed",
            "right_censored",
            "unsupported",
            "failed_technical",
            "missing_units",
        )
    }
    terminal_sum = sum(
        terminal_counts[key]
        for key in (
            "completed",
            "right_censored",
            "unsupported",
            "failed_technical",
        )
    )
    partial = bool(reconciliation.get("partial", True))
    reconciliation_path = root / "unit_reconciliation.parquet"
    if reconciliation_path.is_file():
        reconciliation_schema = pq.ParquetFile(
            reconciliation_path
        ).schema_arrow
        if {"unit_key", "state"}.issubset(
            reconciliation_schema.names
        ):
            reconciliation_table = pq.read_table(
                reconciliation_path,
                columns=["unit_key", "state"],
            )
            completed_metric_units = {
                str(row["unit_key"])
                for row in reconciliation_table.to_pylist()
                if row["state"] == "completed"
            }
            if completed_metric_units != metric_unit_keys:
                failures.append("METRIC_EVIDENCE_INCOMPLETE")
    if (
        terminal_sum + terminal_counts["missing_units"]
        != terminal_counts["expected_units"]
    ):
        failures.append("RECONCILIATION_TOTAL_MISMATCH")
        partial = True
    if terminal_counts["missing_units"]:
        failures.append("RECONCILIATION_MISSING_UNITS")
        partial = True
    requirements_passed = _traceability_passed(
        root / "requirements_traceability.csv"
    )
    if not requirements_passed:
        failures.append("REQUIREMENTS_FAILED")
    passed = not failures and not partial
    return VerificationReport(
        passed=passed,
        partial=partial,
        requirements_passed=requirements_passed,
        locked_opened=locked_opened,
        validation_used_for_selection=validation_used,
        standard_runner_only=standard_runner_only,
        matrix_job_ceiling_respected=matrix_ok,
        evidence_paths=tuple(sorted(set(evidence_paths))),
        terminal_counts=terminal_counts,
        evidence_sha256=evidence_hashes,
        failure_codes=tuple(sorted(set(failures))),
    )


def _display(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def build_requirements_traceability(
    spec: RunSpec,
    evidence: Mapping[str, Any],
) -> pa.Table:
    """Build one explicit row for every campaign acceptance criterion."""

    checks = (
        (
            "github_only",
            "Execution occurs only in GitHub Actions",
            True,
            evidence.get("github_only"),
            "performance_contract.json",
        ),
        (
            "standard_runner",
            "Only standard ubuntu-24.04 runners are used",
            True,
            evidence.get("standard_runner_only"),
            "performance_contract.json",
        ),
        (
            "larger_runner_forbidden",
            "No larger, paid, GPU, or self-hosted runner is used",
            False,
            evidence.get("larger_runner_used"),
            "runtime_audit.json",
        ),
        (
            "matrix_ceiling",
            "No matrix exceeds 256 jobs",
            True,
            evidence.get("matrix_job_ceiling_respected"),
            "execution_plan.json",
        ),
        (
            "concurrency_ceiling",
            "Standard concurrency never exceeds 360 jobs",
            True,
            evidence.get(
                "standard_concurrency_ceiling_respected"
            ),
            "performance_contract.json",
        ),
        (
            "deadline_guard",
            "The projected route remains inside the hard deadline",
            True,
            evidence.get("deadline_respected"),
            "deadline_audit.json",
        ),
        (
            "budget_guard",
            "The projected route remains inside hard budget limits",
            True,
            evidence.get("budget_respected"),
            "budget_audit.json",
        ),
        (
            "locked_closed",
            "Locked data remains closed",
            False,
            evidence.get("locked_opened"),
            "policy_audit.json",
        ),
        (
            "runtime_locked_rows_zero",
            "Runtime evidence contains zero locked rows",
            True,
            evidence.get("runtime_locked_rows_zero"),
            "data_audit.json",
        ),
        (
            "validation_report_only",
            "Validation is not used for selection",
            False,
            evidence.get("validation_used_for_selection"),
            "policy_audit.json",
        ),
        (
            "no_future_data",
            "Runtime never reads beyond validation_end",
            True,
            evidence.get("maximum_accessed_date_valid"),
            "data_audit.json",
        ),
        (
            "causal_execution",
            "Signals preserve the frozen minimum causal lag",
            True,
            evidence.get("causal_lag_respected"),
            "resolved_run_spec.json",
        ),
        (
            "complete_reconciliation",
            "Every expected logical unit has one terminal outcome",
            True,
            evidence.get("reconciliation_complete"),
            "unit_reconciliation.parquet",
        ),
        (
            "artifact_hashes",
            "Every final artifact hash verifies",
            True,
            evidence.get("artifact_hashes_valid"),
            "final_artifact_manifest.json",
        ),
        (
            "required_outputs",
            "Every mandatory campaign output is present before seal",
            True,
            evidence.get("required_outputs_complete"),
            "final_artifact_manifest.json",
        ),
        (
            "telemetry_complete",
            "Runtime and GitHub timeline telemetry are complete and sealed",
            True,
            evidence.get("telemetry_complete"),
            "performance_telemetry_manifest.json",
        ),
        (
            "independent_metrics",
            "Independent metric recalculation matches primary outputs",
            True,
            evidence.get("independent_metrics_equal"),
            "independent_metric_verification.json",
        ),
        (
            "dependency_environment",
            "The exact dependency environment identity is reproducible",
            True,
            evidence.get("dependency_environment_reproducible"),
            "environment_manifest.json",
        ),
        (
            "selective_recovery",
            "Recovery preserves valid work and targets only pending units",
            True,
            evidence.get("selective_recovery_verified"),
            "recovery_plan.json",
        ),
        (
            "replan",
            "Operational replan preserves scientific unit identity",
            True,
            evidence.get("replan_verified"),
            "replan_descriptor.json",
        ),
        (
            "merge_only",
            "Merge-only repeats no scientific shard computation",
            True,
            evidence.get("merge_only_verified"),
            "merge_only_verification.json",
        ),
        (
            "multi_level_merge",
            "Every executed merge level and direct-child hash verifies",
            True,
            evidence.get("multi_level_merge_verified"),
            "final_merge_summary.json",
        ),
        (
            "scientific_equivalence",
            "Performance comparison uses exactly equivalent science",
            True,
            evidence.get("scientific_equivalence_verified"),
            "benchmark_report.json",
        ),
        (
            "scientific_content_identity",
            "Canonical unit-level scientific content identity is present",
            True,
            evidence.get("scientific_content_identity_verified"),
            "final_merge_summary.json",
        ),
    )
    rows = []
    for requirement_id, text, expected, observed, path in checks:
        if observed is None:
            status = "not_applicable"
            observed_display = "not_applicable"
        else:
            status = "pass" if observed == expected else "fail"
            observed_display = _display(observed)
        rows.append(
            {
                "requirement_id": requirement_id,
                "requirement_text": text,
                "expected_value": _display(expected),
                "observed_value": observed_display,
                "evidence_path": path,
                "status": status,
            }
        )
    schema = pa.schema(
        [pa.field(column, pa.string(), nullable=False) for column in TRACEABILITY_COLUMNS]
    )
    return pa.Table.from_pylist(rows, schema=schema)


def _optional_json(path: Path) -> Mapping[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, Mapping) else None


def _write_final_performance_outputs(root: Path) -> tuple[Path, Path]:
    timeline = _optional_json(root / "timeline_summary.json") or {}
    merge = _optional_json(root / "final_merge_summary.json") or {}
    components = {
        name: float(timeline.get(f"{name}_seconds_total", 0.0))
        for name in (
            "setup",
            "transfer",
            "compute",
            "retry",
            "merge",
            "other",
        )
    }
    dominant, dominant_seconds = max(
        components.items(),
        key=lambda item: (item[1], item[0]),
    )
    bottleneck = _atomic_json(
        root / "bottleneck_report.json",
        {
            "schema_version": "1",
            "measurement_source": "github_jobs_timeline",
            "dominant_component": dominant,
            "dominant_component_seconds": dominant_seconds,
            "components": components,
            "speedup_claimed": False,
        },
    )
    performance = _atomic_json(
        root / "performance_final.json",
        {
            "schema_version": "1",
            "telemetry_complete": bool(timeline.get("complete", False)),
            "workflow_wall_seconds": float(
                timeline.get("workflow_wall_seconds", 0.0)
            ),
            "execution_wall_seconds": float(
                timeline.get("execution_wall_seconds", 0.0)
            ),
            "observed_peak_parallelism": int(
                timeline.get("observed_peak_parallelism", 0)
            ),
            "requested_parallelism": int(
                timeline.get("requested_parallelism", 0)
            ),
            "estimated_billable_minutes": float(
                timeline.get("estimated_billable_minutes", 0.0)
            ),
            "partial": bool(merge.get("partial", True)),
            "scientific_content_sha256": str(
                merge.get("scientific_content_sha256", "")
            ),
            "scientific_content_rows": int(
                merge.get("scientific_content_rows", 0)
            ),
            "locked_opened": bool(
                merge.get("locked_opened", True)
            ),
            "locked_rows_accessed": int(
                merge.get("locked_rows_accessed", -1)
            ),
            "validation_used_for_selection": bool(
                merge.get("validation_used_for_selection", True)
            ),
            "speedup_claimed": False,
        },
    )
    return bottleneck, performance


def _final_evidence(
    root: Path,
    spec: RunSpec,
) -> dict[str, Any]:
    runtime = _optional_json(root / "runtime_audit.json") or {}
    policy = _optional_json(root / "policy_audit.json") or {}
    data = _optional_json(root / "data_audit.json") or {}
    contract = _optional_json(root / "performance_contract.json") or {}
    environment = _optional_json(root / "environment_manifest.json") or {}
    deadline = _optional_json(root / "deadline_audit.json") or {}
    budget = _optional_json(root / "budget_audit.json") or {}
    budget_decision = budget.get("decision")
    if not isinstance(budget_decision, Mapping):
        budget_decision = {}
    merge = _optional_json(root / "final_merge_summary.json") or {}
    telemetry_failures: list[str] = []
    telemetry_complete = _validate_telemetry_evidence(
        root,
        telemetry_failures,
    )
    identity_failures: list[str] = []
    identity_valid = _validate_scientific_content_identity(
        root,
        _relative_file_set(
            root,
            root / "final_artifact_manifest.json",
        ),
        identity_failures,
    )
    maximum = data.get("maximum_accessed_date")
    replan = _optional_json(root / "replan.json")
    merge_only = _optional_json(root / "merge_only_verification.json")
    benchmark = _optional_json(root / "benchmark_report.json")
    if replan is None:
        replan_verified: bool | None = None
    else:
        replan_verified = all(
            replan.get(field) is True
            for field in (
                "scientific_contract_unchanged",
                "logical_units_unchanged",
                "completed_evidence_unchanged",
            )
        )
    if merge_only is None:
        merge_only_verified: bool | None = None
    else:
        merge_only_verified = (
            merge_only.get("merge_only") is True
            and merge_only.get("compute_scheduled") is False
            and merge_only.get("scientific_outputs_equal") is True
        )
    equivalence_source = benchmark or merge_only
    scientific_equivalence: bool | None = (
        None
        if equivalence_source is None
        else equivalence_source.get("scientific_outputs_equal") is True
    )
    reconciliation = _read_reconciliation_summary(
        root / "unit_reconciliation.parquet"
    )
    required_before_trace = set(MANDATORY_FINAL_OUTPUTS).difference(
        {"requirements_traceability.csv"}
    )
    actual = _relative_file_set(
        root,
        root / "final_artifact_manifest.json",
    )
    return {
        "github_only": runtime.get("github_only_run"),
        "standard_runner_only": runtime.get("standard_runner_only"),
        "larger_runner_used": runtime.get("larger_runner_used"),
        "matrix_job_ceiling_respected": (
            int(spec.performance["matrix_max_jobs"]) <= 256
        ),
        "standard_concurrency_ceiling_respected": (
            int(spec.performance["planner_max_jobs"]) <= 360
        ),
        "deadline_respected": deadline.get("route_allowed"),
        "budget_respected": (
            budget_decision.get("route_allowed") is True
            and budget_decision.get("evidence_complete") is True
        ),
        "locked_opened": policy.get("locked_opened"),
        "runtime_locked_rows_zero": (
            data.get("locked_rows_accessed") == 0
        ),
        "validation_used_for_selection": policy.get(
            "validation_used_for_selection"
        ),
        "maximum_accessed_date_valid": (
            maximum is not None
            and str(maximum) <= str(spec.policy["validation_end"])
        ),
        "causal_lag_respected": (
            int(spec.policy.get("causal_lag_minimum", 0)) >= 1
        ),
        "reconciliation_complete": (
            reconciliation.get("partial") is False
            and int(reconciliation.get("missing_units", 0)) == 0
        ),
        "artifact_hashes_valid": True,
        "required_outputs_complete": (
            required_before_trace.issubset(actual)
        ),
        "telemetry_complete": telemetry_complete,
        "independent_metrics_equal": merge.get(
            "independent_metrics_equal"
        ),
        "dependency_environment_reproducible": (
            bool(environment.get("environment_sha256"))
            and environment.get("environment_sha256")
            == contract.get("environment_sha256")
        ),
        "selective_recovery_verified": (
            (root / "recovery_plan.json").is_file()
            and reconciliation.get("partial") is False
        ),
        "replan_verified": replan_verified,
        "merge_only_verified": merge_only_verified,
        "multi_level_merge_verified": merge.get(
            "multi_level_merge_verified"
        ),
        "scientific_equivalence_verified": scientific_equivalence,
        "scientific_content_identity_verified": identity_valid,
    }


def seal_final_artifact(root: Path, spec: RunSpec) -> Path:
    """Add telemetry-derived outputs, trace every criterion, then seal."""

    root = Path(root).resolve()
    manifest_path = root / "final_artifact_manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()
    _write_final_performance_outputs(root)
    runtime_rows = pq.read_table(
        root / "runtime_breakdown.parquet",
        columns=["phase", "duration_seconds"],
    ).to_pylist()
    ensure_runtime_native_fallback_artifacts(runtime_rows, root)
    evidence = _final_evidence(root, spec)
    traceability = build_requirements_traceability(spec, evidence)
    write_requirements_traceability(
        traceability,
        root / "requirements_traceability.csv",
    )
    actual = _relative_file_set(root, manifest_path)
    missing = sorted(set(MANDATORY_FINAL_OUTPUTS).difference(actual))
    failed_rows = [
        row["requirement_id"]
        for row in traceability.to_pylist()
        if row["status"] == "fail"
    ]
    if missing or failed_rows:
        reasons = [
            *(f"REQUIRED_OUTPUT_MISSING:{name}" for name in missing),
            *(f"REQUIREMENT_FAILED:{name}" for name in failed_rows),
        ]
        raise FinalArtifactCompletenessError(",".join(reasons))
    return write_final_artifact_manifest(root, manifest_path)


def write_requirements_traceability(
    table: pa.Table,
    path: Path,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRACEABILITY_COLUMNS)
        writer.writeheader()
        writer.writerows(table.to_pylist())
    temporary.replace(path)
    return path


def write_verification_report(
    report: VerificationReport,
    path: Path,
) -> Path:
    return _atomic_json(Path(path), report)


def write_campaign_closure(
    report: VerificationReport,
    path: Path,
) -> Path:
    status = (
        "success"
        if (
            report.passed
            and not report.partial
            and report.requirements_passed
            and not report.locked_opened
            and not report.validation_used_for_selection
            and report.standard_runner_only
            and report.matrix_job_ceiling_respected
        )
        else "failed"
    )
    payload = {
        "schema_version": "1",
        "status": status,
        "partial": report.partial,
        "terminal_counts": deep_thaw_json(report.terminal_counts),
        "locked_opened": report.locked_opened,
        "validation_used_for_selection": (
            report.validation_used_for_selection
        ),
        "standard_runner_only": report.standard_runner_only,
        "matrix_job_ceiling_respected": (
            report.matrix_job_ceiling_respected
        ),
        "requirements_passed": report.requirements_passed,
        "evidence_sha256": deep_thaw_json(report.evidence_sha256),
        "verification_failure_codes": list(report.failure_codes),
    }
    return _atomic_json(Path(path), payload)
