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
            "aurora.infra.sp500_megarun.volatility_positioning_feature_smoke"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"volatility-positioning feature smoke is missing: {exc}")


def _write_snapshot(root: Path) -> Path:
    snapshot = root / "train_snapshot_1993_2010"
    snapshot.mkdir()
    sessions = pd.bdate_range("2000-01-03", "2010-12-31")
    phase = np.arange(len(sessions), dtype=float)
    close = 100.0 * np.exp(
        np.cumsum(0.0002 + 0.006 * np.sin(phase / 31.0) + 0.002 * np.cos(phase / 9.0))
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

    vix = 18.0 + 5.0 * np.sin(phase / 37.0) + 2.0 * np.cos(phase / 13.0)
    vxo = vix + 0.8 * np.sin(phase / 19.0)
    vol_rows = pd.concat(
        (
            pd.DataFrame(
                {
                    "date": sessions,
                    "resource_id": "vix_from_2003",
                    "source_dataset": "D_VIX",
                    "CLOSE": vix,
                }
            ),
            pd.DataFrame(
                {
                    "date": sessions,
                    "resource_id": "vxo_1986_2003",
                    "source_dataset": "D_VXO",
                    "4": vxo,
                }
            ),
        ),
        ignore_index=True,
    )
    vol_rows.to_parquet(snapshot / "D_CBOE_VOL.parquet", index=False)

    reports = pd.date_range("2000-01-04", "2010-12-28", freq="W-TUE")
    w = np.arange(len(reports), dtype=float)
    cftc_rows: list[dict[str, object]] = []
    for index, date in enumerate(reports):
        for market_offset, market in enumerate(
            (
                "E-MINI S&P 500 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE",
                "CRUDE OIL - NEW YORK MERCANTILE EXCHANGE",
            )
        ):
            for combined in (False, True):
                if combined and market_offset:
                    continue
                oi = 900_000.0 + 2_000.0 * index + 40_000.0 * np.sin(
                    (index + market_offset) / 9.0
                )
                if combined:
                    oi *= 1.16
                noncommercial_net = 0.10 * np.sin(
                    (index + 2.0 * market_offset + combined) / 11.0
                )
                commercial_net = -0.08 * np.sin(
                    (index + market_offset + 2.0 * combined) / 12.0
                )
                noncommercial_short = 0.28 * oi
                noncommercial_long = noncommercial_short + noncommercial_net * oi
                commercial_short = 0.31 * oi
                commercial_long = commercial_short + commercial_net * oi
                spreading = (0.08 + 0.02 * np.sin(index / 8.0)) * oi
                cftc_rows.append(
                    {
                        "date": date,
                        "resource_id": (
                            "legacy_futures_options_late:2010"
                            if combined
                            else "legacy_futures_only:2010"
                        ),
                        "source_dataset": "D_CFTC",
                        "Market and Exchange Names": market,
                        "Open Interest (All)": oi,
                        "Noncommercial Positions-Long (All)": noncommercial_long,
                        "Noncommercial Positions-Short (All)": noncommercial_short,
                        "Noncommercial Positions-Spreading (All)": spreading,
                        "Commercial Positions-Long (All)": commercial_long,
                        "Commercial Positions-Short (All)": commercial_short,
                        "Total Reportable Positions-Short (All)": 0.58 * oi,
                        "Traders-Total (All)": 80.0
                        + 8.0 * np.sin((index + combined) / 13.0),
                        "Concentration-Net LT =4 TDR-Long (All)": 24.0
                        + 3.0 * np.sin(index / 15.0),
                        "Concentration-Net LT =4 TDR-Short (All)": 27.0
                        + 2.0 * np.cos(index / 14.0),
                        "Concentration-Net LT =8 TDR-Long (All)": 39.0
                        + 4.0 * np.sin(index / 16.0),
                        "Concentration-Net LT =8 TDR-Short (All)": 44.0
                        + 3.0 * np.cos(index / 17.0),
                    }
                )
    cftc = pd.DataFrame(cftc_rows)
    cftc.to_parquet(snapshot / "D_CFTC_LEGACY.parquet", index=False)
    cftc.to_parquet(snapshot / "D_CBOE_PCR.parquet", index=False)
    return snapshot


def test_volatility_positioning_smoke_builds_f211_f220_train_only_artifacts(
    tmp_path: Path,
) -> None:
    snapshot = _write_snapshot(tmp_path)

    report = _api().build_volatility_positioning_feature_smoke(
        snapshot, output_dir=tmp_path / "out"
    )

    assert report["ready"] is True
    assert report["executable_lanes"] == [f"F{i:03d}" for i in range(211, 221)]
    assert report["executable_lane_count"] == 10
    assert report["row_release_causality_valid"] is True
    assert report["vix_bridge_policy"] == "VXO_before_2003_09_22_then_modern_VIX"
    assert report["cftc_release_policy"] == "tuesday_observation_after_friday_release"
    assert report["put_call_source"] == "preregistered_cftc_cross_market_fallback"
    assert report["put_call_ratio_claimed"] is False
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert report["empty_lanes"] == []
    assert report["exact_duplicate_groups"] == []
    assert report["near_duplicate_pairs"] == []
    assert len(report["coverage"]) == 10
    assert set(report["artifacts"]) == {f"F{i:03d}" for i in range(211, 221)}
    assert (tmp_path / "out" / "features" / "F211.parquet").is_file()
    assert (tmp_path / "out" / "features" / "F220.parquet").is_file()


def test_volatility_positioning_smoke_requires_physical_train_partition(
    tmp_path: Path,
) -> None:
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(
        _api().VolatilityPositioningFeatureSmokeError,
        match="TRAIN_PARTITION_REQUIRED",
    ):
        _api().build_volatility_positioning_feature_smoke(
            wrong, output_dir=tmp_path / "out"
        )


def test_volatility_positioning_smoke_rejects_fake_put_call_claim(
    tmp_path: Path,
) -> None:
    snapshot = _write_snapshot(tmp_path)
    pcr_path = snapshot / "D_CBOE_PCR.parquet"
    pcr = pd.read_parquet(pcr_path)
    pcr["source_dataset"] = "D_CBOE"
    pcr.to_parquet(pcr_path, index=False)

    with pytest.raises(Exception, match="PCR_FALLBACK_PROVENANCE_MISSING"):
        _api().build_volatility_positioning_feature_smoke(
            snapshot, output_dir=tmp_path / "out"
        )


def test_volatility_positioning_smoke_cli_accepts_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = importlib.import_module(
        "scripts.run_sp500_megarun_volatility_positioning_feature_smoke_f211"
    )
    monkeypatch.setattr(cli, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(
        cli,
        "build_volatility_positioning_feature_smoke",
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
