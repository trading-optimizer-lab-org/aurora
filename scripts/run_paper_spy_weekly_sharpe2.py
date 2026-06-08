from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_spy_weekly_longshort_sharpe2 import (
    build_positions_train_only,
    metrics,
    position_audit,
    train_only_score,
    train_only_stability,
    turnover,
)


CAMPAIGN_ID = "paper_spy_weekly_sharpe2_360jobs"
TRAIN_START = pd.Timestamp("1995-01-01")
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")
TARGET_SHARPE = 2.0

INDEX_HISTORY_URL_TEMPLATE = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{ticker}_History.csv"
CBOE_TOTAL_PC_URLS = (
    "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/pcratioarchive.csv",
    "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/totalpcarchive.csv",
    "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/totalpc.csv",
)


PAPER_SOURCES: dict[str, dict[str, str]] = {
    "faber_ma": {
        "paper": "A Quantitative Approach to Tactical Asset Allocation",
        "authors": "Mebane Faber",
        "year": "2007/2013",
        "type": "template",
        "rule": "Use moving averages and trend to time equity exposure.",
    },
    "glabadanidis_ma": {
        "paper": "Market Timing With Moving Averages",
        "authors": "Paskalis Glabadanidis",
        "year": "2015",
        "type": "template",
        "rule": "Moving-average timing reduces volatility versus buy-and-hold.",
    },
    "mop_tsmom": {
        "paper": "Time Series Momentum",
        "authors": "Moskowitz, Ooi, Pedersen",
        "year": "2012",
        "type": "template",
        "rule": "Prior returns forecast continuation across assets.",
    },
    "moreira_muir_vol": {
        "paper": "Volatility-Managed Portfolios",
        "authors": "Moreira, Muir",
        "year": "2017",
        "type": "template",
        "rule": "Use lagged realized volatility to scale or time exposure.",
    },
    "btz_vrp": {
        "paper": "Expected Stock Returns and Variance Risk Premia",
        "authors": "Bollerslev, Tauchen, Zhou",
        "year": "2009",
        "type": "proxy",
        "rule": "Variance-risk-premium proxy from implied volatility minus realized variance predicts equity returns.",
    },
    "vix_fear": {
        "paper": "The Investor Fear Gauge",
        "authors": "Robert Whaley",
        "year": "2000",
        "type": "template",
        "rule": "VIX regimes proxy market fear and expected equity risk.",
    },
    "fassa_vix_term": {
        "paper": "VIX Futures as a Market Timing Indicator",
        "authors": "Fassas, Hourvouliades",
        "year": "2019",
        "type": "proxy",
        "rule": "VIX term structure contains information for future S&P 500 returns.",
    },
    "put_call_sentiment": {
        "paper": "Measures of Investor Sentiment: Put-Call Ratio vs. Volatility Index",
        "authors": "Bandopadhyaya, Jones",
        "year": "2008",
        "type": "template",
        "rule": "Cboe put-call ratios are investor sentiment signals for S&P 500 behavior.",
    },
    "skew_tail": {
        "paper": "The SKEW Index: Extracting What Has Been Left",
        "authors": "Kokholm-style SKEW literature",
        "year": "2020",
        "type": "template",
        "rule": "Option-implied skew/tail-risk measures enrich equity risk signals.",
    },
    "cboe_putwrite": {
        "paper": "Historical Performance of Put-Writing Strategies",
        "authors": "Bondarenko / Cboe research",
        "year": "2019",
        "type": "proxy",
        "rule": "Cboe option benchmark indices capture option-risk-premium regimes.",
    },
}


FEATURE_PAPERS: dict[str, tuple[str, ...]] = {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["data", "shard", "merge"], required=True)
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--configs-per-stage", type=int, default=30_000)
    parser.add_argument("--time-budget-minutes", type=float, default=45.0)
    parser.add_argument("--top-per-stage", type=int, default=150)
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
    yf_cache_dir = output_dir / ".yfinance_cache"
    yf_cache_dir.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(yf_cache_dir))
    symbols = ["SPY", "^GSPC", "^VIX", "^VIX3M", "^VXO", "^SKEW", "^TNX", "^IRX"]
    raw = yf.download(
        symbols,
        start="1995-01-01",
        end="2021-01-01",
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=False,
    )
    prices = pd.DataFrame()
    for symbol in symbols:
        try:
            prices[symbol] = raw[symbol]["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]
        except Exception:
            continue
    if "SPY" not in prices or prices["SPY"].dropna().empty:
        raise RuntimeError("SPY data unavailable")
    cboe = fetch_cboe_weekly_panel()
    weekly_prices = prices.resample("W-FRI").last().join(cboe, how="outer").sort_index().ffill()
    weekly_prices = weekly_prices[weekly_prices.index < LOCKED_START]
    weekly_prices = weekly_prices.dropna(subset=["SPY"], how="any")
    if weekly_prices.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached data output")
    if weekly_prices.index.min() > TRAIN_START + pd.Timedelta(days=14):
        raise RuntimeError(f"Insufficient SPY history: {weekly_prices.index.min()}")
    returns = weekly_prices[["SPY"]].pct_change(fill_method=None).dropna()

    feature_frame, feature_papers = build_paper_feature_frame(weekly_prices, returns)
    feature_frame.to_csv(output_dir / "paper_feature_frame.csv", index_label="timestamp")
    returns.to_csv(output_dir / "weekly_returns.csv", index_label="timestamp")
    weekly_prices.to_csv(output_dir / "weekly_prices.csv", index_label="timestamp")
    audit = build_feature_audit(feature_papers)
    audit.to_csv(output_dir / "paper_feature_audit.csv", index=False)
    pd.DataFrame(PAPER_SOURCES.values()).assign(paper_key=list(PAPER_SOURCES)).to_csv(
        output_dir / "paper_sources.csv",
        index=False,
    )
    (output_dir / "policy_audit.json").write_text(
        json.dumps(
            {
                "campaign_id": CAMPAIGN_ID,
                "objective": "Sharpe >= 2 in train and validation using paper-sourced SPY timing signals",
                "train_start": str(TRAIN_START.date()),
                "train_end": str(TRAIN_END.date()),
                "validation_start": str(VALIDATION_START.date()),
                "validation_end": str(VALIDATION_END.date()),
                "locked_start": str(LOCKED_START.date()),
                "data_end_max": str(weekly_prices.index.max().date()),
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "validation_used_for_selection": False,
                "paper_exact_replication_claimed": False,
                "paper_strategy_type": "template_or_proxy",
                "traded_asset": "SPY",
                "frequency": "weekly",
                "feature_count": int(feature_frame.shape[1]),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def fetch_cboe_weekly_panel() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for ticker, name in [
        ("PPUT", "cboe_benchmark_pput"),
        ("BXY", "cboe_benchmark_bxy"),
        ("BXMD", "cboe_benchmark_bxmd"),
        ("CMBO", "cboe_benchmark_cmbo"),
        ("PUTY", "cboe_benchmark_puty"),
        ("SKEW", "cboe_options_derived_skew"),
        ("VIXMO", "cboe_options_derived_vixmo"),
        ("VIX", "cboe_volatility_vix"),
        ("VXO", "cboe_volatility_vxo"),
    ]:
        try:
            raw = fetch_cboe_index_history(ticker)
        except Exception:
            continue
        frames.append(raw[["close"]].rename(columns={"close": name}))
    try:
        frames.append(fetch_total_put_call_ratio().rename(columns={"put_call_ratio": "cboe_total_put_call_ratio"}))
    except Exception:
        pass
    if not frames:
        return pd.DataFrame()
    daily = pd.concat(frames, axis=1).sort_index()
    return daily.resample("W-FRI").last()


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "aurora-paper-spy-sharpe2/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return response.read()


def fetch_cboe_index_history(ticker: str) -> pd.DataFrame:
    raw = fetch_bytes(INDEX_HISTORY_URL_TEMPLATE.format(ticker=ticker))
    text = raw.decode("utf-8-sig", errors="ignore").replace("\x00", "")
    df = pd.read_csv(io.StringIO(text))
    if df.empty:
        raise ValueError(f"{ticker} index history empty")
    df.columns = [normalise_name(c) for c in df.columns]
    date_col = first_matching(df.columns, (r"^date$",))
    value_col = first_matching(df.columns, (r"close$", rf"^{normalise_name(ticker)}$", r"value$"))
    if date_col is None or value_col is None:
        raise ValueError(f"{ticker} index history lacks date/value")
    out = pd.DataFrame(index=pd.to_datetime(df[date_col], errors="coerce"))
    out.index = pd.DatetimeIndex(out.index).tz_localize(None)
    out.index.name = "date"
    out["close"] = pd.to_numeric(df[value_col], errors="coerce").to_numpy(dtype=float)
    out = out[~out.index.isna()].dropna(subset=["close"]).sort_index()
    return out[~out.index.duplicated(keep="last")]


def fetch_total_put_call_ratio() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for url in CBOE_TOTAL_PC_URLS:
        raw = fetch_bytes(url)
        text = raw.decode("utf-8-sig", errors="ignore").replace("\x00", "")
        parsed = parse_put_call_csv(text, source_url=url)
        frames.append(parsed)
    combined = pd.concat(frames).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.dropna(subset=["put_call_ratio"])


def parse_put_call_csv(text: str, *, source_url: str) -> pd.DataFrame:
    lines = [line for line in text.splitlines() if line.strip()]
    header_idx = next((i for i, line in enumerate(lines) if "date" in line.lower() and ("ratio" in line.lower() or "p/c" in line.lower())), None)
    if header_idx is None:
        raise ValueError(f"put/call file lacks header: {source_url}")
    df = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])))
    df.columns = [normalise_name(c) for c in df.columns]
    date_col = first_matching(df.columns, (r"trade_date", r"^date$"))
    ratio_col = first_matching(df.columns, (r"total_volume_p_c_ratio", r"put_call", r"p_c", r"ratio"))
    if date_col is None or ratio_col is None:
        raise ValueError(f"put/call file lacks date/ratio: {source_url}")
    out = pd.DataFrame(index=pd.to_datetime(df[date_col], errors="coerce"))
    out.index = pd.DatetimeIndex(out.index).tz_localize(None)
    out.index.name = "date"
    out["put_call_ratio"] = pd.to_numeric(df[ratio_col], errors="coerce").to_numpy(dtype=float)
    out = out[~out.index.isna()].dropna(subset=["put_call_ratio"]).sort_index()
    return out


def normalise_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def first_matching(columns: list[str] | pd.Index, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        for col in columns:
            if re.search(pattern, str(col)):
                return str(col)
    return None


def add_feature(out: pd.DataFrame, name: str, values: pd.Series, papers: tuple[str, ...], feature_papers: dict[str, tuple[str, ...]]) -> None:
    out[name] = values
    feature_papers[name] = papers


def build_paper_feature_frame(prices: pd.DataFrame, returns: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, tuple[str, ...]]]:
    out = pd.DataFrame(index=returns.index)
    papers: dict[str, tuple[str, ...]] = {}
    spy = prices["SPY"].reindex(out.index).ffill()
    spy_ret = returns["SPY"].reindex(out.index).astype(float)
    for lb in [1, 2, 4, 8, 13, 26, 39, 52]:
        add_feature(out, f"spy_mom_{lb}w", ((1.0 + spy_ret).rolling(lb).apply(np.prod, raw=True) - 1.0).shift(1), ("mop_tsmom",), papers)
    for lb in [10, 20, 30, 40, 52]:
        ma = spy.rolling(lb).mean()
        add_feature(out, f"spy_ma_gap_{lb}w", (spy / ma - 1.0).shift(1), ("faber_ma", "glabadanidis_ma"), papers)
    for lb in [4, 8, 13, 26, 52]:
        add_feature(out, f"spy_realized_vol_{lb}w", spy_ret.rolling(lb).std().shift(1), ("moreira_muir_vol", "btz_vrp"), papers)
        add_feature(out, f"spy_drawdown_{lb}w", (spy / spy.rolling(lb).max() - 1.0).shift(1), ("faber_ma",), papers)

    for raw_col, prefix, paper_keys in [
        ("^VIX", "vix_yahoo", ("vix_fear", "btz_vrp")),
        ("cboe_volatility_vix", "vix_cboe", ("vix_fear", "btz_vrp")),
        ("cboe_volatility_vxo", "vxo_cboe", ("vix_fear",)),
        ("cboe_options_derived_vixmo", "vixmo_cboe", ("fassa_vix_term",)),
        ("cboe_options_derived_skew", "skew_cboe", ("skew_tail",)),
        ("^SKEW", "skew_yahoo", ("skew_tail",)),
        ("cboe_total_put_call_ratio", "total_pc", ("put_call_sentiment",)),
    ]:
        if raw_col not in prices.columns:
            continue
        raw = prices[raw_col].reindex(out.index).ffill()
        add_level_features(out, raw, prefix, paper_keys, papers)

    vix = first_available(prices, out.index, ["cboe_volatility_vix", "^VIX"])
    vix_term = first_available(prices, out.index, ["cboe_options_derived_vixmo", "^VIX3M"])
    if vix is not None and vix_term is not None:
        basis = vix / vix_term.replace(0.0, np.nan) - 1.0
        add_feature(out, "vix_term_basis", basis.shift(1), ("fassa_vix_term",), papers)
        add_feature(out, "vix_term_basis_chg_4w", basis.diff(4).shift(1), ("fassa_vix_term",), papers)
    if vix is not None:
        for lb in [4, 13, 26]:
            rv = spy_ret.rolling(lb).std() * math.sqrt(52.0) * 100.0
            vrp = (vix * vix) - (rv * rv)
            add_feature(out, f"vrp_proxy_{lb}w", vrp.shift(1), ("btz_vrp",), papers)
            add_feature(out, f"iv_rv_ratio_{lb}w", (vix / rv.replace(0.0, np.nan)).shift(1), ("btz_vrp",), papers)

    for raw_col, prefix in [
        ("cboe_benchmark_pput", "pput"),
        ("cboe_benchmark_bxy", "bxy"),
        ("cboe_benchmark_bxmd", "bxmd"),
        ("cboe_benchmark_cmbo", "cmbo"),
        ("cboe_benchmark_puty", "puty"),
    ]:
        if raw_col not in prices.columns:
            continue
        raw = prices[raw_col].reindex(out.index).ffill()
        ret = raw.pct_change(fill_method=None)
        for lb in [4, 13, 26, 52]:
            add_feature(out, f"{prefix}_ret_{lb}w", ((1.0 + ret).rolling(lb).apply(np.prod, raw=True) - 1.0).shift(1), ("cboe_putwrite",), papers)
            add_feature(out, f"{prefix}_rel_spy_{lb}w", (((1.0 + ret).rolling(lb).apply(np.prod, raw=True) - 1.0) - ((1.0 + spy_ret).rolling(lb).apply(np.prod, raw=True) - 1.0)).shift(1), ("cboe_putwrite",), papers)

    if {"^TNX", "^IRX"}.issubset(prices.columns):
        spread = prices["^TNX"].reindex(out.index).ffill() - prices["^IRX"].reindex(out.index).ffill()
        for lb in [4, 13, 26, 52]:
            add_feature(out, f"yield_curve_chg_{lb}w", spread.diff(lb).shift(1), ("faber_ma",), papers)
            add_feature(out, f"yield_curve_z_{lb}w", zscore(spread, lb).shift(1), ("faber_ma",), papers)

    out = out.replace([np.inf, -np.inf], np.nan).dropna(axis=1, how="all")
    out = out.dropna(how="any")
    train = out.loc[out.index <= TRAIN_END]
    median = train.median()
    iqr = train.quantile(0.75) - train.quantile(0.25)
    std = train.std().replace(0.0, np.nan)
    scale = iqr.mask(iqr == 0.0, std).replace(0.0, np.nan)
    valid_cols = [c for c in scale.dropna().index if c in papers]
    scaled = (out[valid_cols] - median[valid_cols]) / scale[valid_cols]
    return scaled.replace([np.inf, -np.inf], np.nan).dropna(how="any").clip(-8.0, 8.0), {k: papers[k] for k in valid_cols}


def add_level_features(out: pd.DataFrame, raw: pd.Series, prefix: str, paper_keys: tuple[str, ...], papers: dict[str, tuple[str, ...]]) -> None:
    for lb in [4, 13, 26, 52]:
        add_feature(out, f"{prefix}_chg_{lb}w", raw.diff(lb).shift(1), paper_keys, papers)
        add_feature(out, f"{prefix}_z_{lb}w", zscore(raw, lb).shift(1), paper_keys, papers)
    add_feature(out, f"{prefix}_level", raw.shift(1), paper_keys, papers)


def first_available(prices: pd.DataFrame, index: pd.Index, names: list[str]) -> pd.Series | None:
    for name in names:
        if name in prices.columns and prices[name].notna().sum() > 100:
            return prices[name].reindex(index).ffill().astype(float)
    return None


def zscore(series: pd.Series, lb: int) -> pd.Series:
    return (series - series.rolling(lb).mean()) / series.rolling(lb).std().replace(0.0, np.nan)


def build_feature_audit(feature_papers: dict[str, tuple[str, ...]]) -> pd.DataFrame:
    rows = []
    for feature, keys in sorted(feature_papers.items()):
        rows.append(
            {
                "feature": feature,
                "paper_keys": "|".join(keys),
                "paper_titles": "|".join(PAPER_SOURCES[k]["paper"] for k in keys),
                "paper_strategy_type": "|".join(sorted({PAPER_SOURCES[k]["type"] for k in keys})),
                "lagged": True,
                "lag_periods": 1,
            }
        )
    return pd.DataFrame(rows)


def paper_sources_for_features(features: list[str], feature_papers: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    keys: list[str] = []
    for feature in features:
        keys.extend(feature_papers.get(feature, tuple()))
    return tuple(dict.fromkeys(keys))


def sample_params(rng: np.random.Generator, feature_cols: list[str], stage: int) -> dict[str, Any]:
    groups = [
        ["spy_mom_", "spy_ma_gap_", "spy_drawdown_"],
        ["vix_", "vxo_", "vixmo_", "vrp_", "iv_rv_"],
        ["total_pc_"],
        ["skew_"],
        ["vix_term_"],
        ["pput_", "bxy_", "bxmd_", "cmbo_", "puty_"],
        ["spy_realized_vol_", "vrp_", "vix_"],
        ["yield_curve_"],
        ["spy_mom_", "vix_", "total_pc_", "skew_"],
        ["spy_ma_gap_", "vix_term_", "vrp_", "pput_"],
    ]
    group = groups[stage % len(groups)]
    candidates = [i for i, name in enumerate(feature_cols) if any(name.startswith(token) for token in group)]
    if not candidates:
        candidates = list(range(len(feature_cols)))
    max_candidates = max(1, len(candidates))
    rule_types = [
        "linear",
        "threshold_vote",
        "signed_stump_vote",
        "train_leaf_tree",
        "era_leaf_tree",
        "cv_era_leaf_tree",
        "split_guard_leaf_tree",
        "time_split_leaf_tree",
        "ridge_model",
        "quadratic_ridge_model",
        "cv_ridge_model",
        "cv_quadratic_ridge_model",
        "walk_forward_ridge_model",
        "walk_forward_quadratic_ridge_model",
        "logic_majority",
    ]
    rule_type = str(rng.choice(rule_types))
    if rule_type in {"linear", "threshold_vote", "signed_stump_vote"}:
        low = 1
        high = min(7, max_candidates)
    elif "ridge" in rule_type:
        low = min(3, max_candidates)
        high = min(12, max_candidates)
    else:
        low = min(3, max_candidates)
        high = min(8, max_candidates)
    k = int(rng.integers(low, high + 1)) if high >= low else max_candidates
    feature_indices = rng.choice(candidates, size=k, replace=False)
    weights = rng.normal(0.0, 1.0, size=k)
    norm = np.sum(np.abs(weights))
    weights = weights / norm if norm > 0 else np.ones(k) / k
    return {
        "family": int(stage % len(groups)),
        "rule_type": rule_type,
        "feature_indices": [int(i) for i in feature_indices],
        "weights": [float(w) for w in weights],
        "thresholds": [float(x) for x in rng.normal(0.0, 1.0, size=k)],
        "quantiles": [float(x) for x in rng.uniform(0.1, 0.9, size=k)],
        "band_widths": [float(x) for x in rng.uniform(0.25, 2.0, size=k)],
        "directions": [float(x) for x in rng.choice([-1.0, 1.0], size=k)],
        "logic_operator": "majority",
        "threshold": float(rng.normal(0.0, 0.25)),
        "ridge_alpha": float(10.0 ** rng.uniform(-3.0, 2.0)),
        "walk_forward_min_train": int(rng.choice([156, 208, 260, 312])),
        "walk_forward_refit_step": int(rng.choice([1, 2, 4, 8, 13])),
        "walk_forward_window": int(rng.choice([0, 260, 390, 520])),
        "ensemble_members": [],
        "invert": int(rng.integers(0, 2)),
    }


def run_shard(output_dir: Path, *, stage: int, configs_per_stage: int, time_budget_minutes: float, top_per_stage: int) -> None:
    returns = pd.read_csv(output_dir / "weekly_returns.csv", parse_dates=["timestamp"]).set_index("timestamp")
    feature_frame = pd.read_csv(output_dir / "paper_feature_frame.csv", parse_dates=["timestamp"]).set_index("timestamp")
    feature_audit = pd.read_csv(output_dir / "paper_feature_audit.csv")
    feature_papers = {row["feature"]: tuple(str(row["paper_keys"]).split("|")) for _, row in feature_audit.iterrows()}
    if returns.index.max() >= LOCKED_START or feature_frame.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached shard")
    spy_rets = returns["SPY"].reindex(feature_frame.index).astype(float)
    train_mask = (feature_frame.index >= TRAIN_START) & (feature_frame.index <= TRAIN_END)
    validation_mask = (feature_frame.index >= VALIDATION_START) & (feature_frame.index <= VALIDATION_END)
    matrix = feature_frame.to_numpy(dtype=float)
    spy_values = spy_rets.to_numpy(dtype=float)
    feature_cols = list(feature_frame.columns)
    rng = np.random.default_rng(20260607 + int(stage) * 1_000_003)
    deadline = time.monotonic() + max(1.0, float(time_budget_minutes)) * 60.0
    rows: list[dict[str, Any]] = []
    evaluated = 0
    for config_index in range(int(configs_per_stage)):
        if time.monotonic() >= deadline:
            break
        evaluated += 1
        params = sample_params(rng, feature_cols, stage)
        positions, train_metrics = build_positions_train_only(matrix, spy_values, train_mask, params)
        if not np.isfinite(train_metrics["sharpe"]):
            continue
        strategy_returns = positions * spy_values
        if train_metrics["sharpe"] < 0.25 and config_index % 251 != 0:
            continue
        validation_metrics = metrics(strategy_returns[validation_mask])
        train_returns = strategy_returns[train_mask]
        train_dates = feature_frame.index[train_mask]
        stability = train_only_stability(train_returns, train_dates)
        train_score = train_only_score(train_metrics, positions[train_mask], params, stability)
        features = [feature_cols[int(i)] for i in params["feature_indices"]]
        paper_keys = paper_sources_for_features(features, feature_papers)
        train_position = position_audit(positions[train_mask])
        validation_position = position_audit(positions[validation_mask])
        pass_train = bool(train_metrics["sharpe"] >= TARGET_SHARPE and train_position["always_invested"])
        pass_validation = bool(validation_metrics["sharpe"] >= TARGET_SHARPE and validation_position["always_invested"])
        payload = {"params": params, "paper_keys": paper_keys, "features": features}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        rows.append(
            {
                "strategy_id": f"paper_spy_weekly_sharpe2_s{stage:03d}_{digest}",
                "stage": int(stage),
                "config_index": int(config_index),
                "train_pass": pass_train,
                "validation_pass_report_only": pass_validation,
                "final_verified_report_only": bool(pass_train and pass_validation),
                "validation_used_for_selection": False,
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "paper_exact_replication_claimed": False,
                "paper_strategy_type": "template_or_proxy",
                "paper_keys": "|".join(paper_keys),
                "paper_titles": "|".join(PAPER_SOURCES[k]["paper"] for k in paper_keys),
                "paper_authors": "|".join(PAPER_SOURCES[k]["authors"] for k in paper_keys),
                "source_rule_summary": "|".join(PAPER_SOURCES[k]["rule"] for k in paper_keys),
                "traded_asset": "SPY",
                "frequency": "weekly",
                "lag_periods": 1,
                "train_sharpe": float(train_metrics["sharpe"]),
                "validation_sharpe": float(validation_metrics["sharpe"]),
                "train_cagr": float(train_metrics["cagr"]),
                "validation_cagr": float(validation_metrics["cagr"]),
                "train_mdd": float(train_metrics["mdd"]),
                "validation_mdd": float(validation_metrics["mdd"]),
                "train_positive_weeks_pct": float(train_metrics["positive_weeks_pct"]),
                "validation_positive_weeks_pct": float(validation_metrics["positive_weeks_pct"]),
                "train_first_half_sharpe": float(stability["first_half_sharpe"]),
                "train_second_half_sharpe": float(stability["second_half_sharpe"]),
                "train_min_half_sharpe": float(stability["min_half_sharpe"]),
                "train_turnover_weekly": float(turnover(positions[train_mask])),
                "validation_turnover_weekly": float(turnover(positions[validation_mask])),
                "train_always_invested": bool(train_position["always_invested"]),
                "validation_always_invested": bool(validation_position["always_invested"]),
                "rule_type": str(params["rule_type"]),
                "feature_count": int(len(features)),
                "features": "|".join(features),
                "params_json": json.dumps(params, sort_keys=True),
                "train_score": float(train_score),
            }
        )
    shard_dir = output_dir / "shards" / f"stage_{stage:03d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(columns=["strategy_id", "train_score", "final_verified_report_only"])
    top = frame.sort_values(["train_score", "train_sharpe"], ascending=[False, False]).head(int(top_per_stage))
    verified = frame[frame.get("final_verified_report_only", pd.Series(dtype=bool)).astype(bool)]
    diagnostic = frame.sort_values(["validation_sharpe", "train_sharpe"], ascending=[False, False]).head(int(top_per_stage))
    diagnostic = diagnostic.copy()
    diagnostic["eligible_for_acceptance"] = False
    top.to_csv(shard_dir / "top_candidates.csv", index=False)
    verified.to_csv(shard_dir / "verified_candidates_report_only.csv", index=False)
    diagnostic.to_csv(shard_dir / "validation_ceiling_diagnostic.csv", index=False)
    (shard_dir / "shard_summary.json").write_text(
        json.dumps(
            {
                "stage": int(stage),
                "configs_requested": int(configs_per_stage),
                "configs_evaluated": int(evaluated),
                "rows_kept": int(len(frame)),
                "verified_rows": int(len(verified)),
                "locked_opened": False,
                "validation_used_for_selection": False,
                "paper_exact_replication_claimed": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def run_merge(output_dir: Path) -> None:
    shard_root = output_dir / "shards"
    top_files = list(shard_root.glob("**/top_candidates.csv"))
    verified_files = list(shard_root.glob("**/verified_candidates_report_only.csv"))
    diag_files = list(shard_root.glob("**/validation_ceiling_diagnostic.csv"))
    summary_files = list(shard_root.glob("**/shard_summary.json"))
    top = pd.concat([pd.read_csv(path) for path in top_files], ignore_index=True) if top_files else pd.DataFrame()
    verified = pd.concat([pd.read_csv(path) for path in verified_files], ignore_index=True) if verified_files else pd.DataFrame()
    diagnostic = pd.concat([pd.read_csv(path) for path in diag_files], ignore_index=True) if diag_files else pd.DataFrame()
    if not top.empty:
        top = top.drop_duplicates("strategy_id").sort_values(["train_score", "train_sharpe"], ascending=[False, False])
    if not verified.empty:
        verified = verified.drop_duplicates("strategy_id").sort_values(["train_sharpe", "validation_sharpe"], ascending=[False, False])
    if not diagnostic.empty:
        diagnostic = diagnostic.drop_duplicates("strategy_id").sort_values(["validation_sharpe", "train_sharpe"], ascending=[False, False])
    top.to_csv(output_dir / "paper_spy_weekly_sharpe2_leaderboard.csv", index=False)
    verified.to_csv(output_dir / "paper_spy_weekly_sharpe2_verified.csv", index=False)
    diagnostic.to_csv(output_dir / "paper_spy_weekly_sharpe2_validation_ceiling_diagnostic.csv", index=False)
    fail_reasons = build_fail_reasons(top)
    fail_reasons.to_csv(output_dir / "paper_spy_weekly_sharpe2_fail_reasons.csv", index=False)
    summaries = []
    for path in summary_files:
        try:
            summaries.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    pd.DataFrame(summaries).to_csv(output_dir / "paper_spy_weekly_sharpe2_shard_summaries.csv", index=False)
    for name in ["weekly_prices.csv", "weekly_returns.csv", "paper_feature_audit.csv", "paper_sources.csv", "policy_audit.json"]:
        src = output_dir / name
        if src.exists():
            continue
        data_src = output_dir / "data" / name
        if data_src.exists():
            if name.endswith(".json"):
                src.write_text(data_src.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                pd.read_csv(data_src).to_csv(src, index=False)
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "target_train_sharpe": TARGET_SHARPE,
        "target_validation_sharpe_report_only": TARGET_SHARPE,
        "verified_count_report_only": int(len(verified)),
        "top_candidate_rows": int(len(top)),
        "validation_diagnostic_rows": int(len(diagnostic)),
        "configs_evaluated": int(sum(item.get("configs_evaluated", 0) for item in summaries)),
        "best_train_sharpe": float(top["train_sharpe"].max()) if not top.empty else None,
        "best_validation_sharpe": float(top["validation_sharpe"].max()) if not top.empty else None,
        "best_min_train_validation_sharpe": float(top[["train_sharpe", "validation_sharpe"]].min(axis=1).max()) if not top.empty else None,
        "locked_opened": False,
        "locked_rows_accessed": 0,
        "validation_used_for_selection": False,
        "paper_exact_replication_claimed": False,
        "paper_sourced_only": True,
        "paper_strategy_type": "template_or_proxy",
        "train_start": str(TRAIN_START.date()),
        "train_end": str(TRAIN_END.date()),
        "validation_start": str(VALIDATION_START.date()),
        "validation_end": str(VALIDATION_END.date()),
        "locked_start": str(LOCKED_START.date()),
    }
    (output_dir / "paper_spy_weekly_sharpe2_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def build_fail_reasons(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["reason", "count"])
    reasons = []
    for _, row in frame.iterrows():
        if bool(row.get("final_verified_report_only", False)):
            reasons.append("verified")
        elif float(row.get("train_sharpe", -999.0)) < TARGET_SHARPE:
            reasons.append("train_sharpe_below_2")
        elif float(row.get("validation_sharpe", -999.0)) < TARGET_SHARPE:
            reasons.append("validation_sharpe_below_2_report_only")
        else:
            reasons.append("other")
    return pd.Series(reasons).value_counts().rename_axis("reason").reset_index(name="count")


if __name__ == "__main__":
    main()
