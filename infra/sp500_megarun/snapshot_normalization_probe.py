"""Train-only structural probe for raw columns that still need normalization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import pandas as pd


class SnapshotNormalizationProbeError(ValueError):
    """Raised when the probe would leave the physical train partition."""


_TRAIN_PARTITION = "train_snapshot_1993_2010"
_TRAIN_END = pd.Timestamp("2010-12-31")
_CATEGORY_COLUMNS = {
    "series_id",
    "series_name",
    "source_sheet",
    "resource_id",
    "Market and Exchange Names",
    "CFTC Contract Market Code",
    "CFTC Commodity Code",
}


def _samples(values: pd.Series, *, limit: int = 5) -> list[str]:
    cleaned = values.dropna().astype(str)
    cleaned = cleaned.loc[cleaned.str.strip().ne("")]
    return cleaned.drop_duplicates().iloc[:limit].tolist()


def build_train_snapshot_normalization_probe(
    snapshot_dir: str | Path,
    *,
    dataset_ids: Sequence[str],
    output_path: str | Path,
) -> dict[str, Any]:
    """Report coercibility and identifiers without evaluating any strategy."""

    snapshot = Path(snapshot_dir)
    if snapshot.name != _TRAIN_PARTITION:
        raise SnapshotNormalizationProbeError("TRAIN_PARTITION_REQUIRED")
    if not dataset_ids:
        raise SnapshotNormalizationProbeError("DATASET_IDS_REQUIRED")

    datasets: dict[str, dict[str, Any]] = {}
    for dataset_id in dataset_ids:
        target = snapshot / f"{dataset_id}.parquet"
        if not target.is_file():
            raise SnapshotNormalizationProbeError(f"DATASET_MISSING:{dataset_id}")
        frame = pd.read_parquet(target)
        if "date" not in frame:
            raise SnapshotNormalizationProbeError(f"DATE_COLUMN_MISSING:{dataset_id}")
        dates = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
        if dates.isna().any():
            raise SnapshotNormalizationProbeError(f"INVALID_DATE:{dataset_id}")
        if dates.gt(_TRAIN_END).any():
            raise SnapshotNormalizationProbeError(f"NON_TRAIN_ROW:{dataset_id}")

        coercible: dict[str, int] = {}
        samples: dict[str, list[str]] = {}
        categories: dict[str, list[str]] = {}
        category_counts: dict[str, int] = {}
        for column in frame.columns:
            if column == "date":
                continue
            coercible[str(column)] = int(
                pd.to_numeric(frame[column], errors="coerce").notna().sum()
            )
            samples[str(column)] = _samples(frame[column])
            if str(column) in _CATEGORY_COLUMNS:
                unique = sorted(
                    frame[column].dropna().astype(str).str.strip().loc[lambda row: row.ne("")].unique()
                )
                category_counts[str(column)] = len(unique)
                categories[str(column)] = unique[:500]
        datasets[dataset_id] = {
            "rows": int(len(frame)),
            "minimum_date": dates.min().date().isoformat(),
            "maximum_date": dates.max().date().isoformat(),
            "numeric_coercible_counts": coercible,
            "sample_non_null": samples,
            "category_unique_counts": category_counts,
            "category_values": categories,
        }

    report: dict[str, Any] = {
        "schema_version": 1,
        "ready": True,
        "scope": "train_snapshot_normalization_probe",
        "partition": _TRAIN_PARTITION,
        "dataset_count": len(datasets),
        "validation_opened": False,
        "locked_opened": False,
        "datasets": datasets,
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


__all__ = [
    "SnapshotNormalizationProbeError",
    "build_train_snapshot_normalization_probe",
]
