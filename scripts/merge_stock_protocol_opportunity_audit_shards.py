"""Merge the three immutable opportunity-audit period shards."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil

import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.research.stock_protocol.opportunity_audit import (
    AUDIT_ROLE,
    CUTOFF,
    event_study_statistics,
    label_analysis_role,
    write_artifact_manifest,
)
from scripts.run_stock_protocol_opportunity_audit import (
    EXPECTED_COUNTS,
    _assert_reconciliation,
    _final_report,
    _json,
    _survivorship_report,
    _verdicts,
)


TABLES = (
    "fixed_position_portfolio_results.csv",
    "fixed_position_portfolio_yearly.csv",
    "cost_liquidity_capacity_results.csv",
    "capacity_violations.csv",
    "sequence_dependence_results.csv",
    "sequence_permutation_distribution.csv",
    "calendar_frequency_metrics.csv",
    "benchmark_comparison_by_frequency.csv",
    "benchmark_regressions.csv",
    "fx_adjusted_portfolio_results.csv",
    "return_concentration_analysis.csv",
    "leave_one_group_out_results.csv",
    "survivorship_coverage.csv",
)

COMMON_FILES = (
    "frozen_oos_strategy_manifest.json",
    "frozen_strategy_exact.json",
    "frozen_component_signals.csv",
    "frozen_effective_unique_signals.csv",
    "symbol_exchange_currency_map.csv",
    "historical_fx_audit.csv",
    "input_artifact_audit.json",
)


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _shard_roots(root: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for summary_path in root.rglob("audit_summary.json"):
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        period = summary.get("shard_period")
        if period in EXPECTED_COUNTS:
            if period in found:
                raise ValueError(f"duplicate audit shard: {period}")
            found[str(period)] = summary_path.parent
    if set(found) != set(EXPECTED_COUNTS):
        raise ValueError(f"missing audit shards: {sorted(set(EXPECTED_COUNTS) - set(found))}")
    return found


def _concat(shards: dict[str, Path], name: str) -> pd.DataFrame:
    frames = [_read_csv(shards[period] / name) for period in EXPECTED_COUNTS]
    frames = [frame for frame in frames if not frame.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _observed_bucket_date(
    label: object,
    frequency: str,
    curve_dates: pd.DatetimeIndex,
) -> pd.Timestamp:
    timestamp = pd.Timestamp(label).normalize()
    aliases = {"weekly": "W-FRI", "monthly": "M", "quarterly": "Q"}
    if frequency == "daily":
        candidates = curve_dates[curve_dates <= timestamp]
    else:
        alias = aliases[frequency]
        candidates = curve_dates[curve_dates.to_period(alias) == timestamp.to_period(alias)]
    if len(candidates) == 0:
        raise ValueError(f"no observed date for {frequency} bucket {timestamp.date()}")
    return pd.Timestamp(candidates.max()).normalize()


def _repair_benchmark_observation_dates(
    frame: pd.DataFrame,
    output: Path,
) -> pd.DataFrame:
    """Replace period-end labels with real dates and preserve total returns."""

    repaired = frame.copy()
    evaluated = repaired["status"].astype(str).eq("evaluated")
    for index, row in repaired.loc[evaluated].iterrows():
        curve_path = (
            output
            / "fixed_position_equity_curves"
            / f"{row['period']}_{row['variant']}.csv"
        )
        curve_dates = pd.DatetimeIndex(
            pd.to_datetime(pd.read_csv(curve_path, usecols=["date"])["date"], errors="raise")
        ).normalize()
        old_start = pd.Timestamp(row["comparison_start"])
        old_end = pd.Timestamp(row["comparison_end"])
        new_start = _observed_bucket_date(old_start, str(row["frequency"]), curve_dates)
        new_end = _observed_bucket_date(old_end, str(row["frequency"]), curve_dates)
        old_years = max((old_end - old_start).days / 365.2425, 1.0 / 365.2425)
        new_years = max((new_end - new_start).days / 365.2425, 1.0 / 365.2425)
        for column in ("strategy_cagr", "benchmark_cagr"):
            old_cagr = float(row[column])
            total = 0.0 if old_cagr <= -1.0 else (1.0 + old_cagr) ** old_years
            repaired.at[index, column] = -1.0 if total <= 0 else total ** (1.0 / new_years) - 1.0
        repaired.at[index, "cagr_difference"] = (
            float(repaired.at[index, "strategy_cagr"])
            - float(repaired.at[index, "benchmark_cagr"])
        )
        repaired.at[index, "comparison_start"] = new_start.date().isoformat()
        repaired.at[index, "comparison_end"] = new_end.date().isoformat()
    return repaired


def run(args: argparse.Namespace) -> None:
    require_github_actions_or_explicit_local_permission("stock protocol opportunity audit merge")
    shards = _shard_roots(args.shards_root)
    output = args.output_root
    output.mkdir(parents=True, exist_ok=True)

    for name in COMMON_FILES:
        source = shards["walk_forward_is"] / name
        shutil.copy2(source, output / name)
    for directory in (
        "fixed_position_trade_ledgers",
        "fixed_position_equity_curves",
        "fx_adjusted_trade_ledgers",
    ):
        for period in EXPECTED_COUNTS:
            shutil.copytree(shards[period] / directory, output / directory, dirs_exist_ok=True)

    opportunities = _concat(shards, "all_individual_opportunities.csv")
    actual_counts = opportunities.groupby("period").size().to_dict()
    if actual_counts != EXPECTED_COUNTS:
        raise ValueError(f"opportunity counts do not reconcile: {actual_counts}")
    if len(opportunities) != 7176 or opportunities["opportunity_id"].nunique() != 7176:
        raise ValueError("merged opportunity ledger is incomplete or duplicated")
    if pd.to_datetime(opportunities["exit_date"], errors="raise").max() > CUTOFF:
        raise ValueError("merged opportunity ledger exceeds the frozen cutoff")
    opportunities.to_csv(output / "all_individual_opportunities.csv", index=False)
    opportunities.loc[
        opportunities["selection_provenance_status"].ne("reconstructed_exactly")
    ].to_csv(output / "opportunity_provenance_gaps.csv", index=False)

    fx_opportunities = _concat(shards, "fx_adjusted_opportunities.csv")
    if len(fx_opportunities) != 7176:
        raise ValueError("merged FX opportunity ledger is incomplete")
    fx_opportunities.to_csv(output / "fx_adjusted_opportunities.csv", index=False)

    event_frames: list[pd.DataFrame] = []
    bootstrap_frames: list[pd.DataFrame] = []
    combined, combined_bootstrap = event_study_statistics(opportunities)
    combined["analysis_scope"] = "all_periods_combined"
    combined["period"] = "all_periods_combined"
    combined["analysis_role"] = "combined_walk_forward_and_diagnostics"
    combined_bootstrap["analysis_scope"] = "all_periods_combined"
    combined_bootstrap["period"] = "all_periods_combined"
    combined_bootstrap["analysis_role"] = "combined_walk_forward_and_diagnostics"
    event_frames.append(combined)
    bootstrap_frames.append(combined_bootstrap)
    for period, group in opportunities.groupby("period", sort=False):
        event, bootstrap = event_study_statistics(group)
        event["analysis_scope"] = period
        event["period"] = period
        bootstrap["analysis_scope"] = period
        bootstrap["period"] = period
        event_frames.append(label_analysis_role(event))
        bootstrap_frames.append(label_analysis_role(bootstrap))
    event_summary = pd.concat(event_frames, ignore_index=True)
    event_summary.to_csv(output / "individual_opportunity_statistics.csv", index=False)
    pd.concat(bootstrap_frames, ignore_index=True).to_parquet(
        output / "individual_opportunity_bootstrap.parquet", index=False
    )

    yearly = _concat(shards, "individual_opportunities_yearly.csv")
    yearly.to_csv(output / "individual_opportunities_yearly.csv", index=False)
    reconciliation = label_analysis_role(
        _assert_reconciliation(opportunities, yearly, expected_total=7176)
    )
    reconciliation.to_csv(output / "opportunity_reconciliation.csv", index=False)

    merged: dict[str, pd.DataFrame] = {}
    for name in TABLES:
        frame = _concat(shards, name)
        if name == "benchmark_comparison_by_frequency.csv":
            frame = _repair_benchmark_observation_dates(frame, output)
        merged[name] = frame
        if name == "capacity_violations.csv" and frame.empty:
            frame = pd.DataFrame(
                columns=["period", "variant", "analysis_role", "capacity_currency"]
            )
            merged[name] = frame
        frame.to_csv(output / name, index=False)

    coverage = merged["survivorship_coverage.csv"]
    (output / "survivorship_bias_audit.md").write_text(
        _survivorship_report(coverage), encoding="utf-8"
    )
    fixed = merged["fixed_position_portfolio_results.csv"]
    sequence = merged["sequence_dependence_results.csv"]
    fx_portfolios = merged["fx_adjusted_portfolio_results.csv"]
    benchmarks = merged["benchmark_comparison_by_frequency.csv"]
    costs = merged["cost_liquidity_capacity_results.csv"]
    concentration = merged["return_concentration_analysis.csv"]
    leave_out = merged["leave_one_group_out_results.csv"]
    capacity = merged["capacity_violations.csv"]
    verdicts = _verdicts(event_summary, sequence, fx_portfolios)
    _json(
        output / "separate_verdicts.json",
        {**verdicts, "new_oos_claimed": False, "role": AUDIT_ROLE},
    )
    report = _final_report(
        reconciliation,
        event_summary,
        sequence,
        fixed,
        benchmarks,
        costs,
        concentration,
        fx_portfolios,
        leave_out,
        capacity,
        verdicts,
    )
    (output / "final_opportunity_and_portfolio_audit.md").write_text(
        report, encoding="utf-8"
    )

    manifest = json.loads((output / "frozen_oos_strategy_manifest.json").read_text())
    source_manifest = json.loads(
        (shards["walk_forward_is"] / "final_artifact_manifest.json").read_text()
    )
    summary = {
        "candidate_id": manifest["candidate_id"],
        "opportunities": 7176,
        "period_counts": actual_counts,
        "selection_provenance_gaps": int(
            opportunities["selection_provenance_status"].ne("reconstructed_exactly").sum()
        ),
        "financed": int(opportunities["originally_financed"].astype(bool).sum()),
        "not_financed": int((~opportunities["originally_financed"].astype(bool)).sum()),
        "reconciled": True,
        "sequence_permutations_per_period": 1000,
        "sequence_workers_per_period": 2,
        "period_shards": list(EXPECTED_COUNTS),
        "locked_opened": True,
        "opened_locked_analysis_role": AUDIT_ROLE,
        "new_oos_claimed": False,
        "optimization_performed": False,
        "validation_used_for_selection": False,
        "survivorship_limited": True,
        "cutoff": CUTOFF.date().isoformat(),
        "verdicts": verdicts,
    }
    _json(output / "audit_summary.json", summary)
    write_artifact_manifest(
        output,
        input_artifacts=source_manifest["input_artifacts"],
        commit=os.environ.get("GITHUB_SHA", "unknown"),
    )
    print(json.dumps(summary, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shards-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
