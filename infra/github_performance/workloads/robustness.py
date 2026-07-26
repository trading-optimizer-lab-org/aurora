"""Compute and merge-heavy deterministic block-bootstrap workload."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.github_performance.metric_verifier import MetricInputRecord
from aurora.infra.github_performance.shard_planner import sha256_file
from aurora.infra.github_performance.workloads.common import (
    FrozenScientificWorkload,
    atomic_json,
    metrics_for_row,
    primary_metric_record,
)


SEED = 20_260_803
METRIC_FIELDS = (
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
)


def _result_schema() -> pa.Schema:
    fields = [
        pa.field("unit_key", pa.string(), nullable=False),
        pa.field("source_attempt_id", pa.string(), nullable=False),
        pa.field("family", pa.string(), nullable=False),
        pa.field("block_length", pa.int32(), nullable=False),
        pa.field("bootstrap_samples", pa.int32(), nullable=False),
        pa.field("seed_offset", pa.int32(), nullable=False),
        pa.field("return_scale", pa.float64(), nullable=False),
        pa.field("train_p05", pa.float64()),
        pa.field("train_median", pa.float64()),
        pa.field("train_p95", pa.float64()),
        pa.field("validation_p05", pa.float64()),
        pa.field("validation_median", pa.float64()),
        pa.field("validation_p95", pa.float64()),
    ]
    for split in ("train", "validation"):
        for name in METRIC_FIELDS:
            kind = pa.int32() if name == "period_count" else pa.float64()
            fields.append(pa.field(f"{split}_{name}", kind))
    fields.extend(
        [
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
    return pa.schema(fields)


def _generate_returns() -> pd.DataFrame:
    train_dates = pd.bdate_range("1995-01-02", "2010-12-31")
    validation_dates = pd.bdate_range("2011-01-03", "2020-12-31")
    dates = train_dates.append(validation_dates)
    rng = np.random.default_rng(SEED)
    phase = np.linspace(0.0, 18.0 * math.pi, len(dates))
    returns = (
        rng.normal(0.00025, 0.0105, len(dates))
        + 0.00018 * np.sin(phase)
    )
    return pd.DataFrame(
        {
            "date": dates,
            "return": np.clip(returns, -0.2, 0.2),
            "period": (
                ["train"] * len(train_dates)
                + ["validation"] * len(validation_dates)
            ),
        }
    )


def _block_bootstrap_distribution(
    returns: np.ndarray,
    *,
    block_length: int,
    samples: int,
    seed: int,
    scale: float,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    size = len(returns)
    blocks_needed = math.ceil(size / block_length)
    starts = rng.integers(0, size, size=(samples, blocks_needed))
    offsets = np.arange(block_length, dtype=np.int64)
    indices = (starts[..., None] + offsets) % size
    sampled = returns[indices.reshape(samples, -1)[:, :size]]
    return sampled.mean(axis=1) * 252.0 * scale


class RobustnessWorkload(FrozenScientificWorkload):
    workload_name = "aurora_statistical_robustness"
    workload_family = "robustness"
    dataset_name = "frozen_robustness_return_series"
    result_filename = "robustness_results.parquet"
    result_schema = _result_schema()
    seed = SEED

    def _prepare_dataset(self, root: Path) -> tuple[tuple[str, ...], str]:
        path = root / "robustness_returns.parquet"
        pq.write_table(
            pa.Table.from_pandas(_generate_returns(), preserve_index=False),
            path,
            compression="zstd",
            version="2.6",
        )
        return (path.name,), sha256_file(path)

    def _load_dataset(self, root: Path) -> pd.DataFrame:
        path = Path(root) / "robustness_returns.parquet"
        frame = pq.read_table(
            path,
            columns=["date", "return", "period"],
        ).to_pandas()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values("date", kind="mergesort")
        if frame["date"].max() > pd.Timestamp("2020-12-31"):
            raise ValueError("robustness workload crossed locked boundary")
        return frame

    def _unit_definitions(
        self,
    ) -> Sequence[tuple[str, Mapping[str, Any], float]]:
        definitions = []
        for block_length in (5, 10, 20, 40):
            for samples in (32, 64, 96, 128):
                for seed_offset in range(8):
                    for return_scale in (0.8, 1.0, 1.2, 1.4):
                        definitions.append(
                            (
                                (
                                    f"robust-b{block_length:02d}-"
                                    f"n{samples:03d}-s{seed_offset:02d}-"
                                    f"x{return_scale:.1f}"
                                ),
                                {
                                    "block_length": block_length,
                                    "bootstrap_samples": samples,
                                    "seed_offset": seed_offset,
                                    "return_scale": return_scale,
                                },
                                0.02 + samples * block_length / 1_000_000.0,
                            )
                        )
        if len(definitions) != 512:
            raise AssertionError("robustness workload must have 512 units")
        return tuple(definitions)

    def _evaluate(
        self,
        data: pd.DataFrame,
        unit_key: str,
        parameters: Mapping[str, Any],
        attempt_id: str,
    ) -> tuple[dict[str, Any], tuple[MetricInputRecord, ...]]:
        block_length = int(parameters["block_length"])
        samples = int(parameters["bootstrap_samples"])
        seed_offset = int(parameters["seed_offset"])
        scale = float(parameters["return_scale"])
        row: dict[str, Any] = {
            "unit_key": unit_key,
            "source_attempt_id": attempt_id,
            "family": self.workload_family,
            "block_length": block_length,
            "bootstrap_samples": samples,
            "seed_offset": seed_offset,
            "return_scale": scale,
        }
        records = []
        for split_index, split in enumerate(("train", "validation")):
            source = data.loc[
                data["period"] == split,
                "return",
            ].to_numpy(dtype=np.float64)
            distribution = _block_bootstrap_distribution(
                source,
                block_length=block_length,
                samples=samples,
                seed=SEED + seed_offset * 17 + split_index,
                scale=scale,
            )
            row[f"{split}_p05"] = float(np.quantile(distribution, 0.05))
            row[f"{split}_median"] = float(np.median(distribution))
            row[f"{split}_p95"] = float(np.quantile(distribution, 0.95))
            record = primary_metric_record(
                unit_key,
                split,
                distribution,
                periods_per_year=1,
            )
            records.append(record)
            row.update(
                {
                    f"{split}_{key}": value
                    for key, value in metrics_for_row(record).items()
                }
            )
        row.update(
            {
                "selected_on": "train_only",
                "causal_lag_periods": 1,
                "locked_opened": False,
                "validation_used_for_selection": False,
            }
        )
        row["unit_output_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in row.items()
                if key != "source_attempt_id"
            }
        )
        return row, tuple(records)

    def _access_ranges(
        self,
        data: pd.DataFrame,
    ) -> Mapping[str, tuple[Any, Any, int]]:
        result = {}
        for split in ("train", "validation"):
            dates = data.loc[data["period"] == split, "date"]
            result[split] = (
                dates.min().date(),
                dates.max().date(),
                len(dates),
            )
        return result

    def _write_reduction(
        self,
        rows: Sequence[Mapping[str, Any]],
        root: Path,
    ) -> None:
        if rows:
            table = pa.Table.from_pylist(
                list(rows),
                schema=self.result_schema,
            )
            medians = np.asarray(
                table.column("validation_median").to_pylist(),
                dtype=np.float64,
            )
            best_index = int(np.nanargmax(medians))
            best_unit = str(table.column("unit_key")[best_index].as_py())
            reduction = {
                "validation_median_p05": float(np.quantile(medians, 0.05)),
                "validation_median_median": float(np.median(medians)),
                "validation_median_p95": float(np.quantile(medians, 0.95)),
                "best_train_selected_unit": best_unit,
            }
        else:
            reduction = {
                "validation_median_p05": None,
                "validation_median_median": None,
                "validation_median_p95": None,
                "best_train_selected_unit": None,
            }
        atomic_json(
            root / "robustness_reduction_summary.json",
            {
                "schema_version": "1",
                "workload_family": self.workload_family,
                "rows": len(rows),
                "locked_opened": False,
                "validation_used_for_selection": False,
                **reduction,
            },
        )


WORKLOAD = RobustnessWorkload()
