"""Weekly multi-asset hedge search for SP500 down weeks.

Contract:
* only train can choose rules and size;
* validation is report-only;
* locked is not read.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from aurora.core.metrics import compute_metrics
from aurora.core.runtime_paths import base_data_dir
from aurora.data_contracts.timeseries_store import TimeSeriesStore


METHOD = "dehb_real"
WEEKLY_PPY = 52
DEFAULT_SIZE_GRID = tuple(round(x * 0.01, 2) for x in range(0, 501))
FORBIDDEN_TOKENS = ("future", "target", "label", "prediction", "locked")
WAVE_SEED_STRIDE = 100_000_000


@dataclass(frozen=True)
class SP500WeeklyHedgeConfig:
    run_id: str = "sp500_weekly_hedge_all_assets_all_features_dehb_500"
    manifest_path: str = "config/diversified_seed_dataset.yaml"
    train_start: str = "2015-01-01"
    train_end: str = "2022-12-31"
    validation_start: str = "2023-01-01"
    validation_end: str = "2025-12-31"
    locked_start: str = "2026-01-01"
    benchmark_symbol: str = "SPY"
    max_leverage: float = 5.0
    size_grid: tuple[float, ...] = DEFAULT_SIZE_GRID
    min_train_weeks: int = 120
    min_down_weeks: int = 20
    max_features_per_candidate: int = 8
    max_assets_per_candidate: int = 8
    max_feature_columns: int = 5000
    top_rows_per_stage: int = 500
    random_seed: int = 9102601


def run_stage(
    config: SP500WeeklyHedgeConfig,
    *,
    stage: int,
    total_stages: int,
    time_budget_minutes: float,
    wave: int = 0,
    total_waves: int = 1,
    dataset: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    dataset, audit = (dataset, _synthetic_audit()) if dataset is not None else load_dataset(config)
    seed = int(config.random_seed + int(wave) * WAVE_SEED_STRIDE + int(stage) * 100_003)
    rng = np.random.default_rng(seed)
    start = time.monotonic()
    deadline = start + max(0.1, float(time_budget_minutes) * 60.0)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    iteration = 0

    while time.monotonic() < deadline or iteration == 0:
        specs = candidate_specs(dataset, config, stage=stage, total_stages=total_stages, rng=rng, iteration=iteration)
        if not specs:
            break
        for spec in specs:
            if rows and time.monotonic() >= deadline:
                break
            row = evaluate_spec(dataset, config, spec)
            candidate_id = str(row["candidate_id"])
            if candidate_id in seen:
                continue
            seen.add(candidate_id)
            row["stage"] = int(stage)
            row["total_stages"] = int(total_stages)
            row["wave"] = int(wave)
            row["total_waves"] = int(total_waves)
            row["candidates_evaluated"] = int(len(rows) + 1)
            row["elapsed_seconds"] = float(time.monotonic() - start)
            rows.append(row)
        iteration += 1
        if len(rows) > int(config.top_rows_per_stage) * 8:
            rows = sorted(rows, key=lambda item: float(item.get("train_score", -math.inf)), reverse=True)
            rows = rows[: int(config.top_rows_per_stage)]

    rows = sorted(rows, key=lambda item: float(item.get("train_score", -math.inf)), reverse=True)
    rows = rows[: int(config.top_rows_per_stage)]
    meta = {
        "run_id": config.run_id,
        "method": METHOD,
        "wave": int(wave),
        "total_waves": int(total_waves),
        "stage": int(stage),
        "total_stages": int(total_stages),
        "seed": int(seed),
        "rows": len(rows),
        "candidates_unique": len({row["candidate_id"] for row in rows}),
        "time_budget_minutes": float(time_budget_minutes),
        "locked_opened": False,
        "optimization_period": "train",
        "validation_role": "report_only",
        "validation_used_for_selection": False,
        "objective": "gain_or_hold_when_sp500_falls_weekly_and_avoid_losses_when_sp500_rises",
    }
    return rows, meta, audit


def load_dataset(config: SP500WeeklyHedgeConfig) -> tuple[dict[str, Any], dict[str, Any]]:
    repo_root = Path(__file__).resolve().parents[1]
    manifest = yaml.safe_load((repo_root / config.manifest_path).read_text(encoding="utf-8"))
    store = TimeSeriesStore(base_data_dir() / "timeseries")
    tradable_symbols, context_symbols = _symbols_from_manifest(manifest)
    prices, found, missing = _load_price_panels(store, tradable_symbols, end=config.validation_end)
    context, context_found, context_missing = _load_context_panels(store, context_symbols, end=config.validation_end)
    if config.benchmark_symbol not in prices.columns:
        raise ValueError(f"benchmark {config.benchmark_symbol} is required in stored prices")

    weekly_close = prices.resample("W-FRI").last().ffill()
    weekly_returns = weekly_close.pct_change().shift(-1)
    spy_returns = weekly_returns[config.benchmark_symbol].copy()
    features = build_weekly_feature_panel(weekly_close, context)
    features = features.replace([np.inf, -np.inf], np.nan)
    features = features.loc[:, [c for c in features.columns if not _forbidden(c)]]

    train_mask = _between(features.index, config.train_start, config.train_end)
    valid_mask = _between(features.index, config.validation_start, config.validation_end)
    locked_mask = features.index >= pd.Timestamp(config.locked_start)

    train_x = features.loc[train_mask].copy()
    valid_x = features.loc[valid_mask].copy()
    train_rets = weekly_returns.loc[train_x.index].copy()
    valid_rets = weekly_returns.loc[valid_x.index].copy()
    train_spy = spy_returns.loc[train_x.index].copy()
    valid_spy = spy_returns.loc[valid_x.index].copy()
    train_x, valid_x, train_rets, valid_rets, train_spy, valid_spy = _clean_and_align(
        train_x, valid_x, train_rets, valid_rets, train_spy, valid_spy, config
    )

    selected, dropped = _select_usable_features(train_x, train_spy, config)
    train_x = train_x.loc[:, selected]
    valid_x = valid_x.loc[:, selected]
    train_x, valid_x = _impute_and_standardize(train_x, valid_x)

    audit = {
        "manifest": manifest.get("name", "unknown"),
        "tradable_requested": len(tradable_symbols),
        "tradable_found": len(found),
        "tradable_missing": missing,
        "context_found": len(context_found),
        "context_missing": context_missing,
        "assets_used": list(train_rets.columns),
        "features_raw": int(features.shape[1]),
        "features_used": int(len(selected)),
        "feature_columns_used_names": list(selected),
        "dropped_features": dropped,
        "rows_train": int(len(train_x)),
        "rows_validation": int(len(valid_x)),
        "rows_locked_declared": int(np.sum(locked_mask)),
        "locked_opened": False,
        "validation_role": "report_only",
    }
    return {
        "train_x": train_x,
        "valid_x": valid_x,
        "train_asset_returns": train_rets,
        "valid_asset_returns": valid_rets,
        "train_spy_returns": train_spy.to_numpy(dtype=np.float64),
        "valid_spy_returns": valid_spy.to_numpy(dtype=np.float64),
        "train_index": pd.DatetimeIndex(train_x.index),
        "valid_index": pd.DatetimeIndex(valid_x.index),
        "feature_names": tuple(selected),
        "asset_symbols": tuple(train_rets.columns),
    }, audit


def build_weekly_feature_panel(weekly_close: pd.DataFrame, context: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    weekly_ret = weekly_close.pct_change()
    spy_ret = weekly_ret["SPY"] if "SPY" in weekly_ret.columns else weekly_ret.iloc[:, 0]
    for symbol in weekly_close.columns:
        close = weekly_close[symbol].astype(float)
        ret = weekly_ret[symbol].astype(float)
        part = pd.DataFrame(index=weekly_close.index)
        part[f"{symbol}__ret_1w"] = ret
        part[f"{symbol}__ret_4w"] = close.pct_change(4)
        part[f"{symbol}__ret_13w"] = close.pct_change(13)
        part[f"{symbol}__ret_26w"] = close.pct_change(26)
        part[f"{symbol}__vol_4w"] = ret.rolling(4).std()
        part[f"{symbol}__vol_13w"] = ret.rolling(13).std()
        part[f"{symbol}__ma_gap_10w"] = close / close.rolling(10).mean() - 1.0
        part[f"{symbol}__ma_gap_30w"] = close / close.rolling(30).mean() - 1.0
        part[f"{symbol}__drawdown_26w"] = close / close.rolling(26).max() - 1.0
        part[f"{symbol}__corr_spy_13w"] = ret.rolling(13).corr(spy_ret)
        part[f"{symbol}__beta_spy_13w"] = ret.rolling(13).cov(spy_ret) / spy_ret.rolling(13).var()
        frames.append(part)
    if not context.empty:
        weekly_context = context.resample("W-FRI").last().ffill()
        for column in weekly_context.columns:
            s = pd.to_numeric(weekly_context[column], errors="coerce")
            frames.append(
                pd.DataFrame(
                    {
                        f"macro__{column}__level": s,
                        f"macro__{column}__chg_4w": s.diff(4),
                        f"macro__{column}__chg_13w": s.diff(13),
                    },
                    index=weekly_context.index,
                )
            )
    return pd.concat(frames, axis=1).sort_index()


def evaluate_spec(dataset: dict[str, Any], config: SP500WeeklyHedgeConfig, spec: dict[str, Any]) -> dict[str, Any]:
    train_base, train_exposure = returns_for_spec(dataset["train_x"], dataset["train_asset_returns"], spec)
    valid_base, valid_exposure = returns_for_spec(dataset["valid_x"], dataset["valid_asset_returns"], spec)
    size, train_sized = choose_train_size(train_base, dataset["train_spy_returns"], dataset["train_index"], config)
    valid_sized = portfolio_metrics(valid_base, dataset["valid_spy_returns"], dataset["valid_index"], size=size)
    train_1x = portfolio_metrics(train_base, dataset["train_spy_returns"], dataset["train_index"], size=1.0)
    valid_1x = portfolio_metrics(valid_base, dataset["valid_spy_returns"], dataset["valid_index"], size=1.0)
    fail_reason = train_fail_reason(train_sized, config)
    score = hedge_train_score(train_sized) if not fail_reason else -1_000_000.0 + hedge_train_score(train_sized)
    public_spec = {k: v for k, v in spec.items() if not str(k).startswith("_")}
    asset_weights = dict(zip(spec["assets"], spec["asset_weights"]))
    row: dict[str, Any] = {
        "candidate_id": candidate_id_from_spec(public_spec),
        "method": METHOD,
        "source_method": METHOD,
        "rule": json.dumps(public_spec, sort_keys=True, default=str),
        "features": ",".join(spec.get("features", ())),
        "feature_count": int(len(spec.get("features", ()))),
        "assets": ",".join(spec.get("assets", ())),
        "asset_count": int(len(spec.get("assets", ()))),
        "asset_weights": _format_weights(asset_weights),
        "long_gross_weight": float(sum(max(0.0, float(w)) for w in asset_weights.values())),
        "short_gross_weight": float(sum(abs(min(0.0, float(w))) for w in asset_weights.values())),
        "allows_short": any(float(w) < 0.0 for w in asset_weights.values()),
        "threshold": float(spec["threshold"]),
        "position_size": float(size),
        "max_leverage": float(config.max_leverage),
        "train_score": float(score),
        "verified": fail_reason == "",
        "rejection_reason": fail_reason,
        "locked_opened": False,
        "optimization_period": "train",
        "validation_role": "report_only",
        "validation_used_for_selection": False,
        "train_average_abs_exposure": float(np.nanmean(np.abs(train_exposure))) if len(train_exposure) else 0.0,
        "validation_average_abs_exposure": float(np.nanmean(np.abs(valid_exposure))) if len(valid_exposure) else 0.0,
    }
    row.update(_prefix_metrics("train_1x", train_1x))
    row.update(_prefix_metrics("validation_1x", valid_1x))
    row.update(_prefix_metrics("train", train_sized))
    row.update(_prefix_metrics("validation", valid_sized))
    return row


def returns_for_spec(
    features: pd.DataFrame,
    asset_returns: pd.DataFrame,
    spec: dict[str, Any],
) -> tuple[np.ndarray, np.ndarray]:
    selected = list(spec.get("features", ()))
    matrix = features.loc[:, selected].to_numpy(dtype=np.float64)
    signal_weights = np.asarray(spec.get("signal_weights", (1.0,) * len(selected)), dtype=np.float64)
    if len(signal_weights) != len(selected):
        signal_weights = np.ones(len(selected), dtype=np.float64)
    denom = float(np.sum(np.abs(signal_weights)))
    signal_weights = signal_weights / denom if denom > 1e-12 else np.ones(len(selected)) / max(1, len(selected))
    scores = matrix @ signal_weights if len(selected) else np.zeros(len(features), dtype=np.float64)
    threshold = abs(float(spec.get("threshold", 0.0)))
    exposure = np.zeros(len(scores), dtype=np.float64)
    exposure[scores >= threshold] = 1.0
    exposure[scores <= -threshold] = -1.0
    assets = list(spec.get("assets", ()))
    weights = np.asarray(spec.get("asset_weights", (1.0,) * len(assets)), dtype=np.float64)
    if len(weights) != len(assets):
        weights = np.ones(len(assets), dtype=np.float64)
    gross = float(np.sum(np.abs(weights)))
    weights = weights / gross if gross > 1e-12 else np.ones(len(assets)) / max(1, len(assets))
    portfolio_base = asset_returns.loc[:, assets].to_numpy(dtype=np.float64) @ weights if assets else np.zeros(len(features))
    return exposure * portfolio_base, exposure


def choose_train_size(
    base_returns: np.ndarray,
    spy_returns: np.ndarray,
    index: pd.DatetimeIndex,
    config: SP500WeeklyHedgeConfig,
) -> tuple[float, dict[str, float]]:
    best_size = 0.0
    best_metrics = portfolio_metrics(base_returns, spy_returns, index, size=0.0)
    best_score = hedge_train_score(best_metrics)
    for size in config.size_grid:
        size = float(size)
        if size < 0.0 or size > float(config.max_leverage):
            continue
        metrics = portfolio_metrics(base_returns, spy_returns, index, size=size)
        if metrics["min_nav"] <= 0.0 or not np.isfinite(metrics["final_nav"]):
            continue
        score = hedge_train_score(metrics)
        if score > best_score:
            best_size = size
            best_metrics = metrics
            best_score = score
    return best_size, best_metrics


def portfolio_metrics(
    base_returns: np.ndarray,
    spy_returns: np.ndarray,
    index: pd.DatetimeIndex,
    *,
    size: float,
) -> dict[str, float]:
    strategy = np.asarray(base_returns, dtype=np.float64) * float(size)
    spy = np.asarray(spy_returns, dtype=np.float64)
    finite = np.isfinite(strategy) & np.isfinite(spy)
    strategy = strategy[finite]
    spy = spy[finite]
    idx = pd.DatetimeIndex(index[finite])
    if len(strategy) < 2:
        return _empty_metrics()
    nav = np.cumprod(1.0 + strategy)
    metrics = compute_metrics(strategy, ppy=WEEKLY_PPY)
    down = spy < 0.0
    up = spy >= 0.0
    return {
        "cagr": float(metrics.cagr) / 100.0,
        "sharpe": float(metrics.sharpe),
        "calmar": float(metrics.calmar),
        "max_drawdown": float(metrics.mdd) / 100.0,
        "profit_factor": _profit_factor(strategy),
        "win_rate": float(metrics.win_rate),
        "final_nav": float(metrics.final_nav),
        "min_nav": float(np.min(nav)),
        "weeks": float(len(strategy)),
        "weeks_positive_pct": float(np.mean(strategy > 0.0)) if len(strategy) else 0.0,
        "months_positive_pct": _positive_period_pct(strategy, idx, "ME"),
        "years_positive_pct": _positive_period_pct(strategy, idx, "YE"),
        "spy_down_weeks": float(np.sum(down)),
        "spy_up_weeks": float(np.sum(up)),
        "spy_down_total_return": _compound_return(strategy[down]),
        "spy_up_total_return": _compound_return(strategy[up]),
        "spy_down_mean_weekly": float(np.mean(strategy[down])) if np.any(down) else 0.0,
        "spy_up_mean_weekly": float(np.mean(strategy[up])) if np.any(up) else 0.0,
        "spy_down_positive_pct": float(np.mean(strategy[down] > 0.0)) if np.any(down) else 0.0,
        "spy_up_positive_pct": float(np.mean(strategy[up] > 0.0)) if np.any(up) else 0.0,
        "correlation_spy": _safe_corr(pd.Series(strategy), pd.Series(spy)),
        "beta_spy": _beta(strategy, spy),
    }


def hedge_train_score(metrics: dict[str, float]) -> float:
    down_mean = _finite_or(metrics.get("spy_down_mean_weekly"), -1.0)
    up_mean = _finite_or(metrics.get("spy_up_mean_weekly"), -1.0)
    down_hit = _finite_or(metrics.get("spy_down_positive_pct"), 0.0)
    up_hit = _finite_or(metrics.get("spy_up_positive_pct"), 0.0)
    sharpe = _finite_or(metrics.get("sharpe"), -10.0)
    calmar = _finite_or(metrics.get("calmar"), -10.0)
    pf = min(_finite_or(metrics.get("profit_factor"), 0.0), 10.0)
    drawdown = abs(min(_finite_or(metrics.get("max_drawdown"), 0.0), 0.0))
    beta = _finite_or(metrics.get("beta_spy"), 0.0)
    return float(120.0 * down_mean + 70.0 * up_mean + 1.5 * down_hit + 0.8 * up_hit + 0.3 * sharpe + 0.3 * calmar + 0.05 * pf - 1.2 * drawdown - 0.4 * max(beta, 0.0))


def train_fail_reason(metrics: dict[str, float], config: SP500WeeklyHedgeConfig) -> str:
    if metrics["min_nav"] <= 0.0:
        return "train_nav_wipeout"
    if metrics["weeks"] < float(config.min_train_weeks):
        return "train_too_few_weeks"
    if metrics["spy_down_weeks"] < float(config.min_down_weeks):
        return "train_too_few_spy_down_weeks"
    if metrics["spy_down_mean_weekly"] <= 0.0:
        return "train_not_hedging_spy_down_weeks"
    if metrics["spy_up_mean_weekly"] < 0.0:
        return "train_loses_when_spy_rises"
    if metrics["final_nav"] <= 1.0:
        return "train_final_nav"
    if metrics["profit_factor"] <= 1.0:
        return "train_profit_factor"
    return ""


def candidate_specs(
    dataset: dict[str, Any],
    config: SP500WeeklyHedgeConfig,
    *,
    stage: int,
    total_stages: int,
    rng: np.random.Generator,
    iteration: int,
) -> list[dict[str, Any]]:
    feature_names = tuple(dataset["feature_names"])
    asset_symbols = tuple(dataset["asset_symbols"])
    stage_features = tuple(name for idx, name in enumerate(feature_names) if idx % int(total_stages) == int(stage))
    if not stage_features:
        stage_features = feature_names
    ranked_features = _rank_features_for_hedge(dataset, stage_features)
    ranked_assets = _rank_assets_for_hedge(dataset, asset_symbols)
    feature_pool = tuple(dict.fromkeys((*ranked_features[:120], *stage_features[:120])))
    asset_pool = tuple(dict.fromkeys((*ranked_assets[:40], *asset_symbols[:40])))
    if not feature_pool or not asset_pool:
        return []
    specs: list[dict[str, Any]] = []
    for _ in range(72):
        feature_count = int(rng.integers(1, min(config.max_features_per_candidate, len(feature_pool)) + 1))
        asset_count = int(rng.integers(1, min(config.max_assets_per_candidate, len(asset_pool)) + 1))
        features = tuple(rng.choice(feature_pool, size=feature_count, replace=False).tolist())
        assets = tuple(rng.choice(asset_pool, size=asset_count, replace=False).tolist())
        signal_weights = rng.normal(0.0, 1.0, feature_count)
        asset_weights = rng.normal(0.0, 1.0, asset_count)
        if not np.any(asset_weights < 0.0):
            asset_weights[int(rng.integers(0, asset_count))] *= -1.0
        threshold = float(rng.choice([0.0, 0.15, 0.30, 0.50, 0.75, 1.0]))
        specs.append(
            {
                "method": METHOD,
                "route": "weekly_hedge_linear",
                "features": tuple(str(x) for x in features),
                "signal_weights": tuple(float(x) for x in signal_weights),
                "threshold": threshold,
                "assets": tuple(str(x) for x in assets),
                "asset_weights": tuple(float(x) for x in asset_weights),
                "iteration": int(iteration),
                "stage_bucket": int(stage),
                "engine": METHOD,
                "can_short": True,
            }
        )
    return specs


def candidate_id_from_spec(spec: dict[str, Any]) -> str:
    raw = json.dumps(spec, sort_keys=True, default=str, separators=(",", ":"))
    return "sp500_weekly_hedge_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def merge_stage_rows(rows: list[pd.DataFrame]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    merged = pd.concat([frame for frame in rows if not frame.empty], ignore_index=True)
    if merged.empty or "candidate_id" not in merged.columns:
        return merged
    merged = merged.sort_values("train_score", ascending=False)
    return merged.drop_duplicates("candidate_id", keep="first").reset_index(drop=True)


def method_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["method", "rows", "unique_candidates", "verified", "verified_per_1000_unique"])
    unique = int(frame["candidate_id"].nunique()) if "candidate_id" in frame.columns else int(len(frame))
    verified = int(frame.get("verified", pd.Series(dtype=bool)).astype(bool).sum()) if "verified" in frame.columns else 0
    return pd.DataFrame(
        [
            {
                "method": METHOD,
                "rows": int(len(frame)),
                "unique_candidates": unique,
                "verified": verified,
                "verified_per_1000_unique": float(verified / unique * 1000.0) if unique else 0.0,
                "top_train_score": float(pd.to_numeric(frame.get("train_score"), errors="coerce").max()),
                "top_validation_sharpe": float(pd.to_numeric(frame.get("validation_sharpe"), errors="coerce").max()),
                "mean_validation_sharpe": float(pd.to_numeric(frame.get("validation_sharpe"), errors="coerce").mean()),
                "top_train_spy_down_mean_weekly": float(pd.to_numeric(frame.get("train_spy_down_mean_weekly"), errors="coerce").max()),
                "top_validation_spy_down_mean_weekly": float(pd.to_numeric(frame.get("validation_spy_down_mean_weekly"), errors="coerce").max()),
                "locked_opened": False,
            }
        ]
    )


def _symbols_from_manifest(manifest: dict[str, Any]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    tradable: list[tuple[str, str]] = []
    context: list[tuple[str, str]] = []
    for section in manifest.get("sections", {}).values():
        library = str(section.get("library", ""))
        for symbol in section.get("symbols", []):
            item = (library, str(symbol))
            if library in {"prices_daily", "fx_daily", "crypto_daily"}:
                tradable.append(item)
            elif library == "macro_daily":
                context.append(item)
    return tradable, context


def _load_price_panels(
    store: TimeSeriesStore,
    symbols: list[tuple[str, str]],
    *,
    end: str,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    frames: list[pd.Series] = []
    found: list[str] = []
    missing: list[str] = []
    for library, symbol in symbols:
        try:
            frame = store.read(library, symbol, end=end)
        except Exception:
            missing.append(f"{library}/{symbol}")
            continue
        close_col = "close" if "close" in frame.columns else "adj_close" if "adj_close" in frame.columns else None
        if close_col is None:
            missing.append(f"{library}/{symbol}:no_close")
            continue
        series = pd.to_numeric(frame[close_col], errors="coerce").rename(symbol)
        series.index = pd.to_datetime(series.index).tz_localize(None)
        frames.append(series)
        found.append(symbol)
    if not frames:
        raise ValueError("no tradable price series found in TimeSeriesStore")
    return pd.concat(frames, axis=1).sort_index(), found, missing


def _load_context_panels(
    store: TimeSeriesStore,
    symbols: list[tuple[str, str]],
    *,
    end: str,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    frames: list[pd.Series] = []
    found: list[str] = []
    missing: list[str] = []
    for library, symbol in symbols:
        try:
            frame = store.read(library, symbol, end=end)
        except Exception:
            missing.append(f"{library}/{symbol}")
            continue
        column = "value" if "value" in frame.columns else frame.columns[0]
        series = pd.to_numeric(frame[column], errors="coerce").rename(symbol)
        series.index = pd.to_datetime(series.index).tz_localize(None)
        frames.append(series)
        found.append(symbol)
    if not frames:
        return pd.DataFrame(), found, missing
    return pd.concat(frames, axis=1).sort_index(), found, missing


def _clean_and_align(
    train_x: pd.DataFrame,
    valid_x: pd.DataFrame,
    train_rets: pd.DataFrame,
    valid_rets: pd.DataFrame,
    train_spy: pd.Series,
    valid_spy: pd.Series,
    config: SP500WeeklyHedgeConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    assets = [c for c in train_rets.columns if train_rets[c].notna().sum() >= config.min_train_weeks]
    train_rets = train_rets.loc[:, assets]
    valid_rets = valid_rets.loc[:, assets]
    train_rets = train_rets.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    valid_rets = valid_rets.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    mask_train = np.isfinite(train_spy.to_numpy(dtype=float))
    mask_valid = np.isfinite(valid_spy.to_numpy(dtype=float))
    return (
        train_x.loc[mask_train],
        valid_x.loc[mask_valid],
        train_rets.loc[mask_train],
        valid_rets.loc[mask_valid],
        train_spy.loc[mask_train],
        valid_spy.loc[mask_valid],
    )


def _select_usable_features(
    train_x: pd.DataFrame,
    train_spy: pd.Series,
    config: SP500WeeklyHedgeConfig,
) -> tuple[tuple[str, ...], dict[str, list[str]]]:
    dropped = {"forbidden": [], "too_sparse": [], "constant": []}
    usable: list[str] = []
    for column in train_x.columns:
        if _forbidden(column):
            dropped["forbidden"].append(str(column))
            continue
        series = pd.to_numeric(train_x[column], errors="coerce")
        if int(series.notna().sum()) < int(config.min_train_weeks):
            dropped["too_sparse"].append(str(column))
            continue
        if float(series.std(skipna=True) or 0.0) <= 1e-12:
            dropped["constant"].append(str(column))
            continue
        usable.append(str(column))
    if len(usable) > int(config.max_feature_columns):
        y = pd.to_numeric(train_spy, errors="coerce")
        scored = []
        for column in usable:
            joined = pd.concat([train_x[column], y], axis=1).dropna()
            score = abs(float(joined.iloc[:, 0].corr(joined.iloc[:, 1]) or 0.0)) if len(joined) else 0.0
            scored.append((score, column))
        usable = [column for _, column in sorted(scored, reverse=True)[: int(config.max_feature_columns)]]
    if not usable:
        raise ValueError("no usable weekly hedge features after train-only audit")
    return tuple(usable), dropped


def _impute_and_standardize(train: pd.DataFrame, valid: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    med = train.median(axis=0, skipna=True).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    train_filled = train.replace([np.inf, -np.inf], np.nan).fillna(med).fillna(0.0)
    valid_filled = valid.replace([np.inf, -np.inf], np.nan).fillna(med).fillna(0.0)
    mean = train_filled.mean(axis=0)
    std = train_filled.std(axis=0).replace(0.0, 1.0).fillna(1.0)
    return (train_filled - mean) / std, (valid_filled - mean) / std


def _rank_features_for_hedge(dataset: dict[str, Any], features: tuple[str, ...]) -> list[str]:
    spy = pd.Series(dataset["train_spy_returns"], index=dataset["train_x"].index)
    down = spy < 0.0
    scores = []
    for feature in features:
        series = dataset["train_x"][feature]
        down_score = abs(_safe_corr(series.loc[down], spy.loc[down])) if down.any() else 0.0
        all_score = abs(_safe_corr(series, spy))
        scores.append((down_score + 0.25 * all_score, feature))
    return [feature for _, feature in sorted(scores, reverse=True)]


def _rank_assets_for_hedge(dataset: dict[str, Any], assets: tuple[str, ...]) -> list[str]:
    spy = pd.Series(dataset["train_spy_returns"], index=dataset["train_asset_returns"].index)
    down = spy < 0.0
    scores = []
    for asset in assets:
        ret = dataset["train_asset_returns"][asset]
        down_mean = float(ret.loc[down].mean()) if down.any() else 0.0
        up_mean = float(ret.loc[~down].mean()) if (~down).any() else 0.0
        short_down_mean = float((-ret).loc[down].mean()) if down.any() else 0.0
        score = max(down_mean, short_down_mean) + 0.25 * abs(up_mean)
        scores.append((score, asset))
    return [asset for _, asset in sorted(scores, reverse=True)]


def _prefix_metrics(prefix: str, metrics: dict[str, float]) -> dict[str, float]:
    return {f"{prefix}_{key}": value for key, value in metrics.items() if key != "min_nav"}


def _empty_metrics() -> dict[str, float]:
    return {
        "cagr": float("nan"),
        "sharpe": float("nan"),
        "calmar": float("nan"),
        "max_drawdown": float("nan"),
        "profit_factor": 0.0,
        "win_rate": 0.0,
        "final_nav": float("nan"),
        "min_nav": float("nan"),
        "weeks": 0.0,
        "weeks_positive_pct": 0.0,
        "months_positive_pct": 0.0,
        "years_positive_pct": 0.0,
        "spy_down_weeks": 0.0,
        "spy_up_weeks": 0.0,
        "spy_down_total_return": 0.0,
        "spy_up_total_return": 0.0,
        "spy_down_mean_weekly": 0.0,
        "spy_up_mean_weekly": 0.0,
        "spy_down_positive_pct": 0.0,
        "spy_up_positive_pct": 0.0,
        "correlation_spy": 0.0,
        "beta_spy": 0.0,
    }


def _profit_factor(returns: np.ndarray) -> float:
    arr = np.asarray(returns, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    gains = float(arr[arr > 0.0].sum())
    losses = float(arr[arr < 0.0].sum())
    if abs(losses) > 1e-15:
        return gains / abs(losses)
    return float("inf") if gains > 0.0 else 0.0


def _positive_period_pct(returns: np.ndarray, index: pd.DatetimeIndex, freq: str) -> float:
    if len(returns) == 0:
        return 0.0
    series = pd.Series(returns, index=index)
    grouped = series.groupby(pd.Grouper(freq=freq)).apply(lambda x: float(np.prod(1.0 + x) - 1.0))
    grouped = grouped.dropna()
    return float((grouped > 0.0).mean()) if len(grouped) else 0.0


def _compound_return(returns: np.ndarray) -> float:
    arr = np.asarray(returns, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return 0.0
    return float(np.prod(1.0 + arr) - 1.0)


def _beta(strategy: np.ndarray, spy: np.ndarray) -> float:
    variance = float(np.var(spy))
    if variance <= 1e-15:
        return 0.0
    return float(np.cov(strategy, spy)[0, 1] / variance)


def _safe_corr(left: pd.Series, right: pd.Series) -> float:
    joined = pd.concat([pd.to_numeric(left, errors="coerce"), pd.to_numeric(right, errors="coerce")], axis=1).dropna()
    if len(joined) < 2:
        return 0.0
    if float(joined.iloc[:, 0].std() or 0.0) <= 1e-15:
        return 0.0
    if float(joined.iloc[:, 1].std() or 0.0) <= 1e-15:
        return 0.0
    value = float(joined.iloc[:, 0].corr(joined.iloc[:, 1]) or 0.0)
    return value if np.isfinite(value) else 0.0


def _finite_or(value: Any, fallback: float) -> float:
    try:
        out = float(value)
    except Exception:
        return fallback
    return out if np.isfinite(out) else fallback


def _between(index: pd.DatetimeIndex, start: str, end: str) -> np.ndarray:
    idx = pd.DatetimeIndex(index)
    return (idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))


def _forbidden(column: object) -> bool:
    lower = str(column).lower()
    return any(token in lower for token in FORBIDDEN_TOKENS)


def _format_weights(weights: dict[str, float]) -> str:
    return ",".join(f"{symbol}:{float(weight):.6g}" for symbol, weight in sorted(weights.items()))


def _synthetic_audit() -> dict[str, Any]:
    return {
        "manifest": "synthetic_smoke",
        "tradable_requested": 3,
        "tradable_found": 3,
        "tradable_missing": [],
        "context_found": 1,
        "context_missing": [],
        "locked_opened": False,
        "validation_role": "report_only",
    }
