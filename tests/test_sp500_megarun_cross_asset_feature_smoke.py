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
            "aurora.infra.sp500_megarun.cross_asset_feature_smoke"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"cross-asset feature smoke is missing: {exc}")


def _write_snapshot(root: Path) -> Path:
    snapshot = root / "train_snapshot_1993_2010"
    snapshot.mkdir()
    dates = pd.bdate_range("2003-01-02", "2010-12-31")
    phase = np.arange(len(dates), dtype=float)
    close = 100.0 * np.exp(np.cumsum(0.0003 + 0.004 * np.sin(phase / 31.0)))
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

    fed_frames: list[pd.DataFrame] = []
    rates = {
        "RIFLGFCM03_N.B": 2.5 + 0.6 * np.sin(phase / 127.0),
        "RILSPDEPM03_N.B": 2.8 + 0.7 * np.sin((phase + 9.0) / 131.0),
        "RIFLGFCY02_N.B": 3.0 + 0.5 * np.sin(phase / 137.0),
        "RIFLGFCY05_N.B": 3.5 + 0.45 * np.sin(phase / 149.0),
        "RIFLGFCY10_N.B": 4.0 + 0.4 * np.sin(phase / 163.0),
        "RIFLGFCY20_N.B": 4.4 + 0.35 * np.sin(phase / 173.0),
    }
    for series_id, values in rates.items():
        fed_frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "series_id": series_id,
                    "value": values,
                    "source_dataset": "D_RATES",
                }
            )
        )
    fx_ids = (
        "V0.JRXWTFB_N.B",
        "RXI_N.B.CA",
        "RXI_N.B.JA",
        "RXI_N.B.SZ",
        "RXI$US_N.B.UK",
        "RXI$US_N.B.AL",
        "RXI$US_N.B.NZ",
        "RXI_N.B.DN",
        "RXI_N.B.NO",
        "RXI_N.B.SD",
    )
    for offset, series_id in enumerate(fx_ids, start=1):
        fed_frames.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "series_id": series_id,
                    "value": 1.0 + offset + 0.001 * phase + 0.05 * np.sin((phase + offset) / 41.0),
                    "source_dataset": "D_FX",
                }
            )
        )
    pd.concat(fed_frames, ignore_index=True).to_parquet(
        snapshot / "D_FED_H15_H10.parquet", index=False
    )

    monthly = pd.date_range("2003-01-01", "2010-11-01", freq="MS")
    mp = np.arange(len(monthly), dtype=float)
    raw_names = (
        "Crude oil, average", "Coal, Australian", "Natural gas, US", "Aluminum",
        "Copper", "Lead", "Tin", "Nickel", "Zinc", "Gold", "Platinum",
        "Silver", "Cocoa", "Coffee, Arabica", "Coffee, Robusta", "Palm oil",
        "Soybeans", "Maize", "Rice, Thai 5%", "Wheat, US SRW", "Beef **",
        "Sugar, world", "Cotton, A Index", "Phosphate rock", "DAP", "Urea",
        "Potassium chloride **",
    )
    commodity_values: dict[str, object] = {"date": monthly}
    for offset, name in enumerate(raw_names, start=1):
        commodity_values[name] = 50.0 * np.exp(
            0.002 * offset * mp + 0.06 * np.sin((mp + offset) / (5.0 + offset / 5.0))
        )
    pd.DataFrame(commodity_values).to_parquet(
        snapshot / "D_WORLD_BANK_COMMODITIES.parquet", index=False
    )
    return snapshot


def test_cross_asset_smoke_builds_f171_f180_train_only_artifacts(
    tmp_path: Path,
) -> None:
    snapshot = _write_snapshot(tmp_path)

    report = _api().build_cross_asset_feature_smoke(
        snapshot, output_dir=tmp_path / "out"
    )

    assert report["ready"] is True
    assert report["executable_lanes"] == [f"F{i:03d}" for i in range(171, 181)]
    assert report["executable_lane_count"] == 10
    assert report["h10_release_policy"] == "following_week_release_plus_next_spy_session"
    assert report["f172_fidelity"] == "usd_funding_pressure_proxy_not_fx_carry"
    assert report["historical_revision_pit_exact"] is False
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert report["empty_lanes"] == []
    assert (tmp_path / "out" / "features" / "F171.parquet").is_file()
    assert (tmp_path / "out" / "features" / "F180.parquet").is_file()


def test_cross_asset_smoke_requires_physical_train_partition(tmp_path: Path) -> None:
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(_api().CrossAssetFeatureSmokeError, match="TRAIN_PARTITION_REQUIRED"):
        _api().build_cross_asset_feature_smoke(wrong, output_dir=tmp_path / "out")


def test_cross_asset_smoke_rejects_missing_h10_rows(tmp_path: Path) -> None:
    snapshot = _write_snapshot(tmp_path)
    fed = pd.read_parquet(snapshot / "D_FED_H15_H10.parquet")
    fed.loc[fed["source_dataset"].ne("D_FX")].to_parquet(
        snapshot / "D_FED_H15_H10.parquet", index=False
    )

    with pytest.raises(_api().CrossAssetFeatureSmokeError, match="FED_SOURCE_MISSING:D_FX"):
        _api().build_cross_asset_feature_smoke(snapshot, output_dir=tmp_path / "out")


def test_cross_asset_smoke_rejects_implausible_normalized_rate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    api = _api()
    snapshot = _write_snapshot(tmp_path)
    original = api.normalize_treasury_curve_panel

    def poisoned(*args: object, **kwargs: object) -> pd.DataFrame:
        result = original(*args, **kwargs)
        result.loc[result.index[10], "yield_10y"] = -9999.0
        return result

    monkeypatch.setattr(api, "normalize_treasury_curve_panel", poisoned)

    with pytest.raises(
        api.CrossAssetFeatureSmokeError,
        match="NORMALIZED_RATE_OUT_OF_RANGE:yield_10y",
    ):
        api.build_cross_asset_feature_smoke(snapshot, output_dir=tmp_path / "out")


def test_cross_asset_smoke_cli_accepts_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = importlib.import_module(
        "scripts.run_sp500_megarun_cross_asset_feature_smoke_f171"
    )
    monkeypatch.setattr(cli, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(
        cli,
        "build_cross_asset_feature_smoke",
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
