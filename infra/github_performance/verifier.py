"""Independent final-artifact verification and formal campaign closure."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from aurora.infra.github_performance.contracts import (
    RunSpec,
    VerificationReport,
    canonical_sha256,
    deep_thaw_json,
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


def write_final_artifact_manifest(root: Path, path: Path) -> Path:
    """Hash every already-produced final file without recursive self-hashes."""

    root = Path(root).resolve()
    path = Path(path).resolve()
    excluded = {
        path,
        root / "final_verification_report.json",
        root / "campaign_closure.json",
    }
    files: list[dict[str, Any]] = []
    for candidate in sorted(root.rglob("*")):
        resolved = candidate.resolve()
        if (
            not candidate.is_file()
            or resolved in excluded
            or candidate.suffix == ".tmp"
        ):
            continue
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
        "files": files,
    }
    return _atomic_json(path, payload)


def _read_reconciliation_summary(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        return {}
    metadata = pq.ParquetFile(path).schema_arrow.metadata or {}
    raw = metadata.get(b"summary_json")
    if raw is None:
        return {}
    payload = json.loads(raw.decode("utf-8"))
    return payload if isinstance(payload, Mapping) else {}


def _traceability_passed(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return bool(rows) and all(row.get("status") == "pass" for row in rows)


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
    for entry in manifest.get("files", []):
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
    locked_opened = bool(policy["locked_opened"])
    validation_used = bool(policy["validation_used_for_selection"])
    standard_runner_only = (
        performance["runner_label"] == "ubuntu-24.04"
        and performance["larger_runners_allowed"] is False
    )
    matrix_ok = (
        int(performance["matrix_max_jobs"]) <= 256
        and int(performance["planner_max_jobs"]) <= 360
    )
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
    """Build the fixed eight-row hard-requirement traceability table."""

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
            "matrix_ceiling",
            "No matrix exceeds 256 jobs",
            True,
            evidence.get("matrix_job_ceiling_respected"),
            "execution_plan.json",
        ),
        (
            "locked_closed",
            "Locked data remains closed",
            False,
            evidence.get("locked_opened"),
            "performance_contract.json",
        ),
        (
            "validation_report_only",
            "Validation is not used for selection",
            False,
            evidence.get("validation_used_for_selection"),
            "performance_contract.json",
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
            "independent_verification",
            "Independent final verification passes",
            True,
            evidence.get("independent_verification"),
            "final_verification_report.json",
        ),
    )
    rows = [
        {
            "requirement_id": requirement_id,
            "requirement_text": text,
            "expected_value": _display(expected),
            "observed_value": _display(observed),
            "evidence_path": path,
            "status": "pass" if observed == expected else "fail",
        }
        for requirement_id, text, expected, observed, path in checks
    ]
    schema = pa.schema(
        [pa.field(column, pa.string(), nullable=False) for column in TRACEABILITY_COLUMNS]
    )
    return pa.Table.from_pylist(rows, schema=schema)


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
