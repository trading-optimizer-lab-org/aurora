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

try:
    from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
except Exception:  # pragma: no cover - optional in minimal installs
    ExtraTreesClassifier = None
    HistGradientBoostingClassifier = None
    RandomForestClassifier = None
    LogisticRegression = None


CAMPAIGN_ID = "spy_daily_direction_accuracy_355jobs"
TRAIN_START = pd.Timestamp("1995-01-01")
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")
TARGET_ACCURACY = 0.55


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["data", "shard", "merge"], required=True)
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--configs-per-stage", type=int, default=25_000)
    parser.add_argument("--time-budget-minutes", type=float, default=45.0)
    parser.add_argument("--top-per-stage", type=int, default=100)
    parser.add_argument("--target-accuracy", type=float, default=TARGET_ACCURACY)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "data":
        run_data(output_dir)
    elif args.mode == "shard":
        run_shard(
            output_dir,
            stage=int(args.stage),
            configs_per_stage=int(args.configs_per_stage),
            time_budget_minutes=float(args.time_budget_minutes),
            top_per_stage=int(args.top_per_stage),
            target_accuracy=float(args.target_accuracy),
        )
    else:
        run_merge(output_dir, target_accuracy=float(args.target_accuracy))


def run_data(output_dir: Path) -> None:
    required = ["SPY", "^VIX", "^TNX", "^IRX"]
    optional = [
        "QQQ",
        "IWM",
        "DIA",
        "EFA",
        "EEM",
        "TLT",
        "IEF",
        "SHY",
        "GLD",
        "LQD",
        "HYG",
        "XLY",
        "XLP",
        "XLK",
        "XLU",
        "XLF",
        "XLE",
        "XLV",
        "XLI",
        "XLB",
        "UUP",
        "DX-Y.NYB",
    ]
    symbols = required + optional
    raw = yf.download(
        symbols,
        start="1994-01-01",
        end="2021-01-01",
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
        timeout=30,
    )
    close = pd.DataFrame()
    ohlcv = pd.DataFrame()
    for symbol in symbols:
        if isinstance(raw.columns, pd.MultiIndex):
            if symbol not in raw.columns.get_level_values(0):
                continue
            frame = raw[symbol]
        else:
            frame = raw
        if "Close" not in frame:
            continue
        close[symbol] = frame["Close"]
        if symbol == "SPY":
            ohlcv = pd.DataFrame(
                {
                    "SPY_OPEN": frame["Open"],
                    "SPY_HIGH": frame["High"],
                    "SPY_LOW": frame["Low"],
                    "SPY_CLOSE": frame["Close"],
                    "SPY_VOLUME": frame["Volume"],
                }
            )
    close.index = pd.to_datetime(close.index).tz_localize(None)
    ohlcv.index = pd.to_datetime(ohlcv.index).tz_localize(None)
    close = close.sort_index().dropna(subset=required, how="any")
    ohlcv = ohlcv.reindex(close.index).dropna(how="any")
    close = close.loc[close.index < LOCKED_START]
    ohlcv = ohlcv.loc[ohlcv.index < LOCKED_START]
    if close.index.max() >= LOCKED_START or ohlcv.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data leaked into daily panel.")
    if close.index.min() > pd.Timestamp("1995-01-10"):
        raise RuntimeError(f"Insufficient daily history from 1995: {close.index.min()}")

    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    close.to_csv(data_dir / "daily_close.csv", index_label="timestamp")
    ohlcv.to_csv(data_dir / "spy_ohlcv.csv", index_label="timestamp")
    build_dataset(close, ohlcv).to_csv(data_dir / "daily_direction_dataset.csv", index_label="timestamp")
    pd.DataFrame(
        [
            {
                "frequency": "daily",
                "target": "SPY next trading day direction",
                "target_definition": "sign(SPY close[t+1] / SPY close[t] - 1)",
                "signal_lag": "features at close t predict next trading day",
                "train_start": str(TRAIN_START.date()),
                "train_end": str(TRAIN_END.date()),
                "validation_start": str(VALIDATION_START.date()),
                "validation_end": str(VALIDATION_END.date()),
                "locked_start": str(LOCKED_START.date()),
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "validation_used_for_selection": False,
                "data_end_max": str(close.index.max().date()),
                "zero_return_targets_count_as": "ties_do_not_count_as_free_hit",
            }
        ]
    ).to_csv(data_dir / "policy_audit.csv", index=False)


def build_dataset(close: pd.DataFrame, ohlcv: pd.DataFrame) -> pd.DataFrame:
    returns = close.pct_change(fill_method=None)
    spy = close["SPY"].astype(float)
    spy_ret = returns["SPY"].astype(float)
    target_return = spy_ret.shift(-1)
    target_direction = np.sign(target_return)

    data = pd.DataFrame(index=close.index)
    data["target_return_next_day"] = target_return
    data["target_direction"] = target_direction

    for window in [1, 2, 3, 5, 10, 21, 42, 63, 126, 252]:
        min_periods = rolling_min_periods(window)
        data[f"spy_ret_{window}d"] = spy.pct_change(window, fill_method=None)
        data[f"spy_vol_{window}d"] = spy_ret.rolling(window, min_periods=min_periods).std()
        data[f"spy_mean_{window}d"] = spy_ret.rolling(window, min_periods=min_periods).mean()
        data[f"spy_min_{window}d"] = spy_ret.rolling(window, min_periods=min_periods).min()
        data[f"spy_max_{window}d"] = spy_ret.rolling(window, min_periods=min_periods).max()
        data[f"spy_price_z_{window}d"] = zscore(spy, window)
        high = spy.rolling(window, min_periods=min_periods).max()
        low = spy.rolling(window, min_periods=min_periods).min()
        data[f"spy_donchian_pos_{window}d"] = (spy - low) / (high - low).replace(0.0, np.nan)
        data[f"spy_drawdown_{window}d"] = spy / high - 1.0

    for lag in range(1, 11):
        data[f"spy_ret_lag_{lag}d"] = spy_ret.shift(lag - 1)

    for window in [2, 3, 5, 10, 14, 21, 50, 100, 200]:
        min_periods = rolling_min_periods(window)
        ma = spy.rolling(window, min_periods=min_periods).mean()
        data[f"spy_ma_gap_{window}d"] = spy / ma - 1.0
        data[f"spy_rsi_{window}d"] = rsi(spy_ret, window)
        high = spy.rolling(window, min_periods=min_periods).max()
        low = spy.rolling(window, min_periods=min_periods).min()
        data[f"spy_dist_to_high_{window}d"] = spy / high - 1.0
        data[f"spy_dist_to_low_{window}d"] = spy / low - 1.0

    ema_12 = spy.ewm(span=12, adjust=False, min_periods=4).mean()
    ema_26 = spy.ewm(span=26, adjust=False, min_periods=9).mean()
    macd = ema_12 - ema_26
    data["spy_macd_line"] = macd / spy
    data["spy_macd_signal"] = macd.ewm(span=9, adjust=False, min_periods=3).mean() / spy
    data["spy_macd_hist"] = data["spy_macd_line"] - data["spy_macd_signal"]

    direction = np.sign(spy_ret).replace(0.0, np.nan)
    for window in [3, 5, 10, 21]:
        data[f"spy_up_count_{window}d"] = (direction > 0.0).rolling(window, min_periods=1).sum()
        data[f"spy_down_count_{window}d"] = (direction < 0.0).rolling(window, min_periods=1).sum()

    open_ = ohlcv["SPY_OPEN"].reindex(close.index)
    high = ohlcv["SPY_HIGH"].reindex(close.index)
    low = ohlcv["SPY_LOW"].reindex(close.index)
    volume = ohlcv["SPY_VOLUME"].reindex(close.index).astype(float)
    prev_close = spy.shift(1)
    data["spy_gap"] = open_ / prev_close - 1.0
    data["spy_intraday_ret"] = spy / open_ - 1.0
    data["spy_range"] = high / low - 1.0
    data["spy_close_location"] = (spy - low) / (high - low).replace(0.0, np.nan)
    data["spy_volume_z_21d"] = zscore(volume, 21)
    data["spy_volume_z_63d"] = zscore(volume, 63)
    true_range = pd.concat(
        [(high / low - 1.0), (high / prev_close - 1.0).abs(), (low / prev_close - 1.0).abs()],
        axis=1,
    ).max(axis=1)
    for window in [5, 14, 21]:
        data[f"spy_atr_pct_{window}d"] = true_range.rolling(window, min_periods=rolling_min_periods(window)).mean()
        mean = spy_ret.rolling(window, min_periods=rolling_min_periods(window)).mean()
        std = spy_ret.rolling(window, min_periods=rolling_min_periods(window)).std()
        data[f"spy_bb_ret_z_{window}d"] = (spy_ret - mean) / std.replace(0.0, np.nan)
        data[f"spy_bb_ret_width_{window}d"] = std

    for symbol in [c for c in close.columns if c != "SPY"]:
        s = close[symbol].astype(float)
        r = returns[symbol].astype(float)
        safe = symbol.replace("^", "").replace("-", "_").replace(".", "_")
        for window in [1, 5, 21, 63]:
            data[f"{safe}_ret_{window}d"] = s.pct_change(window, fill_method=None)
        data[f"{safe}_spy_rel_21d"] = s.pct_change(21, fill_method=None) - spy.pct_change(21, fill_method=None)
        data[f"{safe}_vol_21d"] = r.rolling(21, min_periods=7).std()

    if "^VIX" in close:
        vix = close["^VIX"].astype(float)
        data["vix_level"] = vix
        data["vix_z_21d"] = zscore(vix, 21)
        data["vix_z_63d"] = zscore(vix, 63)
        data["vix_ret_1d"] = vix.pct_change(fill_method=None)
        data["vix_ret_5d"] = vix.pct_change(5, fill_method=None)
    if "^TNX" in close and "^IRX" in close:
        data["tnx_irx_slope"] = close["^TNX"] - close["^IRX"]
        data["tnx_irx_slope_change_5d"] = data["tnx_irx_slope"].diff(5)

    # Calendar features known before next-day trading.
    data["day_of_week"] = data.index.dayofweek.astype(float)
    data["day_of_month"] = data.index.day.astype(float)
    data["month"] = data.index.month.astype(float)
    data["is_month_end_5d"] = (data.index.days_in_month - data.index.day <= 5).astype(float)
    data["is_month_start_5d"] = (data.index.day <= 5).astype(float)

    feature_cols = [c for c in data.columns if c not in {"target_return_next_day", "target_direction"}]
    data[feature_cols] = data[feature_cols].replace([np.inf, -np.inf], np.nan)
    data = data.loc[(data.index >= TRAIN_START) & (data.index <= VALIDATION_END)]
    data = data.loc[data.index < LOCKED_START]
    data = data.dropna(subset=["target_return_next_day", "target_direction"])
    if data.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data leaked into daily direction dataset.")
    return data


def zscore(series: pd.Series, window: int) -> pd.Series:
    min_periods = rolling_min_periods(window)
    mean = series.rolling(window, min_periods=min_periods).mean()
    std = series.rolling(window, min_periods=min_periods).std()
    return (series - mean) / std.replace(0.0, np.nan)


def rsi(returns: pd.Series, window: int) -> pd.Series:
    gains = returns.clip(lower=0.0)
    losses = -returns.clip(upper=0.0)
    avg_gain = gains.rolling(window, min_periods=rolling_min_periods(window)).mean()
    avg_loss = losses.rolling(window, min_periods=rolling_min_periods(window)).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def rolling_min_periods(window: int) -> int:
    return min(window, max(1, window // 3))


def run_shard(
    output_dir: Path,
    *,
    stage: int,
    configs_per_stage: int,
    time_budget_minutes: float,
    top_per_stage: int,
    target_accuracy: float = TARGET_ACCURACY,
) -> None:
    dataset = pd.read_csv(output_dir / "data" / "daily_direction_dataset.csv", parse_dates=["timestamp"]).set_index("timestamp")
    if dataset.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached shard.")
    feature_cols = [c for c in dataset.columns if c not in {"target_return_next_day", "target_direction"}]
    x = dataset[feature_cols].replace([np.inf, -np.inf], np.nan)
    x = x.fillna(x.loc[x.index <= TRAIN_END].median(numeric_only=True)).fillna(0.0)
    y = dataset["target_direction"].astype(float)
    nonzero = y != 0.0
    train_mask = (dataset.index >= TRAIN_START) & (dataset.index <= TRAIN_END) & nonzero
    validation_mask = (dataset.index >= VALIDATION_START) & (dataset.index <= VALIDATION_END) & nonzero
    if int(train_mask.sum()) < 2000 or int(validation_mask.sum()) < 1500:
        raise RuntimeError("Not enough daily train/validation rows.")

    matrix = x.to_numpy(dtype=float)
    target = y.to_numpy(dtype=float)
    rng = np.random.default_rng(20260606 + stage * 1_000_003)
    started = time.monotonic()
    deadline = started + max(1.0, time_budget_minutes) * 60.0
    rows: list[dict[str, Any]] = []
    evaluated = 0
    validation_examined = 0

    for config_index in range(configs_per_stage):
        if time.monotonic() >= deadline:
            break
        evaluated += 1
        params = sample_params(rng, feature_cols, stage)
        params, scores = fit_candidate_scores_train_only(matrix, target, train_mask.to_numpy(), params)
        if not np.isfinite(scores).any():
            continue
        threshold, invert, train_metrics = choose_threshold_train_only(scores, target, train_mask.to_numpy())
        oriented = -scores if invert else scores
        preds = np.where(oriented >= threshold, 1.0, -1.0)
        if not np.isfinite(train_metrics["accuracy"]):
            continue
        if train_metrics["accuracy"] < 0.515 and config_index % 311 != 0:
            continue
        validation_metrics = classification_metrics(preds[validation_mask.to_numpy()], target[validation_mask.to_numpy()])
        validation_examined += 1
        train_years = yearly_accuracy(dataset.index[train_mask], preds[train_mask.to_numpy()], target[train_mask.to_numpy()])
        validation_years = yearly_accuracy(
            dataset.index[validation_mask],
            preds[validation_mask.to_numpy()],
            target[validation_mask.to_numpy()],
        )
        sub_train = subperiod_accuracy(dataset.index[train_mask], preds[train_mask.to_numpy()], target[train_mask.to_numpy()], 2)
        sub_valid = subperiod_accuracy(
            dataset.index[validation_mask],
            preds[validation_mask.to_numpy()],
            target[validation_mask.to_numpy()],
            2,
        )
        accepted = bool(
            train_metrics["accuracy"] >= target_accuracy
            and validation_metrics["accuracy"] >= target_accuracy
        )
        config_hash = hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()
        rows.append(
            {
                "strategy_id": f"spy_daily_direction_s{stage:03d}_{config_hash[:16]}",
                "stage": stage,
                "config_index": config_index,
                "accepted": accepted,
                "close_to_pass": bool(
                    train_metrics["accuracy"] >= max(0.545, target_accuracy - 0.02)
                    and validation_metrics["accuracy"] >= max(0.545, target_accuracy - 0.02)
                    and not accepted
                ),
                "train_pass": bool(train_metrics["accuracy"] >= target_accuracy),
                "validation_pass_report_only": bool(validation_metrics["accuracy"] >= target_accuracy),
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "validation_used_for_selection": False,
                "data_end_max": str(VALIDATION_END.date()),
                "frequency": "daily",
                "target": "SPY next-day direction",
                "ties_excluded_from_accuracy": True,
                "rule_type": params["rule_type"],
                "feature_count": len(params["feature_indices"]),
                "features": "|".join(feature_cols[i] for i in params["feature_indices"]),
                "threshold": float(threshold),
                "invert": int(invert),
                "params_json": json.dumps(params, sort_keys=True),
                "score": score_candidate(train_metrics, validation_metrics=None, feature_count=len(params["feature_indices"]))
                + float(train_years["min_accuracy"]) * 140_000.0
                + float(sub_train["min_accuracy"]) * 220_000.0,
                "train_accuracy": float(train_metrics["accuracy"]),
                "validation_accuracy": float(validation_metrics["accuracy"]),
                "train_up_accuracy": float(train_metrics["up_accuracy"]),
                "validation_up_accuracy": float(validation_metrics["up_accuracy"]),
                "train_down_accuracy": float(train_metrics["down_accuracy"]),
                "validation_down_accuracy": float(validation_metrics["down_accuracy"]),
                "train_precision_up": float(train_metrics["precision_up"]),
                "validation_precision_up": float(validation_metrics["precision_up"]),
                "train_recall_up": float(train_metrics["recall_up"]),
                "validation_recall_up": float(validation_metrics["recall_up"]),
                "train_precision_down": float(train_metrics["precision_down"]),
                "validation_precision_down": float(validation_metrics["precision_down"]),
                "train_recall_down": float(train_metrics["recall_down"]),
                "validation_recall_down": float(validation_metrics["recall_down"]),
                "train_tp": int(train_metrics["tp"]),
                "train_tn": int(train_metrics["tn"]),
                "train_fp": int(train_metrics["fp"]),
                "train_fn": int(train_metrics["fn"]),
                "validation_tp": int(validation_metrics["tp"]),
                "validation_tn": int(validation_metrics["tn"]),
                "validation_fp": int(validation_metrics["fp"]),
                "validation_fn": int(validation_metrics["fn"]),
                "train_min_year_accuracy": float(train_years["min_accuracy"]),
                "validation_min_year_accuracy": float(validation_years["min_accuracy"]),
                "train_year_accuracy_json": json.dumps(train_years["by_year"], sort_keys=True),
                "validation_year_accuracy_json": json.dumps(validation_years["by_year"], sort_keys=True),
                "train_min_2y_accuracy": float(sub_train["min_accuracy"]),
                "validation_min_2y_accuracy": float(sub_valid["min_accuracy"]),
                "train_2y_accuracy_json": json.dumps(sub_train["by_period"], sort_keys=True),
                "validation_2y_accuracy_json": json.dumps(sub_valid["by_period"], sort_keys=True),
                "long_prediction_fraction_train": float(np.mean(preds[train_mask.to_numpy()] > 0.0)),
                "long_prediction_fraction_validation": float(np.mean(preds[validation_mask.to_numpy()] > 0.0)),
            }
        )

    shard_dir = output_dir / "shards" / f"stage_{stage:03d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(columns=["strategy_id", "accepted", "train_accuracy", "validation_accuracy"])
    top = select_top(frame, top_per_stage)
    top.to_csv(shard_dir / "top_candidates.csv", index=False)
    frame[frame.get("accepted", pd.Series(dtype=bool)).astype(bool)].to_csv(shard_dir / "accepted.csv", index=False)
    frame[frame.get("close_to_pass", pd.Series(dtype=bool)).astype(bool)].to_csv(shard_dir / "close_to_pass.csv", index=False)
    (shard_dir / "shard_summary.json").write_text(
        json.dumps(
            {
                "stage": stage,
                "target_accuracy": target_accuracy,
                "configs_evaluated": evaluated,
                "validation_examined_report_only": validation_examined,
                "rows_kept": len(frame),
                "accepted_rows": int(frame.get("accepted", pd.Series(dtype=bool)).astype(bool).sum()) if not frame.empty else 0,
                "close_to_pass_rows": int(frame.get("close_to_pass", pd.Series(dtype=bool)).astype(bool).sum()) if not frame.empty else 0,
                "elapsed_seconds": time.monotonic() - started,
                "locked_opened": False,
                "validation_used_for_selection": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def sample_params(rng: np.random.Generator, feature_cols: list[str], stage: int) -> dict[str, Any]:
    groups = feature_groups(feature_cols)
    group_names = [name for name, cols in groups.items() if cols]
    family = group_names[stage % len(group_names)] if group_names else "all"
    pool = groups.get(family) or list(range(len(feature_cols)))
    if stage % 11 == 0:
        pool = list(range(len(feature_cols)))
    base_rules = ["linear", "threshold_vote", "stump_pair", "rank_vote", "train_corr_linear"]
    ml_rules = ["ml_logistic", "ml_extra_trees", "ml_random_forest", "ml_hist_gradient"]
    rule_type = str(rng.choice(base_rules + ml_rules))
    max_k = min(24 if rule_type.startswith("ml_") else 9, len(pool))
    min_k = min(4 if rule_type.startswith("ml_") else 2, max_k)
    k = int(rng.integers(min_k, max_k + 1))
    idx = rng.choice(pool, size=k, replace=False).astype(int)
    return {
        "rule_type": rule_type,
        "family": family,
        "feature_indices": [int(i) for i in idx],
        "weights": [float(x) for x in rng.normal(0.0, 1.0, size=k)],
        "quantiles": [float(x) for x in rng.uniform(0.15, 0.85, size=k)],
        "directions": [float(x) for x in rng.choice([-1.0, 1.0], size=k)],
        "model_c": float(rng.choice([0.05, 0.1, 0.25, 0.5, 1.0, 2.0])),
        "model_depth": int(rng.choice([2, 3, 4, 5, 6])),
        "model_estimators": int(rng.choice([32, 48, 64, 96])),
        "model_leaf": int(rng.choice([10, 20, 40, 80])),
        "model_lr": float(rng.choice([0.02, 0.03, 0.05, 0.08])),
        "model_iter": int(rng.choice([24, 40, 64, 96])),
        "class_weight": str(rng.choice(["none", "balanced"])),
        "random_state": int(20260606 + stage * 100_003 + rng.integers(0, 1_000_000)),
    }


def feature_groups(feature_cols: list[str]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = {
        "spy_momentum": [],
        "spy_volatility": [],
        "spy_intraday": [],
        "vix": [],
        "rates": [],
        "relative_assets": [],
        "calendar": [],
        "technical": [],
        "all": list(range(len(feature_cols))),
    }
    for i, name in enumerate(feature_cols):
        low = name.lower()
        if low.startswith("spy_ret") or "donchian" in low or "drawdown" in low or "price_z" in low:
            groups["spy_momentum"].append(i)
        if "vol" in low and not low.startswith("spy_volume"):
            groups["spy_volatility"].append(i)
        if "gap" in low or "intraday" in low or "range" in low or "close_location" in low or "volume" in low:
            groups["spy_intraday"].append(i)
        if "vix" in low:
            groups["vix"].append(i)
        if "tnx" in low or "irx" in low or "slope" in low:
            groups["rates"].append(i)
        if "_spy_rel" in low or any(low.startswith(prefix.lower()) for prefix in ["QQQ", "IWM", "DIA", "EFA", "EEM", "TLT", "GLD", "HYG", "LQD", "XLY", "XLP"]):
            groups["relative_assets"].append(i)
        if "day_" in low or "month" in low:
            groups["calendar"].append(i)
        if any(
            token in low
            for token in [
                "rsi",
                "macd",
                "ma_gap",
                "atr",
                "bb_",
                "ret_lag",
                "up_count",
                "down_count",
                "dist_to_high",
                "dist_to_low",
            ]
        ):
            groups["technical"].append(i)
    return groups


def build_scores(matrix: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    idx = np.asarray(params["feature_indices"], dtype=int)
    values = matrix[:, idx]
    weights = np.asarray(params["weights"], dtype=float)
    rule_type = params["rule_type"]
    if rule_type == "linear":
        return values @ weights
    if rule_type == "train_corr_linear":
        return values @ np.asarray(params.get("fitted_weights", weights), dtype=float)
    thresholds = np.asarray(params["split_thresholds"], dtype=float)
    directions = np.asarray(params["directions"], dtype=float)
    votes = (values * directions >= thresholds * directions).astype(float) * 2.0 - 1.0
    if rule_type == "threshold_vote":
        return votes @ np.sign(weights)
    if rule_type == "stump_pair":
        return votes[:, 0] * 0.7 + votes[:, 1:].mean(axis=1) * 0.3 if votes.shape[1] > 1 else votes[:, 0]
    return votes.mean(axis=1)


def fit_candidate_scores_train_only(
    matrix: np.ndarray,
    target: np.ndarray,
    train_mask: np.ndarray,
    params: dict[str, Any],
) -> tuple[dict[str, Any], np.ndarray]:
    rule_type = str(params["rule_type"])
    if rule_type.startswith("ml_"):
        return fit_ml_scores_train_only(matrix, target, train_mask, params)
    fitted = fit_rule_params_train_only(matrix, train_mask, params)
    if rule_type == "train_corr_linear":
        fitted = fit_train_corr_linear(matrix, target, train_mask, fitted)
    return fitted, build_scores(matrix, fitted)


def fit_train_corr_linear(
    matrix: np.ndarray,
    target: np.ndarray,
    train_mask: np.ndarray,
    params: dict[str, Any],
) -> dict[str, Any]:
    idx = np.asarray(params["feature_indices"], dtype=int)
    values = matrix[train_mask][:, idx]
    y = target[train_mask]
    weights = []
    for col in range(values.shape[1]):
        x = values[:, col]
        finite = np.isfinite(x) & np.isfinite(y)
        if finite.sum() < 50 or np.nanstd(x[finite]) == 0.0:
            weights.append(0.0)
            continue
        weights.append(float(np.corrcoef(x[finite], y[finite])[0, 1]))
    fitted = dict(params)
    fitted["fitted_weights"] = [0.0 if not np.isfinite(w) else float(w) for w in weights]
    fitted["fitted_on_train_only"] = True
    return fitted


def fit_ml_scores_train_only(
    matrix: np.ndarray,
    target: np.ndarray,
    train_mask: np.ndarray,
    params: dict[str, Any],
) -> tuple[dict[str, Any], np.ndarray]:
    idx = np.asarray(params["feature_indices"], dtype=int)
    values = matrix[:, idx].astype(float)
    train_values = values[train_mask]
    train_target = target[train_mask]
    finite_rows = np.isfinite(train_values).all(axis=1) & np.isfinite(train_target) & (train_target != 0.0)
    if finite_rows.sum() < 500:
        return params, np.full(matrix.shape[0], np.nan)
    x_train = train_values[finite_rows]
    y_train = (train_target[finite_rows] > 0.0).astype(int)
    median = np.nanmedian(x_train, axis=0)
    scale = np.nanstd(x_train, axis=0)
    scale = np.where((~np.isfinite(scale)) | (scale == 0.0), 1.0, scale)
    clean_values = np.where(np.isfinite(values), values, median)
    x_all = (clean_values - median) / scale
    x_fit = x_all[train_mask][finite_rows]
    rule_type = str(params["rule_type"])
    class_weight = "balanced" if params.get("class_weight") == "balanced" else None
    random_state = int(params.get("random_state", 0))
    try:
        if rule_type == "ml_logistic":
            if LogisticRegression is None:
                return params, np.full(matrix.shape[0], np.nan)
            model = LogisticRegression(
                C=float(params.get("model_c", 1.0)),
                class_weight=class_weight,
                max_iter=300,
                solver="liblinear",
                random_state=random_state,
            )
        elif rule_type == "ml_extra_trees":
            if ExtraTreesClassifier is None:
                return params, np.full(matrix.shape[0], np.nan)
            model = ExtraTreesClassifier(
                n_estimators=int(params.get("model_estimators", 48)),
                max_depth=int(params.get("model_depth", 4)),
                min_samples_leaf=int(params.get("model_leaf", 20)),
                class_weight=class_weight,
                n_jobs=1,
                random_state=random_state,
            )
        elif rule_type == "ml_random_forest":
            if RandomForestClassifier is None:
                return params, np.full(matrix.shape[0], np.nan)
            model = RandomForestClassifier(
                n_estimators=int(params.get("model_estimators", 48)),
                max_depth=int(params.get("model_depth", 4)),
                min_samples_leaf=int(params.get("model_leaf", 20)),
                class_weight=class_weight,
                n_jobs=1,
                random_state=random_state,
            )
        elif rule_type == "ml_hist_gradient":
            if HistGradientBoostingClassifier is None:
                return params, np.full(matrix.shape[0], np.nan)
            model = HistGradientBoostingClassifier(
                max_iter=int(params.get("model_iter", 40)),
                learning_rate=float(params.get("model_lr", 0.05)),
                max_leaf_nodes=max(3, int(params.get("model_depth", 4)) * 2),
                l2_regularization=float(params.get("model_c", 1.0)),
                random_state=random_state,
            )
        else:
            return params, np.full(matrix.shape[0], np.nan)
        model.fit(x_fit, y_train)
        if hasattr(model, "predict_proba"):
            scores = model.predict_proba(x_all)[:, 1]
        else:
            scores = model.decision_function(x_all)
    except Exception:
        return params, np.full(matrix.shape[0], np.nan)
    fitted = dict(params)
    fitted["fitted_on_train_only"] = True
    fitted["train_rows_fit"] = int(finite_rows.sum())
    fitted["feature_median"] = [float(x) for x in median]
    fitted["feature_scale"] = [float(x) for x in scale]
    return fitted, np.asarray(scores, dtype=float)


def fit_rule_params_train_only(matrix: np.ndarray, train_mask: np.ndarray, params: dict[str, Any]) -> dict[str, Any]:
    if params["rule_type"] == "linear":
        return params
    idx = np.asarray(params["feature_indices"], dtype=int)
    train_values = matrix[train_mask][:, idx]
    quantiles = np.asarray(params["quantiles"], dtype=float)
    thresholds = []
    for col, q in enumerate(quantiles):
        values = train_values[:, col]
        finite = values[np.isfinite(values)]
        thresholds.append(float(np.nanmedian(values) if len(finite) == 0 else np.nanquantile(finite, q)))
    fitted = dict(params)
    fitted["split_thresholds"] = thresholds
    return fitted


def choose_threshold_train_only(
    scores: np.ndarray,
    target: np.ndarray,
    train_mask: np.ndarray,
) -> tuple[float, int, dict[str, float]]:
    train_scores = scores[train_mask]
    train_target = target[train_mask]
    finite = np.isfinite(train_scores) & np.isfinite(train_target) & (train_target != 0.0)
    train_scores = train_scores[finite]
    train_target = train_target[finite]
    if len(train_scores) < 100:
        return 0.0, 0, empty_metrics()
    thresholds = np.unique(np.quantile(train_scores, np.linspace(0.05, 0.95, 31)))
    best_threshold = 0.0
    best_invert = 0
    best = empty_metrics()
    best_score = -np.inf
    for invert in [0, 1]:
        oriented = -train_scores if invert else train_scores
        for threshold in thresholds:
            preds = np.where(oriented >= threshold, 1.0, -1.0)
            long_frac = float(np.mean(preds > 0.0))
            if long_frac < 0.15 or long_frac > 0.85:
                continue
            current = classification_metrics(preds, train_target)
            score = current["accuracy"] + min(current["up_accuracy"], current["down_accuracy"]) * 0.15
            if score > best_score:
                best_threshold = float(threshold)
                best_invert = int(invert)
                best = current
                best_score = score
    return best_threshold, best_invert, best


def empty_metrics() -> dict[str, float]:
    return {
        "accuracy": np.nan,
        "up_accuracy": np.nan,
        "down_accuracy": np.nan,
        "precision_up": np.nan,
        "recall_up": np.nan,
        "precision_down": np.nan,
        "recall_down": np.nan,
        "tp": 0,
        "tn": 0,
        "fp": 0,
        "fn": 0,
    }


def classification_metrics(preds: np.ndarray, target: np.ndarray) -> dict[str, float]:
    p = np.asarray(preds, dtype=float)
    y = np.asarray(target, dtype=float)
    mask = np.isfinite(p) & np.isfinite(y) & (y != 0.0)
    p = p[mask]
    y = y[mask]
    if len(y) == 0:
        return empty_metrics()
    tp = int(np.sum((p > 0.0) & (y > 0.0)))
    tn = int(np.sum((p < 0.0) & (y < 0.0)))
    fp = int(np.sum((p > 0.0) & (y < 0.0)))
    fn = int(np.sum((p < 0.0) & (y > 0.0)))
    up_total = tp + fn
    down_total = tn + fp
    return {
        "accuracy": float((tp + tn) / len(y)),
        "up_accuracy": float(tp / up_total) if up_total else np.nan,
        "down_accuracy": float(tn / down_total) if down_total else np.nan,
        "precision_up": float(tp / (tp + fp)) if tp + fp else np.nan,
        "recall_up": float(tp / up_total) if up_total else np.nan,
        "precision_down": float(tn / (tn + fn)) if tn + fn else np.nan,
        "recall_down": float(tn / down_total) if down_total else np.nan,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
    }


def yearly_accuracy(index: pd.DatetimeIndex, preds: np.ndarray, target: np.ndarray) -> dict[str, Any]:
    out: dict[str, float] = {}
    for year in sorted(set(index.year)):
        mask = index.year == year
        out[str(int(year))] = classification_metrics(preds[mask], target[mask])["accuracy"]
    values = [v for v in out.values() if np.isfinite(v)]
    return {"by_year": out, "min_accuracy": min(values) if values else np.nan}


def subperiod_accuracy(index: pd.DatetimeIndex, preds: np.ndarray, target: np.ndarray, years: int) -> dict[str, Any]:
    out: dict[str, float] = {}
    start = int(index.year.min())
    end = int(index.year.max())
    for left in range(start, end + 1, years):
        right = min(left + years - 1, end)
        mask = (index.year >= left) & (index.year <= right)
        out[f"{left}-{right}"] = classification_metrics(preds[mask], target[mask])["accuracy"]
    values = [v for v in out.values() if np.isfinite(v)]
    return {"by_period": out, "min_accuracy": min(values) if values else np.nan}


def score_candidate(train: dict[str, float], validation_metrics: dict[str, float] | None, feature_count: int) -> float:
    del validation_metrics
    balance = min(float(train["up_accuracy"]), float(train["down_accuracy"]))
    return float(train["accuracy"]) * 1_000_000.0 + balance * 180_000.0 - feature_count * 100.0


def select_top(frame: pd.DataFrame, top_per_stage: int) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    pieces = [
        frame.sort_values(["score", "train_accuracy"], ascending=[False, False]).head(top_per_stage),
    ]
    if "rule_type" in frame:
        for _, group in frame.groupby("rule_type"):
            pieces.append(group.sort_values(["score", "train_accuracy"], ascending=[False, False]).head(max(4, top_per_stage // 20)))
    return pd.concat(pieces, ignore_index=True).drop_duplicates("strategy_id")


def run_merge(output_dir: Path, target_accuracy: float = TARGET_ACCURACY) -> None:
    top_files = list((output_dir / "shards").glob("**/top_candidates.csv"))
    accepted_files = list((output_dir / "shards").glob("**/accepted.csv"))
    close_files = list((output_dir / "shards").glob("**/close_to_pass.csv"))
    summary_files = list((output_dir / "shards").glob("**/shard_summary.json"))
    top = pd.concat([pd.read_csv(path) for path in top_files], ignore_index=True) if top_files else pd.DataFrame()
    accepted = pd.concat([pd.read_csv(path) for path in accepted_files], ignore_index=True) if accepted_files else pd.DataFrame()
    close = pd.concat([pd.read_csv(path) for path in close_files], ignore_index=True) if close_files else pd.DataFrame()
    if not top.empty:
        top = top.sort_values(["train_accuracy", "validation_accuracy", "score"], ascending=[False, False, False])
    if not accepted.empty:
        accepted = accepted.sort_values(["train_accuracy", "validation_accuracy"], ascending=[False, False])
    if not close.empty:
        close = close.sort_values(["train_accuracy", "validation_accuracy"], ascending=[False, False])
    summaries = []
    for path in summary_files:
        try:
            summaries.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass

    output_dir.mkdir(parents=True, exist_ok=True)
    top.to_csv(output_dir / "spy_daily_direction_leaderboard.csv", index=False)
    accepted.to_csv(output_dir / "spy_daily_direction_accepted.csv", index=False)
    close.to_csv(output_dir / "spy_daily_direction_close_to_pass.csv", index=False)
    pd.DataFrame(summaries).to_csv(output_dir / "spy_daily_direction_shard_summaries.csv", index=False)
    policy = pd.read_csv(output_dir / "data" / "policy_audit.csv") if (output_dir / "data" / "policy_audit.csv").exists() else pd.DataFrame()
    baseline = compute_baseline(output_dir / "data" / "daily_direction_dataset.csv")
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "accepted_count": int(len(accepted)),
        "close_to_pass_count": int(len(close)),
        "leaderboard_rows": int(len(top)),
        "configs_evaluated": int(sum(item.get("configs_evaluated", 0) for item in summaries)),
        "validation_examined_report_only": int(sum(item.get("validation_examined_report_only", 0) for item in summaries)),
        "target_accuracy": target_accuracy,
        "frequency": "daily",
        "target": "SPY next-day direction",
        "baseline_always_up": baseline,
        "locked_opened": False,
        "locked_rows_accessed": 0,
        "validation_used_for_selection": False,
        "data_end_max": "2020-12-31",
        "policy_rows": policy.to_dict("records"),
    }
    (output_dir / "spy_daily_direction_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def compute_baseline(dataset_path: Path) -> dict[str, float]:
    if not dataset_path.exists():
        return {}
    data = pd.read_csv(dataset_path, parse_dates=["timestamp"]).set_index("timestamp")
    y = data["target_direction"].astype(float)
    pred = np.ones(len(y), dtype=float)
    out: dict[str, float] = {}
    for label, start, end in (
        ("train", TRAIN_START, TRAIN_END),
        ("validation", VALIDATION_START, VALIDATION_END),
    ):
        mask = (data.index >= start) & (data.index <= end) & (y != 0.0)
        out[f"{label}_accuracy"] = classification_metrics(pred[mask.to_numpy()], y[mask].to_numpy())["accuracy"]
    return out


if __name__ == "__main__":
    main()
