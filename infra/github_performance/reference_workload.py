"""Deterministic real-engine workload for end-to-end GitHub validation."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from aurora.core.costs import CostModel
from aurora.core.engine import run_backtest
from aurora.infra.github_performance.checkpoint import CheckpointManager
from aurora.infra.github_performance.audits import (
    DataAccessRecord,
    RuntimeAccessLedger,
    write_runtime_access_ledger,
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
    WorkUnit,
    WorkUnitManifest,
    canonical_sha256,
)
from aurora.infra.github_performance.merge_planner import (
    write_unit_attempt_manifest,
)
from aurora.infra.github_performance.shard_planner import (
    sha256_file,
    write_work_unit_manifest,
)


REFERENCE_SEED = 20_260_725
TRAIN_OBSERVATIONS = 4_032
VALIDATION_OBSERVATIONS = 2_520
REFERENCE_COSTS = CostModel(
    commission_bps=0.5,
    spread_bps=0.5,
    slippage_bps=0.5,
)
RESULT_SCHEMA = pa.schema(
    [
        pa.field("unit_key", pa.string(), nullable=False),
        pa.field("source_attempt_id", pa.string(), nullable=False),
        pa.field("fast_window", pa.int32(), nullable=False),
        pa.field("slow_window", pa.int32(), nullable=False),
        pa.field("train_cagr", pa.float64()),
        pa.field("train_sharpe", pa.float64()),
        pa.field("train_calmar", pa.float64()),
        pa.field("train_max_drawdown", pa.float64()),
        pa.field("validation_cagr", pa.float64()),
        pa.field("validation_sharpe", pa.float64()),
        pa.field("validation_calmar", pa.float64()),
        pa.field("validation_max_drawdown", pa.float64()),
        pa.field("selected_on", pa.string(), nullable=False),
        pa.field("causal_lag_periods", pa.int32(), nullable=False),
        pa.field("locked_opened", pa.bool_(), nullable=False),
        pa.field(
            "validation_used_for_selection",
            pa.bool_(),
            nullable=False,
        ),
        pa.field("unit_output_sha256", pa.string(), nullable=False),
    ]
)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _write_results(rows: Sequence[Mapping[str, Any]], path: Path) -> Path:
    table = pa.Table.from_pylist(
        sorted(rows, key=lambda row: str(row["unit_key"])),
        schema=RESULT_SCHEMA.with_metadata(
            {
                b"schema_version": b"1",
                b"sorted_by": b"unit_key",
            }
        ),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", version="2.6")
    temporary.replace(path)
    return path


def _sample_calendar(
    start: str,
    end: str,
    observations: int,
) -> pd.DatetimeIndex:
    calendar = pd.bdate_range(start=start, end=end)
    if len(calendar) < observations:
        raise ValueError("reference period has too few business days")
    offsets = np.linspace(
        0,
        len(calendar) - 1,
        observations,
        dtype=np.int64,
    )
    selected = calendar[offsets]
    if len(selected.unique()) != observations:
        raise AssertionError("reference calendar sampling produced duplicates")
    return selected


def _generate_prices() -> pd.DataFrame:
    train_dates = _sample_calendar(
        "1995-01-01",
        "2010-12-31",
        TRAIN_OBSERVATIONS,
    )
    validation_dates = _sample_calendar(
        "2011-01-01",
        "2020-12-31",
        VALIDATION_OBSERVATIONS,
    )
    dates = train_dates.append(validation_dates)
    rng = np.random.default_rng(REFERENCE_SEED)
    phase = np.linspace(0.0, 24.0 * math.pi, len(dates))
    returns = (
        rng.normal(0.00022, 0.0095, len(dates))
        + 0.00018 * np.sin(phase)
        + 0.00008 * np.cos(phase / 3.0)
    )
    returns = np.clip(returns, -0.18, 0.18)
    close = 100.0 * np.exp(np.cumsum(np.log1p(returns)))
    return pd.DataFrame(
        {
            "date": dates,
            "close": close,
            "period": (
                ["train"] * TRAIN_OBSERVATIONS
                + ["validation"] * VALIDATION_OBSERVATIONS
            ),
        }
    )


def _load_prices(root: Path) -> pd.DataFrame:
    path = Path(root) / "reference_prices.parquet"
    table = pq.read_table(path, columns=["date", "close", "period"])
    frame = table.to_pandas()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date", kind="mergesort")
    if frame["date"].max() > pd.Timestamp("2020-12-31"):
        raise ValueError("reference data crossed the locked boundary")
    return frame


def _signal(prices: pd.Series, fast: int, slow: int) -> np.ndarray:
    fast_mean = prices.rolling(fast, min_periods=fast).mean()
    slow_mean = prices.rolling(slow, min_periods=slow).mean()
    signal = np.where(fast_mean > slow_mean, 1.0, 0.0)
    signal[np.isnan(fast_mean) | np.isnan(slow_mean)] = 0.0
    return signal


def _finite(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None


def _unit_payload(fast: int, slow: int) -> str:
    return json.dumps(
        {"fast_window": fast, "slow_window": slow},
        sort_keys=True,
        separators=(",", ":"),
    )


def _evaluate(
    frame: pd.DataFrame,
    unit_key: str,
    fast: int,
    slow: int,
    attempt_id: str,
) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    for period in ("train", "validation"):
        selected = frame.loc[frame["period"] == period]
        prices = pd.Series(
            selected["close"].to_numpy(dtype=float),
            index=pd.DatetimeIndex(selected["date"]),
            name="SPY_REFERENCE",
        )
        result = run_backtest(
            prices,
            _signal,
            costs=REFERENCE_COSTS,
            ppy=252,
            fast=fast,
            slow=slow,
        )
        outputs[f"{period}_cagr"] = _finite(result.metrics.cagr)
        outputs[f"{period}_sharpe"] = _finite(result.metrics.sharpe)
        outputs[f"{period}_calmar"] = _finite(result.metrics.calmar)
        outputs[f"{period}_max_drawdown"] = _finite(result.metrics.mdd)
    row: dict[str, Any] = {
        "unit_key": unit_key,
        "source_attempt_id": attempt_id,
        "fast_window": fast,
        "slow_window": slow,
        **outputs,
        "selected_on": "train_only",
        "causal_lag_periods": 1,
        "locked_opened": False,
        "validation_used_for_selection": False,
    }
    scientific_output = {
        key: value
        for key, value in row.items()
        if key != "source_attempt_id"
    }
    row["unit_output_sha256"] = canonical_sha256(scientific_output)
    return row


def _prepared_root(prepared: PreparedInputs | None = None) -> Path:
    if prepared is not None:
        return Path(prepared.manifest_path).resolve().parent
    value = os.environ.get("AURORA_PREPARED_ROOT")
    if not value:
        raise RuntimeError("AURORA_PREPARED_ROOT is not set")
    return Path(value).resolve()


def _assignment_rows(shard: ShardDefinition) -> list[dict[str, Any]]:
    path = Path(shard.assignment_member)
    if not path.is_file() or sha256_file(path) != shard.assignment_sha256:
        raise ValueError("reference shard assignment is invalid")
    table = pq.read_table(path)
    rows = table.to_pylist()
    if len(rows) != shard.unit_count:
        raise ValueError("reference shard assignment count mismatch")
    if any(row["shard_id"] != shard.shard_id for row in rows):
        raise ValueError("reference shard assignment identity mismatch")
    return sorted(rows, key=lambda row: row["unit_key"])


def _checkpoint_rows(
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
    return pq.read_table(path, schema=RESULT_SCHEMA).to_pylist()


class ReferenceWorkload:
    """Real Aurora engine adapter with deterministic generated inputs."""

    def prepare(self, spec: RunSpec, output_dir: Path) -> PreparedInputs:
        root = Path(output_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        frame = _generate_prices()
        prices_path = root / "reference_prices.parquet"
        table = pa.Table.from_pandas(frame, preserve_index=False)
        pq.write_table(table, prices_path, compression="zstd", version="2.6")
        prices_hash = sha256_file(prices_path)
        manifest_path = _atomic_json(
            root / "reference_data_manifest.json",
            {
                "schema_version": "1",
                "dataset": "deterministic_spy_reference",
                "seed": REFERENCE_SEED,
                "train_observations": TRAIN_OBSERVATIONS,
                "validation_observations": VALIDATION_OBSERVATIONS,
                "max_date": "2020-12-31",
                "locked_opened": False,
                "prices_path": prices_path.name,
                "prices_sha256": prices_hash,
            },
        )
        return PreparedInputs(
            manifest_path=str(manifest_path),
            manifest_sha256=sha256_file(manifest_path),
            snapshot_hash=prices_hash,
            policy_hash=str(spec.policy["policy_hash"]),
            artifact_names=(
                manifest_path.name,
                prices_path.name,
            ),
        )

    def smoke(
        self,
        spec: RunSpec,
        prepared: PreparedInputs,
    ) -> SmokeResult:
        frame = _load_prices(_prepared_root(prepared))
        reasons: list[str] = []
        if len(frame.loc[frame["period"] == "train"]) != TRAIN_OBSERVATIONS:
            reasons.append("TRAIN_OBSERVATION_COUNT_MISMATCH")
        if (
            len(frame.loc[frame["period"] == "validation"])
            != VALIDATION_OBSERVATIONS
        ):
            reasons.append("VALIDATION_OBSERVATION_COUNT_MISMATCH")
        row = _evaluate(frame, "smoke", 10, 100, "smoke")
        return SmokeResult(
            passed=not reasons,
            output_sha256=canonical_sha256(row),
            reason_codes=tuple(reasons),
        )

    def pilot(
        self,
        spec: RunSpec,
        prepared: PreparedInputs,
    ) -> PilotResult:
        frame = _load_prices(_prepared_root(prepared))
        samples: list[float] = []
        for index, (fast, slow) in enumerate(
            ((5, 50), (15, 100), (30, 170))
        ):
            started = time.perf_counter()
            _evaluate(frame, f"pilot-{index}", fast, slow, "pilot")
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
        units: list[WorkUnit] = []
        for fast in range(4, 36):
            for slow in range(50, 178, 4):
                payload = _unit_payload(fast, slow)
                key = f"ref-f{fast:03d}-s{slow:03d}"
                units.append(
                    WorkUnit(
                        unit_key=key,
                        estimated_seconds=0.01 + slow / 100_000.0,
                        payload_ref=payload,
                        payload_sha256=hashlib.sha256(
                            payload.encode("utf-8")
                        ).hexdigest(),
                    )
                )
        if len(units) != 1_024:
            raise AssertionError("reference workload must have 1,024 units")
        return write_work_unit_manifest(units, Path(output_path))

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
        frame = _load_prices(_prepared_root())
        assignments = _assignment_rows(shard)
        rows = _checkpoint_rows(checkpoint, shard)
        completed = {row["unit_key"] for row in rows}
        checkpoint_manager = CheckpointManager(root / "checkpoint")
        latest_checkpoint: CheckpointManifest | None = None
        for assignment in assignments:
            unit_key = str(assignment["unit_key"])
            if unit_key in completed:
                continue
            payload = str(assignment["payload_ref"])
            if (
                hashlib.sha256(payload.encode("utf-8")).hexdigest()
                != assignment["payload_sha256"]
            ):
                raise ValueError(f"unit payload hash mismatch: {unit_key}")
            parameters = json.loads(payload)
            rows.append(
                _evaluate(
                    frame,
                    unit_key,
                    int(parameters["fast_window"]),
                    int(parameters["slow_window"]),
                    attempt_id,
                )
            )
            completed.add(unit_key)
            if len(rows) % 32 == 0 and len(rows) < len(assignments):
                checkpoint_path = _write_results(
                    rows,
                    root / "checkpoint_rows.parquet",
                )
                latest_checkpoint = checkpoint_manager.commit(
                    shard.shard_id,
                    attempt_id,
                    len(rows),
                    unit_key,
                    checkpoint_path,
                )
        output_path = _write_results(
            rows,
            root / "reference_results.parquet",
        )
        unit_attempt_path = write_unit_attempt_manifest(
            (
                UnitAttemptRecord(
                    unit_key=str(row["unit_key"]),
                    shard_id=shard.shard_id,
                    attempt_id=str(row["source_attempt_id"]),
                    state=TerminalState.COMPLETED,
                    output_sha256=str(row["unit_output_sha256"]),
                    reason_code=None,
                )
                for row in rows
            ),
            root / "unit_attempts.parquet",
        )
        train = frame.loc[frame["period"] == "train", "date"]
        validation = frame.loc[frame["period"] == "validation", "date"]
        access_path = write_runtime_access_ledger(
            root / "runtime_access_ledger.parquet",
            RuntimeAccessLedger(
                records=(
                    DataAccessRecord(
                        source="snapshot:deterministic_spy_reference",
                        partition="train",
                        minimum_date=train.min().date(),
                        maximum_date=train.max().date(),
                        row_count=len(train),
                        split="train",
                        purpose="selection",
                        locked=False,
                        shard_id=shard.shard_id,
                        attempt_id=attempt_id,
                    ),
                    DataAccessRecord(
                        source="snapshot:deterministic_spy_reference",
                        partition="validation",
                        minimum_date=validation.min().date(),
                        maximum_date=validation.max().date(),
                        row_count=len(validation),
                        split="validation",
                        purpose="report",
                        locked=False,
                        shard_id=shard.shard_id,
                        attempt_id=attempt_id,
                    ),
                )
            ),
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
        )

    def merge_group(
        self,
        inputs: Sequence[Path],
        output_dir: Path,
    ) -> Path:
        rows_by_key: dict[str, dict[str, Any]] = {}
        for directory in sorted(Path(path) for path in inputs):
            candidates = sorted(directory.rglob("reference_results.parquet"))
            if len(candidates) != 1:
                raise ValueError(
                    f"expected one reference result in {directory}"
                )
            table = pq.read_table(candidates[0], schema=RESULT_SCHEMA)
            for row in table.to_pylist():
                key = str(row["unit_key"])
                previous = rows_by_key.get(key)
                if (
                    previous is not None
                    and previous["unit_output_sha256"]
                    != row["unit_output_sha256"]
                ):
                    raise ValueError(f"conflicting result for {key}")
                rows_by_key[key] = row
        output = _write_results(
            tuple(rows_by_key.values()),
            Path(output_dir) / "reference_results.parquet",
        )
        _atomic_json(
            Path(output_dir) / "reference_results_summary.json",
            {
                "schema_version": "1",
                "rows": len(rows_by_key),
                "locked_opened": False,
                "validation_used_for_selection": False,
                "results_sha256": sha256_file(output),
            },
        )
        return output


WORKLOAD = ReferenceWorkload()
