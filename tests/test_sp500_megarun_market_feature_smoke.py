from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def _smoke_api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.market_feature_smoke"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"market feature smoke is missing: {exc}")


def _write_train_snapshot(root: Path) -> Path:
    snapshot = root / "train_snapshot_1993_2010"
    snapshot.mkdir()
    dates = pd.bdate_range("1993-01-22", "2010-12-31")
    phase = np.arange(len(dates), dtype=float)
    close = 100.0 + 0.02 * phase + 2.0 * np.sin(phase / 17.0)
    pd.DataFrame(
        {
            "date": dates,
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1_000_000.0 + 100.0 * phase,
        }
    ).to_parquet(snapshot / "D_SPY.parquet", index=False)
    pd.DataFrame(
        {
            "date": dates,
            "CLOSE": 20.0 + 2.0 * np.sin(phase / 13.0),
            "resource_id": "vix_from_2003",
        }
    ).to_parquet(snapshot / "D_VIX.parquet", index=False)
    pd.DataFrame(
        {
            "date": dates,
            "4": (19.0 + 2.0 * np.sin(phase / 15.0)).astype(str),
            "Unnamed: 4": None,
            "resource_id": "vxo_1986_2003",
        }
    ).to_parquet(snapshot / "D_VXO.parquet", index=False)

    tuesdays = dates[dates.weekday == 1]
    cot_phase = np.arange(len(tuesdays), dtype=float)
    pd.DataFrame(
        {
            "date": tuesdays,
            "Market and Exchange Names": (
                "E-MINI S&P 500 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE"
            ),
            "Open Interest (All)": (1_000_000.0 + 1_000.0 * cot_phase).astype(str),
            "Noncommercial Positions-Long (All)": (
                400_000.0 + 5_000.0 * np.sin(cot_phase / 5.0)
            ).astype(str),
            "Noncommercial Positions-Short (All)": "300000",
            "Commercial Positions-Long (All)": "200000",
            "Commercial Positions-Short (All)": (
                250_000.0 + 4_000.0 * np.cos(cot_phase / 7.0)
            ).astype(str),
            "Concentration-Net LT =4 TDR-Long (All)": "25",
            "Concentration-Net LT =4 TDR-Short (All)": "30",
            "resource_id": "legacy_futures_only:train",
        }
    ).to_parquet(snapshot / "D_CFTC.parquet", index=False)

    rate_rows: list[dict[str, object]] = []
    for position, date in enumerate(dates):
        for series_id, base in (
            ("RIFLGFCM03_N.B", 1.0),
            ("RIFLGFCY02_N.B", 2.0),
            ("RIFLGFCY10_N.B", 4.0),
        ):
            rate_rows.append(
                {
                    "date": date,
                    "series_id": series_id,
                    "value": base + 0.1 * np.sin(position / 30.0 + base),
                }
            )
    pd.DataFrame(rate_rows).to_parquet(snapshot / "D_RATES.parquet", index=False)
    return snapshot


def test_market_smoke_builds_f021_f031_train_only_artifacts(tmp_path: Path) -> None:
    api = _smoke_api()
    snapshot = _write_train_snapshot(tmp_path)

    report = api.build_market_feature_smoke(snapshot, output_dir=tmp_path / "out")

    assert report["ready"] is True
    assert report["executable_lane_count"] == 11
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert report["parameter_choice_audit"]["ready"] is True
    assert report["parameter_choice_audit"]["choice_probe_count"] == report[
        "parameter_choice_audit"
    ]["expected_choice_probe_count"]
    assert report["parameter_choice_audit"]["validation_opened"] is False
    assert report["parameter_choice_audit"]["locked_opened"] is False
    assert len(list((tmp_path / "out" / "features").glob("F*.parquet"))) == 11
    assert (tmp_path / "out" / "parameter_choice_audit_F021_F031.json").is_file()


def test_market_smoke_requires_the_physical_train_partition(tmp_path: Path) -> None:
    api = _smoke_api()
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(api.MarketFeatureSmokeError, match="TRAIN_PARTITION_REQUIRED"):
        api.build_market_feature_smoke(wrong, output_dir=tmp_path / "out")
