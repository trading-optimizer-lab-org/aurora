"""GitHub-only clean portfolio and position-size evaluation for one GTBI strategy."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping

import numpy as np
import pandas as pd

from scripts import global_technical_buy_indicator as gtbi
from scripts.gtbi_clean_portfolio import (
    DataQualityPolicy,
    MAX_TERMINAL_MARK_DAYS,
    PortfolioConfig,
    choose_train_selected_result,
    prepare_signal_portfolio_data,
    sanitize_symbol_prices,
    simulate_prepared_signal_portfolio,
)


ENGINE_VERSION = "gtbi_clean_portfolio_v7"
DEFAULT_STRATEGY_ID = "lhv1_2f6eb0c50f_fam_00_v1004"
CANONICAL_TRAIN_START = "1993-01-01"
CANONICAL_TRAIN_END = "2010-12-31"
CANONICAL_VALIDATION_START = "2011-01-01"
CANONICAL_VALIDATION_END = "2020-12-31"
CANONICAL_LOCKED_START = "2021-01-01"
DEFAULT_POSITION_SIZES = "0.001,0.0025,0.005,0.0075,0.01,0.0125,0.0135,0.015,0.02,0.025,0.03,0.04,0.05"
DEFAULT_MAX_POSITIONS = "10,20,30,50"
DEFAULT_PRIORITY_LOOKBACK = 63


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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


def provenance_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sanitized_universe_identity(frames: Mapping[str, pd.DataFrame]) -> str:
    manifest = []
    for symbol, frame in sorted(frames.items()):
        index = pd.DatetimeIndex(frame.index)
        manifest.append(
            {
                "symbol": str(symbol),
                "rows": int(len(frame)),
                "first_date": pd.Timestamp(index.min()).date().isoformat() if len(index) else None,
                "last_date": pd.Timestamp(index.max()).date().isoformat() if len(index) else None,
                "original_symbol": str(frame["original_symbol"].iloc[0])
                if len(frame) and "original_symbol" in frame.columns
                else str(symbol).split("::segment_", 1)[0],
            }
        )
    return provenance_hash({"segments": manifest})


def build_relative_strength_priorities(
    frames: Mapping[str, pd.DataFrame],
    benchmark: pd.DataFrame,
    *,
    lookback: int = DEFAULT_PRIORITY_LOOKBACK,
) -> dict[str, pd.Series]:
    if lookback < 1:
        raise ValueError("priority lookback must be positive")
    benchmark_close = pd.to_numeric(benchmark["close"], errors="coerce").sort_index()
    benchmark_return = benchmark_close / benchmark_close.shift(lookback) - 1.0
    priorities: dict[str, pd.Series] = {}
    for symbol, frame in frames.items():
        stock_close = pd.to_numeric(frame["close"], errors="coerce").sort_index()
        stock_return = stock_close / stock_close.shift(lookback) - 1.0
        aligned_benchmark = benchmark_return.reindex(
            stock_return.index,
            method="ffill",
            tolerance=pd.Timedelta(days=MAX_TERMINAL_MARK_DAYS),
        )
        priorities[str(symbol)] = (stock_return - aligned_benchmark).replace([np.inf, -np.inf], np.nan)
    return priorities


def build_provenance_payload(
    *,
    args: argparse.Namespace,
    strategy_payload: Mapping[str, Any],
    source_file_hashes: Mapping[str, str],
    position_sizes: list[float],
    max_positions_grid: list[int],
    policy: DataQualityPolicy,
    universe_identity: str,
    code_sha: str,
) -> dict[str, Any]:
    return {
        "engine_version": ENGINE_VERSION,
        "code_sha": str(code_sha),
        "source_data_run_id": str(args.source_data_run_id),
        "source_artifact_name": str(args.source_artifact_name),
        "source_file_hashes": dict(source_file_hashes),
        "strategy_id": str(args.strategy_id),
        "strategy_payload": dict(strategy_payload),
        "train_start": str(args.train_start),
        "train_end": str(args.train_end),
        "validation_start": str(args.validation_start),
        "validation_end": str(args.validation_end),
        "locked_start": str(args.locked_start),
        "position_sizes": list(position_sizes),
        "max_positions_grid": list(max_positions_grid),
        "initial_capital": float(args.initial_capital),
        "risk_limit_pct": float(args.risk_limit_pct),
        "safety_target_pct": float(args.safety_target_pct),
        "transaction_cost_bps_per_side": float(args.transaction_cost_bps_per_side),
        "slippage_bps_per_side": float(args.slippage_bps_per_side),
        "allow_fractional_shares": bool(args.allow_fractional_shares),
        "max_gross_exposure": 1.0,
        "data_quality_policy": asdict(policy),
        "max_symbols": int(args.max_symbols),
        "priority_lookback_days": int(args.priority_lookback_days),
        "priority_method": f"relative_strength_{int(args.priority_lookback_days)}d_at_signal_close",
        "selection_method": "train_only_max_cagr_with_predeclared_risk_target",
        "sanitized_universe_identity": str(universe_identity),
        "benchmark_start_tolerance_days": 31,
        "maximum_benchmark_gap_days": MAX_TERMINAL_MARK_DAYS,
        "maximum_terminal_mark_days": MAX_TERMINAL_MARK_DAYS,
    }


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
    if os.environ.get("GITHUB_ACTIONS") == "true":
        if not re.fullmatch(r"[0-9a-fA-F]{40}", value):
            raise RuntimeError("GITHUB_SHA must contain the exact GitHub commit")
        return value
    if value:
        return value
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def validate_canonical_dates(
    *,
    train_start: str,
    train_end: str,
    validation_start: str,
    validation_end: str,
    locked_start: str,
) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    supplied = (train_start, train_end, validation_start, validation_end, locked_start)
    canonical = (
        CANONICAL_TRAIN_START,
        CANONICAL_TRAIN_END,
        CANONICAL_VALIDATION_START,
        CANONICAL_VALIDATION_END,
        CANONICAL_LOCKED_START,
    )
    if supplied != canonical:
        raise ValueError(f"dates must match the canonical train/validation/locked boundaries: {canonical}")
    parsed = tuple(pd.Timestamp(value) for value in supplied)
    if not parsed[0] <= parsed[1] < parsed[2] <= parsed[3] < parsed[4]:
        raise ValueError("canonical dates are not strictly separated")
    return parsed


def validate_benchmark_coverage(
    benchmark: pd.DataFrame,
    *,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
) -> None:
    if len(benchmark.index) == 0 or not isinstance(benchmark.index, pd.DatetimeIndex):
        raise ValueError("SPY benchmark does not cover the evaluation period")
    start_date = pd.Timestamp(start)
    end_date = pd.Timestamp(end)
    first = pd.Timestamp(benchmark.index.min())
    last = pd.Timestamp(benchmark.index.max())
    start_tolerance = pd.Timedelta(days=31)
    if first > start_date + start_tolerance or last < end_date:
        raise ValueError(
            f"SPY benchmark does not cover {start_date.date()} through {end_date.date()}: "
            f"available {first.date()} through {last.date()}"
        )
    dates = pd.DatetimeIndex(benchmark.index).sort_values().unique()
    dates = dates[(dates >= start_date) & (dates <= end_date)]
    if len(dates) < 2:
        raise ValueError("SPY benchmark does not cover the evaluation period continuously")
    maximum_gap_days = int(pd.Series(dates).diff().dt.days.max())
    if maximum_gap_days > MAX_TERMINAL_MARK_DAYS:
        raise ValueError(
            "SPY benchmark does not cover the evaluation period continuously; "
            f"maximum internal gap is {maximum_gap_days} days"
        )


def period_covering_segments(
    segments: Mapping[str, pd.DataFrame],
    *,
    end: str | pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    end_date = pd.Timestamp(end)
    earliest_acceptable = end_date - pd.Timedelta(days=MAX_TERMINAL_MARK_DAYS)
    return {
        str(symbol): frame
        for symbol, frame in sorted(segments.items())
        if len(frame.index) and pd.Timestamp(frame.index.max()) >= earliest_acceptable
    }


def _sanitize_pack(
    *,
    data_pack_root: Path,
    locked_start: str,
    policy: DataQualityPolicy,
    max_symbols: int,
    benchmark_start: str,
    benchmark_end: str,
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
        eligible_segments = period_covering_segments(result.segments, end=benchmark_end)
        frames.update(eligible_segments)
        diagnostic = dict(result.diagnostics)
        diagnostic["segments_rejected_no_period_end_coverage"] = int(
            len(result.segments) - len(eligible_segments)
        )
        diagnostic["segments_kept"] = int(len(eligible_segments))
        diagnostic["usable_rows"] = int(sum(len(frame) for frame in eligible_segments.values()))
        diagnostic["excluded"] = not bool(eligible_segments)
        diagnostics.append(diagnostic)
        if not result.anomalies.empty:
            anomalies.append(result.anomalies)
    del prices

    benchmark_raw = pd.read_parquet(benchmark_path)
    benchmark_policy = DataQualityPolicy(
        max_adjusted_gap_ratio=policy.max_adjusted_gap_ratio,
        min_segment_rows=min(policy.min_segment_rows, max(len(benchmark_raw), 2)),
        min_split_adjustment_ratio=policy.min_split_adjustment_ratio,
        max_calendar_gap_days=policy.max_calendar_gap_days,
    )
    benchmark_result = sanitize_symbol_prices(
        benchmark_raw,
        symbol="SPY",
        locked_start=locked_start,
        policy=benchmark_policy,
    )
    if not benchmark_result.segments:
        raise ValueError("SPY benchmark has no clean segment")
    covering_segments = []
    for segment in benchmark_result.segments.values():
        try:
            validate_benchmark_coverage(segment, start=benchmark_start, end=benchmark_end)
        except ValueError:
            continue
        covering_segments.append(segment)
    if not covering_segments:
        raise ValueError("SPY benchmark has no continuous clean segment covering train and validation")
    benchmark = max(covering_segments, key=len).copy()
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
    row = _train_sweep_row(
        position_size=position_size,
        max_positions=max_positions,
        train_result=train_result,
    )
    for field in RESULT_SUMMARY_FIELDS:
        row[f"validation_{field}"] = validation_result.summary[field]
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


RESULT_SUMMARY_FIELDS = (
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
)


def _train_sweep_row(*, position_size: float, max_positions: int, train_result: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "position_size_pct": float(position_size),
        "max_positions": int(max_positions),
    }
    for field in RESULT_SUMMARY_FIELDS:
        row[f"train_{field}"] = train_result.summary[field]
    return row


def run(args: argparse.Namespace) -> dict[str, Any]:
    require_github_actions()
    code_sha = _git_sha()
    validate_canonical_dates(
        train_start=args.train_start,
        train_end=args.train_end,
        validation_start=args.validation_start,
        validation_end=args.validation_end,
        locked_start=args.locked_start,
    )
    output = Path(args.output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    policy = DataQualityPolicy(
        max_adjusted_gap_ratio=float(args.max_adjusted_gap_ratio),
        min_segment_rows=int(args.min_segment_rows),
        min_split_adjustment_ratio=float(args.min_split_adjustment_ratio),
        max_calendar_gap_days=int(args.max_calendar_gap_days),
    )
    data_pack_root = Path(args.data_pack_root)
    source_file_hashes = {
        "prices.parquet": _sha256_file(data_pack_root / "prices.parquet"),
        "benchmark.parquet": _sha256_file(data_pack_root / "benchmark.parquet"),
    }
    frames, benchmark, quality, anomalies = _sanitize_pack(
        data_pack_root=data_pack_root,
        locked_start=args.locked_start,
        policy=policy,
        max_symbols=int(args.max_symbols),
        benchmark_start=args.train_start,
        benchmark_end=args.validation_end,
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
    priority_scores = build_relative_strength_priorities(
        frames,
        benchmark,
        lookback=int(args.priority_lookback_days),
    )
    signal_diagnostics["entry_priority_method"] = (
        f"relative_strength_{int(args.priority_lookback_days)}d_at_signal_close"
    )
    train_data = prepare_signal_portfolio_data(
        signals,
        frames,
        market_exit_signals=market_exits,
        priority_scores=priority_scores,
        start=args.train_start,
        end=args.train_end,
        indicator_config=candidate.config,
    )
    validation_data = prepare_signal_portfolio_data(
        signals,
        frames,
        market_exit_signals=market_exits,
        priority_scores=priority_scores,
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
            sweep_rows.append(
                _train_sweep_row(
                    position_size=position_size,
                    max_positions=max_positions,
                    train_result=train_result,
                )
            )
    sweep = pd.DataFrame(sweep_rows)
    try:
        selected = choose_train_selected_result(sweep, risk_limit_pct=float(args.safety_target_pct))
        selected_target = float(args.safety_target_pct)
    except ValueError:
        selected = choose_train_selected_result(sweep, risk_limit_pct=float(args.risk_limit_pct))
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
    selected_evaluation = _sweep_row(
        position_size=float(selected["position_size_pct"]),
        max_positions=int(selected["max_positions"]),
        train_result=train_result,
        validation_result=validation_result,
        risk_limit_pct=float(args.risk_limit_pct),
    )
    sweep["selected_from_train"] = (
        np.isclose(sweep["position_size_pct"], float(selected["position_size_pct"]))
        & sweep["max_positions"].eq(int(selected["max_positions"]))
    )
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
    ledger["candidate_id"] = str(args.strategy_id)
    annual["candidate_id"] = str(args.strategy_id)
    daily["candidate_id"] = str(args.strategy_id)
    skipped = pd.concat(
        [train_result.skipped_entries.assign(split="train"), validation_result.skipped_entries.assign(split="validation")],
        ignore_index=True,
    )
    if not skipped.empty:
        skipped["candidate_id"] = str(args.strategy_id)
    validate_selected_result(
        selected_evaluation,
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
    provenance_payload = build_provenance_payload(
        args=args,
        strategy_payload=payload,
        source_file_hashes=source_file_hashes,
        position_sizes=position_sizes,
        max_positions_grid=max_positions_grid,
        policy=policy,
        universe_identity=sanitized_universe_identity(frames),
        code_sha=code_sha,
    )
    run_hash = provenance_hash(provenance_payload)
    validation_concentration = concentration["validation"]
    data_quality_pass = bool(extreme_trades == 0)
    robustness_pass = bool(
        validation_concentration["top_trade_positive_pnl_share"] <= 0.25
        and validation_concentration["top_symbol_positive_pnl_share"] <= 0.25
        and validation_concentration["return_without_top_10_trades_pct"] > 0.0
    )
    validation_profitability_pass = bool(validation_result.summary["cagr_pct"] > 0.0)
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
        "data_quality_pass": data_quality_pass,
        "robustness_pass": robustness_pass,
        "validation_profitability_pass": validation_profitability_pass,
        "strategy_quality_pass": bool(data_quality_pass and robustness_pass and validation_profitability_pass),
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
    value.add_argument("--train-start", default=CANONICAL_TRAIN_START)
    value.add_argument("--train-end", default=CANONICAL_TRAIN_END)
    value.add_argument("--validation-start", default=CANONICAL_VALIDATION_START)
    value.add_argument("--validation-end", default=CANONICAL_VALIDATION_END)
    value.add_argument("--locked-start", default=CANONICAL_LOCKED_START)
    value.add_argument("--position-sizes", default=DEFAULT_POSITION_SIZES)
    value.add_argument("--max-positions-grid", default=DEFAULT_MAX_POSITIONS)
    value.add_argument("--initial-capital", type=float, default=1_000_000.0)
    value.add_argument("--risk-limit-pct", type=float, default=25.0)
    value.add_argument("--safety-target-pct", type=float, default=20.0)
    value.add_argument("--transaction-cost-bps-per-side", type=float, default=10.0)
    value.add_argument("--slippage-bps-per-side", type=float, default=5.0)
    value.add_argument("--max-adjusted-gap-ratio", type=float, default=3.0)
    value.add_argument("--min-segment-rows", type=int, default=260)
    value.add_argument("--min-split-adjustment-ratio", type=float, default=1.1)
    value.add_argument("--max-calendar-gap-days", type=int, default=14)
    value.add_argument("--priority-lookback-days", type=int, default=DEFAULT_PRIORITY_LOOKBACK)
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
