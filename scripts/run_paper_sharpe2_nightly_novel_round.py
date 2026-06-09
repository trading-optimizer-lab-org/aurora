from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from pandas.errors import EmptyDataError

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import run_paper_cboe_sentiment_sharpe2 as cboe
from scripts import run_paper_operable_ensemble_sharpe2 as ensemble
from scripts import run_paper_spy_weekly_sharpe2 as weekly
from scripts.run_spy_weekly_longshort_sharpe2 import (
    build_feature_frame as build_rich_weekly_feature_frame,
    build_positions_train_only,
    metrics,
    position_audit,
    train_only_score,
    train_only_stability,
    turnover,
)

CAMPAIGN_ID = "paper_sharpe2_nightly_novel_30min_until_0630"
TARGET_SHARPE = 2.0
TRAIN_START = pd.Timestamp("1995-01-01")
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")
TZ = ZoneInfo("Europe/Madrid")


ROUND_SPECS: list[dict[str, Any]] = [
    {
        "name": "calendar_crash_seasonality",
        "engine": "generic",
        "prefixes": ["calendar_", "spy_drawdown_"],
        "novelty": "Calendar state around historical SPY drawdowns; previous runs were mostly momentum/regime, not calendar-crash focused.",
    },
    {
        "name": "international_lead_lag_stress",
        "engine": "generic",
        "prefixes": ["ftse_", "dax_", "nikkei_", "hsi_", "efa_", "eem_", "spy_gap_"],
        "novelty": "Uses international public index/ETF lead-lag stress only; no individual stocks.",
    },
    {
        "name": "spy_spx_basis_disagreement",
        "engine": "generic",
        "prefixes": ["spx_", "spy_", "sr_"],
        "novelty": "Uses SPY/SPX and support-resistance disagreement because sector ETF features are not present in the prepared paper dataset.",
    },
    {
        "name": "rates_equity_regime_switch",
        "engine": "generic",
        "prefixes": ["yield_curve_", "tnx_", "irx_", "spy_realized_vol_", "spy_drawdown_"],
        "novelty": "Focuses on rates/equity regime switches using available public yield and SPY volatility features.",
    },
    {
        "name": "skew_vix_stress_mix",
        "engine": "generic",
        "prefixes": ["skew_", "vix_", "vxo_", "vixmo_"],
        "novelty": "Combines SKEW, VIX, VXO and VIXMO stress signals rather than pure equity timing.",
    },
    {
        "name": "volume_range_pressure",
        "engine": "generic",
        "prefixes": ["sr_prev_gap_", "sr_range_", "sr_atr_", "sr_breakout_", "sr_breakdown_"],
        "novelty": "Uses available support/resistance range, ATR, gap and breakout pressure features.",
    },
    {
        "name": "volatility_acceleration",
        "engine": "generic",
        "prefixes": ["vix_ret_", "vix_z_", "vix_cboe_", "vix_yahoo_", "spy_realized_vol_", "iv_rv_", "vrp_"],
        "novelty": "Searches volatility acceleration and volatility-risk-premium changes, not simple VIX level.",
    },
    {
        "name": "put_call_regime_transitions",
        "engine": "generic",
        "prefixes": ["total_pc_", "vix_", "skew_"],
        "novelty": "Targets transitions in option sentiment regimes, not only contrarian put/call thresholds.",
    },
    {
        "name": "credit_rates_squeeze",
        "engine": "generic",
        "prefixes": ["yield_curve_", "tnx_", "irx_", "spy_realized_vol_", "vix_"],
        "novelty": "Credit ETF features are unavailable here, so this tests rates/volatility squeeze using available public features.",
    },
    {
        "name": "drawdown_recovery_asymmetry",
        "engine": "generic",
        "prefixes": ["spy_drawdown_", "sr_", "spy_ret_", "spy_mom_"],
        "novelty": "Models failed recovery/asymmetry after SPY drawdowns instead of raw trend.",
    },
    {
        "name": "cross_asset_voting_sparse",
        "engine": "generic",
        "prefixes": ["spy_", "vix_", "yield_curve_", "skew_", "total_pc_", "pput_"],
        "novelty": "Sparse cross-asset voting with low feature count to reduce overfit.",
    },
    {
        "name": "low_turnover_tactical_spy",
        "engine": "generic",
        "prefixes": ["spy_ma_gap_", "spy_mom_", "vix_", "yield_curve_"],
        "novelty": "Slow tactical rules with turnover penalty instead of high-churn weekly classifiers.",
    },
    {
        "name": "crash_first_selector",
        "engine": "generic",
        "prefixes": ["spy_drawdown_", "vix_", "skew_", "total_pc_", "yield_curve_"],
        "novelty": "Ranks first by behavior in SPY-stress weeks before overall Sharpe.",
    },
    {
        "name": "anti_2022_train_filter",
        "engine": "generic",
        "prefixes": ["yield_curve_", "tnx_", "irx_", "vix_", "spy_mom_", "spy_realized_vol_"],
        "novelty": "Train-only inflation/rates stress filter designed to avoid 2022-style failure modes without reading locked.",
    },
    {
        "name": "train_only_survivor_ensemble",
        "engine": "ensemble",
        "configs": 1800,
        "novelty": "Combines only prior train-valid survivors; validation remains report-only and does not select members.",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["prepare-data", "time-guard", "round-shard", "round-merge", "final-merge"], required=True)
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--round-index", type=int, default=0)
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--time-budget-minutes", type=float, default=24.0)
    parser.add_argument("--top-per-stage", type=int, default=90)
    parser.add_argument("--stop-new-round-hour", type=int, default=6)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "prepare-data":
        prepare_data(output_dir)
    elif args.mode == "time-guard":
        time_guard(output_dir, args.round_index, args.stop_new_round_hour)
    elif args.mode == "round-shard":
        run_round_shard(output_dir, args.round_index, args.stage, args.time_budget_minutes, args.top_per_stage)
    elif args.mode == "round-merge":
        run_round_merge(output_dir, args.round_index)
    else:
        final_merge(output_dir)


def round_spec(round_index: int) -> dict[str, Any]:
    if round_index < 0 or round_index >= len(ROUND_SPECS):
        raise ValueError(f"Unknown round_index={round_index}")
    spec = dict(ROUND_SPECS[round_index])
    spec["round_index"] = round_index
    return spec


def prepare_data(output_dir: Path) -> None:
    data_root = output_dir / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    weekly_dir = data_root / "weekly"
    cboe_dir = data_root / "cboe"
    ensemble_dir = data_root / "ensemble"
    for folder in (weekly_dir, cboe_dir, ensemble_dir):
        folder.mkdir(parents=True, exist_ok=True)
    weekly.run_data(weekly_dir)
    enrich_weekly_novel_features(weekly_dir)
    cboe.run_data(cboe_dir)
    ensemble.run_data(ensemble_dir)
    audit = {
        "campaign_id": CAMPAIGN_ID,
        "rounds": ROUND_SPECS,
        "train_start": str(TRAIN_START.date()),
        "train_end": str(TRAIN_END.date()),
        "validation_start": str(VALIDATION_START.date()),
        "validation_end": str(VALIDATION_END.date()),
        "locked_start": str(LOCKED_START.date()),
        "locked_opened": False,
        "validation_used_for_selection": False,
        "uses_individual_stocks": False,
        "paper_exact_replication_claimed": False,
    }
    (data_root / "nightly_data_audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    write_data_feature_audit(data_root)


def enrich_weekly_novel_features(weekly_dir: Path) -> None:
    prices_path = weekly_dir / "weekly_prices.csv"
    returns_path = weekly_dir / "weekly_returns.csv"
    if not prices_path.exists() or not returns_path.exists():
        return
    prices = pd.read_csv(prices_path, parse_dates=["timestamp"]).set_index("timestamp")
    returns = pd.read_csv(returns_path, parse_dates=["timestamp"]).set_index("timestamp")
    rich = build_rich_weekly_feature_frame(prices, returns)
    existing_path = weekly_dir / "paper_feature_frame.csv"
    if existing_path.exists() and existing_path.stat().st_size > 0:
        existing = pd.read_csv(existing_path, parse_dates=["timestamp"]).set_index("timestamp")
        combined = existing.join(rich[[c for c in rich.columns if c not in existing.columns]], how="inner")
    else:
        combined = rich
    if combined.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached enriched weekly feature frame")
    combined = combined.replace([np.inf, -np.inf], np.nan).dropna(how="any")
    combined.to_csv(existing_path, index_label="timestamp")
    audit_path = weekly_dir / "paper_feature_audit.csv"
    if audit_path.exists() and audit_path.stat().st_size > 0:
        audit = pd.read_csv(audit_path)
    else:
        audit = pd.DataFrame(columns=["feature", "paper_keys", "paper_titles", "paper_strategy_type", "lagged", "lag_periods"])
    existing_features = set(audit.get("feature", pd.Series(dtype=str)).astype(str))
    rows = []
    for feature in combined.columns:
        if feature in existing_features:
            continue
        rows.append(
            {
                "feature": feature,
                "paper_keys": "faber_ma|mop_tsmom|moreira_muir_vol",
                "paper_titles": "Audit-only public ETF/index feature family",
                "paper_strategy_type": "template",
                "lagged": True,
                "lag_periods": 1,
            }
        )
    if rows:
        audit = pd.concat([audit, pd.DataFrame(rows)], ignore_index=True)
    audit.to_csv(audit_path, index=False)


def write_data_feature_audit(data_root: Path) -> None:
    rows: list[dict[str, Any]] = []
    weekly_audit = data_root / "weekly" / "paper_feature_audit.csv"
    if weekly_audit.exists():
        audit = pd.read_csv(weekly_audit)
        for prefix, frame in audit.assign(prefix=audit["feature"].astype(str).str.split("_").str[0]).groupby("prefix"):
            rows.append(
                {
                    "dataset": "weekly",
                    "feature_group": prefix,
                    "feature_count": int(len(frame)),
                    "locked_opened": False,
                    "uses_individual_stocks": False,
                    "lag_periods_min": int(pd.to_numeric(frame.get("lag_periods", 1), errors="coerce").fillna(1).min()),
                }
            )
    pd.DataFrame(rows).to_csv(data_root / "data_feature_audit.csv", index=False)


def time_guard(output_dir: Path, round_index: int, stop_new_round_hour: int) -> None:
    now = datetime.now(TZ)
    should_run = now.hour >= 18 or now.hour < int(stop_new_round_hour)
    guard_dir = output_dir / "guards"
    guard_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "round_index": round_index,
        "round_name": round_spec(round_index)["name"],
        "checked_at_madrid": now.isoformat(),
        "stop_new_round_hour": int(stop_new_round_hour),
        "should_run": bool(should_run),
    }
    (guard_dir / f"round_{round_index:02d}_guard.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"should_run={'true' if should_run else 'false'}")
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"should_run={'true' if should_run else 'false'}\n")


def run_round_shard(output_dir: Path, round_index: int, stage: int, time_budget_minutes: float, top_per_stage: int) -> None:
    ensure_prepared_data_layout(output_dir)
    spec = round_spec(round_index)
    round_dir = output_dir / "rounds" / f"round_{round_index:02d}_{spec['name']}"
    round_dir.mkdir(parents=True, exist_ok=True)
    if spec["engine"] == "ensemble":
        copy_tree_contents(output_dir / "data" / "ensemble", round_dir)
        ensemble.run_shard(
            round_dir,
            stage=stage + round_index * 10_000,
            total_stages=360,
            configs_per_stage=int(spec.get("configs", 1200)),
        )
        annotate_latest_stage(round_dir, stage, spec)
    elif spec["engine"] == "cboe":
        copy_tree_contents(output_dir / "data" / "cboe", round_dir)
        cboe.run_shard(
            round_dir,
            stage=stage + round_index * 10_000,
            total_stages=360,
            configs_per_stage=int(spec.get("configs", 5_000_000)),
            time_budget_minutes=time_budget_minutes,
            top_per_stage=top_per_stage,
        )
        annotate_latest_stage(round_dir, stage, spec)
    else:
        copy_tree_contents(output_dir / "data" / "weekly", round_dir)
        run_generic_spy_shard(round_dir, spec, stage, time_budget_minutes, top_per_stage)


def ensure_prepared_data_layout(output_dir: Path) -> None:
    data_root = output_dir / "data"
    if (data_root / "weekly").exists() and (data_root / "cboe").exists() and (data_root / "ensemble").exists():
        return
    data_root.mkdir(parents=True, exist_ok=True)
    for name in ("weekly", "cboe", "ensemble"):
        flat = output_dir / name
        target = data_root / name
        if flat.exists() and not target.exists():
            shutil.copytree(flat, target)


def annotate_latest_stage(round_dir: Path, stage: int, spec: dict[str, Any]) -> None:
    stage_dirs = sorted((round_dir / "shards").glob("stage_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not stage_dirs:
        return
    stage_dir = stage_dirs[0]
    visible_dir = round_dir / "shards" / f"stage_{stage:03d}"
    if stage_dir != visible_dir:
        if visible_dir.exists():
            shutil.rmtree(visible_dir)
        stage_dir.rename(visible_dir)
        stage_dir = visible_dir
    meta = {
        "nightly_round_index": spec["round_index"],
        "nightly_round_name": spec["name"],
        "nightly_engine": spec["engine"],
        "display_stage": int(stage),
        "locked_opened": False,
        "validation_used_for_selection": False,
    }
    (stage_dir / "nightly_round_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def run_generic_spy_shard(round_dir: Path, spec: dict[str, Any], stage: int, time_budget_minutes: float, top_per_stage: int) -> None:
    returns = pd.read_csv(round_dir / "weekly_returns.csv", parse_dates=["timestamp"]).set_index("timestamp")
    feature_frame = pd.read_csv(round_dir / "paper_feature_frame.csv", parse_dates=["timestamp"]).set_index("timestamp")
    feature_audit = pd.read_csv(round_dir / "paper_feature_audit.csv")
    feature_papers = {row["feature"]: tuple(str(row["paper_keys"]).split("|")) for _, row in feature_audit.iterrows()}
    if returns.index.max() >= LOCKED_START or feature_frame.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached generic nightly shard")
    feature_cols = list(feature_frame.columns)
    selected = feature_indices_for_prefixes(feature_cols, list(spec.get("prefixes", [])))
    shard_dir = round_dir / "shards" / f"stage_{stage:03d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    if not selected:
        write_unsupported_shard(shard_dir, spec, stage, "no_features_for_round_prefixes")
        return
    spy_rets = returns["SPY"].reindex(feature_frame.index).astype(float)
    train_mask = np.asarray((feature_frame.index >= TRAIN_START) & (feature_frame.index <= TRAIN_END), dtype=bool)
    validation_mask = np.asarray((feature_frame.index >= VALIDATION_START) & (feature_frame.index <= VALIDATION_END), dtype=bool)
    matrix = feature_frame.to_numpy(dtype=float)
    spy_values = spy_rets.to_numpy(dtype=float)
    rng = np.random.default_rng(990_000_007 + spec["round_index"] * 1_000_003 + stage * 10_007)
    deadline = time.monotonic() + max(0.01, float(time_budget_minutes)) * 60.0
    rows: list[dict[str, Any]] = []
    evaluated = 0
    while evaluated < 5_000_000 and time.monotonic() < deadline:
        evaluated += 1
        params = sample_generic_params(rng, selected, spec["round_index"])
        positions, train_metrics = build_positions_train_only(matrix, spy_values, train_mask, params)
        if not np.isfinite(train_metrics["sharpe"]):
            continue
        strategy_returns = positions * spy_values
        if train_metrics["sharpe"] < 0.2 and evaluated % 257 != 0:
            continue
        validation_metrics = metrics(strategy_returns[validation_mask])
        train_returns = strategy_returns[train_mask]
        train_dates = feature_frame.index[train_mask]
        stability = train_only_stability(train_returns, train_dates)
        score = train_only_score(train_metrics, positions[train_mask], params, stability)
        features = [feature_cols[int(i)] for i in params["feature_indices"]]
        paper_keys = weekly.paper_sources_for_features(features, feature_papers)
        train_position = position_audit(positions[train_mask])
        validation_position = position_audit(positions[validation_mask])
        payload = {"round": spec["name"], "params": params, "features": features, "paper_keys": paper_keys}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        rows.append(
            {
                "strategy_id": f"nightly_{spec['name']}_s{stage:03d}_{digest}",
                "candidate_id": f"nightly_{spec['name']}_s{stage:03d}_{digest}",
                "round_index": int(spec["round_index"]),
                "round_name": spec["name"],
                "stage": int(stage),
                "config_index": int(evaluated),
                "train_pass": bool(train_metrics["sharpe"] >= TARGET_SHARPE and train_position["always_invested"]),
                "validation_pass_report_only": bool(validation_metrics["sharpe"] >= TARGET_SHARPE and validation_position["always_invested"]),
                "final_verified_report_only": bool(
                    train_metrics["sharpe"] >= TARGET_SHARPE
                    and validation_metrics["sharpe"] >= TARGET_SHARPE
                    and train_position["always_invested"]
                    and validation_position["always_invested"]
                ),
                "validation_used_for_selection": False,
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "uses_individual_stocks": False,
                "paper_exact_replication_claimed": False,
                "paper_strategy_type": "template_or_proxy",
                "paper_keys": "|".join(paper_keys),
                "paper_titles": "|".join(weekly.PAPER_SOURCES[k]["paper"] for k in paper_keys),
                "source_papers": "|".join(weekly.PAPER_SOURCES[k]["paper"] for k in paper_keys),
                "source_rule_summary": "|".join(weekly.PAPER_SOURCES[k]["rule"] for k in paper_keys),
                "traded_asset": "SPY",
                "frequency": "weekly",
                "lag_periods": 1,
                "lookahead_audit": "Weekly signal is built from prior/available features and traded with one-period causal lag.",
                "proxy_audit": "No individual stocks; paper-derived public index/ETF/benchmark features only.",
                "train_sharpe": float(train_metrics["sharpe"]),
                "validation_sharpe": float(validation_metrics["sharpe"]),
                "train_cagr": float(train_metrics["cagr"]),
                "validation_cagr": float(validation_metrics["cagr"]),
                "train_mdd": float(train_metrics["mdd"]),
                "validation_mdd": float(validation_metrics["mdd"]),
                "train_positive_weeks_pct": float(train_metrics["positive_weeks_pct"]),
                "validation_positive_weeks_pct": float(validation_metrics["positive_weeks_pct"]),
                "train_turnover_weekly": float(turnover(positions[train_mask])),
                "validation_turnover_weekly": float(turnover(positions[validation_mask])),
                "train_always_invested": bool(train_position["always_invested"]),
                "validation_always_invested": bool(validation_position["always_invested"]),
                "rule_type": str(params["rule_type"]),
                "feature_count": int(len(features)),
                "features": "|".join(features),
                "params_json": json.dumps(params, sort_keys=True),
                "train_score": float(score),
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(columns=["strategy_id", "candidate_id", "train_score", "train_sharpe", "validation_sharpe", "final_verified_report_only"])
    top = frame.sort_values(["train_score", "train_sharpe"], ascending=[False, False]).head(int(top_per_stage))
    verified = frame[frame.get("final_verified_report_only", pd.Series(dtype=bool)).astype(bool)]
    diagnostic = frame.sort_values(["validation_sharpe", "train_sharpe"], ascending=[False, False]).head(int(top_per_stage))
    top.to_csv(shard_dir / "top_candidates.csv", index=False)
    verified.to_csv(shard_dir / "verified_candidates_report_only.csv", index=False)
    diagnostic.to_csv(shard_dir / "validation_ceiling_diagnostic.csv", index=False)
    (shard_dir / "shard_summary.json").write_text(
        json.dumps(
            {
                "stage": int(stage),
                "round_index": int(spec["round_index"]),
                "round_name": spec["name"],
                "engine": "generic",
                "configs_evaluated": int(evaluated),
                "rows_kept": int(len(frame)),
                "verified_rows": int(len(verified)),
                "selected_feature_count": int(len(selected)),
                "prefixes": spec.get("prefixes", []),
                "locked_opened": False,
                "validation_used_for_selection": False,
                "uses_individual_stocks": False,
                "paper_exact_replication_claimed": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def feature_indices_for_prefixes(feature_cols: list[str], prefixes: list[str]) -> list[int]:
    if not prefixes:
        return list(range(len(feature_cols)))
    return [i for i, name in enumerate(feature_cols) if any(name.startswith(prefix) for prefix in prefixes)]


def sample_generic_params(rng: np.random.Generator, candidates: list[int], round_index: int) -> dict[str, Any]:
    max_candidates = max(1, len(candidates))
    rule_types = [
        "linear",
        "threshold_vote",
        "signed_stump_vote",
        "logic_majority",
    ]
    rule_type = str(rng.choice(rule_types))
    if rule_type in {"linear", "threshold_vote", "signed_stump_vote"}:
        low, high = 1, min(6, max_candidates)
    elif "ridge" in rule_type:
        low, high = min(3, max_candidates), min(12, max_candidates)
    else:
        low, high = min(2, max_candidates), min(7, max_candidates)
    k = int(rng.integers(low, high + 1)) if high >= low else max_candidates
    feature_indices = rng.choice(candidates, size=k, replace=False)
    weights = rng.normal(0.0, 1.0, size=k)
    norm = float(np.sum(np.abs(weights)))
    weights = weights / norm if norm > 0 else np.ones(k) / k
    return {
        "family": int(round_index),
        "rule_type": rule_type,
        "feature_indices": [int(i) for i in feature_indices],
        "weights": [float(w) for w in weights],
        "thresholds": [float(x) for x in rng.normal(0.0, 1.0, size=k)],
        "quantiles": [float(x) for x in rng.uniform(0.1, 0.9, size=k)],
        "band_widths": [float(x) for x in rng.uniform(0.25, 1.8, size=k)],
        "directions": [float(x) for x in rng.choice([-1.0, 1.0], size=k)],
        "logic_operator": "majority",
        "threshold": float(rng.normal(0.0, 0.15)),
        "ridge_alpha": float(10.0 ** rng.uniform(-2.5, 2.0)),
        "walk_forward_min_train": int(rng.choice([208, 260, 312, 416])),
        "walk_forward_refit_step": int(rng.choice([1, 2, 4, 8, 13])),
        "walk_forward_window": int(rng.choice([0, 260, 390, 520])),
        "ensemble_members": [],
        "invert": int(rng.integers(0, 2)),
    }


def write_unsupported_shard(shard_dir: Path, spec: dict[str, Any], stage: int, reason: str) -> None:
    row = {
        "round_index": int(spec["round_index"]),
        "round_name": spec["name"],
        "stage": int(stage),
        "reason": reason,
        "prefixes": "|".join(spec.get("prefixes", [])),
        "locked_opened": False,
        "validation_used_for_selection": False,
    }
    pd.DataFrame([row]).to_csv(shard_dir / "unsupported.csv", index=False)
    pd.DataFrame(columns=["strategy_id", "candidate_id", "train_score", "train_sharpe", "validation_sharpe"]).to_csv(
        shard_dir / "top_candidates.csv",
        index=False,
    )
    pd.DataFrame(columns=["strategy_id", "candidate_id"]).to_csv(shard_dir / "verified_candidates_report_only.csv", index=False)
    pd.DataFrame(columns=["strategy_id", "candidate_id", "train_sharpe", "validation_sharpe"]).to_csv(
        shard_dir / "validation_ceiling_diagnostic.csv",
        index=False,
    )
    (shard_dir / "shard_summary.json").write_text(
        json.dumps(
            {
                **row,
                "engine": "generic",
                "configs_evaluated": 0,
                "rows_kept": 0,
                "verified_rows": 0,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def run_round_merge(output_dir: Path, round_index: int) -> None:
    spec = round_spec(round_index)
    round_dir = output_dir / "rounds" / f"round_{round_index:02d}_{spec['name']}"
    materialize_downloaded_shards(output_dir, round_dir)
    final = round_dir / "final"
    final.mkdir(parents=True, exist_ok=True)
    if spec["engine"] == "ensemble":
        try:
            ensemble.run_merge(round_dir, total_stages=360, allow_partial=True)
            source = round_dir / "final" / "paper_operable_ensemble_leaderboard.csv"
        except Exception as exc:
            write_round_failure(final, spec, exc)
            return
    elif spec["engine"] == "cboe":
        try:
            cboe.run_merge(round_dir, total_stages=360, allow_partial=True)
            source = round_dir / "final" / "paper_cboe_sentiment_leaderboard.csv"
            if not source.exists():
                source = round_dir / "paper_cboe_sentiment_leaderboard.csv"
        except Exception as exc:
            write_round_failure(final, spec, exc)
            return
    else:
        source = merge_generic_round(round_dir, spec)
    leaderboard = normalize_round_leaderboard(source, spec)
    leaderboard.to_csv(final / "leaderboard.csv", index=False)
    accepted = accepted_rows(leaderboard)
    accepted.to_csv(final / "accepted.csv", index=False)
    unsupported = load_unsupported(round_dir)
    unsupported.to_csv(final / "unsupported.csv", index=False)
    summaries = load_shard_summaries(round_dir)
    pd.DataFrame(summaries).to_csv(final / "shard_summaries.csv", index=False)
    summary = {
        "round_index": int(round_index),
        "round_name": spec["name"],
        "engine": spec["engine"],
        "novelty": spec.get("novelty", ""),
        "status": "loaded",
        "rows": int(len(leaderboard)),
        "accepted_count": int(len(accepted)),
        "unsupported_rows": int(len(unsupported)),
        "shards_found": int(len(summaries)),
        "best_train_sharpe": safe_max(leaderboard, "train_sharpe"),
        "best_validation_sharpe": safe_max(leaderboard, "validation_sharpe"),
        "best_min_train_validation_sharpe": safe_max(leaderboard, "min_train_validation_sharpe"),
        "locked_opened": False,
        "validation_used_for_selection": False,
        "uses_individual_stocks": False,
        "paper_exact_replication_claimed": False,
    }
    (final / "round_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_round_novelty_audit(final, spec, leaderboard, summaries)


def write_round_novelty_audit(final: Path, spec: dict[str, Any], leaderboard: pd.DataFrame, summaries: list[dict[str, Any]]) -> None:
    selected_prefixes = "|".join(spec.get("prefixes", []))
    skipped = bool(spec.get("skipped_duplicate_family", False))
    pd.DataFrame(
        [
            {
                "round_index": int(spec["round_index"]),
                "round_name": spec["name"],
                "engine": spec["engine"],
                "novelty_claim": spec.get("novelty", ""),
                "selected_prefixes": selected_prefixes,
                "rows": int(len(leaderboard)),
                "shards_found": int(len(summaries)),
                "skipped_duplicate_family": skipped,
                "locked_opened": False,
                "validation_used_for_selection": False,
                "uses_individual_stocks": False,
            }
        ]
    ).to_csv(final / "novelty_audit.csv", index=False)


def materialize_downloaded_shards(output_dir: Path, round_dir: Path) -> None:
    shards_dir = round_dir / "shards"
    shards_dir.mkdir(parents=True, exist_ok=True)
    if any(shards_dir.glob("stage_*")):
        return
    downloaded_root = output_dir / "rounds"
    candidates = [p for p in downloaded_root.glob("stage_*") if p.is_dir()]
    candidates += [p for p in downloaded_root.glob("**/stage_*") if p.is_dir() and round_dir not in p.parents]
    seen: set[Path] = set()
    for stage_dir in candidates:
        resolved = stage_dir.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        target = shards_dir / stage_dir.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(stage_dir, target)


def merge_generic_round(round_dir: Path, spec: dict[str, Any]) -> Path:
    top_files = list((round_dir / "shards").glob("**/top_candidates.csv"))
    diag_files = list((round_dir / "shards").glob("**/validation_ceiling_diagnostic.csv"))
    verified_files = list((round_dir / "shards").glob("**/verified_candidates_report_only.csv"))
    top = pd.concat([pd.read_csv(path) for path in top_files], ignore_index=True) if top_files else pd.DataFrame()
    diag = pd.concat([pd.read_csv(path) for path in diag_files], ignore_index=True) if diag_files else pd.DataFrame()
    verified = pd.concat([pd.read_csv(path) for path in verified_files], ignore_index=True) if verified_files else pd.DataFrame()
    if not top.empty:
        top = top.drop_duplicates("strategy_id").sort_values(["train_score", "train_sharpe"], ascending=[False, False])
    if not diag.empty:
        diag = diag.drop_duplicates("strategy_id").sort_values(["validation_sharpe", "train_sharpe"], ascending=[False, False])
    if not verified.empty:
        verified = verified.drop_duplicates("strategy_id")
    top.to_csv(round_dir / "nightly_round_leaderboard.csv", index=False)
    diag.to_csv(round_dir / "nightly_round_validation_ceiling_diagnostic.csv", index=False)
    verified.to_csv(round_dir / "nightly_round_verified.csv", index=False)
    return round_dir / "nightly_round_leaderboard.csv"


def normalize_round_leaderboard(path: Path, spec: dict[str, Any]) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=canonical_columns())
    frame = pd.read_csv(path)
    if frame.empty:
        return pd.DataFrame(columns=canonical_columns())
    out = pd.DataFrame()
    out["round_index"] = int(spec["round_index"])
    out["round_name"] = spec["name"]
    out["strategy_id"] = first_existing(frame, ["strategy_id", "candidate_id"]).fillna("").astype(str)
    out["source_papers"] = first_existing(frame, ["source_papers", "paper_titles", "paper_title", "strategy_name"]).fillna("")
    out["source_rule_summary"] = first_existing(frame, ["source_rule_summary", "rule_summary", "strategy_name"]).fillna("")
    out["paper_strategy_type"] = first_existing(frame, ["paper_strategy_type", "replication_level"]).fillna("template_or_proxy")
    out["traded_asset"] = first_existing(frame, ["traded_asset"]).fillna("SPY_or_operable_paper_proxy")
    out["frequency"] = first_existing(frame, ["frequency"]).fillna("paper_defined")
    out["train_sharpe"] = numeric(first_existing(frame, ["train_sharpe"]))
    out["validation_sharpe"] = numeric(first_existing(frame, ["validation_sharpe"]))
    out["train_cagr_pct"] = numeric(first_existing(frame, ["train_cagr_pct", "train_cagr"]))
    out["validation_cagr_pct"] = numeric(first_existing(frame, ["validation_cagr_pct", "validation_cagr"]))
    out["train_mdd_pct"] = numeric(first_existing(frame, ["train_mdd_pct", "train_mdd"]))
    out["validation_mdd_pct"] = numeric(first_existing(frame, ["validation_mdd_pct", "validation_mdd"]))
    out["locked_opened"] = first_existing(frame, ["locked_opened"]).fillna(False)
    out["validation_used_for_selection"] = first_existing(frame, ["validation_used_for_selection"]).fillna(False)
    out["uses_individual_stocks"] = first_existing(frame, ["uses_individual_stocks"]).fillna(False)
    out["paper_exact_replication_claimed"] = first_existing(frame, ["paper_exact_replication_claimed"]).fillna(False)
    out["lookahead_audit"] = first_existing(frame, ["lookahead_audit", "lag_audit"]).fillna("Lag causal audited in round policy.")
    out["proxy_audit"] = first_existing(frame, ["proxy_audit"]).fillna("No individual stocks; proxy/template status retained.")
    out["raw_status"] = first_existing(frame, ["status", "accepted", "final_verified_report_only"]).fillna("evaluated")
    out["min_train_validation_sharpe"] = out[["train_sharpe", "validation_sharpe"]].min(axis=1)
    return out[canonical_columns()]


def final_merge(output_dir: Path) -> None:
    final = output_dir / "final"
    final.mkdir(parents=True, exist_ok=True)
    leaderboard_files = list((output_dir / "rounds").glob("**/final/leaderboard.csv")) + list(
        (output_dir / "round_final_downloads").glob("**/leaderboard.csv")
    )
    summary_files = list((output_dir / "rounds").glob("**/final/round_summary.json")) + list(
        (output_dir / "round_final_downloads").glob("**/round_summary.json")
    )
    unsupported_files = list((output_dir / "rounds").glob("**/final/unsupported.csv")) + list(
        (output_dir / "round_final_downloads").glob("**/unsupported.csv")
    )
    novelty_files = list((output_dir / "rounds").glob("**/final/novelty_audit.csv")) + list(
        (output_dir / "round_final_downloads").glob("**/novelty_audit.csv")
    )
    frames = [pd.read_csv(path) for path in leaderboard_files if path.exists() and path.stat().st_size > 0]
    leaderboard = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=canonical_columns())
    if not leaderboard.empty:
        leaderboard = leaderboard.drop_duplicates("strategy_id", keep="first")
        leaderboard = leaderboard.sort_values(
            ["min_train_validation_sharpe", "train_sharpe", "validation_sharpe"],
            ascending=[False, False, False],
        )
    accepted = accepted_rows(leaderboard)
    near_misses = leaderboard[~leaderboard["strategy_id"].isin(set(accepted["strategy_id"]))].head(500).copy() if not leaderboard.empty else pd.DataFrame(columns=canonical_columns())
    unsupported_frames = []
    for path in unsupported_files:
        try:
            unsupported_frames.append(pd.read_csv(path))
        except EmptyDataError:
            continue
    unsupported = pd.concat(unsupported_frames, ignore_index=True) if unsupported_frames else pd.DataFrame()
    novelty_frames = []
    for path in novelty_files:
        try:
            novelty_frames.append(pd.read_csv(path))
        except EmptyDataError:
            continue
    novelty = pd.concat(novelty_frames, ignore_index=True) if novelty_frames else pd.DataFrame(
        columns=[
            "round_index",
            "round_name",
            "engine",
            "novelty_claim",
            "selected_prefixes",
            "rows",
            "shards_found",
            "skipped_duplicate_family",
            "locked_opened",
            "validation_used_for_selection",
            "uses_individual_stocks",
        ]
    )
    summaries = []
    for path in summary_files:
        try:
            summaries.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    leaderboard.to_csv(final / "leaderboard_all.csv", index=False)
    accepted.to_csv(final / "accepted_strategies.csv", index=False)
    near_misses.to_csv(final / "near_misses.csv", index=False)
    unsupported.to_csv(final / "unsupported.csv", index=False)
    novelty.to_csv(final / "novelty_audit.csv", index=False)
    pd.DataFrame(summaries).to_csv(final / "leaderboard_by_round.csv", index=False)
    build_fail_reasons(leaderboard).to_csv(final / "fail_reasons.csv", index=False)
    build_paper_source_audit(leaderboard).to_csv(final / "paper_source_audit.csv", index=False)
    build_lookahead_audit(leaderboard).to_csv(final / "lookahead_audit.csv", index=False)
    build_runtime_audit(summaries).to_csv(final / "round_runtime_audit.csv", index=False)
    locked_audit = {
        "locked_opened": False,
        "validation_used_for_selection": False,
        "any_locked_opened_in_rows": bool((leaderboard.get("locked_opened", pd.Series(dtype=object)).astype(str).str.lower() == "true").any()) if not leaderboard.empty else False,
        "any_validation_used_for_selection_in_rows": bool((leaderboard.get("validation_used_for_selection", pd.Series(dtype=object)).astype(str).str.lower() == "true").any()) if not leaderboard.empty else False,
    }
    (final / "locked_audit.json").write_text(json.dumps(locked_audit, indent=2), encoding="utf-8")
    copy_data_feature_audit(output_dir, final)
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "accepted_count": int(len(accepted)),
        "rows_total": int(len(leaderboard)),
        "rounds_configured": int(len(ROUND_SPECS)),
        "rounds_with_results": int(len(summaries)),
        "rounds_skipped_or_missing": int(len(ROUND_SPECS) - len({int(s.get("round_index", -1)) for s in summaries})),
        "rounds_started": int(len({int(s.get("round_index", -1)) for s in summaries})),
        "rounds_completed": int(len([s for s in summaries if str(s.get("status", "")).lower() in {"loaded", "success"}])),
        "rounds_skipped_duplicate": int(
            novelty.get("skipped_duplicate_family", pd.Series(dtype=object)).astype(str).str.lower().isin({"true", "1"}).sum()
        )
        if not novelty.empty
        else 0,
        "best_train_sharpe": safe_max(leaderboard, "train_sharpe"),
        "best_validation_sharpe": safe_max(leaderboard, "validation_sharpe"),
        "best_min_train_validation_sharpe": safe_max(leaderboard, "min_train_validation_sharpe"),
        "locked_opened": False,
        "validation_used_for_selection": False,
        "uses_individual_stocks": False,
        "paper_exact_replication_claimed": False,
        "artifact_main_table": "accepted_strategies.csv" if len(accepted) else "near_misses.csv",
    }
    (final / "nightly_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def copy_data_feature_audit(output_dir: Path, final: Path) -> None:
    candidates = [
        output_dir / "data" / "data_feature_audit.csv",
        output_dir / "data_feature_audit.csv",
    ]
    for path in candidates:
        if path.exists() and path.stat().st_size > 0:
            shutil.copy2(path, final / "data_feature_audit.csv")
            return
    pd.DataFrame(
        [
            {
                "dataset": "unknown",
                "feature_group": "missing",
                "feature_count": 0,
                "locked_opened": False,
                "uses_individual_stocks": False,
                "lag_periods_min": 1,
            }
        ]
    ).to_csv(final / "data_feature_audit.csv", index=False)


def copy_tree_contents(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(src)
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def write_round_failure(final: Path, spec: dict[str, Any], exc: Exception) -> None:
    final.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=canonical_columns()).to_csv(final / "leaderboard.csv", index=False)
    pd.DataFrame(columns=canonical_columns()).to_csv(final / "accepted.csv", index=False)
    pd.DataFrame([{"round_index": spec["round_index"], "round_name": spec["name"], "reason": f"merge_failed:{exc}"}]).to_csv(
        final / "unsupported.csv",
        index=False,
    )
    (final / "round_summary.json").write_text(
        json.dumps(
            {
                "round_index": int(spec["round_index"]),
                "round_name": spec["name"],
                "engine": spec["engine"],
                "novelty": spec.get("novelty", ""),
                "status": "merge_failed",
                "error": str(exc),
                "locked_opened": False,
                "validation_used_for_selection": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    write_round_novelty_audit(final, spec, pd.DataFrame(), [])


def load_shard_summaries(round_dir: Path) -> list[dict[str, Any]]:
    summaries = []
    for path in (round_dir / "shards").glob("**/shard_summary.json"):
        try:
            summaries.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    for path in (round_dir / "shards").glob("**/stage_summary.json"):
        try:
            summaries.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return summaries


def load_unsupported(round_dir: Path) -> pd.DataFrame:
    files = list((round_dir / "shards").glob("**/unsupported.csv"))
    return pd.concat([pd.read_csv(path) for path in files], ignore_index=True) if files else pd.DataFrame()


def first_existing(frame: pd.DataFrame, names: list[str]) -> pd.Series:
    for name in names:
        if name in frame:
            return frame[name]
    return pd.Series([np.nan] * len(frame))


def numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def accepted_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    return frame[
        (frame["train_sharpe"] >= TARGET_SHARPE)
        & (frame["validation_sharpe"] >= TARGET_SHARPE)
        & (frame["locked_opened"].astype(str).str.lower() == "false")
        & (frame["validation_used_for_selection"].astype(str).str.lower() == "false")
        & (frame["uses_individual_stocks"].astype(str).str.lower() == "false")
    ].copy()


def build_fail_reasons(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["reason", "count"])
    reasons = []
    for _, row in frame.iterrows():
        if float(row.get("train_sharpe", -999.0)) >= TARGET_SHARPE and float(row.get("validation_sharpe", -999.0)) >= TARGET_SHARPE:
            reasons.append("accepted")
        elif float(row.get("train_sharpe", -999.0)) < TARGET_SHARPE:
            reasons.append("train_sharpe_below_2")
        elif float(row.get("validation_sharpe", -999.0)) < TARGET_SHARPE:
            reasons.append("validation_sharpe_below_2_report_only")
        else:
            reasons.append("other")
    return pd.Series(reasons).value_counts().rename_axis("reason").reset_index(name="count")


def build_paper_source_audit(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["source_papers", "rows", "best_min_train_validation_sharpe"])
    return (
        frame.groupby("source_papers", dropna=False)
        .agg(rows=("strategy_id", "count"), best_min_train_validation_sharpe=("min_train_validation_sharpe", "max"))
        .reset_index()
        .sort_values(["best_min_train_validation_sharpe", "rows"], ascending=[False, False])
    )


def build_lookahead_audit(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["lookahead_audit", "rows"])
    return frame["lookahead_audit"].fillna("missing").value_counts().rename_axis("lookahead_audit").reset_index(name="rows")


def build_runtime_audit(summaries: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for index, spec in enumerate(ROUND_SPECS):
        found = [s for s in summaries if int(s.get("round_index", -1)) == index]
        if found:
            rows.append(found[0])
        else:
            rows.append({"round_index": index, "round_name": spec["name"], "status": "missing_or_skipped"})
    return pd.DataFrame(rows)


def safe_max(frame: pd.DataFrame, column: str) -> float | None:
    if frame.empty or column not in frame:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.max()) if not values.empty else None


def canonical_columns() -> list[str]:
    return [
        "round_index",
        "round_name",
        "strategy_id",
        "source_papers",
        "source_rule_summary",
        "paper_strategy_type",
        "traded_asset",
        "frequency",
        "train_sharpe",
        "validation_sharpe",
        "min_train_validation_sharpe",
        "train_cagr_pct",
        "validation_cagr_pct",
        "train_mdd_pct",
        "validation_mdd_pct",
        "locked_opened",
        "validation_used_for_selection",
        "uses_individual_stocks",
        "paper_exact_replication_claimed",
        "lookahead_audit",
        "proxy_audit",
        "raw_status",
    ]


if __name__ == "__main__":
    main()
