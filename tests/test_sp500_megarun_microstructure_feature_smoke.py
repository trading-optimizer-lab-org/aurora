from __future__ import annotations

import importlib
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


def _smoke_api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.microstructure_feature_smoke"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"microstructure feature smoke is missing: {exc}")


def _write_inputs(root: Path) -> Path:
    snapshot = root / "train_snapshot_1993_2010"
    snapshot.mkdir()
    dates = pd.bdate_range("2003-01-02", "2010-12-31")
    phase = np.arange(len(dates), dtype=float)
    returns = (
        0.0003
        + 0.003 * np.sin(phase / 7.0)
        + 0.001 * np.cos(phase / 29.0)
        + np.where((phase // 120).astype(int) % 2 == 0, 0.0006, -0.0006)
    )
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]] * (1.0 + 0.0004 * np.sin(phase / 11.0))
    spread = 0.002 + 0.002 * (1.0 + np.cos(phase / 19.0))
    volume = 1_000_000.0 * np.exp(
        0.2 * np.sin(phase / 17.0) + 0.1 * np.cos(phase / 43.0)
    )
    pd.DataFrame({"date": dates}).to_parquet(
        snapshot / "D_CALENDAR.parquet", index=False
    )
    pd.DataFrame(
        {
            "date": dates,
            "open": open_,
            "high": np.maximum(open_, close) * (1.0 + spread),
            "low": np.minimum(open_, close) * (1.0 - spread),
            "close": close,
            "volume": volume,
        }
    ).to_parquet(snapshot / "D_SPY.parquet", index=False)
    return snapshot


def test_microstructure_smoke_builds_f071_f080_train_only_artifacts(
    tmp_path: Path,
) -> None:
    api = _smoke_api()
    snapshot = _write_inputs(tmp_path)

    report = api.build_microstructure_feature_smoke(
        snapshot,
        output_dir=tmp_path / "out",
    )

    assert report["ready"] is True
    assert report["executable_lanes"] == [f"F{index:03d}" for index in range(71, 81)]
    assert report["executable_lane_count"] == 10
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert report["empty_lanes"] == []
    assert report["exact_duplicate_groups"] == []
    assert report["near_duplicate_pairs"] == []
    parameter_audit = report["parameter_choice_audit"]
    assert parameter_audit["ready"] is True
    assert parameter_audit["expected_choice_probe_count"] == 131
    assert parameter_audit["choice_probe_count"] == 131
    assert parameter_audit["failed_probes"] == []
    assert parameter_audit["inactive_choice_groups"] == []
    assert (tmp_path / "out" / "features" / "F071.parquet").is_file()
    assert (tmp_path / "out" / "features" / "F080.parquet").is_file()
    assert (
        tmp_path / "out" / "parameter_choice_audit_F071_F080.json"
    ).is_file()


def test_microstructure_smoke_requires_physical_train_partition(
    tmp_path: Path,
) -> None:
    api = _smoke_api()
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(
        api.MicrostructureFeatureSmokeError, match="TRAIN_PARTITION_REQUIRED"
    ):
        api.build_microstructure_feature_smoke(wrong, output_dir=tmp_path / "out")


def test_microstructure_smoke_rejects_missing_physical_inputs(
    tmp_path: Path,
) -> None:
    api = _smoke_api()
    snapshot = tmp_path / "train_snapshot_1993_2010"
    snapshot.mkdir()

    with pytest.raises(
        api.MicrostructureFeatureSmokeError, match="TRAIN_DATASET_MISSING:D_SPY"
    ):
        api.build_microstructure_feature_smoke(snapshot, output_dir=tmp_path / "out")


def test_microstructure_smoke_cli_accepts_the_f071_f080_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cli = importlib.import_module(
        "scripts.run_sp500_megarun_microstructure_feature_smoke_f071"
    )
    monkeypatch.setattr(cli, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(
        cli,
        "build_microstructure_feature_smoke",
        lambda *_args, **_kwargs: {"ready": True, "executable_lane_count": 10},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke",
            "--train-snapshot",
            str(tmp_path / "train_snapshot_1993_2010"),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )

    assert cli.main() == 0
