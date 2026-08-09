from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def _smoke_api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.macro_feature_smoke"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"macro feature smoke is missing: {exc}")


def _write_train_snapshot(root: Path) -> Path:
    snapshot = root / "train_snapshot_1993_2010"
    snapshot.mkdir()
    dates = pd.bdate_range("2005-01-03", "2010-12-31")
    rows: list[dict[str, object]] = []
    for position, date in enumerate(dates):
        phase = float(position)
        aaa = 4.0 + 0.1 * np.sin(phase / 40.0)
        spread = 1.5 + 0.2 * np.sin(phase / 17.0) + 0.0002 * phase
        rows.extend(
            [
                {"date": date, "series_id": "RIMLPAAAR_N.B", "value": aaa},
                {
                    "date": date,
                    "series_id": "RIMLPBAAR_N.B",
                    "value": aaa + spread,
                },
                {
                    "date": date,
                    "series_id": "RIFLGFCY10_N.B",
                    "value": 3.0 + 0.1 * np.sin(phase / 30.0),
                },
            ]
        )
    pd.DataFrame(rows).to_parquet(snapshot / "D_RATES.parquet", index=False)
    pd.DataFrame({"date": dates}).to_parquet(
        snapshot / "D_CALENDAR.parquet", index=False
    )
    pd.DataFrame(
        {
            "date": dates,
            "financial_conditions_score": np.sin(np.arange(len(dates)) / 20.0),
            "rate_level": 2.0 + np.arange(len(dates)) / 10000.0,
            "volatility_level": 20.0 + np.cos(np.arange(len(dates)) / 15.0),
        }
    ).to_parquet(snapshot / "D_FIN_COND.parquet", index=False)
    vintage_rows: list[dict[str, object]] = []
    for vintage in pd.date_range("2007-02-15", "2010-11-15", freq="3MS"):
        quarter = vintage.to_period("Q").start_time - pd.offsets.QuarterBegin(startingMonth=1)
        vintage_rows.extend(
            [
                {
                    "date": vintage,
                    "observation_date": quarter - pd.offsets.QuarterBegin(startingMonth=1),
                    "value": 100.0 + len(vintage_rows),
                    "resource_id": "real_output_monthly_vintages",
                },
                {
                    "date": vintage,
                    "observation_date": quarter,
                    "value": 101.0 + len(vintage_rows),
                    "resource_id": "real_output_monthly_vintages",
                },
            ]
        )
    pd.DataFrame(vintage_rows).to_parquet(
        snapshot / "D_PHILLY_RT.parquet", index=False
    )
    macro_rows: list[dict[str, object]] = []
    resources = {
        "philly_payroll_first_releases": "monthly",
        "philly_industrial_production_first_releases": "monthly",
        "philly_housing_starts_first_releases": "monthly",
        "philly_cpi_first_releases": "monthly",
        "philly_real_output_first_releases": "quarterly",
        "philly_real_consumption_first_releases": "quarterly",
    }
    for resource_id, frequency in resources.items():
        periods = (
            pd.date_range("2007-01-01", "2010-10-01", freq="QS")
            if frequency == "quarterly"
            else pd.date_range("2007-01-01", "2010-11-01", freq="MS")
        )
        for position, period in enumerate(periods):
            base = 2.0 + 0.1 * position
            if "payroll" in resource_id:
                base = 100.0 + position
            elif "housing" in resource_id:
                base = 800.0 + 2.0 * position
            macro_rows.append(
                {
                    "date": period,
                    "resource_id": resource_id,
                    "1": base,
                    "2": base + 0.1 * np.sin(float(position) / 3.0),
                }
            )
    pd.DataFrame(macro_rows).to_parquet(
        snapshot / "D_MACRO_PIT.parquet", index=False
    )
    pd.DataFrame(
        {
            "date": pd.date_range("2007-01-30", "2010-12-01", freq="60D"),
            "document_kind": "meeting",
        }
    ).to_parquet(snapshot / "D_FOMC_PUBLIC.parquet", index=False)
    valuation_dates = pd.date_range("2004-01-01", "2010-11-01", freq="MS")
    valuation_phase = np.arange(len(valuation_dates), dtype=float)
    pd.DataFrame(
        {
            "date": valuation_dates,
            "resource_id": "predictor_data_updated",
            "Index": 100.0 + valuation_phase,
            "D12": 4.0 + valuation_phase / 20.0,
            "E12": 8.0 + valuation_phase / 10.0 + np.sin(valuation_phase / 4.0),
            "b/m": 0.4 + valuation_phase / 1000.0,
            "ntis": 0.03 - valuation_phase / 10000.0,
        }
    ).to_parquet(snapshot / "D_GOYAL.parquet", index=False)
    pd.DataFrame(
        {
            "date": valuation_dates,
            "12": 20.0 + np.sin(valuation_phase / 5.0),
            "resource_id": "shiller_ie_data",
        }
    ).to_parquet(snapshot / "D_SHILLER.parquet", index=False)
    return snapshot


def test_macro_smoke_builds_f032_f040_train_only_artifacts(tmp_path: Path) -> None:
    api = _smoke_api()
    snapshot = _write_train_snapshot(tmp_path)

    report = api.build_macro_feature_smoke(snapshot, output_dir=tmp_path / "out")

    assert report["ready"] is True
    assert report["executable_lanes"] == [f"F{index:03d}" for index in range(32, 41)]
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert (tmp_path / "out" / "features" / "F032.parquet").is_file()
    assert (tmp_path / "out" / "features" / "F040.parquet").is_file()


def test_macro_smoke_requires_the_physical_train_partition(tmp_path: Path) -> None:
    api = _smoke_api()
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(api.MacroFeatureSmokeError, match="TRAIN_PARTITION_REQUIRED"):
        api.build_macro_feature_smoke(wrong, output_dir=tmp_path / "out")
