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


CAMPAIGN_ID = "swr_path_cppi_expanded_universe_mdd15_trainonly_corr95_360jobs"
INITIAL_CAPITAL = 100_000.0
MONTHLY_WITHDRAWAL = 2_000.0
TRAIN_END = pd.Timestamp("2010-12-31")
TRAIN_CV_SPLIT = pd.Timestamp("2003-12-31")
TRAIN_STRESS_WINDOWS = (
    (pd.Timestamp("1995-01-01"), pd.Timestamp("1998-12-31")),
    (pd.Timestamp("1999-01-01"), pd.Timestamp("2004-12-31")),
    (pd.Timestamp("2005-01-01"), pd.Timestamp("2010-12-31")),
)
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2019-12-31")
LOCKED_START = pd.Timestamp("2020-01-01")
MIN_HORIZON_TRAIN = 120
MIN_HORIZON_VALIDATION = 60
MIN_HORIZON_TRAIN_STRESS = 36
MAX_MDD_AFTER_WITHDRAWALS = -0.15
MIN_PROXY_CORRELATION = 0.95

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


@njit
def eval_path_cppi_all_starts(
    risk_ret: np.ndarray,
    safe_ret: np.ndarray,
    signal: np.ndarray,
    min_horizon: int,
    base_exposure: float,
    multiplier: float,
    floor_pct: float,
    max_risk_exposure: float,
    safe_exposure: float,
    max_gross: float,
    allow_short: int,
    guard_threshold: float,
    guard_scale: float,
    recovery_boost: float,
) -> tuple[int, int, float, float, int, int]:
    failed = 0
    final_le_initial = 0
    min_final = 1.0e18
    worst_mdd = 0.0
    worst_final_i = -1
    worst_mdd_i = -1
    n = len(risk_ret)
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
            floor_value = floor_pct * peak
            cushion = (cap - floor_value) / cap
            if cushion < 0.0:
                cushion = 0.0
            risk_exp = base_exposure + multiplier * cushion
            if risk_exp > max_risk_exposure:
                risk_exp = max_risk_exposure
            if risk_exp < 0.0:
                risk_exp = 0.0
            current_dd = cap / peak - 1.0
            if current_dd <= guard_threshold:
                risk_exp *= guard_scale
                if recovery_boost > 0.0 and signal[i] > 0.0:
                    risk_exp += recovery_boost * max(0.0, current_dd - guard_threshold)
            sign = 1.0
            if signal[i] < 0.0:
                if allow_short == 1:
                    sign = -1.0
                else:
                    risk_exp = 0.0
            gross = abs(risk_exp) + abs(safe_exposure)
            scale = 1.0
            if gross > max_gross and gross > 0.0:
                scale = max_gross / gross
            port_ret = scale * (sign * risk_exp * risk_ret[i] + safe_exposure * safe_ret[i])
            if port_ret < -0.98:
                path_failed = True
                break
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
    parser.add_argument("--configs-per-shard", type=int, default=40_000)
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
    train = returns[returns.index <= TRAIN_END]
    train_early = returns[returns.index <= TRAIN_CV_SPLIT]
    train_late = returns[(returns.index > TRAIN_CV_SPLIT) & (returns.index <= TRAIN_END)]
    train_stress_frames = [
        returns[(returns.index >= start) & (returns.index <= end)]
        for start, end in TRAIN_STRESS_WINDOWS
    ]
    valid = returns[(returns.index >= VALIDATION_START) & (returns.index <= VALIDATION_END)]
    train_dates = train.index
    valid_dates = valid.index
    eval_path_cppi_all_starts(
        np.zeros(130, dtype=np.float64),
        np.zeros(130, dtype=np.float64),
        np.ones(130, dtype=np.float64),
        60,
        0.5,
        2.0,
        0.85,
        3.0,
        1.0,
        4.0,
        0,
        -0.10,
        0.25,
        0.0,
    )
    rng = np.random.default_rng(73_000_019 + family_id * 1_000_003 + shard_id * 1009)
    signals = precompute_signals(returns)
    rows: list[dict[str, Any]] = []
    started = time.monotonic()
    deadline = started + max(1.0, time_budget_minutes) * 60.0
    evaluated = 0
    validation_evaluated = 0
    for config_index in range(configs_per_shard):
        if time.monotonic() >= deadline:
            break
        evaluated += 1
        params = sample_params(rng, family_id)
        risk_ret, safe_ret, signal = build_streams(returns, signals, params)
        train_eval = eval_path_cppi_all_starts(
            risk_ret.loc[train.index].to_numpy(np.float64),
            safe_ret.loc[train.index].to_numpy(np.float64),
            signal.loc[train.index].to_numpy(np.float64),
            MIN_HORIZON_TRAIN,
            float(params["base_exposure"]),
            float(params["multiplier"]),
            float(params["floor_pct"]),
            float(params["max_risk_exposure"]),
            float(params["safe_exposure"]),
            float(params["max_gross"]),
            int(params["allow_short"]),
            float(params["guard_threshold"]),
            float(params["guard_scale"]),
            float(params["recovery_boost"]),
        )
        train_early_eval = eval_path_cppi_all_starts(
            risk_ret.loc[train_early.index].to_numpy(np.float64),
            safe_ret.loc[train_early.index].to_numpy(np.float64),
            signal.loc[train_early.index].to_numpy(np.float64),
            60,
            float(params["base_exposure"]),
            float(params["multiplier"]),
            float(params["floor_pct"]),
            float(params["max_risk_exposure"]),
            float(params["safe_exposure"]),
            float(params["max_gross"]),
            int(params["allow_short"]),
            float(params["guard_threshold"]),
            float(params["guard_scale"]),
            float(params["recovery_boost"]),
        )
        train_late_eval = eval_path_cppi_all_starts(
            risk_ret.loc[train_late.index].to_numpy(np.float64),
            safe_ret.loc[train_late.index].to_numpy(np.float64),
            signal.loc[train_late.index].to_numpy(np.float64),
            60,
            float(params["base_exposure"]),
            float(params["multiplier"]),
            float(params["floor_pct"]),
            float(params["max_risk_exposure"]),
            float(params["safe_exposure"]),
            float(params["max_gross"]),
            int(params["allow_short"]),
            float(params["guard_threshold"]),
            float(params["guard_scale"]),
            float(params["recovery_boost"]),
        )
        train_stress_evals = [
            eval_path_cppi_all_starts(
                risk_ret.loc[frame.index].to_numpy(np.float64),
                safe_ret.loc[frame.index].to_numpy(np.float64),
                signal.loc[frame.index].to_numpy(np.float64),
                MIN_HORIZON_TRAIN_STRESS,
                float(params["base_exposure"]),
                float(params["multiplier"]),
                float(params["floor_pct"]),
                float(params["max_risk_exposure"]),
                float(params["safe_exposure"]),
                float(params["max_gross"]),
                int(params["allow_short"]),
                float(params["guard_threshold"]),
                float(params["guard_scale"]),
                float(params["recovery_boost"]),
            )
            for frame in train_stress_frames
        ]
        stress_failed = int(sum(item[0] for item in train_stress_evals))
        stress_le_initial = int(sum(item[1] for item in train_stress_evals))
        stress_worst_final = float(min(item[2] for item in train_stress_evals))
        stress_worst_mdd = float(min(item[3] for item in train_stress_evals))
        train_full_pass = train_eval[0] == 0 and train_eval[1] == 0 and train_eval[3] > MAX_MDD_AFTER_WITHDRAWALS
        train_cv_pass = (
            train_early_eval[0] == 0
            and train_early_eval[1] == 0
            and train_early_eval[3] > MAX_MDD_AFTER_WITHDRAWALS
            and train_late_eval[0] == 0
            and train_late_eval[1] == 0
            and train_late_eval[3] > MAX_MDD_AFTER_WITHDRAWALS
        )
        train_pass = train_full_pass
        train_score = train_only_score(train_eval, train_early_eval, train_late_eval, train_stress_evals, train_pass, params)
        if not train_pass and train_score < -600_000_000.0 and config_index % 307 != 0:
            continue
        valid_eval = eval_path_cppi_all_starts(
            risk_ret.loc[valid.index].to_numpy(np.float64),
            safe_ret.loc[valid.index].to_numpy(np.float64),
            signal.loc[valid.index].to_numpy(np.float64),
            MIN_HORIZON_VALIDATION,
            float(params["base_exposure"]),
            float(params["multiplier"]),
            float(params["floor_pct"]),
            float(params["max_risk_exposure"]),
            float(params["safe_exposure"]),
            float(params["max_gross"]),
            int(params["allow_short"]),
            float(params["guard_threshold"]),
            float(params["guard_scale"]),
            float(params["recovery_boost"]),
        )
        validation_evaluated += 1
        validation_pass = valid_eval[0] == 0 and valid_eval[1] == 0 and valid_eval[3] > MAX_MDD_AFTER_WITHDRAWALS
        config_hash = hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()
        rows.append(
            {
                "strategy_id": f"swr_path_cppi_expanded_universe_mdd15_corr95_f{family_id:02d}_s{shard_id:02d}_{config_hash[:16]}",
                "family_id": family_id,
                "shard_id": shard_id,
                "config_index": config_index,
                "train_pass": bool(train_pass),
                "train_full_pass": bool(train_full_pass),
                "train_cv_pass": bool(train_cv_pass),
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
                "stress_final_le_initial_count_train": int(stress_le_initial),
                "stress_worst_final_capital_train": float(stress_worst_final),
                "stress_worst_mdd_after_withdrawals_train": float(stress_worst_mdd),
                "mdd_after_withdrawals_validation": float(valid_eval[3]),
                "worst_final_start_train": str(train_dates[int(train_eval[4])].date()) if train_eval[4] >= 0 else "",
                "worst_final_start_validation": str(valid_dates[int(valid_eval[4])].date()) if valid_eval[4] >= 0 else "",
                "worst_mdd_start_train": str(train_dates[int(train_eval[5])].date()) if train_eval[5] >= 0 else "",
                "worst_mdd_start_validation": str(valid_dates[int(valid_eval[5])].date()) if valid_eval[5] >= 0 else "",
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


def precompute_signals(returns: pd.DataFrame) -> dict[str, pd.DataFrame | pd.Series]:
    out: dict[str, pd.DataFrame | pd.Series] = {}
    assets = list(PROXIES)
    for lb in [1, 3, 6, 10, 12]:
        out[f"mom_{lb}"] = (1.0 + returns[assets]).rolling(lb).apply(np.prod, raw=True).shift(1) - 1.0
    for lb in [3, 6, 12]:
        out[f"vol_{lb}"] = returns[assets].rolling(lb).std().shift(1)
    return out


def sample_params(rng: np.random.Generator, family_id: int) -> dict[str, Any]:
    low_risk = family_id in {0, 1, 2, 3, 4, 5, 10, 11, 12, 13, 14, 15}
    tight_floor = family_id % 3 != 0
    asset_modes = [
        "asset_ndx",
        "asset_sp500",
        "asset_small",
        "asset_value",
        "asset_growth",
        "asset_emerging",
        "asset_energy",
        "asset_financial",
        "asset_healthcare",
        "asset_long_treasury",
        "asset_inverse_sp500",
    ]
    base_modes = ["risk_vs_treasury", "inverse_blend", "risk_blend", "multi_tsmom", "sector_vs_treasury", "sector_blend", "style_blend"]
    risk_modes = asset_modes + base_modes
    risk_probs = np.array([0.07, 0.07, 0.06, 0.06, 0.07, 0.07, 0.06, 0.05, 0.06, 0.04, 0.06, 0.09, 0.09, 0.09, 0.08, 0.04, 0.04, 0.04], dtype=float)
    risk_probs = risk_probs / risk_probs.sum()
    return {
        "family_id": family_id,
        "risk_mode": str(rng.choice(risk_modes, p=risk_probs)),
        "safe_mode": str(rng.choice(["shy", "safe_blend", "tlt", "ief", "tlt_tsmom"], p=[0.42, 0.24, 0.18, 0.10, 0.06])),
        "lookback": int(rng.choice([1, 3, 6], p=[0.55, 0.30, 0.15])),
        "vol_lookback": int(rng.choice([3, 6, 12])),
        "top_n": int(rng.choice([1, 2, 3, 4])),
        "bottom_n": int(rng.choice([0, 1, 2, 3])),
        "score_power": float(rng.choice([0.5, 1.0, 1.5, 2.0])),
        "base_exposure": float(rng.uniform(0.0, 2.2 if low_risk else 3.8)),
        "multiplier": float(rng.uniform(4.0, 24.0 if low_risk else 34.0)),
        "floor_pct": float(rng.uniform(0.82 if tight_floor else 0.76, 0.94 if tight_floor else 0.88)),
        "max_risk_exposure": float(rng.uniform(0.5, 4.5 if low_risk else 8.0)),
        "safe_exposure": float(rng.uniform(6.0, 19.0)),
        "max_gross": float(rng.uniform(7.0, 20.0)),
        "allow_short": int(rng.choice([0, 1], p=[0.70, 0.30])),
        "signal_threshold": float(rng.uniform(-0.05, 0.04)),
        "guard_threshold": float(rng.choice([-0.14, -0.12, -0.10, -0.08, -0.06, -0.04])),
        "guard_scale": float(rng.choice([0.0, 0.05, 0.10, 0.20, 0.35, 0.50])),
        "recovery_boost": float(rng.choice([0.0, 0.5, 1.0, 2.0])),
        "risk_blend_ndx": float(rng.uniform(-0.5, 1.5)),
        "risk_blend_sp500": float(rng.uniform(-0.5, 1.5)),
        "risk_blend_tlt": float(rng.uniform(0.0, 2.5)),
        "risk_blend_energy": float(rng.uniform(-0.25, 1.25)),
        "risk_blend_financial": float(rng.uniform(-0.25, 1.25)),
        "risk_blend_healthcare": float(rng.uniform(-0.25, 1.25)),
        "risk_blend_value": float(rng.uniform(-0.5, 1.5)),
        "risk_blend_growth": float(rng.uniform(-0.5, 1.5)),
        "risk_blend_emerging": float(rng.uniform(-0.5, 1.5)),
        "risk_blend_small": float(rng.uniform(-0.5, 1.5)),
        "risk_blend_inverse": float(rng.uniform(0.0, 2.5)),
        "safe_blend_shy": float(rng.uniform(0.0, 2.0)),
        "safe_blend_ief": float(rng.uniform(0.0, 2.0)),
        "safe_blend_tlt": float(rng.uniform(0.0, 2.5)),
    }


def build_streams(returns: pd.DataFrame, signals: dict[str, Any], params: dict[str, Any]) -> tuple[pd.Series, pd.Series, pd.Series]:
    lb = int(params["lookback"])
    mom = signals[f"mom_{lb}"].fillna(0.0)
    risk_mode = str(params["risk_mode"])
    if risk_mode.startswith("asset_"):
        asset = risk_mode.removeprefix("asset_")
        if asset not in returns.columns:
            raise ValueError(f"Unknown risk asset mode: {risk_mode}")
        risk_ret = returns[asset]
        sig = mom[asset] - float(params["signal_threshold"])
    elif params["risk_mode"] == "ndx":
        risk_ret = returns["ndx"]
        sig = mom["ndx"] - float(params["signal_threshold"])
    elif params["risk_mode"] == "sp500":
        risk_ret = returns["sp500"]
        sig = mom["sp500"] - float(params["signal_threshold"])
    elif params["risk_mode"] == "inverse_sp500":
        risk_ret = returns["inverse_sp500"]
        sig = mom["inverse_sp500"] - float(params["signal_threshold"])
    elif params["risk_mode"] == "energy":
        risk_ret = returns["energy"]
        sig = mom["energy"] - float(params["signal_threshold"])
    elif params["risk_mode"] == "financial":
        risk_ret = returns["financial"]
        sig = mom["financial"] - float(params["signal_threshold"])
    elif params["risk_mode"] == "multi_tsmom":
        risk_ret = build_multi_tsmom_returns(returns, signals, params)
        sig = pd.Series(1.0, index=returns.index)
    elif params["risk_mode"] == "risk_vs_treasury":
        risk_ret = 0.6 * returns["ndx"] + 0.4 * returns["long_treasury"]
        sig = (mom["ndx"] - mom["long_treasury"]) - float(params["signal_threshold"])
    elif params["risk_mode"] == "sector_vs_treasury":
        risk_ret = 0.5 * returns["energy"] + 0.5 * returns["financial"]
        sig = ((mom["energy"] + mom["financial"]) / 2.0 - mom["long_treasury"]) - float(params["signal_threshold"])
    elif params["risk_mode"] == "sector_blend":
        raw = (
            float(params["risk_blend_energy"]) * returns["energy"]
            + float(params["risk_blend_financial"]) * returns["financial"]
            + float(params["risk_blend_healthcare"]) * returns["healthcare"]
            + float(params["risk_blend_tlt"]) * returns["long_treasury"]
        )
        norm = (
            abs(float(params["risk_blend_energy"]))
            + abs(float(params["risk_blend_financial"]))
            + abs(float(params["risk_blend_healthcare"]))
            + abs(float(params["risk_blend_tlt"]))
        )
        risk_ret = raw / norm if norm > 0 else returns["energy"] * 0.0
        sig = (mom["energy"] + mom["financial"] + mom["healthcare"] + mom["long_treasury"]) / 4.0 - float(params["signal_threshold"])
    elif params["risk_mode"] == "style_blend":
        raw = (
            float(params["risk_blend_value"]) * returns["value"]
            + float(params["risk_blend_growth"]) * returns["growth"]
            + float(params["risk_blend_small"]) * returns["small"]
            + float(params["risk_blend_emerging"]) * returns["emerging"]
            + float(params["risk_blend_tlt"]) * returns["long_treasury"]
            + float(params["risk_blend_inverse"]) * returns["inverse_sp500"]
        )
        norm = (
            abs(float(params["risk_blend_value"]))
            + abs(float(params["risk_blend_growth"]))
            + abs(float(params["risk_blend_small"]))
            + abs(float(params["risk_blend_emerging"]))
            + abs(float(params["risk_blend_tlt"]))
            + abs(float(params["risk_blend_inverse"]))
        )
        risk_ret = raw / norm if norm > 0 else returns["growth"] * 0.0
        sig = (
            mom["value"]
            + mom["growth"]
            + mom["small"]
            + mom["emerging"]
            + mom["long_treasury"]
            + mom["inverse_sp500"]
        ) / 6.0 - float(params["signal_threshold"])
    elif params["risk_mode"] == "inverse_blend":
        raw = (
            float(params["risk_blend_ndx"]) * returns["ndx"]
            + float(params["risk_blend_inverse"]) * returns["inverse_sp500"]
            + float(params["risk_blend_tlt"]) * returns["long_treasury"]
        )
        norm = abs(float(params["risk_blend_ndx"])) + abs(float(params["risk_blend_inverse"])) + abs(float(params["risk_blend_tlt"]))
        risk_ret = raw / norm if norm > 0 else returns["inverse_sp500"] * 0.0
        sig = (mom["ndx"] + mom["inverse_sp500"] + mom["long_treasury"]) / 3.0 - float(params["signal_threshold"])
    else:
        raw = (
            float(params["risk_blend_ndx"]) * returns["ndx"]
            + float(params["risk_blend_sp500"]) * returns["sp500"]
            + float(params["risk_blend_tlt"]) * returns["long_treasury"]
        )
        norm = abs(float(params["risk_blend_ndx"])) + abs(float(params["risk_blend_sp500"])) + abs(float(params["risk_blend_tlt"]))
        risk_ret = raw / norm if norm > 0 else returns["ndx"] * 0.0
        sig = (mom["ndx"] + mom["sp500"] + mom["long_treasury"]) / 3.0 - float(params["signal_threshold"])
    if params["safe_mode"] == "shy":
        safe_ret = returns["short_treasury"]
    elif params["safe_mode"] == "ief":
        safe_ret = returns["intermediate_treasury"]
    elif params["safe_mode"] == "tlt":
        safe_ret = returns["long_treasury"]
    elif params["safe_mode"] == "inverse_sp500":
        safe_ret = returns["inverse_sp500"]
    elif params["safe_mode"] == "tlt_tsmom":
        safe_sign = np.where(mom["long_treasury"] >= float(params["signal_threshold"]), 1.0, -1.0)
        safe_ret = pd.Series(safe_sign, index=returns.index) * returns["long_treasury"]
    elif params["safe_mode"] == "ief_tsmom":
        safe_sign = np.where(mom["intermediate_treasury"] >= float(params["signal_threshold"]), 1.0, -1.0)
        safe_ret = pd.Series(safe_sign, index=returns.index) * returns["intermediate_treasury"]
    elif params["safe_mode"] == "inverse_tsmom":
        safe_sign = np.where(mom["inverse_sp500"] >= float(params["signal_threshold"]), 1.0, -1.0)
        safe_ret = pd.Series(safe_sign, index=returns.index) * returns["inverse_sp500"]
    elif params["safe_mode"] == "safe_tsmom_blend":
        shy_sign = np.where(mom["short_treasury"] >= float(params["signal_threshold"]), 1.0, -1.0)
        ief_sign = np.where(mom["intermediate_treasury"] >= float(params["signal_threshold"]), 1.0, -1.0)
        tlt_sign = np.where(mom["long_treasury"] >= float(params["signal_threshold"]), 1.0, -1.0)
        raw = (
            float(params["safe_blend_shy"]) * pd.Series(shy_sign, index=returns.index) * returns["short_treasury"]
            + float(params["safe_blend_ief"]) * pd.Series(ief_sign, index=returns.index) * returns["intermediate_treasury"]
            + float(params["safe_blend_tlt"]) * pd.Series(tlt_sign, index=returns.index) * returns["long_treasury"]
        )
        norm = abs(float(params["safe_blend_shy"])) + abs(float(params["safe_blend_ief"])) + abs(float(params["safe_blend_tlt"]))
        safe_ret = raw / norm if norm > 0 else returns["short_treasury"] * 0.0
    else:
        raw = (
            float(params["safe_blend_shy"]) * returns["short_treasury"]
            + float(params["safe_blend_ief"]) * returns["intermediate_treasury"]
            + float(params["safe_blend_tlt"]) * returns["long_treasury"]
        )
        norm = abs(float(params["safe_blend_shy"])) + abs(float(params["safe_blend_ief"])) + abs(float(params["safe_blend_tlt"]))
        safe_ret = raw / norm if norm > 0 else returns["short_treasury"] * 0.0
    return risk_ret.astype(float), safe_ret.astype(float), sig.astype(float)


def build_multi_tsmom_returns(returns: pd.DataFrame, signals: dict[str, Any], params: dict[str, Any]) -> pd.Series:
    assets = list(PROXIES)
    mom = signals[f"mom_{int(params['lookback'])}"].reindex(returns.index).fillna(0.0)
    vol = signals[f"vol_{int(params['vol_lookback'])}"].reindex(returns.index).replace(0.0, np.nan)
    threshold = float(params["signal_threshold"])
    top_n = int(params["top_n"])
    bottom_n = int(params["bottom_n"]) if int(params["allow_short"]) == 1 else 0
    score_power = float(params["score_power"])
    values: list[float] = []
    for dt in returns.index:
        score = mom.loc[dt, assets].astype(float)
        risk = vol.loc[dt, assets].astype(float).fillna(score.abs().median() if score.abs().median() > 0 else 1.0)
        adjusted = score / risk.clip(lower=1.0e-6)
        longs = adjusted[adjusted > threshold].sort_values(ascending=False).head(top_n)
        shorts = adjusted[adjusted < -threshold].sort_values(ascending=True).head(bottom_n)
        weights = pd.Series(0.0, index=assets)
        if len(longs):
            lw = longs.abs().pow(score_power)
            weights.loc[lw.index] = lw / lw.sum()
        if len(shorts):
            sw = shorts.abs().pow(score_power)
            weights.loc[sw.index] = weights.loc[sw.index] - sw / sw.sum()
        gross = weights.abs().sum()
        if gross > 0:
            weights = weights / gross
        values.append(float((weights * returns.loc[dt, assets]).sum()))
    return pd.Series(values, index=returns.index)


def train_only_score(
    result: tuple[int, int, float, float, int, int],
    early_result: tuple[int, int, float, float, int, int],
    late_result: tuple[int, int, float, float, int, int],
    stress_results: list[tuple[int, int, float, float, int, int]],
    train_pass: bool,
    params: dict[str, Any],
) -> float:
    failed, le_initial, worst_final, mdd, _, _ = result
    early_failed, early_le_initial, early_final, early_mdd, _, _ = early_result
    late_failed, late_le_initial, late_final, late_mdd, _, _ = late_result
    stress_failed = sum(item[0] for item in stress_results)
    stress_le_initial = sum(item[1] for item in stress_results)
    stress_final = min(item[2] for item in stress_results)
    stress_mdd = min(item[3] for item in stress_results)
    complexity = abs(float(params["base_exposure"])) + abs(float(params["multiplier"])) + abs(float(params["safe_exposure"]))
    return (
        (1_000_000_000.0 if train_pass else 0.0)
        - failed * 25_000_000.0
        - le_initial * 2_500_000.0
        - (early_failed + late_failed) * 15_000_000.0
        - (early_le_initial + late_le_initial) * 1_500_000.0
        - stress_failed * 12_000_000.0
        - stress_le_initial * 1_200_000.0
        + min(worst_final, 10_000_000.0)
        + min(early_final, late_final, 10_000_000.0) * 0.25
        + min(stress_final, 5_000_000.0) * 0.20
        + min(mdd, early_mdd, late_mdd, stress_mdd) * 120_000_000.0
        + (mdd - MAX_MDD_AFTER_WITHDRAWALS) * 180_000_000.0
        - complexity * 35_000.0
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
    verified.to_csv(output_dir / "verified_path_cppi_expanded_universe_mdd15_report_only.csv", index=False)
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
    fail_reasons = build_fail_reasons(top)
    fail_reasons.to_csv(output_dir / "fail_reasons.csv", index=False)
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
