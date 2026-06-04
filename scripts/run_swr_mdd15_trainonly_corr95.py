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


CAMPAIGN_ID = "swr_mdd15_trainonly_corr95_360jobs"
INITIAL_CAPITAL = 100_000.0
MONTHLY_WITHDRAWAL = 2_000.0
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2019-12-31")
LOCKED_START = pd.Timestamp("2020-01-01")
MIN_HORIZON_TRAIN = 120
MIN_HORIZON_VALIDATION = 60
MAX_MDD_AFTER_WITHDRAWALS = -0.15
MIN_PROXY_CORRELATION = 0.95
MAX_TURNOVER_ANNUAL = 8.0

PROXIES = {
    "ndx": {"symbol": "^NDX", "tradable_proxy": "QQQ", "proxy_correlation": 0.999176},
    "sp500": {"symbol": "VFINX", "tradable_proxy": "SPY", "proxy_correlation": 0.998036},
    "small": {"symbol": "NAESX", "tradable_proxy": "IWM", "proxy_correlation": 0.990462},
    "energy": {"symbol": "FSENX", "tradable_proxy": "XLE", "proxy_correlation": 0.969366},
    "financial": {"symbol": "FIDSX", "tradable_proxy": "XLF", "proxy_correlation": 0.966307},
    "long_treasury": {"symbol": "VUSTX", "tradable_proxy": "TLT", "proxy_correlation": 0.989280},
    "intermediate_treasury": {"symbol": "VFITX", "tradable_proxy": "IEF", "proxy_correlation": 0.981267},
    "short_treasury": {"symbol": "VFISX", "tradable_proxy": "SHY", "proxy_correlation": 0.951884},
}

ASSETS = list(PROXIES)
RISK_ASSETS = ["ndx", "sp500", "small", "energy", "financial", "long_treasury"]
SAFE_ASSETS = ["short_treasury", "intermediate_treasury", "long_treasury"]


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
    parser.add_argument("--configs-per-shard", type=int, default=25_000)
    parser.add_argument("--time-budget-minutes", type=float, default=45.0)
    parser.add_argument("--top-per-shard", type=int, default=80)
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "data":
        run_data(output_dir)
    elif args.mode == "shard":
        run_shard(
            output_dir,
            args.family_id,
            args.shard_id,
            args.configs_per_shard,
            args.time_budget_minutes,
            args.top_per_shard,
        )
    else:
        run_merge(output_dir)


def run_data(output_dir: Path) -> None:
    for name, meta in PROXIES.items():
        if meta["proxy_correlation"] < MIN_PROXY_CORRELATION:
            raise RuntimeError(f"Proxy below threshold: {name}")
    prices = download_proxy_prices()
    prices = prices.dropna(how="any")
    monthly = prices.resample("ME").last().pct_change().dropna()
    if prices.index.max() >= LOCKED_START or monthly.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data leak.")
    if monthly.index.min() > pd.Timestamp("1995-02-28"):
        raise RuntimeError(f"Insufficient 1995 history: {monthly.index.min()}")
    if len(monthly) < 250:
        raise RuntimeError(f"Too few monthly rows: {len(monthly)}")
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
        [
            {
                "locked_start": "2020-01-01",
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "max_data_date": "2019-12-31",
                "validation_used_for_selection": False,
            }
        ]
    ).to_csv(data_dir / "locked_access_audit.csv", index=False)


def download_proxy_prices() -> pd.DataFrame:
    symbols = [meta["symbol"] for meta in PROXIES.values()]
    last_error: Exception | None = None
    for _ in range(3):
        try:
            raw = yf.download(
                symbols,
                start="1995-01-01",
                end="2020-01-01",
                auto_adjust=True,
                progress=False,
                group_by="ticker",
                threads=True,
            )
            prices = extract_prices(raw)
            if len(prices.dropna(how="any")) >= 250:
                return prices
        except Exception as exc:
            last_error = exc
        time.sleep(2.0)
    frames = []
    for name, meta in PROXIES.items():
        raw = yf.download(
            meta["symbol"],
            start="1995-01-01",
            end="2020-01-01",
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=False,
        )
        close = raw["Close"] if "Close" in raw else raw[meta["symbol"]]["Close"]
        frames.append(close.rename(name))
    prices = pd.concat(frames, axis=1)
    if prices.dropna(how="any").empty:
        raise RuntimeError(f"Could not download proxy prices: {last_error}")
    return prices


def extract_prices(raw: pd.DataFrame) -> pd.DataFrame:
    prices = pd.DataFrame()
    for name, meta in PROXIES.items():
        symbol = meta["symbol"]
        if isinstance(raw.columns, pd.MultiIndex):
            prices[name] = raw[symbol]["Close"]
        else:
            prices[name] = raw["Close"]
    return prices


def run_shard(
    output_dir: Path,
    family_id: int,
    shard_id: int,
    configs_per_shard: int,
    time_budget_minutes: float,
    top_per_shard: int,
) -> None:
    returns = pd.read_csv(output_dir / "data" / "monthly_returns.csv", parse_dates=["timestamp"]).set_index("timestamp")
    if returns.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached shard.")
    if len(returns) < 250:
        raise RuntimeError(f"Too few monthly rows in shard: {len(returns)}")
    train = returns[returns.index <= TRAIN_END]
    valid = returns[(returns.index >= VALIDATION_START) & (returns.index <= VALIDATION_END)]
    train_dates = train.index
    valid_dates = valid.index
    eval_all_starts(np.zeros(130, dtype=np.float64), 60)
    signals = precompute_signals(returns)
    rows: list[dict[str, Any]] = []
    rng = np.random.default_rng(61_000_003 + family_id * 1_000_003 + shard_id * 1009)
    started = time.monotonic()
    deadline = started + max(1.0, time_budget_minutes) * 60.0
    evaluated = 0
    train_evaluated = 0
    validation_evaluated = 0
    for config_index in range(configs_per_shard):
        if time.monotonic() >= deadline:
            break
        evaluated += 1
        params = sample_params(rng, family_id)
        series, weights = build_strategy(returns, signals, params)
        if series.min() <= -0.98 or not np.isfinite(series.to_numpy()).all():
            continue
        turnover = float(weights.diff().abs().sum(axis=1).mean() * 12.0)
        if turnover > MAX_TURNOVER_ANNUAL:
            continue
        train_series = series.loc[train.index]
        train_eval = eval_all_starts(train_series.to_numpy(np.float64), MIN_HORIZON_TRAIN)
        train_evaluated += 1
        train_pass = (
            train_eval[0] == 0
            and train_eval[1] == 0
            and train_eval[3] > MAX_MDD_AFTER_WITHDRAWALS
        )
        train_metrics = period_metrics(train_series)
        train_score = train_only_score(train_eval, train_metrics, turnover, train_pass)
        keep_for_report = train_pass or train_score > -500_000_000.0 or config_index % 307 == 0
        if not keep_for_report:
            continue
        valid_series = series.loc[valid.index]
        valid_eval = eval_all_starts(valid_series.to_numpy(np.float64), MIN_HORIZON_VALIDATION)
        validation_evaluated += 1
        validation_pass = (
            valid_eval[0] == 0
            and valid_eval[1] == 0
            and valid_eval[3] > MAX_MDD_AFTER_WITHDRAWALS
        )
        validation_metrics = period_metrics(valid_series)
        config_hash = hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()
        rows.append(
            {
                "strategy_id": f"swr_mdd15_trainonly_corr95_f{family_id:02d}_s{shard_id:02d}_{config_hash[:16]}",
                "family_id": family_id,
                "shard_id": shard_id,
                "config_index": config_index,
                "train_pass": bool(train_pass),
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
                "worst_final_start_train": str(train_dates[int(train_eval[4])].date()) if train_eval[4] >= 0 else "",
                "worst_final_start_validation": str(valid_dates[int(valid_eval[4])].date()) if valid_eval[4] >= 0 else "",
                "worst_mdd_start_train": str(train_dates[int(train_eval[5])].date()) if train_eval[5] >= 0 else "",
                "worst_mdd_start_validation": str(valid_dates[int(valid_eval[5])].date()) if valid_eval[5] >= 0 else "",
                "train_cagr": train_metrics["cagr"],
                "validation_cagr": validation_metrics["cagr"],
                "train_sharpe": train_metrics["sharpe"],
                "validation_sharpe": validation_metrics["sharpe"],
                "train_calmar": train_metrics["calmar"],
                "validation_calmar": validation_metrics["calmar"],
                "train_months_positive_pct": train_metrics["months_positive_pct"],
                "validation_months_positive_pct": validation_metrics["months_positive_pct"],
                "turnover_annual": turnover,
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
                "train_evaluated": int(train_evaluated),
                "validation_evaluated_report_only": int(validation_evaluated),
                "elapsed_seconds": float(time.monotonic() - started),
                "time_budget_minutes": float(time_budget_minutes),
                "rows_kept": int(len(df)),
                "train_pass_rows": int(df.get("train_pass", pd.Series(dtype=bool)).astype(bool).sum()) if "train_pass" in df else 0,
                "final_verified_report_only_rows": int(len(verified)),
                "max_turnover_annual": MAX_TURNOVER_ANNUAL,
                "max_mdd_after_withdrawals_required": MAX_MDD_AFTER_WITHDRAWALS,
                "proxy_corr_min": min(meta["proxy_correlation"] for meta in PROXIES.values()),
                "locked_opened": False,
                "validation_used_for_selection": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def precompute_signals(returns: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for lb in [1, 2, 3, 4, 6, 8, 10, 12]:
        out[f"mom_{lb}"] = (1.0 + returns[ASSETS]).rolling(lb).apply(np.prod, raw=True).shift(1) - 1.0
        out[f"risk_mom_{lb}"] = (1.0 + returns[RISK_ASSETS]).rolling(lb).apply(np.prod, raw=True).shift(1) - 1.0
        out[f"safe_mom_{lb}"] = (1.0 + returns[SAFE_ASSETS]).rolling(lb).apply(np.prod, raw=True).shift(1) - 1.0
    for lb in [3, 6, 12]:
        out[f"vol_{lb}"] = returns[ASSETS].rolling(lb).std().shift(1)
    for lb in [3, 6, 12]:
        out[f"breadth_{lb}"] = (out[f"risk_mom_{lb}"] > 0.0).mean(axis=1)
    for asset in ["ndx", "sp500", "long_treasury", "short_treasury"]:
        for lb in [1, 3, 6, 12]:
            out[f"{asset}_filter_{lb}"] = (1.0 + returns[asset]).rolling(lb).apply(np.prod, raw=True).shift(1) - 1.0
    return out


def sample_params(rng: np.random.Generator, family_id: int) -> dict[str, Any]:
    mode = family_id % 5
    low_leverage_family = family_id in {0, 1, 5, 6, 10, 15}
    max_gross_hi = 7.0 if low_leverage_family else 12.0
    return {
        "family_id": family_id,
        "mode": mode,
        "risk_lb": int(rng.choice([1, 2, 3, 4, 6, 8, 10, 12])),
        "safe_lb": int(rng.choice([1, 3, 6, 12])),
        "vol_lb": int(rng.choice([3, 6, 12])),
        "top_n": int(rng.choice([1, 2, 3, 4])),
        "risk_long": float(rng.uniform(0.0, 8.0 if low_leverage_family else 14.0)),
        "risk_short": float(rng.uniform(0.0, 5.0 if low_leverage_family else 10.0)),
        "safe_long": float(rng.uniform(0.0, 10.0 if low_leverage_family else 16.0)),
        "safe_short": float(rng.uniform(0.0, 4.0 if low_leverage_family else 8.0)),
        "cash_buffer": float(rng.uniform(0.0, 0.65)),
        "momentum_threshold": float(rng.uniform(-0.035, 0.075)),
        "short_threshold": float(rng.uniform(0.0, 0.08)),
        "filter_asset": str(rng.choice(["ndx", "sp500", "long_treasury", "short_treasury"])),
        "filter_lb": int(rng.choice([1, 3, 6, 12])),
        "filter_threshold": float(rng.uniform(-0.10, 0.08)),
        "filter_risk_scale": float(rng.choice([0.0, 0.15, 0.25, 0.40, 0.60, 0.80, 1.0])),
        "breadth_lb": int(rng.choice([3, 6, 12])),
        "breadth_threshold": float(rng.uniform(0.20, 0.95)),
        "breadth_risk_scale": float(rng.choice([0.0, 0.15, 0.25, 0.50, 0.75, 1.0])),
        "vol_target": float(rng.choice([0.0, 0.12, 0.18, 0.25, 0.35, 0.50])),
        "max_gross": float(rng.uniform(1.0, max_gross_hi)),
        "rebalance_months": int(rng.choice([1, 2, 3, 6])),
        "rebalance_band": float(rng.choice([0.0, 0.25, 0.50, 1.0, 2.0, 4.0])),
        "loss_guard_lb": int(rng.choice([1, 2, 3, 6])),
        "loss_guard_threshold": float(rng.choice([-0.16, -0.12, -0.09, -0.06, -0.04])),
        "loss_guard_scale": float(rng.choice([0.0, 0.15, 0.25, 0.40, 0.60])),
        "loss_guard_safe_blend": float(rng.choice([0.25, 0.50, 0.75, 1.00])),
    }


def build_strategy(returns: pd.DataFrame, signals: dict[str, Any], params: dict[str, Any]) -> tuple[pd.Series, pd.DataFrame]:
    weights = raw_weights(returns, signals, params)
    weights = apply_vol_target_and_cap(weights, returns, params)
    weights = apply_loss_guard(weights, returns, params)
    weights = rebalance_with_band(weights, int(params["rebalance_months"]), float(params["rebalance_band"]))
    series = (weights * returns).sum(axis=1)
    return series.astype(float), weights.astype(float)


def raw_weights(returns: pd.DataFrame, signals: dict[str, Any], params: dict[str, Any]) -> pd.DataFrame:
    mode = int(params["mode"])
    risk_mom = signals[f"risk_mom_{params['risk_lb']}"].fillna(0.0)
    safe_mom = signals[f"safe_mom_{params['safe_lb']}"].fillna(0.0)
    risk_vol = signals[f"vol_{params['vol_lb']}"][RISK_ASSETS].replace(0.0, np.nan)
    safe_vol = signals[f"vol_{params['vol_lb']}"][SAFE_ASSETS].replace(0.0, np.nan)
    filter_signal = signals[f"{params['filter_asset']}_filter_{params['filter_lb']}"].fillna(0.0)
    breadth = signals[f"breadth_{params['breadth_lb']}"].fillna(0.0)
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    for dt in returns.index:
        risk_scale = 1.0 if float(filter_signal.loc[dt]) >= params["filter_threshold"] else params["filter_risk_scale"]
        if float(breadth.loc[dt]) < params["breadth_threshold"]:
            risk_scale *= params["breadth_risk_scale"]
        risk_row = risk_mom.loc[dt].sort_values(ascending=False)
        safe_row = safe_mom.loc[dt].sort_values(ascending=False)
        risk_picks = risk_row[risk_row > params["momentum_threshold"]].head(int(params["top_n"])).index.tolist()
        safe_picks = safe_row.head(2).index.tolist()
        row = pd.Series(0.0, index=returns.columns)
        if mode in {0, 1, 3, 4} and risk_picks and risk_scale > 0.0:
            inv = (1.0 / risk_vol.loc[dt, risk_picks]).replace([np.inf, -np.inf], np.nan).fillna(1.0)
            inv = inv / inv.sum()
            row.loc[risk_picks] += inv * params["risk_long"] * risk_scale
        if mode in {1, 2, 4}:
            short_picks = risk_row[risk_row < -params["short_threshold"]].sort_values(ascending=True).head(int(params["top_n"])).index.tolist()
            if short_picks:
                inv = (1.0 / risk_vol.loc[dt, short_picks]).replace([np.inf, -np.inf], np.nan).fillna(1.0)
                inv = inv / inv.sum()
                row.loc[short_picks] -= inv * params["risk_short"] * (1.0 - 0.5 * risk_scale)
        if safe_picks:
            inv_safe = (1.0 / safe_vol.loc[dt, safe_picks]).replace([np.inf, -np.inf], np.nan).fillna(1.0)
            inv_safe = inv_safe / inv_safe.sum()
            row.loc[safe_picks] += inv_safe * params["safe_long"] * (1.0 - params["cash_buffer"])
        if mode in {2, 4}:
            weak_safe = safe_row[safe_row < -params["short_threshold"]].sort_values(ascending=True).head(1).index.tolist()
            if weak_safe:
                row.loc[weak_safe] -= params["safe_short"]
        weights.loc[dt] = row
    return weights


def apply_vol_target_and_cap(weights: pd.DataFrame, returns: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    out = cap_gross(weights, float(params["max_gross"]))
    base = (out * returns).sum(axis=1)
    if float(params["vol_target"]) <= 0.0:
        return out
    realized = base.rolling(int(params["vol_lb"])).std().shift(1) * math.sqrt(12.0)
    vol_scale = (float(params["vol_target"]) / realized).replace([np.inf, -np.inf], np.nan).clip(0.0, 2.0).fillna(0.0)
    out = out.mul(vol_scale, axis=0)
    return cap_gross(out, float(params["max_gross"]))


def apply_loss_guard(weights: pd.DataFrame, returns: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    base = (weights * returns).sum(axis=1)
    trail = (1.0 + base).rolling(int(params["loss_guard_lb"])).apply(np.prod, raw=True).shift(1) - 1.0
    safe = pd.DataFrame(0.0, index=weights.index, columns=weights.columns)
    safe["short_treasury"] = float(params["safe_long"]) * 0.65
    safe["intermediate_treasury"] = float(params["safe_long"]) * 0.25
    safe["long_treasury"] = float(params["safe_long"]) * 0.10
    out = weights.copy()
    mask = trail.fillna(0.0) <= float(params["loss_guard_threshold"])
    if mask.any():
        scaled = weights.mul(float(params["loss_guard_scale"]), axis=0)
        blended = scaled * (1.0 - float(params["loss_guard_safe_blend"])) + safe * float(params["loss_guard_safe_blend"])
        out.loc[mask] = blended.loc[mask]
    return cap_gross(out, float(params["max_gross"]))


def cap_gross(weights: pd.DataFrame, max_gross: float) -> pd.DataFrame:
    gross = weights.abs().sum(axis=1).replace(0.0, np.nan)
    scale = (max_gross / gross).clip(upper=1.0).fillna(0.0)
    return weights.mul(scale, axis=0)


def rebalance_with_band(target: pd.DataFrame, rebalance_months: int, band: float) -> pd.DataFrame:
    out = pd.DataFrame(0.0, index=target.index, columns=target.columns)
    last = pd.Series(0.0, index=target.columns)
    for idx, dt in enumerate(target.index):
        desired = target.loc[dt] if idx % max(1, rebalance_months) == 0 else last
        if float((desired - last).abs().sum()) > band:
            last = desired.astype(float).copy()
        out.loc[dt] = last
    return out


def period_metrics(series: pd.Series) -> dict[str, float]:
    arr = series.to_numpy(np.float64)
    n = len(arr)
    if n == 0:
        return {"cagr": 0.0, "sharpe": 0.0, "calmar": 0.0, "months_positive_pct": 0.0, "mdd": 0.0}
    equity = np.cumprod(1.0 + arr)
    years = n / 12.0
    cagr = float(equity[-1] ** (1.0 / years) - 1.0) if equity[-1] > 0 and years > 0 else -1.0
    vol = float(np.std(arr, ddof=1) * math.sqrt(12.0)) if n > 1 else 0.0
    sharpe = float(np.mean(arr) * 12.0 / vol) if vol > 0 else 0.0
    peaks = np.maximum.accumulate(equity)
    mdd = float(np.min(equity / peaks - 1.0)) if len(equity) else 0.0
    calmar = float(cagr / abs(mdd)) if mdd < 0 else 0.0
    return {
        "cagr": cagr,
        "sharpe": sharpe,
        "calmar": calmar,
        "months_positive_pct": float(np.mean(arr > 0.0)),
        "mdd": mdd,
    }


def train_only_score(train_eval: tuple[int, int, float, float, int, int], metrics: dict[str, float], turnover: float, train_pass: bool) -> float:
    failed, le_initial, worst_final, mdd, _, _ = train_eval
    return (
        (1_000_000_000.0 if train_pass else 0.0)
        - failed * 20_000_000.0
        - le_initial * 2_000_000.0
        + min(worst_final, 10_000_000.0)
        + mdd * 20_000_000.0
        + metrics["sharpe"] * 100_000.0
        + metrics["cagr"] * 250_000.0
        - turnover * 10_000.0
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
    verified.to_csv(output_dir / "verified_mdd15_report_only.csv", index=False)
    train_pass = top[top.get("train_pass", pd.Series(dtype=bool)).astype(bool)] if "train_pass" in top else pd.DataFrame()
    train_pass.to_csv(output_dir / "train_pass_candidates.csv", index=False)
    fail_reasons = build_fail_reasons(top)
    fail_reasons.to_csv(output_dir / "fail_reasons.csv", index=False)
    for name in ["proxy_map.csv", "locked_access_audit.csv"]:
        src = output_dir / "data" / name
        if src.exists():
            pd.read_csv(src).to_csv(output_dir / name, index=False)
    shard_summaries = []
    for path in summary_files:
        try:
            shard_summaries.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    pd.DataFrame(shard_summaries).to_csv(output_dir / "shard_summaries.csv", index=False)
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "verified_count_report_only": int(len(verified)),
        "train_pass_count": int(len(train_pass)),
        "top_candidate_rows": int(len(top)),
        "shards_with_summary": int(len(shard_summaries)),
        "configs_evaluated": int(sum(item.get("configs_evaluated", 0) for item in shard_summaries)),
        "train_evaluated": int(sum(item.get("train_evaluated", 0) for item in shard_summaries)),
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
            elif int(row.get("train_final_le_initial_count", 0)) > 0:
                reason = "train_final_capital_not_above_initial"
            elif float(row.get("mdd_after_withdrawals_train", -1.0)) <= MAX_MDD_AFTER_WITHDRAWALS:
                reason = "train_mdd_after_withdrawals_gt_15pct"
            else:
                reason = "train_other"
        elif int(row.get("validation_failed_starts", 0)) > 0:
            reason = "validation_failed_withdrawal_path_report_only"
        elif int(row.get("validation_final_le_initial_count", 0)) > 0:
            reason = "validation_final_capital_not_above_initial_report_only"
        elif float(row.get("mdd_after_withdrawals_validation", -1.0)) <= MAX_MDD_AFTER_WITHDRAWALS:
            reason = "validation_mdd_after_withdrawals_gt_15pct_report_only"
        else:
            reason = "validation_other_report_only"
        reasons.append(reason)
    return pd.Series(reasons).value_counts().rename_axis("reason").reset_index(name="count")


if __name__ == "__main__":
    main()
