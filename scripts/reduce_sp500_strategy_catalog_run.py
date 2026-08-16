"""Fail-closed reduction of all 360 SP500 catalog shards."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    expected = [json.loads(line)["strategy_id"] for line in args.catalog.read_text("utf-8").splitlines()]
    rows = []
    for path in sorted(args.input_root.rglob("results.jsonl")):
        rows.extend(json.loads(line) for line in path.read_text("utf-8").splitlines())
    by_id = {row["strategy_id"]: row for row in rows}
    if len(rows) != len(by_id) or set(by_id) != set(expected) or len(rows) != 37258:
        raise SystemExit(f"CATALOG_RESULT_SET_INVALID:{len(rows)}:{len(by_id)}")
    ordered = [by_id[strategy_id] for strategy_id in expected]
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "results.jsonl").write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in ordered), "utf-8")
    selected = []
    for path in sorted(args.input_root.rglob("selected_results.jsonl")):
        selected.extend(json.loads(line) for line in path.read_text("utf-8").splitlines())
    if len(selected) != 13 or len({row["source_strategy_key"] for row in selected}) != 13:
        raise SystemExit(f"CATALOG_SELECTED_RESULT_SET_INVALID:{len(selected)}")
    (args.output_dir / "selected_results.jsonl").write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in selected
        ),
        "utf-8",
    )
    summary_rows = []
    for row in ordered:
        info = row["result"]["info"]
        summary_rows.append({"strategy_id": row["strategy_id"], "strategy_kind": row["strategy_kind"], "annualized_strategy_return": info["annualized_strategy_return"], "annualized_alpha": info["annualized_alpha"], "weekly_spy_beat_rate": info["weekly_spy_beat_rate"], "positive_weeks": info["positive_weeks"], "winning_or_positive_weeks": info["winning_or_positive_weeks"], "weekly_winning_or_positive_rate": info["weekly_winning_or_positive_rate"], "week_count": info["week_count"], "train_feasible": info["train_feasible"], "failed_years": json.dumps(info["failed_years"], separators=(",", ":")), "validation_opened": False, "locked_opened": False})
    fields = list(summary_rows[0])
    with (args.output_dir / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(summary_rows)
    top = sorted(summary_rows, key=lambda row: (not row["train_feasible"], -float(row["annualized_strategy_return"]), -float(row["weekly_spy_beat_rate"]), row["strategy_id"]))[:10]
    receipt = {"schema_version": 1, "strategy_count": len(ordered), "selected_strategy_count": len(selected), "feasible_count": sum(bool(row["train_feasible"]) for row in summary_rows), "top_10": top, "validation_opened": False, "locked_opened": False}
    (args.output_dir / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
