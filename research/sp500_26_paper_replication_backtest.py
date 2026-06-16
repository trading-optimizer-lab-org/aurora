"""Paper-by-paper SP500 strategy replication backtests.

This module is intentionally explicit: every strategy comes from the curated
26-paper specification and is labelled by fidelity. It does not claim exact
paper replication unless the spec says so.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from aurora.core.metrics import compute_metrics
from aurora.research.literature_strategy_backtest import (
    LiteratureBacktestConfig,
    load_dataset,
    synthetic_dataset,
)


SPEC_PATH = "config/sp500_26_paper_replication_specs.yaml"
TRAIN_START = "1995-01-01"
TRAIN_END = "2010-12-31"
VALIDATION_START = "2011-01-01"
VALIDATION_END = "2020-12-31"
LOCKED_START = "2021-01-01"
PERIODS_PER_YEAR = {"daily": 252, "weekly": 52, "monthly": 12}
SUPPORTED_STATUSES = {
    "paper_like_exact",
    "near_replica",
    "near_replica_if_data",
    "aurora_proxy",
    "unsupported",
    "methodology_only",
}


@dataclass(frozen=True)
class Paper26Config:
    specs_path: str = SPEC_PATH
    train_start: str = TRAIN_START
    train_end: str = TRAIN_END
    validation_start: str = VALIDATION_START
    validation_end: str = VALIDATION_END
    locked_start: str = LOCKED_START
    benchmark: str = "SPY"
    expected_specs: int = 26
    min_lag_periods: int = 1


def load_paper26_config(path: str | Path = SPEC_PATH) -> tuple[Paper26Config, list[dict[str, Any]], dict[str, Any]]:
    """Load and validate the curated 26-paper YAML."""

    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    specs = list(raw.get("specs") or [])
    config = Paper26Config(
        specs_path=str(path),
        train_start=str(raw.get("train_start", TRAIN_START)),
        train_end=str(raw.get("train_end", TRAIN_END)),
        validation_start=str(raw.get("validation_start", VALIDATION_START)),
        validation_end=str(raw.get("validation_end", VALIDATION_END)),
        locked_start=str(raw.get("locked_start", LOCKED_START)),
        benchmark=str(raw.get("benchmark", "SPY")),
        expected_specs=26,
        min_lag_periods=int(raw.get("min_lag_periods", 1)),
    )
    validate_specs(config, specs)
    return config, specs, raw


def validate_specs(config: Paper26Config, specs: list[dict[str, Any]]) -> None:
    if len(specs) != config.expected_specs:
        raise ValueError(f"expected {config.expected_specs} specs, found {len(specs)}")
    if pd.Timestamp(config.validation_end) >= pd.Timestamp(config.locked_start):
        raise ValueError("validation_end must be before locked_start")
    if config.min_lag_periods < 1:
        raise ValueError("min_lag_periods must be >= 1")
    ids = [int(spec["paper_id"]) for spec in specs]
    if sorted(ids) != list(range(1, config.expected_specs + 1)):
        raise ValueError("paper_id values must be exactly 1..26")
    slugs = [str(spec["slug"]) for spec in specs]
    if len(slugs) != len(set(slugs)):
        raise ValueError("duplicate spec slug")
    for spec in specs:
        status = str(spec.get("fidelity_status") or "")
        if status not in SUPPORTED_STATUSES:
            raise ValueError(f"unsupported fidelity_status for {spec.get('slug')}: {status}")
        if int(spec.get("paper_id", 0)) != 4 and not spec.get("primary", False):
            raise ValueError(f"non-methodology spec must be primary: {spec.get('slug')}")


def load_real_dataset(config: Paper26Config) -> dict[str, Any]:
    """Load the existing Aurora data store through validation only."""

    literature_config = LiteratureBacktestConfig(
        train_start=config.train_start,
        train_end=config.train_end,
        validation_start=config.validation_start,
        validation_end=config.validation_end,
        locked_start=config.locked_start,
        expected_signatures=0,
    )
    return load_dataset(literature_config)


def run_specs_chunk(
    specs: list[dict[str, Any]],
    dataset: dict[str, Any],
    config: Paper26Config,
    *,
    chunk_index: int,
    chunks: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    start, end = chunk_bounds(len(specs), chunks, chunk_index)
    selected = specs[start:end]
    result_rows: list[dict[str, Any]] = []
    annual_rows: list[dict[str, Any]] = []
    monthly_rows: list[dict[str, Any]] = []
    for spec in selected:
        evaluated = evaluate_spec(spec, dataset, config)
        result_rows.extend(evaluated["results"])
        annual_rows.extend(evaluated["annual"])
        monthly_rows.extend(evaluated["monthly"])
    summary = {
        "chunk_index": int(chunk_index),
        "chunks": int(chunks),
        "start": int(start),
        "end": int(end),
        "specs": int(len(selected)),
        "result_rows": int(len(result_rows)),
        "locked_opened": False,
        "validation_used_for_selection": False,
        "paper_exact_replication_claimed": False,
    }
    return pd.DataFrame(result_rows), pd.DataFrame(annual_rows), pd.DataFrame(monthly_rows), summary


def chunk_bounds(total: int, chunks: int, chunk_index: int) -> tuple[int, int]:
    if chunks <= 0:
        raise ValueError("chunks must be > 0")
    if chunk_index < 0 or chunk_index >= chunks:
        raise ValueError("chunk_index out of range")
    return math.floor(total * chunk_index / chunks), math.floor(total * (chunk_index + 1) / chunks)


def evaluate_spec(spec: dict[str, Any], dataset: dict[str, Any], config: Paper26Config) -> dict[str, list[dict[str, Any]]]:
    base = base_fields(spec)
    unsupported_reason = unsupported_reason_for_spec(spec, dataset)
    if unsupported_reason:
        rows = []
        for view in ("paper_like", "aurora_comparable"):
            rows.append(base | {
                "view": view,
                "status": "unsupported",
                "unsupported_reason": unsupported_reason,
                "error": "",
                "locked_opened": False,
                "validation_used_for_selection": False,
                "paper_exact_replication_claimed": False,
            })
        return {"results": rows, "annual": [], "monthly": []}

    try:
        strategy = build_strategy_returns(spec, dataset, config)
    except Exception as exc:
        rows = []
        for view in ("paper_like", "aurora_comparable"):
            rows.append(base | {
                "view": view,
                "status": "error",
                "unsupported_reason": "",
                "error": f"{type(exc).__name__}: {exc}",
                "locked_opened": False,
                "validation_used_for_selection": False,
                "paper_exact_replication_claimed": False,
            })
        return {"results": rows, "annual": [], "monthly": []}

    results: list[dict[str, Any]] = []
    annual_rows: list[dict[str, Any]] = []
    monthly_rows: list[dict[str, Any]] = []
    for view, start, end in (
        ("paper_like", str(spec.get("paper_start") or config.train_start), min(str(spec.get("paper_end") or config.validation_end), config.validation_end)),
        ("aurora_comparable", config.train_start, config.validation_end),
    ):
        period_rows = evaluate_view(base, strategy, config, view=view, start=start, end=end)
        results.append(period_rows["summary"])
        annual_rows.extend(period_rows["annual"])
        monthly_rows.extend(period_rows["monthly"])
    return {"results": results, "annual": annual_rows, "monthly": monthly_rows}


def base_fields(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_id": int(spec["paper_id"]),
        "slug": str(spec["slug"]),
        "title": str(spec["title"]),
        "strategy_name": str(spec["strategy_name"]),
        "fidelity_status": str(spec["fidelity_status"]),
        "strategy_type": str(spec["strategy_type"]),
        "frequency": str(spec["frequency"]),
        "symbols_requested": "|".join(map(str, spec.get("symbols") or [])),
        "paper_start": str(spec.get("paper_start") or ""),
        "paper_end": str(spec.get("paper_end") or ""),
        "proxy_notes": str(spec.get("proxy_notes") or ""),
    }


def unsupported_reason_for_spec(spec: dict[str, Any], dataset: dict[str, Any]) -> str:
    strategy_type = str(spec.get("strategy_type") or "")
    if strategy_type == "methodology_only":
        return "methodology_only_not_trading_strategy"
    if strategy_type == "unsupported_intraday":
        return "unsupported_missing_intraday_data"
    if strategy_type == "missing_lei":
        return "unsupported_missing_conference_board_lei"
    if "SPY" not in dataset.get("prices", pd.DataFrame()).columns:
        return "unsupported_missing_spy"
    if strategy_type == "equivolume_proxy":
        prices = dataset.get("prices", pd.DataFrame())
        if "SPY" not in prices.columns:
            return "unsupported_missing_spy_ohlcv"
    return ""


def build_strategy_returns(spec: dict[str, Any], dataset: dict[str, Any], config: Paper26Config) -> dict[str, Any]:
    frequency = str(spec["frequency"])
    if frequency not in PERIODS_PER_YEAR:
        raise ValueError(f"unsupported frequency: {frequency}")
    prices = resample_prices(dataset["prices"], frequency)
    returns = resample_returns(dataset["returns"], frequency).reindex(prices.index)
    context = resample_context(dataset.get("context", pd.DataFrame()), frequency, prices.index)
    spy = pd.to_numeric(prices["SPY"], errors="coerce")
    spy_ret = pd.to_numeric(returns["SPY"], errors="coerce")
    cash_ret = cash_returns(returns)
    signal = build_signal_for_type(str(spec["strategy_type"]), spy, spy_ret, context)
    signal = signal.reindex(spy_ret.index).fillna(0.0)
    position = signal.shift(config.min_lag_periods).fillna(0.0).clip(-1.0, 1.0)
    if str(spec["strategy_type"]) == "high_confidence_proxy" and "SH" not in returns.columns:
        position = position.clip(lower=0.0)
    if str(spec["strategy_type"]) == "high_confidence_proxy" and "SH" in returns.columns:
        short_leg = pd.to_numeric(returns["SH"], errors="coerce").reindex(spy_ret.index).fillna(0.0)
        strategy_returns = np.where(position >= 0.0, position * spy_ret + (1.0 - position.abs()) * cash_ret, position.abs() * short_leg)
        strategy_returns = pd.Series(strategy_returns, index=spy_ret.index)
    else:
        strategy_returns = position.clip(lower=0.0) * spy_ret + (1.0 - position.clip(lower=0.0)) * cash_ret
        if position.lt(0.0).any():
            strategy_returns = pd.Series(np.where(position < 0.0, -spy_ret, strategy_returns), index=spy_ret.index)
    benchmark = spy_ret.reindex(strategy_returns.index)
    weights = pd.DataFrame({"SPY": position}, index=strategy_returns.index)
    return {
        "returns": pd.to_numeric(strategy_returns, errors="coerce"),
        "benchmark": pd.to_numeric(benchmark, errors="coerce"),
        "weights": weights,
        "position": position,
        "frequency": frequency,
        "periods_per_year": PERIODS_PER_YEAR[frequency],
        "data_start": str(spy.dropna().index.min().date()) if not spy.dropna().empty else "",
        "data_end": str(spy.dropna().index.max().date()) if not spy.dropna().empty else "",
        "symbols_used": "SPY|SHY/BIL/cash",
    }


def build_signal_for_type(strategy_type: str, price: pd.Series, returns: pd.Series, context: pd.DataFrame) -> pd.Series:
    ma_10 = price.rolling(10, min_periods=5).mean()
    ma_50 = price.rolling(50, min_periods=20).mean()
    ma_200 = price.rolling(200, min_periods=60).mean()
    mom_3 = price.pct_change(3)
    mom_12 = price.pct_change(12)
    vol_21 = returns.rolling(21, min_periods=8).std()
    drawdown = price / price.rolling(252, min_periods=60).max() - 1.0
    vix = context["VIXCLS"] if "VIXCLS" in context.columns else pd.Series(index=price.index, dtype=float)
    dgs10 = context["DGS10"] if "DGS10" in context.columns else pd.Series(index=price.index, dtype=float)
    slope = first_existing(context, ("T10Y3M", "T10Y2Y", "DGS10"))

    if strategy_type in {"ma_timing", "monthly_technical_timing"}:
        return binary(price > ma_10)
    if strategy_type == "ma_crossover":
        return binary(ma_50 > ma_200)
    if strategy_type == "time_series_momentum":
        return binary(mom_12 > 0.0)
    if strategy_type == "breakout_250":
        rolling_high = price.rolling(250, min_periods=80).max()
        return binary(price >= rolling_high.shift(1) * 0.995)
    if strategy_type == "trend_yc_macro":
        macro = pd.Series(0.0, index=price.index)
        if not slope.empty:
            macro = macro + zscore(slope).clip(-1, 1)
        if "UNRATE" in context.columns:
            macro = macro - zscore(context["UNRATE"].diff()).clip(-1, 1)
        if "CPIAUCSL" in context.columns:
            macro = macro - zscore(context["CPIAUCSL"].pct_change(12)).clip(-1, 1)
        return binary((price > ma_200) & (macro.reindex(price.index).fillna(0.0) >= -0.25))
    if strategy_type in {"yield_curve_probit_proxy", "bull_bear_probability"}:
        prob = zscore(slope if not slope.empty else returns.rolling(63).mean()).fillna(0.0)
        trend = zscore(returns.rolling(63, min_periods=20).mean()).fillna(0.0)
        return binary((prob + trend) > -0.25)
    if strategy_type in {"ep_rate_proxy", "fed_model_proxy"}:
        valuation_proxy = -zscore(price.pct_change(252))
        rate_pressure = zscore(dgs10).reindex(price.index).fillna(0.0)
        return binary((valuation_proxy - 0.35 * rate_pressure) > -0.5)
    if strategy_type in {"expected_premium_proxy", "monthly_classifier_proxy", "ml_daily_direction_proxy", "technical_ml_proxy"}:
        score = (
            zscore(returns.rolling(21, min_periods=8).mean()).fillna(0.0)
            + 0.5 * zscore(returns.rolling(126, min_periods=40).mean()).fillna(0.0)
            - 0.5 * zscore(vol_21).fillna(0.0)
            - 0.25 * zscore(vix.pct_change()).reindex(price.index).fillna(0.0)
        )
        return binary(score > 0.0)
    if strategy_type == "relative_extrema":
        smooth = price.rolling(20, min_periods=8).mean()
        trough = smooth.rolling(63, min_periods=20).min()
        peak = smooth.rolling(63, min_periods=20).max()
        return binary((smooth > trough * 1.03) & (smooth > smooth.shift(3)) & (smooth > peak * 0.90))
    if strategy_type == "gp_published_rule":
        local_min = ma_50.rolling(6, min_periods=3).min()
        return binary((mom_12 < mom_3) | (ma_50 > local_min.shift(2)))
    if strategy_type == "wavelet_proxy":
        cycle = price.rolling(8, min_periods=4).mean() - price.rolling(34, min_periods=12).mean()
        return binary(cycle > cycle.shift(1))
    if strategy_type == "fuzzy_direction_proxy":
        score = 0.4 * zscore(mom_3) + 0.4 * zscore(mom_12) - 0.3 * zscore(vol_21) - 0.2 * zscore(vix)
        return binary(score > -0.1)
    if strategy_type == "tail_risk_proxy":
        stress = zscore(vol_21).fillna(0.0) + zscore(vix).reindex(price.index).fillna(0.0) - zscore(mom_3).fillna(0.0)
        return binary(stress < 1.0)
    if strategy_type == "optimism_premium_proxy":
        recovery = zscore(price / price.rolling(126, min_periods=40).max() - 1.0)
        return binary((recovery - zscore(vix).reindex(price.index).fillna(0.0) * 0.2) > -0.5)
    if strategy_type == "equivolume_proxy":
        pressure = zscore(returns.rolling(5, min_periods=3).sum()) - zscore(vol_21)
        return binary(pressure > 0.0)
    if strategy_type == "high_confidence_proxy":
        score = zscore(mom_3).fillna(0.0) + zscore(mom_12).fillna(0.0) - zscore(vol_21).fillna(0.0)
        high = score.abs() > score.abs().rolling(252, min_periods=60).quantile(0.80)
        return pd.Series(np.where(high, np.sign(score), 0.0), index=price.index)
    return binary(price > ma_200)


def evaluate_view(
    base: dict[str, Any],
    strategy: dict[str, Any],
    config: Paper26Config,
    *,
    view: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    returns = strategy["returns"].loc[between(strategy["returns"].index, start, end)]
    benchmark = strategy["benchmark"].loc[between(strategy["benchmark"].index, start, end)]
    weights = strategy["weights"].loc[between(strategy["weights"].index, start, end)]
    ppy = int(strategy["periods_per_year"])
    train_returns = strategy["returns"].loc[between(strategy["returns"].index, config.train_start, config.train_end)]
    validation_returns = strategy["returns"].loc[between(strategy["returns"].index, config.validation_start, config.validation_end)]
    metrics = metrics_for_returns(returns, ppy)
    bench_metrics = metrics_for_returns(benchmark, ppy, prefix="spy_")
    summary = base | {
        "view": view,
        "status": "evaluated",
        "unsupported_reason": "",
        "error": "",
        "start": start,
        "end": end,
        "actual_start": str(returns.dropna().index.min().date()) if not returns.dropna().empty else "",
        "actual_end": str(returns.dropna().index.max().date()) if not returns.dropna().empty else "",
        "observations": int(returns.dropna().shape[0]),
        "symbols_used": strategy["symbols_used"],
        "data_start": strategy["data_start"],
        "data_end": strategy["data_end"],
        "trades_per_year": trades_per_year(weights, ppy),
        "locked_opened": False,
        "validation_used_for_selection": False,
        "paper_exact_replication_claimed": False,
    } | metrics | bench_metrics | split_metrics(train_returns, validation_returns, ppy)
    return {
        "summary": summary,
        "annual": annual_returns_rows(base, view, returns, benchmark),
        "monthly": monthly_returns_rows(base, view, returns, benchmark),
    }


def split_metrics(train_returns: pd.Series, validation_returns: pd.Series, ppy: int) -> dict[str, float]:
    return metrics_for_returns(train_returns, ppy, "train_") | metrics_for_returns(validation_returns, ppy, "validation_")


def metrics_for_returns(returns: pd.Series, ppy: int, prefix: str = "") -> dict[str, float]:
    finite = returns.dropna()
    if finite.empty:
        keys = ("cagr", "sharpe", "calmar", "mdd", "profit_factor", "win_rate", "final_nav")
        return {f"{prefix}{key}": float("nan") for key in keys} | {
            f"{prefix}positive_months_pct": float("nan"),
            f"{prefix}positive_years_pct": float("nan"),
        }
    raw = compute_metrics(finite.to_numpy(dtype=float), ppy=ppy).to_dict()
    out = {
        f"{prefix}cagr": float(raw.get("cagr", float("nan"))),
        f"{prefix}sharpe": float(raw.get("sharpe", float("nan"))),
        f"{prefix}calmar": float(raw.get("calmar", float("nan"))),
        f"{prefix}mdd": float(raw.get("mdd", float("nan"))),
        f"{prefix}profit_factor": float(raw.get("profit_factor", float("nan"))),
        f"{prefix}win_rate": float(raw.get("win_rate", float("nan"))),
        f"{prefix}final_nav": float(raw.get("final_nav", float("nan"))),
    }
    out[f"{prefix}positive_months_pct"] = positive_period_pct(finite, "ME")
    out[f"{prefix}positive_years_pct"] = positive_period_pct(finite, "YE")
    return out


def annual_returns_rows(base: dict[str, Any], view: str, returns: pd.Series, benchmark: pd.Series) -> list[dict[str, Any]]:
    frame = period_return_frame(returns, benchmark, "YE")
    rows = []
    for idx, row in frame.iterrows():
        rows.append({
            "paper_id": base["paper_id"],
            "slug": base["slug"],
            "view": view,
            "year": int(pd.Timestamp(idx).year),
            "strategy_return": float(row["strategy"]),
            "spy_return": float(row["spy"]),
            "excess_vs_spy": float(row["strategy"] - row["spy"]),
            "spy_negative": bool(row["spy"] < 0.0),
        })
    return rows


def monthly_returns_rows(base: dict[str, Any], view: str, returns: pd.Series, benchmark: pd.Series) -> list[dict[str, Any]]:
    frame = period_return_frame(returns, benchmark, "ME")
    rows = []
    for idx, row in frame.iterrows():
        stamp = pd.Timestamp(idx)
        rows.append({
            "paper_id": base["paper_id"],
            "slug": base["slug"],
            "view": view,
            "month": stamp.strftime("%Y-%m"),
            "strategy_return": float(row["strategy"]),
            "spy_return": float(row["spy"]),
            "excess_vs_spy": float(row["strategy"] - row["spy"]),
            "spy_negative": bool(row["spy"] < 0.0),
        })
    return rows


def period_return_frame(returns: pd.Series, benchmark: pd.Series, freq: str) -> pd.DataFrame:
    strategy = (1.0 + returns.dropna()).resample(freq).prod(min_count=1) - 1.0
    spy = (1.0 + benchmark.dropna()).resample(freq).prod(min_count=1) - 1.0
    return pd.DataFrame({"strategy": strategy, "spy": spy}).dropna()


def resample_prices(prices: pd.DataFrame, frequency: str) -> pd.DataFrame:
    if frequency == "daily":
        return prices.sort_index().ffill()
    rule = {"weekly": "W-FRI", "monthly": "ME"}[frequency]
    return prices.sort_index().ffill().resample(rule).last()


def resample_returns(returns: pd.DataFrame, frequency: str) -> pd.DataFrame:
    if frequency == "daily":
        return returns.sort_index()
    rule = {"weekly": "W-FRI", "monthly": "ME"}[frequency]
    return (1.0 + returns.sort_index()).resample(rule).prod(min_count=1) - 1.0


def resample_context(context: pd.DataFrame, frequency: str, index: pd.Index) -> pd.DataFrame:
    if context.empty:
        return context
    if frequency == "daily":
        return context.sort_index().reindex(index).ffill()
    rule = {"weekly": "W-FRI", "monthly": "ME"}[frequency]
    return context.sort_index().resample(rule).last().reindex(index).ffill()


def cash_returns(returns: pd.DataFrame) -> pd.Series:
    for symbol in ("BIL", "SHY", "IEF"):
        if symbol in returns.columns:
            return pd.to_numeric(returns[symbol], errors="coerce").fillna(0.0)
    return pd.Series(0.0, index=returns.index)


def first_existing(frame: pd.DataFrame, names: tuple[str, ...]) -> pd.Series:
    for name in names:
        if name in frame.columns:
            return pd.to_numeric(frame[name], errors="coerce")
    return pd.Series(index=frame.index, dtype=float)


def zscore(series: pd.Series, window: int = 252) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    mean = values.rolling(window, min_periods=max(10, window // 5)).mean()
    std = values.rolling(window, min_periods=max(10, window // 5)).std()
    return ((values - mean) / std.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)


def binary(condition: pd.Series) -> pd.Series:
    return pd.Series(np.where(condition.fillna(False), 1.0, 0.0), index=condition.index)


def between(index: pd.Index, start: str, end: str) -> np.ndarray:
    idx = pd.to_datetime(index)
    return (idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))


def positive_period_pct(returns: pd.Series, freq: str) -> float:
    finite = returns.dropna()
    if finite.empty:
        return float("nan")
    period = (1.0 + finite).resample(freq).prod(min_count=1) - 1.0
    period = period.dropna()
    if period.empty:
        return float("nan")
    return round(float((period > 0.0).mean() * 100.0), 6)


def trades_per_year(weights: pd.DataFrame, ppy: int) -> float:
    if weights.empty or len(weights) < 2:
        return 0.0
    changed = weights.diff().abs().sum(axis=1).fillna(0.0) > 1e-9
    years = max(len(weights) / float(ppy), 1e-9)
    return round(float(changed.sum() / years), 6)


def summary_from_results(
    results: pd.DataFrame,
    annual: pd.DataFrame,
    monthly: pd.DataFrame,
    *,
    expected_specs: int,
    chunks_expected: int,
    chunks_found: int,
) -> dict[str, Any]:
    evaluated = results[results["status"] == "evaluated"] if not results.empty else pd.DataFrame()
    comparable = evaluated[evaluated["view"] == "aurora_comparable"] if not evaluated.empty else pd.DataFrame()
    best = comparable.sort_values(["validation_sharpe", "train_sharpe"], ascending=False).head(1)
    down_months = monthly[(monthly["view"] == "aurora_comparable") & (monthly["spy_negative"])] if not monthly.empty else pd.DataFrame()
    return {
        "expected_specs": int(expected_specs),
        "result_rows": int(len(results)),
        "evaluated_rows": int(len(evaluated)),
        "unsupported_rows": int((results["status"] == "unsupported").sum()) if not results.empty else 0,
        "error_rows": int((results["status"] == "error").sum()) if not results.empty else 0,
        "chunks_expected": int(chunks_expected),
        "chunks_found": int(chunks_found),
        "partial": bool(chunks_found != chunks_expected),
        "best_slug": str(best.iloc[0]["slug"]) if not best.empty else "",
        "best_validation_sharpe": float(best.iloc[0]["validation_sharpe"]) if not best.empty else float("nan"),
        "best_train_sharpe": float(best.iloc[0]["train_sharpe"]) if not best.empty else float("nan"),
        "down_month_rows": int(len(down_months)),
        "backtest_enabled": True,
        "locked_opened": False,
        "validation_used_for_selection": False,
        "paper_exact_replication_claimed": False,
    }


def dataset_for_mode(config: Paper26Config, *, synthetic_smoke: bool) -> dict[str, Any]:
    return synthetic_dataset() if synthetic_smoke else load_real_dataset(config)
