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
    market_phase = np.arange(len(dates), dtype=float)
    market_close = 100.0 * np.exp(
        np.cumsum(0.0002 + 0.002 * np.sin(market_phase / 17.0))
    )
    pd.DataFrame(
        {
            "date": dates,
            "open": market_close * 0.999,
            "high": market_close * 1.005,
            "low": market_close * 0.995,
            "close": market_close,
            "volume": 1_000_000.0 + market_phase,
        }
    ).to_parquet(snapshot / "D_SPY.parquet", index=False)
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

    fx_rows: list[dict[str, object]] = []
    fx_series = {
        "V0.JRXWTFB_N.B": 100.0 + market_phase / 100.0,
        "RXI_N.B.CA": 1.1 + 0.01 * np.sin(market_phase / 9.0),
        "RXI_N.B.JA": 100.0 + np.sin(market_phase / 7.0),
        "RXI_N.B.SZ": 1.0 + 0.01 * np.cos(market_phase / 11.0),
        "RXI$US_N.B.UK": 1.6 + 0.01 * np.sin(market_phase / 13.0),
    }
    shock_rows = np.arange(80, len(dates), 137)
    for series_index, values in enumerate(fx_series.values(), start=1):
        values[shock_rows] *= 1.0 + 0.003 * series_index
    for series_id, values in fx_series.items():
        fx_rows.extend(
            {"date": date, "series_id": series_id, "value": value}
            for date, value in zip(dates, values, strict=True)
        )
    pd.DataFrame(fx_rows).to_parquet(snapshot / "D_FX.parquet", index=False)

    commodity_dates = pd.date_range("2004-01-01", "2010-12-01", freq="MS")
    commodity_phase = np.arange(len(commodity_dates), dtype=float)
    pd.DataFrame(
        {"date": commodity_dates, "value": 400.0 + commodity_phase * 4.0}
    ).to_parquet(snapshot / "D_GOLD.parquet", index=False)
    pd.DataFrame(
        {"date": commodity_dates, "value": 40.0 + 5.0 * np.sin(commodity_phase / 4.0)}
    ).to_parquet(snapshot / "D_WTI.parquet", index=False)

    factor_phase = np.arange(len(dates), dtype=float)
    pd.DataFrame(
        {
            "date": dates,
            "resource_id": "ff3_daily",
            "Mkt-RF": 0.1 * np.sin(factor_phase / 5.0),
            "SMB": 0.1 * np.cos(factor_phase / 7.0),
            "HML": 0.1 * np.sin(factor_phase / 9.0),
            "RF": 0.01,
        }
    ).to_parquet(snapshot / "D_FRENCH_FACTORS.parquet", index=False)
    industry_names = [
        "Autos", "Cnstr", "Steel", "Mach", "Chips", "Fin", "Rtail", "Trans",
        "Food", "Beer", "Smoke", "Hlth", "Drugs", "Util",
    ]
    industry_data: dict[str, object] = {
        "date": dates,
        "resource_id": "industry_48_daily",
    }
    for index, name in enumerate(industry_names, start=1):
        industry_data[name] = 0.2 * np.sin(factor_phase / (3.0 + index))
    pd.DataFrame(industry_data).to_parquet(
        snapshot / "D_FRENCH_INDUSTRIES.parquet", index=False
    )

    z1_rows: list[dict[str, object]] = []
    z1_dates = pd.date_range("2003-03-31", "2009-09-30", freq="QE")
    for position, date in enumerate(z1_dates):
        z1_values = {
            "FL153064105.Q": 400.0 + position * 8.0,
            "FL154090005.Q": 1000.0 + position * 10.0,
            "FL653064100.Q": 300.0 + position * 5.0,
            "FL654090000.Q": 600.0 + position * 7.0,
        }
        z1_rows.extend(
            {"date": date, "series_id": series_id, "value": value}
            for series_id, value in z1_values.items()
        )
    pd.DataFrame(z1_rows).to_parquet(snapshot / "D_Z1.parquet", index=False)

    margin_dates = pd.date_range("2004-01-01", "2010-10-01", freq="MS")
    margin_phase = np.arange(len(margin_dates), dtype=float)
    pd.DataFrame(
        {
            "date": margin_dates,
            "Debit Balances in Customers' Securities Margin Accounts": 100.0 + margin_phase * 2.0,
            "Free Credit Balances in Customers' Cash Accounts": 80.0 + margin_phase,
            "Free Credit Balances in Customers' Securities Margin Accounts": 20.0 + margin_phase / 2.0,
        }
    ).to_parquet(snapshot / "D_FINRA_MARGIN.parquet", index=False)

    cftc_rows: list[dict[str, object]] = []
    for position, date in enumerate(pd.date_range("2004-01-06", "2010-12-21", freq="W-TUE")):
        cftc_rows.append(
            {
                "date": date,
                "Market and Exchange Names": "E-MINI S&P 500 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE",
                "Open Interest (All)": str(1000 + position * 5),
                "Noncommercial Positions-Long (All)": str(400 + position),
                "Noncommercial Positions-Short (All)": str(300 + position // 2),
                "Commercial Positions-Long (All)": str(250 + position // 3),
                "Commercial Positions-Short (All)": str(350 + position // 4),
                "Concentration-Net LT =4 TDR-Long (All)": "25",
                "Concentration-Net LT =4 TDR-Short (All)": "30",
                "resource_id": "legacy_futures_only:synthetic",
            }
        )
    pd.DataFrame(cftc_rows).to_parquet(
        snapshot / "D_CFTC_LEGACY.parquet", index=False
    )
    return snapshot


def test_macro_smoke_builds_f032_f050_train_only_artifacts(tmp_path: Path) -> None:
    api = _smoke_api()
    snapshot = _write_train_snapshot(tmp_path)

    report = api.build_macro_feature_smoke(snapshot, output_dir=tmp_path / "out")

    assert report["ready"] is True
    assert report["executable_lanes"] == [f"F{index:03d}" for index in range(32, 51)]
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert report["parameter_choice_audit"]["ready"] is True
    assert report["parameter_choice_audit"]["choice_probe_count"] == report[
        "parameter_choice_audit"
    ]["expected_choice_probe_count"]
    assert report["parameter_choice_audit"]["validation_opened"] is False
    assert report["parameter_choice_audit"]["locked_opened"] is False
    assert (tmp_path / "out" / "features" / "F032.parquet").is_file()
    assert (tmp_path / "out" / "features" / "F040.parquet").is_file()
    assert (tmp_path / "out" / "features" / "F050.parquet").is_file()
    assert (tmp_path / "out" / "parameter_choice_audit_F032_F050.json").is_file()


def test_macro_smoke_requires_the_physical_train_partition(tmp_path: Path) -> None:
    api = _smoke_api()
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(api.MacroFeatureSmokeError, match="TRAIN_PARTITION_REQUIRED"):
        api.build_macro_feature_smoke(wrong, output_dir=tmp_path / "out")


def test_macro_smoke_cli_accepts_the_f032_f050_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cli = importlib.import_module("scripts.run_sp500_megarun_macro_feature_smoke_f032")
    monkeypatch.setattr(cli, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(
        cli,
        "build_macro_feature_smoke",
        lambda *_args, **_kwargs: {"ready": True, "executable_lane_count": 19},
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
