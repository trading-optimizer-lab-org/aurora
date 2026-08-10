from __future__ import annotations

import importlib
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


_Z1_SERIES = (
    "LM153064105.Q",
    "FL154090005.Q",
    "FL154190005.Q",
    "FL153020005.Q",
    "FL153030005.Q",
    "FL153034005.Q",
    "FL104090005.Q",
    "FL104190005.Q",
    "FL103020000.Q",
    "FL103030003.Q",
    "FL103034000.Q",
    "FL104122005.Q",
    "FA103164105.Q",
    "LM654090000.Q",
    "LM653064100.Q",
    "FA654090000.Q",
    "LM564090005.Q",
    "LM563064100.Q",
    "FA564090005.Q",
    "FL634090005.Q",
    "FA634090005.Q",
    "FL633061105.Q",
    "FL633069175.Q",
    "FL664090005.Q",
    "FL664190005.Q",
    "FL662051003.Q",
    "FL662151003.Q",
    "FA263061105.Q",
    "FA263063005.Q",
    "FA263064105.Q",
    "FA263064203.Q",
)


def _api():
    try:
        return importlib.import_module(
            "aurora.infra.sp500_megarun.financial_accounts_feature_smoke"
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - removed by implementation
        pytest.fail(f"financial-accounts feature smoke is missing: {exc}")


def _write_snapshot(root: Path) -> Path:
    snapshot = root / "train_snapshot_1993_2010"
    snapshot.mkdir()
    sessions = pd.bdate_range("1996-01-02", "2010-12-31")
    phase = np.arange(len(sessions), dtype=float)
    close = 100.0 * np.exp(np.cumsum(0.0002 + 0.004 * np.sin(phase / 37.0)))
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
            "volume": 1_000_000.0 + 100_000.0 * np.sin(phase / 19.0),
        }
    ).to_parquet(snapshot / "D_SPY.parquet", index=False)

    quarters = pd.date_range("1994-12-31", "2009-09-30", freq="QE")
    q = np.arange(len(quarters), dtype=float)
    flow_series = {
        "FA103164105.Q",
        "FA654090000.Q",
        "FA564090005.Q",
        "FA634090005.Q",
        "FA263061105.Q",
        "FA263063005.Q",
        "FA263064105.Q",
        "FA263064203.Q",
    }
    z1_rows: list[dict[str, object]] = []
    for offset, series_id in enumerate(_Z1_SERIES):
        if series_id in flow_series:
            values = (
                80.0 * np.sin((q + offset) / (2.4 + 0.07 * offset))
                + 35.0 * np.cos((q + 2.0 * offset) / (3.7 + 0.03 * offset))
                + 0.4 * offset
            )
        else:
            values = (
                900.0
                + 140.0 * offset
                + (8.0 + 0.6 * offset) * q
                + (60.0 + offset) * np.sin((q + offset) / (3.1 + 0.11 * offset))
            )
        z1_rows.extend(
            {"date": date, "series_id": series_id, "value": value}
            for date, value in zip(quarters, values, strict=True)
        )
    pd.DataFrame(z1_rows).to_parquet(snapshot / "D_Z1.parquet", index=False)

    months = pd.date_range("1996-01-31", "2010-10-31", freq="ME")
    m = np.arange(len(months), dtype=float)
    tic_rows: list[dict[str, object]] = []
    for offset, resource_id in enumerate(
        ("tic_treasury_sector", "tic_equity_sector")
    ):
        total = 45.0 * np.sin((m + 5.0 * offset) / (5.0 + offset))
        total += 22.0 * np.cos((m + offset) / (9.0 + offset))
        official = 12.0 * np.sin((m + 3.0 * offset) / (7.0 + offset))
        tic_rows.extend(
            {
                "date": date,
                "resource_id": resource_id,
                "total_net_purchases": total_value,
                "foreign_official": official_value,
            }
            for date, total_value, official_value in zip(
                months, total, official, strict=True
            )
        )
    pd.DataFrame(tic_rows).to_parquet(snapshot / "D_TIC.parquet", index=False)
    return snapshot


def test_financial_accounts_smoke_builds_f201_f210_train_only_artifacts(
    tmp_path: Path,
) -> None:
    snapshot = _write_snapshot(tmp_path)

    report = _api().build_financial_accounts_feature_smoke(
        snapshot, output_dir=tmp_path / "out"
    )

    assert report["ready"] is True
    assert report["executable_lanes"] == [f"F{i:03d}" for i in range(201, 211)]
    assert report["executable_lane_count"] == 10
    assert report["row_release_causality_valid"] is True
    assert report["z1_release_policy"] == "observation_plus_13_month_revision_guard"
    assert report["z1_historical_revision_pit_exact"] is False
    assert report["tic_release_policy"] == "second_following_month_tenth_spy_session"
    assert report["validation_opened"] is False
    assert report["locked_opened"] is False
    assert report["maximum_feature_date"] == "2010-12-31"
    assert report["empty_lanes"] == []
    parameter_audit = report["parameter_choice_audit"]
    assert parameter_audit["ready"] is True
    assert parameter_audit["expected_choice_probe_count"] == 179
    assert parameter_audit["choice_probe_count"] == 179
    assert parameter_audit["failed_probes"] == []
    assert parameter_audit["inactive_choice_groups"] == []
    assert report["exact_duplicate_groups"] == []
    assert report["near_duplicate_pairs"] == []
    assert len(report["coverage"]) == 10
    assert set(report["artifacts"]) == {f"F{i:03d}" for i in range(201, 211)}
    assert (tmp_path / "out" / "features" / "F201.parquet").is_file()
    assert (tmp_path / "out" / "features" / "F210.parquet").is_file()


def test_financial_accounts_smoke_requires_physical_train_partition(
    tmp_path: Path,
) -> None:
    wrong = tmp_path / "validation_snapshot_2011_2020"
    wrong.mkdir()

    with pytest.raises(
        _api().FinancialAccountsFeatureSmokeError, match="TRAIN_PARTITION_REQUIRED"
    ):
        _api().build_financial_accounts_feature_smoke(
            wrong, output_dir=tmp_path / "out"
        )


def test_financial_accounts_smoke_fails_closed_on_missing_z1_series(
    tmp_path: Path,
) -> None:
    snapshot = _write_snapshot(tmp_path)
    z1_path = snapshot / "D_Z1.parquet"
    z1 = pd.read_parquet(z1_path)
    z1.loc[z1["series_id"].ne("FL154190005.Q")].to_parquet(z1_path, index=False)

    with pytest.raises(Exception, match="household_liabilities"):
        _api().build_financial_accounts_feature_smoke(
            snapshot, output_dir=tmp_path / "out"
        )


def test_financial_accounts_smoke_cli_accepts_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli = importlib.import_module(
        "scripts.run_sp500_megarun_financial_accounts_feature_smoke_f201"
    )
    monkeypatch.setattr(cli, "require_github_only_execution", lambda _: None)
    monkeypatch.setattr(
        cli,
        "build_financial_accounts_feature_smoke",
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
    ("lane_id", "parameter", "configuration", "expected"),
    [
        ("F201", "window", {"statistic": "household_equity_share"}, {"statistic": "risk_appetite"}),
        ("F201", "change_lag", {"statistic": "household_equity_share"}, {"statistic": "equity_share_change"}),
        ("F202", "window", {"statistic": "household_leverage"}, {"statistic": "household_balance_composite"}),
        ("F204", "window", {"statistic": "corporate_net_issuance"}, {"statistic": "issuance_pressure"}),
        ("F204", "change_lag", {"statistic": "corporate_net_issuance"}, {"statistic": "issuance_change"}),
        ("F205", "window", {"normalization": "raw"}, {"normalization": "rolling_zscore"}),
        ("F208", "window", {"statistic": "broker_leverage"}, {"statistic": "dealer_capacity"}),
        ("F209", "window", {"statistic": "tic_treasury_flow"}, {"statistic": "combined_foreign_flow"}),
        ("F210", "window", {"statistic": "household_to_fund"}, {"statistic": "interconnection_composite"}),
    ],
)
def test_financial_accounts_parameter_witnesses_activate_conditional_choices(
    lane_id: str,
    parameter: str,
    configuration: dict[str, object],
    expected: dict[str, object],
) -> None:
    repaired = _api()._repair_financial_accounts_configuration(
        lane_id,
        parameter,
        configuration.copy(),
    )

    for name, value in expected.items():
        assert repaired[name] == value


def test_financial_accounts_physical_smoke_has_an_isolated_dispatch_scope() -> None:
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "sp500-megarun-macro-feature-smoke-f032.yml"
    ).read_text(encoding="utf-8")

    assert "- f201_f210" in workflow
    assert "smoke_f201_f210:" in workflow
    assert "inputs.scope == 'f201_f210'" in workflow
    assert "timeout-minutes: 15" in workflow
