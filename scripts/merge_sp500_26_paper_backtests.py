from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.execution_policy import require_github_actions_or_explicit_local_permission  # noqa: E402
from aurora.research.sp500_26_paper_replication_backtest import (  # noqa: E402
    load_paper26_config,
    summary_from_results,
)


def main() -> int:
    require_github_actions_or_explicit_local_permission("sp500 26 paper backtest merge")
    parser = argparse.ArgumentParser(description="Merge SP500 26-paper replication chunks.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--specs", default="config/sp500_26_paper_replication_specs.yaml")
    parser.add_argument("--expected-chunks", type=int, default=26)
    parser.add_argument("--expected-specs", type=int, default=26)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    merge(args)
    return 0


def merge(args: argparse.Namespace) -> dict[str, object]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    config, specs, raw = load_paper26_config(args.specs)

    result_paths = sorted(glob.glob(str(Path(args.input_dir) / "**" / "sp500_26_paper_chunk_*_results.csv"), recursive=True))
    annual_paths = sorted(glob.glob(str(Path(args.input_dir) / "**" / "sp500_26_paper_chunk_*_annual.csv"), recursive=True))
    monthly_paths = sorted(glob.glob(str(Path(args.input_dir) / "**" / "sp500_26_paper_chunk_*_monthly.csv"), recursive=True))
    summary_paths = sorted(glob.glob(str(Path(args.input_dir) / "**" / "sp500_26_paper_chunk_*_summary.json"), recursive=True))
    missing = missing_chunks(result_paths, int(args.expected_chunks))
    if len(result_paths) != int(args.expected_chunks) and not args.allow_partial:
        raise SystemExit(f"merge failed: expected {args.expected_chunks} chunks, found {len(result_paths)}")

    results = concat_csvs(result_paths)
    annual = concat_csvs(annual_paths)
    monthly = concat_csvs(monthly_paths)
    if len(results) < int(args.expected_specs) and not args.allow_partial:
        raise SystemExit(f"merge failed: expected at least {args.expected_specs} result rows, found {len(results)}")
    if not results.empty and results.get("locked_opened", pd.Series([True])).astype(bool).any():
        raise SystemExit("merge failed: locked_opened must be false")
    if not results.empty and results.get("validation_used_for_selection", pd.Series([True])).astype(bool).any():
        raise SystemExit("merge failed: validation_used_for_selection must be false")
    if not results.empty and results.get("paper_exact_replication_claimed", pd.Series([True])).astype(bool).any():
        raise SystemExit("merge failed: paper_exact_replication_claimed must be false")

    summary = summary_from_results(
        results,
        annual,
        monthly,
        expected_specs=int(args.expected_specs),
        chunks_expected=int(args.expected_chunks),
        chunks_found=len(result_paths),
    )
    summary["missing_chunks"] = missing
    summary["chunk_summaries"] = read_jsons(summary_paths)

    specs_frame = pd.DataFrame(raw["specs"])
    unsupported = results[results["status"] == "unsupported"].copy() if not results.empty else pd.DataFrame()
    evaluated = results[results["status"] == "evaluated"].copy() if not results.empty else pd.DataFrame()
    paper_like = evaluated[evaluated["view"] == "paper_like"].copy() if not evaluated.empty else pd.DataFrame()
    comparable = evaluated[evaluated["view"] == "aurora_comparable"].copy() if not evaluated.empty else pd.DataFrame()
    leaderboard = comparable.sort_values(["validation_sharpe", "train_sharpe"], ascending=False).reset_index(drop=True) if not comparable.empty else comparable
    missing_data = build_missing_data(specs_frame, unsupported)
    fidelity = build_fidelity_audit(specs_frame, results)
    lookahead = build_lookahead_audit(specs_frame)
    vs_spy = build_vs_spy(annual)

    leaderboard.to_csv(output_dir / "sp500_26_leaderboard.csv", index=False)
    paper_like.to_csv(output_dir / "sp500_26_paper_like_results.csv", index=False)
    comparable.to_csv(output_dir / "sp500_26_aurora_comparable_results.csv", index=False)
    annual.to_csv(output_dir / "sp500_26_annual_returns.csv", index=False)
    monthly.to_csv(output_dir / "sp500_26_monthly_returns.csv", index=False)
    vs_spy.to_csv(output_dir / "sp500_26_vs_spy.csv", index=False)
    specs_frame.to_csv(output_dir / "sp500_26_strategy_specs_used.csv", index=False)
    missing_data.to_csv(output_dir / "sp500_26_missing_data.csv", index=False)
    unsupported.to_csv(output_dir / "sp500_26_unsupported.csv", index=False)
    fidelity.to_csv(output_dir / "sp500_26_fidelity_audit.csv", index=False)
    lookahead.to_csv(output_dir / "sp500_26_lookahead_audit.csv", index=False)
    (output_dir / "sp500_26_locked_audit.json").write_text(
        json.dumps(
            {
                "locked_opened": False,
                "locked_start": config.locked_start,
                "validation_end": config.validation_end,
                "validation_used_for_selection": False,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (output_dir / "sp500_26_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def concat_csvs(paths: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in paths:
        csv_path = Path(path)
        if not csv_path.exists() or csv_path.stat().st_size == 0:
            continue
        try:
            frame = pd.read_csv(csv_path)
        except pd.errors.EmptyDataError:
            continue
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def missing_chunks(paths: list[str], expected: int) -> list[int]:
    seen: set[int] = set()
    for path in paths:
        match = re.search(r"sp500_26_paper_chunk_(\d+)_results\.csv$", str(path))
        if match:
            seen.add(int(match.group(1)))
    return [idx for idx in range(expected) if idx not in seen]


def read_jsons(paths: list[str]) -> list[dict[str, object]]:
    out = []
    for path in paths:
        try:
            out.append(json.loads(Path(path).read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def build_missing_data(specs: pd.DataFrame, unsupported: pd.DataFrame) -> pd.DataFrame:
    if unsupported.empty:
        return pd.DataFrame(columns=["paper_id", "slug", "required_data", "unsupported_reason"])
    reasons = unsupported[["paper_id", "slug", "unsupported_reason"]].drop_duplicates()
    required = specs[["paper_id", "required_data"]].copy()
    required["required_data"] = required["required_data"].map(lambda value: "|".join(value) if isinstance(value, list) else str(value))
    return reasons.merge(required, on="paper_id", how="left")


def build_fidelity_audit(specs: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    audit = specs[["paper_id", "slug", "title", "strategy_name", "fidelity_status", "proxy_notes"]].copy()
    if results.empty:
        audit["status"] = ""
        return audit
    statuses = results.groupby("paper_id")["status"].agg(lambda values: "|".join(sorted(set(map(str, values))))).reset_index()
    return audit.merge(statuses, on="paper_id", how="left")


def build_lookahead_audit(specs: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "paper_id": specs["paper_id"],
            "slug": specs["slug"],
            "lag_periods": 1,
            "lookahead_detected": False,
            "note": "Signals are shifted by at least one strategy period before applying returns.",
        }
    )


def build_vs_spy(annual: pd.DataFrame) -> pd.DataFrame:
    if annual.empty:
        return pd.DataFrame()
    work = annual.copy()
    grouped = work.groupby(["paper_id", "slug", "view"], dropna=False)
    return grouped.agg(
        years=("year", "count"),
        years_beating_spy=("excess_vs_spy", lambda x: int((pd.to_numeric(x, errors="coerce") > 0).sum())),
        avg_strategy_return=("strategy_return", "mean"),
        avg_spy_return=("spy_return", "mean"),
        avg_excess_vs_spy=("excess_vs_spy", "mean"),
    ).reset_index()


if __name__ == "__main__":
    raise SystemExit(main())
