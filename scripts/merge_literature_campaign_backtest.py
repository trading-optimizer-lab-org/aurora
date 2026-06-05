from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from aurora.research.literature_campaign import load_campaign_config  # noqa: E402
from scripts.merge_literature_strategy_backtest_chunks import merge as merge_strategy_chunks  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge literature campaign backtest chunks.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--expected-chunks", type=int, required=True)
    parser.add_argument("--expected-specs", type=int, required=True)
    parser.add_argument("--max-parallel-requested", type=int, default=180)
    parser.add_argument("--prepare-dir", default="")
    args = parser.parse_args()
    merge_campaign(args)
    return 0


def merge_campaign(args: argparse.Namespace) -> dict[str, object]:
    campaign = load_campaign_config(args.config)
    out = Path(args.output_dir)
    tmp = out / "_strategy_merge"
    out.mkdir(parents=True, exist_ok=True)
    prepare_dir = Path(args.prepare_dir) if str(args.prepare_dir or "").strip() else None
    strategy_summary = merge_strategy_chunks(
        argparse.Namespace(
            input_dir=str(args.input_dir),
            output_dir=str(tmp),
            expected_chunks=int(args.expected_chunks),
            expected_signatures=int(args.expected_specs),
            max_parallel_requested=int(args.max_parallel_requested),
            allow_partial=True,
        )
    )

    mapping = {
        "literature_strategy_backtest_train_report.csv": "campaign_backtest_train.csv",
        "literature_strategy_backtest_validation_report.csv": "campaign_backtest_validation.csv",
        "literature_strategy_backtest_leaderboard.csv": "campaign_leaderboard.csv",
        "literature_strategy_backtest_unsupported.csv": "campaign_unsupported.csv",
        "literature_strategy_backtest_fail_reasons.csv": "campaign_fail_reasons.csv",
        "literature_strategy_backtest_manifest_used.csv": "campaign_strategy_specs_used.csv",
    }
    for src_name, dst_name in mapping.items():
        src = tmp / src_name
        if src.exists():
            shutil.copyfile(src, out / dst_name)
    _copy_prepare_artifacts(prepare_dir, out)

    leaderboard = pd.read_csv(out / "campaign_leaderboard.csv") if (out / "campaign_leaderboard.csv").exists() else pd.DataFrame()
    top20_count = 0
    if not leaderboard.empty:
        primary = str(campaign.raw["ranking"]["primary_metric"])
        tie_breakers = list(campaign.raw["ranking"].get("tie_breakers", []) or [])
        sort_cols = [col for col in [primary, *tie_breakers] if col in leaderboard.columns]
        if sort_cols:
            leaderboard = leaderboard.sort_values(sort_cols, ascending=False).reset_index(drop=True)
            leaderboard.to_csv(out / "campaign_leaderboard.csv", index=False)
        down_months = _sp500_down_month_table(leaderboard)
        down_months.to_csv(out / "campaign_sp500_down_months.csv", index=False)
        diversity = _candidate_diversity(leaderboard, campaign)
        diversity.to_csv(out / "campaign_candidate_diversity.csv", index=False)
        top20 = diversity[diversity["diverse_selected"]].head(
            int(campaign.raw.get("diversity", {}).get("target_count", 20))
        ).copy()
        require_start = campaign.require_effective_start
        if not top20.empty and require_start and (pd.to_datetime(top20["effective_start"]) > pd.Timestamp(require_start)).any():
            raise SystemExit("merge failed: top diverse strategy starts after required 1995 start")
        if top20.empty:
            top20 = pd.DataFrame(columns=diversity.columns)
        top20_count = int(len(top20))
        top20.to_csv(out / "campaign_top20_diverse.csv", index=False)
    else:
        pd.DataFrame().to_csv(out / "campaign_sp500_down_months.csv", index=False)
        pd.DataFrame().to_csv(out / "campaign_candidate_diversity.csv", index=False)
        pd.DataFrame().to_csv(out / "campaign_top20_diverse.csv", index=False)

    summary = {
        **strategy_summary,
        "campaign_id": campaign.campaign_id,
        "objective": campaign.raw.get("objective", ""),
        "ranking_primary_metric": campaign.raw["ranking"]["primary_metric"],
        "top20_diverse_count": top20_count,
        "required_effective_start_lte": campaign.require_effective_start,
        "locked_opened": False,
        "validation_used_for_selection": False,
        "partial": bool(strategy_summary.get("partial", True)),
    }
    (out / "campaign_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (out / "campaign_audit.md").write_text(_audit(campaign.campaign_id, summary), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def _audit(campaign_id: str, summary: dict[str, object]) -> str:
    return "\n".join([
        f"# Campaign Backtest Audit: {campaign_id}",
        "",
        f"- input_signatures: {summary.get('input_signatures')}",
        f"- evaluated: {summary.get('evaluated')}",
        f"- unsupported: {summary.get('unsupported')}",
        f"- errors: {summary.get('errors')}",
        f"- top20_diverse_count: {summary.get('top20_diverse_count')}",
        f"- required_effective_start_lte: {summary.get('required_effective_start_lte')}",
        f"- partial: {summary.get('partial')}",
        "- locked_opened: false",
        "- validation_used_for_selection: false",
        "- paper_exact_replication_claimed: false",
        "",
    ])


def _copy_prepare_artifacts(prepare_dir: Path | None, out: Path) -> None:
    if prepare_dir is None or not prepare_dir.exists():
        return
    for name in [
        "campaign_studies.csv",
        "campaign_pdf_status.csv",
        "campaign_rule_extraction.csv",
        "campaign_strategy_specs.csv",
    ]:
        src = prepare_dir / name
        if src.exists():
            shutil.copyfile(src, out / name)
    unsupported = prepare_dir / "campaign_unsupported.csv"
    if unsupported.exists():
        shutil.copyfile(unsupported, out / "campaign_rule_unsupported.csv")


def _sp500_down_month_table(leaderboard: pd.DataFrame) -> pd.DataFrame:
    keep = [
        "candidate_id",
        "signature_hash",
        "primary_family",
        "example_study_id",
        "example_title",
        "effective_start",
        "train_sp500_down_month_avg_return_pct",
        "train_sp500_down_month_positive_pct",
        "train_sp500_down_month_worst_return_pct",
        "train_sp500_down_month_beats_sp500_pct",
        "train_sp500_down_month_count",
        "train_sp500_up_month_avg_return_pct",
        "train_sp500_up_month_positive_pct",
        "train_sp500_up_month_count",
        "train_sp500_down_true_positive_count",
        "train_sp500_down_false_negative_count",
        "train_sp500_down_false_positive_count",
        "train_sp500_down_true_negative_count",
        "train_sp500_down_precision_pct",
        "train_sp500_down_recall_pct",
        "train_sp500_down_false_positive_rate_pct",
        "validation_sp500_down_month_avg_return_pct",
        "validation_sp500_down_month_positive_pct",
        "validation_sp500_down_month_worst_return_pct",
        "validation_sp500_down_month_beats_sp500_pct",
        "validation_sp500_down_month_count",
        "validation_sp500_up_month_avg_return_pct",
        "validation_sp500_up_month_positive_pct",
        "validation_sp500_up_month_count",
        "validation_sp500_down_true_positive_count",
        "validation_sp500_down_false_negative_count",
        "validation_sp500_down_false_positive_count",
        "validation_sp500_down_true_negative_count",
        "validation_sp500_down_precision_pct",
        "validation_sp500_down_recall_pct",
        "validation_sp500_down_false_positive_rate_pct",
    ]
    cols = [col for col in keep if col in leaderboard.columns]
    return leaderboard.loc[:, cols].copy()


def _candidate_diversity(leaderboard: pd.DataFrame, campaign) -> pd.DataFrame:
    work = leaderboard.copy()
    if "effective_start" in work.columns and campaign.require_effective_start:
        work = work[pd.to_datetime(work["effective_start"], errors="coerce") <= pd.Timestamp(campaign.require_effective_start)]
    primary = str(campaign.raw["ranking"]["primary_metric"])
    tie_breakers = list(campaign.raw["ranking"].get("tie_breakers", []) or [])
    sort_cols = [col for col in [primary, *tie_breakers] if col in work.columns]
    for col in sort_cols:
        work[col] = pd.to_numeric(work[col], errors="coerce")
    if sort_cols:
        work = work.sort_values(sort_cols, ascending=False, na_position="last")
    selected = []
    used_families: set[str] = set()
    used_studies: set[str] = set()
    target = int(campaign.raw.get("diversity", {}).get("target_count", 20))
    for _, row in work.iterrows():
        family = str(row.get("primary_family", ""))
        study = str(row.get("example_study_id", ""))
        if family in used_families:
            selected.append(False)
            continue
        if study and study in used_studies:
            selected.append(False)
            continue
        pick = len(used_families) < target
        selected.append(pick)
        if pick:
            used_families.add(family)
            if study:
                used_studies.add(study)
    work["diverse_selected"] = selected
    work["diversity_rank"] = range(1, len(work) + 1)
    return work.reset_index(drop=True)


if __name__ == "__main__":
    raise SystemExit(main())
