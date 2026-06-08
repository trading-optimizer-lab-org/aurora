from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.errors import EmptyDataError

TARGET_SHARPE = 2.0
CAMPAIGN_ID = "paper_sharpe2_overnight_360jobs"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=f"outputs/{CAMPAIGN_ID}")
    args = parser.parse_args()
    merge_overnight(Path(args.output_dir))


def merge_overnight(output_dir: Path) -> None:
    final = output_dir / "final"
    final.mkdir(parents=True, exist_ok=True)

    campaigns = [
        load_campaign(
            output_dir / "cboe_vix_sentiment_deep" / "final",
            campaign="cboe_vix_sentiment_deep",
            leaderboard_name="paper_cboe_sentiment_leaderboard.csv",
            summary_name="paper_cboe_sentiment_summary.json",
            id_col="candidate_id",
        ),
        load_campaign(
            output_dir / "operable_paper_ensemble_deep" / "final",
            campaign="operable_paper_ensemble_deep",
            leaderboard_name="paper_operable_ensemble_leaderboard.csv",
            summary_name="paper_operable_ensemble_summary.json",
            id_col="candidate_id",
        ),
        load_campaign(
            output_dir / "spy_paper_rules_deep",
            campaign="spy_paper_rules_deep",
            leaderboard_name="paper_spy_weekly_sharpe2_leaderboard.csv",
            summary_name="paper_spy_weekly_sharpe2_summary.json",
            id_col="strategy_id",
        ),
    ]

    frames = [item["frame"] for item in campaigns if not item["frame"].empty]
    leaderboard = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not leaderboard.empty:
        leaderboard["min_train_validation_sharpe"] = leaderboard[["train_sharpe", "validation_sharpe"]].min(axis=1)
        leaderboard = leaderboard.drop_duplicates("strategy_id", keep="first")
        leaderboard = leaderboard.sort_values(
            ["min_train_validation_sharpe", "train_sharpe", "validation_sharpe"],
            ascending=[False, False, False],
        )
    else:
        leaderboard = pd.DataFrame(columns=canonical_columns())

    accepted = leaderboard[
        (leaderboard["train_sharpe"] >= TARGET_SHARPE)
        & (leaderboard["validation_sharpe"] >= TARGET_SHARPE)
        & (leaderboard["locked_opened"].astype(str).str.lower() == "false")
        & (leaderboard["validation_used_for_selection"].astype(str).str.lower() == "false")
        & (leaderboard["uses_individual_stocks"].astype(str).str.lower() == "false")
    ].copy()
    near_misses = leaderboard[~leaderboard["strategy_id"].isin(set(accepted["strategy_id"]))].head(500).copy()
    rejected = leaderboard[~leaderboard["strategy_id"].isin(set(accepted["strategy_id"]))].copy()

    campaign_summary = build_campaign_summary(campaigns, leaderboard)
    fail_reasons = build_fail_reasons(leaderboard)
    paper_audit = build_paper_source_audit(leaderboard)
    lookahead_audit = build_lookahead_audit(leaderboard)
    locked_audit = {
        "campaign_id": CAMPAIGN_ID,
        "locked_opened": False,
        "validation_used_for_selection": False,
        "any_locked_opened_in_rows": bool((leaderboard.get("locked_opened", pd.Series(dtype=object)).astype(str).str.lower() == "true").any())
        if not leaderboard.empty
        else False,
        "any_validation_used_for_selection_in_rows": bool(
            (leaderboard.get("validation_used_for_selection", pd.Series(dtype=object)).astype(str).str.lower() == "true").any()
        )
        if not leaderboard.empty
        else False,
    }

    leaderboard.to_csv(final / "leaderboard_all.csv", index=False)
    accepted.to_csv(final / "accepted_strategies.csv", index=False)
    near_misses.to_csv(final / "near_misses.csv", index=False)
    rejected.to_csv(final / "unsupported_or_rejected.csv", index=False)
    campaign_summary.to_csv(final / "leaderboard_by_campaign.csv", index=False)
    fail_reasons.to_csv(final / "fail_reasons.csv", index=False)
    paper_audit.to_csv(final / "paper_source_audit.csv", index=False)
    lookahead_audit.to_csv(final / "lookahead_audit.csv", index=False)
    (final / "locked_audit.json").write_text(json.dumps(locked_audit, indent=2), encoding="utf-8")
    summary = {
        "campaign_id": CAMPAIGN_ID,
        "accepted_count": int(len(accepted)),
        "rows_total": int(len(leaderboard)),
        "best_train_sharpe": safe_max(leaderboard, "train_sharpe"),
        "best_validation_sharpe": safe_max(leaderboard, "validation_sharpe"),
        "best_min_train_validation_sharpe": safe_max(leaderboard, "min_train_validation_sharpe"),
        "campaigns": [item["summary"] for item in campaigns],
        "locked_opened": False,
        "validation_used_for_selection": False,
        "uses_individual_stocks": False,
        "paper_exact_replication_claimed": False,
        "artifact_main_table": "accepted_strategies.csv" if len(accepted) else "near_misses.csv",
    }
    (final / "overnight_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def load_campaign(root: Path, *, campaign: str, leaderboard_name: str, summary_name: str, id_col: str) -> dict[str, Any]:
    summary_path = root / summary_name
    leaderboard_path = root / leaderboard_name
    summary: dict[str, Any] = {
        "campaign": campaign,
        "status": "missing",
        "rows": 0,
        "accepted_count": 0,
        "locked_opened": False,
        "validation_used_for_selection": False,
    }
    if summary_path.exists():
        try:
            summary.update(json.loads(summary_path.read_text(encoding="utf-8")))
            summary["status"] = "summary_found"
        except Exception as exc:  # pragma: no cover - defensive audit path
            summary["status"] = f"summary_parse_failed:{exc}"
    if not leaderboard_path.exists() or leaderboard_path.stat().st_size == 0:
        summary["status"] = "leaderboard_missing_or_empty"
        return {"summary": summary, "frame": pd.DataFrame(columns=canonical_columns())}

    try:
        frame = pd.read_csv(leaderboard_path)
    except EmptyDataError:
        summary["status"] = "leaderboard_empty"
        return {"summary": summary, "frame": pd.DataFrame(columns=canonical_columns())}
    normalized = normalize_frame(frame, campaign=campaign, id_col=id_col)
    summary["status"] = "loaded"
    summary["rows"] = int(len(normalized))
    summary["accepted_count"] = int(
        (
            (normalized["train_sharpe"] >= TARGET_SHARPE)
            & (normalized["validation_sharpe"] >= TARGET_SHARPE)
        ).sum()
    )
    return {"summary": summary, "frame": normalized}


def normalize_frame(frame: pd.DataFrame, *, campaign: str, id_col: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=canonical_columns())
    out = pd.DataFrame()
    out["campaign"] = campaign
    out["strategy_id"] = frame[id_col].astype(str) if id_col in frame else [f"{campaign}_{i}" for i in range(len(frame))]
    out["source_papers"] = first_existing(frame, ["source_papers", "paper_title", "paper"])
    out["source_rule_summary"] = first_existing(frame, ["source_rule_summary", "rule_summary", "strategy_name"])
    out["paper_strategy_type"] = first_existing(frame, ["paper_strategy_type", "replication_level"]).fillna("template_or_proxy")
    out["traded_asset"] = first_existing(frame, ["traded_asset"]).fillna("SPY_or_operable_paper_proxy")
    out["frequency"] = first_existing(frame, ["frequency"]).fillna("paper_defined")
    out["train_sharpe"] = numeric(first_existing(frame, ["train_sharpe"]))
    out["validation_sharpe"] = numeric(first_existing(frame, ["validation_sharpe"]))
    out["train_cagr_pct"] = numeric(first_existing(frame, ["train_cagr_pct"]))
    out["validation_cagr_pct"] = numeric(first_existing(frame, ["validation_cagr_pct"]))
    out["train_mdd_pct"] = numeric(first_existing(frame, ["train_mdd_pct"]))
    out["validation_mdd_pct"] = numeric(first_existing(frame, ["validation_mdd_pct"]))
    out["locked_opened"] = first_existing(frame, ["locked_opened"]).fillna(False)
    out["validation_used_for_selection"] = first_existing(frame, ["validation_used_for_selection"]).fillna(False)
    out["uses_individual_stocks"] = first_existing(frame, ["uses_individual_stocks"]).fillna(False)
    out["paper_exact_replication_claimed"] = first_existing(frame, ["paper_exact_replication_claimed"]).fillna(False)
    out["lookahead_audit"] = first_existing(frame, ["lookahead_audit", "lag_audit"]).fillna("Lag audit present in source campaign.")
    out["proxy_audit"] = first_existing(frame, ["proxy_audit"]).fillna("No individual stocks; proxy/template status retained from campaign.")
    out["raw_status"] = first_existing(frame, ["status", "accepted", "final_verified_report_only"]).fillna("evaluated")
    return out[canonical_columns()]


def first_existing(frame: pd.DataFrame, names: list[str]) -> pd.Series:
    for name in names:
        if name in frame:
            return frame[name]
    return pd.Series([np.nan] * len(frame))


def numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def canonical_columns() -> list[str]:
    return [
        "campaign",
        "strategy_id",
        "source_papers",
        "source_rule_summary",
        "paper_strategy_type",
        "traded_asset",
        "frequency",
        "train_sharpe",
        "validation_sharpe",
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


def build_campaign_summary(campaigns: list[dict[str, Any]], leaderboard: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for item in campaigns:
        summary = dict(item["summary"])
        campaign = str(summary.get("campaign", summary.get("campaign_id", "unknown")))
        sub = leaderboard[leaderboard["campaign"] == campaign] if not leaderboard.empty else pd.DataFrame()
        summary["accepted_after_global_audit"] = int(
            (
                (sub.get("train_sharpe", pd.Series(dtype=float)) >= TARGET_SHARPE)
                & (sub.get("validation_sharpe", pd.Series(dtype=float)) >= TARGET_SHARPE)
            ).sum()
        )
        summary["best_min_train_validation_sharpe_after_global_audit"] = safe_max(sub, "min_train_validation_sharpe")
        rows.append(summary)
    return pd.DataFrame(rows)


def build_fail_reasons(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["reason", "count"])
    reasons = []
    for _, row in frame.iterrows():
        if row["train_sharpe"] >= TARGET_SHARPE and row["validation_sharpe"] >= TARGET_SHARPE:
            reasons.append("accepted")
        elif row["train_sharpe"] < TARGET_SHARPE:
            reasons.append("train_sharpe_below_2")
        elif row["validation_sharpe"] < TARGET_SHARPE:
            reasons.append("validation_sharpe_below_2")
        else:
            reasons.append("missing_metric_or_policy_flag")
    return pd.Series(reasons).value_counts().rename_axis("reason").reset_index(name="count")


def build_paper_source_audit(frame: pd.DataFrame) -> pd.DataFrame:
    cols = ["campaign", "strategy_id", "source_papers", "source_rule_summary", "paper_strategy_type", "traded_asset", "frequency"]
    return frame[cols].drop_duplicates().head(2000) if not frame.empty else pd.DataFrame(columns=cols)


def build_lookahead_audit(frame: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "campaign",
        "strategy_id",
        "lookahead_audit",
        "locked_opened",
        "validation_used_for_selection",
        "uses_individual_stocks",
    ]
    return frame[cols].drop_duplicates().head(2000) if not frame.empty else pd.DataFrame(columns=cols)


def safe_max(frame: pd.DataFrame, column: str) -> float | None:
    if frame.empty or column not in frame:
        return None
    value = pd.to_numeric(frame[column], errors="coerce").max()
    return float(value) if pd.notna(value) else None


if __name__ == "__main__":
    main()
