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
            "aurora.infra.sp500_megarun.fundamental_feature_smoke"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"fundamental feature smoke is missing: {exc}")


def _macro_frame() -> pd.DataFrame:
    weekly_dates = pd.date_range("1993-01-06", "2010-11-30", freq="W-WED")
    phase = np.arange(len(weekly_dates), dtype=float)
    weekly_series = {
        "B1001NCBA": 3_500.0
        * np.exp(0.0013 * phase + 0.05 * np.sin(phase / 9.0)),
        "B1020NCBA": 2_700.0
        * np.exp(0.0014 * phase + 0.06 * np.cos(phase / 10.0)),
        "M2.WM": 4_000.0
        * np.exp(0.0012 * phase + 0.04 * np.cos(phase / 13.0)),
        "DTBSPCK_N.WW": 800.0
        * np.exp(0.0008 * phase + 0.09 * np.sin(phase / 6.0)),
    }
    weekly = pd.concat(
        [
            pd.DataFrame(
                {
                    "date": weekly_dates,
                    "series_id": name,
                    "resource_id": "synthetic_federal_reserve_release",
                    "value": values,
                }
            )
            for name, values in weekly_series.items()
        ],
        ignore_index=True,
    )
    monthly_dates = pd.date_range("1993-01-01", "2010-06-01", freq="MS")
    monthly_phase = np.arange(len(monthly_dates), dtype=float)
    monthly_series = {
        "philly_payroll_first_releases": 150.0
        + 80.0 * np.sin(monthly_phase / 5.0),
        "philly_industrial_production_first_releases": 2.0
        + 1.7 * np.sin(monthly_phase / 7.0),
        "philly_housing_starts_first_releases": 1_500.0
        + 180.0 * np.cos(monthly_phase / 8.0),
    }
    monthly = pd.concat(
        [
            pd.DataFrame(
                {
                    "date": monthly_dates,
                    "resource_id": name,
                    "1": values,
                    "2": values + 0.1 * np.sin(monthly_phase / 3.0),
                }
            )
            for name, values in monthly_series.items()
        ],
        ignore_index=True,
    )
    quarterly_dates = pd.date_range("1993-01-01", "2010-01-01", freq="QS")
    quarterly_phase = np.arange(len(quarterly_dates), dtype=float)
    quarterly_series = {
        "philly_real_output_first_releases": 3.0
        + 1.2 * np.sin(quarterly_phase / 7.0),
        "philly_real_consumption_first_releases": 2.5
        + 0.9 * np.cos(quarterly_phase / 8.0),
    }
    quarterly = pd.concat(
        [
            pd.DataFrame(
                {
                    "date": quarterly_dates,
                    "resource_id": name,
                    "1": values,
                    "2": values + 0.05 * np.cos(quarterly_phase / 4.0),
                }
            )
            for name, values in quarterly_series.items()
        ],
        ignore_index=True,
    )
    return pd.concat([weekly, monthly, quarterly], ignore_index=True)


def _z1_frame() -> pd.DataFrame:
    dates = pd.date_range("1993-03-31", "2009-09-30", freq="QE")
    phase = np.arange(len(dates), dtype=float)
    series = {
        "FL153064105.Q": 4_000.0 + 200.0 * np.sin(phase / 5.0),
        "FL154090005.Q": 10_000.0 + 300.0 * np.cos(phase / 7.0),
        "FL653064100.Q": 2_500.0 + 180.0 * np.sin(phase / 6.0),
        "FL654090000.Q": 5_000.0 + 220.0 * np.cos(phase / 8.0),
        "FA103164105.Q": 120.0 + 30.0 * np.sin(phase / 4.0),
    }
    return pd.concat(
        [
            pd.DataFrame({"date": dates, "series_id": name, "value": values})
            for name, values in series.items()
        ],
        ignore_index=True,
    )


def _realtime_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    vintages = pd.date_range("1993-02-15", "2010-11-15", freq="3MS")
    for index, vintage in enumerate(vintages):
        output_latest = (vintage - pd.offsets.MonthBegin(1)).normalize()
        output_previous = (output_latest - pd.offsets.MonthBegin(3)).normalize()
        unemployment_latest = (vintage - pd.offsets.MonthBegin(1)).normalize()
        unemployment_previous = (
            unemployment_latest - pd.offsets.MonthBegin(3)
        ).normalize()
        rows.extend(
            [
                {
                    "date": vintage,
                    "observation_date": output_previous,
                    "value": 100.0 + index + 0.2 * np.sin(index / 3.0),
                    "resource_id": "real_output_monthly_vintages",
                },
                {
                    "date": vintage,
                    "observation_date": output_latest,
                    "value": 101.0 + index + 0.3 * np.cos(index / 4.0),
                    "resource_id": "real_output_monthly_vintages",
                },
                {
                    "date": vintage,
                    "observation_date": unemployment_previous,
                    "value": 5.0 + 0.5 * np.sin(index / 6.0),
                    "resource_id": "unemployment_quarterly_vintages",
                },
                {
                    "date": vintage,
                    "observation_date": unemployment_latest,
                    "value": 5.1 + 0.5 * np.sin(index / 6.0 + 0.2),
                    "resource_id": "unemployment_quarterly_vintages",
                },
            ]
        )
    return pd.DataFrame(rows)


def _cftc_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    dates = pd.date_range("1993-01-05", "2010-12-21", freq="W-TUE")
    for index, date in enumerate(dates):
        for combined in (False, True):
            phase = float(index)
            multiplier = 1.2 if combined else 1.0
            open_interest = 1_000_000.0 * multiplier * (1.0 + 0.001 * phase)
            rows.append(
                {
                    "date": date,
                    "Market and Exchange Names": (
                        "E-MINI S&P 500 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE"
                    ),
                    "Open Interest (All)": open_interest,
                    "Noncommercial Positions-Long (All)": open_interest
                    * (0.35 + 0.03 * np.sin(phase / 7.0)),
                    "Noncommercial Positions-Short (All)": open_interest
                    * (0.30 + 0.02 * np.cos(phase / 9.0)),
                    "Commercial Positions-Long (All)": open_interest * 0.28,
                    "Commercial Positions-Short (All)": open_interest * 0.33,
                    "Total Reportable Positions-Short (All)": open_interest * 0.66,
                    "Concentration-Net LT =4 TDR-Long (All)": 25.0,
                    "Concentration-Net LT =4 TDR-Short (All)": 28.0,
                    "Concentration-Net LT =8 TDR-Long (All)": 40.0,
                    "Concentration-Net LT =8 TDR-Short (All)": 46.0,
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
    sessions = pd.bdate_range("1993-01-04", "2010-12-31")
    observations = sessions[:-1]
    phase = np.arange(len(observations), dtype=float)
    pd.DataFrame({"date": sessions}).to_parquet(
        snapshot / "D_CALENDAR.parquet", index=False
    )

    monthly_dates = pd.date_range("1993-01-01", "2009-11-01", freq="MS")
    monthly_phase = np.arange(len(monthly_dates), dtype=float)
    pd.DataFrame(
        {
            "date": monthly_dates,
            "resource_id": "predictor_data_updated",
            "Index": 400.0
            * np.exp(0.008 * monthly_phase + 0.04 * np.sin(monthly_phase / 7.0)),
            "D12": 15.0
            * np.exp(0.005 * monthly_phase + 0.03 * np.cos(monthly_phase / 6.0)),
            "E12": 30.0
            * np.exp(0.007 * monthly_phase + 0.05 * np.sin(monthly_phase / 5.0)),
            "b/m": 0.45 + 0.05 * np.cos(monthly_phase / 9.0),
            "ntis": 0.02 * np.sin(monthly_phase / 11.0)
            + 0.006 * np.cos(monthly_phase / 4.0),
        }
    ).to_parquet(snapshot / "D_GOYAL.parquet", index=False)
    pd.DataFrame(
        {
            "date": monthly_dates,
            "12": 18.0 + 3.0 * np.sin(monthly_phase / 13.0),
        }
    ).to_parquet(snapshot / "D_SHILLER.parquet", index=False)
    _z1_frame().to_parquet(snapshot / "D_Z1.parquet", index=False)
    _macro_frame().to_parquet(snapshot / "D_MACRO_PIT.parquet", index=False)

    pd.DataFrame(
        {
            "date": observations,
            "financial_conditions_score": 0.5 * np.sin(phase / 37.0)
            + 0.1 * np.cos(phase / 11.0),
            "rate_level": 4.0 + 0.6 * np.cos(phase / 101.0),
            "volatility_level": 20.0 + 4.0 * np.sin(phase / 31.0),
        }
    ).to_parquet(snapshot / "D_FIN_COND.parquet", index=False)
    pd.DataFrame(
        {
            "date": observations,
            "uncertainty_score": 0.3 + 0.15 * np.sin(phase / 47.0),
            "volatility_level": 20.0 + 4.0 * np.sin(phase / 31.0),
            "absolute_rate_change": 0.03
            + 0.02 * np.abs(np.cos(phase / 29.0)),
        }
    ).to_parquet(snapshot / "D_EPU.parquet", index=False)

    rate_series = {
        "RIFLGFCM03_N.B": 3.7 + 0.5 * np.sin(phase / 103.0),
        "RIFLGFCY10_N.B": 4.3 + 0.5 * np.sin(phase / 103.0 + 0.2),
        "RIMLPAAAR_N.B": 5.0 + 0.2 * np.sin(phase / 71.0),
        "RIMLPBAAR_N.B": 5.9 + 0.3 * np.sin(phase / 71.0 + 0.3),
    }
    pd.concat(
        [
            pd.DataFrame({"date": observations, "series_id": name, "value": values})
            for name, values in rate_series.items()
        ],
        ignore_index=True,
    ).to_parquet(snapshot / "D_RATES.parquet", index=False)
    _realtime_frame().to_parquet(snapshot / "D_PHILLY_RT.parquet", index=False)
    _cftc_frame().to_parquet(snapshot / "D_CFTC_LEGACY.parquet", index=False)

    vxo = pd.DataFrame(
        {
            "date": observations,
            "4": 19.0 + 3.0 * np.sin(phase / 31.0 + 0.2),
            "Unnamed: 4": np.nan,
            "resource_id": "vxo_1986_2003",
            "source_dataset": "D_VXO",
        }
    )
    modern_dates = observations[observations >= pd.Timestamp("2003-09-22")]
    modern_phase = np.arange(len(modern_dates), dtype=float)
    vix = pd.DataFrame(
        {
            "date": modern_dates,
            "CLOSE": 20.0 + 4.0 * np.sin(modern_phase / 31.0),
            "resource_id": "vix_from_2003",
            "source_dataset": "D_VIX",
        }
    )
    pd.concat([vix, vxo], ignore_index=True).to_parquet(
        snapshot / "D_CBOE_VOL.parquet", index=False
    )
    pd.DataFrame(
        {
            "date": monthly_dates,
            "value": 350.0
            * np.exp(0.003 * monthly_phase + 0.04 * np.cos(monthly_phase / 7.0)),
        }
    ).to_parquet(snapshot / "D_GOLD.parquet", index=False)
    pd.DataFrame(
        {
            "date": monthly_dates,
            "value": 35.0
            * np.exp(0.004 * monthly_phase + 0.08 * np.sin(monthly_phase / 5.0)),
        }
    ).to_parquet(snapshot / "D_WTI.parquet", index=False)
    return snapshot


def test_fundamental_smoke_builds_f101_f110_train_only_artifacts(
    tmp_path: Path,
) -> None:
    api = _smoke_api()
    snapshot = _write_inputs(tmp_path)

    report = api.build_fundamental_feature_smoke(
        snapshot,
        output_dir=tmp_path / "out",
    )

    assert report["ready"] is True
    assert report["executable_lanes"] == [f"F{index:03d}" for index in range(101, 111)]
    assert report["executable_lane_count"] == 10
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert report["empty_lanes"] == []
    assert report["exact_duplicate_groups"] == []
    assert report["near_duplicate_pairs"] == []
    parameter_audit = report["parameter_choice_audit"]
    assert parameter_audit["ready"] is True
    assert parameter_audit["expected_choice_probe_count"] == 114
    assert parameter_audit["choice_probe_count"] == 114
    assert parameter_audit["failed_probes"] == []
    assert parameter_audit["inactive_choice_groups"] == []
    assert all(
        item["yearly_non_null_fraction"][1998] == pytest.approx(1.0)
        for item in report["coverage"]
    )
    assert (tmp_path / "out" / "features" / "F101.parquet").is_file()
    assert (tmp_path / "out" / "features" / "F110.parquet").is_file()
    assert (
        tmp_path / "out" / "parameter_choice_audit_F101_F110.json"
    ).is_file()


def test_fundamental_smoke_requires_physical_train_partition(tmp_path: Path) -> None:
    api = _smoke_api()
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(
        api.FundamentalFeatureSmokeError, match="TRAIN_PARTITION_REQUIRED"
    ):
        api.build_fundamental_feature_smoke(wrong, output_dir=tmp_path / "out")


def test_fundamental_smoke_rejects_missing_physical_inputs(tmp_path: Path) -> None:
    api = _smoke_api()
    snapshot = tmp_path / "train_snapshot_1993_2010"
    snapshot.mkdir()

    with pytest.raises(
        api.FundamentalFeatureSmokeError, match="TRAIN_DATASET_MISSING:D_CALENDAR"
    ):
        api.build_fundamental_feature_smoke(snapshot, output_dir=tmp_path / "out")


def test_fundamental_smoke_cli_accepts_the_f101_f110_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cli = importlib.import_module(
        "scripts.run_sp500_megarun_fundamental_feature_smoke_f101"
    )
    monkeypatch.setattr(cli, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(
        cli,
        "build_fundamental_feature_smoke",
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
