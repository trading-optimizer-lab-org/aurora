"""GitHub-only clean portfolio and position-size evaluation for one GTBI strategy."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any

import numpy as np
import pandas as pd

from scripts import global_technical_buy_indicator as gtbi
from scripts.gtbi_clean_portfolio import (
    DataQualityPolicy,
    PortfolioConfig,
    choose_risk_compliant_result,
    prepare_signal_portfolio_data,
    sanitize_symbol_prices,
    simulate_prepared_signal_portfolio,
)


ENGINE_VERSION = "gtbi_clean_portfolio_v7"
DEFAULT_STRATEGY_ID = "lhv1_2f6eb0c50f_fam_00_v1004"
DEFAULT_POSITION_SIZES = "0.001,0.0025,0.005,0.0075,0.01,0.0125,0.0135,0.015,0.02,0.025,0.03,0.04,0.05"
DEFAULT_MAX_POSITIONS = "10,20,30,50"


def parse_float_grid(value: str) -> list[float]:
    values = sorted({float(part.strip()) for part in str(value).split(",") if part.strip()})
    if not values or any(not math.isfinite(item) or not 0 < item <= 1 for item in values):
        raise ValueError("position sizes must contain values in (0, 1]")
    return values


def parse_int_grid(value: str) -> list[int]:
    values = sorted({int(part.strip()) for part in str(value).split(",") if part.strip()})
    if not values or any(item < 1 for item in values):
        raise ValueError("max positions must contain positive integers")
    return values


def load_strategy_payload(pack_root: Path, strategy_id: str) -> dict[str, Any]:
    root = Path(pack_root)
    match = re.search(r"_v(\d+)$", str(strategy_id))
    paths: list[Path] = []
    if match:
        likely = root / "shards" / f"shard_{int(match.group(1)) // 200:03d}.jsonl"
        if likely.exists():
            paths.append(likely)
    paths.extend(path for path in sorted((root / "shards").glob("shard_*.jsonl")) if path not in paths)
    if not paths:
        paths = sorted(root.rglob("*.jsonl"))
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if strategy_id not in line:
                    continue
                payload = json.loads(line)
                if str(payload.get("strategy_id")) == str(strategy_id):
                    return dict(payload)
    raise KeyError(f"strategy not found: {strategy_id}")


def build_concentration_summary(ledger: pd.DataFrame, *, initial_capital: float) -> dict[str, Any]:
    if ledger.empty or "net_pnl" not in ledger.columns:
        return {
            "top_trade_positive_pnl_share": 0.0,
            "top_symbol_positive_pnl_share": 0.0,
            "return_without_top_10_trades_pct": 0.0,
            "profitable_trades": 0,
        }
    pnl = pd.to_numeric(ledger["net_pnl"], errors="coerce").fillna(0.0)
    positive = pnl.clip(lower=0.0)
    positive_total = float(positive.sum())
    top_trade_share = float(positive.max() / positive_total) if positive_total > 0 else 0.0
    symbols = ledger.get("original_symbol", ledger.get("symbol", pd.Series("", index=ledger.index))).astype(str)
    positive_by_symbol = positive.groupby(symbols).sum()
    top_symbol_share = float(positive_by_symbol.max() / positive_total) if positive_total > 0 else 0.0
    top_ten = float(pnl.nlargest(min(10, len(pnl))).sum())
    return {
        "top_trade_positive_pnl_share": top_trade_share,
        "top_symbol_positive_pnl_share": top_symbol_share,
        "return_without_top_10_trades_pct": float((pnl.sum() - top_ten) / float(initial_capital) * 100.0),
        "profitable_trades": int((pnl > 0).sum()),
    }


def validate_selected_result(
    selected: dict[str, Any] | pd.Series,
    annual_returns: pd.DataFrame,
    daily_equity: pd.DataFrame,
    *,
    locked_start: str,
    risk_limit_pct: float,
) -> None:
    limit = float(risk_limit_pct)
    risk_fields = (
        "train_max_drawdown_pct",
        "validation_max_drawdown_pct",
        "train_worst_year_pct",
        "validation_worst_year_pct",
    )
    if any(float(selected[field]) <= -limit for field in risk_fields):
        raise ValueError("selected portfolio breaches risk limit")
    locked = pd.Timestamp(locked_start)
    if not annual_returns.empty and int(pd.to_numeric(annual_returns["year"], errors="coerce").max()) >= locked.year:
        raise ValueError("annual results expose locked data")
    if not daily_equity.empty:
        dates = pd.to_datetime(daily_equity["date"], errors="coerce")
        if bool((dates >= locked).fillna(False).any()):
            raise ValueError("daily equity exposes locked data")
        if bool((pd.to_numeric(daily_equity["cash"], errors="coerce") < -1e-6).fillna(True).any()):
            raise ValueError("portfolio uses negative cash")
        if bool((pd.to_numeric(daily_equity["gross_exposure"], errors="coerce") > 1.0 + 1e-9).fillna(True).any()):
            raise ValueError("portfolio uses leverage")


def _git_sha() -> str:
    value = os.environ.get("GITHUB_SHA", "").strip()
    if value:
        return value
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def _sanitize_pack(
    *,
    data_pack_root: Path,
    locked_start: str,
    policy: DataQualityPolicy,
    max_symbols: int,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    prices_path = Path(data_pack_root) / "prices.parquet"
    benchmark_path = Path(data_pack_root) / "benchmark.parquet"
    if not prices_path.exists() or not benchmark_path.exists():
        raise FileNotFoundError("data pack needs prices.parquet and benchmark.parquet")
    prices = pd.read_parquet(prices_path)
    if "symbol" not in prices.columns:
        raise ValueError("prices.parquet has no symbol column")
    symbols = sorted(prices["symbol"].dropna().astype(str).unique())
    if max_symbols > 0:
        symbols = symbols[: int(max_symbols)]
    symbol_set = set(symbols)
    frames: dict[str, pd.DataFrame] = {}
    diagnostics: list[dict[str, Any]] = []
    anomalies: list[pd.DataFrame] = []
    for symbol, group in prices.loc[prices["symbol"].astype(str).isin(symbol_set)].groupby("symbol", sort=True):
        result = sanitize_symbol_prices(group, symbol=str(symbol), locked_start=locked_start, policy=policy)
        frames.update(result.segments)
        diagnostics.append(result.diagnostics)
        if not result.anomalies.empty:
            anomalies.append(result.anomalies)
    del prices

    benchmark_raw = pd.read_parquet(benchmark_path)
    benchmark_policy = DataQualityPolicy(
        max_adjusted_gap_ratio=policy.max_adjusted_gap_ratio,
        min_segment_rows=min(policy.min_segment_rows, max(len(benchmark_raw), 2)),
    )
    benchmark_result = sanitize_symbol_prices(
        benchmark_raw,
        symbol="SPY",
        locked_start=locked_start,
        policy=benchmark_policy,
    )
    if not benchmark_result.segments:
        raise ValueError("SPY benchmark has no clean segment")
    benchmark = max(benchmark_result.segments.values(), key=len).copy()
    diagnostics.append(benchmark_result.diagnostics)
    if not benchmark_result.anomalies.empty:
        anomalies.append(benchmark_result.anomalies)
    quality = pd.DataFrame(diagnostics)
    anomaly_frame = pd.concat(anomalies, ignore_index=True) if anomalies else pd.DataFrame(
        columns=[
            "symbol",
            "date",
            "reason",
            "adjusted_open_to_previous_close_ratio",
            "adjusted_close_to_previous_close_ratio",
        ]
    )
    return frames, benchmark, quality, anomaly_frame


def _build_signals(
    *,
    frames: dict[str, pd.DataFrame],
    benchmark: pd.DataFrame,
    config: gtbi.IndicatorConfig,
    strategy_id: str,
) -> tuple[dict[str, pd.Series], dict[str, pd.Series], dict[str, Any]]:
    feature_store = gtbi.build_feature_store(frames, benchmark, enabled=True, prewarm=False)
    signals, diagnostics = gtbi._build_signals_by_symbol(
        config=config,
        candidate_id=strategy_id,
        symbol_frames=frames,
        benchmark_prices=benchmark,
        deadline=None,
        feature_store=feature_store,
        max_workers=max(int(os.environ.get("GTBI_SYMBOL_WORKERS", "4")), 1),
    )
    market_exits = {
        symbol: ~gtbi._market_trend_ok_for_frame(frame, benchmark, config)
        for symbol, frame in frames.items()
    } if config.use_market_exit else {}
    return dict(signals), market_exits, {
        **diagnostics,
        "feature_store_seconds": float(feature_store.seconds_build),
        "signal_symbols": int(len(signals)),
    }


def _sweep_row(
    *,
    position_size: float,
    max_positions: int,
    train_result: Any,
    validation_result: Any,
    risk_limit_pct: float,
) -> dict[str, Any]:
    row: dict[str, Any] = {"position_size_pct": position_size, "max_positions": max_positions}
    for split, result in (("train", train_result), ("validation", validation_result)):
        for field in (
            "ending_equity",
            "total_return_pct",
            "cagr_pct",
            "max_drawdown_pct",
            "worst_year_pct",
            "positive_years",
            "years",
            "trades_accepted",
            "entries_skipped",
            "max_open_positions",
            "max_gross_exposure",
        ):
            row[f"{split}_{field}"] = result.summary[field]
    limit = float(risk_limit_pct)
    row["risk_limit_pass"] = all(
        float(row[field]) > -limit
        for field in (
            "train_max_drawdown_pct",
            "validation_max_drawdown_pct",
            "train_worst_year_pct",
            "validation_worst_year_pct",
        )
    )
    return row


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    policy = DataQualityPolicy(
        max_adjusted_gap_ratio=float(args.max_adjusted_gap_ratio),
        min_segment_rows=int(args.min_segment_rows),
    )
    frames, benchmark, quality, anomalies = _sanitize_pack(
        data_pack_root=Path(args.data_pack_root),
        locked_start=args.locked_start,
        policy=policy,
        max_symbols=int(args.max_symbols),
    )
    payload = load_strategy_payload(Path(args.strategy_pack_root), args.strategy_id)
    candidate = gtbi.external_strategy_to_config(payload)
    if candidate.unsupported_rules:
        raise ValueError(f"strategy has unsupported rules: {candidate.unsupported_rules}")
    signals, market_exits, signal_diagnostics = _build_signals(
        frames=frames,
        benchmark=benchmark,
        config=candidate.config,
        strategy_id=args.strategy_id,
    )
    train_signal_dates = [
        pd.Timestamp(date)
        for signal in signals.values()
        for date in signal.index[signal.to_numpy(dtype=bool)]
        if pd.Timestamp(date) <= pd.Timestamp(args.train_end)
    ]
    train_start = min(train_signal_dates) if train_signal_dates else pd.Timestamp(args.train_end)
    train_data = prepare_signal_portfolio_data(
        signals,
        frames,
        market_exit_signals=market_exits,
        start=str(train_start.date()),
        end=args.train_end,
        indicator_config=candidate.config,
    )
    validation_data = prepare_signal_portfolio_data(
        signals,
        frames,
        market_exit_signals=market_exits,
        start=args.validation_start,
        end=args.validation_end,
        indicator_config=candidate.config,
    )

    position_sizes = parse_float_grid(args.position_sizes)
    max_positions_grid = parse_int_grid(args.max_positions_grid)
    sweep_rows: list[dict[str, Any]] = []
    for max_positions in max_positions_grid:
        for position_size in position_sizes:
            portfolio_config = PortfolioConfig(
                initial_capital=float(args.initial_capital),
                position_size_pct=position_size,
                max_positions=max_positions,
                max_gross_exposure=1.0,
                transaction_cost_bps_per_side=float(args.transaction_cost_bps_per_side),
                slippage_bps_per_side=float(args.slippage_bps_per_side),
                allow_fractional_shares=bool(args.allow_fractional_shares),
            )
            train_result = simulate_prepared_signal_portfolio(train_data, portfolio_config=portfolio_config)
            validation_result = simulate_prepared_signal_portfolio(validation_data, portfolio_config=portfolio_config)
            sweep_rows.append(
                _sweep_row(
                    position_size=position_size,
                    max_positions=max_positions,
                    train_result=train_result,
                    validation_result=validation_result,
                    risk_limit_pct=float(args.risk_limit_pct),
                )
            )
    sweep = pd.DataFrame(sweep_rows)
    try:
        selected = choose_risk_compliant_result(sweep, risk_limit_pct=float(args.safety_target_pct))
        selected_target = float(args.safety_target_pct)
    except ValueError:
        selected = choose_risk_compliant_result(sweep, risk_limit_pct=float(args.risk_limit_pct))
        selected_target = float(args.risk_limit_pct)

    selected_config = PortfolioConfig(
        initial_capital=float(args.initial_capital),
        position_size_pct=float(selected["position_size_pct"]),
        max_positions=int(selected["max_positions"]),
        max_gross_exposure=1.0,
        transaction_cost_bps_per_side=float(args.transaction_cost_bps_per_side),
        slippage_bps_per_side=float(args.slippage_bps_per_side),
        allow_fractional_shares=bool(args.allow_fractional_shares),
    )
    train_result = simulate_prepared_signal_portfolio(train_data, portfolio_config=selected_config)
    validation_result = simulate_prepared_signal_portfolio(validation_data, portfolio_config=selected_config)
    annual = pd.concat(
        [train_result.annual_returns.assign(split="train"), validation_result.annual_returns.assign(split="validation")],
        ignore_index=True,
    )
    daily = pd.concat(
        [train_result.daily_equity.assign(split="train"), validation_result.daily_equity.assign(split="validation")],
        ignore_index=True,
    )
    ledger = pd.concat(
        [train_result.ledger.assign(split="train"), validation_result.ledger.assign(split="validation")],
        ignore_index=True,
    )
    skipped = pd.concat(
        [train_result.skipped_entries.assign(split="train"), validation_result.skipped_entries.assign(split="validation")],
        ignore_index=True,
    )
    validate_selected_result(
        selected,
        annual,
        daily,
        locked_start=args.locked_start,
        risk_limit_pct=float(args.risk_limit_pct),
    )
    concentration = {
        "train": build_concentration_summary(train_result.ledger, initial_capital=float(args.initial_capital)),
        "validation": build_concentration_summary(validation_result.ledger, initial_capital=float(args.initial_capital)),
    }
    extreme_trades = int(
        (pd.to_numeric(ledger.get("portfolio_trade_return_pct", pd.Series(dtype=float)), errors="coerce").abs() > 500).sum()
    )
    provenance_payload = {
        "engine_version": ENGINE_VERSION,
        "code_sha": _git_sha(),
        "source_data_run_id": str(args.source_data_run_id),
        "source_artifact_name": str(args.source_artifact_name),
        "strategy_id": str(args.strategy_id),
        "strategy_payload": payload,
        "train_end": args.train_end,
        "validation_start": args.validation_start,
        "validation_end": args.validation_end,
        "locked_start": args.locked_start,
        "position_sizes": position_sizes,
        "max_positions_grid": max_positions_grid,
        "risk_limit_pct": float(args.risk_limit_pct),
    }
    run_hash = hashlib.sha256(json.dumps(provenance_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    summary = {
        **provenance_payload,
        "portfolio_run_hash": run_hash,
        "github_only_run": True,
        "requires_local_machine": False,
        "locked_opened": False,
        "symbols_loaded": int(quality["symbol"].ne("SPY").sum()),
        "clean_segments": int(len(frames)),
        "symbols_excluded": int(quality["excluded"].sum()),
        "price_hard_breaks": int(quality["hard_breaks"].sum()),
        "price_anomaly_rows": int(len(anomalies)),
        "raw_signals_total": int(signal_diagnostics.get("raw_signals_total", 0)),
        "signal_symbols": int(signal_diagnostics.get("signal_symbols", 0)),
        "sizing_combinations": int(len(sweep)),
        "selected_risk_target_pct": selected_target,
        "selected_position_size_pct": float(selected["position_size_pct"]),
        "selected_max_positions": int(selected["max_positions"]),
        "hard_risk_limit_pct": float(args.risk_limit_pct),
        "strict_risk_pass": True,
        "train": train_result.summary,
        "validation": validation_result.summary,
        "concentration": concentration,
        "extreme_portfolio_trades_gt_500pct": extreme_trades,
        "artifact_valid": True,
    }

    quality.to_csv(output / "data_quality_report.csv", index=False)
    anomalies.to_csv(output / "price_anomalies.csv", index=False)
    sweep.to_csv(output / "position_sizing_sweep.csv", index=False)
    daily.to_csv(output / "portfolio_daily_equity.csv", index=False)
    annual.to_csv(output / "portfolio_annual_returns.csv", index=False)
    ledger.to_csv(output / "portfolio_trade_ledger.csv", index=False)
    skipped.to_csv(output / "skipped_entries.csv", index=False)
    (output / "strategy_rules.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "signal_diagnostics.json").write_text(json.dumps(signal_diagnostics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "provenance.json").write_text(json.dumps(provenance_payload | {"portfolio_run_hash": run_hash}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "_SUCCESS").write_text(run_hash + "\n", encoding="utf-8")
    return summary


def require_github_actions() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("GTBI clean portfolio evaluation is GitHub Actions only")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--data-pack-root", type=Path, required=True)
    value.add_argument("--strategy-pack-root", type=Path, required=True)
    value.add_argument("--strategy-id", default=DEFAULT_STRATEGY_ID)
    value.add_argument("--output-dir", type=Path, required=True)
    value.add_argument("--source-data-run-id", default="29148013009")
    value.add_argument("--source-artifact-name", default="gtbi-external-pack-data")
    value.add_argument("--train-end", default="2010-12-31")
    value.add_argument("--validation-start", default="2011-01-01")
    value.add_argument("--validation-end", default="2020-12-31")
    value.add_argument("--locked-start", default="2021-01-01")
    value.add_argument("--position-sizes", default=DEFAULT_POSITION_SIZES)
    value.add_argument("--max-positions-grid", default=DEFAULT_MAX_POSITIONS)
    value.add_argument("--initial-capital", type=float, default=1_000_000.0)
    value.add_argument("--risk-limit-pct", type=float, default=25.0)
    value.add_argument("--safety-target-pct", type=float, default=20.0)
    value.add_argument("--transaction-cost-bps-per-side", type=float, default=10.0)
    value.add_argument("--slippage-bps-per-side", type=float, default=5.0)
    value.add_argument("--max-adjusted-gap-ratio", type=float, default=3.0)
    value.add_argument("--min-segment-rows", type=int, default=260)
    value.add_argument("--max-symbols", type=int, default=0)
    value.add_argument("--allow-fractional-shares", action="store_true")
    return value


def main(argv: list[str] | None = None) -> int:
    require_github_actions()
    summary = run(parser().parse_args(argv))
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

