from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import run_paper_spy_weekly_sharpe2 as base
from scripts.run_spy_weekly_longshort_sharpe2 import (
    build_positions_train_only,
    metrics,
    position_audit,
    turnover,
)


CAMPAIGN_ID = "paper_spy_weekly_regime_sharpe2_360jobs"
TRAIN_START = pd.Timestamp("1995-01-01")
TRAIN_END = pd.Timestamp("2010-12-31")
VALIDATION_START = pd.Timestamp("2011-01-01")
VALIDATION_END = pd.Timestamp("2020-12-31")
LOCKED_START = pd.Timestamp("2021-01-01")
TARGET_SHARPE = 2.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["data", "shard", "merge"], required=True)
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--configs-per-stage", type=int, default=5_000_000)
    parser.add_argument("--time-budget-minutes", type=float, default=2.0)
    parser.add_argument("--top-per-stage", type=int, default=120)
    parser.add_argument("--search-style", choices=["regime", "simple"], default="regime")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "data":
        base.run_data(output_dir)
    elif args.mode == "shard":
        run_shard(
            output_dir,
            stage=args.stage,
            configs_per_stage=args.configs_per_stage,
            time_budget_minutes=args.time_budget_minutes,
            top_per_stage=args.top_per_stage,
            search_style=args.search_style,
        )
    else:
        run_merge(output_dir)


def sample_regime_params(rng: np.random.Generator, feature_cols: list[str], stage: int) -> dict[str, Any]:
    groups = [
        ["spy_mom_", "spy_ma_gap_", "spy_drawdown_", "vix_"],
        ["vix_", "vxo_", "vixmo_", "vrp_", "iv_rv_", "vix_term_"],
        ["total_pc_", "skew_", "vix_"],
        ["skew_", "spy_mom_", "spy_drawdown_", "total_pc_"],
        ["pput_", "bxy_", "bxmd_", "cmbo_", "puty_", "vrp_"],
        ["yield_curve_", "vix_", "spy_realized_vol_", "vrp_"],
        ["spy_mom_", "spy_ma_gap_", "total_pc_", "skew_", "vix_term_"],
        ["vix_", "btz_", "vrp_", "iv_rv_", "spy_realized_vol_"],
    ]
    group = groups[stage % len(groups)]
    candidates = [i for i, name in enumerate(feature_cols) if any(name.startswith(token) for token in group)]
    if not candidates:
        candidates = list(range(len(feature_cols)))
    max_candidates = max(1, len(candidates))
    rule_types = [
        "cv_era_leaf_tree",
        "split_guard_leaf_tree",
        "time_split_leaf_tree",
        "multi_era_leaf_tree",
        "cv_ridge_model",
        "cv_quadratic_ridge_model",
        "walk_forward_ridge_model",
        "walk_forward_quadratic_ridge_model",
        "logic_majority",
        "signed_stump_vote",
        "threshold_vote",
    ]
    rule_type = str(
        rng.choice(
            rule_types,
            p=[0.13, 0.15, 0.13, 0.08, 0.13, 0.13, 0.09, 0.09, 0.03, 0.02, 0.02],
        )
    )
    if "ridge" in rule_type:
        low = min(4, max_candidates)
        high = min(12 if "quadratic" in rule_type else 18, max_candidates)
    elif "leaf_tree" in rule_type:
        low = min(3, max_candidates)
        high = min(8, max_candidates)
    else:
        low = min(2, max_candidates)
        high = min(6, max_candidates)
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
        "band_widths": [float(x) for x in rng.uniform(0.25, 1.75, size=k)],
        "directions": [float(x) for x in rng.choice([-1.0, 1.0], size=k)],
        "logic_operator": "majority",
        "threshold": float(rng.normal(0.0, 0.18)),
        "ridge_alpha": float(10.0 ** rng.uniform(-2.5, 2.0)),
        "walk_forward_min_train": int(rng.choice([208, 260, 312, 416])),
        "walk_forward_refit_step": int(rng.choice([1, 2, 4, 8, 13])),
        "walk_forward_window": int(rng.choice([0, 260, 390, 520])),
        "ensemble_members": [],
        "invert": int(rng.integers(0, 2)),
    }


def sample_simple_params(rng: np.random.Generator, feature_cols: list[str], stage: int) -> dict[str, Any]:
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
    rule_type = str(rng.choice(["linear", "threshold_vote", "signed_stump_vote", "logic_majority"], p=[0.35, 0.25, 0.25, 0.15]))
    high = min(4 if rule_type != "linear" else 5, max_candidates)
    low = min(1 if rule_type != "logic_majority" else 2, high)
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
        "thresholds": [float(x) for x in rng.normal(0.0, 0.75, size=k)],
        "quantiles": [float(x) for x in rng.uniform(0.2, 0.8, size=k)],
        "band_widths": [float(x) for x in rng.uniform(0.5, 1.5, size=k)],
        "directions": [float(x) for x in rng.choice([-1.0, 1.0], size=k)],
        "logic_operator": "majority",
        "threshold": float(rng.normal(0.0, 0.12)),
        "ridge_alpha": 1.0,
        "walk_forward_min_train": 260,
        "walk_forward_refit_step": 4,
        "walk_forward_window": 0,
        "ensemble_members": [],
        "invert": int(rng.integers(0, 2)),
    }


def regime_stability(strategy_returns: np.ndarray, dates: pd.DatetimeIndex) -> dict[str, float]:
    eras = [
        ("1995_1998", pd.Timestamp("1995-01-01"), pd.Timestamp("1998-12-31")),
        ("1999_2002", pd.Timestamp("1999-01-01"), pd.Timestamp("2002-12-31")),
        ("2003_2006", pd.Timestamp("2003-01-01"), pd.Timestamp("2006-12-31")),
        ("2007_2010", pd.Timestamp("2007-01-01"), pd.Timestamp("2010-12-31")),
    ]
    out: dict[str, float] = {}
    sharpes: list[float] = []
    cagrs: list[float] = []
    mdds: list[float] = []
    for name, start, end in eras:
        mask = (dates >= start) & (dates <= end)
        row = metrics(strategy_returns[mask])
        sharpe = float(row["sharpe"])
        cagr = float(row["cagr"])
        mdd = float(row["mdd"])
        out[f"train_{name}_sharpe"] = sharpe
        out[f"train_{name}_cagr"] = cagr
        out[f"train_{name}_mdd"] = mdd
        if np.isfinite(sharpe):
            sharpes.append(sharpe)
        if np.isfinite(cagr):
            cagrs.append(cagr)
        if np.isfinite(mdd):
            mdds.append(mdd)
    out["train_min_era_sharpe"] = float(np.min(sharpes)) if sharpes else -99.0
    out["train_avg_era_sharpe"] = float(np.mean(sharpes)) if sharpes else -99.0
    out["train_positive_era_pct"] = float(np.mean(np.asarray(cagrs) > 0.0)) if cagrs else 0.0
    out["train_worst_era_mdd"] = float(np.min(mdds)) if mdds else -1.0
    return out


def regime_score(train_metrics: dict[str, float], positions: np.ndarray, params: dict[str, Any], stability: dict[str, float]) -> float:
    sharpe = float(train_metrics["sharpe"])
    cagr = float(train_metrics["cagr"])
    mdd = float(train_metrics["mdd"])
    min_era = float(stability.get("train_min_era_sharpe", -99.0))
    avg_era = float(stability.get("train_avg_era_sharpe", -99.0))
    pos_era = float(stability.get("train_positive_era_pct", 0.0))
    cv_sharpe = float(params.get("cv_train_sharpe", np.nan))
    cv_min_fold = float(params.get("cv_min_fold_sharpe", np.nan))
    cv_fold_positive = float(params.get("cv_fold_positive_pct", np.nan))
    turn = turnover(positions)
    score = (
        sharpe * 650_000.0
        + max(-2.0, min_era) * 950_000.0
        + max(-2.0, avg_era) * 250_000.0
        + pos_era * 320_000.0
        + cagr * 280_000.0
        - abs(mdd) * 520_000.0
        - turn * 90_000.0
    )
    if np.isfinite(cv_sharpe):
        score += cv_sharpe * 420_000.0
        score -= max(0.0, sharpe - cv_sharpe) * 180_000.0
    if np.isfinite(cv_min_fold):
        score += max(-2.0, cv_min_fold) * 260_000.0
    if np.isfinite(cv_fold_positive):
        score += cv_fold_positive * 110_000.0
    if min_era < 0.0:
        score -= abs(min_era) * 600_000.0
    if pos_era < 1.0:
        score -= (1.0 - pos_era) * 300_000.0
    return float(score)


def run_shard(
    output_dir: Path,
    *,
    stage: int,
    configs_per_stage: int,
    time_budget_minutes: float,
    top_per_stage: int,
    search_style: str,
) -> None:
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
    rng = np.random.default_rng(20260608 + int(stage) * 1_000_003)
    deadline = time.monotonic() + max(1.0, float(time_budget_minutes)) * 60.0
    rows: list[dict[str, Any]] = []
    evaluated = 0
    for config_index in range(int(configs_per_stage)):
        if time.monotonic() >= deadline:
            break
        evaluated += 1
        if search_style == "simple":
            params = sample_simple_params(rng, feature_cols, stage)
        else:
            params = sample_regime_params(rng, feature_cols, stage)
        positions, train_metrics = build_positions_train_only(matrix, spy_values, train_mask, params)
        if not np.isfinite(train_metrics["sharpe"]):
            continue
        strategy_returns = positions * spy_values
        if train_metrics["sharpe"] < 0.15 and config_index % 251 != 0:
            continue
        train_returns = strategy_returns[train_mask]
        train_dates = feature_frame.index[train_mask]
        stability = regime_stability(train_returns, train_dates)
        train_score = regime_score(train_metrics, positions[train_mask], params, stability)
        validation_metrics = metrics(strategy_returns[validation_mask])
        features = [feature_cols[int(i)] for i in params["feature_indices"]]
        paper_keys = base.paper_sources_for_features(features, feature_papers)
        train_position = position_audit(positions[train_mask])
        validation_position = position_audit(positions[validation_mask])
        pass_train = bool(train_metrics["sharpe"] >= TARGET_SHARPE and train_position["always_invested"])
        pass_validation = bool(validation_metrics["sharpe"] >= TARGET_SHARPE and validation_position["always_invested"])
        payload = {"params": params, "paper_keys": paper_keys, "features": features, "search_style": search_style}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        row = {
            "strategy_id": f"paper_spy_weekly_regime_sharpe2_s{stage:03d}_{digest}",
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
            "search_style": search_style,
            "paper_keys": "|".join(paper_keys),
            "paper_titles": "|".join(base.PAPER_SOURCES[k]["paper"] for k in paper_keys),
            "paper_authors": "|".join(base.PAPER_SOURCES[k]["authors"] for k in paper_keys),
            "source_rule_summary": "|".join(base.PAPER_SOURCES[k]["rule"] for k in paper_keys),
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
        row.update(stability)
        rows.append(row)
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
                "search_style": search_style,
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
    top.to_csv(output_dir / "paper_spy_weekly_regime_sharpe2_leaderboard.csv", index=False)
    verified.to_csv(output_dir / "paper_spy_weekly_regime_sharpe2_verified.csv", index=False)
    diagnostic.to_csv(output_dir / "paper_spy_weekly_regime_sharpe2_validation_ceiling_diagnostic.csv", index=False)
    build_fail_reasons(top).to_csv(output_dir / "paper_spy_weekly_regime_sharpe2_fail_reasons.csv", index=False)
    summaries = []
    for path in summary_files:
        try:
            summaries.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    pd.DataFrame(summaries).to_csv(output_dir / "paper_spy_weekly_regime_sharpe2_shard_summaries.csv", index=False)
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
        "best_min_train_era_sharpe": float(top["train_min_era_sharpe"].max()) if "train_min_era_sharpe" in top else None,
        "locked_opened": False,
        "locked_rows_accessed": 0,
        "validation_used_for_selection": False,
        "paper_exact_replication_claimed": False,
        "paper_sourced_only": True,
        "paper_strategy_type": "template_or_proxy",
        "selection_logic": "train-only regime/subperiod score; validation is report-only",
        "train_start": str(TRAIN_START.date()),
        "train_end": str(TRAIN_END.date()),
        "validation_start": str(VALIDATION_START.date()),
        "validation_end": str(VALIDATION_END.date()),
        "locked_start": str(LOCKED_START.date()),
    }
    (output_dir / "paper_spy_weekly_regime_sharpe2_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


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
