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
from numba import njit


CAMPAIGN_ID = "swr_floor_controller_mdd15_corr95_360jobs"
INITIAL_CAPITAL = 100_000.0
MONTHLY_WITHDRAWAL = 2_000.0
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2019-12-31")
LOCKED_START = pd.Timestamp("2020-01-01")
MIN_HORIZON_TRAIN = 120
MIN_HORIZON_VALIDATION = 60
MIN_HORIZON_TRAIN_STRESS = 36
MAX_MDD_AFTER_WITHDRAWALS = -0.15
MIN_PROXY_CORRELATION = 0.95

TRAIN_STRESS_WINDOWS = (
    (pd.Timestamp("1995-01-01"), pd.Timestamp("1998-12-31")),
    (pd.Timestamp("1997-01-01"), pd.Timestamp("2002-12-31")),
    (pd.Timestamp("1999-01-01"), pd.Timestamp("2004-12-31")),
    (pd.Timestamp("2001-01-01"), pd.Timestamp("2006-12-31")),
    (pd.Timestamp("2003-01-01"), pd.Timestamp("2008-12-31")),
    (pd.Timestamp("2005-01-01"), pd.Timestamp("2010-12-31")),
)

PROXIES = {
    "ndx": {"symbol": "^NDX", "tradable_proxy": "QQQ", "proxy_correlation": 0.999176},
    "sp500": {"symbol": "VFINX", "tradable_proxy": "SPY", "proxy_correlation": 0.998036},
    "small": {"symbol": "NAESX", "tradable_proxy": "IWM", "proxy_correlation": 0.990462},
    "long_treasury": {"symbol": "VUSTX", "tradable_proxy": "TLT", "proxy_correlation": 0.989280},
    "intermediate_treasury": {"symbol": "VFITX", "tradable_proxy": "IEF", "proxy_correlation": 0.981267},
    "short_treasury": {"symbol": "VFISX", "tradable_proxy": "SHY", "proxy_correlation": 0.951884},
    "energy": {"symbol": "FSENX", "tradable_proxy": "XLE", "proxy_correlation": 0.969365},
    "financial": {"symbol": "FIDSX", "tradable_proxy": "XLF", "proxy_correlation": 0.966307},
    "inverse_sp500": {"symbol": "RYURX", "tradable_proxy": "SH", "proxy_correlation": 0.996929},
}


@njit
def eval_all_starts(port_ret: np.ndarray, min_horizon: int) -> tuple[int, int, float, float, int, int]:
    failed = 0
    final_le_initial = 0
    min_final = 1.0e18
    worst_mdd = 0.0
    worst_final_i = -1
    worst_mdd_i = -1
    n = len(port_ret)
    for start in range(n):
        if n - start < min_horizon:
            continue
        cap = INITIAL_CAPITAL
        peak = INITIAL_CAPITAL
        mdd = 0.0
        path_failed = False
        for i in range(start, n):
            cap -= MONTHLY_WITHDRAWAL
            if cap <= 0.0:
                path_failed = True
                break
            r = port_ret[i]
            if r < -0.98:
                path_failed = True
                break
            cap *= 1.0 + r
            if cap <= 0.0:
                path_failed = True
                break
            if cap > peak:
                peak = cap
            dd = cap / peak - 1.0
            if dd < mdd:
                mdd = dd
        if path_failed:
            failed += 1
        if cap <= INITIAL_CAPITAL:
            final_le_initial += 1
        if cap < min_final:
            min_final = cap
            worst_final_i = start
        if mdd < worst_mdd:
            worst_mdd = mdd
            worst_mdd_i = start
    return failed, final_le_initial, min_final, worst_mdd, worst_final_i, worst_mdd_i


@njit
def eval_floor_controller_all_starts(
    risky_ret: np.ndarray,
    safe_ret: np.ndarray,
    min_horizon: int,
    safe_leverage: float,
    risk_buffer: float,
    max_state_scale: float,
    de_risk_drawdown: float,
    de_risk_fraction: float,
) -> tuple[int, int, float, float, int, int]:
    failed = 0
    final_le_initial = 0
    min_final = 1.0e18
    worst_mdd = 0.0
    worst_final_i = -1
    worst_mdd_i = -1
    n = len(risky_ret)
    floor_fraction = 1.0 + MAX_MDD_AFTER_WITHDRAWALS
    for start in range(n):
        if n - start < min_horizon:
            continue
        cap = INITIAL_CAPITAL
        peak = INITIAL_CAPITAL
        mdd = 0.0
        path_failed = False
        for i in range(start, n):
            cap -= MONTHLY_WITHDRAWAL
            if cap <= 0.0:
                path_failed = True
                break
            floor_value = peak * floor_fraction
            cushion = cap - floor_value
            if cushion <= 0.0:
                state_scale = 0.0
            else:
                state_scale = cushion / (peak * risk_buffer)
                if state_scale > max_state_scale:
                    state_scale = max_state_scale
                if state_scale < 0.0:
                    state_scale = 0.0
            current_dd = cap / peak - 1.0
            if current_dd <= de_risk_drawdown:
                state_scale *= de_risk_fraction
            r = safe_ret[i] * safe_leverage + risky_ret[i] * state_scale
            if r < -0.98:
                path_failed = True
                break
            cap *= 1.0 + r
            if cap <= 0.0:
                path_failed = True
                break
            if cap > peak:
                peak = cap
            dd = cap / peak - 1.0
            if dd < mdd:
                mdd = dd
        if path_failed:
            failed += 1
        if cap <= INITIAL_CAPITAL:
            final_le_initial += 1
        if cap < min_final:
            min_final = cap
            worst_final_i = start
        if mdd < worst_mdd:
            worst_mdd = mdd
            worst_mdd_i = start
    return failed, final_le_initial, min_final, worst_mdd, worst_final_i, worst_mdd_i


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["data", "shard", "merge"], required=True)
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--family-id", type=int, default=0)
    parser.add_argument("--shard-id", type=int, default=0)
    parser.add_argument("--configs-per-shard", type=int, default=80_000)
    parser.add_argument("--time-budget-minutes", type=float, default=45.0)
    parser.add_argument("--top-per-shard", type=int, default=80)
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "data":
        run_data(output_dir)
    elif args.mode == "shard":
        run_shard(output_dir, args.family_id, args.shard_id, args.configs_per_shard, args.time_budget_minutes, args.top_per_shard)
    else:
        run_merge(output_dir)


def run_data(output_dir: Path) -> None:
    for name, meta in PROXIES.items():
        if meta["proxy_correlation"] < MIN_PROXY_CORRELATION:
            raise RuntimeError(f"Proxy below threshold: {name}")
    raw = yf.download(
        [meta["symbol"] for meta in PROXIES.values()],
        start="1995-01-01",
        end="2020-01-01",
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    prices = pd.DataFrame()
    for name, meta in PROXIES.items():
        symbol = meta["symbol"]
        close = raw[symbol]["Close"] if isinstance(raw.columns, pd.MultiIndex) and symbol in raw.columns.get_level_values(0) else raw.get("Close", pd.Series(dtype=float))
        if close.empty or close.dropna().empty:
            single = yf.download(symbol, start="1995-01-01", end="2020-01-01", auto_adjust=True, progress=False, threads=False)
            close = single["Close"] if "Close" in single else pd.Series(dtype=float)
        if close.empty or close.dropna().empty:
            raise RuntimeError(f"Missing proxy data for {name} ({symbol})")
        prices[name] = close
    prices = prices.dropna(how="any")
    monthly = prices.resample("ME").last().pct_change().dropna()
    if prices.index.max() >= LOCKED_START or monthly.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data leak.")
    if monthly.index.min() > pd.Timestamp("1995-02-28"):
        raise RuntimeError(f"Insufficient 1995 history: {monthly.index.min()}")
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(data_dir / "monthly_returns.csv", index_label="timestamp")
    pd.DataFrame(
        [
            {
                "sleeve": name,
                **meta,
                "proxy_correlation_min_required": MIN_PROXY_CORRELATION,
                "uses_concrete_stocks": False,
                "uses_crypto": False,
                "locked_opened": False,
                "data_end_max": "2019-12-31",
            }
            for name, meta in PROXIES.items()
        ]
    ).to_csv(data_dir / "proxy_map.csv", index=False)
    pd.DataFrame(
        [{"locked_start": "2020-01-01", "locked_opened": False, "locked_rows_accessed": 0, "max_data_date": "2019-12-31", "validation_used_for_selection": False}]
    ).to_csv(data_dir / "locked_access_audit.csv", index=False)


def run_shard(output_dir: Path, family_id: int, shard_id: int, configs_per_shard: int, time_budget_minutes: float, top_per_shard: int) -> None:
    returns = pd.read_csv(output_dir / "data" / "monthly_returns.csv", parse_dates=["timestamp"]).set_index("timestamp")
    if returns.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached shard.")
    assets = list(PROXIES)
    train = returns[returns.index <= TRAIN_END]
    valid = returns[(returns.index >= VALIDATION_START) & (returns.index <= VALIDATION_END)]
    stress_frames = [returns[(returns.index >= start) & (returns.index <= end)] for start, end in TRAIN_STRESS_WINDOWS]
    eval_all_starts(np.zeros(130, dtype=np.float64), 60)
    eval_floor_controller_all_starts(np.zeros(130, dtype=np.float64), np.zeros(130, dtype=np.float64), 60, 1.0, 0.1, 1.0, -0.05, 0.5)
    rng = np.random.default_rng(91_000_019 + family_id * 1_000_003 + shard_id * 1009)
    rows: list[dict[str, Any]] = []
    started = time.monotonic()
    deadline = started + max(1.0, time_budget_minutes) * 60.0
    evaluated = 0
    validation_evaluated = 0
    for config_index in range(configs_per_shard):
        if time.monotonic() >= deadline:
            break
        evaluated += 1
        params = sample_params(rng, family_id, assets)
        weights_frame = build_timing_weights(returns[assets], params, assets)
        risky_port = (returns[assets] * weights_frame).sum(axis=1)
        safe_port = returns["short_treasury"]
        if risky_port.min() <= -0.98:
            continue
        train_port = risky_port.loc[train.index]
        train_safe = safe_port.loc[train.index]
        train_eval = eval_floor_controller_all_starts(
            train_port.to_numpy(np.float64),
            train_safe.to_numpy(np.float64),
            MIN_HORIZON_TRAIN,
            float(params["safe_leverage"]),
            float(params["risk_buffer"]),
            float(params["max_state_scale"]),
            float(params["de_risk_drawdown"]),
            float(params["de_risk_fraction"]),
        )
        stress_evals = [
            eval_floor_controller_all_starts(
                risky_port.loc[frame.index].to_numpy(np.float64),
                safe_port.loc[frame.index].to_numpy(np.float64),
                MIN_HORIZON_TRAIN_STRESS,
                float(params["safe_leverage"]),
                float(params["risk_buffer"]),
                float(params["max_state_scale"]),
                float(params["de_risk_drawdown"]),
                float(params["de_risk_fraction"]),
            )
            for frame in stress_frames
        ]
        stress_failed = int(sum(item[0] for item in stress_evals))
        stress_le_initial = int(sum(item[1] for item in stress_evals))
        stress_worst_mdd = float(min(item[3] for item in stress_evals))
        stress_worst_final = float(min(item[2] for item in stress_evals))
        full_train_pass = train_eval[0] == 0 and train_eval[1] == 0 and train_eval[3] > MAX_MDD_AFTER_WITHDRAWALS
        stress_train_pass = stress_failed == 0 and stress_le_initial == 0 and stress_worst_mdd > MAX_MDD_AFTER_WITHDRAWALS
        train_pass = full_train_pass and stress_train_pass
        metrics = return_metrics(train_port)
        train_score = train_only_score(train_eval, stress_evals, metrics, train_pass, params)
        if not train_pass and train_score < -500_000_000.0 and config_index % 503 != 0:
            continue
        valid_port = risky_port.loc[valid.index]
        valid_safe = safe_port.loc[valid.index]
        valid_eval = eval_floor_controller_all_starts(
            valid_port.to_numpy(np.float64),
            valid_safe.to_numpy(np.float64),
            MIN_HORIZON_VALIDATION,
            float(params["safe_leverage"]),
            float(params["risk_buffer"]),
            float(params["max_state_scale"]),
            float(params["de_risk_drawdown"]),
            float(params["de_risk_fraction"]),
        )
        validation_evaluated += 1
        validation_pass = valid_eval[0] == 0 and valid_eval[1] == 0 and valid_eval[3] > MAX_MDD_AFTER_WITHDRAWALS
        avg_weights = weights_frame.loc[train.index].mean().to_dict()
        max_abs_weight = float(weights_frame.abs().sum(axis=1).max())
        config_hash = hashlib.sha256(json.dumps({"params": params}, sort_keys=True).encode("utf-8")).hexdigest()
        rows.append(
            {
                "strategy_id": f"swr_floor_controller_mdd15_corr95_f{family_id:02d}_s{shard_id:02d}_{config_hash[:16]}",
                "family_id": family_id,
                "shard_id": shard_id,
                "config_index": config_index,
                "train_pass": bool(train_pass),
                "full_train_pass": bool(full_train_pass),
                "stress_train_pass": bool(stress_train_pass),
                "validation_pass_report_only": bool(validation_pass),
                "final_verified_report_only": bool(train_pass and validation_pass),
                "validation_used_for_selection": False,
                "train_failed_starts": int(train_eval[0]),
                "validation_failed_starts": int(valid_eval[0]),
                "train_final_le_initial_count": int(train_eval[1]),
                "validation_final_le_initial_count": int(valid_eval[1]),
                "worst_final_capital_train": float(train_eval[2]),
                "worst_final_capital_validation": float(valid_eval[2]),
                "mdd_after_withdrawals_train": float(train_eval[3]),
                "mdd_after_withdrawals_validation": float(valid_eval[3]),
                "stress_failed_starts_train": int(stress_failed),
                "stress_final_le_initial_count_train": int(stress_le_initial),
                "stress_worst_final_capital_train": float(stress_worst_final),
                "stress_worst_mdd_after_withdrawals_train": float(stress_worst_mdd),
                "train_mean_monthly": float(metrics["mean"]),
                "train_std_monthly": float(metrics["std"]),
                "train_min_monthly": float(metrics["min"]),
                "train_sharpe_monthly_ann": float(metrics["sharpe"]),
                "gross_exposure": max_abs_weight,
                "safe_leverage": float(params["safe_leverage"]),
                "risk_buffer": float(params["risk_buffer"]),
                "max_state_scale": float(params["max_state_scale"]),
                "de_risk_drawdown": float(params["de_risk_drawdown"]),
                "de_risk_fraction": float(params["de_risk_fraction"]),
                "net_exposure": float(weights_frame.loc[train.index].sum(axis=1).mean()),
                "uses_concrete_stocks": False,
                "uses_crypto": False,
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "data_end_max": "2019-12-31",
                "proxy_corr_min": min(meta["proxy_correlation"] for meta in PROXIES.values()),
                "max_mdd_after_withdrawals_required": MAX_MDD_AFTER_WITHDRAWALS,
                "params_json": json.dumps(params, sort_keys=True),
                "avg_train_weights_json": json.dumps({asset: float(avg_weights.get(asset, 0.0)) for asset in assets}, sort_keys=True),
                "config_hash": config_hash,
                "train_score": float(train_score),
                "score": float(train_score),
            }
        )
    shard_dir = output_dir / "shards" / f"family_{family_id:02d}_shard_{shard_id:02d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["strategy_id", "train_score", "final_verified_report_only"])
    df.sort_values("train_score", ascending=False).head(top_per_shard).to_csv(shard_dir / "top_candidates.csv", index=False)
    verified = df[df.get("final_verified_report_only", pd.Series(dtype=bool)).astype(bool)]
    verified.to_csv(shard_dir / "verified_candidates_report_only.csv", index=False)
    (shard_dir / "shard_summary.json").write_text(
        json.dumps(
            {
                "family_id": family_id,
                "shard_id": shard_id,
                "configs_requested": int(configs_per_shard),
                "configs_evaluated": int(evaluated),
                "validation_evaluated_report_only": int(validation_evaluated),
                "elapsed_seconds": float(time.monotonic() - started),
                "time_budget_minutes": float(time_budget_minutes),
                "rows_kept": int(len(df)),
                "train_pass_rows": int(df.get("train_pass", pd.Series(dtype=bool)).astype(bool).sum()) if "train_pass" in df else 0,
                "final_verified_report_only_rows": int(len(verified)),
                "max_mdd_after_withdrawals_required": MAX_MDD_AFTER_WITHDRAWALS,
                "proxy_corr_min": min(meta["proxy_correlation"] for meta in PROXIES.values()),
                "locked_opened": False,
                "validation_used_for_selection": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def sample_params(rng: np.random.Generator, family_id: int, assets: list[str]) -> dict[str, Any]:
    return {
        "family_id": family_id,
        "gross": float(rng.uniform(0.0, 16.0 if family_id >= 8 else 10.0)),
        "lookback": int(rng.choice([1, 3, 6, 10, 12])),
        "vol_lookback": int(rng.choice([3, 6, 12])),
        "top_n": int(rng.choice([1, 2, 3, 4])),
        "bottom_n": int(rng.choice([0, 1, 2, 3])),
        "mode": str(rng.choice(["long_top", "long_top_short_bottom", "crisis_hedge", "risk_switch", "short_downtrend"])),
        "risk_threshold": float(rng.uniform(-0.08, 0.08)),
        "cash_threshold": float(rng.uniform(-0.03, 0.06)),
        "vol_penalty": float(rng.uniform(0.0, 2.5)),
        "treasury_bonus": float(rng.uniform(0.0, 1.0)),
        "inverse_bonus": float(rng.uniform(0.0, 1.5)),
        "equity_bonus": float(rng.uniform(-0.5, 0.8)),
        "safe_leverage": float(rng.uniform(0.0, 18.0)),
        "risk_buffer": float(rng.choice([0.03, 0.05, 0.075, 0.10, 0.15, 0.20, 0.30])),
        "max_state_scale": float(rng.uniform(0.0, 4.0)),
        "de_risk_drawdown": float(rng.uniform(-0.14, -0.02)),
        "de_risk_fraction": float(rng.uniform(0.0, 0.75)),
    }


def build_timing_weights(returns: pd.DataFrame, params: dict[str, Any], assets: list[str]) -> pd.DataFrame:
    lookback = int(params["lookback"])
    vol_lookback = int(params["vol_lookback"])
    momentum = (1.0 + returns).rolling(lookback).apply(np.prod, raw=True).shift(1) - 1.0
    vol = returns.rolling(vol_lookback).std(ddof=0).shift(1).replace(0.0, np.nan)
    score = momentum / (vol.pow(float(params["vol_penalty"])) + 1.0e-12)
    for asset in assets:
        if "treasury" in asset:
            score[asset] = score[asset] + float(params["treasury_bonus"])
        elif asset == "inverse_sp500":
            score[asset] = score[asset] + float(params["inverse_bonus"])
        elif asset in {"ndx", "sp500", "small", "energy", "financial"}:
            score[asset] = score[asset] + float(params["equity_bonus"])
    risk_signal = momentum[["sp500", "ndx", "small"]].mean(axis=1)
    weights = pd.DataFrame(0.0, index=returns.index, columns=assets)
    gross = float(params["gross"])
    top_n = max(1, min(int(params["top_n"]), len(assets)))
    bottom_n = max(0, min(int(params["bottom_n"]), len(assets) - top_n))
    mode = str(params["mode"])
    for idx in returns.index:
        row = score.loc[idx].dropna()
        if row.empty or gross <= 0.0:
            continue
        risk = float(risk_signal.loc[idx]) if pd.notna(risk_signal.loc[idx]) else 0.0
        ordered = row.sort_values(ascending=False)
        top = list(ordered.head(top_n).index)
        bottom = list(ordered.tail(bottom_n).index) if bottom_n else []
        if mode == "long_top":
            if risk < float(params["cash_threshold"]):
                continue
            weights.loc[idx, top] = gross / len(top)
        elif mode == "long_top_short_bottom":
            weights.loc[idx, top] = gross * 0.65 / len(top)
            if bottom:
                weights.loc[idx, bottom] = -gross * 0.35 / len(bottom)
        elif mode == "crisis_hedge":
            if risk < float(params["risk_threshold"]):
                hedge = [asset for asset in ["inverse_sp500", "long_treasury", "intermediate_treasury", "short_treasury"] if asset in assets]
                weights.loc[idx, hedge] = gross / len(hedge)
            elif risk > float(params["cash_threshold"]):
                risk_assets = [asset for asset in top if asset in {"ndx", "sp500", "small", "energy", "financial"}] or top
                weights.loc[idx, risk_assets] = gross / len(risk_assets)
        elif mode == "risk_switch":
            if risk >= float(params["risk_threshold"]):
                weights.loc[idx, top] = gross / len(top)
            else:
                defensive = [asset for asset in ["short_treasury", "intermediate_treasury", "long_treasury", "inverse_sp500"] if asset in assets]
                weights.loc[idx, defensive] = gross / len(defensive)
        elif mode == "short_downtrend":
            if risk < float(params["risk_threshold"]):
                shortable = [asset for asset in ["sp500", "ndx", "small", "energy", "financial"] if asset in assets]
                weights.loc[idx, shortable] = -gross / len(shortable)
                weights.loc[idx, "short_treasury"] += gross * 0.25
            elif risk > float(params["cash_threshold"]):
                weights.loc[idx, top] = gross / len(top)
    return weights.fillna(0.0)


def return_metrics(series: pd.Series) -> dict[str, float]:
    mean = float(series.mean())
    std = float(series.std(ddof=0))
    sharpe = mean / std * math.sqrt(12.0) if std > 0 else 0.0
    return {"mean": mean, "std": std, "min": float(series.min()), "sharpe": sharpe}


def train_only_score(
    result: tuple[int, int, float, float, int, int],
    stress_results: list[tuple[int, int, float, float, int, int]],
    metrics: dict[str, float],
    train_pass: bool,
    params: dict[str, Any],
) -> float:
    failed, le_initial, worst_final, mdd, _, _ = result
    stress_failed = sum(item[0] for item in stress_results)
    stress_le_initial = sum(item[1] for item in stress_results)
    stress_final = min(item[2] for item in stress_results)
    stress_mdd = min(item[3] for item in stress_results)
    gross = float(params["gross"])
    return (
        (1_000_000_000.0 if train_pass else 0.0)
        - failed * 30_000_000.0
        - le_initial * 3_000_000.0
        - stress_failed * 18_000_000.0
        - stress_le_initial * 1_800_000.0
        + min(worst_final, 10_000_000.0)
        + min(stress_final, 5_000_000.0) * 0.35
        + min(mdd, stress_mdd) * 70_000_000.0
        + metrics["mean"] * 500_000_000.0
        + metrics["sharpe"] * 2_000_000.0
        + metrics["min"] * 50_000_000.0
        - gross * 25_000.0
    )


def run_merge(output_dir: Path) -> None:
    top_files = list((output_dir / "shards").glob("**/top_candidates.csv"))
    verified_files = list((output_dir / "shards").glob("**/verified_candidates_report_only.csv"))
    summary_files = list((output_dir / "shards").glob("**/shard_summary.json"))
    top = pd.concat([pd.read_csv(path) for path in top_files], ignore_index=True) if top_files else pd.DataFrame()
    verified = pd.concat([pd.read_csv(path) for path in verified_files], ignore_index=True) if verified_files else pd.DataFrame()
    if not top.empty:
        top = top.sort_values("train_score", ascending=False)
    if not verified.empty:
        verified = verified.sort_values("train_score", ascending=False)
    top.to_csv(output_dir / "all_top_candidates.csv", index=False)
    verified.to_csv(output_dir / "verified_floor_controller_mdd15_report_only.csv", index=False)
    train_pass = top[top.get("train_pass", pd.Series(dtype=bool)).astype(bool)] if "train_pass" in top else pd.DataFrame()
    train_pass.to_csv(output_dir / "train_pass_candidates.csv", index=False)
    for name in ["proxy_map.csv", "locked_access_audit.csv"]:
        src = output_dir / "data" / name
        if src.exists():
            pd.read_csv(src).to_csv(output_dir / name, index=False)
    shard_summaries: list[dict[str, Any]] = []
    for path in summary_files:
        try:
            shard_summaries.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    pd.DataFrame(shard_summaries).to_csv(output_dir / "shard_summaries.csv", index=False)
    build_fail_reasons(top).to_csv(output_dir / "fail_reasons.csv", index=False)
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "strategy_type": "monthly_floor_controller",
        "signals_are_lagged": True,
        "train_stress_hard_gate": True,
        "verified_count_report_only": int(len(verified)),
        "train_pass_count": int(len(train_pass)),
        "top_candidate_rows": int(len(top)),
        "shards_with_summary": int(len(shard_summaries)),
        "configs_evaluated": int(sum(item.get("configs_evaluated", 0) for item in shard_summaries)),
        "validation_evaluated_report_only": int(sum(item.get("validation_evaluated_report_only", 0) for item in shard_summaries)),
        "proxy_corr_min": min(meta["proxy_correlation"] for meta in PROXIES.values()),
        "max_mdd_after_withdrawals_required": MAX_MDD_AFTER_WITHDRAWALS,
        "monthly_withdrawal": MONTHLY_WITHDRAWAL,
        "initial_capital": INITIAL_CAPITAL,
        "locked_opened": False,
        "locked_rows_accessed": 0,
        "validation_used_for_selection": False,
        "uses_concrete_stocks": False,
        "uses_crypto": False,
        "data_end_max": "2019-12-31",
    }
    (output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def build_fail_reasons(top: pd.DataFrame) -> pd.DataFrame:
    reasons: list[str] = []
    if top.empty:
        return pd.DataFrame([{"reason": "no_candidates", "count": 0}])
    for _, row in top.iterrows():
        if bool(row.get("final_verified_report_only", False)):
            continue
        if not bool(row.get("train_pass", False)):
            if bool(row.get("full_train_pass", False)) and not bool(row.get("stress_train_pass", False)):
                reason = "train_stress_gate_failed"
            elif int(row.get("train_failed_starts", 0)) > 0:
                reason = "train_failed_withdrawal_path"
            elif int(row.get("train_final_le_initial_count", 0)) > 0:
                reason = "train_final_capital_not_above_initial"
            else:
                reason = "train_mdd_after_withdrawals_gt_15pct"
        elif int(row.get("validation_failed_starts", 0)) > 0:
            reason = "validation_failed_withdrawal_path_report_only"
        elif int(row.get("validation_final_le_initial_count", 0)) > 0:
            reason = "validation_final_capital_not_above_initial_report_only"
        elif float(row.get("mdd_after_withdrawals_validation", -1.0)) <= MAX_MDD_AFTER_WITHDRAWALS:
            reason = "validation_mdd_after_withdrawals_gt_15pct_report_only"
        else:
            reason = "other"
        reasons.append(reason)
    return pd.Series(reasons).value_counts().rename_axis("reason").reset_index(name="count")


if __name__ == "__main__":
    main()
