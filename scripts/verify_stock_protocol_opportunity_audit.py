"""Enforce the final immutable opportunity-audit artifact contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


EXPECTED_COUNTS = {
    "walk_forward_is": 2947,
    "diagnostic_reused_holdout": 2043,
    "opened_locked_diagnostic": 2186,
}
DIAGNOSTIC_ROLE = "diagnostic_reanalysis_of_opened_locked_period"


def verify(root: Path) -> None:
    summary = json.loads((root / "audit_summary.json").read_text())
    manifest = json.loads((root / "final_artifact_manifest.json").read_text())
    opportunities = pd.read_csv(root / "all_individual_opportunities.csv")
    reconciliation = pd.read_csv(root / "opportunity_reconciliation.csv")
    assert summary["opportunities"] == 7176
    assert summary["period_counts"] == EXPECTED_COUNTS
    assert opportunities.groupby("period").size().to_dict() == EXPECTED_COUNTS
    assert opportunities["opportunity_id"].nunique() == 7176
    assert summary["financed"] + summary["not_financed"] == 7176
    assert reconciliation["reconciled"].all()
    assert (
        reconciliation["opportunities"]
        == reconciliation["funded"] + reconciliation["unfunded"]
    ).all()
    assert int(reconciliation["opportunities"].sum()) == 7176
    assert summary["opened_locked_analysis_role"] == DIAGNOSTIC_ROLE
    assert summary["new_oos_claimed"] is False
    assert summary["optimization_performed"] is False
    source_audit = json.loads((root / "input_artifact_audit.json").read_text())
    assert len(source_audit["verified_artifacts"]) == 35
    assert len(
        [row for row in source_audit["verified_artifacts"] if row["role"] == "locked_data_shard"]
    ) == 32
    assert all(
        not row["expired"] and row["digest"].startswith("sha256:")
        for row in source_audit["verified_artifacts"]
    )
    assert pd.to_datetime(opportunities["exit_date"]).max() <= pd.Timestamp("2026-07-17")
    distribution = pd.read_csv(root / "sequence_permutation_distribution.csv")
    assert distribution.groupby("period").size().to_dict() == {
        period: 1000 for period in EXPECTED_COUNTS
    }
    fixed = pd.read_csv(root / "fixed_position_portfolio_results.csv")
    assert set(fixed["variant"]) == {"Original", "P10", "P20", "P30", "P50", "P100"}
    assert fixed.groupby("period")["variant"].nunique().to_dict() == {
        period: 6 for period in EXPECTED_COUNTS
    }
    fx_fixed = pd.read_csv(root / "fx_adjusted_portfolio_results.csv")
    assert set(fx_fixed["currency_basis"]) == {"USD"}
    assert fx_fixed.groupby("period")["variant"].nunique().to_dict() == {
        period: 5 for period in EXPECTED_COUNTS
    }
    costs = pd.read_csv(root / "cost_liquidity_capacity_results.csv")
    assert set(costs["currency_basis"]) == {"USD"}
    assert set(costs["cost_bps_per_side"]) == {0, 5, 10, 25, 50, 100, 200}
    assert costs.groupby(["period", "variant"])["cost_bps_per_side"].nunique().eq(7).all()
    benchmarks = pd.read_csv(root / "benchmark_comparison_by_frequency.csv")
    assert {"SPY", "VT", "ACWI"} <= set(benchmarks["benchmark"])
    assert {"weekly", "monthly"} <= set(
        benchmarks.loc[benchmarks["status"].eq("evaluated"), "frequency"]
    )
    for path in root.rglob("*.csv"):
        frame = pd.read_csv(path)
        if {"period", "analysis_role"} <= set(frame.columns):
            opened = frame["period"].astype(str).eq("opened_locked_diagnostic")
            if opened.any():
                assert frame.loc[opened, "analysis_role"].astype(str).eq(DIAGNOSTIC_ROLE).all(), path
        for date_column in (
            "date",
            "entry_date",
            "exit_date",
            "comparison_end",
            "fx_date",
            "fx_entry_date",
            "fx_exit_date",
        ):
            if date_column in frame.columns:
                dates = pd.to_datetime(frame[date_column], errors="coerce").dropna()
                assert dates.empty or dates.max() <= pd.Timestamp("2026-07-17"), (
                    path,
                    date_column,
                )
    report = (root / "final_opportunity_and_portfolio_audit.md").read_text(encoding="utf-8")
    assert all(f"{number}." in report for number in range(1, 21))
    required = {
        "audit_summary.json", "frozen_oos_strategy_manifest.json",
        "frozen_strategy_exact.json", "frozen_component_signals.csv",
        "frozen_effective_unique_signals.csv", "individual_opportunity_statistics.csv",
        "individual_opportunity_bootstrap.parquet", "all_individual_opportunities.csv",
        "individual_opportunities_yearly.csv", "opportunity_reconciliation.csv",
        "opportunity_provenance_gaps.csv", "sequence_dependence_results.csv",
        "sequence_permutation_distribution.csv", "fixed_position_portfolio_results.csv",
        "fixed_position_portfolio_yearly.csv", "symbol_exchange_currency_map.csv",
        "historical_fx_audit.csv", "fx_adjusted_opportunities.csv",
        "fx_adjusted_portfolio_results.csv", "calendar_frequency_metrics.csv",
        "benchmark_comparison_by_frequency.csv", "benchmark_regressions.csv",
        "cost_liquidity_capacity_results.csv", "capacity_violations.csv",
        "return_concentration_analysis.csv", "leave_one_group_out_results.csv",
        "survivorship_bias_audit.md", "final_opportunity_and_portfolio_audit.md",
        "final_artifact_manifest.json", "input_artifact_audit.json",
        "separate_verdicts.json", "survivorship_coverage.csv",
    }
    assert required <= {path.name for path in root.iterdir()}
    for name, metadata in manifest["files"].items():
        path = root / name
        assert path.stat().st_size == metadata["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == metadata["sha256"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    verify(parser.parse_args().root)


if __name__ == "__main__":
    main()
