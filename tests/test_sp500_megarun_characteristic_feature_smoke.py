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
            "aurora.infra.sp500_megarun.characteristic_feature_smoke"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"characteristic feature smoke is missing: {exc}")


def _raw_standard(
    dates: pd.DatetimeIndex,
    phase: np.ndarray,
    resource_id: str,
    offset: float,
) -> pd.DataFrame:
    wave = np.sin((phase + offset) / (11.0 + offset / 10.0))
    base = 0.1 * wave
    premium = 0.35 + 0.12 * np.cos(
        (phase + 2.0 * offset) / (17.0 + offset / 5.0)
    )
    return pd.DataFrame(
        {
            "date": dates,
            "resource_id": resource_id,
            "Lo 30": base - premium * 0.6,
            "Med 40": base,
            "Hi 30": base + premium * 0.6,
            "Lo 20": base - premium * 0.8,
            "Qnt 2": base - premium * 0.4,
            "Qnt 3": base,
            "Qnt 4": base + premium * 0.4,
            "Hi 20": base + premium * 0.8,
            "Lo 10": base - premium,
            "Dec 2": base - premium * 0.75,
            "Dec 3": base - premium * 0.55,
            "Dec 4": base - premium * 0.30,
            "Dec 5": base - premium * 0.08,
            "Dec 6": base + premium * 0.08,
            "Dec 7": base + premium * 0.30,
            "Dec 8": base + premium * 0.55,
            "Dec 9": base + premium * 0.75,
            "Hi 10": base + premium,
        }
    )


def _raw_prior(
    dates: pd.DatetimeIndex,
    phase: np.ndarray,
    resource_id: str,
    offset: float,
) -> pd.DataFrame:
    base = 0.1 * np.cos((phase + offset) / (13.0 + offset / 10.0))
    premium = 0.40 + 0.10 * np.sin(
        (phase + 3.0 * offset) / (19.0 + offset / 5.0)
    )
    data: dict[str, object] = {
        "date": dates,
        "resource_id": resource_id,
        "Lo PRIOR": base - premium,
    }
    for decile in range(2, 10):
        weight = -1.0 + 2.0 * (decile - 1) / 9.0
        data[f"PRIOR {decile}"] = base + weight * premium
    data["Hi PRIOR"] = base + premium
    return pd.DataFrame(data)


def _write_snapshot(root: Path) -> Path:
    snapshot = root / "train_snapshot_1993_2010"
    snapshot.mkdir()
    dates = pd.bdate_range("2004-01-02", "2010-12-31")
    phase = np.arange(len(dates), dtype=float)
    returns = 0.0003 + 0.004 * np.sin(phase / 17.0)
    close = 100.0 * np.exp(np.cumsum(returns))
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
            "volume": 1_000_000.0 * (1.2 + 0.1 * np.sin(phase / 19.0)),
        }
    ).to_parquet(snapshot / "D_SPY.parquet", index=False)

    frames = [
        _raw_standard(dates, phase, "size_daily", 1.0),
        _raw_standard(dates, phase, "book_to_market_daily", 2.0),
        _raw_standard(dates, phase, "profitability_daily", 3.0),
        _raw_standard(dates, phase, "investment_daily", 4.0),
        _raw_prior(dates, phase, "momentum_10_daily", 5.0),
        _raw_prior(dates, phase, "short_reversal_10_daily", 6.0),
        _raw_prior(dates, phase, "long_reversal_10_daily", 7.0),
    ]
    monthly_dates = pd.date_range("2004-01-01", "2010-12-01", freq="MS")
    monthly_phase = np.arange(len(monthly_dates), dtype=float)
    for offset, resource_id in enumerate(
        (
            "accruals_monthly",
            "beta_monthly",
            "net_share_issues_monthly",
            "variance_monthly",
            "residual_variance_monthly",
        ),
        start=8,
    ):
        frames.append(
            _raw_standard(
                monthly_dates,
                monthly_phase,
                resource_id,
                float(offset),
            )
        )
    pd.concat(frames, ignore_index=True, sort=False).to_parquet(
        snapshot / "D_FRENCH_US.parquet", index=False
    )
    return snapshot


def test_characteristic_smoke_builds_f151_f160_train_only_artifacts(
    tmp_path: Path,
) -> None:
    snapshot = _write_snapshot(tmp_path)

    report = _api().build_characteristic_feature_smoke(
        snapshot, output_dir=tmp_path / "out"
    )

    assert report["ready"] is True
    assert report["executable_lanes"] == [f"F{i:03d}" for i in range(151, 161)]
    assert report["executable_lane_count"] == 10
    assert len(report["approved_free_resources"]) == 12
    assert report["row_release_causality_valid"] is True
    assert report["historical_revision_pit_exact"] is False
    assert report["source_vintage_status"] == "current_download_not_historical_vintage"
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert report["empty_lanes"] == []
    assert (tmp_path / "out" / "features" / "F151.parquet").is_file()
    assert (tmp_path / "out" / "features" / "F160.parquet").is_file()


def test_characteristic_smoke_requires_physical_train_partition(
    tmp_path: Path,
) -> None:
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(
        _api().CharacteristicFeatureSmokeError,
        match="TRAIN_PARTITION_REQUIRED",
    ):
        _api().build_characteristic_feature_smoke(
            wrong, output_dir=tmp_path / "out"
        )


def test_characteristic_smoke_rejects_missing_physical_resource(
    tmp_path: Path,
) -> None:
    snapshot = _write_snapshot(tmp_path)
    french = pd.read_parquet(snapshot / "D_FRENCH_US.parquet")
    french.loc[
        ~french["resource_id"].eq("residual_variance_monthly")
    ].to_parquet(snapshot / "D_FRENCH_US.parquet", index=False)

    with pytest.raises(
        _api().CharacteristicFeatureSmokeError,
        match="FRENCH_RESOURCE_MISSING:residual_variance_monthly",
    ):
        _api().build_characteristic_feature_smoke(
            snapshot, output_dir=tmp_path / "out"
        )


def test_characteristic_smoke_cli_accepts_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = importlib.import_module(
        "scripts.run_sp500_megarun_characteristic_feature_smoke_f151"
    )
    monkeypatch.setattr(cli, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(
        cli,
        "build_characteristic_feature_smoke",
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
