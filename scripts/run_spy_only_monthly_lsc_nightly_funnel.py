from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import run_paper_spy_monthly_sharpe2 as monthly
from scripts import run_paper_spy_weekly_sharpe2 as weekly

CAMPAIGN_ID = "spy_only_monthly_lsc_nightly_funnel_20260610"
TRAIN_START = pd.Timestamp("1995-01-01")
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")
TARGET_SHARPE = 2.0
PPY = 12
ALLOWED_POSITIONS = {-1.0, 0.0, 1.0}

ROUND_SPECS: list[dict[str, Any]] = [
    {"name": "momentum_tsmom", "prefixes": ["spy_mom_"], "styles": ["single_threshold", "sparse_linear", "threshold_vote"]},
    {"name": "sma_trend", "prefixes": ["spy_ma_gap_"], "styles": ["single_threshold", "simple_regime_tree", "threshold_vote"]},
    {"name": "reversal_pullback", "prefixes": ["spy_mom_", "spy_drawdown_"], "styles": ["single_threshold", "signed_stump", "sparse_linear"]},
    {"name": "realized_vol_drawdown", "prefixes": ["spy_realized_vol_", "spy_drawdown_"], "styles": ["single_threshold", "simple_regime_tree", "threshold_vote"]},
    {"name": "vix_vrp_ivrv", "prefixes": ["vix_", "vxo_", "vixmo_", "vix_term_", "vrp_", "iv_rv_"], "styles": ["sparse_linear", "ridge", "simple_regime_tree"]},
    {"name": "put_call_skew_cboe", "prefixes": ["total_pc_", "skew_", "pput_", "bxy_", "bxmd_", "cmbo_", "puty_"], "styles": ["threshold_vote", "sparse_linear", "ridge"]},
    {"name": "yield_curve_rates", "prefixes": ["yield_curve_", "tnx_", "irx_"], "styles": ["single_threshold", "sparse_linear", "ridge"]},
    {"name": "calendar_seasonality", "prefixes": ["calendar_"], "styles": ["threshold_vote", "sparse_linear", "simple_regime_tree"]},
    {"name": "low_turnover_tactical", "prefixes": ["spy_mom_", "spy_ma_gap_", "vix_", "yield_curve_"], "styles": ["sparse_linear", "walk_forward_ridge", "threshold_vote"], "turnover_penalty": 250_000.0},
    {"name": "sparse_cross_feature", "prefixes": ["spy_", "vix_", "skew_", "total_pc_", "yield_curve_", "vrp_"], "styles": ["sparse_linear", "ridge", "quadratic_ridge", "train_only_ensemble"]},
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["prepare-data", "run-until", "final-merge"], required=True)
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--deadline", default="")
    parser.add_argument("--stop-new-shard-after", default="")
    parser.add_argument("--shard-minutes", type=float, default=18.0)
    parser.add_argument("--top-per-shard", type=int, default=250)
    parser.add_argument("--configs-per-shard", type=int, default=5_000_000)
    parser.add_argument("--max-stages", type=int, default=0)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.mode == "prepare-data":
        prepare_data(output_dir)
    elif args.mode == "run-until":
        run_until(
            output_dir,
            deadline=parse_datetime(args.deadline),
            stop_new_shard_after=parse_datetime(args.stop_new_shard_after),
            shard_minutes=float(args.shard_minutes),
            top_per_shard=int(args.top_per_shard),
            configs_per_shard=int(args.configs_per_shard),
            max_stages=int(args.max_stages),
        )
    else:
        final_merge(output_dir)


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def prepare_data(output_dir: Path) -> None:
    cache_dir = output_dir / ".yfinance_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(cache_dir))
    symbols = ["SPY", "^GSPC", "^VIX", "^VIX3M", "^VXO", "^SKEW", "^TNX", "^IRX"]
    weekly_prices = try_load_local_weekly_price_fallback()
    if weekly_prices is not None:
        monthly_prices = weekly_prices.resample("ME").last().sort_index().ffill()
        data_source = "local_weekly_price_fallback"
    else:
        prices = download_yahoo_prices(symbols)
        if "SPY" not in prices or prices["SPY"].dropna().empty:
            raise RuntimeError("SPY data unavailable")
        cboe = weekly.fetch_cboe_weekly_panel()
        monthly_prices = prices.resample("ME").last().join(cboe.resample("ME").last(), how="outer").sort_index().ffill()
        data_source = "yfinance_plus_cboe"
    monthly_prices = monthly_prices[monthly_prices.index < LOCKED_START].dropna(subset=["SPY"])
    if monthly_prices.empty or monthly_prices.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached monthly data output")

    monthly_returns = monthly_prices[["SPY"]].pct_change(fill_method=None).dropna()
    features, feature_papers = monthly.build_monthly_features(monthly_prices, monthly_returns)
    features, feature_papers = enrich_monthly_features(features, monthly_prices, monthly_returns, feature_papers)
    common = features.index.intersection(monthly_returns.index)
    features = scale_features(features.reindex(common)).dropna(how="any")
    monthly_returns = monthly_returns.reindex(features.index)
    if features.index.max() >= LOCKED_START or monthly_returns.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached aligned output")

    features.to_csv(output_dir / "paper_monthly_feature_frame.csv", index_label="timestamp")
    monthly_returns.to_csv(output_dir / "monthly_returns.csv", index_label="timestamp")
    monthly_prices.to_csv(output_dir / "monthly_prices.csv", index_label="timestamp")
    build_feature_audit(feature_papers).to_csv(output_dir / "feature_family_audit_source.csv", index=False)
    pd.DataFrame(weekly.PAPER_SOURCES.values()).assign(paper_key=list(weekly.PAPER_SOURCES)).to_csv(output_dir / "paper_sources.csv", index=False)
    (output_dir / "policy_audit.json").write_text(
        json.dumps(
            {
                "campaign_id": CAMPAIGN_ID,
                "objective": "Monthly SPY-only long/short/cash top-of-funnel search",
                "traded_asset": "SPY",
                "frequency": "monthly",
                "position_policy": "discrete_long_short_cash",
                "allowed_positions": [-1, 0, 1],
                "cash_allowed": True,
                "leverage_allowed": False,
                "max_leverage": 1.0,
                "locked_start": str(LOCKED_START.date()),
                "data_end_max": str(monthly_returns.index.max().date()),
                "data_source": data_source,
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "validation_used_for_selection": False,
                "paper_exact_replication_claimed": False,
                "feature_count": int(features.shape[1]),
                "rounds": ROUND_SPECS,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def download_yahoo_prices(symbols: list[str]) -> pd.DataFrame:
    try:
        raw = yf.download(
            symbols,
            start="1995-01-01",
            end="2021-01-01",
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=False,
        )
    except Exception:
        return pd.DataFrame()
    prices = pd.DataFrame()
    for symbol in symbols:
        try:
            prices[symbol] = raw[symbol]["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]
        except Exception:
            continue
    return prices


def load_local_weekly_price_fallback() -> pd.DataFrame:
    frame = try_load_local_weekly_price_fallback()
    if frame is None:
        raise RuntimeError("SPY data unavailable and no local weekly fallback found")
    return frame


def try_load_local_weekly_price_fallback() -> pd.DataFrame | None:
    candidates = [
        Path("outputs/paper_spy_weekly_regime_sharpe2_simple_smoke/weekly_prices.csv"),
        Path("outputs/paper_spy_weekly_sharpe2_smoke_fix/weekly_prices.csv"),
        Path("outputs/spy_weekly_longshort_sharpe2_smoke25_optional_context/data/weekly_prices.csv"),
        Path("outputs/spy_weekly_annual_beat_spy_full1995_15m_run_27222114316/data/weekly_prices.csv"),
    ]
    for path in candidates:
        if not path.exists() or path.stat().st_size == 0:
            continue
        frame = pd.read_csv(path, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
        if "SPY" in frame and frame["SPY"].dropna().shape[0] > 200 and frame.index.max() < LOCKED_START:
            return frame
    return None


def enrich_monthly_features(
    features: pd.DataFrame,
    prices: pd.DataFrame,
    returns: pd.DataFrame,
    feature_papers: dict[str, tuple[str, ...]],
) -> tuple[pd.DataFrame, dict[str, tuple[str, ...]]]:
    out = features.copy()
    spy = prices["SPY"].reindex(out.index).ffill()
    spy_ret = returns["SPY"].reindex(out.index).astype(float)
    for lb in [1, 2, 3, 6, 9, 12, 18, 24]:
        add_feature(out, feature_papers, f"spy_reversal_{lb}m", -((1.0 + spy_ret).rolling(lb).apply(np.prod, raw=True) - 1.0).shift(1), ("mop_tsmom",))
    for lb in [3, 6, 12, 24]:
        high = spy.rolling(lb).max()
        dd = (spy / high - 1.0).shift(1)
        add_feature(out, feature_papers, f"spy_drawdown_recovery_{lb}m", (-dd).clip(lower=0.0), ("faber_ma",))
    month = pd.Series(out.index.month.astype(float), index=out.index)
    quarter = pd.Series(out.index.quarter.astype(float), index=out.index)
    year = pd.Series(out.index.year.astype(float), index=out.index)
    time_index = pd.Series(np.arange(len(out), dtype=float), index=out.index)
    calendar_features = {
        "calendar_month_sin": np.sin(2.0 * np.pi * month / 12.0),
        "calendar_month_cos": np.cos(2.0 * np.pi * month / 12.0),
        "calendar_quarter_sin": np.sin(2.0 * np.pi * quarter / 4.0),
        "calendar_quarter_cos": np.cos(2.0 * np.pi * quarter / 4.0),
        "calendar_cycle4_sin": np.sin(2.0 * np.pi * (year % 4.0) / 4.0),
        "calendar_cycle4_cos": np.cos(2.0 * np.pi * (year % 4.0) / 4.0),
        "calendar_january": (month == 1.0).astype(float),
        "calendar_september": (month == 9.0).astype(float),
        "calendar_nov_apr": month.isin([11.0, 12.0, 1.0, 2.0, 3.0, 4.0]).astype(float),
        "calendar_q4": (quarter == 4.0).astype(float),
        "calendar_time_trend": time_index / max(1.0, float(len(time_index) - 1)),
    }
    for name, values in calendar_features.items():
        add_feature(out, feature_papers, name, values, ("faber_ma",))
    return out.replace([np.inf, -np.inf], np.nan).dropna(axis=1, how="all"), feature_papers


def add_feature(out: pd.DataFrame, papers: dict[str, tuple[str, ...]], name: str, values: pd.Series, paper_keys: tuple[str, ...]) -> None:
    out[name] = values
    papers[name] = paper_keys


def scale_features(features: pd.DataFrame) -> pd.DataFrame:
    train = features.loc[(features.index >= TRAIN_START) & (features.index <= TRAIN_END)]
    median = train.median()
    iqr = train.quantile(0.75) - train.quantile(0.25)
    std = train.std().replace(0.0, np.nan)
    scale = iqr.mask(iqr == 0.0, std).replace(0.0, np.nan)
    valid_cols = [c for c in scale.dropna().index if c in features]
    scaled = (features[valid_cols] - median[valid_cols]) / scale[valid_cols]
    return scaled.replace([np.inf, -np.inf], np.nan).dropna(how="any").clip(-8.0, 8.0)


def build_feature_audit(feature_papers: dict[str, tuple[str, ...]]) -> pd.DataFrame:
    rows = []
    for feature, keys in sorted(feature_papers.items()):
        rows.append(
            {
                "feature": feature,
                "feature_family": feature_family(feature),
                "paper_keys": "|".join(keys),
                "paper_titles": "|".join(weekly.PAPER_SOURCES.get(k, {}).get("paper", k) for k in keys),
                "lagged": True,
                "frequency": "monthly",
            }
        )
    return pd.DataFrame(rows)


def feature_family(feature: str) -> str:
    for prefix, family in [
        ("spy_mom_", "momentum"),
        ("spy_reversal_", "reversal"),
        ("spy_ma_gap_", "trend"),
        ("spy_realized_vol_", "realized_volatility"),
        ("spy_drawdown_", "drawdown"),
        ("spy_drawdown_recovery_", "drawdown"),
        ("vix_", "vix"),
        ("vxo_", "vix"),
        ("vixmo_", "vix_term"),
        ("vix_term_", "vix_term"),
        ("vrp_", "variance_risk_premium"),
        ("iv_rv_", "variance_risk_premium"),
        ("total_pc_", "put_call"),
        ("skew_", "skew"),
        ("pput_", "cboe_option_benchmark"),
        ("bxy_", "cboe_option_benchmark"),
        ("bxmd_", "cboe_option_benchmark"),
        ("cmbo_", "cboe_option_benchmark"),
        ("puty_", "cboe_option_benchmark"),
        ("yield_curve_", "rates"),
        ("tnx_", "rates"),
        ("irx_", "rates"),
        ("calendar_", "calendar"),
    ]:
        if feature.startswith(prefix):
            return family
    return "other"


def run_until(
    output_dir: Path,
    *,
    deadline: datetime | None,
    stop_new_shard_after: datetime | None,
    shard_minutes: float,
    top_per_shard: int,
    configs_per_shard: int,
    max_stages: int,
) -> None:
    if deadline is None:
        raise ValueError("--deadline is required for run-until")
    if stop_new_shard_after is None:
        stop_new_shard_after = deadline
    stages_done = 0
    while datetime.now(deadline.tzinfo) < stop_new_shard_after:
        if max_stages and stages_done >= max_stages:
            break
        remaining = (deadline - datetime.now(deadline.tzinfo)).total_seconds() / 60.0
        if remaining <= 1.0:
            break
        stage = next_stage(output_dir)
        run_shard(
            output_dir,
            stage=stage,
            shard_minutes=min(float(shard_minutes), max(0.1, remaining - 0.5)),
            top_per_shard=top_per_shard,
            configs_per_shard=configs_per_shard,
        )
        stages_done += 1
    final_merge(output_dir)


def next_stage(output_dir: Path) -> int:
    stages: list[int] = []
    for path in (output_dir / "shards").glob("stage_*"):
        try:
            stages.append(int(path.name.split("_", 1)[1]))
        except Exception:
            continue
    return (max(stages) + 1) if stages else 0


def run_shard(output_dir: Path, *, stage: int, shard_minutes: float, top_per_shard: int, configs_per_shard: int) -> None:
    returns = pd.read_csv(output_dir / "monthly_returns.csv", parse_dates=["timestamp"]).set_index("timestamp")
    features = pd.read_csv(output_dir / "paper_monthly_feature_frame.csv", parse_dates=["timestamp"]).set_index("timestamp")
    audit = pd.read_csv(output_dir / "feature_family_audit_source.csv")
    feature_papers = {row["feature"]: tuple(str(row["paper_keys"]).split("|")) for _, row in audit.iterrows()}
    if returns.index.max() >= LOCKED_START or features.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached shard")

    spec = ROUND_SPECS[stage % len(ROUND_SPECS)]
    feature_cols = list(features.columns)
    selected = feature_indices_for_prefixes(feature_cols, list(spec["prefixes"]))
    if not selected:
        write_unsupported_shard(output_dir, stage, spec, "no_matching_features")
        return

    matrix = features.to_numpy(dtype=float)
    spy_values = returns["SPY"].reindex(features.index).astype(float).to_numpy()
    train_mask = np.asarray((features.index >= TRAIN_START) & (features.index <= TRAIN_END), dtype=bool)
    validation_mask = np.asarray((features.index >= VALIDATION_START) & (features.index <= VALIDATION_END), dtype=bool)
    rng = np.random.default_rng(20260610 + stage * 1_000_003)
    deadline = time.monotonic() + max(0.05, float(shard_minutes)) * 60.0
    rows: list[dict[str, Any]] = []
    evaluated = 0
    while evaluated < int(configs_per_shard) and time.monotonic() < deadline:
        evaluated += 1
        params = sample_params(rng, selected, spec, feature_cols)
        positions, train_metrics = fit_positions(matrix, spy_values, train_mask, params)
        policy = position_policy_audit(positions)
        if not policy["policy_pass"]:
            continue
        strategy_returns = positions * spy_values
        validation_metrics = metrics(strategy_returns[validation_mask])
        train_position = position_summary(positions[train_mask])
        validation_position = position_summary(positions[validation_mask])
        train_turnover = turnover(positions[train_mask])
        validation_turnover = turnover(positions[validation_mask])
        train_stability = train_stability_metrics(strategy_returns[train_mask], features.index[train_mask])
        features_used = [feature_cols[int(i)] for i in params["feature_indices"]]
        paper_keys = paper_sources_for_features(features_used, feature_papers)
        score = train_score(train_metrics, train_stability, train_turnover, params, float(spec.get("turnover_penalty", 120_000.0)))
        payload = {"round": spec["name"], "params": params, "features": features_used, "frequency": "monthly"}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        rows.append(
            {
                "strategy_id": f"spy_only_monthly_lsc_{spec['name']}_s{stage:03d}_{digest}",
                "round_index": int(stage % len(ROUND_SPECS)),
                "round_name": spec["name"],
                "stage": int(stage),
                "config_index": int(evaluated),
                "train_score": float(score),
                "train_sharpe": float(train_metrics["sharpe"]),
                "validation_sharpe": float(validation_metrics["sharpe"]),
                "min_train_validation_sharpe": safe_nanmin([train_metrics["sharpe"], validation_metrics["sharpe"]]),
                "train_cagr_pct": float(train_metrics["cagr"] * 100.0),
                "validation_cagr_pct": float(validation_metrics["cagr"] * 100.0),
                "train_mdd_pct": float(train_metrics["mdd"] * 100.0),
                "validation_mdd_pct": float(validation_metrics["mdd"] * 100.0),
                "train_positive_months_pct": float(train_metrics["positive_periods_pct"] * 100.0),
                "validation_positive_months_pct": float(validation_metrics["positive_periods_pct"] * 100.0),
                "train_turnover_monthly": float(train_turnover),
                "validation_turnover_monthly": float(validation_turnover),
                "train_min_era_sharpe": float(train_stability["min_era_sharpe"]),
                "train_positive_era_pct": float(train_stability["positive_era_pct"]),
                "traded_asset": "SPY",
                "frequency": "monthly",
                "position_policy": "discrete_long_short_cash_no_leverage",
                "unique_positions": policy["unique_positions"],
                "max_abs_position": float(policy["max_abs_position"]),
                "train_cash_pct": float(train_position["cash_pct"]),
                "validation_cash_pct": float(validation_position["cash_pct"]),
                "train_long_pct": float(train_position["long_pct"]),
                "validation_long_pct": float(validation_position["long_pct"]),
                "train_short_pct": float(train_position["short_pct"]),
                "validation_short_pct": float(validation_position["short_pct"]),
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "validation_used_for_selection": False,
                "paper_exact_replication_claimed": False,
                "paper_strategy_type": "template_or_proxy",
                "source_papers": "|".join(paper_keys),
                "source_rule_summary": "|".join(weekly.PAPER_SOURCES.get(k, {}).get("rule", k) for k in paper_keys),
                "feature_families": "|".join(sorted({feature_family(name) for name in features_used})),
                "features": "|".join(features_used),
                "rule_type": str(params["rule_type"]),
                "feature_count": int(len(features_used)),
                "params_json": json.dumps(params, sort_keys=True),
                "final_verified_report_only": bool(train_metrics["sharpe"] >= TARGET_SHARPE and validation_metrics["sharpe"] >= TARGET_SHARPE),
                "eligible_for_acceptance": False,
            }
        )

    shard_dir = output_dir / "shards" / f"stage_{stage:03d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(columns=leaderboard_columns())
    top = frame.sort_values(["train_score", "train_sharpe"], ascending=[False, False]).head(int(top_per_shard)) if not frame.empty else frame
    diagnostic = frame.sort_values(["validation_sharpe", "train_sharpe"], ascending=[False, False]).head(int(top_per_shard)) if not frame.empty else frame
    verified = frame[frame.get("final_verified_report_only", pd.Series(dtype=bool)).astype(bool)] if not frame.empty else frame
    top.to_csv(shard_dir / "top_candidates.csv", index=False)
    diagnostic.to_csv(shard_dir / "validation_diagnostic.csv", index=False)
    verified.to_csv(shard_dir / "verified_report_only.csv", index=False)
    (shard_dir / "shard_summary.json").write_text(
        json.dumps(
            {
                "stage": int(stage),
                "round_index": int(stage % len(ROUND_SPECS)),
                "round_name": spec["name"],
                "configs_requested": int(configs_per_shard),
                "configs_evaluated": int(evaluated),
                "rows_kept": int(len(frame)),
                "verified_report_only": int(len(verified)),
                "locked_opened": False,
                "validation_used_for_selection": False,
                "traded_asset": "SPY",
                "frequency": "monthly",
                "position_policy": "discrete_long_short_cash_no_leverage",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def feature_indices_for_prefixes(feature_cols: list[str], prefixes: list[str]) -> list[int]:
    return [i for i, name in enumerate(feature_cols) if any(name.startswith(prefix) for prefix in prefixes)]


def sample_params(rng: np.random.Generator, candidates: list[int], spec: dict[str, Any], feature_cols: list[str]) -> dict[str, Any]:
    styles = list(spec["styles"])
    rule_type = str(rng.choice(styles))
    max_candidates = max(1, len(candidates))
    if rule_type == "single_threshold":
        k = 1
    elif rule_type in {"ridge", "quadratic_ridge", "walk_forward_ridge"}:
        k = int(rng.integers(min(3, max_candidates), min(10, max_candidates) + 1))
    elif rule_type == "train_only_ensemble":
        k = int(rng.integers(min(4, max_candidates), min(12, max_candidates) + 1))
    else:
        k = int(rng.integers(min(2, max_candidates), min(7, max_candidates) + 1))
    indices = rng.choice(candidates, size=k, replace=False)
    weights = rng.normal(0.0, 1.0, size=k)
    norm = np.sum(np.abs(weights))
    weights = weights / norm if norm > 0 else np.ones(k) / k
    return {
        "rule_type": rule_type,
        "feature_indices": [int(i) for i in indices],
        "feature_names": [feature_cols[int(i)] for i in indices],
        "weights": [float(w) for w in weights],
        "directions": [float(x) for x in rng.choice([-1.0, 1.0], size=k)],
        "quantiles": [float(x) for x in rng.uniform(0.12, 0.88, size=k)],
        "band_quantile": float(rng.uniform(0.45, 0.85)),
        "cash_band": float(rng.uniform(0.02, 0.45)),
        "threshold": float(rng.normal(0.0, 0.18)),
        "ridge_alpha": float(10.0 ** rng.uniform(-2.5, 2.0)),
        "walk_forward_min_train": int(rng.choice([72, 96, 120, 144])),
        "walk_forward_refit_step": int(rng.choice([1, 3, 6, 12])),
        "invert": int(rng.integers(0, 2)),
    }


def fit_positions(matrix: np.ndarray, spy_values: np.ndarray, train_mask: np.ndarray, params: dict[str, Any]) -> tuple[np.ndarray, dict[str, float]]:
    rule_type = str(params["rule_type"])
    if rule_type in {"ridge", "quadratic_ridge"}:
        raw = ridge_score(matrix, spy_values, train_mask, params, quadratic=(rule_type == "quadratic_ridge"))
    elif rule_type == "walk_forward_ridge":
        raw = walk_forward_ridge_score(matrix, spy_values, train_mask, params)
    elif rule_type == "simple_regime_tree":
        raw = regime_tree_score(matrix, spy_values, train_mask, params)
    elif rule_type == "train_only_ensemble":
        raw = ensemble_score(matrix, spy_values, train_mask, params)
    else:
        raw = raw_rule_score(matrix, params, matrix[train_mask])
    if int(params.get("invert", 0)):
        raw = -raw
    return choose_discrete_positions(raw, spy_values, train_mask, params)


def raw_rule_score(matrix: np.ndarray, params: dict[str, Any], train_matrix: np.ndarray) -> np.ndarray:
    idx = np.asarray(params["feature_indices"], dtype=int)
    selected = matrix[:, idx]
    train_selected = train_matrix[:, idx]
    rule = str(params["rule_type"])
    if rule in {"single_threshold", "signed_stump"}:
        direction = float(params["directions"][0])
        threshold = float(np.nanquantile(train_selected[:, 0], float(params["quantiles"][0])))
        return direction * (selected[:, 0] - threshold)
    if rule == "threshold_vote":
        votes = []
        for j, q, direction in zip(range(len(idx)), params["quantiles"], params["directions"], strict=False):
            threshold = float(np.nanquantile(train_selected[:, j], float(q)))
            votes.append(np.where(float(direction) * (selected[:, j] - threshold) >= 0.0, 1.0, -1.0))
        return np.mean(np.vstack(votes), axis=0)
    weights = np.asarray(params["weights"], dtype=float)
    return selected @ weights


def ridge_score(matrix: np.ndarray, spy_values: np.ndarray, train_mask: np.ndarray, params: dict[str, Any], *, quadratic: bool) -> np.ndarray:
    idx = np.asarray(params["feature_indices"], dtype=int)
    x = matrix[:, idx]
    if quadratic:
        x = np.column_stack([x, x * x])
    train_x = x[train_mask]
    y = np.asarray(spy_values[train_mask], dtype=float)
    valid = np.isfinite(train_x).all(axis=1) & np.isfinite(y)
    train_x = train_x[valid]
    y = y[valid]
    if len(y) < x.shape[1] + 5:
        return raw_rule_score(matrix, params, matrix[train_mask])
    mu = train_x.mean(axis=0)
    sigma = train_x.std(axis=0)
    sigma[sigma == 0.0] = 1.0
    tx = (train_x - mu) / sigma
    full_x = (x - mu) / sigma
    alpha = float(params.get("ridge_alpha", 1.0))
    design = np.column_stack([np.ones(len(tx)), tx])
    full_design = np.column_stack([np.ones(len(full_x)), full_x])
    penalty = np.eye(design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    try:
        beta = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    except np.linalg.LinAlgError:
        beta = np.linalg.pinv(design.T @ design + penalty) @ design.T @ y
    return full_design @ beta


def walk_forward_ridge_score(matrix: np.ndarray, spy_values: np.ndarray, train_mask: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    idx = np.asarray(params["feature_indices"], dtype=int)
    x = matrix[:, idx]
    out = np.zeros(matrix.shape[0], dtype=float)
    train_indices = np.where(train_mask)[0]
    min_train = int(params.get("walk_forward_min_train", 96))
    step = int(params.get("walk_forward_refit_step", 6))
    if len(train_indices) <= min_train:
        return ridge_score(matrix, spy_values, train_mask, params, quadratic=False)
    last_beta: np.ndarray | None = None
    last_mu: np.ndarray | None = None
    last_sigma: np.ndarray | None = None
    for position, current_index in enumerate(train_indices):
        if position < min_train:
            continue
        if last_beta is None or position % step == 0:
            hist = train_indices[:position]
            local_mask = np.zeros_like(train_mask, dtype=bool)
            local_mask[hist] = True
            local_params = dict(params)
            local_params["rule_type"] = "ridge"
            train_x = x[local_mask]
            y = spy_values[local_mask]
            valid = np.isfinite(train_x).all(axis=1) & np.isfinite(y)
            train_x = train_x[valid]
            y = y[valid]
            last_mu = train_x.mean(axis=0)
            last_sigma = train_x.std(axis=0)
            last_sigma[last_sigma == 0.0] = 1.0
            tx = (train_x - last_mu) / last_sigma
            design = np.column_stack([np.ones(len(tx)), tx])
            alpha = float(params.get("ridge_alpha", 1.0))
            penalty = np.eye(design.shape[1]) * alpha
            penalty[0, 0] = 0.0
            try:
                last_beta = np.linalg.solve(design.T @ design + penalty, design.T @ y)
            except np.linalg.LinAlgError:
                last_beta = np.linalg.pinv(design.T @ design + penalty) @ design.T @ y
        if last_beta is not None and last_mu is not None and last_sigma is not None:
            row = np.concatenate([[1.0], (x[current_index] - last_mu) / last_sigma])
            out[current_index] = float(row @ last_beta)
    future_mask = ~train_mask
    if np.any(future_mask):
        out[future_mask] = ridge_score(matrix, spy_values, train_mask, params, quadratic=False)[future_mask]
    if np.allclose(out, 0.0):
        return ridge_score(matrix, spy_values, train_mask, params, quadratic=False)
    return out


def regime_tree_score(matrix: np.ndarray, spy_values: np.ndarray, train_mask: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    idx = np.asarray(params["feature_indices"][:2], dtype=int)
    if len(idx) < 2:
        return raw_rule_score(matrix, params, matrix[train_mask])
    x = matrix[:, idx]
    train_x = x[train_mask]
    train_y = spy_values[train_mask]
    q1 = float(np.nanquantile(train_x[:, 0], float(params["quantiles"][0])))
    q2 = float(np.nanquantile(train_x[:, 1], float(params["quantiles"][1])))
    leaf = (x[:, 0] > q1).astype(int) * 2 + (x[:, 1] > q2).astype(int)
    train_leaf = leaf[train_mask]
    signs = np.zeros(4, dtype=float)
    for item in range(4):
        vals = train_y[train_leaf == item]
        if len(vals) < 8:
            signs[item] = 0.0
        else:
            mean = float(np.nanmean(vals))
            signs[item] = 0.0 if abs(mean) < float(np.nanstd(train_y)) * 0.05 else math.copysign(1.0, mean)
    return signs[leaf]


def ensemble_score(matrix: np.ndarray, spy_values: np.ndarray, train_mask: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    idx = list(params["feature_indices"])
    scores = []
    for offset, feature_index in enumerate(idx):
        local = dict(params)
        local["rule_type"] = "single_threshold"
        local["feature_indices"] = [int(feature_index)]
        local["directions"] = [float(params["directions"][offset % len(params["directions"])])]
        local["quantiles"] = [float(params["quantiles"][offset % len(params["quantiles"])])]
        scores.append(raw_rule_score(matrix, local, matrix[train_mask]))
    return np.mean(np.vstack(scores), axis=0) if scores else np.zeros(matrix.shape[0], dtype=float)


def choose_discrete_positions(raw: np.ndarray, spy_values: np.ndarray, train_mask: np.ndarray, params: dict[str, Any]) -> tuple[np.ndarray, dict[str, float]]:
    raw = np.asarray(raw, dtype=float)
    train_raw = raw[train_mask]
    thresholds = [float(params.get("threshold", 0.0))]
    for q in np.linspace(0.15, 0.85, 15):
        val = np.nanquantile(train_raw, q)
        if np.isfinite(val):
            thresholds.append(float(val))
    band_base = np.nanstd(train_raw)
    if not np.isfinite(band_base) or band_base <= 0.0:
        band_base = 0.0
    bands = [0.0, float(params.get("cash_band", 0.1)) * band_base, 0.5 * float(params.get("cash_band", 0.1)) * band_base]
    best_positions: np.ndarray | None = None
    best_metrics: dict[str, float] | None = None
    best_sharpe = -999.0
    for threshold in thresholds:
        for band in bands:
            pos = np.where(raw > threshold + band, 1.0, np.where(raw < threshold - band, -1.0, 0.0))
            summary = position_summary(pos[train_mask])
            if summary["long_pct"] < 0.03 or summary["short_pct"] < 0.03:
                continue
            if summary["cash_pct"] > 0.85:
                continue
            current = metrics(pos[train_mask] * spy_values[train_mask])
            sharpe = float(current["sharpe"]) if np.isfinite(current["sharpe"]) else -999.0
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_positions = pos.astype(float)
                best_metrics = current
                params["fit_threshold"] = float(threshold)
                params["fit_band"] = float(band)
    if best_positions is None or best_metrics is None:
        fallback = np.sign(raw)
        fallback[np.abs(raw) < np.nanmedian(np.abs(train_raw)) * 0.25] = 0.0
        best_positions = sanitize_positions(fallback)
        best_metrics = metrics(best_positions[train_mask] * spy_values[train_mask])
    return sanitize_positions(best_positions), best_metrics


def sanitize_positions(values: np.ndarray) -> np.ndarray:
    out = np.asarray(values, dtype=float).copy()
    out = np.where(out > 0.0, 1.0, np.where(out < 0.0, -1.0, 0.0))
    return out.astype(float)


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
    values = np.asarray(positions, dtype=float)
    return float(np.mean(np.abs(np.diff(values)) > 0.0)) if len(values) > 1 else 0.0


def position_summary(positions: np.ndarray) -> dict[str, float]:
    values = np.asarray(positions, dtype=float)
    if len(values) == 0:
        return {"long_pct": 0.0, "short_pct": 0.0, "cash_pct": 0.0}
    return {
        "long_pct": float(np.mean(values > 0.0) * 100.0),
        "short_pct": float(np.mean(values < 0.0) * 100.0),
        "cash_pct": float(np.mean(np.isclose(values, 0.0)) * 100.0),
    }


def position_policy_audit(positions: np.ndarray) -> dict[str, Any]:
    values = np.asarray(positions, dtype=float)
    finite = values[np.isfinite(values)]
    unique = sorted({float(x) for x in finite})
    max_abs = float(np.max(np.abs(finite))) if len(finite) else np.nan
    policy_pass = bool(len(finite) == len(values) and set(unique).issubset(ALLOWED_POSITIONS) and max_abs <= 1.0)
    return {"unique_positions": "|".join(str(int(x)) for x in unique), "max_abs_position": max_abs, "policy_pass": policy_pass}


def train_stability_metrics(strategy_returns: np.ndarray, dates: pd.DatetimeIndex) -> dict[str, float]:
    eras = [
        (pd.Timestamp("1995-01-01"), pd.Timestamp("1998-12-31")),
        (pd.Timestamp("1999-01-01"), pd.Timestamp("2002-12-31")),
        (pd.Timestamp("2003-01-01"), pd.Timestamp("2006-12-31")),
        (pd.Timestamp("2007-01-01"), pd.Timestamp("2010-12-31")),
    ]
    sharpes = []
    cagrs = []
    for start, end in eras:
        mask = (dates >= start) & (dates <= end)
        row = metrics(strategy_returns[mask])
        if np.isfinite(row["sharpe"]):
            sharpes.append(float(row["sharpe"]))
        if np.isfinite(row["cagr"]):
            cagrs.append(float(row["cagr"]))
    return {
        "min_era_sharpe": float(np.min(sharpes)) if sharpes else -99.0,
        "avg_era_sharpe": float(np.mean(sharpes)) if sharpes else -99.0,
        "positive_era_pct": float(np.mean(np.asarray(cagrs) > 0.0) * 100.0) if cagrs else 0.0,
    }


def train_score(train_metrics: dict[str, float], stability: dict[str, float], turn: float, params: dict[str, Any], turnover_penalty: float) -> float:
    sharpe = float(train_metrics["sharpe"])
    cagr = float(train_metrics["cagr"])
    mdd = float(train_metrics["mdd"])
    score = (
        sharpe * 700_000.0
        + max(-2.0, float(stability["min_era_sharpe"])) * 420_000.0
        + float(stability["positive_era_pct"]) * 5_000.0
        + cagr * 250_000.0
        - abs(mdd) * 400_000.0
        - turn * float(turnover_penalty)
        - int(len(params.get("feature_indices", []))) * 1_000.0
    )
    return float(score)


def paper_sources_for_features(features: list[str], feature_papers: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    keys: list[str] = []
    for feature in features:
        keys.extend(feature_papers.get(feature, tuple()))
    return tuple(dict.fromkeys(keys)) or ("faber_ma",)


def write_unsupported_shard(output_dir: Path, stage: int, spec: dict[str, Any], reason: str) -> None:
    shard_dir = output_dir / "shards" / f"stage_{stage:03d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"stage": stage, "round_name": spec["name"], "reason": reason}]).to_csv(shard_dir / "unsupported.csv", index=False)
    pd.DataFrame(columns=leaderboard_columns()).to_csv(shard_dir / "top_candidates.csv", index=False)
    (shard_dir / "shard_summary.json").write_text(
        json.dumps({"stage": stage, "round_name": spec["name"], "status": "unsupported", "reason": reason}, indent=2),
        encoding="utf-8",
    )


def final_merge(output_dir: Path) -> None:
    final = output_dir / "final"
    final.mkdir(parents=True, exist_ok=True)
    top_files = list((output_dir / "shards").glob("**/top_candidates.csv"))
    diag_files = list((output_dir / "shards").glob("**/validation_diagnostic.csv"))
    summary_files = list((output_dir / "shards").glob("**/shard_summary.json"))
    leaderboard = concat_csv(top_files)
    diagnostic = concat_csv(diag_files)
    summaries = load_json_files(summary_files)
    if not leaderboard.empty:
        leaderboard = normalize_and_filter_policy(leaderboard)
        leaderboard = leaderboard.drop_duplicates("strategy_id", keep="first")
        leaderboard = leaderboard.sort_values(["train_score", "train_sharpe"], ascending=[False, False])
    if not diagnostic.empty:
        diagnostic = normalize_and_filter_policy(diagnostic).drop_duplicates("strategy_id", keep="first")
        diagnostic = diagnostic.sort_values(["validation_sharpe", "train_sharpe"], ascending=[False, False])
    top_train = leaderboard.head(1000).copy()
    near_misses = leaderboard[leaderboard["train_sharpe"] < TARGET_SHARPE].head(500).copy() if not leaderboard.empty else pd.DataFrame(columns=leaderboard_columns())
    exposure = build_exposure_audit(leaderboard)
    feature_audit = build_feature_family_audit(leaderboard)
    leaderboard.to_csv(final / "leaderboard_all.csv", index=False)
    top_train.to_csv(final / "top_train_candidates.csv", index=False)
    diagnostic.to_csv(final / "validation_diagnostic.csv", index=False)
    near_misses.to_csv(final / "near_misses.csv", index=False)
    exposure.to_csv(final / "exposure_audit.csv", index=False)
    feature_audit.to_csv(final / "feature_family_audit.csv", index=False)
    pd.DataFrame(summaries).to_csv(final / "shard_summaries.csv", index=False)
    policy = {
        "campaign_id": CAMPAIGN_ID,
        "traded_asset": "SPY",
        "frequency": "monthly",
        "allowed_positions": [-1, 0, 1],
        "cash_allowed": True,
        "leverage_allowed": False,
        "max_leverage": 1.0,
        "locked_opened": False,
        "validation_used_for_selection": False,
        "policy_rejected_rows": int(sum(item.get("policy_rejected_rows", 0) for item in summaries)),
    }
    (final / "policy_audit.json").write_text(json.dumps(policy, indent=2), encoding="utf-8")
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "rows_total": int(len(leaderboard)),
        "top_train_rows": int(len(top_train)),
        "validation_diagnostic_rows": int(len(diagnostic)),
        "near_miss_rows": int(len(near_misses)),
        "configs_evaluated": int(sum(int(item.get("configs_evaluated", 0)) for item in summaries)),
        "rounds_completed": int(len({int(item.get("stage", -1)) for item in summaries if "stage" in item})),
        "best_train_sharpe": safe_max(leaderboard, "train_sharpe"),
        "best_validation_sharpe_report_only": safe_max(leaderboard, "validation_sharpe"),
        "best_min_train_validation_sharpe_report_only": safe_max(leaderboard, "min_train_validation_sharpe"),
        "selection_logic": "train-only top-of-funnel; validation diagnostic is report-only",
        "locked_opened": False,
        "validation_used_for_selection": False,
        "traded_asset": "SPY",
        "frequency": "monthly",
        "position_policy": "discrete_long_short_cash_no_leverage",
    }
    (final / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def concat_csv(paths: list[Path]) -> pd.DataFrame:
    frames = []
    for path in paths:
        if path.exists() and path.stat().st_size > 0:
            try:
                frame = pd.read_csv(path)
            except pd.errors.EmptyDataError:
                continue
            if not frame.empty:
                frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=leaderboard_columns())


def load_json_files(paths: list[Path]) -> list[dict[str, Any]]:
    rows = []
    for path in paths:
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return rows


def normalize_and_filter_policy(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=leaderboard_columns())
    out = frame.copy()
    before = len(out)
    mask = (
        (out.get("traded_asset", "").astype(str) == "SPY")
        & (out.get("frequency", "").astype(str) == "monthly")
        & (pd.to_numeric(out.get("max_abs_position", np.nan), errors="coerce") <= 1.0)
        & out.get("unique_positions", "").astype(str).apply(unique_positions_ok)
        & (out.get("locked_opened", False).astype(str).str.lower() == "false")
        & (out.get("validation_used_for_selection", False).astype(str).str.lower() == "false")
    )
    out = out[mask].copy()
    out.attrs["policy_rejected_rows"] = before - len(out)
    for column in leaderboard_columns():
        if column not in out:
            out[column] = np.nan
    return out[leaderboard_columns()]


def unique_positions_ok(value: str) -> bool:
    if not value:
        return False
    try:
        vals = {float(x) for x in str(value).split("|") if x != ""}
    except Exception:
        return False
    return vals.issubset(ALLOWED_POSITIONS)


def build_exposure_audit(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["check", "passed", "detail"])
    return pd.DataFrame(
        [
            {"check": "traded_asset_spy_only", "passed": bool((frame["traded_asset"] == "SPY").all()), "detail": "|".join(sorted(frame["traded_asset"].astype(str).unique()))},
            {"check": "monthly_only", "passed": bool((frame["frequency"] == "monthly").all()), "detail": "|".join(sorted(frame["frequency"].astype(str).unique()))},
            {"check": "max_abs_position_le_1", "passed": bool((pd.to_numeric(frame["max_abs_position"], errors="coerce") <= 1.0).all()), "detail": str(safe_max(frame, "max_abs_position"))},
            {"check": "unique_positions_allowed", "passed": bool(frame["unique_positions"].astype(str).apply(unique_positions_ok).all()), "detail": "|".join(sorted(frame["unique_positions"].astype(str).unique()))},
            {"check": "locked_closed", "passed": bool((frame["locked_opened"].astype(str).str.lower() == "false").all()), "detail": "locked_opened false"},
            {"check": "validation_report_only", "passed": bool((frame["validation_used_for_selection"].astype(str).str.lower() == "false").all()), "detail": "validation_used_for_selection false"},
        ]
    )


def build_feature_family_audit(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["feature_family", "rows", "best_train_sharpe", "best_validation_sharpe_report_only"])
    rows = []
    for _, row in frame.iterrows():
        for family in str(row.get("feature_families", "")).split("|"):
            if family:
                rows.append(
                    {
                        "feature_family": family,
                        "strategy_id": row["strategy_id"],
                        "train_sharpe": row["train_sharpe"],
                        "validation_sharpe": row["validation_sharpe"],
                    }
                )
    if not rows:
        return pd.DataFrame(columns=["feature_family", "rows", "best_train_sharpe", "best_validation_sharpe_report_only"])
    data = pd.DataFrame(rows)
    return (
        data.groupby("feature_family")
        .agg(rows=("strategy_id", "count"), best_train_sharpe=("train_sharpe", "max"), best_validation_sharpe_report_only=("validation_sharpe", "max"))
        .reset_index()
        .sort_values(["best_train_sharpe", "rows"], ascending=[False, False])
    )


def safe_max(frame: pd.DataFrame, column: str) -> float | None:
    if frame.empty or column not in frame:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.max()) if not values.empty else None


def safe_nanmin(values: list[float]) -> float:
    finite = [float(value) for value in values if np.isfinite(value)]
    return float(min(finite)) if finite else np.nan


def leaderboard_columns() -> list[str]:
    return [
        "strategy_id",
        "round_index",
        "round_name",
        "stage",
        "config_index",
        "train_score",
        "train_sharpe",
        "validation_sharpe",
        "min_train_validation_sharpe",
        "train_cagr_pct",
        "validation_cagr_pct",
        "train_mdd_pct",
        "validation_mdd_pct",
        "train_positive_months_pct",
        "validation_positive_months_pct",
        "train_turnover_monthly",
        "validation_turnover_monthly",
        "train_min_era_sharpe",
        "train_positive_era_pct",
        "traded_asset",
        "frequency",
        "position_policy",
        "unique_positions",
        "max_abs_position",
        "train_cash_pct",
        "validation_cash_pct",
        "train_long_pct",
        "validation_long_pct",
        "train_short_pct",
        "validation_short_pct",
        "locked_opened",
        "locked_rows_accessed",
        "validation_used_for_selection",
        "paper_exact_replication_claimed",
        "paper_strategy_type",
        "source_papers",
        "source_rule_summary",
        "feature_families",
        "features",
        "rule_type",
        "feature_count",
        "params_json",
        "final_verified_report_only",
        "eligible_for_acceptance",
    ]


if __name__ == "__main__":
    main()
