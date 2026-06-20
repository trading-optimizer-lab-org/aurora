from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import run_spy_weekly_noleverage_50ideas_v2 as base
from scripts.run_spy_weekly_global_random_yearly_outperformance import (
    TRAIN_END,
    TRAIN_START,
    VALIDATION_END,
    VALIDATION_START,
)
from scripts.run_spy_weekly_noleverage_global_random import activated_base_campaign


CAMPAIGN_ID = "spy_weekly_global_random_train_yearly_calmar_beat_counts"
ARTIFACT_NAME = "spy-weekly-global-random-train-yearly-calmar-beat-counts"


def main() -> None:
    base.require_github_actions_or_explicit_local_permission("SPY train yearly Calmar survivor beat counts")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    parser.add_argument("--cost-bps", type=float, default=1.0)
    parser.add_argument("--top-n", type=int, default=100)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    summarize(output_dir, cost_bps=float(args.cost_bps), top_n=int(args.top_n))


def annual_beat_counts(
    index: pd.DatetimeIndex,
    strategy_returns: np.ndarray,
    spy_returns: np.ndarray,
    mask: np.ndarray,
) -> dict[str, Any]:
    frame = pd.DataFrame(
        {
            "year": index[mask].year,
            "strategy": np.asarray(strategy_returns, dtype=float)[mask],
            "spy": np.asarray(spy_returns, dtype=float)[mask],
        }
    )
    annual = frame.groupby("year", sort=True)[["strategy", "spy"]].sum()
    excess = annual["strategy"] - annual["spy"]
    beaten = [str(int(year)) for year, value in excess.items() if float(value) > 0.0]
    equalled = [str(int(year)) for year, value in excess.items() if float(value) == 0.0]
    lagged = [str(int(year)) for year, value in excess.items() if float(value) < 0.0]
    return {
        "years_total": int(len(excess)),
        "years_beaten": int(len(beaten)),
        "years_equalled": int(len(equalled)),
        "years_lagged": int(len(lagged)),
        "beaten_years": "|".join(beaten),
        "equalled_years": "|".join(equalled),
        "lagged_years": "|".join(lagged),
        "min_annual_excess_vs_spy": float(excess.min()) if len(excess) else np.nan,
        "max_annual_excess_vs_spy": float(excess.max()) if len(excess) else np.nan,
    }


def summarize(output_dir: Path, *, cost_bps: float, top_n: int) -> None:
    survivors_path = output_dir / "yearly_outperform.csv"
    panel_path = output_dir / "weekly_panel_no_locked.csv"
    survivors = pd.read_csv(survivors_path)
    panel = pd.read_csv(panel_path, parse_dates=["timestamp"]).set_index("timestamp")

    with activated_base_campaign():
        feature_cols = base.feature_columns(panel)
        matrix = panel[feature_cols].to_numpy(dtype=float)
        spy_returns = panel["spy_return"].to_numpy(dtype=float)
        train_mask = np.asarray((panel.index >= TRAIN_START) & (panel.index <= TRAIN_END), dtype=bool)
        validation_mask = np.asarray((panel.index >= VALIDATION_START) & (panel.index <= VALIDATION_END), dtype=bool)

        rows: list[dict[str, Any]] = []
        for _, row in survivors.iterrows():
            params = json.loads(str(row["params_json"]))
            scores = base.build_scores(matrix, params)
            positions = base.positions_from_fit(scores, params)
            policy = base.position_policy_audit(positions)
            if not policy["policy_pass"]:
                continue
            strategy_returns = base.apply_costs(positions, spy_returns, cost_bps)
            train = annual_beat_counts(panel.index, strategy_returns, spy_returns, train_mask)
            validation = annual_beat_counts(panel.index, strategy_returns, spy_returns, validation_mask)
            item = row.to_dict()
            item.update(
                {
                    "train_years_beaten": train["years_beaten"],
                    "train_years_equalled": train["years_equalled"],
                    "train_years_lagged": train["years_lagged"],
                    "train_beaten_years": train["beaten_years"],
                    "train_equalled_years": train["equalled_years"],
                    "train_lagged_years": train["lagged_years"],
                    "train_max_annual_excess_vs_spy": train["max_annual_excess_vs_spy"],
                    "validation_years_beaten": validation["years_beaten"],
                    "validation_years_equalled": validation["years_equalled"],
                    "validation_years_lagged": validation["years_lagged"],
                    "validation_beaten_years": validation["beaten_years"],
                    "validation_equalled_years": validation["equalled_years"],
                    "validation_lagged_years": validation["lagged_years"],
                    "validation_max_annual_excess_vs_spy": validation["max_annual_excess_vs_spy"],
                    "total_years_beaten": int(train["years_beaten"] + validation["years_beaten"]),
                    "total_years_equalled": int(train["years_equalled"] + validation["years_equalled"]),
                    "total_years_lagged": int(train["years_lagged"] + validation["years_lagged"]),
                }
            )
            rows.append(item)

    final = output_dir / "beat_counts"
    final.mkdir(parents=True, exist_ok=True)
    counts = pd.DataFrame(rows)
    if not counts.empty:
        counts = counts.sort_values(
            [
                "total_years_beaten",
                "validation_years_beaten",
                "train_years_beaten",
                "validation_total_return",
                "train_calmar_excess_vs_spy",
            ],
            ascending=[False, False, False, False, False],
        )
    counts.to_csv(final / "yearly_beat_counts.csv", index=False)
    counts.head(int(top_n)).to_csv(final / "top_yearly_beat_counts.csv", index=False)
    family = (
        counts.groupby("idea_family")
        .agg(
            rows=("strategy_id", "count"),
            best_total_years_beaten=("total_years_beaten", "max"),
            best_validation_years_beaten=("validation_years_beaten", "max"),
            best_validation_total_return=("validation_total_return", "max"),
        )
        .reset_index()
        .sort_values(["best_total_years_beaten", "best_validation_total_return"], ascending=[False, False])
        if not counts.empty
        else pd.DataFrame(
            columns=[
                "idea_family",
                "rows",
                "best_total_years_beaten",
                "best_validation_years_beaten",
                "best_validation_total_return",
            ]
        )
    )
    family.to_csv(final / "family_beat_counts.csv", index=False)
    best = counts.iloc[0].to_dict() if not counts.empty else {}
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "source_rows": int(len(survivors)),
        "rows_scored": int(len(counts)),
        "sort_rule": "max total strict years beating SPY across train and validation, then validation years, then train years",
        "train_years_total": 16,
        "validation_years_total": 10,
        "best_strategy_id": best.get("strategy_id", ""),
        "best_idea_id": best.get("idea_id", ""),
        "best_idea_family": best.get("idea_family", ""),
        "best_total_years_beaten": int(best.get("total_years_beaten", 0)) if best else 0,
        "best_train_years_beaten": int(best.get("train_years_beaten", 0)) if best else 0,
        "best_validation_years_beaten": int(best.get("validation_years_beaten", 0)) if best else 0,
        "locked_opened": False,
        "validation_used_for_selection": False,
    }
    (final / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
