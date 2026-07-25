from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from aurora.infra.github_performance.contracts import (
    RunSpec,
)
from aurora.infra.github_performance.audits import (
    DataAccessRecord,
    RuntimeAccessLedger,
    build_required_audits,
    write_required_audits,
)
from aurora.infra.github_performance.merge_planner import (
    reconcile_attempts,
    write_reconciliation,
)
from aurora.infra.github_performance.verifier import (
    TRACEABILITY_COLUMNS,
    build_requirements_traceability,
    verify_final_artifact,
    write_campaign_closure,
    write_final_artifact_manifest,
    write_requirements_traceability,
)
from aurora.infra.github_performance.preflight import (
    freeze_resolved_contract,
    resolve_run_spec,
)
from github_performance_helpers import (
    complete_runtime_evidence,
    completed_unit,
    minimal_valid_spec,
    verification_report,
)


def _complete_evidence() -> dict[str, bool]:
    return {
        "github_only": True,
        "standard_runner_only": True,
        "matrix_job_ceiling_respected": True,
        "locked_opened": False,
        "validation_used_for_selection": False,
        "reconciliation_complete": True,
        "artifact_hashes_valid": True,
        "independent_verification": True,
    }


def _resolved_fixture(tmp_path: Path) -> RunSpec:
    requested = RunSpec.model_validate(minimal_valid_spec())
    evidence = complete_runtime_evidence()
    resolved = resolve_run_spec(requested, evidence)
    freeze_resolved_contract(requested, evidence, tmp_path)
    return resolved


def _write_safe_runtime_audits(tmp_path: Path, spec: RunSpec) -> None:
    audits = build_required_audits(
        spec,
        RuntimeAccessLedger(
            records=(
                DataAccessRecord(
                    source="snapshot:test",
                    partition="train",
                    minimum_date="2003-01-02",
                    maximum_date="2010-12-31",
                    row_count=2_016,
                    split="train",
                    purpose="selection",
                    locked=False,
                    shard_id="s000",
                    attempt_id="a000",
                ),
                DataAccessRecord(
                    source="snapshot:test",
                    partition="validation",
                    minimum_date="2011-01-03",
                    maximum_date="2020-12-31",
                    row_count=2_520,
                    split="validation",
                    purpose="report",
                    locked=False,
                    shard_id="s000",
                    attempt_id="a000",
                ),
            )
        ),
        environment={
            "github_actions": True,
            "runner_label": "ubuntu-24.04",
            "larger_runner_used": False,
            "code_sha": spec.identity["code_sha"],
        },
    )
    write_required_audits(tmp_path, audits)


def test_traceability_has_exact_required_columns() -> None:
    spec = RunSpec.model_validate(minimal_valid_spec())
    table = build_requirements_traceability(spec, _complete_evidence())
    assert tuple(table.column_names) == TRACEABILITY_COLUMNS
    assert table.num_rows == 8
    assert set(table.column("status").to_pylist()) == {"pass"}


def test_closure_cannot_claim_success_with_failed_requirement(
    tmp_path: Path,
) -> None:
    report = verification_report(
        partial=False,
        requirements_passed=False,
        locked_opened=False,
    )
    path = write_campaign_closure(
        report,
        tmp_path / "campaign_closure.json",
    )
    payload = json.loads(path.read_text())
    assert payload["status"] == "failed"


def test_final_verifier_detects_post_manifest_tampering(
    tmp_path: Path,
) -> None:
    spec = _resolved_fixture(tmp_path)
    reconciliation = reconcile_attempts(
        {"u1"},
        [completed_unit("u1", "a1", "1" * 64)],
    )
    write_reconciliation(
        reconciliation,
        tmp_path / "unit_reconciliation.parquet",
    )
    traceability = build_requirements_traceability(
        spec,
        _complete_evidence(),
    )
    write_requirements_traceability(
        traceability,
        tmp_path / "requirements_traceability.csv",
    )
    result_file = tmp_path / "result.json"
    result_file.write_text('{"schema_version":"1","value":1}\n')
    write_final_artifact_manifest(
        tmp_path,
        tmp_path / "final_artifact_manifest.json",
    )
    result_file.write_text('{"schema_version":"1","value":2}\n')
    report = verify_final_artifact(tmp_path, spec)
    assert report.passed is False
    assert "MANIFEST_HASH_MISMATCH" in report.failure_codes


def test_final_verifier_accepts_complete_untampered_artifact(
    tmp_path: Path,
) -> None:
    spec = _resolved_fixture(tmp_path)
    reconciliation = reconcile_attempts(
        {"u1"},
        [completed_unit("u1", "a1", "1" * 64)],
    )
    write_reconciliation(
        reconciliation,
        tmp_path / "unit_reconciliation.parquet",
    )
    traceability = build_requirements_traceability(
        spec,
        _complete_evidence(),
    )
    write_requirements_traceability(
        traceability,
        tmp_path / "requirements_traceability.csv",
    )
    (tmp_path / "result.json").write_text(
        '{"schema_version":"1","value":1}\n',
        encoding="utf-8",
    )
    _write_safe_runtime_audits(tmp_path, spec)
    write_final_artifact_manifest(
        tmp_path,
        tmp_path / "final_artifact_manifest.json",
    )
    report = verify_final_artifact(tmp_path, spec)
    assert report.passed is True
    assert report.partial is False


def test_final_verifier_reads_streaming_reconciliation_footer(
    tmp_path: Path,
) -> None:
    spec = _resolved_fixture(tmp_path)
    path = tmp_path / "unit_reconciliation.parquet"
    schema = pa.schema(
        [pa.field("unit_key", pa.string(), nullable=False)],
        metadata={b"schema_version": b"1"},
    )
    writer = pq.ParquetWriter(path, schema)
    writer.write_table(pa.Table.from_pylist([{"unit_key": "u1"}], schema))
    writer.add_key_value_metadata(
        {
            "summary_json": json.dumps(
                {
                    "expected_units": 1,
                    "completed": 1,
                    "right_censored": 0,
                    "unsupported": 0,
                    "failed_technical": 0,
                    "missing_units": 0,
                    "partial": False,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        }
    )
    writer.close()
    traceability = build_requirements_traceability(
        spec,
        _complete_evidence(),
    )
    write_requirements_traceability(
        traceability,
        tmp_path / "requirements_traceability.csv",
    )
    _write_safe_runtime_audits(tmp_path, spec)
    write_final_artifact_manifest(
        tmp_path,
        tmp_path / "final_artifact_manifest.json",
    )

    report = verify_final_artifact(tmp_path, spec)

    assert report.passed is True
    assert report.partial is False
    assert report.terminal_counts["expected_units"] == 1
    assert report.terminal_counts["completed"] == 1


def test_final_verifier_requires_runtime_derived_policy_audits(
    tmp_path: Path,
) -> None:
    spec = _resolved_fixture(tmp_path)
    reconciliation = reconcile_attempts(
        {"u1"},
        [completed_unit("u1", "a1", "1" * 64)],
    )
    write_reconciliation(
        reconciliation,
        tmp_path / "unit_reconciliation.parquet",
    )
    traceability = build_requirements_traceability(
        spec,
        _complete_evidence(),
    )
    write_requirements_traceability(
        traceability,
        tmp_path / "requirements_traceability.csv",
    )
    write_final_artifact_manifest(
        tmp_path,
        tmp_path / "final_artifact_manifest.json",
    )

    report = verify_final_artifact(tmp_path, spec)

    assert report.passed is False
    assert "DATA_AUDIT_MISSING" in report.failure_codes
    assert "POLICY_AUDIT_MISSING" in report.failure_codes
    assert "RUNTIME_AUDIT_MISSING" in report.failure_codes
    assert "PROVENANCE_MISSING" in report.failure_codes


def test_final_verifier_rejects_declared_safe_policy_with_locked_runtime_rows(
    tmp_path: Path,
) -> None:
    spec = _resolved_fixture(tmp_path)
    reconciliation = reconcile_attempts(
        {"u1"},
        [completed_unit("u1", "a1", "1" * 64)],
    )
    write_reconciliation(
        reconciliation,
        tmp_path / "unit_reconciliation.parquet",
    )
    traceability = build_requirements_traceability(
        spec,
        _complete_evidence(),
    )
    write_requirements_traceability(
        traceability,
        tmp_path / "requirements_traceability.csv",
    )
    (tmp_path / "data_audit.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "locked_rows_accessed": 1,
                "maximum_accessed_date": "2021-01-04",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "policy_audit.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "locked_opened": False,
                "validation_used_for_selection": False,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "runtime_audit.json").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "github_only_run": True,
                "standard_runner_only": True,
                "larger_runner_used": False,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "provenance.json").write_text(
        json.dumps({"schema_version": "1"}),
        encoding="utf-8",
    )
    write_final_artifact_manifest(
        tmp_path,
        tmp_path / "final_artifact_manifest.json",
    )

    report = verify_final_artifact(tmp_path, spec)

    assert report.passed is False
    assert "RUNTIME_LOCKED_ROWS_ACCESSED" in report.failure_codes
