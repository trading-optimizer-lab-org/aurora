"""Correct reporting-only counts in an already evaluated exact-OOS artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from core.execution_policy import require_github_actions_or_explicit_local_permission


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _closed_counts(trades: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    if "status" not in trades.columns:
        raise ValueError("trade ledger lacks status")
    closed = trades.loc[trades["status"].astype(str).eq("closed")].copy()
    closed["exit_date"] = pd.to_datetime(closed["exit_date"], errors="raise")
    closed["exit_year"] = closed["exit_date"].dt.year
    closed["net_return"] = pd.to_numeric(closed["net_return"], errors="raise")
    closed["is_take_profit"] = closed["exit_reason"].astype(str).isin(
        ["take_profit", "gap_through_target"]
    )
    closed["is_time_exit"] = closed["exit_reason"].astype(str).eq("time_exit")
    totals = {
        "closed_operations": int(len(closed)),
        "take_profits": int(closed["is_take_profit"].sum()),
        "time_exits": int(closed["is_time_exit"].sum()),
    }
    return closed, totals


def _correct_yearly(root: Path) -> tuple[dict[str, int], dict[str, int]]:
    yearly_path = root / "exact_strategy_yearly_comparison.csv"
    yearly = pd.read_csv(yearly_path)
    totals_by_period: dict[str, dict[str, int]] = {}
    sources = {
        "diagnostic_reused_holdout": root / "diagnostic_oos_2016_2020_trades.csv",
        "true_locked_oos": root / "true_oos_2021_latest_trades.csv",
    }
    for period, path in sources.items():
        closed, totals = _closed_counts(pd.read_csv(path))
        totals_by_period[period] = totals
        for index in yearly.index[yearly["period"].astype(str).eq(period)]:
            year = int(yearly.at[index, "year"])
            selected = closed.loc[closed["exit_year"].eq(year)]
            yearly.at[index, "operations"] = int(len(selected))
            yearly.at[index, "win_rate"] = (
                float(selected["net_return"].gt(0).mean()) if len(selected) else 0.0
            )
            yearly.at[index, "take_profits"] = int(selected["is_take_profit"].sum())
            yearly.at[index, "time_exits"] = int(selected["is_time_exit"].sum())
    yearly.to_csv(yearly_path, index=False)
    return totals_by_period["diagnostic_reused_holdout"], totals_by_period["true_locked_oos"]


def _write_verdict(root: Path, true_totals: dict[str, int]) -> None:
    summary = _json(root / "exact_oos_summary.json")
    diagnostic = summary["diagnostic_metrics"]
    true_oos = summary["true_oos_metrics"]
    spy = summary["spy_metrics"]
    stats = pd.read_csv(root / "statistical_validation.csv").set_index("test")
    costs = pd.read_csv(root / "cost_sensitivity.csv").set_index("cost_bps_per_side")
    audit = _json(root / "locked_data_audit.json")
    verdict = str(summary["classification"])
    markdown = f"""# Final exact strategy verdict

Classification: `{verdict}`

1. Exact 1995-2015 reproduction: **yes**, including all source ledger rows and the exact operation count.
2. Diagnostic 2016-2020: CAGR {diagnostic['cagr']:.6f}, Sharpe {diagnostic['sharpe']:.6f}, max drawdown {diagnostic['max_drawdown']:.6f}.
3. True locked 2021-{audit['locked_end']}: CAGR {true_oos['cagr']:.6f}, Sharpe {true_oos['sharpe']:.6f}, max drawdown {true_oos['max_drawdown']:.6f}.
4. Beat SPY CAGR: **{true_oos['cagr'] > spy['cagr']}**.
5. Beat SPY Sharpe: **{true_oos['sharpe'] > spy['sharpe']}**.
6. Beat SPY Sortino: **{true_oos['sortino'] > spy['sortino']}**.
7. Lower drawdown than SPY: **{true_oos['max_drawdown'] > spy['max_drawdown']}**.
8. Remained solvent at 5/10/25/50 bps: **{bool(costs.loc[[5, 10, 25, 50], 'survived'].all())}**. These scenarios were not used for selection.
9. Closed operations: **{true_totals['closed_operations']}**.
10. Reached +50% target: **{true_totals['take_profits']}**.
11. Exited after 252 sessions: **{true_totals['time_exits']}**.
12. Year-by-year outcomes are in `exact_strategy_yearly_comparison.csv`; no year was excluded.
13. Statistically distinguishable from zero: **{float(stats.loc['block_bootstrap_sharpe', 'lower_95']) > 0}** by the frozen block-bootstrap rule.
14. Statistically superior to SPY: **{float(stats.loc['paired_daily_return_ttest', 'estimate']) > 0 and float(stats.loc['paired_daily_return_ttest', 'p_value']) <= 0.05}** by paired daily returns.
15. Operable: **{verdict == 'validated_out_of_sample'}** under the predeclared strict verdict; otherwise research-only.
16. Survivorship limitation: **material and unresolved**. The current-universe backfill is not point-in-time membership and can overstate performance.

The true OOS sample is only about five to six years, so statistical power remains limited. No parameter, signal, universe rule, cost, or period was changed after the manifest was frozen.
"""
    (root / "final_exact_strategy_verdict.md").write_text(markdown, encoding="utf-8")


def finalize(root: Path, source_run_id: int, source_artifact_digest: str) -> dict[str, object]:
    require_github_actions_or_explicit_local_permission("exact OOS artifact reporting finalization")
    summary = _json(root / "exact_oos_summary.json")
    if summary.get("locked_opened") is not True or summary.get("locked_strategy_count") != 1:
        raise ValueError("source artifact is not the single locked evaluation")
    original_yearly = pd.read_csv(root / "exact_strategy_yearly_comparison.csv")
    old_operations = int(original_yearly["operations"].sum())
    diagnostic_totals, true_totals = _correct_yearly(root)
    _write_verdict(root, true_totals)
    correction = {
        "kind": "reporting_only_closed_trade_filter",
        "source_run_id": source_run_id,
        "source_artifact_digest": source_artifact_digest,
        "old_yearly_operations_including_rejected": old_operations,
        "diagnostic_closed_operations": diagnostic_totals["closed_operations"],
        "true_oos_closed_operations": true_totals["closed_operations"],
        "true_oos_take_profits": true_totals["take_profits"],
        "true_oos_time_exits": true_totals["time_exits"],
        "financial_logic_changed": False,
        "equity_curve_changed": False,
        "trade_ledger_changed": False,
        "metrics_changed": False,
    }
    audit_path = root / "reporting_correction_audit.json"
    audit_path.write_text(
        json.dumps(correction, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_path = root / "final_artifact_manifest.json"
    artifact_manifest = _json(manifest_path)
    artifact_manifest["reporting_correction"] = correction
    artifact_manifest["files"] = {
        path.name: {"bytes": path.stat().st_size, "sha256": _sha256(path)}
        for path in sorted(root.iterdir())
        if path.is_file() and path.name != manifest_path.name
    }
    manifest_path.write_text(
        json.dumps(artifact_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return correction


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-run-id", type=int, required=True)
    parser.add_argument("--source-artifact-digest", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            finalize(args.root, args.source_run_id, args.source_artifact_digest),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
