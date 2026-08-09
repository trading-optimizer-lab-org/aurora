from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest


def _inventory_api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.snapshot_schema_inventory"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"snapshot schema inventory implementation is missing: {exc}")


def _write_snapshot(root: Path, *, include_2011: bool = False) -> Path:
    snapshot = root / "train_snapshot_1993_2010"
    snapshot.mkdir()
    dates = [pd.Timestamp("2010-12-30"), pd.Timestamp("2010-12-31")]
    if include_2011:
        dates.append(pd.Timestamp("2011-01-03"))
    pd.DataFrame(
        {
            "date": dates,
            "close": [100.0, 101.0, *([102.0] if include_2011 else [])],
            "label": ["a", "b", *(["c"] if include_2011 else [])],
        }
    ).to_parquet(snapshot / "D_SPY.parquet", index=False)
    return snapshot


def test_inventory_reports_columns_types_and_non_null_counts(tmp_path: Path) -> None:
    api = _inventory_api()
    snapshot = _write_snapshot(tmp_path)
    output = tmp_path / "schema_inventory.json"

    report = api.build_train_snapshot_schema_inventory(snapshot, output_path=output)

    assert report["ready"] is True
    assert report["dataset_count"] == 1
    assert report["maximum_observation_date"] == "2010-12-31"
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    row = report["datasets"]["D_SPY"]
    assert row["columns"] == ["date", "close", "label"]
    assert row["numeric_columns"] == ["close"]
    assert row["non_null_counts"] == {"date": 2, "close": 2, "label": 2}
    assert output.exists()


def test_inventory_rejects_non_train_rows(tmp_path: Path) -> None:
    api = _inventory_api()
    snapshot = _write_snapshot(tmp_path, include_2011=True)

    with pytest.raises(api.SnapshotSchemaInventoryError, match="NON_TRAIN_ROW:D_SPY"):
        api.build_train_snapshot_schema_inventory(
            snapshot,
            output_path=tmp_path / "schema_inventory.json",
        )


def test_inventory_requires_the_physical_train_partition_name(tmp_path: Path) -> None:
    api = _inventory_api()
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(api.SnapshotSchemaInventoryError, match="TRAIN_PARTITION_REQUIRED"):
        api.build_train_snapshot_schema_inventory(
            wrong,
            output_path=tmp_path / "schema_inventory.json",
        )
