from __future__ import annotations

import argparse
import hashlib
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd

from scripts import run_spy_weekly_noleverage_50ideas_v2 as base


CAMPAIGN_ID = "spy_weekly_noleverage_global_random_nightly_until_0700"
STRATEGY_PREFIX = "spy_weekly_noleverage_global_random"
ALLOWED_POSITIONS = {-1.0, 0.0, 1.0}

TRAIN_START = base.TRAIN_START
TRAIN_END = base.TRAIN_END
VALIDATION_START = base.VALIDATION_START
VALIDATION_END = base.VALIDATION_END
LOCKED_START = base.LOCKED_START


GLOBAL_RANDOM_BASKETS: list[tuple[str, str, list[str]]] = [
    ("price_action_ohlc", "price_action", ["close_location", "upper_wick", "lower_wick", "range", "gap", "inside_bar", "outside_bar"]),
    ("returns_all_horizons", "returns", ["ret_", "post_loss", "post_gain", "intraw_ret"]),
    ("trend_ma_stack", "trend", ["ma_gap", "ma_slope", "dual_ma", "ma_stack", "macd"]),
    ("volatility_atr", "volatility", ["volatility", "atr", "range_z", "vol_of_vol"]),
    ("drawdown_path", "path", ["drawdown", "ulcer", "time_since", "streak"]),
    ("distribution_shape", "distribution", ["skew", "kurtosis", "semivariance", "upside", "downside"]),
    ("entropy_motif", "motif", ["entropy", "sign_pattern", "alternating", "streak"]),
    ("vix_stress", "macro_vol", ["vix", "stress", "volatility_expansion", "volatility_contraction"]),
    ("rates_curve", "macro_rates", ["tnx", "irx", "yield_curve", "curve", "rates"]),
    ("dollar_fx", "macro_fx", ["dxy", "fx", "dollar"]),
    ("credit_risk", "credit", ["hyg", "lqd", "credit"]),
    ("bond_equity", "rates_rotation", ["tlt", "spy_tlt", "rates_equity"]),
    ("qqq_growth", "equity_relative", ["qqq", "growth", "large_small"]),
    ("iwm_smallcap", "equity_relative", ["iwm", "small", "large_small"]),
    ("dow_industrial", "equity_relative", ["dia", "xli", "industrial"]),
    ("sector_breadth", "sector", ["sector", "breadth", "dispersion"]),
    ("sector_rotation", "sector", ["rotation", "defensive", "cyclical", "growth_value"]),
    ("defensive_warning", "sector", ["xlp", "xlu", "xlv", "defensive"]),
    ("cyclical_confirmation", "sector", ["xly", "xlk", "xlf", "xli", "cyclical"]),
    ("global_equity", "global", ["efa", "eem", "global", "em_dm"]),
    ("asia_lead", "global", ["n225", "hsi", "asia"]),
    ("europe_lead", "global", ["ftse", "dax", "fchi", "europe"]),
    ("beta_instability", "beta", ["beta", "corr", "instability"]),
    ("multi_asset_agreement", "agreement", ["agreement", "disagreement", "multi_asset"]),
]


def build_global_random_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    variants = [
        ("linear_mix", ["ret_", "volatility", "ma_", "vix", "credit", "sector"]),
        ("rank_vote", ["rank", "corr", "beta", "dispersion", "agreement"]),
        ("reversal", ["drawdown", "gap_failure", "failed", "wick", "rsi"]),
        ("breakout", ["range", "entropy", "trend", "macd", "volume"]),
    ]
    for basket_name, family, patterns in GLOBAL_RANDOM_BASKETS:
        for variant_name, extra_patterns in variants:
            specs.append(
                {
                    "idea_id": f"global_random_{basket_name}_{variant_name}",
                    "idea_family": f"global_random_{family}",
                    "patterns": sorted(set(patterns + extra_patterns)),
                }
            )
    return specs


GLOBAL_RANDOM_IDEA_SPECS = build_global_random_specs()


@contextmanager
def activated_base_campaign() -> Iterator[None]:
    old_campaign = base.CAMPAIGN_ID
    old_specs = base.IDEA_SPECS
    base.CAMPAIGN_ID = CAMPAIGN_ID
    base.IDEA_SPECS = GLOBAL_RANDOM_IDEA_SPECS
    try:
        yield
    finally:
        base.CAMPAIGN_ID = old_campaign
        base.IDEA_SPECS = old_specs


def main() -> None:
    base.require_github_actions_or_explicit_local_permission("SPY weekly no-leverage global random nightly")
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["data", "shard", "merge"], required=True)
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--stage", type=int, default=0)
    parser.add_argument("--configs-per-stage", type=int, default=30_000)
    parser.add_argument("--time-budget-minutes", type=float, default=24.0)
    parser.add_argument("--top-per-stage", type=int, default=175)
    parser.add_argument("--cost-bps", type=float, default=1.0)
    parser.add_argument("--locked-retest-top-n", type=int, default=7_500)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.mode == "data":
        run_data(output_dir)
    elif args.mode == "shard":
        run_shard(
            output_dir,
            stage=int(args.stage),
            configs_per_stage=int(args.configs_per_stage),
            time_budget_minutes=float(args.time_budget_minutes),
            top_per_stage=int(args.top_per_stage),
            cost_bps=float(args.cost_bps),
        )
    else:
        final_merge(output_dir, locked_retest_top_n=int(args.locked_retest_top_n), cost_bps=float(args.cost_bps))


def run_data(output_dir: Path) -> None:
    with activated_base_campaign():
        base.run_data(output_dir)


def final_merge(output_dir: Path, *, locked_retest_top_n: int, cost_bps: float) -> None:
    with activated_base_campaign():
        base.final_merge(output_dir, locked_retest_top_n=locked_retest_top_n, cost_bps=cost_bps)


def run_shard(
    output_dir: Path,
    *,
    stage: int,
    configs_per_stage: int,
    time_budget_minutes: float,
    top_per_stage: int,
    cost_bps: float,
) -> None:
    panel = pd.read_csv(output_dir / "weekly_panel_no_locked.csv", parse_dates=["timestamp"]).set_index("timestamp")
    if panel.index.max() >= LOCKED_START:
        raise RuntimeError("Locked data reached shard")
    feature_cols = base.feature_columns(panel)
    train_mask = np.asarray((panel.index >= TRAIN_START) & (panel.index <= TRAIN_END), dtype=bool)
    validation_mask = np.asarray((panel.index >= VALIDATION_START) & (panel.index <= VALIDATION_END), dtype=bool)
    matrix = panel[feature_cols].to_numpy(dtype=float)
    spy_returns = panel["spy_return"].to_numpy(dtype=float)
    idea = GLOBAL_RANDOM_IDEA_SPECS[stage % len(GLOBAL_RANDOM_IDEA_SPECS)]
    rng = np.random.default_rng(20260618 + int(stage) * 1_000_003)
    deadline = time.monotonic() + max(0.01, float(time_budget_minutes)) * 60.0
    rows: list[dict[str, Any]] = []
    evaluated = 0

    while evaluated < int(configs_per_stage) and time.monotonic() < deadline:
        evaluated += 1
        params = base.sample_params(rng, feature_cols, idea, stage=stage)
        params["campaign_id"] = CAMPAIGN_ID
        scores = base.build_scores(matrix, params)
        positions, train_metrics, fit = base.choose_discrete_positions_train_only(scores, spy_returns, train_mask)
        params.update(fit)
        policy = base.position_policy_audit(positions)
        if not policy["policy_pass"]:
            continue
        strategy_returns = base.apply_costs(positions, spy_returns, cost_bps)
        train_metrics = base.metrics(strategy_returns[train_mask])
        validation_metrics = base.metrics(strategy_returns[validation_mask])
        train_position = base.position_summary(positions[train_mask])
        validation_position = base.position_summary(positions[validation_mask])
        accepted = base.is_accepted(train_metrics, validation_metrics, validation_position)
        features = [feature_cols[int(i)] for i in params["feature_indices"]]
        payload = {"idea_id": idea["idea_id"], "params": params, "features": features}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        rows.append(
            {
                "strategy_id": f"{STRATEGY_PREFIX}_s{stage:03d}_{digest}",
                "stage": int(stage),
                "config_index": int(evaluated),
                "idea_id": idea["idea_id"],
                "idea_family": idea["idea_family"],
                "train_score": base.selection_score(train_metrics, train_position, params),
                "accepted": bool(accepted),
                "traded_asset": "SPY",
                "frequency": "weekly",
                "position_policy": "discrete_long_flat_short_no_leverage",
                "unique_positions": policy["unique_positions"],
                "max_abs_position": policy["max_abs_position"],
                "cash_allowed": True,
                "leverage_allowed": False,
                "locked_opened": False,
                "locked_rows_accessed": 0,
                "validation_used_for_selection": False,
                "train_sharpe": train_metrics["sharpe"],
                "validation_sharpe": validation_metrics["sharpe"],
                "train_total_return": train_metrics["total_return"],
                "validation_total_return": validation_metrics["total_return"],
                "train_profit_factor": train_metrics["profit_factor"],
                "validation_profit_factor": validation_metrics["profit_factor"],
                "train_mdd": train_metrics["mdd"],
                "validation_mdd": validation_metrics["mdd"],
                "train_trades": train_metrics["trades"],
                "validation_trades": validation_metrics["trades"],
                "train_abs_exposure_mean": train_position["abs_exposure_mean"],
                "validation_abs_exposure_mean": validation_position["abs_exposure_mean"],
                "train_long_pct": train_position["long_pct"],
                "validation_long_pct": validation_position["long_pct"],
                "train_short_pct": train_position["short_pct"],
                "validation_short_pct": validation_position["short_pct"],
                "train_cash_pct": train_position["cash_pct"],
                "validation_cash_pct": validation_position["cash_pct"],
                "features": "|".join(features),
                "params_json": json.dumps(params, sort_keys=True),
            }
        )

    shard_dir = output_dir / "shards" / f"stage_{stage:03d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(columns=base.leaderboard_columns())
    top = frame.sort_values(["train_score", "train_sharpe"], ascending=[False, False]).head(int(top_per_stage))
    accepted_frame = frame[frame.get("accepted", pd.Series(dtype=bool)).astype(bool)]
    top.to_csv(shard_dir / "top_candidates.csv", index=False)
    accepted_frame.to_csv(shard_dir / "accepted.csv", index=False)
    (shard_dir / "shard_summary.json").write_text(
        json.dumps(
            {
                "stage": int(stage),
                "idea_id": idea["idea_id"],
                "idea_family": idea["idea_family"],
                "configs_evaluated": int(evaluated),
                "rows_kept": int(len(frame)),
                "accepted_rows": int(len(accepted_frame)),
                "locked_opened": False,
                "validation_used_for_selection": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def base_policy_audit() -> dict[str, Any]:
    with activated_base_campaign():
        return base.base_policy_audit()


build_weekly_panel = base.build_weekly_panel
choose_discrete_positions_train_only = base.choose_discrete_positions_train_only
position_policy_audit = base.position_policy_audit
synthetic_weekly_panel = base.synthetic_weekly_panel


if __name__ == "__main__":
    main()
