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
            "aurora.infra.sp500_megarun.realtime_survey_feature_smoke"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"realtime-survey feature smoke is missing: {exc}")


def _write_snapshot(root: Path) -> Path:
    snapshot = root / "train_snapshot_1993_2010"
    snapshot.mkdir()
    dates = pd.bdate_range("2003-01-02", "2010-12-31")
    phase = np.arange(len(dates), dtype=float)
    close = 100.0 * np.exp(np.cumsum(0.0003 + 0.004 * np.sin(phase / 31.0)))
    pd.DataFrame({"date": dates}).to_parquet(snapshot / "D_CALENDAR.parquet", index=False)
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

    realtime_rows: list[dict[str, object]] = []
    quarter_vintages = pd.date_range("2003-02-15", "2010-11-15", freq="3MS")
    quarterly_resources = {
        "real_output_quarterly_vintages": (5_000.0, 80.0),
        "real_gdi_quarterly_vintages": (4_900.0, 75.0),
        "nominal_consumption_quarterly_vintages": (7_000.0, 90.0),
        "nominal_disposable_income_quarterly_vintages": (8_000.0, 100.0),
        "saving_rate_quarterly_vintages": (5.0, 0.05),
    }
    for vintage_index, vintage in enumerate(quarter_vintages):
        observations = pd.date_range("2002-07-01", periods=vintage_index + 2, freq="QS")
        for offset, (resource_id, (base, step)) in enumerate(quarterly_resources.items()):
            for observation_index, observation in enumerate(observations):
                realtime_rows.append(
                    {
                        "date": vintage,
                        "observation_date": observation,
                        "value": base
                        + step * observation_index
                        + 0.2 * vintage_index * np.sin((observation_index + offset + 1) / 5.0),
                        "resource_id": resource_id,
                    }
                )
        for observation_index, observation in enumerate(observations):
            realtime_rows.append(
                {
                    "date": vintage,
                    "observation_date": observation,
                    "value": 5_000.0 + 80.0 * observation_index + 0.3 * vintage_index,
                    "resource_id": "real_output_monthly_vintages",
                }
            )
            realtime_rows.append(
                {
                    "date": vintage,
                    "observation_date": observation,
                    "value": 6.0 - 0.02 * observation_index + 0.05 * np.sin(vintage_index / 4.0),
                    "resource_id": "unemployment_quarterly_vintages",
                }
            )
    pd.DataFrame(realtime_rows).to_parquet(snapshot / "D_PHILLY_RT.parquet", index=False)

    macro_rows: list[dict[str, object]] = []
    monthly = pd.date_range("2003-01-01", "2010-12-01", freq="MS")
    quarterly = pd.date_range("2003-01-01", "2010-10-01", freq="QS")
    resources = {
        "philly_cpi_first_releases": (monthly, 2.2),
        "philly_core_cpi_first_releases": (monthly, 2.0),
        "philly_core_pce_first_releases": (quarterly, 1.9),
        "philly_payroll_first_releases": (monthly, 150.0),
        "philly_industrial_production_first_releases": (monthly, 2.0),
        "philly_manufacturing_production_first_releases": (monthly, 1.8),
        "philly_capacity_utilization_first_releases": (monthly, 77.0),
        "philly_manufacturing_capacity_first_releases": (monthly, 75.0),
        "philly_housing_starts_first_releases": (monthly, 1_400.0),
        "philly_real_output_first_releases": (quarterly, 2.8),
        "philly_real_consumption_first_releases": (quarterly, 3.0),
        "philly_nonresidential_investment_first_releases": (quarterly, 3.2),
        "philly_residential_investment_first_releases": (quarterly, 2.5),
    }
    for offset, (resource_id, (observations, base)) in enumerate(resources.items()):
        values = np.arange(len(observations), dtype=float)
        first = base + (0.05 * max(abs(base), 1.0)) * np.sin((values + offset) / 6.0)
        for observation, first_value, delta in zip(
            observations, first, 0.02 * np.cos((values + offset) / 5.0), strict=True
        ):
            macro_rows.append(
                {
                    "date": observation,
                    "resource_id": resource_id,
                    "1": first_value,
                    "2": first_value + delta,
                }
            )
    pd.DataFrame(macro_rows).to_parquet(snapshot / "D_MACRO_PIT.parquet", index=False)

    spf_rows: list[dict[str, object]] = []
    for survey_index, survey in enumerate(pd.period_range("2003Q1", "2010Q4", freq="Q")):
        year, quarter = survey.year, survey.quarter
        base_levels = {
            "RGDP": 10_000.0 + 100.0 * survey_index,
            "UNEMP": 6.0 + 0.3 * np.sin(survey_index / 5.0),
            "CPI": 2.2 + 0.4 * np.sin(survey_index / 6.0),
            "HOUSING": 1.4 + 0.1 * np.cos(survey_index / 7.0),
            "TBILL": 2.0 + 0.5 * np.cos(survey_index / 8.0),
        }
        for sheet, base in base_levels.items():
            if sheet in {"RGDP", "HOUSING"}:
                values = (base, base * 1.006, base * 1.012)
            else:
                values = (base, base + 0.05, base + 0.1)
            spf_rows.append(
                {
                    "0": str(year),
                    "1": quarter,
                    "2": values[0],
                    "3": values[1],
                    "4": values[2],
                    "source_sheet": sheet,
                    "resource_id": "spf_median_level",
                    "date": survey.start_time,
                }
            )
        for offset, sheet in enumerate(("NGDP", "UNEMP", "CPI", "HOUSING", "TBILL")):
            spf_rows.append(
                {
                    "0": str(survey),
                    "3": 0.2 + 0.04 * offset + 0.03 * np.sin((survey_index + offset) / 4.0),
                    "source_sheet": sheet,
                    "resource_id": "spf_dispersion",
                    "date": survey.start_time,
                }
            )
    pd.DataFrame(spf_rows).to_parquet(snapshot / "D_SPF.parquet", index=False)

    sloos_rows: list[dict[str, object]] = []
    sloos_series = (
        "SUBLPDCILS_N.Q",
        "SUBLPDCILD_N.Q",
        "SUBLPDCISS_N.Q",
        "SUBLPDCISD_N.Q",
        "SUBLPDCILTC_N.Q",
        "SUBLPDCILTL_N.Q",
        "SUBLPDCILTM_N.Q",
        "SUBLPDCILTQ_N.Q",
        "SUBLPDCILTS_N.Q",
    )
    for quarter_index, quarter_end in enumerate(
        pd.date_range("2003-03-31", "2010-12-31", freq="QE")
    ):
        for offset, series_id in enumerate(sloos_series):
            sloos_rows.append(
                {
                    "date": quarter_end,
                    "series_id": series_id,
                    "value": 10.0 + 8.0 * np.sin((quarter_index + offset) / 5.0),
                }
            )
    pd.DataFrame(sloos_rows).to_parquet(snapshot / "D_SLOOS.parquet", index=False)
    return snapshot


def test_realtime_survey_smoke_builds_f191_f200_train_only_artifacts(tmp_path: Path) -> None:
    snapshot = _write_snapshot(tmp_path)

    report = _api().build_realtime_survey_feature_smoke(
        snapshot, output_dir=tmp_path / "out"
    )

    assert report["ready"] is True
    assert report["executable_lanes"] == [f"F{i:03d}" for i in range(191, 201)]
    assert report["executable_lane_count"] == 10
    assert report["row_release_causality_valid"] is True
    assert report["sloos_release_policy"] == "quarter_end_plus_60_days_next_spy_session"
    assert report["sloos_historical_revision_pit_exact"] is False
    assert report["f191_default"] == "output_growth_full_train_history"
    assert set(report["f191_component_first_available_at"]) == {
        "output_growth",
        "gdi_growth",
    }
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert report["empty_lanes"] == []
    assert (tmp_path / "out" / "features" / "F191.parquet").is_file()
    assert (tmp_path / "out" / "features" / "F200.parquet").is_file()


def test_realtime_survey_smoke_requires_physical_train_partition(tmp_path: Path) -> None:
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(_api().RealtimeSurveyFeatureSmokeError, match="TRAIN_PARTITION_REQUIRED"):
        _api().build_realtime_survey_feature_smoke(wrong, output_dir=tmp_path / "out")


def test_realtime_survey_smoke_cli_accepts_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = importlib.import_module("scripts.run_sp500_megarun_realtime_survey_feature_smoke_f191")
    monkeypatch.setattr(cli, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(
        cli,
        "build_realtime_survey_feature_smoke",
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
