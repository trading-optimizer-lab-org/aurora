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
            "aurora.infra.sp500_megarun.positioning_feature_smoke"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"positioning feature smoke is missing: {exc}")


def _margin_frame(dates: pd.DatetimeIndex) -> pd.DataFrame:
    phase = np.arange(len(dates), dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "Debit Balances in Customers' Securities Margin Accounts": 100.0
            * np.exp(0.01 * phase + 0.04 * np.sin(phase / 5.0)),
            "Free Credit Balances in Customers' Cash Accounts": 70.0
            * np.exp(0.007 * phase + 0.03 * np.cos(phase / 7.0)),
            "Free Credit Balances in Customers' Securities Margin Accounts": 20.0
            * np.exp(0.005 * phase),
        }
    )


def _cftc_frame(dates: pd.DatetimeIndex) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index, date in enumerate(dates):
        for combined in (False, True):
            multiplier = 1.2 if combined else 1.0
            phase = float(index)
            open_interest = 1_000_000.0 * multiplier * (1.0 + 0.001 * phase)
            rows.append(
                {
                    "date": date,
                    "As of Date in Form YYYY-MM-DD": date.date().isoformat(),
                    "Market and Exchange Names": (
                        "E-MINI S&P 500 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE"
                    ),
                    "Open Interest (All)": open_interest,
                    "Noncommercial Positions-Long (All)": open_interest
                    * (0.35 + 0.03 * np.sin(phase / 7.0)),
                    "Noncommercial Positions-Short (All)": open_interest
                    * (0.3 + 0.02 * np.cos(phase / 9.0)),
                    "Commercial Positions-Long (All)": open_interest
                    * (0.28 + 0.02 * np.cos(phase / 11.0)),
                    "Commercial Positions-Short (All)": open_interest
                    * (0.33 + 0.02 * np.sin(phase / 13.0)),
                    "Total Reportable Positions-Long (All)": open_interest * 0.72,
                    "Total Reportable Positions-Short (All)": open_interest
                    * (0.66 + 0.01 * np.sin(phase / 8.0)),
                    "Concentration-Net LT =4 TDR-Long (All)": 25.0
                    + 2.0 * np.sin(phase / 10.0),
                    "Concentration-Net LT =4 TDR-Short (All)": 28.0
                    + 2.0 * np.cos(phase / 12.0),
                    "Concentration-Net LT =8 TDR-Long (All)": 40.0
                    + 3.0 * np.sin(phase / 10.0),
                    "Concentration-Net LT =8 TDR-Short (All)": 46.0
                    + 3.0 * np.cos(phase / 12.0),
                    "resource_id": (
                        "legacy_futures_options_combined:synthetic"
                        if combined
                        else "legacy_futures_only:synthetic"
                    ),
                }
            )
    return pd.DataFrame(rows)


def _write_inputs(root: Path) -> Path:
    snapshot = root / "train_snapshot_1993_2010"
    snapshot.mkdir()
    dates = pd.bdate_range("1993-01-04", "2010-12-31")
    phase = np.arange(len(dates), dtype=float)
    returns = 0.00025 + 0.003 * np.sin(phase / 11.0) + 0.001 * np.cos(phase / 37.0)
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]] * (1.0 + 0.0004 * np.sin(phase / 7.0))
    spread = 0.002 + 0.002 * (1.0 + np.cos(phase / 17.0))
    volume = 1_000_000.0 * np.exp(0.2 * np.sin(phase / 23.0))
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

    quarter_dates = pd.date_range("1993-03-31", "2009-09-30", freq="QE")
    z1_rows: list[dict[str, object]] = []
    for index, date in enumerate(quarter_dates):
        values = {
            "FL153064105.Q": 400.0 + 8.0 * index + 20.0 * np.sin(index / 4.0),
            "FL154090005.Q": 1000.0 + 12.0 * index,
            "FL653064100.Q": 300.0 + 7.0 * index + 12.0 * np.cos(index / 5.0),
            "FL654090000.Q": 600.0 + 10.0 * index,
        }
        z1_rows.extend(
            {"date": date, "series_id": series_id, "value": value}
            for series_id, value in values.items()
        )
    pd.DataFrame(z1_rows).to_parquet(snapshot / "D_Z1.parquet", index=False)

    margin = _margin_frame(pd.date_range("1995-01-01", "2010-10-01", freq="MS"))
    margin.to_parquet(snapshot / "D_MARGIN.parquet", index=False)
    margin.assign(source_dataset="D_MARGIN").to_parquet(
        snapshot / "D_FINRA_MARGIN.parquet", index=False
    )

    tuesdays = pd.date_range("1997-01-07", "2010-12-21", freq="W-TUE")
    cftc = _cftc_frame(tuesdays)
    cftc.to_parquet(snapshot / "D_CFTC.parquet", index=False)
    cftc.assign(source_dataset="D_CFTC").to_parquet(
        snapshot / "D_CFTC_LEGACY.parquet", index=False
    )

    vol_phase = np.arange(len(dates), dtype=float)
    pd.DataFrame(
        {
            "date": dates,
            "CLOSE": 20.0 + 3.0 * np.sin(vol_phase / 29.0),
            "resource_id": "vix_from_2003",
        }
    ).to_parquet(snapshot / "D_VIX.parquet", index=False)
    pd.DataFrame(
        {
            "date": dates,
            "4": 19.0 + 2.5 * np.sin(vol_phase / 29.0 + 0.2),
            "Unnamed: 4": np.nan,
            "resource_id": "vxo_1986_2003",
        }
    ).to_parquet(snapshot / "D_VXO.parquet", index=False)
    market = 0.2 * np.sin(vol_phase / 13.0)
    pd.DataFrame(
        {
            "date": dates,
            "resource_id": "industry_48_daily",
            **{
                f"industry_{index}": market
                + 0.15 * np.sin(vol_phase / (5.0 + index) + index)
                for index in range(8)
            },
        }
    ).to_parquet(snapshot / "D_FRENCH_INDUSTRIES.parquet", index=False)
    return snapshot


def test_positioning_smoke_builds_f081_f090_train_only_artifacts(
    tmp_path: Path,
) -> None:
    api = _smoke_api()
    snapshot = _write_inputs(tmp_path)

    report = api.build_positioning_feature_smoke(
        snapshot,
        output_dir=tmp_path / "out",
    )

    assert report["ready"] is True
    assert report["executable_lanes"] == [f"F{index:03d}" for index in range(81, 91)]
    assert report["executable_lane_count"] == 10
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert report["empty_lanes"] == []
    assert report["exact_duplicate_groups"] == []
    assert report["near_duplicate_pairs"] == []
    assert (tmp_path / "out" / "features" / "F081.parquet").is_file()
    assert (tmp_path / "out" / "features" / "F090.parquet").is_file()


def test_positioning_smoke_requires_physical_train_partition(tmp_path: Path) -> None:
    api = _smoke_api()
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(
        api.PositioningFeatureSmokeError, match="TRAIN_PARTITION_REQUIRED"
    ):
        api.build_positioning_feature_smoke(wrong, output_dir=tmp_path / "out")


def test_positioning_smoke_rejects_missing_physical_inputs(tmp_path: Path) -> None:
    api = _smoke_api()
    snapshot = tmp_path / "train_snapshot_1993_2010"
    snapshot.mkdir()

    with pytest.raises(
        api.PositioningFeatureSmokeError, match="TRAIN_DATASET_MISSING:D_SPY"
    ):
        api.build_positioning_feature_smoke(snapshot, output_dir=tmp_path / "out")


def test_positioning_smoke_cli_accepts_the_f081_f090_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cli = importlib.import_module(
        "scripts.run_sp500_megarun_positioning_feature_smoke_f081"
    )
    monkeypatch.setattr(cli, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(
        cli,
        "build_positioning_feature_smoke",
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
