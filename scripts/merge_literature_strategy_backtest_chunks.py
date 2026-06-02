from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge literature strategy backtest chunks.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--expected-chunks", type=int, default=180)
    parser.add_argument("--expected-signatures", type=int, default=9419)
    parser.add_argument("--max-parallel-requested", type=int, default=180)
    args = parser.parse_args()
    merge(args)
    return 0


def merge(args: argparse.Namespace) -> dict[str, object]:
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    chunk_paths = sorted(
        path
        for path in glob.glob(str(input_dir / "**" / "literature_strategy_backtest_chunk_*.csv"), recursive=True)
        if not path.endswith("_manifest.csv")
    )
    summary_paths = sorted(glob.glob(str(input_dir / "**" / "literature_strategy_backtest_chunk_*_summary.json"), recursive=True))
    manifest_paths = sorted(glob.glob(str(input_dir / "**" / "literature_strategy_backtest_chunk_*_manifest.csv"), recursive=True))
    if len(chunk_paths) != int(args.expected_chunks):
        raise SystemExit(f"merge failed: expected {args.expected_chunks} chunks, found {len(chunk_paths)}")

    frames = [pd.read_csv(path) for path in chunk_paths]
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(data) != int(args.expected_signatures):
        raise SystemExit(f"merge failed: expected {args.expected_signatures} rows, found {len(data)}")
    if data["signature_hash"].duplicated().any():
        dupes = data.loc[data["signature_hash"].duplicated(), "signature_hash"].head(10).tolist()
        raise SystemExit(f"merge failed: duplicate signature_hash values: {dupes}")
    if data.get("locked_opened", pd.Series([True])).astype(bool).any():
        raise SystemExit("merge failed: locked_opened must be false")
    if data.get("validation_used_for_selection", pd.Series([True])).astype(bool).any():
        raise SystemExit("merge failed: validation_used_for_selection must be false")
    if data.get("paper_exact_replication_claimed", pd.Series([True])).astype(bool).any():
        raise SystemExit("merge failed: paper_exact_replication_claimed must be false")

    supported = data[data["status"] == "evaluated"].copy()
    unsupported = data[data["status"] == "unsupported"].copy()
    errors = data[data["status"] == "error"].copy()
    leaderboard = supported.sort_values("train_score", ascending=False).reset_index(drop=True) if not supported.empty else supported
    train_cols = [c for c in data.columns if c.startswith("train_") or c in _ID_COLS]
    validation_cols = [c for c in data.columns if c.startswith("validation_") or c in _ID_COLS]
    sizing_cols = [c for c in data.columns if c in _ID_COLS or c.endswith("_trades_per_month") or c in {"size_chosen_train", "frequency_tested", "symbols"}]
    manifest = _merge_manifest(manifest_paths)
    fail_reasons = _fail_reasons(data)
    family_summary = _group_summary(data, "primary_family")
    signal_summary = _group_summary(data, "signal_bucket")
    asset_summary = _group_summary(data, "asset_bucket")
    chunk_summaries = _read_jsons(summary_paths)
    partial = len(chunk_paths) != int(args.expected_chunks)
    summary = {
        "input_signatures": int(len(data)),
        "chunks_expected": int(args.expected_chunks),
        "chunks_found": int(len(chunk_paths)),
        "max_parallel_requested": int(args.max_parallel_requested),
        "partial": bool(partial),
        "backtest_enabled": True,
        "locked_opened": False,
        "validation_used_for_selection": False,
        "paper_exact_replication_claimed": False,
        "evaluated": int(len(supported)),
        "unsupported": int(len(unsupported)),
        "errors": int(len(errors)),
        "exact_source_signatures": int((data["source_exactness"] == "exact_source").sum()) if "source_exactness" in data.columns else 0,
        "template_only_signatures": int((data["source_exactness"] == "template_only").sum()) if "source_exactness" in data.columns else 0,
        "train_start": "1995-01-01",
        "train_end": "2010-12-31",
        "validation_start": "2011-01-01",
        "validation_end": "2020-12-31",
        "locked_start": "2021-01-01",
        "chunk_summaries": chunk_summaries,
    }

    leaderboard.to_csv(output_dir / "literature_strategy_backtest_leaderboard.csv", index=False)
    data.loc[:, train_cols].to_csv(output_dir / "literature_strategy_backtest_train_report.csv", index=False)
    data.loc[:, validation_cols].to_csv(output_dir / "literature_strategy_backtest_validation_report.csv", index=False)
    supported.to_csv(output_dir / "literature_strategy_backtest_supported.csv", index=False)
    unsupported.to_csv(output_dir / "literature_strategy_backtest_unsupported.csv", index=False)
    fail_reasons.to_csv(output_dir / "literature_strategy_backtest_fail_reasons.csv", index=False)
    data.loc[:, sizing_cols].to_csv(output_dir / "literature_strategy_backtest_sizing.csv", index=False)
    family_summary.to_csv(output_dir / "literature_strategy_backtest_family_summary.csv", index=False)
    signal_summary.to_csv(output_dir / "literature_strategy_backtest_signal_summary.csv", index=False)
    asset_summary.to_csv(output_dir / "literature_strategy_backtest_asset_summary.csv", index=False)
    manifest.to_csv(output_dir / "literature_strategy_backtest_manifest_used.csv", index=False)
    (output_dir / "literature_strategy_backtest_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


_ID_COLS = [
    "signature_hash",
    "candidate_id",
    "distinct_strategy_signature",
    "primary_family",
    "asset_bucket",
    "signal_bucket",
    "action_bucket",
    "frequency_bucket",
    "parameter_bucket",
    "example_study_id",
    "example_idea_id",
    "example_title",
    "source_text_ref",
    "rule_summary",
    "fidelity_caveat",
    "source_exactness",
    "status",
    "unsupported_reason",
    "error",
]


def _merge_manifest(paths: list[str]) -> pd.DataFrame:
    frames = [pd.read_csv(path) for path in paths]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _fail_reasons(data: pd.DataFrame) -> pd.DataFrame:
    reasons = data["unsupported_reason"].fillna("").replace("", "evaluated_or_error").value_counts()
    return reasons.rename_axis("reason").reset_index(name="count")


def _group_summary(data: pd.DataFrame, column: str) -> pd.DataFrame:
    rows = []
    for value, group in data.groupby(column, dropna=False):
        evaluated = group[group["status"] == "evaluated"]
        rows.append(
            {
                column: value,
                "rows": int(len(group)),
                "evaluated": int(len(evaluated)),
                "unsupported": int((group["status"] == "unsupported").sum()),
                "errors": int((group["status"] == "error").sum()),
                "best_train_score": float(pd.to_numeric(evaluated.get("train_score"), errors="coerce").max()) if not evaluated.empty else float("nan"),
                "best_validation_sharpe": float(pd.to_numeric(evaluated.get("validation_sharpe"), errors="coerce").max()) if not evaluated.empty else float("nan"),
            }
        )
    return pd.DataFrame(rows).sort_values(["evaluated", "rows"], ascending=False)


def _read_jsons(paths: list[str]) -> list[dict[str, object]]:
    out = []
    for path in paths:
        try:
            out.append(json.loads(Path(path).read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


if __name__ == "__main__":
    raise SystemExit(main())
