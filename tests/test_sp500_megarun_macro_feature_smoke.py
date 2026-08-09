from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def _smoke_api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.macro_feature_smoke"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"macro feature smoke is missing: {exc}")


def _write_train_snapshot(root: Path) -> Path:
    snapshot = root / "train_snapshot_1993_2010"
    snapshot.mkdir()
    dates = pd.bdate_range("2007-01-02", "2010-12-31")
    rows: list[dict[str, object]] = []
    for position, date in enumerate(dates):
        phase = float(position)
        aaa = 4.0 + 0.1 * np.sin(phase / 40.0)
        spread = 1.5 + 0.2 * np.sin(phase / 17.0) + 0.0002 * phase
        rows.extend(
            [
                {"date": date, "series_id": "RIMLPAAAR_N.B", "value": aaa},
                {
                    "date": date,
                    "series_id": "RIMLPBAAR_N.B",
                    "value": aaa + spread,
                },
            ]
        )
    pd.DataFrame(rows).to_parquet(snapshot / "D_RATES.parquet", index=False)
    return snapshot


def test_macro_smoke_builds_f032_train_only_artifact(tmp_path: Path) -> None:
    api = _smoke_api()
    snapshot = _write_train_snapshot(tmp_path)

    report = api.build_macro_feature_smoke(snapshot, output_dir=tmp_path / "out")

    assert report["ready"] is True
    assert report["executable_lanes"] == ["F032"]
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert (tmp_path / "out" / "features" / "F032.parquet").is_file()


def test_macro_smoke_requires_the_physical_train_partition(tmp_path: Path) -> None:
    api = _smoke_api()
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(api.MacroFeatureSmokeError, match="TRAIN_PARTITION_REQUIRED"):
        api.build_macro_feature_smoke(wrong, output_dir=tmp_path / "out")
