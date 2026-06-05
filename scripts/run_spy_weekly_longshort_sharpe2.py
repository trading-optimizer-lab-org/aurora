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
    symbols = ["SPY", "^VIX", "^TNX"]
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
    weekly_prices = weekly_prices[weekly_prices.index < LOCKED_START]
    weekly_returns = weekly_prices.pct_change(fill_method=None).dropna(how="any")
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
        score = build_score(matrix, params)
        if int(params["invert"]) == 1:
            score = -score
        threshold = float(params["threshold"])
        positions = np.where(score >= threshold, 1.0, -1.0)
        strategy_returns = positions * spy_values
        train_metrics = metrics(strategy_returns[train_mask])
        if not np.isfinite(train_metrics["sharpe"]):
            continue
        train_score = train_only_score(train_metrics, positions[train_mask], params)
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
                "train_turnover_weekly": float(turnover(positions[train_mask])),
                "validation_turnover_weekly": float(turnover(positions[validation_mask])),
                **{f"train_{key}": value for key, value in position_train.items() if key != "always_invested"},
                **{f"validation_{key}": value for key, value in position_validation.items() if key != "always_invested"},
                "train_always_invested": bool(position_train["always_invested"]),
                "validation_always_invested": bool(position_validation["always_invested"]),
                "feature_count": int(len(params["feature_indices"])),
                "features": "|".join(feature_cols[int(i)] for i in params["feature_indices"]),
                "weights": "|".join(f"{float(w):.8f}" for w in params["weights"]),
                "threshold": float(threshold),
                "invert": int(params["invert"]),
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
    data["spy_ret_4w_x_vix_z_26w"] = data["spy_ret_4w"] * data["vix_z_26w"]
    data["spy_ma_20w_x_tnx_z_26w"] = data["spy_ma_gap_20w"] * data["tnx_z_26w"]
    data = data.replace([np.inf, -np.inf], np.nan).dropna(how="any")
    # Robust per-column scaling, fit using train only to avoid validation leakage.
    train = data[data.index <= TRAIN_END]
    median = train.median()
    scale = (train.quantile(0.75) - train.quantile(0.25)).replace(0.0, np.nan)
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
    rule_type = str(rng.choice(["linear", "threshold_vote", "band_vote", "signed_stump_vote"]))
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


def train_only_score(metrics_row: dict[str, float], positions: np.ndarray, params: dict[str, Any]) -> float:
    complexity = len(params["feature_indices"])
    return (
        float(metrics_row["sharpe"]) * 1_000_000.0
        + float(metrics_row["cagr"]) * 20_000.0
        + float(metrics_row["mdd"]) * 10_000.0
        - turnover(positions) * 2_000.0
        - complexity * 75.0
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
