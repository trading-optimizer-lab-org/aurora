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
            "aurora.infra.sp500_megarun.public_context_feature_smoke"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"public-context feature smoke is missing: {exc}")


def _write_snapshot(root: Path) -> Path:
    snapshot = root / "train_snapshot_1993_2010"
    snapshot.mkdir()
    sessions = pd.bdate_range("1997-01-02", "2010-12-31")
    phase = np.arange(len(sessions), dtype=float)
    close = 100.0 * np.exp(
        np.cumsum(0.0002 + 0.005 * np.sin(phase / 31.0) + 0.002 * np.cos(phase / 11.0))
    )
    pd.DataFrame({"date": sessions}).to_parquet(
        snapshot / "D_CALENDAR.parquet", index=False
    )
    pd.DataFrame(
        {
            "date": sessions,
            "open": np.r_[close[0], close[:-1]],
            "high": close * 1.006,
            "low": close * 0.994,
            "close": close,
            "volume": 1_000_000.0 + 100_000.0 * np.sin(phase / 17.0),
        }
    ).to_parquet(snapshot / "D_SPY.parquet", index=False)

    vintage_dates = pd.date_range("1997-01-15", "2010-12-15", freq="MS") + pd.Timedelta(days=14)
    philly_rows: list[dict[str, object]] = []
    resources = (
        ("real_output_monthly_vintages", "routput"),
        ("real_output_quarterly_vintages", "ROUTPUT"),
        ("unemployment_quarterly_vintages", "ruc"),
        ("saving_rate_quarterly_vintages", "ratesav"),
    )
    for index, date in enumerate(vintage_dates):
        for resource_number, (resource_id, sheet) in enumerate(resources[: 2 + index % 3]):
            philly_rows.append(
                {
                    "date": date,
                    "observation_date": date - pd.DateOffset(months=1 + resource_number),
                    "value": 100.0 + index + resource_number,
                    "vintage_label": f"V{index:03d}-{resource_number}",
                    "source_sheet": sheet,
                    "resource_id": resource_id,
                }
            )
    pd.DataFrame(philly_rows).to_parquet(snapshot / "D_PHILLY_RT.parquet", index=False)

    announcement_dates = sessions[10::10]
    auction_rows: list[dict[str, object]] = []
    for index, announcement in enumerate(announcement_dates):
        auction = announcement + pd.offsets.BDay(3 + index % 3)
        issue = auction + pd.offsets.BDay(2)
        if issue > pd.Timestamp("2010-12-31"):
            continue
        for kind, years, weight in (("Bill", 0.5, 0.45), ("Note", 5.0, 0.55)):
            offering = (20e9 + 4e9 * np.sin(index / 9.0) + 20e6 * index) * weight
            auction_rows.append(
                {
                    "date": issue,
                    "announcemt_date": announcement,
                    "auction_date": auction,
                    "issue_date": issue,
                    "maturity_date": issue + pd.Timedelta(days=int(365.25 * years)),
                    "security_type": kind,
                    "offering_amt": offering,
                    "resource_id": "treasury_auctions_synthetic",
                }
            )
    pd.DataFrame(auction_rows).to_parquet(
        snapshot / "D_TREASURY_AUCTIONS.parquet", index=False
    )

    fomc_rows: list[dict[str, object]] = []
    cursor = 20
    event_number = 0
    while cursor + 20 < len(sessions):
        meeting = sessions[cursor]
        statement = sessions[cursor + 1]
        minutes = sessions[cursor + 16]
        fomc_rows.extend(
            [
                {"date": meeting, "document_kind": "meeting", "document_reference": f"Meeting {event_number}", "resource_id": "fomc_synthetic"},
                {"date": statement, "document_kind": "statement", "document_reference": f"statement-{event_number}", "resource_id": "fomc_synthetic"},
                {"date": meeting, "document_kind": "minutes", "document_reference": f"minutes-document-{event_number}", "resource_id": "fomc_synthetic"},
                {"date": minutes, "document_kind": "minutes_release", "document_reference": f"minutes-release-{event_number}", "resource_id": "fomc_synthetic"},
            ]
        )
        cursor += 36 + event_number % 7
        event_number += 1
    pd.DataFrame(fomc_rows).to_parquet(snapshot / "D_FOMC_PUBLIC.parquet", index=False)

    month_dates = pd.date_range("1997-01-01", "2010-10-01", freq="MS")
    tic_rows: list[dict[str, object]] = []
    for index, date in enumerate(month_dates):
        treasury = 25_000.0 + 15_000.0 * np.sin(index / 7.0)
        equity = 10_000.0 + 12_000.0 * np.cos(index / 8.0)
        tic_rows.extend(
            [
                {"date": date, "resource_id": "tic_treasury_sector", "total_net_purchases": treasury, "foreign_official": 8_000.0 + 4_000.0 * np.cos(index / 9.0), "other_foreigners": treasury - 8_000.0, "international_regional": 0.0},
                {"date": date, "resource_id": "tic_equity_sector", "total_net_purchases": equity, "foreign_official": 2_000.0 + 2_500.0 * np.sin(index / 10.0), "other_foreigners": equity - 2_000.0, "international_regional": 0.0},
            ]
        )
    pd.DataFrame(tic_rows).to_parquet(snapshot / "D_TIC.parquet", index=False)

    weather_dates = pd.date_range("1997-01-01", "2010-12-29", freq="D")
    w = np.arange(len(weather_dates), dtype=float)
    temperature = 55.0 + 22.0 * np.sin(2.0 * np.pi * w / 365.25)
    pd.DataFrame(
        {
            "date": weather_dates,
            "TEMP": temperature,
            "DEWP": temperature - 12.0 + 2.0 * np.sin(w / 17.0),
            "SLP": 1013.0 + 8.0 * np.cos(w / 19.0),
            "VISIB": 9.0 + 1.5 * np.sin(w / 13.0),
            "WDSP": 7.0 + 3.0 * np.cos(w / 17.0),
            "MXSPD": 13.0 + 4.0 * np.cos(w / 17.0),
            "GUST": 18.0 + 6.0 * np.cos(w / 17.0),
            "MAX": temperature + 9.0,
            "MIN": temperature - 9.0,
            "PRCP": np.maximum(0.0, 0.3 * np.sin(w / 11.0)),
            "SNDP": np.maximum(0.0, 3.0 * np.cos(2.0 * np.pi * w / 365.25)),
            "FRSHTT": np.where(np.sin(w / 23.0) > 0.8, 110000, 0),
            "resource_id": "noaa_ny_laguardia_gsod_synthetic",
        }
    ).to_parquet(snapshot / "D_NOAA_NY.parquet", index=False)
    return snapshot


def test_public_context_smoke_builds_f231_f240_train_only_artifacts(
    tmp_path: Path,
) -> None:
    snapshot = _write_snapshot(tmp_path)

    report = _api().build_public_context_feature_smoke(
        snapshot, output_dir=tmp_path / "out"
    )

    assert report["ready"] is True
    assert report["executable_lanes"] == [f"F{i:03d}" for i in range(231, 241)]
    assert report["executable_lane_count"] == 10
    assert report["row_release_causality_valid"] is True
    assert report["sec_source_used"] is False
    assert report["sunshine_or_cloud_claimed"] is False
    assert report["noaa_release_policy"] == "observation_plus_two_calendar_days"
    assert report["tic_historical_revision_pit_exact"] is False
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert report["empty_lanes"] == []
    assert report["exact_duplicate_groups"] == []
    assert report["near_duplicate_pairs"] == []
    assert len(report["coverage"]) == 10
    assert set(report["artifacts"]) == {f"F{i:03d}" for i in range(231, 241)}
    assert (tmp_path / "out" / "features" / "F231.parquet").is_file()
    assert (tmp_path / "out" / "features" / "F240.parquet").is_file()


def test_public_context_smoke_requires_physical_train_partition(tmp_path: Path) -> None:
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(
        _api().PublicContextFeatureSmokeError,
        match="TRAIN_PARTITION_REQUIRED",
    ):
        _api().build_public_context_feature_smoke(
            wrong, output_dir=tmp_path / "out"
        )


def test_public_context_smoke_rejects_fake_sunshine_field(tmp_path: Path) -> None:
    snapshot = _write_snapshot(tmp_path)
    weather_path = snapshot / "D_NOAA_NY.parquet"
    weather = pd.read_parquet(weather_path)
    weather["SUNSHINE"] = 8.0
    weather.to_parquet(weather_path, index=False)

    with pytest.raises(Exception, match="UNFROZEN_NOAA_SUN_CLOUD_FIELD"):
        _api().build_public_context_feature_smoke(
            snapshot, output_dir=tmp_path / "out"
        )


def test_public_context_smoke_cli_accepts_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = importlib.import_module(
        "scripts.run_sp500_megarun_public_context_feature_smoke_f231"
    )
    monkeypatch.setattr(cli, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(
        cli,
        "build_public_context_feature_smoke",
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
