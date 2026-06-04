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


CAMPAIGN_ID = "swr_daily_tactical_mdd15_trainonly_corr95_360jobs"
INITIAL_CAPITAL = 100_000.0
MONTHLY_WITHDRAWAL = 2_000.0
TRAIN_END = pd.Timestamp("2010-12-31")
TRAIN_CV_SPLIT = pd.Timestamp("2003-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2019-12-31")
LOCKED_START = pd.Timestamp("2020-01-01")
MIN_MONTHS_TRAIN = 120
MIN_MONTHS_VALIDATION = 60
MAX_MDD_AFTER_WITHDRAWALS = -0.15
MIN_PROXY_CORRELATION = 0.95

TRAIN_STRESS_WINDOWS = (
    (pd.Timestamp("1995-01-01"), pd.Timestamp("1998-12-31")),
    (pd.Timestamp("1999-01-01"), pd.Timestamp("2004-12-31")),
    (pd.Timestamp("2005-01-01"), pd.Timestamp("2010-12-31")),
)

PROXIES = {
    "ndx": {"symbol": "^NDX", "tradable_proxy": "QQQ", "proxy_correlation": 0.999176},
    "sp500": {"symbol": "VFINX", "tradable_proxy": "SPY", "proxy_correlation": 0.998036},
    "small": {"symbol": "NAESX", "tradable_proxy": "IWM", "proxy_correlation": 0.990462},
    "value": {"symbol": "VIVAX", "tradable_proxy": "IWD", "proxy_correlation": 0.987293},
    "growth": {"symbol": "VIGRX", "tradable_proxy": "IWF", "proxy_correlation": 0.982302},
    "emerging": {"symbol": "VEIEX", "tradable_proxy": "VWO", "proxy_correlation": 0.990938},
    "long_treasury": {"symbol": "VUSTX", "tradable_proxy": "TLT", "proxy_correlation": 0.989280},
    "intermediate_treasury": {"symbol": "VFITX", "tradable_proxy": "IEF", "proxy_correlation": 0.981267},
    "short_treasury": {"symbol": "VFISX", "tradable_proxy": "SHY", "proxy_correlation": 0.951884},
    "energy": {"symbol": "VGENX", "tradable_proxy": "VDE", "proxy_correlation": 0.977071},
    "financial": {"symbol": "FIDSX", "tradable_proxy": "XLF", "proxy_correlation": 0.966307},
    "healthcare": {"symbol": "VGHCX", "tradable_proxy": "VHT", "proxy_correlation": 0.961949},
    "inverse_sp500": {"symbol": "RYURX", "tradable_proxy": "SH", "proxy_correlation": 0.996929},
}

ASSETS = list(PROXIES)
RISK_ASSETS = ["ndx", "sp500", "small", "value", "growth", "emerging", "energy", "financial", "healthcare"]
SAFE_ASSETS = ["short_treasury", "intermediate_treasury", "long_treasury", "inverse_sp500"]


@njit
def eval_daily_withdrawal_all_starts(
    returns: np.ndarray,
    withdraw_flags: np.ndarray,
    start_indices: np.ndarray,
) -> tuple[int, int, float, float, int, int]:
    failed = 0
    final_le_initial = 0
    min_final = 1.0e18
    worst_mdd = 0.0
    worst_final_i = -1
    worst_mdd_i = -1
    n = len(returns)
    for sidx in range(len(start_indices)):
        start = int(start_indices[sidx])
        cap = INITIAL_CAPITAL
        peak = INITIAL_CAPITAL
        mdd = 0.0
        path_failed = False
        for i in range(start, n):
            if withdraw_flags[i]:
                cap -= MONTHLY_WITHDRAWAL
                if cap <= 0.0:
                    path_failed = True
                    break
            r = returns[i]
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
    parser.add_argument("--configs-per-shard", type=int, default=20_000)
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
        prices[name] = raw[meta["symbol"]]["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]
    prices = prices.dropna(how="any")
    daily = prices.pct_change().dropna()
    if prices.index.max() >= LOCKED_START or daily.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data leak.")
    if daily.index.min() > pd.Timestamp("1995-01-10"):
        raise RuntimeError(f"Insufficient 1995 history: {daily.index.min()}")
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    daily.to_csv(data_dir / "daily_returns.csv", index_label="timestamp")
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
    returns = pd.read_csv(output_dir / "data" / "daily_returns.csv", parse_dates=["timestamp"]).set_index("timestamp")
    if returns.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached shard.")
    signals = precompute_signals(returns)
    periods = build_periods(returns)
    # Warm up numba.
    eval_daily_withdrawal_all_starts(np.zeros(260, dtype=np.float64), np.ones(260, dtype=np.bool_), np.array([0], dtype=np.int64))
    rng = np.random.default_rng(103_000_019 + family_id * 1_000_003 + shard_id * 1009)
    rows: list[dict[str, Any]] = []
    started = time.monotonic()
    deadline = started + max(1.0, time_budget_minutes) * 60.0
    evaluated = 0
    validation_evaluated = 0
    for config_index in range(configs_per_shard):
        if time.monotonic() >= deadline:
            break
        evaluated += 1
        params = anchor_params(family_id, shard_id, config_index) if config_index < 24 else sample_params(rng, family_id)
        port, weights = build_strategy(returns, signals, params)
        if port.min() <= -0.98:
            continue
        train_eval = eval_period(port, periods["train"])
        train_early_eval = eval_period(port, periods["train_early"])
        train_late_eval = eval_period(port, periods["train_late"])
        stress_evals = [eval_period(port, period) for period in periods["stress"]]
        stress_failed = int(sum(item[0] for item in stress_evals))
        stress_worst_mdd = float(min(item[3] for item in stress_evals))
        train_pass = train_eval[0] == 0 and train_eval[3] > MAX_MDD_AFTER_WITHDRAWALS
        train_cv_soft = train_early_eval[0] == 0 and train_late_eval[0] == 0 and min(train_early_eval[3], train_late_eval[3]) > -0.22
        train_metrics = period_metrics(port.loc[periods["train"]["index"]])
        turnover = annual_turnover(weights.loc[periods["train"]["index"]])
        train_score = train_only_score(train_eval, train_early_eval, train_late_eval, stress_evals, train_metrics, turnover, train_pass, train_cv_soft, params)
        if not train_pass and train_score < -600_000_000.0 and config_index % 401 != 0:
            continue
        valid_eval = eval_period(port, periods["validation"])
        validation_evaluated += 1
        validation_pass = valid_eval[0] == 0 and valid_eval[3] > MAX_MDD_AFTER_WITHDRAWALS
        config_hash = hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()
        rows.append(
            {
                "strategy_id": f"swr_daily_tactical_mdd15_corr95_f{family_id:02d}_s{shard_id:02d}_{config_hash[:16]}",
                "family_id": family_id,
                "shard_id": shard_id,
                "config_index": config_index,
                "train_pass": bool(train_pass),
                "train_cv_soft_pass": bool(train_cv_soft),
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
                "mdd_after_withdrawals_train_early": float(train_early_eval[3]),
                "mdd_after_withdrawals_train_late": float(train_late_eval[3]),
                "stress_failed_starts_train": int(stress_failed),
                "stress_worst_mdd_after_withdrawals_train": float(stress_worst_mdd),
                "mdd_after_withdrawals_validation": float(valid_eval[3]),
                "worst_final_start_train": str(periods["train"]["dates"][int(train_eval[4])].date()) if train_eval[4] >= 0 else "",
                "worst_final_start_validation": str(periods["validation"]["dates"][int(valid_eval[4])].date()) if valid_eval[4] >= 0 else "",
                "worst_mdd_start_train": str(periods["train"]["dates"][int(train_eval[5])].date()) if train_eval[5] >= 0 else "",
                "worst_mdd_start_validation": str(periods["validation"]["dates"][int(valid_eval[5])].date()) if valid_eval[5] >= 0 else "",
                "train_cagr": float(train_metrics["cagr"]),
                "train_sharpe": float(train_metrics["sharpe"]),
                "train_raw_mdd": float(train_metrics["mdd"]),
                "turnover_annual": float(turnover),
                "avg_gross_exposure": float(weights.loc[periods["train"]["index"]].abs().sum(axis=1).mean()),
                "max_gross_exposure": float(weights.loc[periods["train"]["index"]].abs().sum(axis=1).max()),
                "uses_concrete_stocks": False,
                "uses_crypto": False,
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "data_end_max": "2019-12-31",
                "proxy_corr_min": min(meta["proxy_correlation"] for meta in PROXIES.values()),
                "max_mdd_after_withdrawals_required": MAX_MDD_AFTER_WITHDRAWALS,
                "params_json": json.dumps(params, sort_keys=True),
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


def build_periods(returns: pd.DataFrame) -> dict[str, Any]:
    train = returns[returns.index <= TRAIN_END]
    train_early = returns[returns.index <= TRAIN_CV_SPLIT]
    train_late = returns[(returns.index > TRAIN_CV_SPLIT) & (returns.index <= TRAIN_END)]
    validation = returns[(returns.index >= VALIDATION_START) & (returns.index <= VALIDATION_END)]
    stress = [returns[(returns.index >= start) & (returns.index <= end)] for start, end in TRAIN_STRESS_WINDOWS]
    return {
        "train": period_descriptor(train, MIN_MONTHS_TRAIN),
        "train_early": period_descriptor(train_early, 36),
        "train_late": period_descriptor(train_late, 36),
        "validation": period_descriptor(validation, MIN_MONTHS_VALIDATION),
        "stress": [period_descriptor(frame, 24) for frame in stress],
    }


def period_descriptor(frame: pd.DataFrame, min_months: int) -> dict[str, Any]:
    dates = frame.index
    periods = dates.to_period("M")
    withdraw_flags = pd.Series(periods, index=dates).ne(pd.Series(periods, index=dates).shift(1)).to_numpy(dtype=np.bool_)
    month_start_positions = np.flatnonzero(withdraw_flags)
    start_indices = []
    for pos_i, pos in enumerate(month_start_positions):
        if len(month_start_positions) - pos_i >= min_months:
            start_indices.append(int(pos))
    return {
        "index": frame.index,
        "dates": frame.index,
        "withdraw_flags": withdraw_flags,
        "start_indices": np.array(start_indices, dtype=np.int64),
    }


def eval_period(port: pd.Series, period: dict[str, Any]) -> tuple[int, int, float, float, int, int]:
    arr = port.loc[period["index"]].to_numpy(np.float64)
    return eval_daily_withdrawal_all_starts(arr, period["withdraw_flags"], period["start_indices"])


def precompute_signals(returns: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for lb in [5, 10, 21, 42, 63, 126, 189, 252]:
        out[f"mom_{lb}"] = (1.0 + returns[ASSETS]).rolling(lb).apply(np.prod, raw=True).shift(1) - 1.0
        out[f"risk_mom_{lb}"] = (1.0 + returns[RISK_ASSETS]).rolling(lb).apply(np.prod, raw=True).shift(1) - 1.0
        out[f"safe_mom_{lb}"] = (1.0 + returns[SAFE_ASSETS]).rolling(lb).apply(np.prod, raw=True).shift(1) - 1.0
    for lb in [10, 21, 42, 63, 126]:
        out[f"vol_{lb}"] = returns[ASSETS].rolling(lb).std().shift(1)
    for lb in [21, 63, 126]:
        out[f"breadth_{lb}"] = (out[f"risk_mom_{lb}"] > 0.0).mean(axis=1)
    for asset in ["sp500", "ndx", "growth", "long_treasury", "short_treasury", "inverse_sp500"]:
        for lb in [10, 21, 63, 126, 252]:
            out[f"{asset}_filter_{lb}"] = (1.0 + returns[asset]).rolling(lb).apply(np.prod, raw=True).shift(1) - 1.0
    return out


def sample_params(rng: np.random.Generator, family_id: int) -> dict[str, Any]:
    conservative = family_id in {0, 1, 2, 3, 10, 11, 12}
    return {
        "family_id": family_id,
        "mode": int(family_id % 6),
        "risk_lb": int(rng.choice([5, 10, 21, 42, 63, 126, 189, 252])),
        "safe_lb": int(rng.choice([10, 21, 63, 126, 252])),
        "vol_lb": int(rng.choice([10, 21, 42, 63, 126])),
        "filter_asset": str(rng.choice(["sp500", "ndx", "growth", "long_treasury", "short_treasury"])),
        "filter_lb": int(rng.choice([10, 21, 63, 126, 252])),
        "filter_threshold": float(rng.uniform(-0.10, 0.06)),
        "top_n": int(rng.choice([1, 2, 3, 4, 5])),
        "bottom_n": int(rng.choice([0, 1, 2, 3])),
        "safe_n": int(rng.choice([1, 2, 3, 4])),
        "risk_exposure": float(rng.uniform(0.0, 4.0 if conservative else 8.0)),
        "short_exposure": float(rng.uniform(0.0, 2.5 if conservative else 5.0)),
        "safe_exposure": float(rng.uniform(0.0, 8.0 if conservative else 14.0)),
        "inverse_exposure": float(rng.uniform(0.0, 4.0 if conservative else 8.0)),
        "cash_buffer": float(rng.uniform(0.0, 0.80)),
        "momentum_threshold": float(rng.uniform(-0.05, 0.08)),
        "short_threshold": float(rng.uniform(0.0, 0.10)),
        "crisis_risk_scale": float(rng.choice([0.0, 0.10, 0.20, 0.35, 0.50, 0.75, 1.0])),
        "crisis_safe_boost": float(rng.choice([0.0, 0.25, 0.50, 0.75, 1.0, 1.5])),
        "crisis_inverse_boost": float(rng.choice([0.0, 0.25, 0.50, 0.75, 1.0, 1.5])),
        "breadth_lb": int(rng.choice([21, 63, 126])),
        "breadth_threshold": float(rng.uniform(0.20, 0.90)),
        "breadth_risk_scale": float(rng.choice([0.0, 0.10, 0.25, 0.50, 0.75, 1.0])),
        "vol_target": float(rng.choice([0.0, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25])),
        "vol_scale_cap": float(rng.choice([0.50, 0.75, 1.0, 1.25, 1.5, 2.0])),
        "max_gross": float(rng.uniform(1.0, 8.0 if conservative else 14.0)),
        "hold_days": int(rng.choice([1, 2, 3, 5, 10, 21])),
        "rebalance_band": float(rng.choice([0.0, 0.15, 0.30, 0.50, 0.80, 1.20])),
        "loss_guard_lb": int(rng.choice([5, 10, 21, 42])),
        "loss_guard_threshold": float(rng.choice([-0.12, -0.09, -0.06, -0.04, -0.025])),
        "loss_guard_scale": float(rng.choice([0.0, 0.10, 0.20, 0.35, 0.50, 0.75])),
        "loss_guard_safe_blend": float(rng.choice([0.25, 0.50, 0.75, 1.0])),
    }


def anchor_params(family_id: int, shard_id: int, config_index: int) -> dict[str, Any]:
    i = family_id * 1009 + shard_id * 37 + config_index
    return {
        "family_id": family_id,
        "mode": int((family_id + config_index) % 6),
        "risk_lb": int([10, 21, 42, 63, 126, 189][i % 6]),
        "safe_lb": int([21, 63, 126, 252][(i // 2) % 4]),
        "vol_lb": int([21, 42, 63, 126][(i // 3) % 4]),
        "filter_asset": str(["sp500", "ndx", "growth", "long_treasury", "short_treasury"][i % 5]),
        "filter_lb": int([21, 63, 126, 252][(i // 5) % 4]),
        "filter_threshold": float([-0.08, -0.05, -0.025, 0.0, 0.025][i % 5]),
        "top_n": int([1, 2, 3, 4][i % 4]),
        "bottom_n": int([0, 1, 2][i % 3]),
        "safe_n": int([1, 2, 3][(i // 2) % 3]),
        "risk_exposure": float([0.5, 1.0, 1.6, 2.4, 3.2, 4.5, 6.0][i % 7]),
        "short_exposure": float([0.0, 0.4, 0.8, 1.4, 2.2][(i // 2) % 5]),
        "safe_exposure": float([1.0, 2.5, 4.0, 6.0, 8.5, 11.0][(i // 3) % 6]),
        "inverse_exposure": float([0.0, 0.5, 1.0, 1.8, 2.8, 4.0][(i // 5) % 6]),
        "cash_buffer": float([0.0, 0.15, 0.30, 0.45, 0.60][i % 5]),
        "momentum_threshold": float([-0.04, -0.02, 0.0, 0.02, 0.04][i % 5]),
        "short_threshold": float([0.02, 0.04, 0.06, 0.08][i % 4]),
        "crisis_risk_scale": float([0.0, 0.10, 0.25, 0.50, 0.75][i % 5]),
        "crisis_safe_boost": float([0.0, 0.50, 1.0, 1.5][(i // 2) % 4]),
        "crisis_inverse_boost": float([0.0, 0.50, 1.0, 1.5][(i // 3) % 4]),
        "breadth_lb": int([21, 63, 126][i % 3]),
        "breadth_threshold": float([0.30, 0.45, 0.60, 0.75][(i // 2) % 4]),
        "breadth_risk_scale": float([0.0, 0.10, 0.25, 0.50, 0.75][(i // 3) % 5]),
        "vol_target": float([0.06, 0.08, 0.10, 0.12, 0.15, 0.20][(i // 7) % 6]),
        "vol_scale_cap": float([0.50, 0.75, 1.0, 1.25, 1.5][i % 5]),
        "max_gross": float([2.0, 3.5, 5.0, 7.0, 10.0, 13.0][(i // 11) % 6]),
        "hold_days": int([1, 2, 3, 5, 10][i % 5]),
        "rebalance_band": float([0.0, 0.15, 0.30, 0.50, 0.80][(i // 2) % 5]),
        "loss_guard_lb": int([5, 10, 21, 42][i % 4]),
        "loss_guard_threshold": float([-0.09, -0.06, -0.04, -0.025][(i // 3) % 4]),
        "loss_guard_scale": float([0.0, 0.10, 0.20, 0.35, 0.50][i % 5]),
        "loss_guard_safe_blend": float([0.50, 0.75, 1.0][(i // 5) % 3]),
    }


def build_strategy(returns: pd.DataFrame, signals: dict[str, Any], params: dict[str, Any]) -> tuple[pd.Series, pd.DataFrame]:
    weights = raw_daily_weights(returns, signals, params)
    weights = apply_loss_guard(weights, returns, params)
    weights = apply_vol_target_and_cap(weights, returns, params)
    weights = rebalance_with_band(weights, int(params["hold_days"]), float(params["rebalance_band"]))
    return (weights * returns[ASSETS]).sum(axis=1).astype(float), weights.astype(float)


def raw_daily_weights(returns: pd.DataFrame, signals: dict[str, Any], params: dict[str, Any]) -> pd.DataFrame:
    risk_mom = signals[f"risk_mom_{params['risk_lb']}"].fillna(0.0)
    safe_mom = signals[f"safe_mom_{params['safe_lb']}"].fillna(0.0)
    risk_vol = signals[f"vol_{params['vol_lb']}"][RISK_ASSETS].replace(0.0, np.nan)
    safe_vol = signals[f"vol_{params['vol_lb']}"][SAFE_ASSETS].replace(0.0, np.nan)
    filter_signal = signals[f"{params['filter_asset']}_filter_{params['filter_lb']}"].fillna(0.0)
    breadth = signals[f"breadth_{params['breadth_lb']}"].fillna(0.0)
    mode = int(params["mode"])
    weights = pd.DataFrame(0.0, index=returns.index, columns=ASSETS)
    for dt in returns.index:
        crisis = float(filter_signal.loc[dt]) < float(params["filter_threshold"])
        risk_scale = 1.0
        if crisis:
            risk_scale *= float(params["crisis_risk_scale"])
        if float(breadth.loc[dt]) < float(params["breadth_threshold"]):
            risk_scale *= float(params["breadth_risk_scale"])
        row = pd.Series(0.0, index=ASSETS)
        risk_row = risk_mom.loc[dt].sort_values(ascending=False)
        risk_picks = risk_row[risk_row > float(params["momentum_threshold"])].head(int(params["top_n"])).index.tolist()
        if mode in {0, 1, 3, 4, 5} and risk_picks and risk_scale > 0:
            inv = inverse_vol_slice(risk_vol.loc[dt], risk_picks)
            row.loc[risk_picks] += inv * float(params["risk_exposure"]) * risk_scale * (1.0 - float(params["cash_buffer"]))
        if mode in {1, 2, 4, 5}:
            short_picks = risk_row[risk_row < -float(params["short_threshold"])].sort_values(ascending=True).head(int(params["bottom_n"])).index.tolist()
            if short_picks:
                inv = inverse_vol_slice(risk_vol.loc[dt], short_picks)
                row.loc[short_picks] -= inv * float(params["short_exposure"]) * max(0.0, 1.0 - 0.5 * risk_scale)
        safe_row = safe_mom.loc[dt].sort_values(ascending=False)
        safe_picks = safe_row.head(int(params["safe_n"])).index.tolist()
        if safe_picks:
            inv_safe = inverse_vol_slice(safe_vol.loc[dt], safe_picks)
            safe_exp = float(params["safe_exposure"]) * (1.0 + (float(params["crisis_safe_boost"]) if crisis else 0.0))
            row.loc[safe_picks] += inv_safe * safe_exp * (1.0 - 0.5 * float(params["cash_buffer"]))
        if crisis or mode in {2, 3, 5}:
            row.loc["inverse_sp500"] += float(params["inverse_exposure"]) * (1.0 + (float(params["crisis_inverse_boost"]) if crisis else 0.0))
        weights.loc[dt] = row
    return cap_gross(weights, float(params["max_gross"]))


def inverse_vol_slice(vol_row: pd.Series, picks: list[str]) -> pd.Series:
    inv = (1.0 / vol_row.loc[picks]).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    total = float(inv.sum())
    if total <= 0.0:
        return pd.Series(1.0 / len(picks), index=picks)
    return inv / total


def apply_loss_guard(weights: pd.DataFrame, returns: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    base = (weights * returns[ASSETS]).sum(axis=1)
    trail = (1.0 + base).rolling(int(params["loss_guard_lb"])).apply(np.prod, raw=True).shift(1) - 1.0
    safe = pd.DataFrame(0.0, index=weights.index, columns=ASSETS)
    safe["short_treasury"] = float(params["safe_exposure"]) * 0.55
    safe["intermediate_treasury"] = float(params["safe_exposure"]) * 0.25
    safe["long_treasury"] = float(params["safe_exposure"]) * 0.10
    safe["inverse_sp500"] = float(params["inverse_exposure"]) * 0.10
    out = weights.copy()
    mask = trail.fillna(0.0) <= float(params["loss_guard_threshold"])
    if mask.any():
        scaled = weights.mul(float(params["loss_guard_scale"]), axis=0)
        blended = scaled * (1.0 - float(params["loss_guard_safe_blend"])) + safe * float(params["loss_guard_safe_blend"])
        out.loc[mask] = blended.loc[mask]
    return cap_gross(out, float(params["max_gross"]))


def apply_vol_target_and_cap(weights: pd.DataFrame, returns: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    out = cap_gross(weights, float(params["max_gross"]))
    target = float(params["vol_target"])
    if target <= 0.0:
        return out
    base = (out * returns[ASSETS]).sum(axis=1)
    realized = base.rolling(int(params["vol_lb"])).std().shift(1) * math.sqrt(252.0)
    scale = (target / realized).replace([np.inf, -np.inf], np.nan).clip(0.0, float(params["vol_scale_cap"])).fillna(0.0)
    return cap_gross(out.mul(scale, axis=0), float(params["max_gross"]))


def cap_gross(weights: pd.DataFrame, max_gross: float) -> pd.DataFrame:
    gross = weights.abs().sum(axis=1).replace(0.0, np.nan)
    scale = (max_gross / gross).clip(upper=1.0).fillna(0.0)
    return weights.mul(scale, axis=0)


def rebalance_with_band(target: pd.DataFrame, hold_days: int, band: float) -> pd.DataFrame:
    out = pd.DataFrame(0.0, index=target.index, columns=target.columns)
    last = pd.Series(0.0, index=target.columns)
    for idx, dt in enumerate(target.index):
        desired = target.loc[dt] if idx % max(1, hold_days) == 0 else last
        if float((desired - last).abs().sum()) > band:
            last = desired.astype(float).copy()
        out.loc[dt] = last
    return out


def annual_turnover(weights: pd.DataFrame) -> float:
    if weights.empty:
        return 0.0
    return float(weights.diff().abs().sum(axis=1).mean() * 252.0)


def period_metrics(series: pd.Series) -> dict[str, float]:
    arr = series.to_numpy(np.float64)
    if len(arr) == 0:
        return {"cagr": 0.0, "sharpe": 0.0, "mdd": 0.0}
    equity = np.cumprod(1.0 + arr)
    years = len(arr) / 252.0
    cagr = float(equity[-1] ** (1.0 / years) - 1.0) if equity[-1] > 0 and years > 0 else -1.0
    vol = float(np.std(arr, ddof=1) * math.sqrt(252.0)) if len(arr) > 1 else 0.0
    sharpe = float(np.mean(arr) * 252.0 / vol) if vol > 0 else 0.0
    peaks = np.maximum.accumulate(equity)
    mdd = float(np.min(equity / peaks - 1.0)) if len(equity) else 0.0
    return {"cagr": cagr, "sharpe": sharpe, "mdd": mdd}


def train_only_score(
    train_eval: tuple[int, int, float, float, int, int],
    early_eval: tuple[int, int, float, float, int, int],
    late_eval: tuple[int, int, float, float, int, int],
    stress_evals: list[tuple[int, int, float, float, int, int]],
    metrics: dict[str, float],
    turnover: float,
    train_pass: bool,
    train_cv_soft: bool,
    params: dict[str, Any],
) -> float:
    failed, le_initial, worst_final, mdd, _, _ = train_eval
    stress_failed = sum(item[0] for item in stress_evals)
    stress_mdd = min(item[3] for item in stress_evals)
    early_mdd = early_eval[3]
    late_mdd = late_eval[3]
    complexity = (
        float(params["risk_exposure"])
        + float(params["short_exposure"])
        + float(params["safe_exposure"])
        + float(params["inverse_exposure"])
        + float(params["max_gross"])
    )
    return (
        (1_000_000_000.0 if train_pass else 0.0)
        + (80_000_000.0 if train_cv_soft else 0.0)
        - failed * 25_000_000.0
        - le_initial * 500_000.0
        - early_eval[0] * 10_000_000.0
        - late_eval[0] * 10_000_000.0
        - stress_failed * 4_000_000.0
        + min(worst_final, 10_000_000.0)
        + min(mdd, early_mdd, late_mdd, stress_mdd) * 55_000_000.0
        + metrics["cagr"] * 2_000_000.0
        + metrics["sharpe"] * 500_000.0
        - turnover * 20_000.0
        - complexity * 25_000.0
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
    verified.to_csv(output_dir / "verified_daily_tactical_mdd15_report_only.csv", index=False)
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


def build_fail_reasons(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["reason", "count"])
    reasons = []
    for _, row in df.iterrows():
        if bool(row.get("final_verified_report_only", False)):
            reason = "verified"
        elif not bool(row.get("train_pass", False)):
            if int(row.get("train_failed_starts", 0)) > 0:
                reason = "train_failed_withdrawal_path"
            elif float(row.get("mdd_after_withdrawals_train", -1.0)) <= MAX_MDD_AFTER_WITHDRAWALS:
                reason = "train_mdd_after_withdrawals_gt_15pct"
            else:
                reason = "train_other"
        elif int(row.get("validation_failed_starts", 0)) > 0:
            reason = "validation_failed_withdrawal_path_report_only"
        elif float(row.get("mdd_after_withdrawals_validation", -1.0)) <= MAX_MDD_AFTER_WITHDRAWALS:
            reason = "validation_mdd_after_withdrawals_gt_15pct_report_only"
        else:
            reason = "validation_other_report_only"
        reasons.append(reason)
    return pd.Series(reasons).value_counts().rename_axis("reason").reset_index(name="count")


if __name__ == "__main__":
    main()
