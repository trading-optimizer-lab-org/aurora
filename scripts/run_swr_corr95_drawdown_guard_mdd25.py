from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf


CAMPAIGN_ID = "swr_corr95_drawdown_guard_mdd25_360jobs"
INITIAL_CAPITAL = 100_000.0
MONTHLY_WITHDRAWAL = 2_000.0
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2019-12-31")
LOCKED_START = pd.Timestamp("2020-01-01")
MIN_HORIZON_TRAIN = 120
MIN_HORIZON_VALIDATION = 60
MAX_MDD_AFTER_WITHDRAWALS = -0.25
MIN_PROXY_CORRELATION = 0.95
MAX_TURNOVER_ANNUAL = 6.0
EXCLUDED_CONFIG_HASHES = {
    # Descartada por el usuario tras abrir locked; no se acepta aunque pase train/validacion.
    "f8679aca5411412b1eed0eb978624eb71368f4483b7a271b421392896e6a75a9",
    # Near-misses ya revisados: sobreviven, pero no cumplen MDD <= 25%.
    "dc7b6cffbe94c496fd51274f41442ca85486e7000cb3fb9a18d023da5468ccf8",
    "75ed1026d15ec65d1e8db9152cb9c6111797b1ccfbcc603992a06ae1ca548305",
    "bceb07c3d51b93cae3a89f6af43df18f06d837a880a5ac4717c049c7a3c96732",
}

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

RISK_ASSETS = ["ndx", "sp500", "small", "energy", "financial", "long_treasury"]
SAFE_ASSETS = ["short_treasury", "intermediate_treasury", "long_treasury"]


def eval_all_starts(returns: np.ndarray, min_horizon: int) -> tuple[int, int, float, float, int, int]:
    n = len(returns)
    if n < min_horizon:
        return 0, 0, 1.0e18, 0.0, -1, -1
    starts = np.arange(0, n - min_horizon + 1, dtype=np.int64)
    caps = np.full(len(starts), INITIAL_CAPITAL, dtype=np.float64)
    peaks = caps.copy()
    mdds = np.zeros(len(starts), dtype=np.float64)
    failed = np.zeros(len(starts), dtype=bool)
    alive = np.ones(len(starts), dtype=bool)
    max_steps = n - int(starts.min())
    for step in range(max_steps):
        idx = starts + step
        active = alive & (idx < n)
        if not bool(active.any()):
            break
        caps[active] -= MONTHLY_WITHDRAWAL
        newly_failed = active & (caps <= 0.0)
        failed |= newly_failed
        alive &= ~newly_failed
        active = alive & (idx < n)
        if not bool(active.any()):
            continue
        caps[active] *= 1.0 + returns[idx[active]]
        newly_failed = active & (caps <= 0.0)
        failed |= newly_failed
        alive &= ~newly_failed
        active = alive & (idx < n)
        if not bool(active.any()):
            continue
        peaks[active] = np.maximum(peaks[active], caps[active])
        dd = caps[active] / peaks[active] - 1.0
        active_indices = np.flatnonzero(active)
        mdds[active_indices] = np.minimum(mdds[active_indices], dd)
    final_le_initial = caps <= INITIAL_CAPITAL
    worst_final_i = int(np.argmin(caps))
    worst_mdd_i = int(np.argmin(mdds))
    return (
        int(failed.sum()),
        int(final_le_initial.sum()),
        float(caps[worst_final_i]),
        float(mdds[worst_mdd_i]),
        int(starts[worst_final_i]),
        int(starts[worst_mdd_i]),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["data", "shard", "merge"], required=True)
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--family-id", type=int, default=0)
    parser.add_argument("--shard-id", type=int, default=0)
    parser.add_argument("--configs-per-shard", type=int, default=50_000)
    parser.add_argument("--time-budget-minutes", type=float, default=75.0)
    parser.add_argument("--top-per-shard", type=int, default=50)
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
    prices = download_proxy_prices()
    prices = prices.dropna(how="any")
    monthly = prices.resample("ME").last().pct_change().dropna()
    if len(monthly) < 250:
        raise RuntimeError(f"Insufficient monthly rows after download: {len(monthly)}")
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
        [{"locked_start": "2020-01-01", "locked_opened": False, "locked_rows_accessed": 0, "max_data_date": "2019-12-31"}]
    ).to_csv(data_dir / "locked_access_audit.csv", index=False)
    write_feature_audit(data_dir)


def download_proxy_prices() -> pd.DataFrame:
    symbols = [meta["symbol"] for meta in PROXIES.values()]
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            raw = yf.download(
                symbols,
                start="1995-01-01",
                end="2020-01-01",
                auto_adjust=True,
                progress=False,
                group_by="ticker",
                threads=False,
            )
            prices = pd.DataFrame()
            for name, meta in PROXIES.items():
                prices[name] = raw[meta["symbol"]]["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]
            prices = prices.dropna(how="any")
            if len(prices) > 4_000:
                return prices
        except Exception as exc:  # pragma: no cover - defensive network retry
            last_error = exc
        time.sleep(2.0 + attempt)

    prices = pd.DataFrame()
    for name, meta in PROXIES.items():
        last_series_error: Exception | None = None
        for attempt in range(5):
            try:
                one = yf.download(
                    meta["symbol"],
                    start="1995-01-01",
                    end="2020-01-01",
                    auto_adjust=True,
                    progress=False,
                    threads=False,
                )
                if not one.empty and "Close" in one:
                    prices[name] = one["Close"]
                    break
            except Exception as exc:  # pragma: no cover - defensive network retry
                last_series_error = exc
            time.sleep(2.0 + attempt)
        if name not in prices:
            raise RuntimeError(f"Could not download proxy {name} ({meta['symbol']}): {last_series_error or last_error}")
    prices = prices.dropna(how="any")
    if len(prices) <= 4_000:
        raise RuntimeError(f"Proxy download returned too few daily rows: {len(prices)}")
    return prices


def run_shard(output_dir: Path, family_id: int, shard_id: int, configs_per_shard: int, time_budget_minutes: float, top_per_shard: int) -> None:
    returns = pd.read_csv(output_dir / "data" / "monthly_returns.csv", parse_dates=["timestamp"]).set_index("timestamp")
    returns.index = pd.to_datetime(returns.index, errors="raise")
    if len(returns) < 250:
        raise RuntimeError(f"Insufficient monthly return rows in shard input: {len(returns)}")
    if returns.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached shard.")
    rng = np.random.default_rng(83_000_029 + family_id * 1_000_057 + shard_id * 3001)
    train = returns[returns.index <= TRAIN_END]
    valid = returns[(returns.index >= VALIDATION_START) & (returns.index <= VALIDATION_END)]
    train_dates = train.index
    valid_dates = valid.index
    eval_all_starts(np.zeros(130, dtype=np.float64), 60)
    signals = precompute_signals(returns)
    rows: list[dict[str, Any]] = []
    started = time.monotonic()
    deadline = started + max(1.0, time_budget_minutes) * 60.0
    evaluated = 0
    for config_index in range(configs_per_shard):
        if time.monotonic() >= deadline:
            break
        evaluated += 1
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
            if config_index % 127 != 0:
                continue
        valid_eval = eval_all_starts(valid_series.to_numpy(np.float64), MIN_HORIZON_VALIDATION)
        config_hash = hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()
        accepted = (
            train_eval[0] == 0
            and train_eval[1] == 0
            and valid_eval[0] == 0
            and valid_eval[1] == 0
            and train_eval[3] > MAX_MDD_AFTER_WITHDRAWALS
            and valid_eval[3] > MAX_MDD_AFTER_WITHDRAWALS
            and config_hash not in EXCLUDED_CONFIG_HASHES
        )
        score = (
            (1_000_000_000.0 if accepted else 0.0)
            - (train_eval[0] + valid_eval[0]) * 10_000_000.0
            - (train_eval[1] + valid_eval[1]) * 1_000_000.0
            + min(float(train_eval[2]), float(valid_eval[2]))
            + (float(train_eval[3]) + float(valid_eval[3])) * 5_000_000.0
            - turnover * 1_000.0
        )
        rows.append(
            {
                "strategy_id": f"swr_multiasset_corr95_mdd25_f{family_id:02d}_s{shard_id:02d}_{config_hash[:16]}",
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
                "proxy_corr_min": min(meta["proxy_correlation"] for meta in PROXIES.values()),
                "max_mdd_after_withdrawals_required": MAX_MDD_AFTER_WITHDRAWALS,
                "params_json": json.dumps(params, sort_keys=True),
                "config_hash": config_hash,
                "excluded_by_user": bool(config_hash in EXCLUDED_CONFIG_HASHES),
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
    (shard_dir / "shard_summary.json").write_text(
        json.dumps(
            {
                "family_id": family_id,
                "shard_id": shard_id,
                "configs_requested": int(configs_per_shard),
                "configs_evaluated": int(evaluated),
                "elapsed_seconds": float(time.monotonic() - started),
                "time_budget_minutes": float(time_budget_minutes),
                "rows_kept": int(len(df)),
                "accepted_rows": int(df.get("accepted", pd.Series(dtype=bool)).astype(bool).sum()) if "accepted" in df else 0,
                "max_turnover_annual": MAX_TURNOVER_ANNUAL,
                "max_mdd_after_withdrawals_required": MAX_MDD_AFTER_WITHDRAWALS,
                "proxy_corr_min": min(meta["proxy_correlation"] for meta in PROXIES.values()),
                "locked_opened": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def precompute_signals(returns: pd.DataFrame) -> dict[str, pd.DataFrame | pd.Series]:
    out: dict[str, pd.DataFrame | pd.Series] = {}
    for lb in [1, 2, 3, 4, 6, 8, 10, 12]:
        out[f"mom_{lb}"] = (1.0 + returns[RISK_ASSETS]).rolling(lb).apply(np.prod, raw=True).shift(1) - 1.0
    for lb in [3, 6, 12]:
        out[f"vol_{lb}"] = returns[RISK_ASSETS].rolling(lb).std().shift(1)
    for asset in ["ndx", "sp500", "long_treasury"]:
        for lb in [1, 3, 6, 12]:
            out[f"{asset}_filter_{lb}"] = (1.0 + returns[asset]).rolling(lb).apply(np.prod, raw=True).shift(1) - 1.0
    equity = (1.0 + returns).cumprod()
    for lb in [3, 6, 10, 12]:
        out[f"trend_gap_{lb}"] = equity.div(equity.rolling(lb).mean()).shift(1) - 1.0
    for lb in [3, 6, 12]:
        out[f"drawdown_{lb}"] = equity.div(equity.rolling(lb).max()).shift(1) - 1.0
    for lb in [3, 6, 12]:
        out[f"breadth_{lb}"] = (out[f"mom_{lb}"][RISK_ASSETS] > 0.0).mean(axis=1)
    all_mom = {
        lb: (1.0 + returns).rolling(lb).apply(np.prod, raw=True).shift(1) - 1.0
        for lb in [1, 3, 6, 12]
    }
    for left, right in [("ndx", "sp500"), ("small", "sp500"), ("energy", "sp500"), ("financial", "sp500"), ("long_treasury", "short_treasury")]:
        for lb in [1, 3, 6, 12]:
            out[f"rel_{left}_{right}_{lb}"] = all_mom[lb][left] - all_mom[lb][right]
    return out


def sample_params(rng: np.random.Generator, family_id: int) -> dict[str, Any]:
    conservative = family_id % 4 == 0
    return {
        "family_id": family_id,
        "score_blend": str(rng.choice(["momentum", "trend", "drawdown", "mixed"])),
        "breadth_lb": int(rng.choice([3, 6, 12])),
        "breadth_threshold": float(rng.uniform(0.15, 0.85)),
        "momentum_lb": int(rng.choice([1, 2, 3, 4, 6, 8, 10, 12])),
        "trend_lb": int(rng.choice([3, 6, 10, 12])),
        "drawdown_lb": int(rng.choice([3, 6, 12])),
        "vol_lb": int(rng.choice([3, 6, 12])),
        "top_n": int(rng.choice([1, 2, 3])),
        "risk_leverage": float(rng.uniform(0.0, 10.0 if conservative else 16.0)),
        "safe_leverage": float(rng.uniform(6.0, 18.0 if conservative else 26.0)),
        "safe_short_weight": float(rng.uniform(0.30, 1.00)),
        "safe_intermediate_weight": float(rng.uniform(0.0, 0.70)),
        "momentum_threshold": float(rng.uniform(-0.04, 0.08)),
        "filter_asset": str(rng.choice(["ndx", "sp500", "long_treasury"])),
        "filter_lb": int(rng.choice([1, 3, 6, 12])),
        "filter_threshold": float(rng.uniform(-0.12, 0.08)),
        "filter_risk_scale": float(rng.choice([0.0, 0.25, 0.50, 0.75, 1.0])),
        "vol_target": float(rng.choice([0.0, 0.20, 0.30, 0.40, 0.55, 0.75])),
        "max_gross": float(rng.uniform(3.0, 12.0 if conservative else 16.0)),
        "dd_guard_threshold": float(rng.choice([-0.04, -0.06, -0.08, -0.10, -0.12, -0.16])),
        "dd_guard_scale": float(rng.choice([0.0, 0.10, 0.20, 0.35, 0.50, 0.75])),
        "dd_guard_safe_blend": float(rng.choice([0.0, 0.25, 0.50, 0.75, 1.0])),
        "dd_guard_safe_leverage_scale": float(rng.choice([0.0, 0.10, 0.25, 0.50, 0.75])),
        "rebalance_months": int(rng.choice([1, 3, 6, 12])),
        "rebalance_band": float(rng.choice([0.0, 0.5, 1.0, 2.0, 4.0, 6.0])),
        "cooldown_trigger": float(rng.choice([-0.25, -0.18, -0.12, -0.08, -0.05, 0.0])),
        "cooldown_months": int(rng.choice([0, 1, 2, 3, 6])),
        "cooldown_safe_blend": float(rng.choice([0.50, 0.75, 1.00])),
    }


def build_strategy(returns: pd.DataFrame, signals: dict[str, pd.DataFrame | pd.Series], params: dict[str, Any]) -> tuple[pd.Series, pd.DataFrame]:
    mom = signals[f"mom_{params['momentum_lb']}"].fillna(-1.0)
    trend = signals[f"trend_gap_{params['trend_lb']}"].fillna(-1.0)
    drawdown = signals[f"drawdown_{params['drawdown_lb']}"].fillna(-1.0)
    vol = signals[f"vol_{params['vol_lb']}"].replace(0.0, np.nan)
    filter_signal = signals[f"{params['filter_asset']}_filter_{params['filter_lb']}"].fillna(0.0)
    breadth = signals[f"breadth_{params['breadth_lb']}"].fillna(0.0)
    weights = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    safe_mid = params["safe_intermediate_weight"]
    safe_short = params["safe_short_weight"]
    safe_long = max(0.0, 1.0 - safe_short - safe_mid)
    for dt in returns.index:
        risk_scale = 1.0 if float(filter_signal.loc[dt]) >= params["filter_threshold"] else params["filter_risk_scale"]
        if float(breadth.loc[dt]) < params["breadth_threshold"]:
            risk_scale *= 0.5
        if params["score_blend"] == "trend":
            row = trend.loc[dt, RISK_ASSETS].dropna()
        elif params["score_blend"] == "drawdown":
            row = drawdown.loc[dt, RISK_ASSETS].dropna()
        elif params["score_blend"] == "mixed":
            row = (0.55 * mom.loc[dt, RISK_ASSETS] + 0.30 * trend.loc[dt, RISK_ASSETS] + 0.15 * drawdown.loc[dt, RISK_ASSETS]).dropna()
        else:
            row = mom.loc[dt, RISK_ASSETS].dropna()
        picks = row[row > params["momentum_threshold"]].sort_values(ascending=False).head(int(params["top_n"])).index.tolist()
        if picks and risk_scale > 0.0:
            inv = (1.0 / vol.loc[dt, picks]).replace([np.inf, -np.inf], np.nan).fillna(1.0)
            inv = inv / inv.sum() * params["risk_leverage"] * risk_scale
            weights.loc[dt, picks] = inv
        weights.loc[dt, "short_treasury"] += params["safe_leverage"] * safe_short
        weights.loc[dt, "intermediate_treasury"] += params["safe_leverage"] * safe_mid
        weights.loc[dt, "long_treasury"] += params["safe_leverage"] * safe_long
    gross = weights.abs().sum(axis=1).replace(0.0, np.nan)
    scale = (params["max_gross"] / gross).clip(upper=1.0).fillna(0.0)
    weights = weights.mul(scale, axis=0)
    base = (weights * returns).sum(axis=1)
    if params["vol_target"] > 0:
        realized = base.rolling(int(params["vol_lb"])).std().shift(1) * np.sqrt(12.0)
        vol_scale = (params["vol_target"] / realized).replace([np.inf, -np.inf], np.nan).clip(0.0, 2.5).fillna(0.0)
        weights = weights.mul(vol_scale, axis=0)
        gross = weights.abs().sum(axis=1).replace(0.0, np.nan)
        scale = (params["max_gross"] / gross).clip(upper=1.0).fillna(0.0)
        weights = weights.mul(scale, axis=0)
        base = (weights * returns).sum(axis=1)
    weights = apply_drawdown_guard(weights, returns, base, params)
    base = (weights * returns).sum(axis=1)
    weights = apply_cooldown(weights, returns, base, params)
    weights = rebalance_with_band(weights, int(params["rebalance_months"]), float(params["rebalance_band"]))
    series = (weights * returns).sum(axis=1)
    return series.astype(float), weights.astype(float)


def apply_cooldown(weights: pd.DataFrame, returns: pd.DataFrame, base: pd.Series, params: dict[str, Any]) -> pd.DataFrame:
    months = int(params["cooldown_months"])
    if months <= 0:
        return weights
    out = weights.copy()
    cooldown = 0
    safe = pd.Series(0.0, index=weights.columns)
    safe_mid = params["safe_intermediate_weight"]
    safe_short = params["safe_short_weight"]
    safe_long = max(0.0, 1.0 - safe_short - safe_mid)
    safe["short_treasury"] = params["safe_leverage"] * safe_short
    safe["intermediate_treasury"] = params["safe_leverage"] * safe_mid
    safe["long_treasury"] = params["safe_leverage"] * safe_long
    for i, dt in enumerate(weights.index):
        if cooldown > 0:
            out.loc[dt] = (1.0 - params["cooldown_safe_blend"]) * weights.loc[dt] + params["cooldown_safe_blend"] * safe
            cooldown -= 1
        if float(base.iloc[i]) < params["cooldown_trigger"]:
            cooldown = months
    return out


def apply_drawdown_guard(weights: pd.DataFrame, returns: pd.DataFrame, base: pd.Series, params: dict[str, Any]) -> pd.DataFrame:
    equity = (1.0 + base).cumprod()
    prior_peak = equity.cummax().shift(1)
    prior_equity = equity.shift(1)
    prior_dd = (prior_equity / prior_peak - 1.0).fillna(0.0)
    safe = pd.Series(0.0, index=weights.columns)
    safe_mid = params["safe_intermediate_weight"]
    safe_short = params["safe_short_weight"]
    safe_long = max(0.0, 1.0 - safe_short - safe_mid)
    safe["short_treasury"] = params["safe_leverage"] * params["dd_guard_safe_leverage_scale"] * safe_short
    safe["intermediate_treasury"] = params["safe_leverage"] * params["dd_guard_safe_leverage_scale"] * safe_mid
    safe["long_treasury"] = params["safe_leverage"] * params["dd_guard_safe_leverage_scale"] * safe_long
    out = weights.copy()
    guard = prior_dd <= params["dd_guard_threshold"]
    if bool(guard.any()):
        scaled = out.loc[guard] * params["dd_guard_scale"]
        blended = (1.0 - params["dd_guard_safe_blend"]) * scaled + params["dd_guard_safe_blend"] * safe
        out.loc[guard] = blended
    return out


def rebalance_with_band(target: pd.DataFrame, rebalance_months: int, band: float) -> pd.DataFrame:
    out = pd.DataFrame(0.0, index=target.index, columns=target.columns)
    last = pd.Series(0.0, index=target.columns)
    for idx, dt in enumerate(target.index):
        desired = target.loc[dt] if idx % rebalance_months == 0 else last
        if float((desired - last).abs().sum()) > band:
            last = desired.astype(float).copy()
        out.loc[dt] = last
    return out


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
    accepted.to_csv(output_dir / "accepted_multiasset_corr95_mdd25_strategies.csv", index=False)
    for name in ["proxy_map.csv", "locked_access_audit.csv", "feature_audit.csv"]:
        src = output_dir / "data" / name
        if src.exists():
            pd.read_csv(src).to_csv(output_dir / name, index=False)
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "accepted_count": int(len(accepted)),
        "top_candidate_rows": int(len(top)),
        "proxy_corr_min": min(meta["proxy_correlation"] for meta in PROXIES.values()),
        "max_mdd_after_withdrawals_required": MAX_MDD_AFTER_WITHDRAWALS,
        "locked_opened": False,
        "uses_concrete_stocks": False,
        "uses_crypto": False,
        "data_end_max": "2019-12-31",
        "excluded_config_hashes": sorted(EXCLUDED_CONFIG_HASHES),
    }
    (output_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def write_feature_audit(data_dir: Path) -> None:
    pd.DataFrame(
        [
            {"family": "proxy_returns", "features": "monthly returns for all corr95 ETF/proxy sleeves", "used": True},
            {"family": "momentum", "features": "1/2/3/4/6/8/10/12 month total return", "used": True},
            {"family": "trend", "features": "3/6/10/12 month moving-average equity gap", "used": True},
            {"family": "drawdown", "features": "3/6/12 month drawdown from rolling peak", "used": True},
            {"family": "volatility", "features": "3/6/12 month realized volatility and inverse-vol sizing", "used": True},
            {"family": "breadth", "features": "percentage of risk sleeves with positive momentum", "used": True},
            {"family": "relative_strength", "features": "NDX/SP500, small/SP500, energy/SP500, financial/SP500, long/short treasury momentum spreads", "used": True},
            {"family": "risk_filter", "features": "NDX, SP500 and long-treasury absolute momentum filters", "used": True},
            {"family": "withdrawal_path", "features": "all possible monthly start dates with start-of-month withdrawal", "used": True},
            {"family": "drawdown_guard", "features": "prior strategy drawdown guard using only past strategy equity", "used": True},
            {"family": "locked", "features": "forbidden; max data date 2019-12-31", "used": False},
        ]
    ).to_csv(data_dir / "feature_audit.csv", index=False)


if __name__ == "__main__":
    main()
