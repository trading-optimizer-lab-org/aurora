from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from numba import njit


CAMPAIGN_ID = "swr_cppi_corr95_360jobs"
INITIAL_CAPITAL = 100_000.0
MONTHLY_WITHDRAWAL = 2_000.0
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2019-12-31")
LOCKED_START = pd.Timestamp("2020-01-01")
MIN_HORIZON_TRAIN = 120
MIN_HORIZON_VALIDATION = 60
MAX_MDD_AFTER_WITHDRAWALS = -0.50
MIN_PROXY_CORRELATION = 0.95

PROXIES = {
    "ndx": {"symbol": "^NDX", "tradable_proxy": "QQQ", "proxy_correlation": 0.999176},
    "short_treasury": {"symbol": "VFISX", "tradable_proxy": "SHY", "proxy_correlation": 0.951883},
    "long_treasury": {"symbol": "VUSTX", "tradable_proxy": "TLT", "proxy_correlation": 0.989281},
}


@njit
def _eval_cppi_all_starts(
    ndx: np.ndarray,
    tlt: np.ndarray,
    shy: np.ndarray,
    signal: np.ndarray,
    min_horizon: int,
    multiplier: float,
    floor_pct: float,
    max_exposure: float,
    safe_weight: float,
    risk_blend: float,
    allow_short: int,
    inverse_when_negative: int,
    initial_capital: float,
    monthly_withdrawal: float,
    final_gt: float,
) -> tuple[int, int, float, float, int, int]:
    n = len(ndx)
    failed = 0
    final_le_initial = 0
    min_final = 1.0e18
    worst_mdd = 0.0
    worst_final_i = -1
    worst_mdd_i = -1
    for start in range(n):
        if n - start < min_horizon:
            continue
        cap = initial_capital
        peak = initial_capital
        mdd = 0.0
        path_failed = False
        for i in range(start, n):
            cap -= monthly_withdrawal
            if cap <= 0.0:
                path_failed = True
                break
            floor_value = peak * floor_pct
            cushion = cap - floor_value
            if cushion < 0.0:
                cushion = 0.0
            exposure = multiplier * cushion / cap
            if exposure > max_exposure:
                exposure = max_exposure
            if exposure < 0.0:
                exposure = 0.0
            sign = 1.0
            if signal[i] < 0.0:
                if inverse_when_negative == 1:
                    sign = -1.0
                elif allow_short == 1:
                    sign = -1.0
                else:
                    exposure = 0.0
            risk_ret = risk_blend * ndx[i] + (1.0 - risk_blend) * tlt[i]
            safe_ret = safe_weight * shy[i] + (1.0 - safe_weight) * tlt[i]
            port_ret = sign * exposure * risk_ret + (1.0 - exposure) * safe_ret
            cap *= 1.0 + port_ret
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
        if cap <= final_gt:
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
    parser.add_argument("--top-per-shard", type=int, default=50)
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "data":
        run_data(output_dir)
    elif args.mode == "shard":
        run_shard(output_dir, args.family_id, args.shard_id, args.configs_per_shard, args.top_per_shard)
    else:
        run_merge(output_dir)


def run_data(output_dir: Path) -> None:
    for name, meta in PROXIES.items():
        if meta["proxy_correlation"] < MIN_PROXY_CORRELATION:
            raise RuntimeError(f"Proxy {name} below correlation threshold.")
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
    if prices.index.max() >= LOCKED_START:
        raise RuntimeError("Locked daily data leak.")
    monthly = prices.resample("ME").last().pct_change().dropna()
    if monthly.index.max() >= LOCKED_START:
        raise RuntimeError("Locked monthly data leak.")
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(data_dir / "monthly_returns.csv", index_label="timestamp")
    proxy_rows = []
    for name, meta in PROXIES.items():
        proxy_rows.append(
            {
                "sleeve": name,
                **meta,
                "proxy_correlation_min_required": MIN_PROXY_CORRELATION,
                "first_date": prices.index.min().date().isoformat(),
                "last_date": prices.index.max().date().isoformat(),
                "uses_concrete_stocks": False,
                "uses_crypto": False,
                "locked_opened": False,
            }
        )
    pd.DataFrame(proxy_rows).to_csv(data_dir / "proxy_map.csv", index=False)
    pd.DataFrame(
        [{"locked_start": "2020-01-01", "locked_opened": False, "locked_rows_accessed": 0, "max_data_date": "2019-12-31"}]
    ).to_csv(data_dir / "locked_access_audit.csv", index=False)


def run_shard(output_dir: Path, family_id: int, shard_id: int, configs_per_shard: int, top_per_shard: int) -> None:
    returns = pd.read_csv(output_dir / "data" / "monthly_returns.csv", parse_dates=["timestamp"]).set_index("timestamp")
    if returns.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached shard.")
    train = returns[returns.index <= TRAIN_END]
    valid = returns[(returns.index >= VALIDATION_START) & (returns.index <= VALIDATION_END)]
    train_dates = train.index
    valid_dates = valid.index
    rng = np.random.default_rng(17_000_019 + family_id * 1009 + shard_id * 9176)
    _eval_cppi_all_starts(
        train["ndx"].to_numpy(np.float64),
        train["long_treasury"].to_numpy(np.float64),
        train["short_treasury"].to_numpy(np.float64),
        np.zeros(len(train), dtype=np.float64),
        MIN_HORIZON_TRAIN,
        2.0,
        0.5,
        2.0,
        1.0,
        1.0,
        0,
        0,
        INITIAL_CAPITAL,
        MONTHLY_WITHDRAWAL,
        INITIAL_CAPITAL,
    )
    rows: list[dict[str, Any]] = []
    for config_index in range(configs_per_shard):
        params = sample_params(rng, family_id)
        signal_all = build_signal(returns, params)
        train_eval = eval_params(train, signal_all.loc[train.index], params, MIN_HORIZON_TRAIN, train_dates)
        if train_eval["failed_starts"] or train_eval["final_le_initial_count"] or train_eval["mdd_after_withdrawals"] <= MAX_MDD_AFTER_WITHDRAWALS:
            if config_index % 97 != 0:
                continue
        valid_eval = eval_params(valid, signal_all.loc[valid.index], params, MIN_HORIZON_VALIDATION, valid_dates)
        accepted = (
            train_eval["failed_starts"] == 0
            and valid_eval["failed_starts"] == 0
            and train_eval["final_le_initial_count"] == 0
            and valid_eval["final_le_initial_count"] == 0
            and train_eval["mdd_after_withdrawals"] > MAX_MDD_AFTER_WITHDRAWALS
            and valid_eval["mdd_after_withdrawals"] > MAX_MDD_AFTER_WITHDRAWALS
        )
        config_hash = hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()
        score = (
            (1_000_000_000.0 if accepted else 0.0)
            - (train_eval["failed_starts"] + valid_eval["failed_starts"]) * 10_000_000.0
            - (train_eval["final_le_initial_count"] + valid_eval["final_le_initial_count"]) * 1_000_000.0
            + min(train_eval["worst_final_capital"], valid_eval["worst_final_capital"])
            + (train_eval["mdd_after_withdrawals"] + valid_eval["mdd_after_withdrawals"]) * 100_000.0
        )
        rows.append(
            {
                "strategy_id": f"swr_cppi_corr95_f{family_id:02d}_s{shard_id:02d}_{config_hash[:16]}",
                "family_id": family_id,
                "shard_id": shard_id,
                "config_index": config_index,
                "accepted": bool(accepted),
                "train_failed_starts": train_eval["failed_starts"],
                "validation_failed_starts": valid_eval["failed_starts"],
                "train_final_le_initial_count": train_eval["final_le_initial_count"],
                "validation_final_le_initial_count": valid_eval["final_le_initial_count"],
                "worst_final_capital_train": train_eval["worst_final_capital"],
                "worst_final_capital_validation": valid_eval["worst_final_capital"],
                "mdd_after_withdrawals_train": train_eval["mdd_after_withdrawals"],
                "mdd_after_withdrawals_validation": valid_eval["mdd_after_withdrawals"],
                "worst_final_start_train": train_eval["worst_final_start"],
                "worst_final_start_validation": valid_eval["worst_final_start"],
                "worst_mdd_start_train": train_eval["worst_mdd_start"],
                "worst_mdd_start_validation": valid_eval["worst_mdd_start"],
                "uses_concrete_stocks": False,
                "uses_crypto": False,
                "locked_opened": False,
                "data_end_max": "2019-12-31",
                "proxy_corr_min": MIN_PROXY_CORRELATION,
                "params_json": json.dumps(params, sort_keys=True),
                "config_hash": config_hash,
                "score": score,
            }
        )
    shard_dir = output_dir / "shards" / f"family_{family_id:02d}_shard_{shard_id:02d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["strategy_id", "accepted", "score"])
    df.sort_values("score", ascending=False).head(top_per_shard).to_csv(shard_dir / "top_candidates.csv", index=False)
    df[df.get("accepted", pd.Series(dtype=bool)).astype(bool)].to_csv(shard_dir / "accepted_candidates.csv", index=False)


def sample_params(rng: np.random.Generator, family_id: int) -> dict[str, Any]:
    return {
        "family_id": family_id,
        "lookback": int(rng.choice([1, 3, 6, 10, 12])),
        "signal_mode": str(rng.choice(["ndx_mom", "ndx_minus_tlt", "dual_mom", "tlt_mom"])),
        "multiplier": float(rng.uniform(0.5, 18.0)),
        "floor_pct": float(rng.uniform(0.05, 0.85)),
        "max_exposure": float(rng.uniform(0.25, 18.0)),
        "safe_weight": float(rng.uniform(0.0, 1.0)),
        "risk_blend": float(rng.uniform(-1.5, 2.5)),
        "allow_short": int(rng.integers(0, 2)),
        "inverse_when_negative": int(rng.integers(0, 2)),
    }


def build_signal(returns: pd.DataFrame, params: dict[str, Any]) -> pd.Series:
    lookback = int(params["lookback"])
    ndx_mom = (1.0 + returns["ndx"]).rolling(lookback).apply(np.prod, raw=True).shift(1) - 1.0
    tlt_mom = (1.0 + returns["long_treasury"]).rolling(lookback).apply(np.prod, raw=True).shift(1) - 1.0
    mode = params["signal_mode"]
    if mode == "ndx_mom":
        signal = ndx_mom
    elif mode == "tlt_mom":
        signal = tlt_mom
    elif mode == "ndx_minus_tlt":
        signal = ndx_mom - tlt_mom
    else:
        signal = ndx_mom.where(ndx_mom.abs() >= tlt_mom.abs(), tlt_mom)
    return signal.fillna(0.0)


def eval_params(
    frame: pd.DataFrame,
    signal: pd.Series,
    params: dict[str, Any],
    min_horizon: int,
    dates: pd.DatetimeIndex,
) -> dict[str, Any]:
    result = _eval_cppi_all_starts(
        frame["ndx"].to_numpy(np.float64),
        frame["long_treasury"].to_numpy(np.float64),
        frame["short_treasury"].to_numpy(np.float64),
        signal.to_numpy(np.float64),
        min_horizon,
        float(params["multiplier"]),
        float(params["floor_pct"]),
        float(params["max_exposure"]),
        float(params["safe_weight"]),
        float(params["risk_blend"]),
        int(params["allow_short"]),
        int(params["inverse_when_negative"]),
        INITIAL_CAPITAL,
        MONTHLY_WITHDRAWAL,
        INITIAL_CAPITAL,
    )
    return {
        "failed_starts": int(result[0]),
        "final_le_initial_count": int(result[1]),
        "worst_final_capital": float(result[2]),
        "mdd_after_withdrawals": float(result[3]),
        "worst_final_start": str(dates[int(result[4])].date()) if result[4] >= 0 else "",
        "worst_mdd_start": str(dates[int(result[5])].date()) if result[5] >= 0 else "",
    }


def run_merge(output_dir: Path) -> None:
    files = list((output_dir / "shards").glob("**/top_candidates.csv"))
    accepted_files = list((output_dir / "shards").glob("**/accepted_candidates.csv"))
    top = pd.concat([pd.read_csv(path) for path in files], ignore_index=True) if files else pd.DataFrame()
    accepted = pd.concat([pd.read_csv(path) for path in accepted_files], ignore_index=True) if accepted_files else pd.DataFrame()
    if not top.empty:
        top = top.sort_values("score", ascending=False)
    if not accepted.empty:
        accepted = accepted.sort_values("score", ascending=False)
    top.to_csv(output_dir / "all_top_candidates.csv", index=False)
    accepted.to_csv(output_dir / "accepted_cppi_corr95_strategies.csv", index=False)
    for name in ["proxy_map.csv", "locked_access_audit.csv"]:
        src = output_dir / "data" / name
        if src.exists():
            pd.read_csv(src).to_csv(output_dir / name, index=False)
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "accepted_count": int(len(accepted)),
        "top_candidate_rows": int(len(top)),
        "proxy_corr_min": MIN_PROXY_CORRELATION,
        "locked_opened": False,
        "uses_concrete_stocks": False,
        "uses_crypto": False,
        "data_end_max": "2019-12-31",
    }
    (output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
