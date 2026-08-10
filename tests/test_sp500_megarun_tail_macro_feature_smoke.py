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
            "aurora.infra.sp500_megarun.tail_macro_feature_smoke"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"tail/macro feature smoke is missing: {exc}")


def _cftc_frame(dates: pd.DatetimeIndex) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index, date in enumerate(dates):
        phase = float(index)
        for combined in (False, True):
            multiplier = 1.2 if combined else 1.0
            open_interest = 1_000_000.0 * multiplier * (
                1.0 + 0.001 * phase
            )
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
                    * (0.30 + 0.02 * np.cos(phase / 9.0)),
                    "Commercial Positions-Long (All)": open_interest * 0.28,
                    "Commercial Positions-Short (All)": open_interest * 0.33,
                    "Total Reportable Positions-Long (All)": open_interest * 0.72,
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


def _rates_frame(dates: pd.DatetimeIndex) -> pd.DataFrame:
    phase = np.arange(len(dates), dtype=float)
    series = {
        "RIFLGFCM03_N.B": 3.0 + 0.3 * np.sin(phase / 31.0),
        "RIFLGFCY02_N.B": 3.3 + 0.4 * np.sin(phase / 43.0),
        "RIFLGFCY05_N.B": 3.7 + 0.5 * np.sin(phase / 59.0),
        "RIFLGFCY10_N.B": 4.0 + 0.6 * np.sin(phase / 71.0),
        "RIFLGFCY30_N.B": 4.4 + 0.7 * np.sin(phase / 83.0),
        "RIFSPFF_N.B": 3.5 + 1.2 * np.sin(phase / 127.0),
    }
    return pd.concat(
        [
            pd.DataFrame({"date": dates, "series_id": name, "value": values})
            for name, values in series.items()
        ],
        ignore_index=True,
    )


def _macro_frame() -> pd.DataFrame:
    weekly_dates = pd.date_range("1993-01-06", "2010-12-15", freq="W-WED")
    phase = np.arange(len(weekly_dates), dtype=float)
    weekly_series = {
        "RESMO14A_N.WW": 500.0
        * np.exp(0.001 * phase + 0.03 * np.sin(phase / 11.0)),
        "RESTR14A_N.WW": 60.0
        * np.exp(0.0015 * phase + 0.08 * np.sin(phase / 7.0)),
        "M2.WM": 4_000.0
        * np.exp(0.0012 * phase + 0.04 * np.cos(phase / 13.0)),
        "B1001NCBA": 3_500.0
        * np.exp(0.0013 * phase + 0.05 * np.sin(phase / 9.0)),
        "B1020NCBA": 2_700.0
        * np.exp(0.0014 * phase + 0.06 * np.cos(phase / 10.0)),
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
        "philly_cpi_first_releases": 2.0
        + 0.5 * np.sin(monthly_phase / 9.0),
        "philly_core_cpi_first_releases": 2.1
        + 0.4 * np.cos(monthly_phase / 11.0),
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
        "philly_core_pce_first_releases": 1.9
        + 0.3 * np.sin(quarterly_phase / 5.0),
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


def _write_inputs(root: Path) -> Path:
    snapshot = root / "train_snapshot_1993_2010"
    snapshot.mkdir()
    sessions = pd.bdate_range("1993-01-04", "2010-12-31")
    observations = sessions[:-1]
    phase = np.arange(len(observations), dtype=float)
    returns = 0.0002 + 0.004 * np.sin(phase / 17.0) + 0.001 * np.cos(
        phase / 41.0
    )
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]] * (
        1.0 + 0.0006 * np.sin(phase / 9.0)
    )
    daily_range = 0.003 + 0.002 * (1.0 + np.cos(phase / 23.0))
    pd.DataFrame({"date": sessions}).to_parquet(
        snapshot / "D_CALENDAR.parquet", index=False
    )
    pd.DataFrame(
        {
            "date": observations,
            "open": open_,
            "high": np.maximum(open_, close) * (1.0 + daily_range),
            "low": np.minimum(open_, close) * (1.0 - daily_range),
            "close": close,
            "volume": 1_000_000.0 * np.exp(0.2 * np.sin(phase / 29.0)),
        }
    ).to_parquet(snapshot / "D_SPY.parquet", index=False)
    pd.DataFrame(
        {
            "date": observations,
            "CLOSE": 20.0 + 4.0 * np.sin(phase / 31.0),
            "resource_id": "vix_from_2003",
        }
    ).to_parquet(snapshot / "D_VIX.parquet", index=False)
    pd.DataFrame(
        {
            "date": observations,
            "4": 19.0 + 3.0 * np.sin(phase / 31.0 + 0.2),
            "Unnamed: 4": np.nan,
            "resource_id": "vxo_1986_2003",
        }
    ).to_parquet(snapshot / "D_VXO.parquet", index=False)
    cftc_dates = pd.date_range("1993-01-05", "2010-12-21", freq="W-TUE")
    _cftc_frame(cftc_dates).to_parquet(snapshot / "D_CFTC.parquet", index=False)
    _rates_frame(observations).to_parquet(snapshot / "D_RATES.parquet", index=False)
    _macro_frame().to_parquet(snapshot / "D_MACRO_PIT.parquet", index=False)
    fomc_dates = observations[40::42]
    pd.DataFrame(
        {
            "date": fomc_dates,
            "document_kind": "meeting",
            "document_reference": [
                f"Synthetic public meeting {date.date().isoformat()}"
                for date in fomc_dates
            ],
        }
    ).to_parquet(snapshot / "D_FOMC_PUBLIC.parquet", index=False)
    return snapshot


def test_tail_macro_smoke_builds_f091_f100_train_only_artifacts(
    tmp_path: Path,
) -> None:
    api = _smoke_api()
    snapshot = _write_inputs(tmp_path)

    report = api.build_tail_macro_feature_smoke(
        snapshot,
        output_dir=tmp_path / "out",
    )

    assert report["ready"] is True
    assert report["executable_lanes"] == [f"F{index:03d}" for index in range(91, 101)]
    assert report["executable_lane_count"] == 10
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert report["empty_lanes"] == []
    assert report["exact_duplicate_groups"] == []
    assert report["near_duplicate_pairs"] == []
    parameter_audit = report["parameter_choice_audit"]
    assert parameter_audit["ready"] is True
    assert parameter_audit["expected_choice_probe_count"] == 125
    assert parameter_audit["choice_probe_count"] == 125
    assert parameter_audit["failed_probes"] == []
    assert parameter_audit["inactive_choice_groups"] == []
    assert (tmp_path / "out" / "features" / "F091.parquet").is_file()
    assert (tmp_path / "out" / "features" / "F100.parquet").is_file()
    assert (
        tmp_path / "out" / "parameter_choice_audit_F091_F100.json"
    ).is_file()


def test_tail_macro_smoke_requires_physical_train_partition(tmp_path: Path) -> None:
    api = _smoke_api()
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(
        api.TailMacroFeatureSmokeError, match="TRAIN_PARTITION_REQUIRED"
    ):
        api.build_tail_macro_feature_smoke(wrong, output_dir=tmp_path / "out")


def test_tail_macro_smoke_rejects_missing_physical_inputs(tmp_path: Path) -> None:
    api = _smoke_api()
    snapshot = tmp_path / "train_snapshot_1993_2010"
    snapshot.mkdir()

    with pytest.raises(
        api.TailMacroFeatureSmokeError, match="TRAIN_DATASET_MISSING:D_SPY"
    ):
        api.build_tail_macro_feature_smoke(snapshot, output_dir=tmp_path / "out")


def test_tail_macro_smoke_cli_accepts_the_f091_f100_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cli = importlib.import_module(
        "scripts.run_sp500_megarun_tail_macro_feature_smoke_f091"
    )
    monkeypatch.setattr(cli, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(
        cli,
        "build_tail_macro_feature_smoke",
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
