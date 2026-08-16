"""Verify and reduce compact recipe-worker Parquet without loading JSONL."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.github_performance.shard_planner import sha256_file
from aurora.infra.sp500_megarun.catalog_admission import verify_catalog_plan_token
from aurora.infra.sp500_megarun.catalog_optimization_contract import (
    RunOptimizationContractV1,
)
from aurora.infra.sp500_megarun.catalog_resume import (
    CatalogResumeWorkManifestV1,
    load_resume_index,
    scientific_result_sha256,
)


_RESULT_SCHEMA = pa.schema(
    [
        ("strategy_id", pa.string()),
        ("result_json", pa.string()),
    ]
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--resolved-contract", type=Path, required=True)
    parser.add_argument("--resume-work-manifest", type=Path, required=True)
    parser.add_argument("--resume-root", type=Path, action="append", default=[])
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
    resolved = RunOptimizationContractV1.model_validate_json(
        args.resolved_contract.read_text("utf-8")
    )
    work_manifest = CatalogResumeWorkManifestV1.model_validate_json(
        args.resume_work_manifest.read_text("utf-8")
    )
    work_identity = work_manifest.model_dump(
        mode="python",
        exclude={"manifest_sha256"},
    )
    if (
        resolved.contract_sha256 != plan.contract_sha256
        or canonical_sha256(work_identity) != work_manifest.manifest_sha256
        or work_manifest.manifest_sha256 != plan.work_manifest_sha256
    ):
        raise SystemExit("OPTIMIZED_REDUCER_PLAN_INVALID")
    expected_rows = [
        json.loads(line)
        for line in args.catalog.read_text("utf-8").splitlines()
        if line
    ]
    expected_ids = [str(row["strategy_id"]) for row in expected_rows]
    catalog_by_id = {str(row["strategy_id"]): row for row in expected_rows}
    science_identity_sha256 = canonical_sha256(resolved.science)
    resume_index = load_resume_index(
        tuple(args.resume_root),
        expected_science_identity_sha256=science_identity_sha256,
        expected_catalog_manifest_sha256=resolved.science.catalog_manifest_sha256,
    )
    if set(resume_index.strategy_ids) != set(work_manifest.cached_strategy_ids):
        raise SystemExit("OPTIMIZED_RESUME_RESULT_SET_INVALID")
    if plan.pending_recipe_count:
        current_index = load_resume_index(
            (args.input_root,),
            expected_science_identity_sha256=science_identity_sha256,
            expected_catalog_manifest_sha256=resolved.science.catalog_manifest_sha256,
        )
    else:
        current_index = load_resume_index(
            (),
            expected_science_identity_sha256=science_identity_sha256,
            expected_catalog_manifest_sha256=resolved.science.catalog_manifest_sha256,
        )
    if set(current_index.strategy_ids) != set(work_manifest.pending_strategy_ids):
        raise SystemExit("OPTIMIZED_PHYSICAL_RESULT_SET_INVALID")
    rows = [
        {"strategy_id": item.strategy_id, "result_json": item.result_json}
        for item in (*resume_index.results, *current_index.results)
    ]
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
        pa.Table.from_pylist(ordered, schema=_RESULT_SCHEMA),
        result_path,
        compression="zstd",
        use_dictionary=True,
        row_group_size=4096,
    )
    selected_by_key: dict[str, dict[str, object]] = {}
    selected_paths = [
        *sorted(args.input_root.rglob("selected_results.jsonl")),
        *[
            path
            for root in args.resume_root
            for path in sorted(Path(root).rglob("selected_results.jsonl"))
        ],
    ]
    for path in selected_paths:
        for line in path.read_text("utf-8").splitlines():
            if not line:
                continue
            row = json.loads(line)
            key = str(row["source_strategy_key"])
            previous = selected_by_key.get(key)
            if previous is not None and scientific_result_sha256(
                dict(previous["result"])
            ) != scientific_result_sha256(dict(row["result"])):
                raise SystemExit("OPTIMIZED_SELECTED_RESULT_CONFLICT")
            selected_by_key[key] = row
    selected = [selected_by_key[key] for key in sorted(selected_by_key)]
    if len(selected) != 13:
        raise SystemExit(f"OPTIMIZED_SELECTED_RESULT_SET_INVALID:{len(selected)}")
    (args.output_dir / "selected_results.jsonl").write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in selected
        ),
        "utf-8",
    )
    summary_rows: list[dict[str, object]] = []
    position_fingerprints: set[str] = set()
    for row in ordered:
        info = json.loads(str(row["result_json"]))["info"]
        position_fingerprints.add(str(info["position_fingerprint"]))
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
    scientific_stage_seconds = {
        name: sum(
            float(receipt.get("scientific_stage_seconds", {}).get(name, 0.0))
            for receipt in worker_receipts
        )
        for name in (
            "component_load",
            "composition",
            "objective",
            "serialization",
            "write",
        )
    }
    scientific_wall_stage_seconds = {
        name: sum(
            float(receipt.get("scientific_wall_stage_seconds", {}).get(name, 0.0))
            for receipt in worker_receipts
        )
        for name in (
            "initialization",
            "evaluation",
            "write",
            "selected_verification",
        )
    }
    scientific_attribution_difference_ratio = max(
        (
            float(receipt.get("scientific_attribution_difference_ratio", 1.0))
            for receipt in worker_receipts
        ),
        default=1.0,
    )
    worker_cpu_seconds = sum(
        float(receipt.get("cpu_seconds", 0.0)) for receipt in worker_receipts
    )
    worker_peak_memory_bytes = max(
        (int(receipt.get("peak_memory_bytes", 0)) for receipt in worker_receipts),
        default=0,
    )
    worker_available_memory_bytes = min(
        (
            int(receipt.get("available_memory_bytes", 0))
            for receipt in worker_receipts
            if int(receipt.get("available_memory_bytes", 0)) > 0
        ),
        default=0,
    )
    worker_peak_memory_fraction = max(
        (
            float(receipt.get("peak_memory_fraction", 0.0))
            for receipt in worker_receipts
        ),
        default=0.0,
    )
    worker_process_counts = {
        int(receipt.get("processes_per_worker", 0)) for receipt in worker_receipts
    }
    worker_block_sizes = {
        int(receipt.get("block_size", 0)) for receipt in worker_receipts
    }
    if worker_process_counts != {plan.processes_per_worker}:
        raise SystemExit("REDUCE_WORKER_PROCESS_COUNT_MISMATCH")
    if worker_block_sizes != {plan.block_size}:
        raise SystemExit("REDUCE_WORKER_BLOCK_SIZE_MISMATCH")
    total_bytes = result_path.stat().st_size
    unique_positions = len(position_fingerprints)
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
        "workers": plan.active_workers,
        "component_workers": plan.component_workers,
        "component_processes_per_worker": (
            plan.component_processes_per_worker
        ),
        "processes_per_worker": plan.processes_per_worker,
        "block_size": plan.block_size,
        "scientific_stage_seconds": scientific_stage_seconds,
        "scientific_wall_stage_seconds": scientific_wall_stage_seconds,
        "scientific_attribution_difference_ratio": (
            scientific_attribution_difference_ratio
        ),
        "worker_cpu_seconds": worker_cpu_seconds,
        "worker_peak_memory_bytes": worker_peak_memory_bytes,
        "worker_available_memory_bytes": worker_available_memory_bytes,
        "worker_peak_memory_fraction": worker_peak_memory_fraction,
        "science_identity_sha256": science_identity_sha256,
        "catalog_manifest_sha256": resolved.science.catalog_manifest_sha256,
        "work_manifest_sha256": work_manifest.manifest_sha256,
        "physical_recipe_evaluations": len(current_index.strategy_ids),
        "prior_result_cache_hits": len(resume_index.strategy_ids),
        "resume_source_result_rows": resume_index.physical_result_count,
        "resume_duplicate_result_rows": resume_index.duplicate_result_count,
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
