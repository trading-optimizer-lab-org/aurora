from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest


def _probe_api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.snapshot_normalization_probe"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"snapshot normalization probe implementation is missing: {exc}")


def _snapshot(root: Path, *, date: str = "2010-12-31") -> Path:
    snapshot = root / "train_snapshot_1993_2010"
    snapshot.mkdir()
    pd.DataFrame(
        {
            "date": pd.to_datetime([date, "2010-12-30"]),
            "numeric_text": ["1.5", "2.5"],
            "mixed": ["3", "not-a-number"],
            "series_id": ["B", "A"],
        }
    ).to_parquet(snapshot / "D_TEST.parquet", index=False)
    return snapshot


def test_probe_reports_numeric_coercion_and_categories(tmp_path: Path) -> None:
    api = _probe_api()
    snapshot = _snapshot(tmp_path)
    output = tmp_path / "probe.json"

    report = api.build_train_snapshot_normalization_probe(
        snapshot,
        dataset_ids=("D_TEST",),
        output_path=output,
    )

    row = report["datasets"]["D_TEST"]
    assert report["ready"] is True
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert row["numeric_coercible_counts"]["numeric_text"] == 2
    assert row["numeric_coercible_counts"]["mixed"] == 1
    assert row["category_values"]["series_id"] == ["A", "B"]
    assert row["sample_non_null"]["numeric_text"] == ["1.5", "2.5"]
    assert output.exists()


def test_probe_rejects_unknown_dataset_and_2011(tmp_path: Path) -> None:
    api = _probe_api()
    snapshot = _snapshot(tmp_path, date="2011-01-03")

    with pytest.raises(api.SnapshotNormalizationProbeError, match="DATASET_MISSING:D_NOPE"):
        api.build_train_snapshot_normalization_probe(
            snapshot,
            dataset_ids=("D_NOPE",),
            output_path=tmp_path / "probe.json",
        )
    with pytest.raises(api.SnapshotNormalizationProbeError, match="NON_TRAIN_ROW:D_TEST"):
        api.build_train_snapshot_normalization_probe(
            snapshot,
            dataset_ids=("D_TEST",),
            output_path=tmp_path / "probe.json",
        )
