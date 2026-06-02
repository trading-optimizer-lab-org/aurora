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
    train_start: str = "1995-01-01"
    train_end: str = "2010-12-31"
    validation_start: str = "2011-01-01"
    validation_end: str = "2020-12-31"
    locked_start: str = "2021-01-01"
    benchmark_symbol: str = "SPY"
    max_leverage: float = 5.0
    size_grid: tuple[float, ...] = DEFAULT_SIZE_GRID
    allow_late_entry: bool = True
    min_train_weeks: int = 260
    min_down_weeks: int = 80
    min_crash_weeks: int = 25
    min_down_positive_pct: float = 0.52
    min_crash_positive_pct: float = 0.45
    min_up_mean_weekly: float = -0.0005
    max_train_beta_spy: float = 0.50
    max_train_correlation_spy: float = 0.60
    max_features_per_candidate: int = 8
    max_assets_per_candidate: int = 8
    max_feature_columns: int = 5000
    top_rows_per_stage: int = 500
    random_seed: int = 9102601
    exclude_asset_groups: tuple[str, ...] = ()


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
        "objective": "maximize_convex_protection_on_negative_sp500_weeks_with_acceptable_cost_on_positive_weeks",
        "train_start": config.train_start,
        "train_end": config.train_end,
        "validation_start": config.validation_start,
        "validation_end": config.validation_end,
        "locked_start": config.locked_start,
        "allow_late_entry": bool(config.allow_late_entry),
        "excluded_asset_groups": list(config.exclude_asset_groups),
    }
    return rows, meta, audit


def load_dataset(config: SP500WeeklyHedgeConfig) -> tuple[dict[str, Any], dict[str, Any]]:
    repo_root = Path(__file__).resolve().parents[1]
    manifest = yaml.safe_load((repo_root / config.manifest_path).read_text(encoding="utf-8"))
    store = TimeSeriesStore(base_data_dir() / "timeseries")
    tradable_symbols, context_symbols, excluded = _symbols_from_manifest(manifest, config.exclude_asset_groups)
    prices, found, missing = _load_price_panels(store, tradable_symbols, start=config.train_start, end=config.validation_end)
    context, context_found, context_missing = _load_context_panels(store, context_symbols, start=config.train_start, end=config.validation_end)
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

    feature_available = features.notna()
    train_x = features.loc[train_mask].copy()
    valid_x = features.loc[valid_mask].copy()
    train_feature_available = feature_available.loc[train_mask].copy()
    valid_feature_available = feature_available.loc[valid_mask].copy()
    train_rets = weekly_returns.loc[train_x.index].copy()
    valid_rets = weekly_returns.loc[valid_x.index].copy()
    train_spy = spy_returns.loc[train_x.index].copy()
    valid_spy = spy_returns.loc[valid_x.index].copy()
    train_x, valid_x, train_rets, valid_rets, train_spy, valid_spy, train_feature_available, valid_feature_available = _clean_and_align(
        train_x,
        valid_x,
        train_rets,
        valid_rets,
        train_spy,
        valid_spy,
        config,
        train_feature_available,
        valid_feature_available,
    )

    selected, dropped = _select_usable_features(train_x, train_spy, config)
    train_x = train_x.loc[:, selected]
    valid_x = valid_x.loc[:, selected]
    train_x, valid_x = _impute_and_standardize(train_x, valid_x)
    train_x.attrs["availability_mask"] = train_feature_available.loc[:, selected]
    valid_x.attrs["availability_mask"] = valid_feature_available.loc[:, selected]

    audit = {
        "manifest": manifest.get("name", "unknown"),
        "tradable_requested": len(tradable_symbols),
        "tradable_found": len(found),
        "tradable_missing": missing,
        "excluded_asset_groups": list(config.exclude_asset_groups),
        "excluded_symbols": excluded,
        "excluded_symbols_count": int(len(excluded)),
        "context_found": len(context_found),
        "context_missing": context_missing,
        "assets_used": list(train_rets.columns),
        "assets_used_count": int(len(train_rets.columns)),
        "features_raw": int(features.shape[1]),
        "features_used": int(len(selected)),
        "feature_columns_used_names": list(selected),
        "dropped_features": dropped,
        "rows_train": int(len(train_x)),
        "rows_validation": int(len(valid_x)),
        "rows_locked_declared": int(np.sum(locked_mask)),
        "locked_opened": False,
        "validation_role": "report_only",
        "train_start": config.train_start,
        "train_end": config.train_end,
        "validation_start": config.validation_start,
        "validation_end": config.validation_end,
        "locked_start": config.locked_start,
        "allow_late_entry": bool(config.allow_late_entry),
        "crypto_used": False if "crypto_spot" in set(config.exclude_asset_groups) else None,
        "single_name_equities_used": False if "equity_single_name" in set(config.exclude_asset_groups) else None,
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
    score = downside_hedge_score(train_sized) if not fail_reason else -1_000_000.0 + downside_hedge_score(train_sized)
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
        "train_downside_hedge_score": float(downside_hedge_score(train_sized)),
        "verified": fail_reason == "",
        "rejection_reason": fail_reason,
        "locked_opened": False,
        "optimization_period": "train",
        "validation_role": "report_only",
        "validation_used_for_selection": False,
        "train_average_abs_exposure": float(np.nanmean(np.abs(train_exposure))) if len(train_exposure) else 0.0,
        "validation_average_abs_exposure": float(np.nanmean(np.abs(valid_exposure))) if len(valid_exposure) else 0.0,
        "effective_start": _effective_start(dataset["train_index"], dataset["valid_index"], train_base, valid_base),
        "effective_train_weeks": int(np.isfinite(train_base).sum()),
        "effective_validation_weeks": int(np.isfinite(valid_base).sum()),
        "effective_spy_down_weeks_train": int(train_sized.get("spy_down_weeks", 0.0)),
        "late_entry_assets": _late_entry_assets(dataset["train_index"], dataset["train_asset_returns"], spec),
        "train_returns_json": _returns_json(train_base * float(size)),
        "validation_returns_json": _returns_json(valid_base * float(size)),
        "train_spy_returns_json": _returns_json(dataset["train_spy_returns"]),
        "validation_spy_returns_json": _returns_json(dataset["valid_spy_returns"]),
        "train_index_json": _index_json(dataset["train_index"]),
        "validation_index_json": _index_json(dataset["valid_index"]),
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
    feature_available = features.attrs.get("availability_mask")
    if isinstance(feature_available, pd.DataFrame) and selected:
        feature_mask = feature_available.loc[:, selected].all(axis=1).to_numpy(dtype=bool)
    else:
        feature_mask = features.loc[:, selected].notna().all(axis=1).to_numpy(dtype=bool) if selected else np.ones(len(features), dtype=bool)
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
    if assets:
        asset_frame = asset_returns.loc[:, assets]
        asset_mask = asset_frame.notna().all(axis=1).to_numpy(dtype=bool)
        portfolio_base = asset_frame.to_numpy(dtype=np.float64) @ weights
    else:
        asset_mask = np.ones(len(features), dtype=bool)
        portfolio_base = np.zeros(len(features))
    valid = feature_mask & asset_mask & np.isfinite(portfolio_base) & np.isfinite(exposure)
    strategy = exposure * portfolio_base
    strategy = np.where(valid, strategy, np.nan)
    exposure = np.where(valid, exposure, np.nan)
    return strategy, exposure


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
    crash = _crash_mask(spy)
    negative_years = _negative_sp500_year_metrics(strategy, spy, idx)
    down_weighted = _weighted_down_mean(strategy, spy)
    crash_weeks = float(np.sum(crash))
    crash_mean = float(np.mean(strategy[crash])) if np.any(crash) else 0.0
    crash_positive = float(np.mean(strategy[crash] > 0.0)) if np.any(crash) else 0.0
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
        "spy_down_weighted_mean_weekly": down_weighted,
        "down_weighted_mean_weekly": down_weighted,
        "spy_up_mean_weekly": float(np.mean(strategy[up])) if np.any(up) else 0.0,
        "spy_down_positive_pct": float(np.mean(strategy[down] > 0.0)) if np.any(down) else 0.0,
        "spy_up_positive_pct": float(np.mean(strategy[up] > 0.0)) if np.any(up) else 0.0,
        "spy_crash_weeks": crash_weeks,
        "crash_weeks": crash_weeks,
        "spy_crash_mean_weekly": crash_mean,
        "crash_mean_weekly": crash_mean,
        "spy_crash_positive_pct": crash_positive,
        "crash_positive_pct": crash_positive,
        "negative_sp500_years": float(negative_years["negative_sp500_years"]),
        "negative_sp500_years_win_pct": float(negative_years["negative_sp500_years_win_pct"]),
        "negative_sp500_years_positive_pct": float(negative_years["negative_sp500_years_positive_pct"]),
        "correlation_spy": _safe_corr(pd.Series(strategy), pd.Series(spy)),
        "beta_spy": _beta(strategy, spy),
    }


def downside_hedge_score(metrics: dict[str, float]) -> float:
    down_weighted = _finite_or(metrics.get("spy_down_weighted_mean_weekly"), -1.0)
    crash_mean = _finite_or(metrics.get("spy_crash_mean_weekly"), -1.0)
    down_hit = _finite_or(metrics.get("spy_down_positive_pct"), 0.0)
    crash_hit = _finite_or(metrics.get("spy_crash_positive_pct"), 0.0)
    negative_win = _finite_or(metrics.get("negative_sp500_years_win_pct"), 0.0)
    negative_positive = _finite_or(metrics.get("negative_sp500_years_positive_pct"), 0.0)
    up_mean = _finite_or(metrics.get("spy_up_mean_weekly"), -1.0)
    drawdown = abs(min(_finite_or(metrics.get("max_drawdown"), 0.0), 0.0))
    beta = _finite_or(metrics.get("beta_spy"), 0.0)
    corr = _finite_or(metrics.get("correlation_spy"), 0.0)
    return float(
        220.0 * down_weighted
        + 140.0 * crash_mean
        + 2.0 * down_hit
        + 2.5 * crash_hit
        + 1.5 * negative_win
        + 1.0 * negative_positive
        + 40.0 * min(up_mean, 0.002)
        - 120.0 * abs(min(up_mean, 0.0))
        - 1.5 * drawdown
        - 0.8 * max(beta, 0.0)
        - 0.5 * max(corr, 0.0)
    )


def hedge_train_score(metrics: dict[str, float]) -> float:
    return downside_hedge_score(metrics)


def train_fail_reason(metrics: dict[str, float], config: SP500WeeklyHedgeConfig) -> str:
    if metrics["min_nav"] <= 0.0:
        return "train_nav_wipeout"
    if metrics["weeks"] < float(config.min_train_weeks):
        return "train_too_few_weeks"
    if metrics["spy_down_weeks"] < float(config.min_down_weeks):
        return "train_too_few_spy_down_weeks"
    if metrics["spy_crash_weeks"] < float(config.min_crash_weeks):
        return "train_too_few_crash_weeks"
    if metrics["spy_down_mean_weekly"] <= 0.0:
        return "train_not_positive_on_spy_down_weeks"
    if metrics["spy_crash_mean_weekly"] < 0.0:
        return "train_not_positive_on_crash_weeks"
    if metrics["spy_down_weighted_mean_weekly"] <= 0.0:
        return "train_not_positive_weighted_spy_down_weeks"
    if metrics["spy_down_positive_pct"] < float(config.min_down_positive_pct):
        return "train_down_hit_rate_low"
    if metrics["spy_crash_positive_pct"] < float(config.min_crash_positive_pct):
        return "train_crash_hit_rate_low"
    if metrics["spy_up_mean_weekly"] < float(config.min_up_mean_weekly):
        return "train_loses_too_much_when_spy_up"
    if metrics["final_nav"] <= 1.0:
        return "train_final_nav"
    if metrics["profit_factor"] <= 1.0:
        return "train_profit_factor"
    if metrics["beta_spy"] > float(config.max_train_beta_spy):
        return "train_beta_too_positive"
    if metrics["correlation_spy"] > float(config.max_train_correlation_spy):
        return "train_correlation_too_high"
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


def generate_subperiod_report(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for payload in _iter_return_payloads(frame):
        for name, start, end, period in _subperiod_specs():
            mask = (payload["index"] >= pd.Timestamp(start)) & (payload["index"] <= pd.Timestamp(end))
            if not np.any(mask):
                continue
            metrics = portfolio_metrics(payload["strategy"][mask], payload["spy"][mask], payload["index"][mask], size=1.0)
            rows.append(
                {
                    "candidate_id": payload["candidate_id"],
                    "period": period,
                    "subperiod": name,
                    "start": start,
                    "end": end,
                    **_prefix_metrics("", metrics),
                }
            )
    return pd.DataFrame(rows)


def generate_negative_sp500_years_report(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for payload in _iter_return_payloads(frame):
        strategy = pd.Series(payload["strategy"], index=payload["index"])
        spy = pd.Series(payload["spy"], index=payload["index"])
        for year, spy_year in spy.groupby(spy.index.year):
            sp500_return = _compound_return(spy_year.to_numpy(dtype=np.float64))
            if sp500_return >= 0.0:
                continue
            strat_year = strategy.loc[strategy.index.year == year]
            strategy_return = _compound_return(strat_year.to_numpy(dtype=np.float64))
            year_metrics = portfolio_metrics(
                strat_year.to_numpy(dtype=np.float64),
                spy_year.to_numpy(dtype=np.float64),
                pd.DatetimeIndex(strat_year.index),
                size=1.0,
            )
            rows.append(
                {
                    "candidate_id": payload["candidate_id"],
                    "period": "train" if int(year) <= 2010 else "validation",
                    "year": int(year),
                    "sp500_return": float(sp500_return),
                    "strategy_return": float(strategy_return),
                    "excess_vs_sp500": float(strategy_return - sp500_return),
                    "strategy_positive": bool(strategy_return > 0.0),
                    "beats_sp500": bool(strategy_return > sp500_return),
                    "max_drawdown_in_year": float(year_metrics["max_drawdown"]),
                    "weeks_positive_pct": float(year_metrics["weeks_positive_pct"]),
                    "spy_down_weeks": float(year_metrics["spy_down_weeks"]),
                    "spy_down_mean_weekly": float(year_metrics["spy_down_mean_weekly"]),
                    "spy_down_positive_pct": float(year_metrics["spy_down_positive_pct"]),
                }
            )
    return pd.DataFrame(rows)


def build_hedge_rankings(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if frame.empty:
        return {name: frame.copy() for name in _ranking_names()}
    data = frame.copy()
    for column in (
        "train_downside_hedge_score",
        "train_spy_down_mean_weekly",
        "train_spy_down_weighted_mean_weekly",
        "train_spy_crash_mean_weekly",
        "train_negative_sp500_years_win_pct",
        "train_spy_up_mean_weekly",
    ):
        if column not in data.columns:
            data[column] = 0.0
    verified = data[data["verified"].astype(bool)].copy() if "verified" in data.columns else data.copy()
    strict = verified[
        (verified["train_spy_down_mean_weekly"] > 0.0)
        & (verified["train_spy_down_weighted_mean_weekly"] > 0.0)
        & (verified["train_spy_crash_mean_weekly"] >= 0.0)
    ].copy()
    return {
        "balanced_hedge_ranking": verified.sort_values("train_downside_hedge_score", ascending=False),
        "best_down_weeks": verified.sort_values(["train_spy_down_weighted_mean_weekly", "train_spy_down_mean_weekly"], ascending=False),
        "best_crash_weeks": verified.sort_values(["train_spy_crash_mean_weekly", "train_spy_crash_positive_pct"], ascending=False),
        "best_negative_years": verified.sort_values(["train_negative_sp500_years_win_pct", "train_negative_sp500_years_positive_pct"], ascending=False),
        "lowest_cost_when_spy_up": verified.sort_values("train_spy_up_mean_weekly", ascending=False),
        "strict_hedge_pass": strict.sort_values("train_downside_hedge_score", ascending=False),
    }


def _ranking_names() -> tuple[str, ...]:
    return (
        "balanced_hedge_ranking",
        "best_down_weeks",
        "best_crash_weeks",
        "best_negative_years",
        "lowest_cost_when_spy_up",
        "strict_hedge_pass",
    )


def _symbols_from_manifest(
    manifest: dict[str, Any],
    exclude_asset_groups: tuple[str, ...] | list[str] | set[str] = (),
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[str]]:
    tradable: list[tuple[str, str]] = []
    context: list[tuple[str, str]] = []
    excluded: list[str] = []
    excluded_groups = {str(group) for group in exclude_asset_groups}
    for section in manifest.get("sections", {}).values():
        library = str(section.get("library", ""))
        asset_group = str(section.get("asset_group", ""))
        for symbol in section.get("symbols", []):
            item = (library, str(symbol))
            if asset_group in excluded_groups:
                excluded.append(f"{asset_group}/{library}/{symbol}")
                continue
            if library in {"prices_daily", "fx_daily", "crypto_daily"}:
                tradable.append(item)
            elif library == "macro_daily":
                context.append(item)
    return tradable, context, excluded


def _load_price_panels(
    store: TimeSeriesStore,
    symbols: list[tuple[str, str]],
    *,
    start: str,
    end: str,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    frames: list[pd.Series] = []
    found: list[str] = []
    missing: list[str] = []
    for library, symbol in symbols:
        try:
            frame = store.read(library, symbol, start=start, end=end)
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
    start: str,
    end: str,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    frames: list[pd.Series] = []
    found: list[str] = []
    missing: list[str] = []
    for library, symbol in symbols:
        try:
            frame = store.read(library, symbol, start=start, end=end)
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
    train_feature_available: pd.DataFrame,
    valid_feature_available: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, pd.DataFrame, pd.DataFrame]:
    assets = [c for c in train_rets.columns if train_rets[c].notna().sum() >= config.min_train_weeks]
    train_rets = train_rets.loc[:, assets]
    valid_rets = valid_rets.loc[:, assets]
    train_rets = train_rets.replace([np.inf, -np.inf], np.nan)
    valid_rets = valid_rets.replace([np.inf, -np.inf], np.nan)
    mask_train = np.isfinite(train_spy.to_numpy(dtype=float))
    mask_valid = np.isfinite(valid_spy.to_numpy(dtype=float))
    return (
        train_x.loc[mask_train],
        valid_x.loc[mask_valid],
        train_rets.loc[mask_train],
        valid_rets.loc[mask_valid],
        train_spy.loc[mask_train],
        valid_spy.loc[mask_valid],
        train_feature_available.loc[mask_train],
        valid_feature_available.loc[mask_valid],
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
    if not prefix:
        return {key: value for key, value in metrics.items() if key != "min_nav"}
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
        "spy_down_weighted_mean_weekly": 0.0,
        "down_weighted_mean_weekly": 0.0,
        "spy_up_mean_weekly": 0.0,
        "spy_down_positive_pct": 0.0,
        "spy_up_positive_pct": 0.0,
        "spy_crash_weeks": 0.0,
        "crash_weeks": 0.0,
        "spy_crash_mean_weekly": 0.0,
        "crash_mean_weekly": 0.0,
        "spy_crash_positive_pct": 0.0,
        "crash_positive_pct": 0.0,
        "negative_sp500_years": 0.0,
        "negative_sp500_years_win_pct": 0.0,
        "negative_sp500_years_positive_pct": 0.0,
        "correlation_spy": 0.0,
        "beta_spy": 0.0,
    }


def _crash_mask(spy: np.ndarray) -> np.ndarray:
    arr = np.asarray(spy, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return np.zeros(len(spy), dtype=bool)
    threshold = min(0.0, float(np.quantile(arr, 0.20)))
    return np.asarray(spy, dtype=np.float64) <= threshold


def _weighted_down_mean(strategy: np.ndarray, spy: np.ndarray) -> float:
    strategy = np.asarray(strategy, dtype=np.float64)
    spy = np.asarray(spy, dtype=np.float64)
    down = spy < 0.0
    if not np.any(down):
        return 0.0
    weights = np.abs(spy[down])
    total = float(np.sum(weights))
    if total <= 1e-15:
        return float(np.mean(strategy[down]))
    return float(np.sum(strategy[down] * weights) / total)


def _negative_sp500_year_metrics(strategy: np.ndarray, spy: np.ndarray, index: pd.DatetimeIndex) -> dict[str, float]:
    s = pd.Series(strategy, index=index)
    b = pd.Series(spy, index=index)
    negative = []
    for year, spy_year in b.groupby(b.index.year):
        sp500_return = _compound_return(spy_year.to_numpy(dtype=np.float64))
        if sp500_return >= 0.0:
            continue
        strat_year = s.loc[s.index.year == year]
        strategy_return = _compound_return(strat_year.to_numpy(dtype=np.float64))
        negative.append((strategy_return, sp500_return))
    if not negative:
        return {
            "negative_sp500_years": 0.0,
            "negative_sp500_years_win_pct": 0.0,
            "negative_sp500_years_positive_pct": 0.0,
        }
    return {
        "negative_sp500_years": float(len(negative)),
        "negative_sp500_years_win_pct": float(np.mean([strategy_return > sp500_return for strategy_return, sp500_return in negative])),
        "negative_sp500_years_positive_pct": float(np.mean([strategy_return > 0.0 for strategy_return, _ in negative])),
    }


def _effective_start(
    train_index: pd.DatetimeIndex,
    valid_index: pd.DatetimeIndex,
    train_returns: np.ndarray,
    valid_returns: np.ndarray,
) -> str:
    idx = train_index.append(valid_index)
    returns = np.concatenate([np.asarray(train_returns, dtype=np.float64), np.asarray(valid_returns, dtype=np.float64)])
    finite = np.isfinite(returns)
    if not np.any(finite):
        return ""
    return pd.Timestamp(idx[np.argmax(finite)]).date().isoformat()


def _late_entry_assets(train_index: pd.DatetimeIndex, train_asset_returns: pd.DataFrame, spec: dict[str, Any]) -> str:
    starts = []
    for asset in spec.get("assets", ()):
        if asset not in train_asset_returns.columns:
            continue
        series = train_asset_returns[asset]
        finite = series.notna().to_numpy(dtype=bool)
        if np.any(finite):
            first = pd.Timestamp(series.index[np.argmax(finite)])
            if first > pd.Timestamp(train_index[0]):
                starts.append(f"{asset}:{first.date().isoformat()}")
    return ",".join(starts)


def _returns_json(returns: Any) -> str:
    arr = np.asarray(returns, dtype=np.float64)
    out = [None if not np.isfinite(value) else float(value) for value in arr]
    return json.dumps(out, separators=(",", ":"))


def _index_json(index: pd.DatetimeIndex) -> str:
    return json.dumps([pd.Timestamp(value).date().isoformat() for value in index], separators=(",", ":"))


def _iter_return_payloads(frame: pd.DataFrame):
    if frame.empty:
        return
    for _, row in frame.iterrows():
        try:
            train_returns = json.loads(row.get("train_returns_json", "[]"))
            valid_returns = json.loads(row.get("validation_returns_json", "[]"))
            train_spy = json.loads(row.get("train_spy_returns_json", "[]"))
            valid_spy = json.loads(row.get("validation_spy_returns_json", "[]"))
            train_index = json.loads(row.get("train_index_json", "[]"))
            valid_index = json.loads(row.get("validation_index_json", "[]"))
            if not train_returns and "strategy_returns_json" in row:
                strategy = np.asarray([np.nan if value is None else float(value) for value in json.loads(row["strategy_returns_json"])], dtype=np.float64)
                spy = np.asarray([np.nan if value is None else float(value) for value in json.loads(row["spy_returns_json"])], dtype=np.float64)
                index = pd.DatetimeIndex(pd.to_datetime(json.loads(row["returns_index_json"])))
            else:
                strategy = np.asarray([np.nan if value is None else float(value) for value in [*train_returns, *valid_returns]], dtype=np.float64)
                spy = np.asarray([np.nan if value is None else float(value) for value in [*train_spy, *valid_spy]], dtype=np.float64)
                index = pd.DatetimeIndex(pd.to_datetime([*train_index, *valid_index]))
        except Exception:
            continue
        if len(strategy) != len(spy) or len(strategy) != len(index):
            continue
        yield {
            "candidate_id": row.get("candidate_id", ""),
            "strategy": strategy,
            "spy": spy,
            "index": index,
        }


def _subperiod_specs() -> tuple[tuple[str, str, str, str], ...]:
    return (
        ("train_1995_1998", "1995-01-01", "1998-12-31", "train"),
        ("train_1999_2002", "1999-01-01", "2002-12-31", "train"),
        ("train_2003_2006", "2003-01-01", "2006-12-31", "train"),
        ("train_2007_2010", "2007-01-01", "2010-12-31", "train"),
        ("valid_2011_2012", "2011-01-01", "2012-12-31", "validation"),
        ("valid_2013_2020", "2013-01-01", "2020-12-31", "validation"),
    )


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
