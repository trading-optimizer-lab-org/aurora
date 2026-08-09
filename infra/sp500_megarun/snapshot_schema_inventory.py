"""Fail-closed schema inventory for the physical 1993-2010 train snapshot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


class SnapshotSchemaInventoryError(ValueError):
    """Raised when an inventory target is not the closed train partition."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_TRAIN_END = pd.Timestamp("2010-12-31")


def build_train_snapshot_schema_inventory(
    snapshot_dir: str | Path,
    *,
    output_path: str | Path,
) -> dict[str, Any]:
    """Describe schemas only; never sample values or mount validation data."""

    snapshot = Path(snapshot_dir)
    if snapshot.name != _TRAIN_PARTITION:
        raise SnapshotSchemaInventoryError("TRAIN_PARTITION_REQUIRED")
    parquet_paths = sorted(snapshot.glob("D_*.parquet"))
    if not parquet_paths:
        raise SnapshotSchemaInventoryError("EMPTY_TRAIN_SNAPSHOT")

    datasets: dict[str, dict[str, Any]] = {}
    maximum_dates: list[pd.Timestamp] = []
    for path in parquet_paths:
        dataset_id = path.stem
        frame = pd.read_parquet(path)
        if "date" not in frame:
            raise SnapshotSchemaInventoryError(f"DATE_COLUMN_MISSING:{dataset_id}")
        dates = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
        if dates.isna().any():
            raise SnapshotSchemaInventoryError(f"INVALID_DATE:{dataset_id}")
        if dates.gt(_TRAIN_END).any():
            raise SnapshotSchemaInventoryError(f"NON_TRAIN_ROW:{dataset_id}")
        if frame.empty:
            raise SnapshotSchemaInventoryError(f"EMPTY_DATASET:{dataset_id}")
        maximum_dates.append(dates.max())
        datasets[dataset_id] = {
            "rows": int(len(frame)),
            "minimum_date": dates.min().date().isoformat(),
            "maximum_date": dates.max().date().isoformat(),
            "columns": [str(column) for column in frame.columns],
            "dtypes": {
                str(column): str(frame[column].dtype) for column in frame.columns
            },
            "numeric_columns": [
                str(column)
                for column in frame.columns
                if column != "date" and pd.api.types.is_numeric_dtype(frame[column])
            ],
            "non_null_counts": {
                str(column): int(frame[column].notna().sum()) for column in frame.columns
            },
        }

    report: dict[str, Any] = {
        "schema_version": 1,
        "ready": True,
        "scope": "train_snapshot_schema_only",
        "partition": _TRAIN_PARTITION,
        "dataset_count": len(datasets),
        "maximum_observation_date": max(maximum_dates).date().isoformat(),
        "validation_opened": False,
        "locked_opened": False,
        "datasets": datasets,
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = ["SnapshotSchemaInventoryError", "build_train_snapshot_schema_inventory"]
