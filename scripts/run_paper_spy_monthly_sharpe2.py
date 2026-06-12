from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import run_paper_spy_weekly_sharpe2 as weekly


CAMPAIGN_ID = "paper_spy_monthly_sharpe2_360jobs"
TRAIN_START = pd.Timestamp("1995-01-01")
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")
TARGET_SHARPE = 2.0
PPY = 12


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["data", "shard", "merge"], required=True)
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--configs-per-stage", type=int, default=2_000_000)
    parser.add_argument("--time-budget-minutes", type=float, default=2.0)
    parser.add_argument("--top-per-stage", type=int, default=120)
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
    cache_dir = output_dir / ".yfinance_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(cache_dir))
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
    cboe = weekly.fetch_cboe_weekly_panel()
    monthly_prices = prices.resample("ME").last().join(cboe.resample("ME").last(), how="outer").sort_index().ffill()
    monthly_prices = monthly_prices[monthly_prices.index < LOCKED_START].dropna(subset=["SPY"])
    if monthly_prices.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached monthly data output")
    monthly_returns = monthly_prices[["SPY"]].pct_change(fill_method=None).dropna()
    features, feature_papers = build_monthly_features(monthly_prices, monthly_returns)
    common = features.index.intersection(monthly_returns.index)
    features = features.reindex(common)
    monthly_returns = monthly_returns.reindex(common)
    if features.index.max() >= LOCKED_START or monthly_returns.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached monthly aligned output")
    features.to_csv(output_dir / "paper_monthly_feature_frame.csv", index_label="timestamp")
    monthly_returns.to_csv(output_dir / "monthly_returns.csv", index_label="timestamp")
    monthly_prices.to_csv(output_dir / "monthly_prices.csv", index_label="timestamp")
    build_feature_audit(feature_papers).to_csv(output_dir / "paper_feature_audit.csv", index=False)
    pd.DataFrame(weekly.PAPER_SOURCES.values()).assign(paper_key=list(weekly.PAPER_SOURCES)).to_csv(
        output_dir / "paper_sources.csv",
        index=False,
    )
    (output_dir / "policy_audit.json").write_text(
        json.dumps(
            {
                "campaign_id": CAMPAIGN_ID,
                "objective": "Sharpe >= 2 in train and validation using paper-sourced SPY monthly timing signals",
                "train_start": str(TRAIN_START.date()),
                "train_end": str(TRAIN_END.date()),
                "validation_start": str(VALIDATION_START.date()),
                "validation_end": str(VALIDATION_END.date()),
                "locked_start": str(LOCKED_START.date()),
                "data_end_max": str(monthly_returns.index.max().date()),
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "validation_used_for_selection": False,
                "paper_exact_replication_claimed": False,
                "paper_sourced_only": True,
                "paper_strategy_type": "template_or_proxy",
                "traded_asset": "SPY",
                "frequency": "monthly",
                "lag_periods": 1,
                "feature_count": int(features.shape[1]),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def add_feature(out: pd.DataFrame, name: str, values: pd.Series, papers: tuple[str, ...], feature_papers: dict[str, tuple[str, ...]]) -> None:
    out[name] = values
    feature_papers[name] = papers


def zscore(series: pd.Series, lb: int) -> pd.Series:
    return (series - series.rolling(lb).mean()) / series.rolling(lb).std().replace(0.0, np.nan)


def first_available(prices: pd.DataFrame, index: pd.Index, names: list[str]) -> pd.Series | None:
    for name in names:
        if name in prices.columns and prices[name].notna().sum() > 24:
            return prices[name].reindex(index).ffill().astype(float)
    return None


def add_level_features(out: pd.DataFrame, raw: pd.Series, prefix: str, paper_keys: tuple[str, ...], papers: dict[str, tuple[str, ...]]) -> None:
    for lb in [3, 6, 12, 24]:
        add_feature(out, f"{prefix}_chg_{lb}m", raw.diff(lb).shift(1), paper_keys, papers)
        add_feature(out, f"{prefix}_z_{lb}m", zscore(raw, lb).shift(1), paper_keys, papers)
    add_feature(out, f"{prefix}_level", raw.shift(1), paper_keys, papers)


def build_monthly_features(prices: pd.DataFrame, returns: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, tuple[str, ...]]]:
    out = pd.DataFrame(index=returns.index)
    papers: dict[str, tuple[str, ...]] = {}
    spy = prices["SPY"].reindex(out.index).ffill()
    spy_ret = returns["SPY"].reindex(out.index).astype(float)
    for lb in [1, 2, 3, 6, 9, 12, 24]:
        add_feature(out, f"spy_mom_{lb}m", ((1.0 + spy_ret).rolling(lb).apply(np.prod, raw=True) - 1.0).shift(1), ("mop_tsmom",), papers)
    for lb in [3, 6, 10, 12, 18, 24]:
        ma = spy.rolling(lb).mean()
        add_feature(out, f"spy_ma_gap_{lb}m", (spy / ma - 1.0).shift(1), ("faber_ma", "glabadanidis_ma"), papers)
    for lb in [3, 6, 12, 24]:
        add_feature(out, f"spy_realized_vol_{lb}m", spy_ret.rolling(lb).std().shift(1), ("moreira_muir_vol", "btz_vrp"), papers)
        add_feature(out, f"spy_drawdown_{lb}m", (spy / spy.rolling(lb).max() - 1.0).shift(1), ("faber_ma",), papers)

    for raw_col, prefix, paper_keys in [
        ("^VIX", "vix_yahoo", ("vix_fear", "btz_vrp")),
        ("cboe_volatility_vix", "vix_cboe", ("vix_fear", "btz_vrp")),
        ("cboe_volatility_vxo", "vxo_cboe", ("vix_fear",)),
        ("cboe_options_derived_vixmo", "vixmo_cboe", ("fassa_vix_term",)),
        ("cboe_options_derived_skew", "skew_cboe", ("skew_tail",)),
        ("^SKEW", "skew_yahoo", ("skew_tail",)),
        ("cboe_total_put_call_ratio", "total_pc", ("put_call_sentiment",)),
    ]:
        if raw_col in prices.columns:
            add_level_features(out, prices[raw_col].reindex(out.index).ffill(), prefix, paper_keys, papers)

    vix = first_available(prices, out.index, ["cboe_volatility_vix", "^VIX"])
    vix_term = first_available(prices, out.index, ["cboe_options_derived_vixmo", "^VIX3M"])
    if vix is not None and vix_term is not None:
        basis = vix / vix_term.replace(0.0, np.nan) - 1.0
        add_feature(out, "vix_term_basis", basis.shift(1), ("fassa_vix_term",), papers)
        add_feature(out, "vix_term_basis_chg_3m", basis.diff(3).shift(1), ("fassa_vix_term",), papers)
    if vix is not None:
        for lb in [3, 6, 12]:
            rv = spy_ret.rolling(lb).std() * math.sqrt(12.0) * 100.0
            vrp = (vix * vix) - (rv * rv)
            add_feature(out, f"vrp_proxy_{lb}m", vrp.shift(1), ("btz_vrp",), papers)
            add_feature(out, f"iv_rv_ratio_{lb}m", (vix / rv.replace(0.0, np.nan)).shift(1), ("btz_vrp",), papers)

    for raw_col, prefix in [
        ("cboe_benchmark_pput", "pput"),
        ("cboe_benchmark_bxy", "bxy"),
        ("cboe_benchmark_bxmd", "bxmd"),
        ("cboe_benchmark_cmbo", "cmbo"),
        ("cboe_benchmark_puty", "puty"),
    ]:
        if raw_col not in prices.columns:
            continue
        ret = prices[raw_col].reindex(out.index).ffill().pct_change(fill_method=None)
        for lb in [3, 6, 12, 24]:
            bench = (1.0 + ret).rolling(lb).apply(np.prod, raw=True) - 1.0
            spy_run = (1.0 + spy_ret).rolling(lb).apply(np.prod, raw=True) - 1.0
            add_feature(out, f"{prefix}_ret_{lb}m", bench.shift(1), ("cboe_putwrite",), papers)
            add_feature(out, f"{prefix}_rel_spy_{lb}m", (bench - spy_run).shift(1), ("cboe_putwrite",), papers)

    if {"^TNX", "^IRX"}.issubset(prices.columns):
        spread = prices["^TNX"].reindex(out.index).ffill() - prices["^IRX"].reindex(out.index).ffill()
        for lb in [3, 6, 12, 24]:
            add_feature(out, f"yield_curve_chg_{lb}m", spread.diff(lb).shift(1), ("faber_ma",), papers)
            add_feature(out, f"yield_curve_z_{lb}m", zscore(spread, lb).shift(1), ("faber_ma",), papers)

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


def build_feature_audit(feature_papers: dict[str, tuple[str, ...]]) -> pd.DataFrame:
    rows = []
    for feature, keys in sorted(feature_papers.items()):
        rows.append(
            {
                "feature": feature,
                "paper_keys": "|".join(keys),
                "paper_titles": "|".join(weekly.PAPER_SOURCES[k]["paper"] for k in keys),
            }
        )
    return pd.DataFrame(rows)


def sample_params(rng: np.random.Generator, feature_cols: list[str], stage: int) -> dict[str, Any]:
    groups = [
        ["spy_mom_", "spy_ma_gap_"],
        ["vix_", "vxo_", "vixmo_", "vix_term_"],
        ["total_pc_", "skew_"],
        ["pput_", "bxy_", "bxmd_", "cmbo_", "puty_"],
        ["vrp_", "iv_rv_", "spy_realized_vol_"],
        ["yield_curve_", "spy_drawdown_"],
        ["spy_mom_", "vix_", "total_pc_"],
        ["skew_", "vix_", "spy_ma_gap_"],
    ]
    group = groups[stage % len(groups)]
    candidates = [i for i, name in enumerate(feature_cols) if any(name.startswith(token) for token in group)]
    if not candidates:
        candidates = list(range(len(feature_cols)))
    max_candidates = max(1, len(candidates))
    rule_type = str(rng.choice(["linear", "threshold_vote", "signed_stump_vote"], p=[0.45, 0.30, 0.25]))
    high = min(7 if rule_type == "linear" else 5, max_candidates)
    low = min(1, high)
    k = int(rng.integers(low, high + 1))
    feature_indices = rng.choice(candidates, size=k, replace=False)
    weights = rng.normal(0.0, 1.0, size=k)
    norm = np.sum(np.abs(weights))
    weights = weights / norm if norm > 0 else np.ones(k) / k
    return {
        "family": int(stage % len(groups)),
        "rule_type": rule_type,
        "feature_indices": [int(i) for i in feature_indices],
        "weights": [float(w) for w in weights],
        "directions": [float(x) for x in rng.choice([-1.0, 1.0], size=k)],
        "quantiles": [float(x) for x in rng.uniform(0.15, 0.85, size=k)],
        "threshold": float(rng.normal(0.0, 0.15)),
        "invert": int(rng.integers(0, 2)),
    }


def raw_score(matrix: np.ndarray, params: dict[str, Any], train_matrix: np.ndarray) -> np.ndarray:
    idx = np.asarray(params["feature_indices"], dtype=int)
    selected = matrix[:, idx]
    train_selected = train_matrix[:, idx]
    rule = str(params["rule_type"])
    if rule == "threshold_vote":
        votes = []
        for j, q, direction in zip(range(len(idx)), params["quantiles"], params["directions"], strict=False):
            threshold = float(np.nanquantile(train_selected[:, j], float(q)))
            votes.append(np.where(float(direction) * (selected[:, j] - threshold) >= 0.0, 1.0, -1.0))
        return np.mean(np.vstack(votes), axis=0)
    if rule == "signed_stump_vote":
        votes = []
        for j, direction in zip(range(len(idx)), params["directions"], strict=False):
            threshold = float(np.nanmedian(train_selected[:, j]))
            votes.append(np.where(float(direction) * selected[:, j] >= float(direction) * threshold, 1.0, -1.0))
        return np.mean(np.vstack(votes), axis=0)
    weights = np.asarray(params["weights"], dtype=float)
    return selected @ weights


def fit_positions(matrix: np.ndarray, spy_values: np.ndarray, train_mask: np.ndarray, params: dict[str, Any]) -> tuple[np.ndarray, dict[str, float]]:
    score = raw_score(matrix, params, matrix[train_mask])
    train_score = score[train_mask]
    train_rets = spy_values[train_mask]
    qs = np.linspace(0.1, 0.9, 17)
    thresholds = [float(params.get("threshold", 0.0))]
    thresholds.extend(float(np.nanquantile(train_score, q)) for q in qs if np.isfinite(np.nanquantile(train_score, q)))
    best_pos: np.ndarray | None = None
    best_metrics: dict[str, float] | None = None
    best_sharpe = -999.0
    for threshold in thresholds:
        for invert in [0, 1]:
            pos = np.where(score >= threshold, 1.0, -1.0)
            if invert:
                pos = -pos
            long_pct = float(np.mean(pos[train_mask] > 0.0))
            if long_pct < 0.05 or long_pct > 0.95:
                continue
            current = metrics(pos[train_mask] * train_rets)
            sharpe = float(current["sharpe"]) if np.isfinite(current["sharpe"]) else -999.0
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_pos = pos
                best_metrics = current
                params["fit_threshold"] = float(threshold)
                params["fit_invert"] = int(invert)
    if best_pos is None or best_metrics is None:
        best_pos = np.ones_like(spy_values)
        best_metrics = metrics(best_pos[train_mask] * train_rets)
    return best_pos, best_metrics


def metrics(returns: np.ndarray) -> dict[str, float]:
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 3:
        return {"sharpe": np.nan, "cagr": np.nan, "mdd": np.nan, "positive_periods_pct": np.nan}
    std = float(np.std(values, ddof=1))
    sharpe = float(np.mean(values) / std * math.sqrt(PPY)) if std > 0 else np.nan
    nav = np.cumprod(1.0 + values)
    years = len(values) / PPY
    cagr = float(nav[-1] ** (1.0 / years) - 1.0) if years > 0 and nav[-1] > 0 else np.nan
    mdd = float(np.min(nav / np.maximum.accumulate(nav) - 1.0))
    return {"sharpe": sharpe, "cagr": cagr, "mdd": mdd, "positive_periods_pct": float(np.mean(values > 0.0))}


def turnover(positions: np.ndarray) -> float:
    if len(positions) < 2:
        return 0.0
    return float(np.mean(np.abs(np.diff(positions)) > 0.0))


def run_shard(output_dir: Path, *, stage: int, configs_per_stage: int, time_budget_minutes: float, top_per_stage: int) -> None:
    returns = pd.read_csv(output_dir / "monthly_returns.csv", parse_dates=["timestamp"]).set_index("timestamp")
    feature_frame = pd.read_csv(output_dir / "paper_monthly_feature_frame.csv", parse_dates=["timestamp"]).set_index("timestamp")
    audit = pd.read_csv(output_dir / "paper_feature_audit.csv")
    feature_papers = {row["feature"]: tuple(str(row["paper_keys"]).split("|")) for _, row in audit.iterrows()}
    if returns.index.max() >= LOCKED_START or feature_frame.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached monthly shard")
    spy_values = returns["SPY"].reindex(feature_frame.index).astype(float).to_numpy()
    train_mask = np.asarray((feature_frame.index >= TRAIN_START) & (feature_frame.index <= TRAIN_END), dtype=bool)
    validation_mask = np.asarray((feature_frame.index >= VALIDATION_START) & (feature_frame.index <= VALIDATION_END), dtype=bool)
    matrix = feature_frame.to_numpy(dtype=float)
    feature_cols = list(feature_frame.columns)
    rng = np.random.default_rng(20260608 + int(stage) * 1_000_003)
    deadline = time.monotonic() + max(0.2, float(time_budget_minutes)) * 60.0
    rows: list[dict[str, Any]] = []
    evaluated = 0
    for config_index in range(int(configs_per_stage)):
        if time.monotonic() >= deadline:
            break
        evaluated += 1
        params = sample_params(rng, feature_cols, stage)
        positions, train_metrics = fit_positions(matrix, spy_values, train_mask, params)
        if not np.isfinite(train_metrics["sharpe"]):
            continue
        strategy_returns = positions * spy_values
        validation_metrics = metrics(strategy_returns[validation_mask])
        features = [feature_cols[int(i)] for i in params["feature_indices"]]
        paper_keys = paper_sources_for_features(features, feature_papers)
        pass_train = bool(train_metrics["sharpe"] >= TARGET_SHARPE)
        pass_validation = bool(validation_metrics["sharpe"] >= TARGET_SHARPE)
        payload = {"params": params, "features": features, "frequency": "monthly"}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        row = {
            "strategy_id": f"paper_spy_monthly_sharpe2_s{stage:03d}_{digest}",
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
            "paper_titles": "|".join(weekly.PAPER_SOURCES[k]["paper"] for k in paper_keys),
            "source_rule_summary": "|".join(weekly.PAPER_SOURCES[k]["rule"] for k in paper_keys),
            "traded_asset": "SPY",
            "frequency": "monthly",
            "lag_periods": 1,
            "train_sharpe": float(train_metrics["sharpe"]),
            "validation_sharpe": float(validation_metrics["sharpe"]),
            "train_cagr": float(train_metrics["cagr"]),
            "validation_cagr": float(validation_metrics["cagr"]),
            "train_mdd": float(train_metrics["mdd"]),
            "validation_mdd": float(validation_metrics["mdd"]),
            "train_positive_months_pct": float(train_metrics["positive_periods_pct"]),
            "validation_positive_months_pct": float(validation_metrics["positive_periods_pct"]),
            "train_turnover_monthly": float(turnover(positions[train_mask])),
            "validation_turnover_monthly": float(turnover(positions[validation_mask])),
            "rule_type": str(params["rule_type"]),
            "feature_count": int(len(features)),
            "features": "|".join(features),
            "params_json": json.dumps(params, sort_keys=True),
            "train_score": float(train_metrics["sharpe"] * 1_000_000.0 + train_metrics["cagr"] * 200_000.0 - abs(train_metrics["mdd"]) * 350_000.0 - turnover(positions[train_mask]) * 100_000.0),
        }
        rows.append(row)
    shard_dir = output_dir / "shards" / f"stage_{stage:03d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(columns=["strategy_id", "train_score", "train_sharpe", "validation_sharpe", "final_verified_report_only"])
    top = frame.sort_values(["train_score", "train_sharpe"], ascending=[False, False]).head(int(top_per_stage))
    verified = frame[frame.get("final_verified_report_only", pd.Series(dtype=bool)).astype(bool)]
    diagnostic = frame.sort_values(["validation_sharpe", "train_sharpe"], ascending=[False, False]).head(int(top_per_stage)).copy()
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


def paper_sources_for_features(features: list[str], feature_papers: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    keys: set[str] = set()
    for feature in features:
        keys.update(feature_papers.get(feature, ()))
    return tuple(sorted(keys)) or ("faber_ma",)


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
    top.to_csv(output_dir / "paper_spy_monthly_sharpe2_leaderboard.csv", index=False)
    verified.to_csv(output_dir / "paper_spy_monthly_sharpe2_verified.csv", index=False)
    diagnostic.to_csv(output_dir / "paper_spy_monthly_sharpe2_validation_ceiling_diagnostic.csv", index=False)
    build_fail_reasons(top).to_csv(output_dir / "paper_spy_monthly_sharpe2_fail_reasons.csv", index=False)
    summaries = []
    for path in summary_files:
        try:
            summaries.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    pd.DataFrame(summaries).to_csv(output_dir / "paper_spy_monthly_sharpe2_shard_summaries.csv", index=False)
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
        "selection_logic": "train-only monthly score; validation is report-only",
        "train_start": str(TRAIN_START.date()),
        "train_end": str(TRAIN_END.date()),
        "validation_start": str(VALIDATION_START.date()),
        "validation_end": str(VALIDATION_END.date()),
        "locked_start": str(LOCKED_START.date()),
    }
    (output_dir / "paper_spy_monthly_sharpe2_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


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
