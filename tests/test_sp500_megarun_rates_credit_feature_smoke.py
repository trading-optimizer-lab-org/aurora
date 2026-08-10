from __future__ import annotations

import importlib
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


def _api():
    try:
        return importlib.import_module("aurora.infra.sp500_megarun.rates_credit_feature_smoke")
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"rates-credit feature smoke is missing: {exc}")


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

    fed_frames: list[pd.DataFrame] = []
    fed_rates = {
        "RIFLGFCM03_N.B": 2.2 + 0.5 * np.sin(phase / 101.0),
        "RIFLGFCY02_N.B": 2.8 + 0.45 * np.sin(phase / 113.0),
        "RIFLGFCY05_N.B": 3.4 + 0.4 * np.sin(phase / 127.0),
        "RIFLGFCY10_N.B": 4.0 + 0.35 * np.sin(phase / 139.0),
        "RIFLGFCY20_N.B": 4.5 + 0.3 * np.sin(phase / 151.0),
        "RIMLPAAAR_N.B": 5.0 + 0.3 * np.sin(phase / 109.0),
        "RIMLPBAAR_N.B": 6.1 + 0.5 * np.sin((phase + 7.0) / 97.0),
    }
    for series_id, values in fed_rates.items():
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
    pd.concat(fed_frames, ignore_index=True).to_parquet(
        snapshot / "D_FED_H15_H10.parquet", index=False
    )

    macro_frames: list[pd.DataFrame] = []

    def add(resource_id: str, series_id: str, obs: pd.DatetimeIndex, values: object) -> None:
        macro_frames.append(
            pd.DataFrame(
                {"date": obs, "series_id": series_id, "value": values, "resource_id": resource_id}
            )
        )

    cp_rates = {
        "RIFSPPNAAD90_N.B": 3.4 + 0.4 * np.sin(phase / 73.0),
        "RIFSPPNA2P2D90_N.B": 3.9 + 0.6 * np.sin((phase + 5.0) / 67.0),
        "RIFSPPFAAD90_N.B": 3.6 + 0.45 * np.sin((phase + 3.0) / 71.0),
    }
    for series_id, values in cp_rates.items():
        add("federal_reserve_cp_all", series_id, dates, values)
    weekly = dates[2::5]
    wp = np.arange(len(weekly), dtype=float)
    add("federal_reserve_cp_all", "DTBSPCK_N.WW", weekly, 900_000.0 * np.exp(0.0005 * wp))
    add(
        "federal_reserve_cp_all",
        "MKT.1_4.MKT.AMT",
        dates,
        30_000.0 + 5_000.0 * (1.0 + np.sin(phase / 17.0)),
    )
    add(
        "federal_reserve_cp_all",
        "MKT.5_9.MKT.AMT",
        dates,
        20_000.0 + 4_000.0 * (1.0 + np.cos(phase / 19.0)),
    )

    h8 = {
        "B1001NCBA": 3_000_000.0 * np.exp(0.0012 * wp),
        "B1002NCBA": 800_000.0 * np.exp(0.0009 * wp),
        "B1020NCBA": 2_200_000.0 * np.exp(0.0013 * wp),
        "B1023NCBA": 600_000.0 * np.exp(0.0011 * wp + 0.01 * np.sin(wp / 13.0)),
        "B1026NCBA": 900_000.0 * np.exp(0.0014 * wp),
        "B1029NCBA": 350_000.0 * np.exp(0.0010 * wp),
    }
    for series_id, values in h8.items():
        add("federal_reserve_h8_all", series_id, weekly, values)
    mondays = dates[dates.weekday == 0]
    mp = np.arange(len(mondays), dtype=float)
    add("federal_reserve_h6_all", "M1.WM", mondays, 1_100.0 * np.exp(0.0008 * mp))
    add("federal_reserve_h6_all", "M2.WM", mondays, 4_000.0 * np.exp(0.0010 * mp))
    add("federal_reserve_h3_all", "RESMO14A_N.WW", weekly, 500_000.0 * np.exp(0.0010 * wp))
    add("federal_reserve_h3_all", "RESTR14A_N.WW", weekly, 45_000.0 * np.exp(0.0008 * wp))
    add(
        "federal_reserve_h3_all",
        "RESBR14A_N.WW",
        weekly,
        1_000.0 * np.exp(0.0009 * wp + 0.02 * np.sin(wp / 11.0)),
    )
    months = pd.date_range("2003-01-31", "2010-10-31", freq="ME")
    mop = np.arange(len(months), dtype=float)
    add("federal_reserve_g19_all", "DTCTL.M", months, 900_000.0 * np.exp(0.004 * mop))
    add("federal_reserve_g19_all", "DTCTLR.M", months, 300_000.0 * np.exp(0.0045 * mop))
    add("federal_reserve_g19_all", "DTCTLN.M", months, 600_000.0 * np.exp(0.0038 * mop))
    pd.concat(macro_frames, ignore_index=True).to_parquet(
        snapshot / "D_FED_H3_H6_H8_G19_CP.parquet", index=False
    )

    spf_rows: list[dict[str, object]] = []
    for year in range(2003, 2011):
        for quarter in range(1, 5):
            for offset, sheet in enumerate(("RR1_TBILL_CPI", "RR1_TBILL_PCE", "RR1_TBILL_PGDP")):
                spf_rows.append(
                    {
                        "0": year,
                        "1": quarter,
                        "6": 1.0 + 0.1 * offset + 0.03 * (year - 2003) + 0.02 * quarter,
                        "date": pd.Timestamp(year, 1, 1),
                        "source_sheet": sheet,
                        "resource_id": "spf_median_level",
                    }
                )
    pd.DataFrame(spf_rows).to_parquet(snapshot / "D_SPF.parquet", index=False)

    vol_frames = []
    vxo = 18.0 + 3.0 * np.sin(phase / 37.0)
    vol_frames.append(
        pd.DataFrame(
            {"date": dates, "4": vxo, "resource_id": "vxo_1986_2003", "source_dataset": "D_VXO"}
        )
    )
    vol_frames.append(
        pd.DataFrame(
            {
                "date": dates,
                "DATE": dates.strftime("%m/%d/%Y"),
                "CLOSE": vxo + 0.3,
                "resource_id": "vix_from_2003",
                "source_dataset": "D_VIX",
            }
        )
    )
    pd.concat(vol_frames, ignore_index=True, sort=False).to_parquet(
        snapshot / "D_CBOE_VOL.parquet", index=False
    )
    return snapshot


def test_rates_credit_smoke_builds_f181_f190_train_only_artifacts(tmp_path: Path) -> None:
    snapshot = _write_snapshot(tmp_path)

    report = _api().build_rates_credit_feature_smoke(snapshot, output_dir=tmp_path / "out")

    assert report["ready"] is True
    assert report["executable_lanes"] == [f"F{i:03d}" for i in range(181, 191)]
    assert report["executable_lane_count"] == 10
    assert report["fed_missing_sentinel"] == -9999.0
    assert report["f183_fidelity"] == "official_spf_expected_real_rate_proxy"
    assert report["f185_default"] == "outstanding_contraction_full_history"
    assert set(report["f185_component_first_available_at"]) == {
        "cp_outstanding",
        "aa_nonfinancial_90d",
        "a2p2_nonfinancial_90d",
        "aa_financial_90d",
        "issuance_amount",
    }
    assert report["historical_revision_pit_exact"] is False
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert report["empty_lanes"] == []
    assert (tmp_path / "out" / "features" / "F181.parquet").is_file()
    assert (tmp_path / "out" / "features" / "F190.parquet").is_file()


def test_rates_credit_smoke_requires_physical_train_partition(tmp_path: Path) -> None:
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(_api().RatesCreditFeatureSmokeError, match="TRAIN_PARTITION_REQUIRED"):
        _api().build_rates_credit_feature_smoke(wrong, output_dir=tmp_path / "out")


def test_rates_credit_smoke_rejects_missing_macro_release(tmp_path: Path) -> None:
    snapshot = _write_snapshot(tmp_path)
    macro = pd.read_parquet(snapshot / "D_FED_H3_H6_H8_G19_CP.parquet")
    macro.loc[macro["resource_id"].ne("federal_reserve_g19_all")].to_parquet(
        snapshot / "D_FED_H3_H6_H8_G19_CP.parquet", index=False
    )

    with pytest.raises(
        _api().RatesCreditFeatureSmokeError,
        match="FED_MACRO_SOURCE_MISSING:federal_reserve_g19_all",
    ):
        _api().build_rates_credit_feature_smoke(snapshot, output_dir=tmp_path / "out")


def test_rates_credit_smoke_cli_accepts_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = importlib.import_module("scripts.run_sp500_megarun_rates_credit_feature_smoke_f181")
    monkeypatch.setattr(cli, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(
        cli,
        "build_rates_credit_feature_smoke",
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
