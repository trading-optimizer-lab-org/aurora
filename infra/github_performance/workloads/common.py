"""Shared runtime for frozen representative scientific workloads."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.ipc as ipc
import pyarrow.parquet as pq

from aurora.core.metrics import compute_metrics
from aurora.infra.github_performance.audits import (
    DataAccessRecord,
    RuntimeAccessLedger,
    write_runtime_access_ledger,
)
from aurora.infra.github_performance.checkpoint import (
    CheckpointManager,
    raise_controlled_transient_after_checkpoint,
)
from aurora.infra.github_performance.contracts import (
    AttemptManifest,
    CheckpointManifest,
    PilotResult,
    PreparedInputs,
    RunSpec,
    ShardDefinition,
    SmokeResult,
    TerminalState,
    UnitAttemptRecord,
    UnitVerification,
    WorkUnit,
    WorkUnitManifest,
    canonical_sha256,
)
from aurora.infra.github_performance.merge_planner import (
    write_unit_attempt_manifest,
)
from aurora.infra.github_performance.metric_verifier import (
    MetricInputRecord,
    write_metric_inputs,
)
from aurora.infra.github_performance.shard_planner import (
    sha256_file,
    write_work_unit_manifest,
)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def finite(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None


def logical_table_sha256(table: pa.Table) -> str:
    """Hash scientific table content independently of Parquet transport bytes."""

    normalized = table.combine_chunks().replace_schema_metadata(None)
    sink = pa.BufferOutputStream()
    with ipc.new_stream(sink, normalized.schema) as writer:
        writer.write_table(normalized)
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()


def primary_metric_record(
    unit_key: str,
    split: str,
    returns: Sequence[float] | np.ndarray,
    *,
    periods_per_year: int,
) -> MetricInputRecord:
    raw = np.asarray(returns, dtype=np.float64)
    metrics = compute_metrics(raw, ppy=periods_per_year)
    finite_returns = raw[~np.isnan(raw)]
    if len(finite_returns) < 2:
        reported: dict[str, float | int | None] = {
            field: None
            for field in (
                "total_return_pct",
                "cagr_pct",
                "annualized_return_pct",
                "annualized_volatility_pct",
                "sharpe",
                "sortino",
                "max_drawdown_pct",
                "calmar",
                "profit_factor",
                "win_rate",
                "average_return_pct",
                "median_return_pct",
                "final_nav",
            )
        }
    else:
        reported = {
            "total_return_pct": (
                (float(metrics.final_nav) - 1.0) * 100.0
                if math.isfinite(float(metrics.final_nav))
                else None
            ),
            "cagr_pct": finite(metrics.cagr),
            "annualized_return_pct": finite(metrics.cagr),
            "annualized_volatility_pct": (
                float(np.std(finite_returns, ddof=0))
                * math.sqrt(periods_per_year)
                * 100.0
            ),
            "sharpe": finite(metrics.sharpe),
            "sortino": finite(metrics.sortino),
            "max_drawdown_pct": finite(metrics.mdd),
            "calmar": finite(metrics.calmar),
            "profit_factor": finite(metrics.profit_factor),
            "win_rate": finite(metrics.win_rate),
            "average_return_pct": float(np.mean(finite_returns)) * 100.0,
            "median_return_pct": float(np.median(finite_returns)) * 100.0,
            "final_nav": finite(metrics.final_nav),
        }
    reported["period_count_raw"] = int(metrics.n_periods_raw)
    reported["period_count"] = int(metrics.n_periods)
    return MetricInputRecord(
        unit_key=unit_key,
        split=split,
        returns=tuple(float(value) for value in raw),
        periods_per_year=periods_per_year,
        undefined_policy="null",
        reported=reported,
    )


def metrics_for_row(record: MetricInputRecord) -> Mapping[str, Any]:
    return {
        key: value
        for key, value in record.reported.items()
        if key
        in {
            "cagr_pct",
            "sharpe",
            "sortino",
            "max_drawdown_pct",
            "calmar",
            "profit_factor",
            "win_rate",
            "average_return_pct",
            "median_return_pct",
            "period_count",
        }
    }


class FrozenScientificWorkload(ABC):
    """Dual phase-1/phase-2 adapter used by the reusable GitHub workflow."""

    workload_name: str
    workload_family: str
    dataset_name: str
    result_filename: str
    result_schema: pa.Schema
    seed: int
    checkpoint_interval: int = 32

    def describe_contract(self) -> Mapping[str, Any]:
        return {
            "name": self.workload_name,
            "adapter_version": "1",
            "scientific_contract": {
                "workload_family": self.workload_family,
                "dataset": self.dataset_name,
                "selection_split": "train_only",
                "validation_role": "report_only",
                "maximum_date": "2020-12-31",
                "locked_start": "2021-01-01",
                "causal_lag_minimum": 1,
                "scientific_output": self.result_filename,
            },
            "original_candidate_id_preserved": True,
        }

    @abstractmethod
    def _prepare_dataset(self, root: Path) -> tuple[tuple[str, ...], str]:
        """Write immutable inputs and return artifact names plus snapshot hash."""

    @abstractmethod
    def _load_dataset(self, root: Path) -> Any:
        """Load the exact prepared input used by one shard."""

    @abstractmethod
    def _unit_definitions(self) -> Sequence[tuple[str, Mapping[str, Any], float]]:
        """Return stable key, immutable payload and estimated cost."""

    @abstractmethod
    def _evaluate(
        self,
        data: Any,
        unit_key: str,
        parameters: Mapping[str, Any],
        attempt_id: str,
    ) -> tuple[dict[str, Any], tuple[MetricInputRecord, ...]]:
        """Evaluate one logical unit without reading validation for selection."""

    @abstractmethod
    def _access_ranges(self, data: Any) -> Mapping[str, tuple[Any, Any, int]]:
        """Return minimum date, maximum date and rows by split."""

    def prepare_shared_inputs(
        self,
        spec: RunSpec,
        output_dir: Path,
    ) -> PreparedInputs:
        root = Path(output_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        artifact_names, snapshot_hash = self._prepare_dataset(root)
        manifest_path = atomic_json(
            root / f"{self.workload_family}_data_manifest.json",
            {
                "schema_version": "1",
                "dataset": self.dataset_name,
                "seed": self.seed,
                "max_date": "2020-12-31",
                "locked_opened": False,
                "validation_used_for_selection": False,
                "artifact_names": list(artifact_names),
                "snapshot_sha256": snapshot_hash,
            },
        )
        return PreparedInputs(
            manifest_path=str(manifest_path),
            manifest_sha256=sha256_file(manifest_path),
            snapshot_hash=snapshot_hash,
            policy_hash=str(spec.policy["policy_hash"]),
            artifact_names=(manifest_path.name, *artifact_names),
        )

    def prepare(self, spec: RunSpec, output_dir: Path) -> PreparedInputs:
        return self.prepare_shared_inputs(spec, output_dir)

    @staticmethod
    def _prepared_root(prepared: PreparedInputs | None = None) -> Path:
        if prepared is not None:
            return Path(prepared.manifest_path).resolve().parent
        value = os.environ.get("AURORA_PREPARED_ROOT")
        if not value:
            raise RuntimeError("AURORA_PREPARED_ROOT is not set")
        return Path(value).resolve()

    def smoke(
        self,
        spec: RunSpec,
        prepared: PreparedInputs,
    ) -> SmokeResult:
        del spec
        data = self._load_dataset(self._prepared_root(prepared))
        key, parameters, _ = self._unit_definitions()[0]
        row, records = self._evaluate(data, key, parameters, "smoke")
        reasons: list[str] = []
        if row.get("locked_opened") is not False:
            reasons.append("LOCKED_OPENED")
        if row.get("validation_used_for_selection") is not False:
            reasons.append("VALIDATION_USED_FOR_SELECTION")
        if len(records) != 2:
            reasons.append("METRIC_SPLIT_COUNT_MISMATCH")
        return SmokeResult(
            passed=not reasons,
            output_sha256=str(row["unit_output_sha256"]),
            reason_codes=tuple(reasons),
        )

    def pilot(
        self,
        spec: RunSpec,
        prepared: PreparedInputs,
    ) -> PilotResult:
        data = self._load_dataset(self._prepared_root(prepared))
        samples: list[float] = []
        definitions = self._unit_definitions()
        for key, parameters, _ in (
            definitions[0],
            definitions[len(definitions) // 2],
            definitions[-1],
        ):
            started = time.perf_counter()
            self._evaluate(data, key, parameters, "pilot")
            samples.append(max(time.perf_counter() - started, 1e-6))
        return PilotResult(
            queue_seconds=0.0,
            setup_seconds=2.0,
            transfer_fixed_seconds=1.0,
            transfer_per_wave_seconds=0.05,
            checkpoint_seconds=0.01,
            merge_fixed_seconds=0.5,
            merge_per_shard_seconds=0.005,
            verify_seconds=0.25,
            unit_seconds_p50=float(np.percentile(samples, 50)),
            unit_seconds_p95=float(np.percentile(samples, 95)),
            usable_parallelism=min(
                int(spec.performance["planner_max_jobs"]),
                int(spec.performance["confirmed_standard_concurrency"]),
            ),
        )

    def enumerate_units(
        self,
        spec: RunSpec,
        prepared: PreparedInputs,
        output_path: Path,
    ) -> WorkUnitManifest:
        del spec, prepared
        units = []
        for key, parameters, estimate in self._unit_definitions():
            payload = json.dumps(
                parameters,
                sort_keys=True,
                separators=(",", ":"),
            )
            units.append(
                WorkUnit(
                    unit_key=key,
                    estimated_seconds=float(estimate),
                    payload_ref=payload,
                    payload_sha256=hashlib.sha256(
                        payload.encode("utf-8")
                    ).hexdigest(),
                )
            )
        return write_work_unit_manifest(units, Path(output_path))

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
    ) -> Mapping[str, Any]:
        del spec, output_dir
        payload = str(unit.payload_ref)
        if hashlib.sha256(payload.encode("utf-8")).hexdigest() != (
            unit.payload_sha256
        ):
            raise ValueError("unit payload hash mismatch")
        row, records = self._evaluate(
            self._load_dataset(self._prepared_root(prepared)),
            unit.unit_key,
            json.loads(payload),
            "phase2-unit",
        )
        return {"row": row, "metric_records": records}

    def verify_unit(
        self,
        spec: RunSpec,
        unit: WorkUnit,
        result: Mapping[str, Any],
    ) -> UnitVerification:
        del spec
        row = result.get("row")
        if not isinstance(row, Mapping):
            return UnitVerification(
                unit_key=unit.unit_key,
                passed=False,
                output_sha256=None,
                failure_codes=("INVALID_RESULT",),
            )
        scientific = {
            key: value
            for key, value in row.items()
            if key not in {"source_attempt_id", "unit_output_sha256"}
        }
        expected = canonical_sha256(scientific)
        observed = row.get("unit_output_sha256")
        passed = row.get("unit_key") == unit.unit_key and observed == expected
        return UnitVerification(
            unit_key=unit.unit_key,
            passed=passed,
            output_sha256=str(observed) if passed else None,
            failure_codes=() if passed else ("SCIENTIFIC_HASH_MISMATCH",),
        )

    def _assignment_rows(
        self,
        shard: ShardDefinition,
    ) -> list[dict[str, Any]]:
        path = Path(shard.assignment_member)
        if not path.is_file() or sha256_file(path) != shard.assignment_sha256:
            raise ValueError("shard assignment is invalid")
        rows = pq.read_table(path).to_pylist()
        if len(rows) != shard.unit_count:
            raise ValueError("shard assignment count mismatch")
        if any(row["shard_id"] != shard.shard_id for row in rows):
            raise ValueError("shard assignment identity mismatch")
        return sorted(rows, key=lambda row: str(row["unit_key"]))

    def _write_results(
        self,
        rows: Sequence[Mapping[str, Any]],
        path: Path,
    ) -> Path:
        table = pa.Table.from_pylist(
            sorted(rows, key=lambda row: str(row["unit_key"])),
            schema=self.result_schema.with_metadata(
                {b"schema_version": b"1", b"sorted_by": b"unit_key"}
            ),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        pq.write_table(table, temporary, compression="zstd", version="2.6")
        temporary.replace(path)
        return path

    def _checkpoint_rows(
        self,
        checkpoint: CheckpointManifest | None,
        shard: ShardDefinition,
    ) -> list[dict[str, Any]]:
        if checkpoint is None:
            return []
        if checkpoint.shard_id != shard.shard_id:
            raise ValueError("checkpoint belongs to another shard")
        path = Path(checkpoint.payload_path)
        if not path.is_file() or sha256_file(path) != checkpoint.payload_sha256:
            raise ValueError("checkpoint payload is invalid")
        return pq.read_table(path, schema=self.result_schema).to_pylist()

    def run_shard(
        self,
        spec: RunSpec,
        shard: ShardDefinition,
        output_dir: Path,
        checkpoint: CheckpointManifest | None,
    ) -> AttemptManifest:
        root = Path(output_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        attempt_id = os.environ["AURORA_ATTEMPT_ID"]
        artifact_name = os.environ["AURORA_ARTIFACT_NAME"]
        data = self._load_dataset(self._prepared_root())
        assignments = self._assignment_rows(shard)
        rows = self._checkpoint_rows(checkpoint, shard)
        completed = {str(row["unit_key"]) for row in rows}
        definitions = {
            key: parameters
            for key, parameters, _ in self._unit_definitions()
        }
        metric_records: list[MetricInputRecord] = []
        for row in rows:
            key = str(row["unit_key"])
            replay, replay_metrics = self._evaluate(
                data,
                key,
                definitions[key],
                attempt_id,
            )
            if replay["unit_output_sha256"] != row["unit_output_sha256"]:
                raise ValueError("checkpoint scientific output changed")
            metric_records.extend(replay_metrics)
        checkpoint_manager = CheckpointManager(root / "checkpoint")
        latest_checkpoint: CheckpointManifest | None = None
        for assignment in assignments:
            key = str(assignment["unit_key"])
            if key in completed:
                continue
            payload = str(assignment["payload_ref"])
            if hashlib.sha256(payload.encode("utf-8")).hexdigest() != (
                assignment["payload_sha256"]
            ):
                raise ValueError(f"unit payload hash mismatch: {key}")
            row, records = self._evaluate(
                data,
                key,
                json.loads(payload),
                attempt_id,
            )
            rows.append(row)
            metric_records.extend(records)
            completed.add(key)
            if (
                len(rows) % self.checkpoint_interval == 0
                and len(rows) < len(assignments)
            ):
                checkpoint_path = self._write_results(
                    rows,
                    root / "checkpoint_rows.parquet",
                )
                latest_checkpoint = checkpoint_manager.commit(
                    shard.shard_id,
                    attempt_id,
                    len(rows),
                    key,
                    checkpoint_path,
                )
                raise_controlled_transient_after_checkpoint(
                    shard.shard_id,
                    len(rows),
                    latest_checkpoint,
                )
        output_path = self._write_results(rows, root / self.result_filename)
        unit_attempt_path = write_unit_attempt_manifest(
            (
                UnitAttemptRecord(
                    unit_key=str(row["unit_key"]),
                    shard_id=shard.shard_id,
                    attempt_id=attempt_id,
                    state=TerminalState.COMPLETED,
                    output_sha256=str(row["unit_output_sha256"]),
                    reason_code=None,
                )
                for row in rows
            ),
            root / "unit_attempts.parquet",
        )
        access_records = []
        for split, (minimum, maximum, row_count) in self._access_ranges(
            data
        ).items():
            access_records.append(
                DataAccessRecord(
                    source=f"snapshot:{self.dataset_name}",
                    partition=split,
                    minimum_date=minimum,
                    maximum_date=maximum,
                    row_count=int(row_count),
                    split=split,
                    purpose="selection" if split == "train" else "report",
                    locked=False,
                    shard_id=shard.shard_id,
                    attempt_id=attempt_id,
                )
            )
        access_path = write_runtime_access_ledger(
            root / "runtime_access_ledger.parquet",
            RuntimeAccessLedger(records=tuple(access_records)),
        )
        metric_path = write_metric_inputs(
            root / "metric_verification_inputs.parquet",
            metric_records,
        )
        return AttemptManifest(
            shard_id=shard.shard_id,
            attempt_id=attempt_id,
            state=TerminalState.COMPLETED,
            spec_hash=canonical_sha256(spec),
            policy_hash=str(spec.policy["policy_hash"]),
            snapshot_hash=str(spec.data["snapshot_hash"]),
            code_sha=str(spec.identity["code_sha"]),
            dependency_lock_sha256=str(
                spec.execution["dependency_lock_sha256"]
            ),
            capacity_profile_sha256=str(
                spec.performance["capacity_profile_sha256"]
            ),
            output_sha256=sha256_file(output_path),
            reason_code=None,
            artifact_name=artifact_name,
            unit_attempts_path=unit_attempt_path.name,
            unit_attempts_sha256=sha256_file(unit_attempt_path),
            checkpoint_artifact=(
                latest_checkpoint.artifact_name
                if latest_checkpoint is not None
                else None
            ),
            completed_unit_count=len(rows),
            output_rows=len(rows),
            output_bytes=output_path.stat().st_size,
            runtime_access_ledger_path=access_path.name,
            runtime_access_ledger_sha256=sha256_file(access_path),
            metric_inputs_path=metric_path.name,
            metric_inputs_sha256=sha256_file(metric_path),
        )

    def merge_outputs(
        self,
        inputs: Sequence[Path],
        output_dir: Path,
    ) -> Path:
        rows_by_key: dict[str, dict[str, Any]] = {}
        for source in sorted(Path(path) for path in inputs):
            candidates = (
                (source,)
                if source.is_file() and source.name == self.result_filename
                else tuple(source.rglob(self.result_filename))
            )
            if len(candidates) != 1:
                raise ValueError(
                    f"expected one {self.result_filename} in {source}"
                )
            for row in pq.read_table(
                candidates[0],
                schema=self.result_schema,
            ).to_pylist():
                key = str(row["unit_key"])
                previous = rows_by_key.get(key)
                if (
                    previous is not None
                    and previous["unit_output_sha256"]
                    != row["unit_output_sha256"]
                ):
                    raise ValueError(f"conflicting result for {key}")
                rows_by_key[key] = row
        root = Path(output_dir)
        output = self._write_results(
            tuple(rows_by_key.values()),
            root / self.result_filename,
        )
        self._write_reduction(tuple(rows_by_key.values()), root)
        return output

    def merge_group(
        self,
        inputs: Sequence[Path],
        output_dir: Path,
    ) -> Path:
        return self.merge_outputs(inputs, output_dir)

    def _write_reduction(
        self,
        rows: Sequence[Mapping[str, Any]],
        root: Path,
    ) -> None:
        atomic_json(
            root / f"{self.workload_family}_summary.json",
            {
                "schema_version": "1",
                "workload_family": self.workload_family,
                "rows": len(rows),
                "locked_opened": False,
                "validation_used_for_selection": False,
            },
        )
