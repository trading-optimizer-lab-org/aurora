"""Verify and reduce compact recipe-worker Parquet without loading JSONL."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from aurora.infra.github_performance.shard_planner import sha256_file
from aurora.infra.sp500_megarun.catalog_admission import verify_catalog_plan_token


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--run-plan", type=Path, required=True)
    parser.add_argument("--admission-token", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    plan = verify_catalog_plan_token(
        args.run_plan,
        admission_token_sha256=args.admission_token,
    )
    expected_rows = [
        json.loads(line)
        for line in args.catalog.read_text("utf-8").splitlines()
        if line
    ]
    expected_ids = [str(row["strategy_id"]) for row in expected_rows]
    catalog_by_id = {str(row["strategy_id"]): row for row in expected_rows}
    tables = [pq.read_table(path) for path in sorted(args.input_root.rglob("results.parquet"))]
    if not tables:
        raise SystemExit("OPTIMIZED_RESULT_PARTITIONS_MISSING")
    table = pa.concat_tables(tables)
    rows = table.to_pylist()
    by_id = {str(row["strategy_id"]): row for row in rows}
    if (
        len(rows) != len(by_id)
        or set(by_id) != set(expected_ids)
        or len(rows) != len(expected_ids)
    ):
        raise SystemExit(
            f"OPTIMIZED_RESULT_SET_INVALID:{len(rows)}:{len(by_id)}"
        )
    ordered = [by_id[strategy_id] for strategy_id in expected_ids]
    args.output_dir.mkdir(parents=True, exist_ok=False)
    result_path = args.output_dir / "results.parquet"
    pq.write_table(
        pa.Table.from_pylist(ordered, schema=table.schema),
        result_path,
        compression="zstd",
        use_dictionary=True,
        row_group_size=4096,
    )
    selected: list[dict[str, object]] = []
    for path in sorted(args.input_root.rglob("selected_results.jsonl")):
        selected.extend(
            json.loads(line) for line in path.read_text("utf-8").splitlines() if line
        )
    if len(selected) != 13 or len(
        {str(row["source_strategy_key"]) for row in selected}
    ) != 13:
        raise SystemExit(f"OPTIMIZED_SELECTED_RESULT_SET_INVALID:{len(selected)}")
    (args.output_dir / "selected_results.jsonl").write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in selected
        ),
        "utf-8",
    )
    summary_rows: list[dict[str, object]] = []
    for row in ordered:
        info = json.loads(str(row["result_json"]))["info"]
        summary_rows.append(
            {
                "strategy_id": row["strategy_id"],
                "strategy_kind": catalog_by_id[str(row["strategy_id"])][
                    "strategy_kind"
                ],
                "annualized_strategy_return": info["annualized_strategy_return"],
                "annualized_alpha": info["annualized_alpha"],
                "weekly_spy_beat_rate": info["weekly_spy_beat_rate"],
                "positive_weeks": info["positive_weeks"],
                "winning_or_positive_weeks": info["winning_or_positive_weeks"],
                "weekly_winning_or_positive_rate": info[
                    "weekly_winning_or_positive_rate"
                ],
                "week_count": info["week_count"],
                "train_feasible": info["train_feasible"],
                "failed_years": json.dumps(info["failed_years"], separators=(",", ":")),
                "validation_opened": False,
                "locked_opened": False,
            }
        )
    with (args.output_dir / "summary.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)
    worker_receipts = [
        json.loads(path.read_text("utf-8"))
        for path in sorted(args.input_root.rglob("receipt.json"))
        if "component" not in path.as_posix().lower()
    ]
    total_bytes = result_path.stat().st_size
    unique_positions = len(
        {
            str(json.loads(str(row["result_json"]))["info"]["position_fingerprint"])
            for row in ordered
        }
    )
    top = sorted(
        summary_rows,
        key=lambda row: (
            not bool(row["train_feasible"]),
            -float(row["annualized_strategy_return"]),
            -float(row["weekly_spy_beat_rate"]),
            str(row["strategy_id"]),
        ),
    )[:10]
    receipt = {
        "schema_version": 1,
        "contract_sha256": plan.contract_sha256,
        "strategy_count": len(ordered),
        "selected_strategy_count": len(selected),
        "unique_position_count": unique_positions,
        "behavior_equivalence_hits": len(ordered) - unique_positions,
        "result_bytes": total_bytes,
        "result_bytes_per_recipe": total_bytes / len(ordered),
        "result_sha256": sha256_file(result_path),
        "worker_receipt_count": len(worker_receipts),
        "top_10": top,
        "validation_opened": False,
        "locked_opened": False,
    }
    (args.output_dir / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
