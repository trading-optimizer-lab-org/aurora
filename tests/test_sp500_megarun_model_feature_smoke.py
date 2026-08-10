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
            "aurora.infra.sp500_megarun.model_feature_smoke"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"model feature smoke is missing: {exc}")


def _write_inputs(root: Path) -> tuple[Path, Path, Path, Path]:
    snapshot = root / "train_snapshot_1993_2010"
    snapshot.mkdir()
    dates = pd.bdate_range("2006-01-03", "2010-12-31")
    phase = np.arange(len(dates), dtype=float)
    close = 100.0 * np.exp(
        np.cumsum(0.0003 + 0.003 * np.sin(phase / 17.0) - 0.001 * np.cos(phase / 43.0))
    )
    pd.DataFrame({"date": dates}).to_parquet(
        snapshot / "D_CALENDAR.parquet", index=False
    )
    pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.999,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": 1_000_000.0 + phase,
        }
    ).to_parquet(snapshot / "D_SPY.parquet", index=False)

    roots = [root / "price", root / "market", root / "macro"]
    for target in roots:
        (target / "features").mkdir(parents=True)
    decision_dates = dates[1:]
    decision_phase = np.arange(len(decision_dates), dtype=float)
    for index in range(1, 51):
        lane_id = f"F{index:03d}"
        values = (
            np.sin(decision_phase / (4.0 + index))
            + 0.3 * np.cos(decision_phase / (7.0 + index % 11))
            + index / 1000.0
        )
        frame = pd.DataFrame(
            {
                "date": decision_dates,
                "observed_at": dates[:-1],
                "available_at": decision_dates,
                "value": values,
            }
        )
        target = roots[0] if index <= 20 else roots[1] if index <= 31 else roots[2]
        frame.to_parquet(target / "features" / f"{lane_id}.parquet", index=False)
    return snapshot, roots[0], roots[1], roots[2]


def test_model_smoke_builds_f051_f060_train_only_artifacts(tmp_path: Path) -> None:
    api = _smoke_api()
    snapshot, price, market, macro = _write_inputs(tmp_path)

    report = api.build_model_feature_smoke(
        snapshot,
        price_feature_dir=price,
        market_feature_dir=market,
        macro_feature_dir=macro,
        output_dir=tmp_path / "out",
    )

    assert report["ready"] is True
    assert report["executable_lanes"] == [f"F{index:03d}" for index in range(51, 61)]
    assert report["executable_lane_count"] == 10
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert report["empty_lanes"] == []
    assert report["parameter_choice_audit"]["ready"] is True
    assert report["parameter_choice_audit"]["expected_choice_probe_count"] == 175
    assert report["parameter_choice_audit"]["choice_probe_count"] == 175
    assert report["parameter_choice_audit"]["failed_probes"] == []
    assert report["parameter_choice_audit"]["inactive_choice_groups"] == []
    assert report["parameter_choice_audit"]["validation_opened"] is False
    assert report["parameter_choice_audit"]["locked_opened"] is False
    assert (tmp_path / "out" / "features" / "F051.parquet").is_file()
    assert (tmp_path / "out" / "features" / "F060.parquet").is_file()
    assert (tmp_path / "out" / "parameter_choice_audit_F051_F060.json").is_file()


def test_model_smoke_requires_the_physical_train_partition(tmp_path: Path) -> None:
    api = _smoke_api()
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(api.ModelFeatureSmokeError, match="TRAIN_PARTITION_REQUIRED"):
        api.build_model_feature_smoke(
            wrong,
            price_feature_dir=tmp_path / "price",
            market_feature_dir=tmp_path / "market",
            macro_feature_dir=tmp_path / "macro",
            output_dir=tmp_path / "out",
        )


def test_model_smoke_rejects_a_missing_simple_feature(tmp_path: Path) -> None:
    api = _smoke_api()
    snapshot, price, market, macro = _write_inputs(tmp_path)
    (macro / "features" / "F049.parquet").unlink()

    with pytest.raises(api.ModelFeatureSmokeError, match="SIMPLE_FEATURE_MISSING:F049"):
        api.build_model_feature_smoke(
            snapshot,
            price_feature_dir=price,
            market_feature_dir=market,
            macro_feature_dir=macro,
            output_dir=tmp_path / "out",
        )


def test_model_smoke_cli_accepts_the_f051_f060_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cli = importlib.import_module("scripts.run_sp500_megarun_model_feature_smoke_f051")
    monkeypatch.setattr(cli, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(
        cli,
        "build_model_feature_smoke",
        lambda *_args, **_kwargs: {"ready": True, "executable_lane_count": 10},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke",
            "--train-snapshot",
            str(tmp_path / "train_snapshot_1993_2010"),
            "--price-feature-dir",
            str(tmp_path / "price"),
            "--market-feature-dir",
            str(tmp_path / "market"),
            "--macro-feature-dir",
            str(tmp_path / "macro"),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )

    assert cli.main() == 0
