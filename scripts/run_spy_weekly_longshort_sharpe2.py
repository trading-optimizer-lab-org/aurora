from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf


CAMPAIGN_ID = "spy_weekly_longshort_sharpe2_trainonly_355jobs"
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2019-12-31")
LOCKED_START = pd.Timestamp("2020-01-01")
PPY = 52
TARGET_SHARPE = 2.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["data", "shard", "merge"], required=True)
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--configs-per-stage", type=int, default=30_000)
    parser.add_argument("--time-budget-minutes", type=float, default=45.0)
    parser.add_argument("--top-per-stage", type=int, default=120)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "data":
        run_data(output_dir)
    elif args.mode == "shard":
        run_shard(
            output_dir,
            stage=args.stage,
            configs_per_stage=args.configs_per_stage,
            time_budget_minutes=args.time_budget_minutes,
            top_per_stage=args.top_per_stage,
        )
    else:
        run_merge(output_dir)


def run_data(output_dir: Path) -> None:
    symbols = [
        "SPY",
        "^VIX",
        "^TNX",
        "^IRX",
        "^FVX",
        "^TYX",
        "DX-Y.NYB",
        "^GSPC",
        "^IXIC",
        "^RUT",
        "^DJI",
        "^FTSE",
        "^N225",
        "^GDAXI",
        "^HSI",
    ]
    raw = yf.download(
        symbols,
        start="1995-01-01",
        end="2020-01-01",
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    prices = pd.DataFrame()
    for symbol in symbols:
        prices[symbol] = raw[symbol]["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]
    prices = prices.dropna(how="any")
    weekly_prices = prices.resample("W-FRI").last().dropna(how="any")
    if isinstance(raw.columns, pd.MultiIndex):
        spy_raw = raw["SPY"].copy()
    else:
        spy_raw = raw.copy()
    spy_ohlcv = pd.DataFrame(
        {
            "SPY_OPEN": spy_raw["Open"].resample("W-FRI").first(),
            "SPY_HIGH": spy_raw["High"].resample("W-FRI").max(),
            "SPY_LOW": spy_raw["Low"].resample("W-FRI").min(),
            "SPY_VOLUME": spy_raw["Volume"].resample("W-FRI").sum(),
        }
    )
    weekly_prices = weekly_prices.join(spy_ohlcv, how="left").dropna(how="any")
    weekly_prices = weekly_prices[weekly_prices.index < LOCKED_START]
    close_cols = symbols
    weekly_returns = weekly_prices[close_cols].pct_change(fill_method=None).dropna(how="any")
    if weekly_returns.index.max() >= LOCKED_START:
        raise RuntimeError(f"Locked leak: max date {weekly_returns.index.max()}")
    if weekly_returns.index.min() > pd.Timestamp("1995-02-28"):
        raise RuntimeError(f"Insufficient history from 1995: {weekly_returns.index.min()}")

    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    weekly_prices.to_csv(data_dir / "weekly_prices.csv", index_label="timestamp")
    weekly_returns.to_csv(data_dir / "weekly_returns.csv", index_label="timestamp")
    pd.DataFrame(
        [
            {
                "traded_asset": "SPY",
                "context_symbols": "|".join(symbols[1:]),
                "frequency": "weekly",
                "position_policy": "always_long_or_short",
                "min_position": -1.0,
                "max_position": 1.0,
                "cash_allowed": False,
                "leverage_allowed": False,
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "validation_used_for_selection": False,
                "data_end_max": str(weekly_returns.index.max().date()),
            }
        ]
    ).to_csv(data_dir / "policy_audit.csv", index=False)


def run_shard(
    output_dir: Path,
    *,
    stage: int,
    configs_per_stage: int,
    time_budget_minutes: float,
    top_per_stage: int,
) -> None:
    returns = pd.read_csv(output_dir / "data" / "weekly_returns.csv", parse_dates=["timestamp"]).set_index("timestamp")
    prices = pd.read_csv(output_dir / "data" / "weekly_prices.csv", parse_dates=["timestamp"]).set_index("timestamp")
    if returns.index.max() >= LOCKED_START or prices.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached shard.")

    feature_frame = build_feature_frame(prices, returns)
    spy_rets = returns["SPY"].reindex(feature_frame.index).astype(float)
    train_mask = feature_frame.index <= TRAIN_END
    validation_mask = (feature_frame.index >= VALIDATION_START) & (feature_frame.index <= VALIDATION_END)
    if train_mask.sum() < 400 or validation_mask.sum() < 300:
        raise RuntimeError("Not enough weekly train/validation rows.")

    feature_cols = list(feature_frame.columns)
    matrix = feature_frame.to_numpy(dtype=float)
    spy_values = spy_rets.to_numpy(dtype=float)
    rng = np.random.default_rng(20260605 + stage * 1_000_003)
    started = time.monotonic()
    deadline = started + max(1.0, float(time_budget_minutes)) * 60.0
    rows: list[dict[str, Any]] = []
    evaluated = 0
    validation_evaluated = 0

    for config_index in range(int(configs_per_stage)):
        if time.monotonic() >= deadline:
            break
        evaluated += 1
        params = sample_params(rng, feature_cols, stage)
        positions, train_metrics = build_positions_train_only(matrix, spy_values, train_mask, params)
        strategy_returns = positions * spy_values
        if not np.isfinite(train_metrics["sharpe"]):
            continue
        train_returns = strategy_returns[train_mask]
        train_dates = feature_frame.index[train_mask]
        train_stability = train_only_stability(train_returns, train_dates)
        train_score = train_only_score(train_metrics, positions[train_mask], params, train_stability)
        # Cheap pruning, but keep deterministic probes so weak areas still report failures.
        if train_metrics["sharpe"] < 0.25 and config_index % 257 != 0:
            continue
        validation_metrics = metrics(strategy_returns[validation_mask])
        validation_evaluated += 1
        position_train = position_audit(positions[train_mask])
        position_validation = position_audit(positions[validation_mask])
        train_pass = bool(train_metrics["sharpe"] >= TARGET_SHARPE and position_train["always_invested"])
        validation_pass = bool(validation_metrics["sharpe"] >= TARGET_SHARPE and position_validation["always_invested"])
        config_hash = hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()
        rows.append(
            {
                "strategy_id": f"spy_weekly_longshort_sharpe2_s{stage:03d}_{config_hash[:16]}",
                "stage": int(stage),
                "config_index": int(config_index),
                "train_pass": train_pass,
                "validation_pass_report_only": validation_pass,
                "final_verified_report_only": bool(train_pass and validation_pass),
                "validation_used_for_selection": False,
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "data_end_max": "2019-12-31",
                "traded_asset": "SPY",
                "frequency": "weekly",
                "position_policy": "always_1x_long_or_short",
                "cash_allowed": False,
                "leverage_allowed": False,
                "uses_crypto": False,
                "uses_concrete_stocks": False,
                "proxy_corr_min": 1.0,
                "train_sharpe": float(train_metrics["sharpe"]),
                "validation_sharpe": float(validation_metrics["sharpe"]),
                "train_cagr": float(train_metrics["cagr"]),
                "validation_cagr": float(validation_metrics["cagr"]),
                "train_mdd": float(train_metrics["mdd"]),
                "validation_mdd": float(validation_metrics["mdd"]),
                "train_positive_weeks_pct": float(train_metrics["positive_weeks_pct"]),
                "validation_positive_weeks_pct": float(validation_metrics["positive_weeks_pct"]),
                "train_first_half_sharpe": float(train_stability["first_half_sharpe"]),
                "train_second_half_sharpe": float(train_stability["second_half_sharpe"]),
                "train_min_half_sharpe": float(train_stability["min_half_sharpe"]),
                "train_min_year_sharpe": float(train_stability["min_year_sharpe"]),
                "train_positive_years_pct": float(train_stability["positive_years_pct"]),
                "train_stability_score": float(train_stability["stability_score"]),
                "cv_train_sharpe": float(params.get("cv_train_sharpe", np.nan)),
                "cv_train_cagr": float(params.get("cv_train_cagr", np.nan)),
                "cv_train_mdd": float(params.get("cv_train_mdd", np.nan)),
                "train_turnover_weekly": float(turnover(positions[train_mask])),
                "validation_turnover_weekly": float(turnover(positions[validation_mask])),
                **{f"train_{key}": value for key, value in position_train.items() if key != "always_invested"},
                **{f"validation_{key}": value for key, value in position_validation.items() if key != "always_invested"},
                "train_always_invested": bool(position_train["always_invested"]),
                "validation_always_invested": bool(position_validation["always_invested"]),
                "feature_count": int(len(params["feature_indices"])),
                "rule_type": str(params.get("rule_type", "linear")),
                "features": "|".join(feature_cols[int(i)] for i in params["feature_indices"]),
                "weights": "|".join(f"{float(w):.8f}" for w in params["weights"]),
                "threshold": float(params.get("threshold", 0.0)),
                "invert": int(params.get("invert", 0)),
                "params_json": json.dumps(params, sort_keys=True),
                "train_score": float(train_score),
                "score": float(train_score),
            }
        )

    shard_dir = output_dir / "shards" / f"stage_{stage:03d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(columns=["strategy_id", "train_score", "final_verified_report_only"])
    frame.sort_values("train_score", ascending=False).head(int(top_per_stage)).to_csv(shard_dir / "top_candidates.csv", index=False)
    verified = frame[frame.get("final_verified_report_only", pd.Series(dtype=bool)).astype(bool)]
    verified.to_csv(shard_dir / "verified_candidates_report_only.csv", index=False)
    (shard_dir / "shard_summary.json").write_text(
        json.dumps(
            {
                "stage": int(stage),
                "configs_requested": int(configs_per_stage),
                "configs_evaluated": int(evaluated),
                "validation_evaluated_report_only": int(validation_evaluated),
                "rows_kept": int(len(frame)),
                "train_pass_rows": int(frame.get("train_pass", pd.Series(dtype=bool)).astype(bool).sum()) if "train_pass" in frame else 0,
                "final_verified_report_only_rows": int(len(verified)),
                "elapsed_seconds": float(time.monotonic() - started),
                "time_budget_minutes": float(time_budget_minutes),
                "locked_opened": False,
                "validation_used_for_selection": False,
                "position_policy": "always_1x_long_or_short",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def build_feature_frame(prices: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    data = pd.DataFrame(index=returns.index)
    spy = prices["SPY"].reindex(returns.index).ffill()
    spy_rets = returns["SPY"].reindex(returns.index)
    for lb in [1, 2, 4, 8, 13, 26, 39, 52]:
        data[f"spy_ret_{lb}w"] = (1.0 + spy_rets).rolling(lb).apply(np.prod, raw=True).shift(1) - 1.0
    for lb in [4, 10, 20, 30, 40, 52]:
        ma = spy.rolling(lb).mean()
        data[f"spy_ma_gap_{lb}w"] = (spy / ma - 1.0).shift(1)
    for lb in [4, 8, 13, 26, 52]:
        data[f"spy_vol_{lb}w"] = spy_rets.rolling(lb).std().shift(1)
        high = spy.rolling(lb).max()
        data[f"spy_drawdown_{lb}w"] = (spy / high - 1.0).shift(1)
    delta = spy.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    rs = gain.rolling(14).mean() / loss.rolling(14).mean().replace(0.0, np.nan)
    data["spy_rsi_14w"] = (100.0 - 100.0 / (1.0 + rs)).shift(1)
    for symbol in ["^VIX", "^TNX"]:
        raw = prices[symbol].reindex(returns.index).ffill()
        ret = raw.pct_change(fill_method=None)
        name = "vix" if symbol == "^VIX" else "tnx"
        for lb in [1, 4, 13, 26]:
            data[f"{name}_ret_{lb}w"] = (1.0 + ret).rolling(lb).apply(np.prod, raw=True).shift(1) - 1.0
        for lb in [13, 26, 52]:
            mean = raw.rolling(lb).mean()
            std = raw.rolling(lb).std().replace(0.0, np.nan)
            data[f"{name}_z_{lb}w"] = ((raw - mean) / std).shift(1)
    for symbol, name in [
        ("^GSPC", "spx"),
        ("^IXIC", "nasdaq"),
        ("^RUT", "russell"),
        ("^DJI", "dow"),
        ("^FTSE", "ftse"),
        ("^N225", "nikkei"),
        ("^GDAXI", "dax"),
        ("^HSI", "hsi"),
        ("DX-Y.NYB", "dxy"),
    ]:
        if symbol not in prices.columns:
            continue
        raw = prices[symbol].reindex(returns.index).ffill()
        ret = raw.pct_change(fill_method=None)
        for lb in [1, 4, 13, 26, 52]:
            data[f"{name}_ret_{lb}w"] = (1.0 + ret).rolling(lb).apply(np.prod, raw=True).shift(1) - 1.0
            if name != "dxy":
                data[f"{name}_rel_spy_{lb}w"] = data[f"{name}_ret_{lb}w"] - data[f"spy_ret_{lb}w"]
        for lb in [13, 26, 52]:
            mean = raw.rolling(lb).mean()
            std = raw.rolling(lb).std().replace(0.0, np.nan)
            data[f"{name}_z_{lb}w"] = ((raw - mean) / std).shift(1)
    for symbol, name in [("^IRX", "irx"), ("^FVX", "fvx"), ("^TNX", "tnx"), ("^TYX", "tyx")]:
        if symbol not in prices.columns:
            continue
        raw = prices[symbol].reindex(returns.index).ffill()
        diff = raw.diff()
        for lb in [1, 4, 13, 26, 52]:
            data[f"{name}_diff_{lb}w"] = diff.rolling(lb).sum().shift(1)
        for lb in [13, 26, 52]:
            mean = raw.rolling(lb).mean()
            std = raw.rolling(lb).std().replace(0.0, np.nan)
            data[f"{name}_level_z_{lb}w"] = ((raw - mean) / std).shift(1)
    for left, right, spread_name in [
        ("^TNX", "^IRX", "tnx_irx_spread"),
        ("^TYX", "^IRX", "tyx_irx_spread"),
        ("^FVX", "^IRX", "fvx_irx_spread"),
        ("^TYX", "^FVX", "tyx_fvx_spread"),
    ]:
        if left not in prices.columns or right not in prices.columns:
            continue
        spread = prices[left].reindex(returns.index).ffill() - prices[right].reindex(returns.index).ffill()
        for lb in [1, 4, 13, 26]:
            data[f"{spread_name}_diff_{lb}w"] = spread.diff().rolling(lb).sum().shift(1)
        for lb in [13, 26, 52]:
            mean = spread.rolling(lb).mean()
            std = spread.rolling(lb).std().replace(0.0, np.nan)
            data[f"{spread_name}_z_{lb}w"] = ((spread - mean) / std).shift(1)
    if {"SPY_OPEN", "SPY_HIGH", "SPY_LOW", "SPY_VOLUME"} <= set(prices.columns):
        spy_open = prices["SPY_OPEN"].reindex(returns.index).ffill()
        spy_high = prices["SPY_HIGH"].reindex(returns.index).ffill()
        spy_low = prices["SPY_LOW"].reindex(returns.index).ffill()
        spy_close = prices["SPY"].reindex(returns.index).ffill()
        spy_volume = prices["SPY_VOLUME"].reindex(returns.index).ffill()
        data["spy_week_range"] = (spy_high / spy_low - 1.0).shift(1)
        data["spy_week_close_open"] = (spy_close / spy_open - 1.0).shift(1)
        data["spy_week_close_high"] = (spy_close / spy_high - 1.0).shift(1)
        data["spy_week_close_low"] = (spy_close / spy_low - 1.0).shift(1)
        volume_change = spy_volume.pct_change(fill_method=None)
        for lb in [4, 13, 26, 52]:
            mean = spy_volume.rolling(lb).mean()
            std = spy_volume.rolling(lb).std().replace(0.0, np.nan)
            data[f"spy_volume_z_{lb}w"] = ((spy_volume - mean) / std).shift(1)
            data[f"spy_volume_ret_{lb}w"] = (1.0 + volume_change).rolling(lb).apply(np.prod, raw=True).shift(1) - 1.0
    data["spy_ret_4w_x_vix_z_26w"] = data["spy_ret_4w"] * data["vix_z_26w"]
    data["spy_ma_20w_x_tnx_z_26w"] = data["spy_ma_gap_20w"] * data["tnx_z_26w"]
    if "nasdaq_rel_spy_13w" in data.columns:
        data["spy_ret_13w_x_nasdaq_rel_spy_13w"] = data["spy_ret_13w"] * data["nasdaq_rel_spy_13w"]
    if "spy_week_range" in data.columns:
        data["spy_week_range_x_vix_z_13w"] = data["spy_week_range"] * data["vix_z_13w"]
    week = pd.Series(data.index.isocalendar().week.astype(float).to_numpy(), index=data.index)
    month = pd.Series(data.index.month.astype(float), index=data.index)
    quarter = pd.Series(data.index.quarter.astype(float), index=data.index)
    year = pd.Series(data.index.year.astype(float), index=data.index)
    time_index = pd.Series(np.arange(len(data), dtype=float), index=data.index)
    data["calendar_week_sin"] = np.sin(2.0 * np.pi * week / 52.0)
    data["calendar_week_cos"] = np.cos(2.0 * np.pi * week / 52.0)
    data["calendar_month_sin"] = np.sin(2.0 * np.pi * month / 12.0)
    data["calendar_month_cos"] = np.cos(2.0 * np.pi * month / 12.0)
    data["calendar_quarter_sin"] = np.sin(2.0 * np.pi * quarter / 4.0)
    data["calendar_quarter_cos"] = np.cos(2.0 * np.pi * quarter / 4.0)
    data["calendar_cycle4_sin"] = np.sin(2.0 * np.pi * (year % 4.0) / 4.0)
    data["calendar_cycle4_cos"] = np.cos(2.0 * np.pi * (year % 4.0) / 4.0)
    data["calendar_time_trend"] = time_index / max(1.0, float(len(time_index) - 1))
    data["calendar_january"] = (month == 1.0).astype(float)
    data["calendar_september"] = (month == 9.0).astype(float)
    data["calendar_q4"] = (quarter == 4.0).astype(float)
    data = data.replace([np.inf, -np.inf], np.nan).dropna(how="any")
    # Robust per-column scaling, fit using train only to avoid validation leakage.
    train = data[data.index <= TRAIN_END]
    median = train.median()
    scale = (train.quantile(0.75) - train.quantile(0.25)).replace(0.0, np.nan)
    valid_cols = scale.dropna().index
    data = data[valid_cols]
    median = median[valid_cols]
    scale = scale[valid_cols]
    scaled = (data - median) / scale
    return scaled.replace([np.inf, -np.inf], np.nan).dropna(how="any").clip(-8.0, 8.0)


def sample_params(rng: np.random.Generator, feature_cols: list[str], stage: int) -> dict[str, Any]:
    family = stage % 7
    if family == 0:
        k = 1
    elif family in {1, 2}:
        k = int(rng.integers(2, 5))
    elif family in {3, 4}:
        k = int(rng.integers(4, 9))
    else:
        k = int(rng.integers(8, min(16, len(feature_cols)) + 1))
    k = min(int(k), len(feature_cols))
    feature_indices = rng.choice(len(feature_cols), size=k, replace=False)
    weights = rng.normal(0.0, 1.0, size=k)
    norm = np.sum(np.abs(weights))
    if norm <= 0:
        weights = np.ones(k) / k
    else:
        weights = weights / norm
    rule_type = str(
        rng.choice(
            [
                "linear",
                "threshold_vote",
                "band_vote",
                "signed_stump_vote",
                "train_leaf_tree",
                "era_leaf_tree",
                "cv_era_leaf_tree",
                "ridge_model",
            ],
            p=[0.10, 0.12, 0.08, 0.12, 0.14, 0.14, 0.18, 0.12],
        )
    )
    if rule_type in {"train_leaf_tree", "era_leaf_tree", "cv_era_leaf_tree"}:
        k = min(max(4, k), min(10, len(feature_cols)))
        feature_indices = rng.choice(len(feature_cols), size=k, replace=False)
        weights = np.ones(k, dtype=float) / k
    if rule_type == "ridge_model":
        k = int(rng.integers(4, min(26, len(feature_cols)) + 1))
        feature_indices = rng.choice(len(feature_cols), size=k, replace=False)
        weights = np.ones(k, dtype=float) / k
    thresholds = rng.normal(0.0, 1.0, size=k)
    band_widths = rng.uniform(0.25, 2.0, size=k)
    directions = rng.choice([-1.0, 1.0], size=k)
    if family == 2:
        weights = np.sign(weights) / k
    threshold = float(rng.normal(0.0, 0.65 if k <= 2 else 0.35))
    if rule_type != "linear":
        threshold = float(rng.normal(0.0, 0.20))
    return {
        "family": int(family),
        "rule_type": rule_type,
        "feature_indices": [int(i) for i in feature_indices],
        "weights": [float(w) for w in weights],
        "thresholds": [float(x) for x in thresholds],
        "band_widths": [float(x) for x in band_widths],
        "directions": [float(x) for x in directions],
        "threshold": threshold,
        "ridge_alpha": float(10.0 ** rng.uniform(-3.0, 2.0)),
        "invert": int(rng.integers(0, 2)),
    }


def build_score(matrix: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    idx = np.asarray(params["feature_indices"], dtype=int)
    weights = np.asarray(params["weights"], dtype=float)
    values = matrix[:, idx]
    rule_type = str(params.get("rule_type", "linear"))
    if rule_type == "threshold_vote":
        thresholds = np.asarray(params.get("thresholds", [0.0] * len(idx)), dtype=float)
        votes = np.where(values >= thresholds, 1.0, -1.0)
        return votes @ weights
    if rule_type == "band_vote":
        centers = np.asarray(params.get("thresholds", [0.0] * len(idx)), dtype=float)
        widths = np.asarray(params.get("band_widths", [1.0] * len(idx)), dtype=float)
        inside = np.abs(values - centers) <= widths
        votes = np.where(inside, 1.0, -1.0)
        return votes @ weights
    if rule_type == "signed_stump_vote":
        thresholds = np.asarray(params.get("thresholds", [0.0] * len(idx)), dtype=float)
        directions = np.asarray(params.get("directions", [1.0] * len(idx)), dtype=float)
        votes = np.where(values * directions >= thresholds, 1.0, -1.0)
        return votes @ weights
    return values @ weights


def build_positions_train_only(
    matrix: np.ndarray,
    spy_returns: np.ndarray,
    train_mask: np.ndarray,
    params: dict[str, Any],
) -> tuple[np.ndarray, dict[str, float]]:
    if str(params.get("rule_type", "linear")) == "train_leaf_tree":
        positions = build_train_leaf_tree_positions(matrix, spy_returns, train_mask, params)
        return positions, metrics(positions[train_mask] * spy_returns[train_mask])
    if str(params.get("rule_type", "linear")) == "era_leaf_tree":
        positions = build_era_leaf_tree_positions(matrix, spy_returns, train_mask, params)
        return positions, metrics(positions[train_mask] * spy_returns[train_mask])
    if str(params.get("rule_type", "linear")) == "cv_era_leaf_tree":
        positions = build_cv_era_leaf_tree_positions(matrix, spy_returns, train_mask, params)
        return positions, metrics(positions[train_mask] * spy_returns[train_mask])
    if str(params.get("rule_type", "linear")) == "ridge_model":
        positions = build_ridge_model_positions(matrix, spy_returns, train_mask, params)
        return positions, metrics(positions[train_mask] * spy_returns[train_mask])
    raw_score = build_score(matrix, params)
    threshold, invert, train_metrics = choose_train_only_threshold(raw_score, spy_returns, train_mask)
    params["threshold"] = float(threshold)
    params["invert"] = int(invert)
    score = -raw_score if invert == 1 else raw_score
    return np.where(score >= threshold, 1.0, -1.0), train_metrics


def build_train_leaf_tree_positions(
    matrix: np.ndarray,
    spy_returns: np.ndarray,
    train_mask: np.ndarray,
    params: dict[str, Any],
) -> np.ndarray:
    idx = np.asarray(params["feature_indices"], dtype=int)
    values = matrix[:, idx]
    train_values = values[train_mask]
    thresholds = np.asarray(params.get("thresholds", [0.0] * len(idx)), dtype=float)
    # Convert random normal thresholds into train quantile thresholds so each split has a chance.
    quantile_points = np.clip(0.5 + np.tanh(thresholds) * 0.45, 0.05, 0.95)
    split_thresholds = np.asarray(
        [np.quantile(train_values[:, i], quantile_points[i]) for i in range(len(idx))],
        dtype=float,
    )
    directions = np.asarray(params.get("directions", [1.0] * len(idx)), dtype=float)
    bits = (values * directions >= split_thresholds).astype(np.int64)
    powers = (1 << np.arange(len(idx), dtype=np.int64))
    leaf_id = bits @ powers
    train_leaf = leaf_id[train_mask]
    train_rets = np.asarray(spy_returns[train_mask], dtype=float)
    leaf_count = int(2 ** len(idx))
    default_sign = 1.0 if float(np.sum(train_rets)) >= 0.0 else -1.0
    signs = np.full(leaf_count, default_sign, dtype=float)
    for leaf in range(leaf_count):
        mask = train_leaf == leaf
        if int(np.sum(mask)) >= 2:
            signs[leaf] = 1.0 if float(np.sum(train_rets[mask])) >= 0.0 else -1.0
    params["split_thresholds"] = [float(x) for x in split_thresholds]
    params["leaf_signs"] = [float(x) for x in signs]
    return signs[leaf_id]


def build_era_leaf_tree_positions(
    matrix: np.ndarray,
    spy_returns: np.ndarray,
    train_mask: np.ndarray,
    params: dict[str, Any],
) -> np.ndarray:
    idx = np.asarray(params["feature_indices"], dtype=int)
    values = matrix[:, idx]
    train_values = values[train_mask]
    thresholds = np.asarray(params.get("thresholds", [0.0] * len(idx)), dtype=float)
    quantile_points = np.clip(0.5 + np.tanh(thresholds) * 0.38, 0.08, 0.92)
    split_thresholds = np.asarray(
        [np.quantile(train_values[:, i], quantile_points[i]) for i in range(len(idx))],
        dtype=float,
    )
    directions = np.asarray(params.get("directions", [1.0] * len(idx)), dtype=float)
    bits = (values * directions >= split_thresholds).astype(np.int64)
    powers = (1 << np.arange(len(idx), dtype=np.int64))
    leaf_id = bits @ powers
    train_leaf = leaf_id[train_mask]
    train_rets = np.asarray(spy_returns[train_mask], dtype=float)
    era_ids = np.array_split(np.arange(len(train_rets)), 4)
    leaf_count = int(2 ** len(idx))
    default_sign = 1.0 if float(np.sum(train_rets)) >= 0.0 else -1.0
    signs = np.full(leaf_count, default_sign, dtype=float)
    era_agreement = np.zeros(leaf_count, dtype=float)
    for leaf in range(leaf_count):
        votes: list[float] = []
        for era in era_ids:
            mask = train_leaf[era] == leaf
            if int(np.sum(mask)) >= 2:
                era_sum = float(np.sum(train_rets[era][mask]))
                if not math.isclose(era_sum, 0.0):
                    votes.append(1.0 if era_sum > 0.0 else -1.0)
        if votes:
            vote_sum = float(np.sum(votes))
            era_agreement[leaf] = abs(vote_sum) / len(votes)
            if era_agreement[leaf] >= 0.50:
                signs[leaf] = 1.0 if vote_sum >= 0.0 else -1.0
    params["split_thresholds"] = [float(x) for x in split_thresholds]
    params["leaf_signs"] = [float(x) for x in signs]
    params["leaf_era_agreement_mean"] = float(np.mean(era_agreement))
    return signs[leaf_id]


def build_cv_era_leaf_tree_positions(
    matrix: np.ndarray,
    spy_returns: np.ndarray,
    train_mask: np.ndarray,
    params: dict[str, Any],
) -> np.ndarray:
    idx = np.asarray(params["feature_indices"], dtype=int)
    values = np.asarray(matrix[:, idx], dtype=float)
    train_indices = np.flatnonzero(train_mask)
    folds = [fold for fold in np.array_split(train_indices, 4) if len(fold) > 0]
    cv_positions = np.full(matrix.shape[0], np.nan, dtype=float)
    for fold in folds:
        fit_mask = train_mask.copy()
        fit_mask[fold] = False
        if int(np.sum(fit_mask)) < max(80, len(idx) * 8):
            continue
        split_thresholds, signs, _ = fit_leaf_tree(values, spy_returns, fit_mask, params, era_consistent=True)
        fold_leaf = compute_leaf_ids(values[fold], split_thresholds, params)
        cv_positions[fold] = signs[fold_leaf]
    default_sign = 1.0 if float(np.sum(spy_returns[train_mask])) >= 0.0 else -1.0
    cv_positions[np.isnan(cv_positions)] = default_sign
    cv_metrics = metrics(cv_positions[train_mask] * spy_returns[train_mask])
    params["cv_train_sharpe"] = float(cv_metrics["sharpe"])
    params["cv_train_cagr"] = float(cv_metrics["cagr"])
    params["cv_train_mdd"] = float(cv_metrics["mdd"])
    split_thresholds, signs, agreement = fit_leaf_tree(values, spy_returns, train_mask, params, era_consistent=True)
    final_leaf = compute_leaf_ids(values, split_thresholds, params)
    params["split_thresholds"] = [float(x) for x in split_thresholds]
    params["leaf_signs"] = [float(x) for x in signs]
    params["leaf_era_agreement_mean"] = float(agreement)
    return signs[final_leaf]


def fit_leaf_tree(
    values: np.ndarray,
    spy_returns: np.ndarray,
    fit_mask: np.ndarray,
    params: dict[str, Any],
    *,
    era_consistent: bool,
) -> tuple[np.ndarray, np.ndarray, float]:
    fit_values = values[fit_mask]
    thresholds = np.asarray(params.get("thresholds", [0.0] * values.shape[1]), dtype=float)
    quantile_points = np.clip(0.5 + np.tanh(thresholds) * 0.38, 0.08, 0.92)
    split_thresholds = np.asarray(
        [np.quantile(fit_values[:, i], quantile_points[i]) for i in range(values.shape[1])],
        dtype=float,
    )
    leaf_id = compute_leaf_ids(values, split_thresholds, params)
    fit_leaf = leaf_id[fit_mask]
    fit_rets = np.asarray(spy_returns[fit_mask], dtype=float)
    leaf_count = int(2 ** values.shape[1])
    default_sign = 1.0 if float(np.sum(fit_rets)) >= 0.0 else -1.0
    signs = np.full(leaf_count, default_sign, dtype=float)
    agreement = np.zeros(leaf_count, dtype=float)
    if not era_consistent:
        for leaf in range(leaf_count):
            mask = fit_leaf == leaf
            if int(np.sum(mask)) >= 2:
                signs[leaf] = 1.0 if float(np.sum(fit_rets[mask])) >= 0.0 else -1.0
                agreement[leaf] = 1.0
        return split_thresholds, signs, float(np.mean(agreement))
    era_ids = np.array_split(np.arange(len(fit_rets)), 4)
    for leaf in range(leaf_count):
        votes: list[float] = []
        for era in era_ids:
            mask = fit_leaf[era] == leaf
            if int(np.sum(mask)) >= 2:
                era_sum = float(np.sum(fit_rets[era][mask]))
                if not math.isclose(era_sum, 0.0):
                    votes.append(1.0 if era_sum > 0.0 else -1.0)
        if votes:
            vote_sum = float(np.sum(votes))
            agreement[leaf] = abs(vote_sum) / len(votes)
            if agreement[leaf] >= 0.50:
                signs[leaf] = 1.0 if vote_sum >= 0.0 else -1.0
    return split_thresholds, signs, float(np.mean(agreement))


def compute_leaf_ids(values: np.ndarray, split_thresholds: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    directions = np.asarray(params.get("directions", [1.0] * values.shape[1]), dtype=float)
    bits = (values * directions >= split_thresholds).astype(np.int64)
    powers = 1 << np.arange(values.shape[1], dtype=np.int64)
    return bits @ powers


def build_ridge_model_positions(
    matrix: np.ndarray,
    spy_returns: np.ndarray,
    train_mask: np.ndarray,
    params: dict[str, Any],
) -> np.ndarray:
    idx = np.asarray(params["feature_indices"], dtype=int)
    x_train = np.asarray(matrix[train_mask][:, idx], dtype=float)
    y_train = np.asarray(spy_returns[train_mask], dtype=float)
    finite = np.isfinite(x_train).all(axis=1) & np.isfinite(y_train)
    x_train = x_train[finite]
    y_train = y_train[finite]
    if len(y_train) < max(30, len(idx) * 4):
        return np.ones(matrix.shape[0], dtype=float)
    alpha = float(params.get("ridge_alpha", 1.0))
    x_design = np.c_[np.ones(len(x_train)), x_train]
    penalty = np.eye(x_design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    try:
        beta = np.linalg.solve(x_design.T @ x_design + penalty, x_design.T @ y_train)
    except np.linalg.LinAlgError:
        beta = np.linalg.pinv(x_design.T @ x_design + penalty) @ x_design.T @ y_train
    full_design = np.c_[np.ones(matrix.shape[0]), np.asarray(matrix[:, idx], dtype=float)]
    prediction = full_design @ beta
    threshold, invert, _ = choose_train_only_threshold(prediction, spy_returns, train_mask)
    params["weights"] = [float(x) for x in beta[1:]]
    params["intercept"] = float(beta[0])
    params["threshold"] = float(threshold)
    params["invert"] = int(invert)
    oriented = -prediction if invert == 1 else prediction
    return np.where(oriented >= threshold, 1.0, -1.0)


def choose_train_only_threshold(score: np.ndarray, spy_returns: np.ndarray, train_mask: np.ndarray) -> tuple[float, int, dict[str, float]]:
    train_score = np.asarray(score[train_mask], dtype=float)
    train_rets = np.asarray(spy_returns[train_mask], dtype=float)
    finite = np.isfinite(train_score) & np.isfinite(train_rets)
    train_score = train_score[finite]
    train_rets = train_rets[finite]
    if len(train_score) < 20:
        return 0.0, 0, metrics(np.array([], dtype=float))
    quantiles = np.unique(np.quantile(train_score, np.linspace(0.03, 0.97, 25)))
    best_threshold = 0.0
    best_invert = 0
    best_metrics = {"sharpe": -np.inf, "cagr": np.nan, "mdd": np.nan, "positive_weeks_pct": np.nan}
    for invert in [0, 1]:
        oriented = -train_score if invert == 1 else train_score
        for threshold in quantiles:
            positions = np.where(oriented >= threshold, 1.0, -1.0)
            long_pct = float(np.mean(positions > 0.0))
            if long_pct < 0.05 or long_pct > 0.95:
                continue
            current = metrics(positions * train_rets)
            if float(current["sharpe"]) > float(best_metrics["sharpe"]):
                best_threshold = float(threshold)
                best_invert = int(invert)
                best_metrics = current
    return best_threshold, best_invert, best_metrics


def metrics(returns: np.ndarray) -> dict[str, float]:
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 2:
        return {"sharpe": np.nan, "cagr": np.nan, "mdd": np.nan, "positive_weeks_pct": np.nan}
    std = float(np.std(values, ddof=1))
    sharpe = float(np.mean(values) / std * math.sqrt(PPY)) if std > 0 else np.nan
    nav = np.cumprod(1.0 + values)
    years = len(values) / PPY
    cagr = float(nav[-1] ** (1.0 / years) - 1.0) if years > 0 and nav[-1] > 0 else np.nan
    mdd = float(np.min(nav / np.maximum.accumulate(nav) - 1.0))
    return {
        "sharpe": sharpe,
        "cagr": cagr,
        "mdd": mdd,
        "positive_weeks_pct": float(np.mean(values > 0.0)),
    }


def train_only_stability(returns: np.ndarray, dates: pd.DatetimeIndex) -> dict[str, float]:
    values = np.asarray(returns, dtype=float)
    midpoint = len(values) // 2
    first = metrics(values[:midpoint])
    second = metrics(values[midpoint:])
    yearly_sharpes: list[float] = []
    yearly_cagrs: list[float] = []
    years = pd.Index(dates).year.to_numpy()
    for year in np.unique(years):
        chunk = values[years == year]
        if len(chunk) >= 20:
            current = metrics(chunk)
            if np.isfinite(current["sharpe"]):
                yearly_sharpes.append(float(current["sharpe"]))
            if np.isfinite(current["cagr"]):
                yearly_cagrs.append(float(current["cagr"]))
    min_half = float(np.nanmin([first["sharpe"], second["sharpe"]]))
    min_year_sharpe = float(np.min(yearly_sharpes)) if yearly_sharpes else np.nan
    positive_years_pct = float(np.mean(np.asarray(yearly_cagrs) > 0.0)) if yearly_cagrs else np.nan
    stability_score = (
        max(-2.0, min_half) * 0.55
        + max(-2.0, min_year_sharpe if np.isfinite(min_year_sharpe) else -2.0) * 0.20
        + (positive_years_pct if np.isfinite(positive_years_pct) else 0.0) * 0.25
    )
    return {
        "first_half_sharpe": float(first["sharpe"]),
        "second_half_sharpe": float(second["sharpe"]),
        "min_half_sharpe": min_half,
        "min_year_sharpe": min_year_sharpe,
        "positive_years_pct": positive_years_pct,
        "stability_score": float(stability_score),
    }


def turnover(positions: np.ndarray) -> float:
    values = np.asarray(positions, dtype=float)
    if len(values) < 2:
        return 0.0
    return float(np.mean(np.abs(np.diff(values)) / 2.0))


def position_audit(positions: np.ndarray) -> dict[str, Any]:
    values = np.asarray(positions, dtype=float)
    return {
        "min_position": float(np.min(values)) if len(values) else np.nan,
        "max_position": float(np.max(values)) if len(values) else np.nan,
        "min_abs_position": float(np.min(np.abs(values))) if len(values) else np.nan,
        "max_abs_position": float(np.max(np.abs(values))) if len(values) else np.nan,
        "long_weeks": int(np.sum(values > 0.0)),
        "short_weeks": int(np.sum(values < 0.0)),
        "cash_weeks": int(np.sum(np.isclose(values, 0.0))),
        "always_invested": bool(len(values) > 0 and np.all(np.isin(values, [-1.0, 1.0]))),
    }


def train_only_score(
    metrics_row: dict[str, float],
    positions: np.ndarray,
    params: dict[str, Any],
    stability: dict[str, float] | None = None,
) -> float:
    complexity = len(params["feature_indices"])
    stability = stability or {
        "min_half_sharpe": -2.0,
        "min_year_sharpe": -2.0,
        "positive_years_pct": 0.0,
        "stability_score": -2.0,
    }
    min_half = float(stability.get("min_half_sharpe", -2.0))
    min_year = float(stability.get("min_year_sharpe", -2.0))
    positive_years = float(stability.get("positive_years_pct", 0.0))
    stability_score = float(stability.get("stability_score", -2.0))
    cv_sharpe = float(params.get("cv_train_sharpe", np.nan))
    unstable_penalty = 0.0
    if min_half < 1.0:
        unstable_penalty += (1.0 - min_half) * 220_000.0
    if min_year < -0.25:
        unstable_penalty += (-0.25 - min_year) * 45_000.0
    if positive_years < 0.65:
        unstable_penalty += (0.65 - positive_years) * 90_000.0
    cv_bonus = 0.0
    cv_gap_penalty = 0.0
    if np.isfinite(cv_sharpe):
        cv_bonus = cv_sharpe * 650_000.0
        cv_gap_penalty = max(0.0, float(metrics_row["sharpe"]) - cv_sharpe) * 180_000.0
    return (
        float(metrics_row["sharpe"]) * 1_000_000.0
        + stability_score * 350_000.0
        + cv_bonus
        + float(metrics_row["cagr"]) * 20_000.0
        + float(metrics_row["mdd"]) * 10_000.0
        - turnover(positions) * 2_000.0
        - complexity * 75.0
        - unstable_penalty
        - cv_gap_penalty
    )


def run_merge(output_dir: Path) -> None:
    top_files = list((output_dir / "shards").glob("**/top_candidates.csv"))
    verified_files = list((output_dir / "shards").glob("**/verified_candidates_report_only.csv"))
    summary_files = list((output_dir / "shards").glob("**/shard_summary.json"))
    top = pd.concat([pd.read_csv(path) for path in top_files], ignore_index=True) if top_files else pd.DataFrame()
    verified = pd.concat([pd.read_csv(path) for path in verified_files], ignore_index=True) if verified_files else pd.DataFrame()
    if not top.empty:
        top = top.sort_values(["train_sharpe", "train_cagr", "feature_count"], ascending=[False, False, True])
    if not verified.empty:
        verified = verified.sort_values(["train_sharpe", "validation_sharpe", "feature_count"], ascending=[False, False, True])
    train_pass = top[top.get("train_pass", pd.Series(dtype=bool)).astype(bool)] if "train_pass" in top else pd.DataFrame()
    top.to_csv(output_dir / "spy_weekly_longshort_sharpe2_leaderboard.csv", index=False)
    train_pass.to_csv(output_dir / "spy_weekly_longshort_sharpe2_train_pass.csv", index=False)
    verified.to_csv(output_dir / "spy_weekly_longshort_sharpe2_verified.csv", index=False)
    for name in ["weekly_prices.csv", "weekly_returns.csv", "policy_audit.csv"]:
        src = output_dir / "data" / name
        if src.exists():
            pd.read_csv(src).to_csv(output_dir / name, index=False)
    shard_summaries: list[dict[str, Any]] = []
    for path in summary_files:
        try:
            shard_summaries.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    pd.DataFrame(shard_summaries).to_csv(output_dir / "spy_weekly_longshort_sharpe2_shard_summaries.csv", index=False)
    fail_reasons = build_fail_reasons(top)
    fail_reasons.to_csv(output_dir / "spy_weekly_longshort_sharpe2_fail_reasons.csv", index=False)
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "verified_count_report_only": int(len(verified)),
        "train_pass_count": int(len(train_pass)),
        "top_candidate_rows": int(len(top)),
        "shards_with_summary": int(len(shard_summaries)),
        "configs_evaluated": int(sum(item.get("configs_evaluated", 0) for item in shard_summaries)),
        "validation_evaluated_report_only": int(sum(item.get("validation_evaluated_report_only", 0) for item in shard_summaries)),
        "target_train_sharpe": TARGET_SHARPE,
        "target_validation_sharpe_report_only": TARGET_SHARPE,
        "traded_asset": "SPY",
        "position_policy": "always_1x_long_or_short",
        "cash_allowed": False,
        "leverage_allowed": False,
        "locked_opened": False,
        "locked_rows_accessed": 0,
        "validation_used_for_selection": False,
        "uses_concrete_stocks": False,
        "uses_crypto": False,
        "data_end_max": "2019-12-31",
    }
    (output_dir / "spy_weekly_longshort_sharpe2_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def build_fail_reasons(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["reason", "count"])
    reasons = []
    for _, row in df.iterrows():
        if bool(row.get("final_verified_report_only", False)):
            reason = "verified"
        elif not bool(row.get("train_always_invested", False)) or not bool(row.get("validation_always_invested", False)):
            reason = "position_policy_failed"
        elif float(row.get("train_sharpe", -999.0)) < TARGET_SHARPE:
            reason = "train_sharpe_below_2"
        elif float(row.get("validation_sharpe", -999.0)) < TARGET_SHARPE:
            reason = "validation_sharpe_below_2_report_only"
        else:
            reason = "other"
        reasons.append(reason)
    return pd.Series(reasons).value_counts().rename_axis("reason").reset_index(name="count")


if __name__ == "__main__":
    main()
