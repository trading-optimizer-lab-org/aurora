"""Stable phase-2 workload interface with phase-1 compatibility."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pyarrow as pa
import pyarrow.parquet as pq

from aurora.infra.github_performance.contracts import (
    AttemptManifest,
    PreparedInputs,
    RunSpec,
    ShardDefinition,
    TerminalState,
    UnitVerification,
    WorkUnit,
    WorkUnitManifest,
    WorkloadContract,
)
from aurora.infra.github_performance.shard_planner import (
    ASSIGNMENT_SCHEMA,
    ASSIGNMENT_SCHEMA_VERSION,
    sha256_file,
)
from aurora.infra.github_performance.workload import (
    REQUIRED_WORKLOAD_METHODS,
    WorkloadLoadError,
    _load_referenced_object,
)


STABLE_WORKLOAD_METHODS = (
    "describe_contract",
    "prepare_shared_inputs",
    "enumerate_units",
    "estimate_unit_cost",
    "execute_unit",
    "verify_unit",
    "merge_outputs",
)


@runtime_checkable
class StableGithubWorkload(Protocol):
    def describe_contract(self) -> WorkloadContract | Mapping[str, Any]: ...

    def prepare_shared_inputs(
        self,
        spec: RunSpec,
        output_dir: Path,
    ) -> PreparedInputs: ...

    def enumerate_units(
        self,
        spec: RunSpec,
        prepared: PreparedInputs,
        output_path: Path,
    ) -> WorkUnitManifest: ...

    def estimate_unit_cost(
        self,
        spec: RunSpec,
        prepared: PreparedInputs,
        unit: WorkUnit,
    ) -> float: ...

    def execute_unit(
        self,
        spec: RunSpec,
        prepared: PreparedInputs,
        unit: WorkUnit,
        output_dir: Path,
    ) -> Any: ...

    def verify_unit(
        self,
        spec: RunSpec,
        unit: WorkUnit,
        result: Any,
    ) -> Any: ...

    def merge_outputs(
        self,
        inputs: Sequence[Path],
        output_dir: Path,
    ) -> Path: ...


def _workload_name(workload: Any) -> str:
    kind = type(workload)
    return f"{kind.__module__}.{kind.__qualname__}"


class StableWorkloadAdapter:
    """Validated delegating adapter for a native phase-2 workload."""

    def __init__(self, workload: Any) -> None:
        self.workload = workload

    def describe_contract(self) -> WorkloadContract:
        payload = self.workload.describe_contract()
        if isinstance(payload, WorkloadContract):
            if not payload.original_candidate_id_preserved:
                raise WorkloadLoadError(
                    "phase-2 workload must preserve candidate identities"
                )
            return payload
        if not isinstance(payload, Mapping):
            raise WorkloadLoadError(
                "describe_contract must return a mapping or WorkloadContract"
            )
        scientific = payload.get("scientific_contract", {})
        if not isinstance(scientific, Mapping):
            raise WorkloadLoadError(
                "scientific_contract must be a mapping"
            )
        contract = WorkloadContract(
            interface_kind="phase2_native",
            adapter_version=str(payload.get("adapter_version", "1")),
            workload_name=str(
                payload.get("name", _workload_name(self.workload))
            ),
            scientific_contract=scientific,
            original_candidate_id_preserved=bool(
                payload.get("original_candidate_id_preserved", True)
            ),
            methods=STABLE_WORKLOAD_METHODS,
        )
        if not contract.original_candidate_id_preserved:
            raise WorkloadLoadError(
                "phase-2 workload must preserve candidate identities"
            )
        return contract

    def prepare_shared_inputs(
        self,
        spec: RunSpec,
        output_dir: Path,
    ) -> Any:
        return self.workload.prepare_shared_inputs(spec, output_dir)

    def enumerate_units(
        self,
        spec: RunSpec,
        prepared: Any,
        output_path: Path,
    ) -> Any:
        return self.workload.enumerate_units(
            spec,
            prepared,
            output_path,
        )

    def estimate_unit_cost(
        self,
        spec: RunSpec,
        prepared: Any,
        unit: WorkUnit,
    ) -> float:
        estimate = float(
            self.workload.estimate_unit_cost(spec, prepared, unit)
        )
        if not math.isfinite(estimate) or estimate < 0:
            raise ValueError("unit cost estimate must be finite and nonnegative")
        return estimate

    def execute_unit(
        self,
        spec: RunSpec,
        prepared: Any,
        unit: WorkUnit,
        output_dir: Path,
    ) -> Any:
        return self.workload.execute_unit(
            spec,
            prepared,
            unit,
            output_dir,
        )

    def verify_unit(
        self,
        spec: RunSpec,
        unit: WorkUnit,
        result: Any,
    ) -> Any:
        return self.workload.verify_unit(spec, unit, result)

    def merge_outputs(
        self,
        inputs: Sequence[Path],
        output_dir: Path,
    ) -> Any:
        return self.workload.merge_outputs(inputs, output_dir)


@contextmanager
def _temporary_environment(values: Mapping[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class Phase1CompatibilityAdapter(StableWorkloadAdapter):
    """Expose the stable interface without changing phase-1 science."""

    def describe_contract(self) -> WorkloadContract:
        return WorkloadContract(
            interface_kind="phase1_compatibility",
            adapter_version="1",
            workload_name=_workload_name(self.workload),
            scientific_contract={
                "legacy_methods": list(REQUIRED_WORKLOAD_METHODS),
                "execution_bridge": "single_unit_shard",
                "deduplication": "exact_content_hash_only",
            },
            original_candidate_id_preserved=True,
            methods=STABLE_WORKLOAD_METHODS,
        )

    def prepare_shared_inputs(
        self,
        spec: RunSpec,
        output_dir: Path,
    ) -> PreparedInputs:
        return self.workload.prepare(spec, output_dir)

    def enumerate_units(
        self,
        spec: RunSpec,
        prepared: PreparedInputs,
        output_path: Path,
    ) -> WorkUnitManifest:
        return self.workload.enumerate_units(
            spec,
            prepared,
            output_path,
        )

    def estimate_unit_cost(
        self,
        spec: RunSpec,
        prepared: PreparedInputs,
        unit: WorkUnit,
    ) -> float:
        del spec, prepared
        return float(unit.estimated_seconds)

    def execute_unit(
        self,
        spec: RunSpec,
        prepared: PreparedInputs,
        unit: WorkUnit,
        output_dir: Path,
    ) -> Any:
        del prepared
        root = Path(output_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        shard_id = f"compat-{unit.unit_key}"
        assignment_path = root / "compat-assignment.parquet"
        metadata = {
            b"schema_version": ASSIGNMENT_SCHEMA_VERSION.encode("ascii"),
            b"sorted_by": b"shard_id,unit_key",
        }
        table = pa.Table.from_pylist(
            [
                {
                    "shard_id": shard_id,
                    "unit_key": unit.unit_key,
                    "estimated_seconds": unit.estimated_seconds,
                    "payload_ref": unit.payload_ref,
                    "payload_sha256": unit.payload_sha256,
                }
            ],
            schema=ASSIGNMENT_SCHEMA.with_metadata(metadata),
        )
        pq.write_table(table, assignment_path, compression="zstd")
        shard = ShardDefinition(
            shard_id=shard_id,
            assignment_artifact="phase1-compatibility",
            assignment_member=str(assignment_path),
            assignment_sha256=sha256_file(assignment_path),
            unit_count=1,
            estimated_seconds=unit.estimated_seconds,
            merge_group="g000",
        )
        environment = {
            "AURORA_ATTEMPT_ID": f"compat-{unit.unit_key}",
            "AURORA_ARTIFACT_NAME": f"compat-{unit.unit_key}",
        }
        with _temporary_environment(environment):
            return self.workload.run_shard(
                spec,
                shard,
                root,
                None,
            )

    def verify_unit(
        self,
        spec: RunSpec,
        unit: WorkUnit,
        result: Any,
    ) -> UnitVerification:
        del spec
        if not isinstance(result, AttemptManifest):
            return UnitVerification(
                unit_key=unit.unit_key,
                passed=False,
                output_sha256=None,
                failure_codes=("INVALID_PHASE1_ATTEMPT",),
            )
        passed = (
            result.state is TerminalState.COMPLETED
            and result.completed_unit_count == 1
            and result.output_sha256 is not None
        )
        return UnitVerification(
            unit_key=unit.unit_key,
            passed=passed,
            output_sha256=result.output_sha256,
            failure_codes=() if passed else ("PHASE1_UNIT_NOT_COMPLETED",),
        )

    def merge_outputs(
        self,
        inputs: Sequence[Path],
        output_dir: Path,
    ) -> Path:
        return self.workload.merge_group(inputs, output_dir)


def adapt_workload(workload: Any) -> StableWorkloadAdapter:
    """Return a stable adapter without accepting incomplete interfaces."""

    stable_missing = tuple(
        name
        for name in STABLE_WORKLOAD_METHODS
        if not callable(getattr(workload, name, None))
    )
    if not stable_missing:
        return StableWorkloadAdapter(workload)
    legacy_missing = tuple(
        name
        for name in REQUIRED_WORKLOAD_METHODS
        if not callable(getattr(workload, name, None))
    )
    if not legacy_missing:
        return Phase1CompatibilityAdapter(workload)
    raise WorkloadLoadError(
        "workload implements neither stable nor phase-1 interface; "
        "stable missing="
        + ",".join(stable_missing)
        + "; phase1 missing="
        + ",".join(legacy_missing)
    )


def load_stable_workload(reference: str) -> StableWorkloadAdapter:
    """Load an approved Aurora object and expose the stable interface."""

    return adapt_workload(_load_referenced_object(reference))
