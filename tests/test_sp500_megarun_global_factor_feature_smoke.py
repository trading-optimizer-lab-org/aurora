from __future__ import annotations

import importlib
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


def _api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.global_factor_feature_smoke"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"global factor feature smoke is missing: {exc}")


def _write_snapshot(root: Path) -> Path:
    snapshot = root / "train_snapshot_1993_2010"
    snapshot.mkdir()
    dates = pd.bdate_range("2004-01-02", "2010-12-31")
    phase = np.arange(len(dates), dtype=float)
    close = 100.0 * np.exp(np.cumsum(0.0003 + 0.004 * np.sin(phase / 17.0)))
    pd.DataFrame({"date": dates}).to_parquet(
        snapshot / "D_CALENDAR.parquet", index=False
    )
    pd.DataFrame(
        {
            "date": dates,
            "open": np.r_[close[0], close[:-1]],
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": 1_000_000.0,
        }
    ).to_parquet(snapshot / "D_SPY.parquet", index=False)

    us_factors = pd.DataFrame(
        {
            "date": dates,
            "resource_id": "ff3_daily",
            "Mkt-RF": 0.04 + 0.4 * np.sin(phase / 17.0),
            "SMB": 0.01 + 0.3 * np.cos(phase / 23.0),
            "HML": -0.01 + 0.25 * np.sin((phase + 7.0) / 29.0),
        }
    )
    industry_values: dict[str, object] = {
        "date": dates,
        "resource_id": "industry_48_daily",
    }
    for index in range(48):
        industry_values[f"Industry{index:02d}"] = (
            0.015 * (index - 23)
            + 0.3 * np.sin(phase / (7.0 + index / 5.0))
            + 0.15 * np.cos((phase + index) / 19.0)
        )
    pd.concat(
        [us_factors, pd.DataFrame(industry_values)],
        ignore_index=True,
        sort=False,
    ).to_parquet(snapshot / "D_FRENCH_US.parquet", index=False)

    global_frames: list[pd.DataFrame] = []
    factor_resources = (
        "developed_five_factors",
        "developed_ex_us",
        "europe",
        "japan",
        "asia_pacific_ex_japan",
    )
    for offset, resource_id in enumerate(factor_resources, start=1):
        global_frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "resource_id": resource_id,
                    "Mkt-RF": 0.015 * offset + 0.35 * np.sin((phase + offset) / 17.0),
                    "SMB": 0.008 * offset + 0.28 * np.cos((phase + offset) / 23.0),
                    "HML": -0.004 * offset + 0.24 * np.sin((phase + offset) / 29.0),
                    "RMW": 0.006 * offset + 0.21 * np.cos((phase + offset) / 31.0),
                    "CMA": 0.003 * offset + 0.19 * np.sin((phase + offset) / 37.0),
                    "RF": 0.01,
                }
            )
        )
    momentum_resources = (
        "developed_momentum",
        "developed_ex_us_momentum",
        "europe_momentum",
        "japan_momentum",
        "asia_pacific_ex_japan_momentum",
    )
    for offset, resource_id in enumerate(momentum_resources, start=1):
        global_frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "resource_id": resource_id,
                    "WML": 0.012 * offset
                    + 0.3 * np.cos((phase + 3.0 * offset) / 19.0),
                }
            )
        )
    pd.concat(global_frames, ignore_index=True, sort=False).to_parquet(
        snapshot / "D_FRENCH_GLOBAL.parquet", index=False
    )
    return snapshot


def test_global_factor_smoke_builds_f161_f170_train_only_artifacts(
    tmp_path: Path,
) -> None:
    snapshot = _write_snapshot(tmp_path)

    report = _api().build_global_factor_feature_smoke(
        snapshot, output_dir=tmp_path / "out"
    )

    assert report["ready"] is True
    assert report["executable_lanes"] == [f"F{i:03d}" for i in range(161, 171)]
    assert report["executable_lane_count"] == 10
    assert len(report["approved_free_resources"]) == 12
    assert report["row_release_causality_valid"] is True
    assert report["historical_revision_pit_exact"] is False
    assert report["source_vintage_status"] == "current_download_not_historical_vintage"
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert report["empty_lanes"] == []
    parameter_audit = report["parameter_choice_audit"]
    assert parameter_audit["ready"] is True
    assert parameter_audit["expected_choice_probe_count"] == 146
    assert parameter_audit["choice_probe_count"] == 146
    assert parameter_audit["failed_probes"] == []
    assert parameter_audit["inactive_choice_groups"] == []
    assert (tmp_path / "out" / "features" / "F161.parquet").is_file()
    assert (tmp_path / "out" / "features" / "F170.parquet").is_file()


def test_global_factor_smoke_requires_physical_train_partition(
    tmp_path: Path,
) -> None:
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(
        _api().GlobalFactorFeatureSmokeError,
        match="TRAIN_PARTITION_REQUIRED",
    ):
        _api().build_global_factor_feature_smoke(
            wrong, output_dir=tmp_path / "out"
        )


def test_global_factor_smoke_rejects_missing_regional_momentum(
    tmp_path: Path,
) -> None:
    snapshot = _write_snapshot(tmp_path)
    global_factors = pd.read_parquet(snapshot / "D_FRENCH_GLOBAL.parquet")
    global_factors.loc[
        ~global_factors["resource_id"].eq("japan_momentum")
    ].to_parquet(snapshot / "D_FRENCH_GLOBAL.parquet", index=False)

    with pytest.raises(
        _api().GlobalFactorFeatureSmokeError,
        match="FRENCH_GLOBAL_RESOURCE_MISSING:japan_momentum",
    ):
        _api().build_global_factor_feature_smoke(
            snapshot, output_dir=tmp_path / "out"
        )


def test_global_factor_smoke_cli_accepts_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = importlib.import_module(
        "scripts.run_sp500_megarun_global_factor_feature_smoke_f161"
    )
    monkeypatch.setattr(cli, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(
        cli,
        "build_global_factor_feature_smoke",
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


@pytest.mark.parametrize(
    ("lane_id", "parameter", "configuration", "expected"),
    [
        ("F161", "change_lag", {"mode": "level"}, {"mode": "change"}),
        ("F165", "short_window", {"statistic": "dispersion", "window": 20}, {"statistic": "regime_change", "window": 126}),
        ("F169", "selection_fraction", {"selection_fraction": 0.33, "universe": "regions_only"}, {"universe": "developed_ex_us_plus_regions"}),
        ("F169", "aggregation", {"aggregation": "median", "selection_fraction": 0.1, "universe": "regions_only"}, {"selection_fraction": 0.5, "universe": "all_available"}),
        ("F170", "change_lag", {"mode": "divergence"}, {"mode": "change"}),
    ],
)
def test_global_factor_parameter_witnesses_activate_conditional_choices(
    lane_id: str,
    parameter: str,
    configuration: dict[str, object],
    expected: dict[str, object],
) -> None:
    repaired = _api()._repair_global_factor_configuration(
        lane_id,
        parameter,
        configuration.copy(),
    )

    for name, value in expected.items():
        assert repaired[name] == value


def test_global_factor_physical_smoke_has_an_isolated_dispatch_scope() -> None:
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "sp500-megarun-macro-feature-smoke-f032.yml"
    ).read_text(encoding="utf-8")

    assert "- f161_f170" in workflow
    assert "smoke_f161_f170:" in workflow
    assert "inputs.scope == 'f161_f170'" in workflow
    assert "timeout-minutes: 15" in workflow
