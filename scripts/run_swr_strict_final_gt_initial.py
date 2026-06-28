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


CAMPAIGN_ID = "swr_strict_final_gt_initial_360jobs"
INITIAL_CAPITAL = 100_000.0
MONTHLY_WITHDRAWAL = 2_000.0
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2019-12-31")
LOCKED_START = pd.Timestamp("2020-01-01")
MIN_HORIZON_TRAIN = 120
MIN_HORIZON_VALIDATION = 60
MAX_MDD_AFTER_WITHDRAWALS = -0.50
MAX_TURNOVER_ANNUAL = 6.0
MIN_PROXY_CORRELATION = 0.95

PROXIES = {
    "ndx": {"symbol": "^NDX", "tradable_proxy": "QQQ", "kind": "index_proxy"},
    "sp500": {"symbol": "^GSPC", "tradable_proxy": "SPY", "kind": "index_proxy"},
    "russell2000": {"symbol": "^RUT", "tradable_proxy": "IWM", "kind": "index_proxy"},
    "dow": {"symbol": "^DJI", "tradable_proxy": "DIA", "kind": "index_proxy"},
    "long_treasury": {"symbol": "VUSTX", "tradable_proxy": "TLT", "kind": "fund_proxy"},
    "intermediate_treasury": {"symbol": "VFITX", "tradable_proxy": "IEF", "kind": "fund_proxy"},
    "short_treasury": {"symbol": "VFISX", "tradable_proxy": "SHY", "kind": "fund_proxy"},
    "high_yield": {"symbol": "VWEHX", "tradable_proxy": "HYG", "kind": "fund_proxy"},
    "precious_metals": {"symbol": "PRCIX", "tradable_proxy": "GLD_GDX_PROXY", "kind": "fund_proxy"},
    "small_value": {"symbol": "RYOCX", "tradable_proxy": "IWN_PROXY", "kind": "fund_proxy"},
    "small_cap": {"symbol": "NAESX", "tradable_proxy": "IWM_PROXY", "kind": "fund_proxy"},
    "gold_miners": {"symbol": "VGPMX", "tradable_proxy": "GDX_PROXY", "kind": "fund_proxy"},
}

PROXY_CORRELATION_ALLOWED = {
    # Measured on overlapping monthly returns up to 2019-12-31.
    # Only sleeves with proxy-vs-real ETF correlation >= 0.95 are enabled.
    "ndx": 0.999176,
    "short_treasury": 0.951883,
    "long_treasury": 0.989281,
}

RISK_SETS = [
    ["ndx", "long_treasury", "short_treasury"],
    ["ndx", "short_treasury"],
    ["ndx", "long_treasury"],
    ["long_treasury", "short_treasury"],
]


@njit
def _eval_withdrawal(
    returns: np.ndarray,
    min_horizon: int,
    initial_capital: float,
    monthly_withdrawal: float,
    final_gt: float,
) -> tuple[int, int, float, float, int, int]:
    failed = 0
    non_positive_final = 0
    min_final = 1.0e18
    worst_mdd = 0.0
    worst_final_index = -1
    worst_mdd_index = -1
    n = len(returns)
    for start in range(n):
        if n - start < min_horizon:
            continue
        capital = initial_capital
        peak = initial_capital
        mdd = 0.0
        failed_path = False
        for idx in range(start, n):
            capital -= monthly_withdrawal
            if capital <= 0.0:
                failed_path = True
                break
            capital *= 1.0 + returns[idx]
            if capital <= 0.0:
                failed_path = True
                break
            if capital > peak:
                peak = capital
            dd = capital / peak - 1.0
            if dd < mdd:
                mdd = dd
        if failed_path:
            failed += 1
        if capital <= final_gt:
            non_positive_final += 1
        if capital < min_final:
            min_final = capital
            worst_final_index = start
        if mdd < worst_mdd:
            worst_mdd = mdd
            worst_mdd_index = start
    return failed, non_positive_final, min_final, worst_mdd, worst_final_index, worst_mdd_index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--mode", choices=["data", "shard", "merge"], required=True)
    parser.add_argument("--family-id", type=int, default=0)
    parser.add_argument("--shard-id", type=int, default=0)
    parser.add_argument("--configs-per-shard", type=int, default=4000)
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
    validate_proxy_universe()
    symbols = [PROXIES[sleeve]["symbol"] for sleeve in PROXY_CORRELATION_ALLOWED]
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
    for sleeve in PROXY_CORRELATION_ALLOWED:
        meta = PROXIES[sleeve]
        symbol = meta["symbol"]
        prices[sleeve] = raw[symbol]["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]
    prices = prices.dropna(how="any")
    if prices.empty:
        raise RuntimeError("No proxy data downloaded.")
    if prices.index.max() >= LOCKED_START:
        raise RuntimeError(f"Locked data leak: {prices.index.max()}")
    monthly_prices = prices.resample("ME").last().dropna()
    monthly_returns = monthly_prices.pct_change().dropna()
    if monthly_returns.index.max() >= LOCKED_START:
        raise RuntimeError(f"Locked monthly return leak: {monthly_returns.index.max()}")
    data_dir = output_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monthly_returns.to_csv(data_dir / "monthly_returns.csv", index_label="timestamp")
    proxy_rows = []
    for sleeve in PROXY_CORRELATION_ALLOWED:
        meta = PROXIES[sleeve]
        proxy_rows.append(
            {
                "sleeve": sleeve,
                **meta,
                "proxy_correlation_to_real": PROXY_CORRELATION_ALLOWED[sleeve],
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
        [
            {
                "locked_start": "2020-01-01",
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "max_data_date": prices.index.max().date().isoformat(),
                "status": "pass",
            }
        ]
    ).to_csv(data_dir / "locked_access_audit.csv", index=False)


def validate_proxy_universe() -> None:
    allowed = set(PROXY_CORRELATION_ALLOWED)
    for sleeve, corr in PROXY_CORRELATION_ALLOWED.items():
        if sleeve not in PROXIES:
            raise RuntimeError(f"Unknown proxy sleeve: {sleeve}")
        if corr < MIN_PROXY_CORRELATION:
            raise RuntimeError(f"Proxy sleeve {sleeve} below correlation threshold: {corr}")
    for risk_set in RISK_SETS:
        forbidden = sorted(set(risk_set) - allowed)
        if forbidden:
            raise RuntimeError(f"Risk set contains proxy below correlation threshold: {forbidden}")


def run_shard(output_dir: Path, family_id: int, shard_id: int, configs_per_shard: int, top_per_shard: int) -> None:
    data_path = output_dir / "data" / "monthly_returns.csv"
    returns = pd.read_csv(data_path, parse_dates=["timestamp"]).set_index("timestamp").astype(float)
    if returns.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached shard.")
    rng = np.random.default_rng(family_id * 1_000_003 + shard_id * 97 + 42)
    train = returns[returns.index <= TRAIN_END]
    validation = returns[(returns.index >= VALIDATION_START) & (returns.index <= VALIDATION_END)]
    rows: list[dict[str, Any]] = []
    for config_index in range(configs_per_shard):
        candidate = make_candidate(returns, rng, family_id)
        if candidate is None:
            continue
        strategy_returns, weights, params = candidate
        if not np.isfinite(strategy_returns).all() or strategy_returns.min() <= -0.99:
            continue
        turnover = annual_turnover(weights)
        if turnover > MAX_TURNOVER_ANNUAL:
            continue
        train_series = strategy_returns.loc[train.index].astype(float)
        validation_series = strategy_returns.loc[validation.index].astype(float)
        train_eval = _eval_withdrawal(
            train_series.to_numpy(np.float64),
            MIN_HORIZON_TRAIN,
            INITIAL_CAPITAL,
            MONTHLY_WITHDRAWAL,
            INITIAL_CAPITAL,
        )
        validation_eval = _eval_withdrawal(
            validation_series.to_numpy(np.float64),
            MIN_HORIZON_VALIDATION,
            INITIAL_CAPITAL,
            MONTHLY_WITHDRAWAL,
            INITIAL_CAPITAL,
        )
        accepted = (
            train_eval[0] == 0
            and train_eval[1] == 0
            and validation_eval[0] == 0
            and validation_eval[1] == 0
            and train_eval[3] > MAX_MDD_AFTER_WITHDRAWALS
            and validation_eval[3] > MAX_MDD_AFTER_WITHDRAWALS
        )
        train_metrics = return_metrics(train_series)
        validation_metrics = return_metrics(validation_series)
        config_hash = hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()
        rows.append(
            {
                "strategy_id": f"swr_strict_f{family_id:02d}_s{shard_id:02d}_{config_hash[:16]}",
                "family_id": family_id,
                "shard_id": shard_id,
                "config_index": config_index,
                "accepted": bool(accepted),
                "train_failed_starts": int(train_eval[0]),
                "validation_failed_starts": int(validation_eval[0]),
                "train_final_le_initial_count": int(train_eval[1]),
                "validation_final_le_initial_count": int(validation_eval[1]),
                "worst_final_capital_train": float(train_eval[2]),
                "worst_final_capital_validation": float(validation_eval[2]),
                "mdd_after_withdrawals_train": float(train_eval[3]),
                "mdd_after_withdrawals_validation": float(validation_eval[3]),
                "worst_final_start_train": str(train.index[int(train_eval[4])].date()) if train_eval[4] >= 0 else "",
                "worst_final_start_validation": str(validation.index[int(validation_eval[4])].date()) if validation_eval[4] >= 0 else "",
                "worst_mdd_start_train": str(train.index[int(train_eval[5])].date()) if train_eval[5] >= 0 else "",
                "worst_mdd_start_validation": str(validation.index[int(validation_eval[5])].date()) if validation_eval[5] >= 0 else "",
                "cagr_train": train_metrics["cagr"],
                "cagr_validation": validation_metrics["cagr"],
                "sharpe_train": train_metrics["sharpe"],
                "sharpe_validation": validation_metrics["sharpe"],
                "raw_mdd_train": train_metrics["mdd"],
                "raw_mdd_validation": validation_metrics["mdd"],
                "turnover_annual": turnover,
                "uses_concrete_stocks": False,
                "uses_crypto": False,
                "locked_opened": False,
                "data_end_max": "2019-12-31",
                "params_json": json.dumps(params, sort_keys=True),
                "config_hash": config_hash,
                "score": score_row(accepted, train_eval, validation_eval, train_metrics, validation_metrics, turnover),
            }
        )
    shard_dir = output_dir / "shards" / f"family_{family_id:02d}_shard_{shard_id:02d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    metrics = pd.DataFrame(rows)
    if metrics.empty:
        metrics = pd.DataFrame(columns=["strategy_id", "accepted", "score"])
    metrics.sort_values("score", ascending=False).head(top_per_shard).to_csv(shard_dir / "top_candidates.csv", index=False)
    metrics[metrics.get("accepted", pd.Series(dtype=bool)).astype(bool)].to_csv(shard_dir / "accepted_candidates.csv", index=False)


def make_candidate(returns: pd.DataFrame, rng: np.random.Generator, family_id: int) -> tuple[pd.Series, pd.DataFrame, dict[str, Any]] | None:
    group = family_id % 5
    risk_set = RISK_SETS[int(rng.integers(0, len(RISK_SETS)))]
    lookback = int(rng.choice([3, 6, 10, 12]))
    vol_lookback = int(rng.choice([3, 6, 10, 12]))
    top_n = int(rng.choice([1, 2, 3, 4]))
    rebalance_months = int(rng.choice([1, 3, 6, 12]))
    band = float(rng.choice([0.0, 0.15, 0.30, 0.55, 0.80]))
    leverage = float(rng.uniform(1.0, 10.0))
    safe = str(rng.choice(["short_treasury", "long_treasury"]))
    if group == 0:
        weights = long_only_momentum_weights(returns, risk_set, lookback, vol_lookback, top_n, rebalance_months, band, safe)
        mode = "long_only_momentum"
    elif group == 1:
        weights = long_short_trend_weights(returns, risk_set, lookback, vol_lookback, top_n, rebalance_months, band)
        mode = "long_short_trend"
    elif group == 2:
        weights = long_short_trend_weights(returns, risk_set, lookback, vol_lookback, top_n, rebalance_months, band)
        target_vol = float(rng.uniform(0.12, 0.65))
        weights = apply_vol_target(returns, weights, vol_lookback, target_vol, cap=float(rng.uniform(2.0, 12.0)))
        mode = "long_short_vol_target"
    elif group == 3:
        weights = static_random_weights(returns, rng, risk_set)
        mode = "static_random"
    else:
        weights = hybrid_defensive_weights(returns, risk_set, lookback, vol_lookback, top_n, rebalance_months, band, safe)
        mode = "hybrid_defensive"
    weights = weights.reindex(columns=returns.columns, fill_value=0.0).fillna(0.0)
    weights = weights * leverage
    strategy = (weights * returns).sum(axis=1)
    params = {
        "mode": mode,
        "family_id": family_id,
        "risk_set": risk_set,
        "lookback": lookback,
        "vol_lookback": vol_lookback,
        "top_n": top_n,
        "rebalance_months": rebalance_months,
        "band": band,
        "gross_leverage": leverage,
        "safe": safe,
    }
    return strategy, weights, params


def long_only_momentum_weights(
    returns: pd.DataFrame,
    risk_set: list[str],
    lookback: int,
    vol_lookback: int,
    top_n: int,
    rebalance_months: int,
    band: float,
    safe: str,
) -> pd.DataFrame:
    mom = (1.0 + returns[risk_set]).rolling(lookback).apply(np.prod, raw=True).shift(1) - 1.0
    vol = returns[risk_set].rolling(vol_lookback).std().shift(1).replace(0.0, np.nan)
    target = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    for dt in returns.index:
        scores = mom.loc[dt].dropna()
        scores = scores[scores > 0.0]
        if scores.empty:
            target.loc[dt, safe] = 1.0
            continue
        selected = list(scores.sort_values(ascending=False).head(top_n).index)
        inv = (1.0 / vol.loc[dt, selected]).replace([np.inf, -np.inf], np.nan).dropna()
        if inv.empty:
            target.loc[dt, safe] = 1.0
            continue
        inv = inv / inv.sum()
        target.loc[dt, inv.index] = inv.values
    return rebalance_with_band(target, rebalance_months, band)


def long_short_trend_weights(
    returns: pd.DataFrame,
    risk_set: list[str],
    lookback: int,
    vol_lookback: int,
    top_n: int,
    rebalance_months: int,
    band: float,
) -> pd.DataFrame:
    mom = (1.0 + returns[risk_set]).rolling(lookback).apply(np.prod, raw=True).shift(1) - 1.0
    vol = returns[risk_set].rolling(vol_lookback).std().shift(1).replace(0.0, np.nan)
    target = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    for dt in returns.index:
        scores = mom.loc[dt].dropna()
        if scores.empty:
            continue
        ranked = scores.abs().sort_values(ascending=False).head(top_n)
        inv = (1.0 / vol.loc[dt, ranked.index]).replace([np.inf, -np.inf], np.nan).dropna()
        if inv.empty:
            continue
        signed = np.sign(scores.loc[inv.index])
        gross = inv / inv.sum()
        target.loc[dt, inv.index] = gross.values * signed.values
    return rebalance_with_band(target, rebalance_months, band)


def hybrid_defensive_weights(
    returns: pd.DataFrame,
    risk_set: list[str],
    lookback: int,
    vol_lookback: int,
    top_n: int,
    rebalance_months: int,
    band: float,
    safe: str,
) -> pd.DataFrame:
    base = long_short_trend_weights(returns, risk_set, lookback, vol_lookback, top_n, rebalance_months, band)
    equity_mom = (1.0 + returns["ndx"]).rolling(lookback).apply(np.prod, raw=True).shift(1) - 1.0
    defensive = base.copy()
    risk_off = equity_mom < 0.0
    defensive.loc[risk_off, :] *= 0.5
    defensive.loc[risk_off, safe] += 0.5
    return defensive


def static_random_weights(returns: pd.DataFrame, rng: np.random.Generator, risk_set: list[str]) -> pd.DataFrame:
    selected = list(rng.choice(risk_set, size=min(len(risk_set), int(rng.choice([2, 3, 4, 5]))), replace=False))
    raw = rng.normal(0.0, 1.0, size=len(selected))
    if rng.random() < 0.6:
        raw = np.abs(raw)
    gross = np.abs(raw).sum()
    raw = raw / gross if gross > 0 else raw
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    weights.loc[:, selected] = raw
    return weights


def apply_vol_target(returns: pd.DataFrame, weights: pd.DataFrame, vol_lookback: int, target_vol: float, cap: float) -> pd.DataFrame:
    base = (weights * returns).sum(axis=1)
    realized = base.rolling(vol_lookback).std().shift(1) * math.sqrt(12.0)
    scale = (target_vol / realized).replace([np.inf, -np.inf], np.nan).clip(lower=0.0, upper=cap).fillna(0.0)
    return weights.mul(scale, axis=0)


def rebalance_with_band(target: pd.DataFrame, rebalance_months: int, band: float) -> pd.DataFrame:
    out = pd.DataFrame(0.0, index=target.index, columns=target.columns)
    last = pd.Series(0.0, index=target.columns)
    for idx, dt in enumerate(target.index):
        desired = target.loc[dt] if idx % rebalance_months == 0 else last
        if float((desired - last).abs().sum()) > band:
            last = desired.astype(float).copy()
        out.loc[dt] = last
    return out


def annual_turnover(weights: pd.DataFrame) -> float:
    if weights.empty:
        return 0.0
    return float(weights.diff().abs().sum(axis=1).mean() * 12.0)


def return_metrics(series: pd.Series) -> dict[str, float]:
    clean = series.dropna()
    if clean.empty:
        return {"cagr": float("nan"), "sharpe": float("nan"), "mdd": float("nan")}
    curve = (1.0 + clean).cumprod()
    cagr = float(curve.iloc[-1] ** (12.0 / len(clean)) - 1.0)
    sharpe = float(clean.mean() / clean.std() * math.sqrt(12.0)) if clean.std() > 0 else 0.0
    mdd = float((curve / curve.cummax() - 1.0).min())
    return {"cagr": cagr, "sharpe": sharpe, "mdd": mdd}


def score_row(
    accepted: bool,
    train_eval: tuple[Any, ...],
    validation_eval: tuple[Any, ...],
    train_metrics: dict[str, float],
    validation_metrics: dict[str, float],
    turnover: float,
) -> float:
    return (
        (1_000_000_000.0 if accepted else 0.0)
        - (train_eval[0] + validation_eval[0]) * 10_000_000.0
        - (train_eval[1] + validation_eval[1]) * 1_000_000.0
        + min(float(train_eval[2]), float(validation_eval[2]))
        + (float(train_eval[3]) + float(validation_eval[3])) * 100_000.0
        + float(validation_metrics["cagr"]) * 10_000.0
        + float(validation_metrics["sharpe"]) * 1_000.0
        - turnover * 100.0
    )


def run_merge(output_dir: Path) -> None:
    shard_root = output_dir / "shards"
    files = list(shard_root.glob("**/top_candidates.csv"))
    accepted_files = list(shard_root.glob("**/accepted_candidates.csv"))
    metrics = pd.concat([pd.read_csv(path) for path in files], ignore_index=True) if files else pd.DataFrame()
    accepted = pd.concat([pd.read_csv(path) for path in accepted_files], ignore_index=True) if accepted_files else pd.DataFrame()
    if not metrics.empty:
        metrics = metrics.sort_values("score", ascending=False)
    if not accepted.empty:
        accepted = accepted.sort_values("score", ascending=False)
    metrics.to_csv(output_dir / "all_top_candidates.csv", index=False)
    accepted.to_csv(output_dir / "accepted_strict_strategies.csv", index=False)
    proxy_map = output_dir / "data" / "proxy_map.csv"
    if proxy_map.exists():
        pd.read_csv(proxy_map).to_csv(output_dir / "proxy_map.csv", index=False)
    locked = output_dir / "data" / "locked_access_audit.csv"
    if locked.exists():
        pd.read_csv(locked).to_csv(output_dir / "locked_access_audit.csv", index=False)
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "top_candidate_rows": int(len(metrics)),
        "accepted_count": int(len(accepted)),
        "monthly_withdrawal": MONTHLY_WITHDRAWAL,
        "initial_capital": INITIAL_CAPITAL,
        "strict_final_gt_initial": True,
        "locked_opened": False,
        "uses_concrete_stocks": False,
        "uses_crypto": False,
        "data_end_max": "2019-12-31",
    }
    (output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    lines = [
        "# SWR strict final > initial report",
        "",
        f"- Accepted count: {summary['accepted_count']}",
        f"- Top candidate rows: {summary['top_candidate_rows']}",
        f"- Monthly withdrawal: {MONTHLY_WITHDRAWAL}",
        "- Strict final > initial: true",
        "- Locked opened: false",
    ]
    (output_dir / "SWR_STRICT_FINAL_GT_INITIAL_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
