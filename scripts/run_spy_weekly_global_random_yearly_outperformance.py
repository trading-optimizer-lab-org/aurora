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

from scripts import run_spy_weekly_noleverage_50ideas_v2 as base
from scripts.run_spy_weekly_noleverage_global_random import (
    CAMPAIGN_ID as SOURCE_CAMPAIGN_ID,
    GLOBAL_RANDOM_IDEA_SPECS,
    LOCKED_START,
    STRATEGY_PREFIX as SOURCE_STRATEGY_PREFIX,
    activated_base_campaign,
)


CAMPAIGN_ID = "spy_weekly_global_random_yearly_outperformance"
ARTIFACT_NAME = "spy-weekly-global-random-yearly-outperformance-results"
TRAIN_YEARLY_CALMAR_ARTIFACT_NAME = "spy-weekly-global-random-train-yearly-calmar-results"
FILTER_TRAIN_VALID_YEARLY_GT_SPY = "train_valid_yearly_gt_spy"
FILTER_TRAIN_YEARLY_GE_SPY_AND_CALMAR_GE_SPY = "train_yearly_ge_spy_and_train_calmar_ge_spy"
TRAIN_START = base.TRAIN_START
TRAIN_END = base.TRAIN_END
VALIDATION_START = base.VALIDATION_START
VALIDATION_END = base.VALIDATION_END
synthetic_weekly_panel = base.synthetic_weekly_panel


def main() -> None:
    base.require_github_actions_or_explicit_local_permission("SPY weekly global random yearly outperformance")
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["shard", "merge"], required=True)
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--configs-per-stage", type=int, default=30_000)
    parser.add_argument("--time-budget-minutes", type=float, default=24.0)
    parser.add_argument("--cost-bps", type=float, default=1.0)
    parser.add_argument(
        "--filter-mode",
        choices=[FILTER_TRAIN_VALID_YEARLY_GT_SPY, FILTER_TRAIN_YEARLY_GE_SPY_AND_CALMAR_GE_SPY],
        default=FILTER_TRAIN_VALID_YEARLY_GT_SPY,
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "shard":
        run_shard(
            output_dir,
            stage=int(args.stage),
            configs_per_stage=int(args.configs_per_stage),
            time_budget_minutes=float(args.time_budget_minutes),
            cost_bps=float(args.cost_bps),
            filter_mode=str(args.filter_mode),
        )
    else:
        merge(output_dir, filter_mode=str(args.filter_mode))


def relaxed_acceptance(train: dict[str, float], validation: dict[str, float]) -> bool:
    return bool(
        float(train["total_return"]) > 0.0
        and float(validation["total_return"]) > 0.0
        and float(validation["profit_factor"]) >= 1.05
    )


def yearly_outperformance(
    index: pd.DatetimeIndex,
    strategy_returns: np.ndarray,
    spy_returns: np.ndarray,
    mask: np.ndarray,
    *,
    inclusive: bool = False,
) -> dict[str, Any]:
    if not bool(np.any(mask)):
        return {"pass": False, "years": "", "min_excess": np.nan}
    frame = pd.DataFrame(
        {
            "year": index[mask].year,
            "strategy": np.asarray(strategy_returns, dtype=float)[mask],
            "spy": np.asarray(spy_returns, dtype=float)[mask],
        }
    )
    annual = frame.groupby("year", sort=True)[["strategy", "spy"]].sum()
    excess = annual["strategy"] - annual["spy"]
    return {
        "pass": bool((excess >= 0.0).all() if inclusive else (excess > 0.0).all()),
        "years": "|".join(str(int(year)) for year in annual.index),
        "min_excess": float(excess.min()) if len(excess) else np.nan,
    }


def calmar_ratio(returns: np.ndarray) -> float:
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 3:
        return np.nan
    total_return = float(np.prod(1.0 + values) - 1.0)
    nav = np.cumprod(1.0 + values)
    mdd = float(np.min(nav / np.maximum.accumulate(nav) - 1.0))
    if mdd == 0.0:
        return np.inf if total_return > 0.0 else 0.0
    years = len(values) / float(base.PPY)
    cagr = float((1.0 + total_return) ** (1.0 / years) - 1.0) if total_return > -1.0 and years > 0.0 else -1.0
    return float(cagr / abs(mdd))


def filter_rule_text(filter_mode: str) -> str:
    if filter_mode == FILTER_TRAIN_YEARLY_GE_SPY_AND_CALMAR_GE_SPY:
        return "strategy annual simple return >= SPY annual simple return for every calendar year in train, and train Calmar >= SPY train Calmar"
    return "strategy annual simple return > SPY annual simple return for every calendar year in train and validation"


def run_shard(
    output_dir: Path,
    *,
    stage: int,
    configs_per_stage: int,
    time_budget_minutes: float,
    cost_bps: float,
    filter_mode: str = FILTER_TRAIN_VALID_YEARLY_GT_SPY,
) -> None:
    panel = pd.read_csv(output_dir / "weekly_panel_no_locked.csv", parse_dates=["timestamp"]).set_index("timestamp")
    if panel.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached yearly outperformance shard")

    with activated_base_campaign():
        feature_cols = base.feature_columns(panel)
        train_mask = np.asarray((panel.index >= TRAIN_START) & (panel.index <= TRAIN_END), dtype=bool)
        validation_mask = np.asarray((panel.index >= VALIDATION_START) & (panel.index <= VALIDATION_END), dtype=bool)
        matrix = panel[feature_cols].to_numpy(dtype=float)
        spy_returns = panel["spy_return"].to_numpy(dtype=float)
        spy_train_calmar = calmar_ratio(spy_returns[train_mask])
        idea = GLOBAL_RANDOM_IDEA_SPECS[stage % len(GLOBAL_RANDOM_IDEA_SPECS)]
        rng = np.random.default_rng(20260618 + int(stage) * 1_000_003)
        deadline = time.monotonic() + max(0.01, float(time_budget_minutes)) * 60.0

        rows: list[dict[str, Any]] = []
        summary = {
            "stage": int(stage),
            "idea_id": idea["idea_id"],
            "idea_family": idea["idea_family"],
            "configs_evaluated": 0,
            "policy_pass_rows": 0,
            "relaxed_rows": 0,
            "yearly_outperform_rows": 0,
            "filter_mode": filter_mode,
            "spy_train_calmar": spy_train_calmar,
            "locked_opened": False,
            "validation_used_for_selection": False,
        }

        while summary["configs_evaluated"] < int(configs_per_stage) and time.monotonic() < deadline:
            summary["configs_evaluated"] += 1
            params = base.sample_params(rng, feature_cols, idea, stage=stage)
            params["campaign_id"] = SOURCE_CAMPAIGN_ID
            scores = base.build_scores(matrix, params)
            positions, _, fit = base.choose_discrete_positions_train_only(scores, spy_returns, train_mask)
            params.update(fit)
            policy = base.position_policy_audit(positions)
            if not policy["policy_pass"]:
                continue
            summary["policy_pass_rows"] += 1

            strategy_returns = base.apply_costs(positions, spy_returns, cost_bps)
            train_metrics = base.metrics(strategy_returns[train_mask])
            validation_metrics = base.metrics(strategy_returns[validation_mask])
            if not relaxed_acceptance(train_metrics, validation_metrics):
                continue
            summary["relaxed_rows"] += 1

            train_years = yearly_outperformance(
                panel.index,
                strategy_returns,
                spy_returns,
                train_mask,
                inclusive=filter_mode == FILTER_TRAIN_YEARLY_GE_SPY_AND_CALMAR_GE_SPY,
            )
            validation_years = yearly_outperformance(panel.index, strategy_returns, spy_returns, validation_mask)
            train_calmar = calmar_ratio(strategy_returns[train_mask])
            if filter_mode == FILTER_TRAIN_YEARLY_GE_SPY_AND_CALMAR_GE_SPY:
                rule_pass = bool(train_years["pass"] and train_calmar >= spy_train_calmar)
            else:
                rule_pass = bool(train_years["pass"] and validation_years["pass"])
            if not rule_pass:
                continue
            summary["yearly_outperform_rows"] += 1

            features = [feature_cols[int(i)] for i in params["feature_indices"]]
            payload = {"idea_id": idea["idea_id"], "params": params, "features": features}
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
            train_position = base.position_summary(positions[train_mask])
            validation_position = base.position_summary(positions[validation_mask])
            rows.append(
                {
                    "strategy_id": f"{SOURCE_STRATEGY_PREFIX}_s{stage:03d}_{digest}",
                    "stage": int(stage),
                    "config_index": int(summary["configs_evaluated"]),
                    "idea_id": idea["idea_id"],
                    "idea_family": idea["idea_family"],
                    "traded_asset": "SPY",
                    "frequency": "weekly",
                    "position_policy": "discrete_long_flat_short_no_leverage",
                    "unique_positions": policy["unique_positions"],
                    "max_abs_position": policy["max_abs_position"],
                    "cash_allowed": True,
                    "leverage_allowed": False,
                    "locked_opened": False,
                    "validation_used_for_selection": False,
                    "train_sharpe": train_metrics["sharpe"],
                    "validation_sharpe": validation_metrics["sharpe"],
                    "train_total_return": train_metrics["total_return"],
                    "validation_total_return": validation_metrics["total_return"],
                    "train_profit_factor": train_metrics["profit_factor"],
                    "validation_profit_factor": validation_metrics["profit_factor"],
                    "train_calmar": train_calmar,
                    "spy_train_calmar": spy_train_calmar,
                    "train_calmar_excess_vs_spy": float(train_calmar - spy_train_calmar),
                    "train_mdd": train_metrics["mdd"],
                    "validation_mdd": validation_metrics["mdd"],
                    "train_trades": train_metrics["trades"],
                    "validation_trades": validation_metrics["trades"],
                    "train_abs_exposure_mean": train_position["abs_exposure_mean"],
                    "validation_abs_exposure_mean": validation_position["abs_exposure_mean"],
                    "train_years": train_years["years"],
                    "validation_years": validation_years["years"],
                    "train_min_annual_excess_vs_spy": train_years["min_excess"],
                    "validation_min_annual_excess_vs_spy": validation_years["min_excess"],
                    "features": "|".join(features),
                    "params_json": json.dumps(params, sort_keys=True),
                }
            )

    shard_dir = output_dir / "shards" / f"stage_{stage:03d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    columns = yearly_columns()
    pd.DataFrame(rows, columns=columns).to_csv(shard_dir / "yearly_outperform.csv", index=False)
    (shard_dir / "yearly_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def merge(output_dir: Path, *, filter_mode: str = FILTER_TRAIN_VALID_YEARLY_GT_SPY) -> None:
    final = output_dir / "final"
    final.mkdir(parents=True, exist_ok=True)
    rows = concat_csv(list((output_dir / "shards").glob("**/yearly_outperform.csv")))
    summaries = []
    for path in (output_dir / "shards").glob("**/yearly_summary.json"):
        try:
            summaries.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    if not rows.empty:
        sort_cols = ["train_calmar_excess_vs_spy", "train_min_annual_excess_vs_spy", "validation_total_return"]
        sort_cols = [col for col in sort_cols if col in rows.columns]
        rows = rows.drop_duplicates("strategy_id").sort_values(
            sort_cols or ["validation_total_return", "train_total_return", "validation_profit_factor"],
            ascending=[False] * len(sort_cols) if sort_cols else [False, False, False],
        )
    rows.to_csv(final / "yearly_outperform.csv", index=False)
    pd.DataFrame(summaries).to_csv(final / "stage_summaries.csv", index=False)
    summary_frame = pd.DataFrame(summaries)
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "source_campaign_id": SOURCE_CAMPAIGN_ID,
        "configs_evaluated": int(summary_frame["configs_evaluated"].sum()) if not summary_frame.empty else 0,
        "policy_pass_rows": int(summary_frame["policy_pass_rows"].sum()) if not summary_frame.empty else 0,
        "relaxed_rows": int(summary_frame["relaxed_rows"].sum()) if not summary_frame.empty else 0,
        "yearly_outperform_rows": int(len(rows)),
        "stages_seen": int(len(summary_frame)),
        "filter_mode": filter_mode,
        "spy_train_calmar": float(summary_frame["spy_train_calmar"].dropna().iloc[0]) if not summary_frame.empty and "spy_train_calmar" in summary_frame else np.nan,
        "traded_asset": "SPY",
        "frequency": "weekly",
        "position_policy": "discrete_long_flat_short_no_leverage",
        "filters_removed": ["validation_trades_min_40", "validation_abs_exposure_015_090"],
        "yearly_rule": filter_rule_text(filter_mode),
        "locked_opened": False,
        "validation_used_for_selection": False,
    }
    (final / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    policy = base.base_policy_audit()
    policy.update(
        {
            "campaign_id": CAMPAIGN_ID,
            "source_campaign_id": SOURCE_CAMPAIGN_ID,
            "locked_opened": False,
            "validation_used_for_selection": False,
            "filters_removed": ["validation_trades_min_40", "validation_abs_exposure_015_090"],
            "filter_mode": filter_mode,
            "yearly_rule": summary["yearly_rule"],
        }
    )
    (final / "position_policy_audit.json").write_text(json.dumps(policy, indent=2), encoding="utf-8")
    pd.DataFrame([family_summary(rows)]).to_csv(final / "family_summary.csv", index=False)


def family_summary(rows: pd.DataFrame) -> dict[str, Any]:
    if rows.empty:
        return {"families": 0, "best_family": "", "best_validation_total_return": np.nan}
    grouped = rows.groupby("idea_family")["validation_total_return"].max().sort_values(ascending=False)
    return {
        "families": int(len(grouped)),
        "best_family": str(grouped.index[0]),
        "best_validation_total_return": float(grouped.iloc[0]),
    }


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
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=yearly_columns())


def yearly_columns() -> list[str]:
    return [
        "strategy_id",
        "stage",
        "config_index",
        "idea_id",
        "idea_family",
        "traded_asset",
        "frequency",
        "position_policy",
        "unique_positions",
        "max_abs_position",
        "cash_allowed",
        "leverage_allowed",
        "locked_opened",
        "validation_used_for_selection",
        "train_sharpe",
        "validation_sharpe",
        "train_total_return",
        "validation_total_return",
        "train_profit_factor",
        "validation_profit_factor",
        "train_calmar",
        "spy_train_calmar",
        "train_calmar_excess_vs_spy",
        "train_mdd",
        "validation_mdd",
        "train_trades",
        "validation_trades",
        "train_abs_exposure_mean",
        "validation_abs_exposure_mean",
        "train_years",
        "validation_years",
        "train_min_annual_excess_vs_spy",
        "validation_min_annual_excess_vs_spy",
        "features",
        "params_json",
    ]


if __name__ == "__main__":
    main()
