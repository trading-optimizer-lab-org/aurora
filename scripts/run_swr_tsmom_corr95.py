from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from numba import njit


CAMPAIGN_ID = "swr_tsmom_corr95_360jobs"
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
MAX_TURNOVER_ANNUAL = 24.0

PROXIES = {
    "ndx": {"symbol": "^NDX", "tradable_proxy": "QQQ", "proxy_correlation": 0.999176},
    "long_treasury": {"symbol": "VUSTX", "tradable_proxy": "TLT", "proxy_correlation": 0.989281},
    "short_treasury": {"symbol": "VFISX", "tradable_proxy": "SHY", "proxy_correlation": 0.951883},
}


@njit
def eval_all_starts(returns: np.ndarray, min_horizon: int) -> tuple[int, int, float, float, int, int]:
    failed = 0
    final_le_initial = 0
    min_final = 1.0e18
    worst_mdd = 0.0
    worst_final_i = -1
    worst_mdd_i = -1
    n = len(returns)
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
            cap *= 1.0 + returns[i]
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
    parser.add_argument("--configs-per-shard", type=int, default=50_000)
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
    monthly = prices.resample("ME").last().pct_change().dropna()
    if prices.index.max() >= LOCKED_START or monthly.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data leak.")
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
        [{"locked_start": "2020-01-01", "locked_opened": False, "locked_rows_accessed": 0, "max_data_date": "2019-12-31"}]
    ).to_csv(data_dir / "locked_access_audit.csv", index=False)


def run_shard(output_dir: Path, family_id: int, shard_id: int, configs_per_shard: int, top_per_shard: int) -> None:
    returns = pd.read_csv(output_dir / "data" / "monthly_returns.csv", parse_dates=["timestamp"]).set_index("timestamp")
    if returns.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached shard.")
    rng = np.random.default_rng(29_000_001 + family_id * 1_000_003 + shard_id * 101)
    train = returns[returns.index <= TRAIN_END]
    valid = returns[(returns.index >= VALIDATION_START) & (returns.index <= VALIDATION_END)]
    train_dates = train.index
    valid_dates = valid.index
    # Compile numba.
    eval_all_starts(np.zeros(130, dtype=np.float64), 60)
    rows: list[dict[str, Any]] = []
    signals = precompute_signals(returns)
    for config_index in range(configs_per_shard):
        params = sample_params(rng, family_id)
        series, weights = build_strategy(returns, signals, params)
        if series.min() <= -0.99 or not np.isfinite(series.to_numpy()).all():
            continue
        turnover = float(weights.diff().abs().sum(axis=1).mean() * 12.0)
        if turnover > MAX_TURNOVER_ANNUAL:
            continue
        train_series = series.loc[train.index]
        valid_series = series.loc[valid.index]
        train_eval = eval_all_starts(train_series.to_numpy(np.float64), MIN_HORIZON_TRAIN)
        if train_eval[0] or train_eval[1] or train_eval[3] <= MAX_MDD_AFTER_WITHDRAWALS:
            if config_index % 211 != 0:
                continue
        valid_eval = eval_all_starts(valid_series.to_numpy(np.float64), MIN_HORIZON_VALIDATION)
        accepted = (
            train_eval[0] == 0
            and train_eval[1] == 0
            and valid_eval[0] == 0
            and valid_eval[1] == 0
            and train_eval[3] > MAX_MDD_AFTER_WITHDRAWALS
            and valid_eval[3] > MAX_MDD_AFTER_WITHDRAWALS
        )
        config_hash = hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()
        score = (
            (1_000_000_000.0 if accepted else 0.0)
            - (train_eval[0] + valid_eval[0]) * 10_000_000.0
            - (train_eval[1] + valid_eval[1]) * 1_000_000.0
            + min(float(train_eval[2]), float(valid_eval[2]))
            + (float(train_eval[3]) + float(valid_eval[3])) * 100_000.0
            - turnover * 1_000.0
        )
        rows.append(
            {
                "strategy_id": f"swr_tsmom_corr95_f{family_id:02d}_s{shard_id:02d}_{config_hash[:16]}",
                "family_id": family_id,
                "shard_id": shard_id,
                "config_index": config_index,
                "accepted": bool(accepted),
                "train_failed_starts": int(train_eval[0]),
                "validation_failed_starts": int(valid_eval[0]),
                "train_final_le_initial_count": int(train_eval[1]),
                "validation_final_le_initial_count": int(valid_eval[1]),
                "worst_final_capital_train": float(train_eval[2]),
                "worst_final_capital_validation": float(valid_eval[2]),
                "mdd_after_withdrawals_train": float(train_eval[3]),
                "mdd_after_withdrawals_validation": float(valid_eval[3]),
                "worst_final_start_train": str(train_dates[int(train_eval[4])].date()) if train_eval[4] >= 0 else "",
                "worst_final_start_validation": str(valid_dates[int(valid_eval[4])].date()) if valid_eval[4] >= 0 else "",
                "worst_mdd_start_train": str(train_dates[int(train_eval[5])].date()) if train_eval[5] >= 0 else "",
                "worst_mdd_start_validation": str(valid_dates[int(valid_eval[5])].date()) if valid_eval[5] >= 0 else "",
                "turnover_annual": turnover,
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


def precompute_signals(returns: pd.DataFrame) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for lb in [1, 2, 3, 4, 6, 8, 10, 12]:
        out[f"ndx_{lb}"] = (1.0 + returns["ndx"]).rolling(lb).apply(np.prod, raw=True).shift(1) - 1.0
        out[f"tlt_{lb}"] = (1.0 + returns["long_treasury"]).rolling(lb).apply(np.prod, raw=True).shift(1) - 1.0
    return out


def sample_params(rng: np.random.Generator, family_id: int) -> dict[str, Any]:
    return {
        "family_id": family_id,
        "ndx_lb": int(rng.choice([1, 2, 3, 4, 6, 8, 10, 12])),
        "tlt_lb": int(rng.choice([1, 2, 3, 4, 6, 8, 10, 12])),
        "ndx_long": float(rng.uniform(0.0, 12.0)),
        "ndx_short": float(rng.uniform(0.0, 12.0)),
        "tlt_long": float(rng.uniform(0.0, 12.0)),
        "tlt_short": float(rng.uniform(0.0, 12.0)),
        "shy_weight": float(rng.uniform(-2.0, 8.0)),
        "threshold_ndx": float(rng.uniform(0.0, 0.08)),
        "threshold_tlt": float(rng.uniform(0.0, 0.05)),
        "max_gross": float(rng.uniform(1.0, 18.0)),
        "vol_target": float(rng.choice([0.0, 0.20, 0.35, 0.50, 0.75, 1.00])),
        "vol_lb": int(rng.choice([3, 6, 12])),
    }


def build_strategy(returns: pd.DataFrame, signals: dict[str, pd.Series], params: dict[str, Any]) -> tuple[pd.Series, pd.DataFrame]:
    ndx_sig = signals[f"ndx_{params['ndx_lb']}"].fillna(0.0)
    tlt_sig = signals[f"tlt_{params['tlt_lb']}"].fillna(0.0)
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    weights["ndx"] = np.where(
        ndx_sig > params["threshold_ndx"],
        params["ndx_long"],
        np.where(ndx_sig < -params["threshold_ndx"], -params["ndx_short"], 0.0),
    )
    weights["long_treasury"] = np.where(
        tlt_sig > params["threshold_tlt"],
        params["tlt_long"],
        np.where(tlt_sig < -params["threshold_tlt"], -params["tlt_short"], 0.0),
    )
    weights["short_treasury"] = params["shy_weight"]
    gross = weights.abs().sum(axis=1).replace(0.0, np.nan)
    scale = (params["max_gross"] / gross).clip(upper=1.0).fillna(0.0)
    weights = weights.mul(scale, axis=0)
    base = (weights * returns).sum(axis=1)
    if params["vol_target"] > 0:
        realized = base.rolling(int(params["vol_lb"])).std().shift(1) * np.sqrt(12.0)
        vol_scale = (params["vol_target"] / realized).replace([np.inf, -np.inf], np.nan).clip(0.0, 3.0).fillna(0.0)
        weights = weights.mul(vol_scale, axis=0)
        gross = weights.abs().sum(axis=1).replace(0.0, np.nan)
        scale = (params["max_gross"] / gross).clip(upper=1.0).fillna(0.0)
        weights = weights.mul(scale, axis=0)
    series = (weights * returns).sum(axis=1)
    return series.astype(float), weights.astype(float)


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
    accepted.to_csv(output_dir / "accepted_tsmom_corr95_strategies.csv", index=False)
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
