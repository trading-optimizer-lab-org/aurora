from __future__ import annotations

import importlib
from pathlib import Path
import sys

import pytest


def _api():
    return importlib.import_module(
        "aurora.infra.sp500_megarun.technical_feature_smoke"
    )


def test_technical_smoke_requires_physical_train_partition(tmp_path: Path) -> None:
    api = _api()
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(api.TechnicalFeatureSmokeError, match="TRAIN_PARTITION_REQUIRED"):
        api.build_technical_feature_smoke(wrong, output_dir=tmp_path / "out")


def test_technical_smoke_rejects_missing_spy_input(tmp_path: Path) -> None:
    api = _api()
    snapshot = tmp_path / "train_snapshot_1993_2010"
    snapshot.mkdir()

    with pytest.raises(api.TechnicalFeatureSmokeError, match="TRAIN_DATASET_MISSING:D_SPY"):
        api.build_technical_feature_smoke(snapshot, output_dir=tmp_path / "out")


def test_technical_smoke_cli_accepts_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = importlib.import_module(
        "scripts.run_sp500_megarun_technical_feature_smoke_f121"
    )
    monkeypatch.setattr(cli, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(
        cli,
        "build_technical_feature_smoke",
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
