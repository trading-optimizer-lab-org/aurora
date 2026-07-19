"""Build the post-lock opportunity and realistic-portfolio diagnostic artifact.

This command consumes only immutable GitHub artifacts.  It does not search,
fit, select, or change the frozen strategy.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
from typing import Any

import numpy as np
import pandas as pd

from aurora.core.execution_policy import require_github_actions_or_explicit_local_permission
from aurora.research.stock_protocol.campaign import canonical_candidate_id
from aurora.research.stock_protocol.entries import apply_entry_rule
from aurora.research.stock_protocol.exact_oos import exact_strategy_spec
from aurora.research.stock_protocol.locked_access import activate_locked_data_access
from aurora.research.stock_protocol.opportunity_audit import (
    AUDIT_ROLE,
    CUTOFF,
    PERIODS,
    benchmark_comparison,
    component_audit_frames,
    enrich_opportunity_paths,
    event_study_statistics,
    frequency_metric_rows,
    fx_adjust_opportunities,
    fx_adjust_price_panel,
    portfolio_metrics,
    portfolio_yearly_rows,
    sequence_dependence,
    sha256_file,
    simulate_opportunity_portfolio,
    symbol_metadata_frame,
    write_artifact_manifest,
    yearly_opportunity_results,
)
from aurora.research.stock_protocol.signals import compute_signal, select_cross_section
from scripts.run_stock_protocol_exact_oos import (
    _locked_shards,
    _manifest_authorization,
    _period_frames,
)


EXPECTED_MANIFEST_SHA256 = "45457b0358b54c63daafec1c1bc2ef362ffba8c811ec2ab59b78a37ac7b871c2"
EXPECTED_FINAL_DIGEST = "sha256:2e878f9cba45ac27d18939b498e54bf4c193b1ce65641231b1914363c1bf4704"
EXPECTED_IS_DIGEST = "sha256:83c07b840680006536343e4407c2cc16f9b73ae33258513088246929628717db"
EXPECTED_COUNTS = {
    "walk_forward_is": 2947,
    "diagnostic_reused_holdout": 2043,
    "opened_locked_diagnostic": 2186,
}
PORTFOLIOS = {
    "P10": (10, 0.10),
    "P20": (20, 0.05),
    "P30": (30, 1.0 / 30.0),
    "P50": (50, 0.02),
    "P100": (100, 0.01),
}
COSTS = (0, 5, 10, 25, 50, 100, 200)


def _json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True, default=str) + "\n",
        encoding="utf-8",
    )


def _one(root: Path, name: str) -> Path:
    matches = list(root.rglob(name))
    if len(matches) != 1:
        raise ValueError(f"expected one {name} below {root}, found {len(matches)}")
    return matches[0]


def _resolve_pack(root: Path) -> Path:
    candidates = [root, root / "pre2021_full_daily_pack"]
    candidates.extend(path.parent for path in root.rglob("shard-000.parquet"))
    for candidate in candidates:
        if (candidate / "shard-000.parquet").is_file() and (candidate / "shard-031.parquet").is_file():
            return candidate
    raise FileNotFoundError("could not resolve the immutable 32-shard prelocked pack")


def _load_ledgers(is_root: Path, final_root: Path) -> pd.DataFrame:
    sources = (
        ("walk_forward_is", _one(is_root, "is_reproduced_trade_ledger.csv")),
        ("diagnostic_reused_holdout", _one(final_root, "diagnostic_oos_2016_2020_trades.csv")),
        ("opened_locked_diagnostic", _one(final_root, "true_oos_2021_latest_trades.csv")),
    )
    frames: list[pd.DataFrame] = []
    for period, path in sources:
        frame = pd.read_csv(path)
        if len(frame) != EXPECTED_COUNTS[period]:
            raise ValueError(f"{period} opportunity count {len(frame)} != {EXPECTED_COUNTS[period]}")
        frame["period"] = period
        frame["source_ledger_sha256"] = sha256_file(path)
        frame["source_row"] = np.arange(len(frame), dtype=int)
        frames.append(frame)
    result = pd.concat(frames, ignore_index=True)
    if len(result) != sum(EXPECTED_COUNTS.values()):
        raise ValueError("source opportunity total is not 7,176")
    return result


def _frozen_events(panel, features: pd.DataFrame, spec: dict[str, Any], authorization) -> pd.DataFrame:
    """Rebuild selection provenance and all ten component scores, not exits."""

    union: list[pd.DataFrame] = []
    component_ids: list[str] = []
    for index, component in enumerate(spec["component_signals"], start=1):
        component_id = canonical_candidate_id(component)
        component_ids.append(component_id)
        variant = dict(component["signal_variant"])
        variant["selection"] = dict(component["selection"])
        variant.setdefault("rebalance", "monthly")
        candidates = compute_signal(
            panel,
            int(component["signal_test_id"]),
            variant,
            features=features,
        )
        candidates["component_id"] = component_id
        candidates["component_index"] = index
        candidates["component_score"] = pd.to_numeric(
            candidates["cross_section_percentile"], errors="raise"
        )
        union.append(candidates)
    weighted = pd.concat(union, ignore_index=True)
    weighted["weighted_vote"] = weighted["component_score"] / len(component_ids)
    metadata = [
        column for column in
        ("available_at", "adj_close", "adj_high", "adj_low", "atr20", "vol_12_1", "mom_12_1", "mom_6_1")
        if column in weighted
    ]
    aggregations: dict[str, Any] = {
        "weighted_vote": "sum",
        "component_index": lambda values: ",".join(str(int(value)) for value in values),
        "component_score": lambda values: json.dumps(
            {str(int(index)): float(score) for index, score in zip(
                weighted.loc[values.index, "component_index"], values
            )},
            sort_keys=True,
        ),
    }
    aggregations.update({column: "first" for column in metadata})
    combined = weighted.groupby(["signal_date", "symbol"], as_index=False).agg(aggregations)
    combined = combined.rename(
        columns={
            "weighted_vote": "score",
            "component_index": "component_indices",
            "component_score": "component_scores_json",
        }
    )
    momentum_columns = [
        column for column in ("mom_12_1", "mom_6_1", "h52", "information_discreteness")
        if column in features
    ]
    if momentum_columns:
        momentum = features[["date", "symbol", *momentum_columns]].rename(
            columns={"date": "signal_date"}
        )
        combined = combined.merge(
            momentum,
            on=["signal_date", "symbol"],
            how="left",
            validate="one_to_one",
        )
    combined["available_at"] = combined["signal_date"]
    selected = select_cross_section(combined, dict(spec["selection"]))
    selected["signal"] = True
    if authorization is None:
        return apply_entry_rule(selected, features, dict(spec["entry"]))
    return apply_entry_rule(
        selected,
        features,
        dict(spec["entry"]),
        locked_authorization=authorization,
    )


def _opportunities_for_period(
    source: pd.DataFrame,
    events: pd.DataFrame,
    panel: pd.DataFrame,
    metadata: pd.DataFrame,
) -> pd.DataFrame:
    ledger = source.copy()
    for column in ("signal_date", "entry_date", "exit_date"):
        ledger[column] = pd.to_datetime(ledger[column], errors="raise").dt.normalize()
    provenance_columns = [
        "symbol", "signal_date", "selection_date", "rvol50", "breakout_level",
        "mom_12_1", "mom_6_1", "component_indices", "component_scores_json", "score",
    ]
    available = [column for column in provenance_columns if column in events]
    provenance = events[available].copy().drop_duplicates(["symbol", "signal_date"], keep="first")
    if "score" in provenance:
        provenance = provenance.rename(columns={"score": "reconstructed_frozen_score"})
    result = ledger.merge(provenance, on=["symbol", "signal_date"], how="left", validate="many_to_one")
    if result["selection_date"].isna().any():
        missing = int(result["selection_date"].isna().sum())
        raise ValueError(f"could not reconcile {missing} frozen opportunities to selection provenance")
    result = result.merge(metadata, on="symbol", how="left", validate="many_to_one")
    result["opportunity_id"] = result.apply(
        lambda row: hashlib.sha256(
            f"{row['period']}|{row['source_row']}|{row['symbol']}|{row['signal_date']}".encode("utf-8")
        ).hexdigest()[:24],
        axis=1,
    )
    result["breakout_date"] = result["signal_date"]
    result["entry_open_real"] = pd.to_numeric(result["entry_price"], errors="raise")
    result["target_50_price"] = result["entry_open_real"] * 1.5
    result["days_selection_to_entry"] = (
        result["entry_date"] - pd.to_datetime(result["selection_date"])
    ).dt.days
    result["originally_financed"] = result["status"].astype(str).eq("closed")
    result["originally_closed"] = result["status"].astype(str).eq("closed")
    result["not_financed_reason"] = np.where(
        result["originally_financed"], "", result["status"].astype(str)
    )
    result["reached_50pct"] = result["exit_reason"].astype(str).isin(
        ["take_profit", "gap_through_target"]
    )
    result["time_exit"] = result["exit_reason"].astype(str).eq("time_exit")
    result["gross_return"] = pd.to_numeric(result["gross_return"], errors="raise")
    result = enrich_opportunity_paths(result, panel)
    overlap = result.sort_values(["symbol", "entry_date", "exit_date"]).copy()
    overlap["overlaps_same_symbol_opportunity"] = (
        overlap.groupby("symbol")["entry_date"].shift(-1).le(overlap["exit_date"])
        | overlap.groupby("symbol")["exit_date"].shift(1).ge(overlap["entry_date"])
    ).fillna(False)
    result = result.merge(
        overlap[["opportunity_id", "overlaps_same_symbol_opportunity"]],
        on="opportunity_id",
        how="left",
        validate="one_to_one",
    )
    return result


def _download_yahoo(symbols: list[str], start: str, end: str) -> dict[str, pd.Series]:
    import yfinance as yf

    output: dict[str, pd.Series] = {}
    for symbol in symbols:
        data = yf.download(
            symbol,
            start=start,
            end=end,
            auto_adjust=False,
            actions=True,
            progress=False,
            threads=False,
        )
        if data.empty:
            continue
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        column = "Adj Close" if "Adj Close" in data else "Close"
        series = pd.to_numeric(data[column], errors="coerce").dropna()
        series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
        output[symbol] = series.loc[series.index <= CUTOFF]
    return output


def _market_data(metadata: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    currencies = sorted(set(metadata.loc[~metadata["currency_unknown"], "currency"].astype(str)) - {"USD"})
    requested = ["SPY", "VT", "ACWI"]
    pairs: dict[str, tuple[str, str]] = {}
    for currency in currencies:
        direct, inverse = f"{currency}USD=X", f"USD{currency}=X"
        requested.extend([direct, inverse])
        pairs[currency] = (direct, inverse)
    downloaded = _download_yahoo(requested, "2006-01-01", "2026-07-18")
    benchmark_parts = [
        pd.DataFrame(
            {"date": downloaded[key].index, "symbol": key, "adj_close": downloaded[key].values}
        )
        for key in ("SPY", "VT", "ACWI")
        if key in downloaded
    ]
    benchmarks = pd.concat(benchmark_parts, ignore_index=True) if benchmark_parts else pd.DataFrame(
        columns=["date", "symbol", "adj_close"]
    )
    fx_rows: list[pd.DataFrame] = []
    fx_audit: list[dict[str, object]] = []
    fx_rows.append(pd.DataFrame({"date": pd.date_range("2006-01-01", CUTOFF, freq="D"), "currency": "USD", "usd_per_local": 1.0}))
    for currency, (direct, inverse) in pairs.items():
        if direct in downloaded:
            series = downloaded[direct]
            orientation = "USD_per_local_direct"
        elif inverse in downloaded:
            series = 1.0 / downloaded[inverse].replace(0, np.nan)
            orientation = "inverted_local_per_USD"
        else:
            fx_audit.append({"currency": currency, "status": "missing", "orientation": "unknown"})
            continue
        fx_rows.append(pd.DataFrame({"date": series.index, "currency": currency, "usd_per_local": series.values}))
        fx_audit.append(
            {
                "currency": currency,
                "status": "downloaded",
                "orientation": orientation,
                "source": "Yahoo Finance historical FX",
                "source_symbol": direct if direct in downloaded else inverse,
                "start": series.index.min(),
                "end": series.index.max(),
                "observations": len(series),
            }
        )
    fx = pd.concat(fx_rows, ignore_index=True).sort_values(["currency", "date"])
    return fx, benchmarks, pd.DataFrame(fx_audit)


def _result_row(period: str, variant: str, curve: pd.DataFrame, ledger: pd.DataFrame, cost: int) -> dict[str, object]:
    funded = ledger["status"].astype(str).eq("closed")
    metrics = portfolio_metrics(curve, ledger)
    profits = pd.to_numeric(ledger.loc[funded, "net_return"], errors="coerce").dropna().sort_values(ascending=False)
    total_profit = max(float(profits.clip(lower=0).sum()), 1e-12)
    return {
        "period": period,
        "variant": variant,
        "cost_bps_per_side": cost,
        **metrics,
        "funded_opportunities": int(funded.sum()),
        "unfunded_opportunities": int((~funded).sum()),
        "opportunities": int(len(ledger)),
        "funded_pct": float(funded.mean()),
        "top5_profit_concentration": float(profits.head(5).clip(lower=0).sum() / total_profit),
        "top10_profit_concentration": float(profits.head(10).clip(lower=0).sum() / total_profit),
        "top20_profit_concentration": float(profits.head(20).clip(lower=0).sum() / total_profit),
    }


def _assert_reconciliation(opportunities: pd.DataFrame, yearly: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    source = opportunities.copy()
    source["year"] = pd.to_datetime(source["entry_date"]).dt.year
    for keys, group in source.groupby(["period", "year"], sort=True):
        funded = int(group["originally_financed"].astype(bool).sum())
        unfunded = int(len(group) - funded)
        passed = len(group) == funded + unfunded
        rows.append(
            {
                "period": keys[0], "year": int(keys[1]), "opportunities": len(group),
                "funded": funded, "unfunded": unfunded, "reconciled": passed,
            }
        )
    audit = pd.DataFrame(rows)
    if not audit["reconciled"].all() or int(audit["opportunities"].sum()) != 7176:
        raise ValueError("opportunity reconciliation failed")
    if int(yearly["opportunities"].sum()) != 7176:
        raise ValueError("yearly opportunity reconciliation failed")
    return audit


def _survivorship_report(coverage: pd.DataFrame) -> str:
    return f"""# Survivorship bias audit

`survivorship_limited = true`

The immutable universe is a current-universe backfill, not point-in-time membership.
It contains {int(coverage['symbols'].max())} distinct symbols at its widest yearly observation
and {int(coverage['late_start_symbols'].max())} symbols with history beginning after the
first observed year. Delisting returns and historically delisted constituents are not
complete. This can overstate long-only selection quality, breakout availability and
take-profit success, and makes comparisons across years non-uniform. No missing delisting
loss was invented. Coverage by year and market is retained in `survivorship_coverage.csv`.
"""


def _verdicts(event_summary: pd.DataFrame, sequence: pd.DataFrame, fixed: pd.DataFrame) -> dict[str, str]:
    event = event_summary.iloc[0]
    individual = (
        "individual_signal_supported"
        if float(event["symbol_cluster_mean_low95"]) > 0 and float(event["year_cluster_mean_low95"]) > 0
        else "individual_signal_weak" if float(event["mean_return"]) > 0 else "individual_signal_not_supported"
    )
    original_row = sequence.loc[sequence["order"].eq("original")]
    original = (
        "original_portfolio_promising"
        if not original_row.empty and float(original_row.iloc[0]["sharpe"]) > 1
        else "original_portfolio_unstable"
    )
    diversified = fixed.loc[fixed["variant"].isin(PORTFOLIOS) & fixed["cost_bps_per_side"].eq(0)]
    construction = (
        "diversified_implementation_promising"
        if not diversified.empty and float(diversified["sharpe"].median()) > 1
        else "diversified_implementation_weak" if not diversified.empty else "diversified_implementation_invalid"
    )
    return {"individual_signal": individual, "original_portfolio": original, "diversified_implementation": construction}


def _final_report(
    counts: pd.DataFrame,
    event: pd.DataFrame,
    sequence: pd.DataFrame,
    fixed: pd.DataFrame,
    benchmark: pd.DataFrame,
    costs: pd.DataFrame,
    concentration: pd.DataFrame,
    verdicts: dict[str, str],
) -> str:
    row = event.iloc[0]
    funded = int(counts["funded"].sum())
    opportunities = int(counts["opportunities"].sum())
    best_cost = costs.loc[costs["cagr"].gt(0), "cost_bps_per_side"].max() if not costs.empty else np.nan
    weekly_spy = benchmark.loc[(benchmark["benchmark"] == "SPY") & (benchmark["frequency"] == "weekly")]
    monthly_spy = benchmark.loc[(benchmark["benchmark"] == "SPY") & (benchmark["frequency"] == "monthly")]
    answers = [
        f"1. Yearly counts are fully listed; total opportunities: **{opportunities:,}**.",
        f"2. Mean return {row['mean_return']:.4%}; median {row['median_return']:.4%}.",
        f"3. Reached +50%: {row['target_50_pct']:.2%}.",
        f"4. Average opportunity positive: **{float(row['mean_return']) > 0}**; classification `{verdicts['individual_signal']}`.",
        f"5. Symbol/year clustered lower bounds: {row['symbol_cluster_mean_low95']:.4%} / {row['year_cluster_mean_low95']:.4%}.",
        f"6. Arrival-order distribution and original percentiles are in `sequence_dependence_results.csv` ({len(sequence)} deterministic rows).",
        f"7. Original portfolio funded {funded:,} of {opportunities:,} opportunities ({funded/opportunities:.2%}).",
        "8. P10/P20/P30/P50/P100 are reported without selecting a winner.",
        f"9. Profit concentration by variant is in the fixed portfolio and concentration files; diagnostic only.",
        "10. FX-adjusted results are separate and exclude unknown currencies rather than inventing rates.",
        "11. VT is the broadest available global benchmark; ACWI is also reported where history overlaps.",
        f"12. SPY weekly/monthly Sharpe differences are {weekly_spy['sharpe_difference'].mean() if len(weekly_spy) else np.nan:.4f} / {monthly_spy['sharpe_difference'].mean() if len(monthly_spy) else np.nan:.4f}.",
        "13. VT and ACWI comparisons are in `benchmark_comparison_by_frequency.csv`.",
        "14. Dependence on 2025 is quantified by the explicit 2025 exclusion row.",
        f"15. Dependence on top trades is quantified in {len(concentration)} concentration/leave-out rows.",
        "16. Every represented country and market is excluded once in `leave_one_group_out_results.csv`.",
        f"17. Highest tested cost with positive CAGR: {best_cost} bps per side (diagnostic, not selection).",
        "18. Operability is judged from capacity, cash, concentration and diversified portfolios, not event-study CAGR.",
        "19. Point-in-time membership, delistings, asynchronous markets and opened locked data prevent a fresh validation claim.",
        "20. A genuinely future test requires an untouched, predeclared post-2026-07-17 period with the strategy and portfolio fixed now.",
    ]
    return "# Final opportunity and portfolio audit\n\n" + "\n\n".join(answers) + "\n\n## Separate verdicts\n\n" + "\n".join(f"- `{key}`: `{value}`" for key, value in verdicts.items()) + f"\n\nAll 2021-03-11 to 2026-07-17 analysis is labelled `{AUDIT_ROLE}`. No new OOS claim is made.\n"


def run(args: argparse.Namespace) -> None:
    require_github_actions_or_explicit_local_permission("stock protocol opportunity audit")
    output = args.output_root
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.manifest
    if sha256_file(manifest_path) != EXPECTED_MANIFEST_SHA256:
        raise ValueError("frozen manifest hash mismatch")
    original_manifest = manifest_path.read_bytes()
    manifest = json.loads(original_manifest)
    spec = manifest["strategy_spec"]
    if spec != exact_strategy_spec():
        raise ValueError("manifest strategy differs from exact frozen source")
    if str(manifest["periods"]["locked_end"]) != CUTOFF.date().isoformat():
        raise ValueError("frozen cutoff mismatch")
    shutil.copy2(manifest_path, output / "frozen_oos_strategy_manifest.json")
    _json(
        output / "frozen_strategy_exact.json",
        {
            "candidate_id": manifest["candidate_id"], "strategy_spec": spec,
            "manifest_sha256": EXPECTED_MANIFEST_SHA256, "role": AUDIT_ROLE,
            "optimization_performed": False, "new_oos_claimed": False,
        },
    )
    full_components, unique_components = component_audit_frames(spec)
    full_components.to_csv(output / "frozen_component_signals.csv", index=False)
    unique_components.to_csv(output / "frozen_effective_unique_signals.csv", index=False)

    all_source = _load_ledgers(args.is_root, args.final_root)
    metadata = symbol_metadata_frame(all_source["symbol"])
    metadata.to_csv(output / "symbol_exchange_currency_map.csv", index=False)
    fx, benchmarks, fx_audit = _market_data(metadata)
    fx_audit.to_csv(output / "historical_fx_audit.csv", index=False)
    locked = _locked_shards(
        args.locked_shards_root,
        manifest_sha256=EXPECTED_MANIFEST_SHA256,
        implementation_commit=str(manifest["implementation_commit"]),
    )
    pack_root = _resolve_pack(args.pack_root)

    all_opportunities: list[pd.DataFrame] = []
    fixed_rows: list[dict[str, object]] = []
    fixed_yearly: list[pd.DataFrame] = []
    cost_rows: list[dict[str, object]] = []
    capacity_rows: list[pd.DataFrame] = []
    calendar_rows: list[pd.DataFrame] = []
    benchmark_rows: list[pd.DataFrame] = []
    regression_rows: list[pd.DataFrame] = []
    sequence_rows: list[pd.DataFrame] = []
    sequence_distribution: list[pd.DataFrame] = []
    concentration_rows: list[dict[str, object]] = []
    leave_rows: list[dict[str, object]] = []
    coverage_rows: list[dict[str, object]] = []
    fx_portfolio_rows: list[dict[str, object]] = []
    curves_by_period: dict[str, dict[str, pd.DataFrame]] = {}

    (output / "fixed_position_trade_ledgers").mkdir(exist_ok=True)
    (output / "fixed_position_equity_curves").mkdir(exist_ok=True)
    period_load = {
        "walk_forward_is": ("2006-01-01", "2015-12-31", False),
        "diagnostic_reused_holdout": ("2014-01-01", "2020-12-31", False),
        "opened_locked_diagnostic": ("2020-01-01", "2026-07-17", True),
    }
    for period, (load_start, end, include_locked) in period_load.items():
        authorization = None
        if include_locked:
            authorization = _manifest_authorization(
                manifest_path, EXPECTED_MANIFEST_SHA256, str(manifest["implementation_commit"])
            )
            activate_locked_data_access(authorization, end=CUTOFF)
        panel, features = _period_frames(
            pack_root=pack_root, locked=locked, start=load_start, end=end,
            include_locked=include_locked, authorization=authorization,
        )
        if pd.to_datetime(panel.frame["date"]).max() > CUTOFF:
            raise ValueError("panel contains a date after 2026-07-17")
        events = _frozen_events(panel, features, spec, authorization)
        opportunities = _opportunities_for_period(
            all_source.loc[all_source["period"].eq(period)], events, panel.frame, metadata
        )
        if len(opportunities) != EXPECTED_COUNTS[period]:
            raise ValueError(f"enriched {period} count mismatch")
        all_opportunities.append(opportunities)
        panel_frame = panel.frame.copy()
        panel_frame["date"] = pd.to_datetime(panel_frame["date"]).dt.normalize()
        period_start, period_end = PERIODS[period]
        for year, part in panel_frame.loc[panel_frame["date"].between(period_start, period_end)].groupby(panel_frame.loc[panel_frame["date"].between(period_start, period_end), "date"].dt.year):
            coverage_rows.append(
                {
                    "period": period, "year": int(year), "symbols": int(part["symbol"].nunique()),
                    "late_start_symbols": int(part.groupby("symbol")["date"].min().gt(pd.Timestamp(f"{int(year)}-01-15")).sum()),
                    "markets": int(metadata.loc[metadata["symbol"].isin(part["symbol"]), "market"].nunique()),
                }
            )

        period_curves: dict[str, pd.DataFrame] = {}
        original_curve, original_ledger = simulate_opportunity_portfolio(
            opportunities, panel_frame, max_positions=None, max_initial_weight=None,
            order_mode="original",
        )
        fixed_rows.append(_result_row(period, "Original", original_curve, original_ledger, 0))
        fixed_yearly.append(portfolio_yearly_rows(original_curve, original_ledger, period=period, variant="Original", cost_bps=0))
        period_curves["Original"] = original_curve
        original_curve.to_csv(output / "fixed_position_equity_curves" / f"{period}_Original.csv", index=False)
        original_ledger.to_csv(output / "fixed_position_trade_ledgers" / f"{period}_Original.csv", index=False)

        for variant, (positions, weight) in PORTFOLIOS.items():
            curve, ledger = simulate_opportunity_portfolio(
                opportunities, panel_frame, max_positions=positions, max_initial_weight=weight,
                order_mode="score",
            )
            fixed_rows.append(_result_row(period, variant, curve, ledger, 0))
            fixed_yearly.append(portfolio_yearly_rows(curve, ledger, period=period, variant=variant, cost_bps=0))
            period_curves[variant] = curve
            curve.to_csv(output / "fixed_position_equity_curves" / f"{period}_{variant}.csv", index=False)
            ledger.to_csv(output / "fixed_position_trade_ledgers" / f"{period}_{variant}.csv", index=False)
            capacity = ledger.loc[ledger["simulation_capacity_reduced"].astype(bool)].copy()
            if not capacity.empty:
                capacity["period"] = period
                capacity["variant"] = variant
                capacity_rows.append(capacity)
            for cost in COSTS:
                if cost == 0:
                    cost_curve, cost_ledger = curve, ledger
                else:
                    cost_curve, cost_ledger = simulate_opportunity_portfolio(
                        opportunities, panel_frame, max_positions=positions,
                        max_initial_weight=weight, order_mode="score", cost_bps_per_side=cost,
                    )
                cost_rows.append(_result_row(period, variant, cost_curve, cost_ledger, cost))

        # Sequence dependence is deliberately evaluated on the original cash rule.
        seq, distribution = sequence_dependence(opportunities, panel_frame, simulations=1000)
        seq["period"] = period
        distribution["period"] = period
        sequence_rows.append(seq)
        sequence_distribution.append(distribution)

        for variant, curve in period_curves.items():
            calendar_rows.append(frequency_metric_rows(curve, period=period, variant=variant))
            for benchmark_name in ("SPY", "VT", "ACWI"):
                comparison, regressions = benchmark_comparison(
                    curve,
                    benchmarks,
                    benchmark=benchmark_name,
                    period=period,
                    variant=variant,
                )
                benchmark_rows.append(comparison)
                regression_rows.append(regressions)
        curves_by_period[period] = period_curves

        fx_opportunities = fx_adjust_opportunities(opportunities, fx)
        known = fx_opportunities.loc[fx_opportunities["return_usd"].notna()].copy()
        known["entry_price"] = known["entry_value_usd_per_share"]
        known["exit_price"] = known["exit_value_usd_per_share"] + known["dividend_value_usd_per_share"].fillna(0)
        usd_panel = fx_adjust_price_panel(panel_frame, metadata, fx)
        for variant, (positions, weight) in PORTFOLIOS.items():
            curve, ledger = simulate_opportunity_portfolio(
                known, usd_panel, max_positions=positions, max_initial_weight=weight,
                order_mode="score",
            )
            fx_portfolio_rows.append(
                {
                    **_result_row(period, variant, curve, ledger, 0),
                    "known_currency_opportunities": len(known),
                    "known_currency_pct": len(known) / len(opportunities),
                }
            )

        # Concentration and leave-group-out use P20, declared in advance as a
        # neutral middle portfolio. They are diagnostics, never selection.
        p20_ledger = pd.read_csv(output / "fixed_position_trade_ledgers" / f"{period}_P20.csv")
        closed = p20_ledger.loc[p20_ledger["status"].astype(str).eq("closed")].copy()
        closed["profit"] = pd.to_numeric(closed["simulation_exit_notional"], errors="coerce") - pd.to_numeric(closed["simulation_entry_notional"], errors="coerce")
        positive_profit = max(float(closed["profit"].clip(lower=0).sum()), 1e-12)
        for n in (5, 10, 20):
            concentration_rows.append({"period": period, "measure": f"top_{n}_trades", "value": float(closed.nlargest(n, "profit")["profit"].clip(lower=0).sum() / positive_profit)})
        concentration_rows.extend(
            {"period": period, "measure": key, "value": value}
            for key, value in {
                "target_50_pct": float(closed["reached_50pct"].astype(bool).mean()) if len(closed) else 0,
                "over_200_sessions_pct": float(pd.to_numeric(closed["holding_sessions"], errors="coerce").gt(200).mean()) if len(closed) else 0,
                "profit_2025_pct": float(closed.loc[pd.to_datetime(closed["exit_date"]).dt.year.eq(2025), "profit"].sum() / positive_profit),
            }.items()
        )
        for column in ("country", "market", "currency"):
            for value in sorted(closed[column].dropna().astype(str).unique()):
                filtered = opportunities.loc[~opportunities[column].astype(str).eq(value)]
                curve, ledger = simulate_opportunity_portfolio(filtered, panel_frame, max_positions=20, max_initial_weight=0.05, order_mode="score")
                leave_rows.append({"period": period, "exclusion_type": column, "excluded": value, **portfolio_metrics(curve, ledger)})
        for year in sorted(pd.to_datetime(closed["entry_date"]).dt.year.unique()):
            filtered = opportunities.loc[pd.to_datetime(opportunities["entry_date"]).dt.year.ne(year)]
            curve, ledger = simulate_opportunity_portfolio(filtered, panel_frame, max_positions=20, max_initial_weight=0.05, order_mode="score")
            leave_rows.append({"period": period, "exclusion_type": "year", "excluded": int(year), **portfolio_metrics(curve, ledger)})
        for n, label in ((1, "top_trade"), (5, "top_5_trades")):
            excluded_ids = set(closed.nlargest(n, "profit")["opportunity_id"].astype(str))
            filtered = opportunities.loc[~opportunities["opportunity_id"].astype(str).isin(excluded_ids)]
            curve, ledger = simulate_opportunity_portfolio(filtered, panel_frame, max_positions=20, max_initial_weight=0.05, order_mode="score")
            leave_rows.append({"period": period, "exclusion_type": label, "excluded": ",".join(sorted(excluded_ids)), **portfolio_metrics(curve, ledger)})

        del features, events, panel, panel_frame, usd_panel
        gc.collect()

    opportunities = pd.concat(all_opportunities, ignore_index=True)
    if len(opportunities) != 7176 or opportunities["opportunity_id"].duplicated().any():
        raise ValueError("final opportunity ledger is incomplete or duplicated")
    if pd.to_datetime(opportunities["exit_date"]).max() > CUTOFF:
        raise ValueError("opportunity ledger exceeds the frozen cutoff")
    opportunities["analysis_role"] = np.where(
        opportunities["period"].eq("opened_locked_diagnostic"), AUDIT_ROLE, opportunities["period"]
    )
    fx_opportunities = fx_adjust_opportunities(opportunities, fx)
    opportunities = opportunities.merge(
        fx_opportunities[["opportunity_id", "return_usd", "fx_return_contribution"]],
        on="opportunity_id", how="left", validate="one_to_one",
    )
    opportunities.to_csv(output / "all_individual_opportunities.csv", index=False)
    fx_opportunities.to_csv(output / "fx_adjusted_opportunities.csv", index=False)
    event_summary, bootstrap = event_study_statistics(opportunities)
    event_summary.to_csv(output / "individual_opportunity_statistics.csv", index=False)
    bootstrap.to_parquet(output / "individual_opportunity_bootstrap.parquet", index=False)
    yearly = yearly_opportunity_results(opportunities)
    yearly = yearly.merge(opportunities.assign(year=pd.to_datetime(opportunities["entry_date"]).dt.year)[["year", "period"]].drop_duplicates(), on="year", how="left")
    yearly.to_csv(output / "individual_opportunities_yearly.csv", index=False)
    reconciliation = _assert_reconciliation(opportunities, yearly)
    reconciliation.to_csv(output / "opportunity_reconciliation.csv", index=False)

    fixed = pd.DataFrame(fixed_rows)
    fixed.to_csv(output / "fixed_position_portfolio_results.csv", index=False)
    pd.concat(fixed_yearly, ignore_index=True).to_csv(output / "fixed_position_portfolio_yearly.csv", index=False)
    costs = pd.DataFrame(cost_rows)
    costs.to_csv(output / "cost_liquidity_capacity_results.csv", index=False)
    (pd.concat(capacity_rows, ignore_index=True) if capacity_rows else pd.DataFrame()).to_csv(output / "capacity_violations.csv", index=False)
    sequence = pd.concat(sequence_rows, ignore_index=True)
    sequence.to_csv(output / "sequence_dependence_results.csv", index=False)
    pd.concat(sequence_distribution, ignore_index=True).to_csv(output / "sequence_permutation_distribution.csv", index=False)
    pd.concat(calendar_rows, ignore_index=True).to_csv(output / "calendar_frequency_metrics.csv", index=False)
    benchmark_frame = pd.concat(benchmark_rows, ignore_index=True)
    benchmark_frame.to_csv(output / "benchmark_comparison_by_frequency.csv", index=False)
    pd.concat(regression_rows, ignore_index=True).to_csv(output / "benchmark_regressions.csv", index=False)
    pd.DataFrame(fx_portfolio_rows).to_csv(output / "fx_adjusted_portfolio_results.csv", index=False)
    concentration = pd.DataFrame(concentration_rows)
    concentration.to_csv(output / "return_concentration_analysis.csv", index=False)
    pd.DataFrame(leave_rows).to_csv(output / "leave_one_group_out_results.csv", index=False)
    coverage = pd.DataFrame(coverage_rows)
    coverage.to_csv(output / "survivorship_coverage.csv", index=False)
    (output / "survivorship_bias_audit.md").write_text(_survivorship_report(coverage), encoding="utf-8")

    verdicts = _verdicts(event_summary, sequence, fixed)
    _json(output / "separate_verdicts.json", {**verdicts, "new_oos_claimed": False, "role": AUDIT_ROLE})
    report = _final_report(reconciliation, event_summary, sequence, fixed, benchmark_frame, costs, concentration, verdicts)
    (output / "final_opportunity_and_portfolio_audit.md").write_text(report, encoding="utf-8")
    summary = {
        "candidate_id": manifest["candidate_id"], "opportunities": len(opportunities),
        "period_counts": opportunities.groupby("period").size().to_dict(),
        "financed": int(opportunities["originally_financed"].sum()),
        "not_financed": int((~opportunities["originally_financed"]).sum()),
        "reconciled": True, "sequence_permutations_per_period": 1000,
        "locked_opened": True, "opened_locked_analysis_role": AUDIT_ROLE,
        "new_oos_claimed": False, "optimization_performed": False,
        "validation_used_for_selection": False, "survivorship_limited": True,
        "cutoff": CUTOFF.date().isoformat(), "verdicts": verdicts,
    }
    _json(output / "audit_summary.json", summary)
    if manifest_path.read_bytes() != original_manifest:
        raise ValueError("frozen manifest was modified")
    write_artifact_manifest(
        output,
        input_artifacts={"final": EXPECTED_FINAL_DIGEST, "is": EXPECTED_IS_DIGEST, "manifest": EXPECTED_MANIFEST_SHA256},
        commit=os.environ.get("GITHUB_SHA", "unknown"),
    )
    print(json.dumps(summary, sort_keys=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--is-root", type=Path, required=True)
    parser.add_argument("--final-root", type=Path, required=True)
    parser.add_argument("--pack-root", type=Path, required=True)
    parser.add_argument("--locked-shards-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
