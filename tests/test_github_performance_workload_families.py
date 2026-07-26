from __future__ import annotations

import json
import os
from pathlib import Path
import tomllib

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from aurora.infra.github_performance.adapter import adapt_workload
from aurora.infra.github_performance.audits import (
    read_runtime_access_ledger,
)
from aurora.infra.github_performance.checkpoint import load_checkpoint
from aurora.infra.github_performance.contracts import (
    RunSpec,
    ShardDefinition,
    WorkUnit,
)
from aurora.infra.github_performance.metric_verifier import (
    read_metric_inputs,
    verify_metric_inputs,
)
from aurora.infra.github_performance.preflight import validate_run_spec
from aurora.infra.github_performance.shard_planner import (
    ASSIGNMENT_SCHEMA,
    ASSIGNMENT_SCHEMA_VERSION,
    sha256_file,
)
from aurora.infra.github_performance.workloads.candidate_sweep import (
    WORKLOAD as CANDIDATE_SWEEP,
)
from aurora.infra.github_performance.workloads.event_study import (
    WORKLOAD as EVENT_STUDY,
)
from aurora.infra.github_performance.workloads.robustness import (
    WORKLOAD as ROBUSTNESS,
)


def test_representative_workloads_are_packaged_in_aurora_wheel() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    packages = pyproject["tool"]["setuptools"]["packages"]
    package_dirs = pyproject["tool"]["setuptools"]["package-dir"]

    assert "aurora.infra.github_performance.workloads" in packages
    assert package_dirs[
        "aurora.infra.github_performance.workloads"
    ] == "infra/github_performance/workloads"
from github_performance_helpers import minimal_valid_spec


WORKLOADS = (CANDIDATE_SWEEP, EVENT_STUDY, ROBUSTNESS)
ROOT = Path(__file__).resolve().parents[1]
CONFIGS = (
    ROOT / "config" / "github_performance_candidate_sweep.yaml",
    ROOT / "config" / "github_performance_event_study.yaml",
    ROOT / "config" / "github_performance_robustness.yaml",
)


def _spec() -> RunSpec:
    payload = minimal_valid_spec()
    payload["identity"]["code_sha"] = "a" * 40
    payload["identity"]["workflow_sha256"] = "b" * 64
    payload["policy"]["train_start"] = "1995-01-01"
    payload["policy"]["train_end"] = "2010-12-31"
    payload["policy"]["validation_start"] = "2011-01-01"
    payload["policy"]["validation_end"] = "2020-12-31"
    payload["policy"]["locked_start"] = "2021-01-01"
    payload["policy"]["locked_opened"] = False
    payload["policy"]["locked_rows_allowed"] = 0
    payload["policy"]["validation_used_for_selection"] = False
    payload["policy"]["policy_hash"] = "c" * 64
    payload["data"]["max_date"] = "2020-12-31"
    payload["data"]["manifest_sha256"] = "d" * 64
    payload["data"]["snapshot_hash"] = "e" * 64
    payload["execution"]["dependency_lock_sha256"] = "f" * 64
    payload["execution"]["environment_sha256"] = "1" * 64
    payload["performance"]["capacity_profile_sha256"] = "2" * 64
    payload["metrics"]["contract_sha256"] = "3" * 64
    return RunSpec.model_validate(payload)


def _first_unit(manifest_path: Path) -> WorkUnit:
    row = pq.read_table(manifest_path).slice(0, 1).to_pylist()[0]
    return WorkUnit(
        unit_key=str(row["unit_key"]),
        estimated_seconds=float(row["estimated_seconds"]),
        payload_ref=str(row["payload_ref"]),
        payload_sha256=str(row["payload_sha256"]),
    )


def _one_unit_shard(
    unit: WorkUnit,
    root: Path,
) -> ShardDefinition:
    assignment = root / "assignment.parquet"
    metadata = {
        b"schema_version": ASSIGNMENT_SCHEMA_VERSION.encode("ascii"),
        b"sorted_by": b"shard_id,unit_key",
    }
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "shard_id": "s000",
                    "unit_key": unit.unit_key,
                    "estimated_seconds": unit.estimated_seconds,
                    "payload_ref": unit.payload_ref,
                    "payload_sha256": unit.payload_sha256,
                }
            ],
            schema=ASSIGNMENT_SCHEMA.with_metadata(metadata),
        ),
        assignment,
        compression="zstd",
    )
    return ShardDefinition(
        shard_id="s000",
        assignment_artifact="workload-family-test",
        assignment_member=str(assignment),
        assignment_sha256=sha256_file(assignment),
        unit_count=1,
        estimated_seconds=unit.estimated_seconds,
        merge_group="g000",
    )


def _multi_unit_shard(
    units: list[WorkUnit],
    root: Path,
) -> ShardDefinition:
    assignment = root / "assignment.parquet"
    metadata = {
        b"schema_version": ASSIGNMENT_SCHEMA_VERSION.encode("ascii"),
        b"sorted_by": b"shard_id,unit_key",
    }
    rows = [
        {
            "shard_id": "s000",
            "unit_key": unit.unit_key,
            "estimated_seconds": unit.estimated_seconds,
            "payload_ref": unit.payload_ref,
            "payload_sha256": unit.payload_sha256,
        }
        for unit in sorted(units, key=lambda item: item.unit_key)
    ]
    pq.write_table(
        pa.Table.from_pylist(
            rows,
            schema=ASSIGNMENT_SCHEMA.with_metadata(metadata),
        ),
        assignment,
        compression="zstd",
    )
    return ShardDefinition(
        shard_id="s000",
        assignment_artifact="workload-family-test",
        assignment_member=str(assignment),
        assignment_sha256=sha256_file(assignment),
        unit_count=len(rows),
        estimated_seconds=sum(unit.estimated_seconds for unit in units),
        merge_group="g000",
    )


def test_three_distinct_native_workload_contracts() -> None:
    contracts = tuple(
        adapt_workload(workload).describe_contract()
        for workload in WORKLOADS
    )

    assert {item.interface_kind for item in contracts} == {"phase2_native"}
    assert len({item.workload_name for item in contracts}) == 3
    assert {
        item.scientific_contract["workload_family"]
        for item in contracts
    } == {"candidate_sweep", "event_study", "robustness"}
    assert all(item.original_candidate_id_preserved for item in contracts)


def test_event_study_has_enough_unique_units_for_both_matrices() -> None:
    definitions = EVENT_STUDY._unit_definitions()
    unit_keys = {unit_key for unit_key, _, _ in definitions}

    assert len(definitions) == 512
    assert len(unit_keys) == 512
    assert len(definitions) > 256


@pytest.mark.parametrize("config_path", CONFIGS)
def test_representative_workload_specs_are_valid_and_locked(
    config_path: Path,
) -> None:
    report = validate_run_spec(config_path)
    text = config_path.read_text(encoding="utf-8")

    assert report.valid is True, report.violations
    assert 'validation_end: "2020-12-31"' in text
    assert 'locked_start: "2021-01-01"' in text
    assert "locked_opened: false" in text
    assert "validation_used_for_selection: false" in text
    assert 'runner_image: "ubuntu-24.04"' in text
    assert "C:\\" not in text


@pytest.mark.parametrize("workload", WORKLOADS)
def test_workload_units_and_science_are_deterministic(
    workload,
    tmp_path: Path,
) -> None:
    spec = _spec()
    prepared = workload.prepare_shared_inputs(spec, tmp_path / "prepared")
    first = workload.enumerate_units(
        spec,
        prepared,
        tmp_path / "plan-a.parquet",
    )
    second = workload.enumerate_units(
        spec,
        prepared,
        tmp_path / "plan-b.parquet",
    )
    unit = _first_unit(Path(first.path))

    assert first.unit_count > 1
    assert first.unit_count == second.unit_count
    assert first.sha256 == second.sha256
    left = workload.execute_unit(
        spec,
        prepared,
        unit,
        tmp_path / "unit-a",
    )
    right = workload.execute_unit(
        spec,
        prepared,
        unit,
        tmp_path / "unit-b",
    )
    assert left["row"]["unit_key"] == unit.unit_key
    assert (
        left["row"]["unit_output_sha256"]
        == right["row"]["unit_output_sha256"]
    )
    assert workload.verify_unit(spec, unit, left).passed is True
    assert workload.verify_unit(spec, unit, right).passed is True

    manifest = json.loads(
        Path(prepared.manifest_path).read_text(encoding="utf-8")
    )
    assert manifest["max_date"] == "2020-12-31"
    assert manifest["locked_opened"] is False
    assert manifest["validation_used_for_selection"] is False


@pytest.mark.parametrize("workload", WORKLOADS)
def test_one_unit_shard_emits_runtime_and_independent_metric_evidence(
    workload,
    tmp_path: Path,
) -> None:
    spec = _spec()
    prepared_root = tmp_path / "prepared"
    prepared = workload.prepare(spec, prepared_root)
    manifest = workload.enumerate_units(
        spec,
        prepared,
        tmp_path / "work_units.parquet",
    )
    unit = _first_unit(Path(manifest.path))
    shard = _one_unit_shard(unit, tmp_path)
    attempt_root = tmp_path / "attempt"
    os.environ["AURORA_PREPARED_ROOT"] = str(prepared_root)
    os.environ["AURORA_ATTEMPT_ID"] = "a-test-000"
    os.environ["AURORA_ARTIFACT_NAME"] = "workload-family-test-s000"

    attempt = workload.run_shard(
        spec,
        shard,
        attempt_root,
        None,
    )

    assert attempt.completed_unit_count == 1
    assert attempt.output_rows == 1
    result_path = attempt_root / workload.result_filename
    result = pq.read_table(result_path).to_pylist()[0]
    assert result["unit_key"] == unit.unit_key
    assert result["locked_opened"] is False
    assert result["validation_used_for_selection"] is False

    ledger = read_runtime_access_ledger(
        attempt_root / "runtime_access_ledger.parquet"
    )
    assert {record.split for record in ledger.records} == {
        "train",
        "validation",
    }
    assert max(record.maximum_date for record in ledger.records).isoformat() == (
        "2020-12-31"
    )
    assert all(record.locked is False for record in ledger.records)
    assert next(
        record for record in ledger.records if record.split == "train"
    ).purpose == "selection"
    assert next(
        record for record in ledger.records if record.split == "validation"
    ).purpose == "report"

    records = read_metric_inputs(
        attempt_root / "metric_verification_inputs.parquet"
    )
    assert len(records) == 2
    assert verify_metric_inputs(records).passed is True

    merged = workload.merge_outputs((attempt_root,), tmp_path / "merged")
    merged_table = pq.read_table(merged)
    assert merged_table.num_rows == 1
    assert merged_table.column("unit_key").to_pylist() == [unit.unit_key]


def test_controlled_transient_failure_resumes_exact_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workload = CANDIDATE_SWEEP
    spec = _spec()
    prepared_root = tmp_path / "prepared"
    prepared = workload.prepare(spec, prepared_root)
    manifest = workload.enumerate_units(
        spec,
        prepared,
        tmp_path / "work_units.parquet",
    )
    unit_rows = pq.read_table(Path(manifest.path)).slice(0, 40).to_pylist()
    units = [
        WorkUnit(
            unit_key=str(row["unit_key"]),
            estimated_seconds=float(row["estimated_seconds"]),
            payload_ref=str(row["payload_ref"]),
            payload_sha256=str(row["payload_sha256"]),
        )
        for row in unit_rows
    ]
    shard = _multi_unit_shard(units, tmp_path)
    monkeypatch.setenv("AURORA_PREPARED_ROOT", str(prepared_root))
    monkeypatch.setenv("AURORA_ATTEMPT_ID", "a-fault")
    monkeypatch.setenv("AURORA_ARTIFACT_NAME", "fault-artifact")
    monkeypatch.setenv("AURORA_FAULT_INJECTION_SHARD_ID", "s000")
    monkeypatch.setenv("AURORA_FAULT_INJECTION_AFTER_UNITS", "32")

    with pytest.raises(
        ConnectionError,
        match="CONTROLLED_TRANSIENT_NETWORK_AFTER_CHECKPOINT",
    ):
        workload.run_shard(
            spec,
            shard,
            tmp_path / "fault-attempt",
            None,
        )

    checkpoint = load_checkpoint(
        tmp_path
        / "fault-attempt"
        / "checkpoint"
        / "checkpoint_manifest.json"
    )
    assert checkpoint.completed_unit_count == 32
    checkpoint = checkpoint.model_copy(
        update={
            "payload_path": str(
                (
                    tmp_path
                    / "fault-attempt"
                    / "checkpoint"
                    / checkpoint.payload_path
                ).resolve()
            )
        }
    )

    monkeypatch.delenv("AURORA_FAULT_INJECTION_SHARD_ID")
    monkeypatch.delenv("AURORA_FAULT_INJECTION_AFTER_UNITS")
    monkeypatch.setenv("AURORA_ATTEMPT_ID", "a-recovery")
    monkeypatch.setenv("AURORA_ARTIFACT_NAME", "recovery-artifact")
    recovered = workload.run_shard(
        spec,
        shard,
        tmp_path / "recovered",
        checkpoint,
    )

    monkeypatch.setenv("AURORA_ATTEMPT_ID", "a-clean")
    monkeypatch.setenv("AURORA_ARTIFACT_NAME", "clean-artifact")
    clean = workload.run_shard(
        spec,
        shard,
        tmp_path / "clean",
        None,
    )

    assert recovered.completed_unit_count == clean.completed_unit_count == 40
    recovered_rows = pq.read_table(
        tmp_path / "recovered" / workload.result_filename
    ).to_pylist()
    clean_rows = pq.read_table(
        tmp_path / "clean" / workload.result_filename
    ).to_pylist()
    assert [
        {key: value for key, value in row.items() if key != "source_attempt_id"}
        for row in recovered_rows
    ] == [
        {key: value for key, value in row.items() if key != "source_attempt_id"}
        for row in clean_rows
    ]
