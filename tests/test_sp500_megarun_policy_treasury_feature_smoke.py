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
            "aurora.infra.sp500_megarun.policy_treasury_feature_smoke"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"policy-Treasury feature smoke is missing: {exc}")


def _write_snapshot(root: Path) -> Path:
    snapshot = root / "train_snapshot_1993_2010"
    snapshot.mkdir()
    sessions = pd.bdate_range("1993-01-22", "2010-12-31")
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

    fomc_rows: list[dict[str, object]] = []
    cursor = 20
    event_number = 0
    while cursor + 20 < len(sessions):
        meeting = sessions[cursor]
        statement = sessions[cursor + 1]
        minutes = sessions[cursor + 14 + event_number % 6]
        fomc_rows.extend(
            [
                {
                    "date": meeting,
                    "document_kind": "meeting",
                    "document_reference": f"Meeting {event_number}",
                    "resource_id": "fomc_historical_synthetic",
                },
                {
                    "date": statement,
                    "document_kind": "statement",
                    "document_reference": f"statement-{event_number}",
                    "resource_id": "fomc_historical_synthetic",
                },
                {
                    "date": minutes,
                    "document_kind": "minutes_release",
                    "document_reference": f"minutes-{event_number}",
                    "resource_id": "fomc_historical_synthetic",
                },
            ]
        )
        cursor += 36 + event_number % 7
        event_number += 1
    pd.DataFrame(fomc_rows).to_parquet(snapshot / "D_FOMC_PUBLIC.parquet", index=False)

    rate_dates = sessions[::5]
    rate_phase = np.arange(len(rate_dates), dtype=float)
    pd.DataFrame(
        {
            "date": rate_dates,
            "series_id": "RIFSPFF_N.B",
            "value": 4.0 + 1.0 * np.sin(rate_phase / 19.0),
            "resource_id": "federal_reserve_h15_all",
        }
    ).to_parquet(snapshot / "D_FED_H15_H10.parquet", index=False)

    auction_dates = sessions[10::10]
    auction_rows: list[dict[str, object]] = []
    for index, date in enumerate(auction_dates):
        for kind, years, weight in (("Bill", 0.5, 0.45), ("Note", 5.0, 0.55)):
            offering = (20e9 + 4e9 * np.sin(index / 9.0) + 30e6 * index) * weight
            accepted = offering * (1.01 + 0.01 * np.sin(index / 7.0))
            auction_rows.append(
                {
                    "date": date,
                    "offering_amt": offering,
                    "total_accepted": accepted,
                    "total_tendered": accepted * (2.4 + 0.3 * np.cos(index / 11.0)),
                    "high_yield": str(4.0 + 1.1 * np.sin(index / 17.0)) if kind == "Note" else "null",
                    "high_investment_rate": str(3.8 + 1.0 * np.sin(index / 17.0)) if kind == "Bill" else "null",
                    "high_discnt_rate": str(3.7 + 1.0 * np.sin(index / 17.0)) if kind == "Bill" else "null",
                    "issue_date": date,
                    "maturity_date": date + pd.Timedelta(days=int(365.25 * years)),
                    "security_type": kind,
                    "reopening": "Yes" if (index + (kind == "Note")) % 4 == 0 else "No",
                    "resource_id": "treasury_auctions_synthetic",
                }
            )
    pd.DataFrame(auction_rows).to_parquet(
        snapshot / "D_TREASURY_AUCTIONS.parquet", index=False
    )

    debt_dates = sessions[2::3]
    debt_phase = np.arange(len(debt_dates), dtype=float)
    total_debt = 5e12 * np.exp(0.0005 * debt_phase + 0.002 * np.sin(debt_phase / 23.0))
    public_share = 0.62 + 0.03 * np.sin(debt_phase / 41.0)
    pd.DataFrame(
        {
            "date": debt_dates,
            "tot_pub_debt_out_amt": total_debt,
            "debt_held_public_amt": total_debt * public_share,
            "intragov_hold_amt": total_debt * (1.0 - public_share),
            "resource_id": "debt_to_penny_synthetic",
        }
    ).to_parquet(snapshot / "D_TREASURY_FISCAL.parquet", index=False)

    month_dates = pd.date_range("1993-01-01", "2010-10-01", freq="MS")
    tic_rows: list[dict[str, object]] = []
    for index, date in enumerate(month_dates):
        treasury = 25_000.0 + 15_000.0 * np.sin(index / 7.0)
        equity = 10_000.0 + 12_000.0 * np.cos(index / 8.0)
        tic_rows.extend(
            [
                {
                    "date": date,
                    "resource_id": "tic_treasury_sector",
                    "total_net_purchases": treasury,
                    "foreign_official": 8_000.0 + 4_000.0 * np.cos(index / 9.0),
                    "other_foreigners": treasury - 8_000.0,
                    "international_regional": 0.0,
                },
                {
                    "date": date,
                    "resource_id": "tic_equity_sector",
                    "total_net_purchases": equity,
                    "foreign_official": 2_000.0 + 2_500.0 * np.sin(index / 10.0),
                    "other_foreigners": equity - 2_000.0,
                    "international_regional": 0.0,
                },
            ]
        )
    pd.DataFrame(tic_rows).to_parquet(snapshot / "D_TIC.parquet", index=False)

    weekly = pd.date_range("1993-01-27", "2010-12-15", freq="W-WED")
    monetary_rows: list[dict[str, object]] = []
    for index, date in enumerate(weekly):
        for series_id, level, drift in (
            ("RESMO14A_N.WW", 500_000.0, 0.0005),
            ("RESTR14A_N.WW", 50_000.0, 0.0007),
            ("M2.WM", 4_000_000.0, 0.0004),
        ):
            monetary_rows.append(
                {
                    "date": date,
                    "series_id": series_id,
                    "value": level * np.exp(drift * index + 0.003 * np.sin(index / 13.0)),
                    "resource_id": "federal_reserve_synthetic",
                    "source_dataset": "D_MACRO_PIT",
                }
            )
    pd.DataFrame(monetary_rows).to_parquet(
        snapshot / "D_FED_H3_H6_H8_G19_CP.parquet", index=False
    )
    return snapshot


def test_policy_treasury_smoke_builds_f221_f230_train_only_artifacts(
    tmp_path: Path,
) -> None:
    snapshot = _write_snapshot(tmp_path)

    report = _api().build_policy_treasury_feature_smoke(
        snapshot, output_dir=tmp_path / "out"
    )

    assert report["ready"] is True
    assert report["executable_lanes"] == [f"F{i:03d}" for i in range(221, 231)]
    assert report["executable_lane_count"] == 10
    assert report["row_release_causality_valid"] is True
    assert report["fomc_text_available"] is False
    assert report["fomc_tone_claimed"] is False
    assert report["treasury_net_cash_claimed"] is False
    assert report["tic_historical_revision_pit_exact"] is False
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert report["empty_lanes"] == []
    assert report["exact_duplicate_groups"] == []
    assert report["near_duplicate_pairs"] == []
    assert report["full_yearly_coverage"] is True
    assert len(report["coverage"]) == 10
    parameter_audit = report["parameter_choice_audit"]
    assert parameter_audit["ready"] is True
    assert parameter_audit["expected_choice_probe_count"] == 198
    assert parameter_audit["choice_probe_count"] == 198
    assert parameter_audit["failed_probes"] == []
    assert parameter_audit["inactive_choice_groups"] == []
    assert all(
        min(item["yearly_non_null_fraction"].values()) == 1.0
        for item in report["coverage"]
    )
    assert set(report["artifacts"]) == {f"F{i:03d}" for i in range(221, 231)}
    assert (tmp_path / "out" / "features" / "F221.parquet").is_file()
    assert (tmp_path / "out" / "features" / "F230.parquet").is_file()


def test_policy_treasury_smoke_requires_physical_train_partition(tmp_path: Path) -> None:
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(
        _api().PolicyTreasuryFeatureSmokeError,
        match="TRAIN_PARTITION_REQUIRED",
    ):
        _api().build_policy_treasury_feature_smoke(
            wrong, output_dir=tmp_path / "out"
        )


def test_policy_treasury_smoke_rejects_a_tone_claim_source(tmp_path: Path) -> None:
    snapshot = _write_snapshot(tmp_path)
    fomc_path = snapshot / "D_FOMC_PUBLIC.parquet"
    fomc = pd.read_parquet(fomc_path)
    fomc["tone_score"] = 0.5
    fomc.to_parquet(fomc_path, index=False)

    with pytest.raises(Exception, match="UNFROZEN_FOMC_TEXT_DERIVATIVE"):
        _api().build_policy_treasury_feature_smoke(
            snapshot, output_dir=tmp_path / "out"
        )


def test_policy_treasury_smoke_cli_accepts_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = importlib.import_module(
        "scripts.run_sp500_megarun_policy_treasury_feature_smoke_f221"
    )
    monkeypatch.setattr(cli, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(
        cli,
        "build_policy_treasury_feature_smoke",
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


@pytest.mark.parametrize(
    ("lane_id", "parameter", "default_overrides", "active_overrides"),
    [
        ("F221", "window", {"statistic": "decision_rate_change"}, {"normalization": "rolling_zscore"}),
        ("F221", "change_lag", {"statistic": "days_since_decision"}, {"statistic": "decision_rate_change"}),
        ("F222", "window", {"statistic": "statement_gap"}, {"statistic": "statement_gap_zscore"}),
        ("F222", "change_lag", {"statistic": "statement_gap"}, {"statistic": "statement_gap_change"}),
        ("F223", "window", {"statistic": "publication_lag"}, {"statistic": "publication_lag_zscore"}),
        ("F223", "change_lag", {"statistic": "publication_lag"}, {"statistic": "publication_lag_change"}),
        ("F224", "window", {"statistic": "cadence_gap"}, {"statistic": "joint_irregularity"}),
        ("F225", "change_lag", {"statistic": "offering_amount"}, {"statistic": "offer_growth"}),
        ("F226", "window", {"statistic": "bid_to_cover"}, {"statistic": "demand_yield_balance"}),
        ("F226", "change_lag", {"statistic": "bid_to_cover"}, {"statistic": "yield_change"}),
        ("F227", "window", {"statistic": "weighted_maturity"}, {"statistic": "refinancing_pressure"}),
        ("F228", "window", {"statistic": "total_debt"}, {"statistic": "debt_growth_zscore"}),
        ("F228", "change_lag", {"statistic": "total_debt"}, {"statistic": "debt_growth"}),
        ("F229", "window", {"statistic": "combined_net_purchases"}, {"normalization": "rolling_zscore"}),
    ],
)
def test_policy_treasury_parameter_repair_activates_conditional_choice(
    lane_id: str,
    parameter: str,
    default_overrides: dict[str, object],
    active_overrides: dict[str, object],
) -> None:
    api = _api()
    base = {
        "statistic": "decision_rate_change",
        "window": 5,
        "change_lag": 1,
        "normalization": "raw",
        "direction": "continuation",
        **default_overrides,
    }

    repaired = api._repair_policy_treasury_configuration(
        lane_id,
        parameter,
        dict(base),
    )

    for key, value in active_overrides.items():
        assert repaired[key] == value


def test_policy_treasury_workflow_has_an_isolated_fail_closed_scope() -> None:
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "sp500-megarun-macro-feature-smoke-f032.yml"
    ).read_text(encoding="utf-8")

    assert "- f221_f230" in workflow
    assert "smoke_f221_f230:" in workflow
    assert "inputs.scope == 'f221_f230'" in workflow
    assert "parameter_choice_audit_F221_F230.json" in workflow
