from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

_SAFE_WITHDRAWAL_PATH = Path(__file__).resolve().parents[1] / "validation" / "safe_withdrawal.py"
_SAFE_WITHDRAWAL_SPEC = importlib.util.spec_from_file_location(
    "aurora_safe_withdrawal_standalone",
    _SAFE_WITHDRAWAL_PATH,
)
if _SAFE_WITHDRAWAL_SPEC is None or _SAFE_WITHDRAWAL_SPEC.loader is None:
    raise RuntimeError(f"cannot load safe withdrawal module from {_SAFE_WITHDRAWAL_PATH}")
_SAFE_WITHDRAWAL = importlib.util.module_from_spec(_SAFE_WITHDRAWAL_SPEC)
sys.modules["aurora_safe_withdrawal_standalone"] = _SAFE_WITHDRAWAL
_SAFE_WITHDRAWAL_SPEC.loader.exec_module(_SAFE_WITHDRAWAL)
safe_withdrawal_rate = _SAFE_WITHDRAWAL.safe_withdrawal_rate


OUTPUT_FILES = {
    "all_candidates": "all_candidates_metrics.parquet",
    "pruned_by_job": "pruned_by_job.csv",
    "pruned_by_family": "pruned_by_family.csv",
    "champions": "final_20_champions.csv",
    "accepted": "accepted_strategies.csv",
    "rejected": "rejected_but_ranked.csv",
    "portfolios": "portfolio_combinations.csv",
    "worst_paths": "worst_start_paths.parquet",
    "equity": "monthly_equity_after_withdrawals.parquet",
    "allocations": "monthly_allocations.parquet",
    "proxy_map": "proxy_map.csv",
    "data_audit": "data_audit.csv",
    "locked_audit": "locked_access_audit.csv",
    "sources": "literature_sources.csv",
    "summary": "run_summary.json",
    "report": "SWR_20_ETF_PROXY_2000_REPORT.md",
}

KNOWN_CONCRETE_STOCKS = {
    "AAPL",
    "MSFT",
    "AMZN",
    "GOOGL",
    "GOOG",
    "META",
    "NVDA",
    "TSLA",
    "BRK.B",
    "JPM",
    "JNJ",
    "V",
    "PG",
    "UNH",
    "HD",
    "MA",
    "BAC",
    "XOM",
    "PFE",
    "KO",
    "PEP",
    "WMT",
    "COST",
    "MCD",
    "IBM",
    "ORCL",
    "CSCO",
    "INTC",
    "QCOM",
    "TXN",
    "CAT",
    "BA",
    "DIS",
    "NKE",
}

CRYPTO_MARKERS = ("BTC", "ETH", "USDT", "USDC", "CRYPTO", "BINANCE", "COIN")


@dataclass(frozen=True)
class Candidate:
    strategy_id: str
    family: str
    family_id: int
    shard_id: int
    config_index: int
    config_hash: str
    params: dict[str, Any]
    monthly_returns: pd.Series
    monthly_allocations: pd.DataFrame
    turnover_annual: float
    expense_annual: float
    proxy_quality_score: float


def main() -> None:
    parser = argparse.ArgumentParser(description="SWR ETF/proxy campaign without locked data.")
    parser.add_argument("--config", default="config/swr_20_etf_proxy_2000_no_locked_360jobs.yaml")
    parser.add_argument("--output-dir", default="outputs/swr_20_etf_proxy_2000_no_locked_360jobs")
    parser.add_argument("--mode", choices=["full", "shard", "merge"], default="full")
    parser.add_argument("--family-id", type=int)
    parser.add_argument("--shard-id", type=int)
    parser.add_argument("--smoke", action="store_true", help="Use deterministic synthetic ETF/proxy data.")
    args = parser.parse_args()

    root = Path.cwd()
    config = load_config(root / args.config)
    output_dir = root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    validate_universe(config)
    validate_campaign_shape(config)
    if args.smoke and args.mode in {"full", "shard"}:
        config = with_smoke_runtime_limits(config)

    if args.mode == "merge":
        merge_shards(output_dir, config)
        return

    returns, proxy_map, data_audit = load_monthly_proxy_returns(config, output_dir, smoke=args.smoke)
    validate_no_locked_dates(returns.reset_index(), "timestamp", config["periods"]["locked_start"])

    if args.mode == "shard":
        if args.family_id is None or args.shard_id is None:
            raise SystemExit("--family-id and --shard-id are required in shard mode")
        run_shard(output_dir, config, returns, proxy_map, data_audit, args.family_id, args.shard_id)
        return

    run_full(output_dir, config, returns, proxy_map, data_audit)


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"invalid config: {path}")
    return config


def validate_campaign_shape(config: dict[str, Any]) -> None:
    families = config["families"]
    github = config["github"]
    if len(families) != int(github["families"]):
        raise ValueError("family count does not match github.families")
    if int(github["families"]) * int(github["shards_per_family"]) != int(github["total_jobs"]):
        raise ValueError("github total_jobs must equal families * shards_per_family")
    if int(github["total_jobs"]) != 360:
        raise ValueError("this campaign must be exactly 360 jobs")
    if int(github["max_parallel"]) != 360:
        raise ValueError("this campaign must request 360 max parallel jobs")
    family_ids = sorted(int(item["id"]) for item in families)
    if family_ids != list(range(20)):
        raise ValueError("families must have ids 0..19")


def with_smoke_runtime_limits(config: dict[str, Any]) -> dict[str, Any]:
    smoke = json.loads(json.dumps(config))
    smoke["github"]["shards_per_family"] = 1
    smoke["github"]["configs_per_shard"] = 3
    smoke["github"]["total_jobs"] = 20
    smoke["capital"]["precision"] = 100.0
    return smoke


def validate_universe(config: dict[str, Any]) -> None:
    sleeves = config["sleeves"]
    for sleeve_name, sleeve in sleeves.items():
        for key in ("tradable_etf", "proxy_symbol", "proxy_name", "proxy_source"):
            if not sleeve.get(key):
                raise ValueError(f"{sleeve_name} missing documented proxy field {key}")
        symbols = [str(sleeve["tradable_etf"]).upper(), str(sleeve["proxy_symbol"]).upper()]
        for symbol in symbols:
            if symbol in KNOWN_CONCRETE_STOCKS:
                raise ValueError(f"concrete stock is forbidden: {symbol}")
            if any(marker in symbol for marker in CRYPTO_MARKERS):
                raise ValueError(f"crypto symbol is forbidden: {symbol}")


def validate_no_locked_dates(frame: pd.DataFrame, date_column: str, locked_start: str) -> None:
    if date_column not in frame.columns:
        raise ValueError(f"missing date column: {date_column}")
    dates = pd.to_datetime(frame[date_column], errors="coerce")
    if dates.dropna().ge(pd.Timestamp(locked_start)).any():
        max_date = dates.max().date().isoformat()
        raise ValueError(f"locked data opened: max date {max_date} >= {locked_start}")


def load_monthly_proxy_returns(
    config: dict[str, Any],
    output_dir: Path,
    *,
    smoke: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if smoke:
        return build_synthetic_proxy_returns(config)
    return download_monthly_proxy_returns(config, output_dir)


def build_synthetic_proxy_returns(
    config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range(config["periods"]["train_start"], config["periods"]["validation_end"], freq="ME")
    rows: dict[str, np.ndarray] = {}
    rng = np.random.default_rng(1995)
    for idx, sleeve_name in enumerate(config["sleeves"]):
        if sleeve_name == "cash":
            rows[sleeve_name] = np.zeros(len(dates), dtype=float)
            continue
        drift = 0.002 + idx * 0.00005
        vol = 0.018 + (idx % 5) * 0.004
        cycle = 0.008 * np.sin(np.arange(len(dates)) / (8.0 + idx % 7))
        shock = rng.normal(0.0, vol, len(dates))
        rows[sleeve_name] = np.clip(drift + cycle + shock, -0.35, 0.35)
    returns = pd.DataFrame(rows, index=dates)
    returns.index.name = "timestamp"
    proxy_map = build_proxy_map(config)
    proxy_map["available"] = True
    proxy_map["first_date"] = dates.min().date().isoformat()
    proxy_map["last_date"] = dates.max().date().isoformat()
    data_audit = proxy_map[["sleeve", "proxy_symbol", "available", "first_date", "last_date", "proxy_quality_score"]].copy()
    data_audit["source_mode"] = "synthetic_smoke"
    return returns, proxy_map, data_audit


def download_monthly_proxy_returns(
    config: dict[str, Any],
    output_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    try:
        import yfinance as yf
    except Exception as exc:  # pragma: no cover - dependency exists in project, guard is for CI clarity.
        raise RuntimeError("yfinance is required for non-smoke SWR campaign") from exc

    start = config["periods"]["train_start"]
    end_exclusive = config["periods"]["locked_start"]
    raw_prices: dict[str, pd.Series] = {}
    audit_rows: list[dict[str, Any]] = []
    proxy_map = build_proxy_map(config)
    cache_path = output_dir / "proxy_price_cache.csv"
    cached = pd.DataFrame()
    if cache_path.exists():
        cached = pd.read_csv(cache_path, parse_dates=["timestamp"]).set_index("timestamp")
        validate_no_locked_dates(cached.reset_index(), "timestamp", end_exclusive)

    for sleeve_name, sleeve in config["sleeves"].items():
        symbol = str(sleeve["proxy_symbol"])
        if sleeve_name == "cash":
            dates = pd.date_range(start, config["periods"]["validation_end"], freq="ME")
            raw_prices[sleeve_name] = pd.Series(1.0, index=dates, name=sleeve_name)
            audit_rows.append(_data_audit_row(sleeve_name, sleeve, True, dates.min(), dates.max(), "internal_cash"))
            continue
        if sleeve_name in cached.columns:
            series = cached[sleeve_name].dropna()
        else:
            data = yf.download(symbol, start=start, end=end_exclusive, auto_adjust=True, progress=False)
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = [col[0] for col in data.columns]
            column = "Close" if "Close" in data.columns else "Adj Close" if "Adj Close" in data.columns else None
            series = data[column].dropna() if column else pd.Series(dtype=float)
        if series.empty:
            audit_rows.append(_data_audit_row(sleeve_name, sleeve, False, None, None, "missing_download"))
            continue
        series.index = pd.to_datetime(series.index).tz_localize(None)
        series = series[series.index < pd.Timestamp(end_exclusive)]
        if series.empty:
            audit_rows.append(_data_audit_row(sleeve_name, sleeve, False, None, None, "empty_before_locked"))
            continue
        raw_prices[sleeve_name] = series.rename(sleeve_name)
        audit_rows.append(_data_audit_row(sleeve_name, sleeve, True, series.index.min(), series.index.max(), "downloaded"))

    if not raw_prices:
        raise RuntimeError("no proxy series available")

    prices = pd.concat(raw_prices.values(), axis=1).sort_index()
    validate_no_locked_dates(prices.reset_index().rename(columns={"index": "timestamp"}), "timestamp", end_exclusive)
    prices.to_csv(cache_path, index_label="timestamp")
    monthly_prices = prices.resample("ME").last().ffill()
    returns = monthly_prices.pct_change().dropna(how="all").fillna(0.0)
    returns.index.name = "timestamp"
    validate_no_locked_dates(returns.reset_index(), "timestamp", end_exclusive)

    data_audit = pd.DataFrame(audit_rows)
    proxy_map = proxy_map.merge(
        data_audit[["sleeve", "available", "first_date", "last_date"]],
        on="sleeve",
        how="left",
    )
    return returns, proxy_map, data_audit


def _data_audit_row(
    sleeve_name: str,
    sleeve: dict[str, Any],
    available: bool,
    first: pd.Timestamp | None,
    last: pd.Timestamp | None,
    status: str,
) -> dict[str, Any]:
    return {
        "sleeve": sleeve_name,
        "tradable_etf": sleeve["tradable_etf"],
        "proxy_symbol": sleeve["proxy_symbol"],
        "available": bool(available),
        "first_date": pd.Timestamp(first).date().isoformat() if first is not None else "",
        "last_date": pd.Timestamp(last).date().isoformat() if last is not None else "",
        "status": status,
        "proxy_quality_score": float(sleeve["proxy_quality_score"]),
        "proxy_source": sleeve["proxy_source"],
    }


def build_proxy_map(config: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for sleeve_name, sleeve in config["sleeves"].items():
        rows.append(
            {
                "sleeve": sleeve_name,
                "tradable_etf": sleeve["tradable_etf"],
                "proxy_name": sleeve["proxy_name"],
                "proxy_symbol": sleeve["proxy_symbol"],
                "proxy_source": sleeve["proxy_source"],
                "proxy_start": sleeve["proxy_start"],
                "etf_inception": sleeve["etf_inception"],
                "proxy_quality_score": float(sleeve["proxy_quality_score"]),
                "expense_annual": float(sleeve.get("expense_annual", 0.0)),
                "uses_concrete_stocks": False,
                "uses_crypto": False,
            }
        )
    return pd.DataFrame(rows)


def run_full(
    output_dir: Path,
    config: dict[str, Any],
    returns: pd.DataFrame,
    proxy_map: pd.DataFrame,
    data_audit: pd.DataFrame,
) -> None:
    candidates: list[Candidate] = []
    shards_per_family = int(config["github"]["shards_per_family"])
    for family in config["families"]:
        for shard_id in range(shards_per_family):
            candidates.extend(generate_candidates_for_shard(config, returns, family, shard_id))
    write_campaign_outputs(output_dir, config, returns, proxy_map, data_audit, candidates)


def run_shard(
    output_dir: Path,
    config: dict[str, Any],
    returns: pd.DataFrame,
    proxy_map: pd.DataFrame,
    data_audit: pd.DataFrame,
    family_id: int,
    shard_id: int,
) -> None:
    family = get_family(config, family_id)
    shard_dir = output_dir / "shards" / f"family_{family_id:02d}_shard_{shard_id:02d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    candidates = generate_candidates_for_shard(config, returns, family, shard_id)
    metrics, paths, allocations, equity = evaluate_candidates(config, candidates)
    metrics = rank_metrics(metrics)
    top = metrics.head(int(config["ranking"]["top_per_job"])).copy()
    _write_table(metrics, shard_dir / "all_candidates_metrics.parquet")
    top.to_csv(shard_dir / "pruned_by_job.csv", index=False)
    paths.to_parquet(shard_dir / "worst_start_paths.parquet", index=False)
    allocations.to_parquet(shard_dir / "monthly_allocations.parquet", index=False)
    equity.to_parquet(shard_dir / "monthly_equity_after_withdrawals.parquet", index=False)
    proxy_map.to_csv(shard_dir / "proxy_map.csv", index=False)
    data_audit.to_csv(shard_dir / "data_audit.csv", index=False)
    write_locked_audit(shard_dir, config, returns)


def merge_shards(output_dir: Path, config: dict[str, Any]) -> None:
    shard_root = output_dir / "shards"
    metric_files = list(shard_root.glob("**/all_candidates_metrics.parquet"))
    if not metric_files:
        raise RuntimeError(f"no shard metrics found under {shard_root}")
    metrics = pd.concat([pd.read_parquet(path) for path in metric_files], ignore_index=True)
    metrics = rank_metrics(metrics)
    pruned_by_job = pd.concat(
        [pd.read_csv(path) for path in shard_root.glob("**/pruned_by_job.csv")],
        ignore_index=True,
    )
    pruned_by_family = (
        metrics.sort_values(["family", "train_rank_score"], ascending=[True, False])
        .groupby("family", group_keys=False)
        .head(int(config["ranking"]["top_per_family"]))
    )
    champions = select_family_champions(pruned_by_family)
    accepted = champions[champions["accepted"].astype(bool)].copy()
    rejected = champions[~champions["accepted"].astype(bool)].copy()
    paths = _concat_optional_parquet(shard_root, "worst_start_paths.parquet")
    allocations = _concat_optional_parquet(shard_root, "monthly_allocations.parquet")
    equity = _concat_optional_parquet(shard_root, "monthly_equity_after_withdrawals.parquet")
    proxy_maps = list(shard_root.glob("**/proxy_map.csv"))
    data_audits = list(shard_root.glob("**/data_audit.csv"))
    proxy_map = pd.read_csv(proxy_maps[0]) if proxy_maps else pd.DataFrame()
    data_audit = pd.read_csv(data_audits[0]) if data_audits else pd.DataFrame()

    _write_table(metrics, output_dir / OUTPUT_FILES["all_candidates"])
    pruned_by_job.to_csv(output_dir / OUTPUT_FILES["pruned_by_job"], index=False)
    pruned_by_family.to_csv(output_dir / OUTPUT_FILES["pruned_by_family"], index=False)
    champions.to_csv(output_dir / OUTPUT_FILES["champions"], index=False)
    accepted.to_csv(output_dir / OUTPUT_FILES["accepted"], index=False)
    rejected.to_csv(output_dir / OUTPUT_FILES["rejected"], index=False)
    pd.DataFrame().to_csv(output_dir / OUTPUT_FILES["portfolios"], index=False)
    _write_table(paths, output_dir / OUTPUT_FILES["worst_paths"])
    _write_table(equity, output_dir / OUTPUT_FILES["equity"])
    _write_table(allocations, output_dir / OUTPUT_FILES["allocations"])
    proxy_map.to_csv(output_dir / OUTPUT_FILES["proxy_map"], index=False)
    data_audit.to_csv(output_dir / OUTPUT_FILES["data_audit"], index=False)
    write_locked_audit(output_dir, config, pd.DataFrame(index=pd.DatetimeIndex([])))
    write_sources(output_dir, config)
    write_summary_and_report(output_dir, config, metrics, champions, accepted, pd.DataFrame())


def _concat_optional_parquet(root: Path, filename: str) -> pd.DataFrame:
    files = list(root.glob(f"**/{filename}"))
    if not files:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(path) for path in files], ignore_index=True)


def generate_candidates_for_shard(
    config: dict[str, Any],
    returns: pd.DataFrame,
    family: dict[str, Any],
    shard_id: int,
) -> list[Candidate]:
    family_id = int(family["id"])
    rng = np.random.default_rng(stable_int(f"{config['campaign_id']}:{family_id}:{shard_id}"))
    candidates: list[Candidate] = []
    configs_per_shard = int(config["github"]["configs_per_shard"])
    available = [s for s in family["sleeves"] if s in returns.columns]
    if len([s for s in available if s != "cash"]) < 2:
        return []
    for local_idx in range(configs_per_shard):
        params = sample_params(config, family, available, rng)
        monthly_allocations = build_allocations(config, returns, family, params)
        monthly_returns = (monthly_allocations.reindex(columns=returns.columns, fill_value=0.0) * returns).sum(axis=1)
        expense = estimate_expense(monthly_allocations, config)
        monthly_returns = monthly_returns - expense / 12.0
        monthly_returns.name = "strategy_return"
        turnover = estimate_turnover(monthly_allocations)
        proxy_quality = estimate_proxy_quality(monthly_allocations, config)
        cfg_hash = config_hash({"family": family["name"], "params": params, "shard": shard_id, "idx": local_idx})
        candidates.append(
            Candidate(
                strategy_id=f"swr_{family['name']}_{cfg_hash[:12]}",
                family=str(family["name"]),
                family_id=family_id,
                shard_id=shard_id,
                config_index=local_idx,
                config_hash=cfg_hash,
                params=params,
                monthly_returns=monthly_returns,
                monthly_allocations=monthly_allocations,
                turnover_annual=turnover,
                expense_annual=expense,
                proxy_quality_score=proxy_quality,
            )
        )
    return candidates


def sample_params(
    config: dict[str, Any],
    family: dict[str, Any],
    available: list[str],
    rng: np.random.Generator,
) -> dict[str, Any]:
    risky = [s for s in available if s != "cash"]
    max_assets = min(len(risky), int(rng.choice([2, 3, 4, 5, 6, 8, 10])))
    assets = sorted(rng.choice(risky, size=max(2, max_assets), replace=False).tolist())
    if "cash" in available and rng.random() < 0.85:
        assets.append("cash")
    lookback = int(rng.choice(config["lookbacks_months"]))
    sma = int(rng.choice(config["sma_months"]))
    vol_lookback = int(rng.choice(config["vol_lookbacks_months"]))
    top_n = int(min(rng.choice(config["top_n"]), max(1, len([a for a in assets if a != "cash"]))))
    target_vol = float(rng.choice(config["target_vols"]))
    cash_bucket_months = int(rng.choice(config["cash_bucket_months"]))
    weights = rng.dirichlet(np.ones(len(assets))).round(6).tolist()
    return {
        "assets": assets,
        "weights": weights,
        "lookback_months": lookback,
        "sma_months": sma,
        "vol_lookback_months": vol_lookback,
        "top_n": top_n,
        "target_vol": target_vol,
        "cash_bucket_months": cash_bucket_months,
        "risk_off_asset": "cash" if "cash" in available else assets[-1],
    }


def build_allocations(
    config: dict[str, Any],
    returns: pd.DataFrame,
    family: dict[str, Any],
    params: dict[str, Any],
) -> pd.DataFrame:
    ftype = str(family["type"])
    assets = [asset for asset in params["assets"] if asset in returns.columns]
    base = pd.DataFrame(0.0, index=returns.index, columns=returns.columns)
    if ftype == "static_mix":
        return static_alloc(base, assets, params["weights"])
    if ftype in {"trend_top_n", "relative_strength"}:
        return trend_top_n_alloc(base, returns, assets, params)
    if ftype == "dual_momentum":
        return dual_momentum_alloc(base, returns, assets, params)
    if ftype == "risk_parity":
        return risk_parity_alloc(base, returns, assets, params, trend_filter=False)
    if ftype == "risk_parity_trend":
        return risk_parity_alloc(base, returns, assets, params, trend_filter=True)
    if ftype == "vol_target":
        return vol_target_alloc(base, returns, assets, params)
    if ftype == "min_vol_rotation":
        return min_vol_alloc(base, returns, assets, params)
    if ftype == "drawdown_aware":
        return drawdown_aware_alloc(base, returns, assets, params)
    if ftype == "canary":
        return canary_alloc(base, returns, assets, params)
    if ftype == "absolute_momentum":
        return absolute_momentum_alloc(base, returns, assets, params)
    if ftype == "crisis_hedge":
        return crisis_hedge_alloc(base, returns, assets, params)
    if ftype == "credit_stress":
        return credit_stress_alloc(base, returns, assets, params)
    if ftype == "cash_bucket":
        return cash_bucket_alloc(base, returns, assets, params)
    if ftype == "ensemble":
        a = trend_top_n_alloc(base.copy(), returns, assets, params)
        b = risk_parity_alloc(base.copy(), returns, assets, params, trend_filter=True)
        c = drawdown_aware_alloc(base.copy(), returns, assets, params)
        return ((a + b + c) / 3.0).clip(lower=0.0, upper=1.0)
    return static_alloc(base, assets, params["weights"])


def static_alloc(base: pd.DataFrame, assets: list[str], weights: list[float]) -> pd.DataFrame:
    weights_arr = np.asarray(weights[: len(assets)], dtype=float)
    weights_arr = weights_arr / weights_arr.sum()
    for asset, weight in zip(assets, weights_arr):
        base[asset] = float(weight)
    return base


def trend_top_n_alloc(
    base: pd.DataFrame,
    returns: pd.DataFrame,
    assets: list[str],
    params: dict[str, Any],
) -> pd.DataFrame:
    risky = [a for a in assets if a != "cash"]
    momentum = (1.0 + returns[risky]).rolling(params["lookback_months"], min_periods=1).apply(np.prod, raw=True) - 1.0
    ranks = momentum.rank(axis=1, ascending=False, method="first")
    selected = (ranks <= int(params["top_n"])) & (momentum > 0)
    weights = selected.div(selected.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    base.loc[:, risky] = weights.shift(1).fillna(0.0)
    if "cash" in base.columns:
        base["cash"] = 1.0 - base[risky].sum(axis=1)
    return base.clip(lower=0.0, upper=1.0)


def dual_momentum_alloc(base: pd.DataFrame, returns: pd.DataFrame, assets: list[str], params: dict[str, Any]) -> pd.DataFrame:
    risky = [a for a in assets if a != "cash"]
    momentum = (1.0 + returns[risky]).rolling(params["lookback_months"], min_periods=1).apply(np.prod, raw=True) - 1.0
    winner = momentum.idxmax(axis=1)
    winner_value = momentum.max(axis=1)
    shifted_winner = winner.shift(1)
    shifted_ok = winner_value.shift(1) > 0
    for date in base.index:
        if bool(shifted_ok.loc[date]) and shifted_winner.loc[date] in base.columns:
            base.loc[date, shifted_winner.loc[date]] = 1.0
        elif "cash" in base.columns:
            base.loc[date, "cash"] = 1.0
    return base


def risk_parity_alloc(
    base: pd.DataFrame,
    returns: pd.DataFrame,
    assets: list[str],
    params: dict[str, Any],
    *,
    trend_filter: bool,
) -> pd.DataFrame:
    risky = [a for a in assets if a != "cash"]
    vol = returns[risky].rolling(params["vol_lookback_months"], min_periods=2).std().replace(0.0, np.nan)
    inv_vol = 1.0 / vol
    weights = inv_vol.div(inv_vol.sum(axis=1), axis=0).shift(1).fillna(0.0)
    if trend_filter:
        momentum = returns[risky].rolling(params["lookback_months"], min_periods=1).sum().shift(1)
        weights = weights.where(momentum > 0, 0.0)
        weights = weights.div(weights.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    base.loc[:, risky] = weights
    if "cash" in base.columns:
        base["cash"] = 1.0 - base[risky].sum(axis=1)
    return base.clip(lower=0.0, upper=1.0)


def vol_target_alloc(base: pd.DataFrame, returns: pd.DataFrame, assets: list[str], params: dict[str, Any]) -> pd.DataFrame:
    alloc = risk_parity_alloc(base, returns, assets, params, trend_filter=False)
    risky = [a for a in assets if a != "cash"]
    gross_returns = (alloc[risky] * returns[risky]).sum(axis=1)
    realized = gross_returns.rolling(params["vol_lookback_months"], min_periods=2).std() * math.sqrt(12)
    scale = (float(params["target_vol"]) / realized).clip(lower=0.0, upper=1.0).shift(1).fillna(0.0)
    alloc.loc[:, risky] = alloc[risky].mul(scale, axis=0)
    if "cash" in alloc.columns:
        alloc["cash"] = 1.0 - alloc[risky].sum(axis=1)
    return alloc.clip(lower=0.0, upper=1.0)


def min_vol_alloc(base: pd.DataFrame, returns: pd.DataFrame, assets: list[str], params: dict[str, Any]) -> pd.DataFrame:
    risky = [a for a in assets if a != "cash"]
    vol = returns[risky].rolling(params["vol_lookback_months"], min_periods=2).std()
    selected = vol.rank(axis=1, ascending=True, method="first") <= int(params["top_n"])
    weights = selected.div(selected.sum(axis=1).replace(0, np.nan), axis=0).shift(1).fillna(0.0)
    base.loc[:, risky] = weights
    if "cash" in base.columns:
        base["cash"] = 1.0 - base[risky].sum(axis=1)
    return base.clip(lower=0.0, upper=1.0)


def drawdown_aware_alloc(base: pd.DataFrame, returns: pd.DataFrame, assets: list[str], params: dict[str, Any]) -> pd.DataFrame:
    risky = [a for a in assets if a != "cash"]
    equal = static_alloc(base.copy(), assets, params["weights"])
    equity = (1.0 + (equal[risky] * returns[risky]).sum(axis=1)).cumprod()
    drawdown = equity / equity.rolling(12, min_periods=3).max() - 1.0
    scale = np.where(drawdown.shift(1).fillna(0.0) < -0.10, 0.35, 1.0)
    equal.loc[:, risky] = equal[risky].mul(scale, axis=0)
    if "cash" in equal.columns:
        equal["cash"] = 1.0 - equal[risky].sum(axis=1)
    return equal.clip(lower=0.0, upper=1.0)


def canary_alloc(base: pd.DataFrame, returns: pd.DataFrame, assets: list[str], params: dict[str, Any]) -> pd.DataFrame:
    risky = [a for a in assets if a != "cash"]
    canaries = [a for a in risky if a in {"us_equity", "developed_ex_us", "emerging_markets"}] or risky[:2]
    canary_ok = returns[canaries].rolling(params["lookback_months"], min_periods=1).sum().mean(axis=1).shift(1) > 0
    risk_on = trend_top_n_alloc(base.copy(), returns, assets, params)
    defensive_assets = [a for a in ["intermediate_treasury", "aggregate_bonds", "long_treasury", "cash"] if a in assets]
    risk_off = static_alloc(base.copy(), defensive_assets or assets, [1.0] * len(defensive_assets or assets))
    return risk_on.where(canary_ok, risk_off).fillna(0.0).clip(lower=0.0, upper=1.0)


def absolute_momentum_alloc(base: pd.DataFrame, returns: pd.DataFrame, assets: list[str], params: dict[str, Any]) -> pd.DataFrame:
    risky = [a for a in assets if a != "cash"]
    momentum = returns[risky].rolling(params["lookback_months"], min_periods=1).sum().shift(1)
    selected = momentum > 0
    weights = selected.div(selected.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    base.loc[:, risky] = weights
    if "cash" in base.columns:
        base["cash"] = 1.0 - base[risky].sum(axis=1)
    return base.clip(lower=0.0, upper=1.0)


def crisis_hedge_alloc(base: pd.DataFrame, returns: pd.DataFrame, assets: list[str], params: dict[str, Any]) -> pd.DataFrame:
    risky = [a for a in assets if a != "cash"]
    if "us_equity" not in returns.columns:
        return trend_top_n_alloc(base, returns, assets, params)
    equity_mom = returns["us_equity"].rolling(params["lookback_months"], min_periods=1).sum().shift(1)
    hedge_assets = [a for a in ["gold_proxy", "commodities_proxy", "long_treasury", "cash"] if a in assets]
    risk_on = static_alloc(base.copy(), ["us_equity"] if "us_equity" in assets else risky[:1], [1.0])
    risk_off = trend_top_n_alloc(base.copy(), returns, hedge_assets or assets, params)
    return risk_on.where(equity_mom > 0, risk_off).fillna(0.0).clip(lower=0.0, upper=1.0)


def credit_stress_alloc(base: pd.DataFrame, returns: pd.DataFrame, assets: list[str], params: dict[str, Any]) -> pd.DataFrame:
    risk_asset = "high_yield_proxy" if "high_yield_proxy" in returns.columns else "us_equity"
    safe_asset = "intermediate_treasury" if "intermediate_treasury" in returns.columns else "cash"
    stress = returns.get(risk_asset, pd.Series(0.0, index=returns.index)).rolling(3, min_periods=1).sum().shift(1) < 0
    base.loc[:, :] = 0.0
    for date in base.index:
        base.loc[date, safe_asset if bool(stress.loc[date]) else risk_asset] = 1.0
    return base.clip(lower=0.0, upper=1.0)


def cash_bucket_alloc(base: pd.DataFrame, returns: pd.DataFrame, assets: list[str], params: dict[str, Any]) -> pd.DataFrame:
    risky = [a for a in assets if a != "cash"]
    invested = max(0.0, 1.0 - (params["cash_bucket_months"] * 2000.0 / 100000.0))
    trend = trend_top_n_alloc(base.copy(), returns, risky + (["cash"] if "cash" in assets else []), params)
    trend.loc[:, risky] = trend[risky] * invested
    if "cash" in trend.columns:
        trend["cash"] = 1.0 - trend[risky].sum(axis=1)
    return trend.clip(lower=0.0, upper=1.0)


def evaluate_candidates(
    config: dict[str, Any],
    candidates: list[Candidate],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    metric_rows: list[dict[str, Any]] = []
    path_rows: list[pd.DataFrame] = []
    alloc_rows: list[pd.DataFrame] = []
    equity_rows: list[pd.DataFrame] = []
    periods = config["periods"]
    for candidate in candidates:
        train = candidate.monthly_returns.loc[periods["train_start"] : periods["train_end"]]
        validation = candidate.monthly_returns.loc[periods["validation_start"] : periods["validation_end"]]
        train_result, train_paths = score_period(config, train, "train")
        validation_result, validation_paths = score_period(config, validation, "validation")
        train_metrics = return_metrics(train)
        validation_metrics = return_metrics(validation)
        accepted = (
            train_result.target_monthly_pass
            and validation_result.target_monthly_pass
            and train_result.worst_start_max_drawdown > float(config["rules"]["max_mdd_after_withdrawals"])
            and validation_result.worst_start_max_drawdown > float(config["rules"]["max_mdd_after_withdrawals"])
        )
        metric_rows.append(
            {
                "strategy_id": candidate.strategy_id,
                "family": candidate.family,
                "family_id": candidate.family_id,
                "shard_id": candidate.shard_id,
                "config_index": candidate.config_index,
                "accepted": bool(accepted),
                "monthly_withdrawal_tested": float(config["capital"]["monthly_withdrawal"]),
                "max_safe_monthly_withdrawal_train": train_result.max_safe_monthly_withdrawal,
                "max_safe_monthly_withdrawal_validation": validation_result.max_safe_monthly_withdrawal,
                "target_2000_pass_train": bool(train_result.target_monthly_pass),
                "target_2000_pass_validation": bool(validation_result.target_monthly_pass),
                "worst_start_month_train": train_result.worst_start_date,
                "worst_start_month_validation": validation_result.worst_start_date,
                "mdd_after_withdrawals_train": train_result.worst_start_max_drawdown,
                "mdd_after_withdrawals_validation": validation_result.worst_start_max_drawdown,
                "cagr_train": train_metrics["cagr"],
                "cagr_validation": validation_metrics["cagr"],
                "sharpe_train": train_metrics["sharpe"],
                "sharpe_validation": validation_metrics["sharpe"],
                "calmar_after_withdrawals_train": safe_div(train_metrics["cagr"], abs(train_result.worst_start_max_drawdown)),
                "calmar_after_withdrawals_validation": safe_div(validation_metrics["cagr"], abs(validation_result.worst_start_max_drawdown)),
                "turnover_annual": candidate.turnover_annual,
                "expense_annual": candidate.expense_annual,
                "uses_concrete_stocks": False,
                "uses_crypto": False,
                "locked_opened": False,
                "data_end_max": config["rules"]["data_end_max"],
                "proxy_quality_score": candidate.proxy_quality_score,
                "config_hash": candidate.config_hash,
                "params_json": json.dumps(candidate.params, sort_keys=True),
            }
        )
        path_rows.append(_tag_paths(train_paths, candidate, "train"))
        path_rows.append(_tag_paths(validation_paths, candidate, "validation"))
        alloc_rows.append(_tag_allocations(candidate))
        equity_rows.append(_worst_equity_paths(config, candidate, train, validation, train_paths, validation_paths))

    metrics = pd.DataFrame(metric_rows)
    paths = pd.concat(path_rows, ignore_index=True) if path_rows else pd.DataFrame()
    allocations = pd.concat(alloc_rows, ignore_index=True) if alloc_rows else pd.DataFrame()
    equity = pd.concat(equity_rows, ignore_index=True) if equity_rows else pd.DataFrame()
    return metrics, paths, allocations, equity


def score_period(config: dict[str, Any], returns: pd.Series, role: str):
    min_horizon_key = "min_horizon_months_train" if role == "train" else "min_horizon_months_validation"
    return safe_withdrawal_rate(
        returns,
        initial_capital=float(config["capital"]["initial"]),
        target_monthly_withdrawal=float(config["capital"]["monthly_withdrawal"]),
        min_horizon_months=int(config["capital"][min_horizon_key]),
        withdraw_at_start=bool(config["capital"]["withdraw_at_start"]),
        precision=float(config["capital"]["precision"]),
        max_monthly_search=float(config["capital"]["max_monthly_search"]),
    )


def return_metrics(returns: pd.Series) -> dict[str, float]:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return {"cagr": float("nan"), "sharpe": float("nan"), "mdd": float("nan")}
    equity = (1.0 + clean).cumprod()
    years = len(clean) / 12.0
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and equity.iloc[-1] > 0 else float("nan")
    sharpe = safe_div(float(clean.mean() * 12.0), float(clean.std(ddof=0) * math.sqrt(12.0)))
    mdd = max_drawdown(equity)
    return {"cagr": cagr, "sharpe": sharpe, "mdd": mdd}


def _tag_paths(paths: pd.DataFrame, candidate: Candidate, role: str) -> pd.DataFrame:
    if paths.empty:
        return paths
    tagged = paths.copy()
    tagged.insert(0, "strategy_id", candidate.strategy_id)
    tagged.insert(1, "family", candidate.family)
    tagged.insert(2, "sample_role", role)
    return tagged


def _tag_allocations(candidate: Candidate) -> pd.DataFrame:
    frame = candidate.monthly_allocations.copy()
    frame.insert(0, "timestamp", frame.index)
    frame.insert(1, "strategy_id", candidate.strategy_id)
    frame.insert(2, "family", candidate.family)
    return frame


def _worst_equity_paths(
    config: dict[str, Any],
    candidate: Candidate,
    train: pd.Series,
    validation: pd.Series,
    train_paths: pd.DataFrame,
    validation_paths: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    for role, series, paths in (("train", train, train_paths), ("validation", validation, validation_paths)):
        if paths.empty:
            continue
        worst = paths.sort_values(["survived", "final_capital", "max_drawdown"], ascending=[True, True, True]).iloc[0]
        monthly = series.dropna()
        start = pd.Timestamp(worst["start_date"])
        start_index = int(np.where(monthly.index == start)[0][0]) if start in monthly.index else 0
        capital = float(config["capital"]["initial"])
        for timestamp, period_return in monthly.iloc[start_index:].items():
            capital -= float(config["capital"]["monthly_withdrawal"])
            if capital <= 0:
                rows.append(
                    {
                        "strategy_id": candidate.strategy_id,
                        "family": candidate.family,
                        "sample_role": role,
                        "start_date": worst["start_date"],
                        "timestamp": timestamp,
                        "capital": capital,
                        "failed": True,
                    }
                )
                break
            capital *= 1.0 + float(period_return)
            rows.append(
                {
                    "strategy_id": candidate.strategy_id,
                    "family": candidate.family,
                    "sample_role": role,
                    "start_date": worst["start_date"],
                    "timestamp": timestamp,
                    "capital": capital,
                    "failed": capital <= 0,
                }
            )
            if capital <= 0:
                break
    return pd.DataFrame(rows)


def write_campaign_outputs(
    output_dir: Path,
    config: dict[str, Any],
    returns: pd.DataFrame,
    proxy_map: pd.DataFrame,
    data_audit: pd.DataFrame,
    candidates: list[Candidate],
) -> None:
    metrics, paths, allocations, equity = evaluate_candidates(config, candidates)
    metrics = rank_metrics(metrics)
    pruned_by_job = (
        metrics.sort_values(["family", "shard_id", "train_rank_score"], ascending=[True, True, False])
        .groupby(["family", "shard_id"], group_keys=False)
        .head(int(config["ranking"]["top_per_job"]))
    )
    pruned_by_family = (
        metrics.sort_values(["family", "train_rank_score"], ascending=[True, False])
        .groupby("family", group_keys=False)
        .head(int(config["ranking"]["top_per_family"]))
    )
    champions = select_family_champions(pruned_by_family)
    accepted = champions[champions["accepted"].astype(bool)].copy()
    rejected = champions[~champions["accepted"].astype(bool)].copy()
    portfolios = build_portfolio_combinations(config, champions, candidates)

    _write_table(metrics, output_dir / OUTPUT_FILES["all_candidates"])
    pruned_by_job.to_csv(output_dir / OUTPUT_FILES["pruned_by_job"], index=False)
    pruned_by_family.to_csv(output_dir / OUTPUT_FILES["pruned_by_family"], index=False)
    champions.to_csv(output_dir / OUTPUT_FILES["champions"], index=False)
    accepted.to_csv(output_dir / OUTPUT_FILES["accepted"], index=False)
    rejected.to_csv(output_dir / OUTPUT_FILES["rejected"], index=False)
    portfolios.to_csv(output_dir / OUTPUT_FILES["portfolios"], index=False)
    _write_table(paths, output_dir / OUTPUT_FILES["worst_paths"])
    _write_table(equity, output_dir / OUTPUT_FILES["equity"])
    _write_table(allocations, output_dir / OUTPUT_FILES["allocations"])
    proxy_map.to_csv(output_dir / OUTPUT_FILES["proxy_map"], index=False)
    data_audit.to_csv(output_dir / OUTPUT_FILES["data_audit"], index=False)
    write_locked_audit(output_dir, config, returns)
    write_sources(output_dir, config)
    write_summary_and_report(output_dir, config, metrics, champions, accepted, portfolios)


def rank_metrics(metrics: pd.DataFrame) -> pd.DataFrame:
    if metrics.empty:
        return metrics
    ranked = metrics.copy()
    ranked["train_rank_score"] = (
        ranked["target_2000_pass_train"].astype(int) * 1_000_000_000
        + ranked["max_safe_monthly_withdrawal_train"].fillna(0.0) * 10_000
        + (ranked["mdd_after_withdrawals_train"].fillna(-1.0) > -0.50).astype(int) * 100_000
        + ranked["calmar_after_withdrawals_train"].replace([np.inf, -np.inf], np.nan).fillna(-99.0) * 1_000
        + ranked["sharpe_train"].replace([np.inf, -np.inf], np.nan).fillna(-99.0) * 100
        - ranked["turnover_annual"].fillna(99.0) * 10
        - ranked["expense_annual"].fillna(1.0) * 1_000
    )
    ranked["final_report_score"] = (
        ranked["accepted"].astype(int) * 1_000_000_000
        + ranked["max_safe_monthly_withdrawal_validation"].fillna(0.0) * 10_000
        + ranked["mdd_after_withdrawals_validation"].fillna(-1.0) * 100_000
        - ranked["turnover_annual"].fillna(99.0) * 10
        - ranked["expense_annual"].fillna(1.0) * 1_000
    )
    return ranked.sort_values("train_rank_score", ascending=False)


def select_family_champions(pruned_by_family: pd.DataFrame) -> pd.DataFrame:
    if pruned_by_family.empty:
        return pruned_by_family
    champions = (
        pruned_by_family.sort_values(["family", "train_rank_score"], ascending=[True, False])
        .groupby("family", group_keys=False)
        .head(1)
        .sort_values("final_report_score", ascending=False)
    )
    return champions


def build_portfolio_combinations(
    config: dict[str, Any],
    champions: pd.DataFrame,
    candidates: list[Candidate],
) -> pd.DataFrame:
    if champions.empty:
        return pd.DataFrame()
    by_id = {candidate.strategy_id: candidate for candidate in candidates}
    rows = []
    ordered = champions.sort_values("train_rank_score", ascending=False)["strategy_id"].tolist()
    for size in (3, 5, 10, 20):
        selected = [strategy_id for strategy_id in ordered[:size] if strategy_id in by_id]
        if not selected:
            continue
        combined = pd.concat([by_id[strategy_id].monthly_returns for strategy_id in selected], axis=1).mean(axis=1)
        train = combined.loc[config["periods"]["train_start"] : config["periods"]["train_end"]]
        validation = combined.loc[config["periods"]["validation_start"] : config["periods"]["validation_end"]]
        train_swr, _ = score_period(config, train, "train")
        valid_swr, _ = score_period(config, validation, "validation")
        rows.append(
            {
                "portfolio_id": f"top_{size}_champions_equal_weight",
                "strategy_count": len(selected),
                "strategy_ids": "|".join(selected),
                "max_safe_monthly_withdrawal_train": train_swr.max_safe_monthly_withdrawal,
                "max_safe_monthly_withdrawal_validation": valid_swr.max_safe_monthly_withdrawal,
                "target_2000_pass_train": train_swr.target_monthly_pass,
                "target_2000_pass_validation": valid_swr.target_monthly_pass,
                "mdd_after_withdrawals_train": train_swr.worst_start_max_drawdown,
                "mdd_after_withdrawals_validation": valid_swr.worst_start_max_drawdown,
            }
        )
    return pd.DataFrame(rows)


def write_locked_audit(output_dir: Path, config: dict[str, Any], returns: pd.DataFrame) -> None:
    max_date = ""
    if not returns.empty and isinstance(returns.index, pd.DatetimeIndex):
        max_date = returns.index.max().date().isoformat()
    audit = pd.DataFrame(
        [
            {
                "campaign_id": config["campaign_id"],
                "locked_start": config["periods"]["locked_start"],
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "max_data_date": max_date,
                "status": "pass",
            }
        ]
    )
    audit.to_csv(output_dir / OUTPUT_FILES["locked_audit"], index=False)


def write_sources(output_dir: Path, config: dict[str, Any]) -> None:
    pd.DataFrame(config.get("literature_sources", [])).to_csv(output_dir / OUTPUT_FILES["sources"], index=False)


def write_summary_and_report(
    output_dir: Path,
    config: dict[str, Any],
    metrics: pd.DataFrame,
    champions: pd.DataFrame,
    accepted: pd.DataFrame,
    portfolios: pd.DataFrame,
) -> None:
    summary = {
        "campaign_id": config["campaign_id"],
        "candidate_rows": int(len(metrics)),
        "family_count": int(len(config["families"])),
        "champion_count": int(len(champions)),
        "accepted_count": int(len(accepted)),
        "monthly_withdrawal_tested": float(config["capital"]["monthly_withdrawal"]),
        "target_swr_annual_pct": float(config["capital"]["monthly_withdrawal"]) * 12.0 / float(config["capital"]["initial"]) * 100.0,
        "locked_opened": False,
        "uses_concrete_stocks": False,
        "uses_crypto": False,
        "data_end_max": config["rules"]["data_end_max"],
        "best_champion": _json_row(champions.head(1)),
        "best_portfolio": _json_row(portfolios.head(1)),
    }
    (output_dir / OUTPUT_FILES["summary"]).write_text(json.dumps(json_safe(summary), indent=2), encoding="utf-8")
    lines = [
        "# SWR 20 ETF/Proxy 2000 No Locked Report",
        "",
        f"- Campaign: `{config['campaign_id']}`",
        f"- Candidates evaluated: {len(metrics)}",
        f"- Champions: {len(champions)}",
        f"- Accepted at 2000/month: {len(accepted)}",
        "- Locked opened: false",
        "- Concrete stocks used: false",
        "- Crypto used: false",
        f"- Data end max: {config['rules']['data_end_max']}",
        "",
        "Acceptance is intentionally brutal: if none pass, the correct answer is zero. No maquillaje.",
    ]
    (output_dir / OUTPUT_FILES["report"]).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".parquet":
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


def get_family(config: dict[str, Any], family_id: int) -> dict[str, Any]:
    for family in config["families"]:
        if int(family["id"]) == int(family_id):
            return family
    raise ValueError(f"unknown family id: {family_id}")


def estimate_turnover(allocations: pd.DataFrame) -> float:
    if allocations.empty:
        return 0.0
    return float(allocations.diff().abs().sum(axis=1).mean() * 12.0)


def estimate_expense(allocations: pd.DataFrame, config: dict[str, Any]) -> float:
    expenses = {k: float(v.get("expense_annual", 0.0)) for k, v in config["sleeves"].items()}
    common = [col for col in allocations.columns if col in expenses]
    if not common:
        return 0.0
    return float((allocations[common].mean() * pd.Series(expenses)).sum())


def estimate_proxy_quality(allocations: pd.DataFrame, config: dict[str, Any]) -> float:
    quality = {k: float(v.get("proxy_quality_score", 0.0)) for k, v in config["sleeves"].items()}
    common = [col for col in allocations.columns if col in quality]
    if not common:
        return 0.0
    weights = allocations[common].mean().abs()
    if weights.sum() == 0:
        return 0.0
    return float((weights * pd.Series(quality)).sum() / weights.sum())


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax().replace(0.0, np.nan)
    return float(((equity - peak) / peak).min())


def safe_div(num: float, den: float) -> float:
    if den == 0 or not np.isfinite(den):
        return float("nan")
    return float(num / den)


def stable_int(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def config_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _json_row(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {}
    return json_safe(frame.iloc[0].to_dict())


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


if __name__ == "__main__":
    main()
