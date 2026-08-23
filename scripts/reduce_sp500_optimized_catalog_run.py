"""Verify and reduce compact recipe-worker Parquet without loading JSONL."""

from __future__ import annotations

import argparse
import csv
import json
import math
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


_REDUCTION_RESOURCE_FIELDS = {
    "timeout_fraction_p99",
    "memory_fraction_p99",
    "disk_fraction_p99",
    "artifact_fraction_p99",
    "download_fraction_p99",
    "input_count_fraction_p99",
}


def _safe_reduction_projection(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == _REDUCTION_RESOURCE_FIELDS
        and all(
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(float(item))
            and 0 <= float(item) <= 0.70
            for item in value.values()
        )
    )


_RESULT_SCHEMA = pa.schema(
    [
        ("strategy_id", pa.string()),
        ("result_json", pa.string()),
    ]
)


def _validate_worker_runtime_contract(
    worker_receipts: tuple[dict[str, object], ...] | list[dict[str, object]],
    *,
    expected_processes_per_worker: int,
    expected_block_size: int,
    pending_recipe_count: int,
) -> None:
    """Validate physical worker topology, including a legitimate hot-cache run."""

    if not worker_receipts:
        if pending_recipe_count:
            raise SystemExit("REDUCE_WORKER_RECEIPTS_MISSING")
        return
    worker_process_counts = {
        int(receipt.get("processes_per_worker", 0))
        for receipt in worker_receipts
    }
    worker_block_sizes = {
        int(receipt.get("block_size", 0)) for receipt in worker_receipts
    }
    if worker_process_counts != {expected_processes_per_worker}:
        raise SystemExit("REDUCE_WORKER_PROCESS_COUNT_MISMATCH")
    if worker_block_sizes != {expected_block_size}:
        raise SystemExit("REDUCE_WORKER_BLOCK_SIZE_MISMATCH")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--resolved-contract", type=Path, required=True)
    parser.add_argument("--resume-work-manifest", type=Path, required=True)
    parser.add_argument("--resume-root", type=Path, action="append", default=[])
    parser.add_argument("--run-plan", type=Path, required=True)
    parser.add_argument("--admission-token", required=True)
    parser.add_argument("--reduction-plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def _verify_group_reduction_inputs(
    input_root: Path,
    *,
    reduction_plan_path: Path,
    pending_recipe_count: int,
    expected_science_identity_sha256: str,
    expected_catalog_manifest_sha256: str,
    expected_work_manifest_sha256: str,
) -> tuple[list[dict[str, object]], str | None]:
    try:
        reduction_plan = json.loads(reduction_plan_path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit("OPTIMIZED_REDUCTION_PLAN_INVALID") from exc
    if not isinstance(reduction_plan, dict):
        raise SystemExit("OPTIMIZED_REDUCTION_PLAN_INVALID")
    plan_identity = {
        key: value
        for key, value in reduction_plan.items()
        if key != "content_sha256"
    }
    groups = reduction_plan.get("groups")
    selected_mode = reduction_plan.get("selected_mode")
    central_eligibility = reduction_plan.get("central_eligibility")
    selection_identity = (
        {
            key: value
            for key, value in central_eligibility.items()
            if key != "decision_sha256"
        }
        if isinstance(central_eligibility, dict)
        else None
    )
    maximum_groups = 1 if selected_mode == "central" else 15
    maximum_workers = 360 if selected_mode == "central" else 30
    if (
        reduction_plan.get("schema_version") != "1"
        or reduction_plan.get("document_type") != "reduction_plan"
        or canonical_sha256(plan_identity) != reduction_plan.get("content_sha256")
        or not isinstance(groups, list)
        or selected_mode not in {"central", "hierarchical"}
        or not isinstance(central_eligibility, dict)
        or central_eligibility.get("mode") != selected_mode
        or canonical_sha256(selection_identity)
        != central_eligibility.get("decision_sha256")
        or len(groups) > maximum_groups
        or reduction_plan.get("validation_opened") is not False
        or reduction_plan.get("locked_opened") is not False
    ):
        raise SystemExit("OPTIMIZED_REDUCTION_PLAN_INVALID")
    expected_artifacts: dict[str, dict[str, object]] = {}
    expected_worker_ids: set[int] = set()
    for expected_group_id, group in enumerate(groups):
        if (
            not isinstance(group, dict)
            or group.get("group_id") != expected_group_id
            or set(group) != {
                "group_id",
                "worker_ids",
                "checkpoint_artifacts",
                "checkpoint_artifact_pattern",
                "reduction_artifact",
            }
            or not isinstance(group.get("worker_ids"), list)
            or not 1 <= len(group["worker_ids"]) <= maximum_workers
            or any(
                not isinstance(worker_id, int)
                or worker_id in expected_worker_ids
                for worker_id in group["worker_ids"]
            )
            or not isinstance(group.get("reduction_artifact"), str)
            or group["reduction_artifact"] in expected_artifacts
        ):
            raise SystemExit("OPTIMIZED_REDUCTION_PLAN_INVALID")
        expected_worker_ids.update(group["worker_ids"])
        expected_artifacts[group["reduction_artifact"]] = group
    if bool(pending_recipe_count) != bool(groups):
        raise SystemExit("OPTIMIZED_REDUCTION_PLAN_COVERAGE_INVALID")
    if not groups:
        if input_root.exists() and any(input_root.iterdir()):
            raise SystemExit("OPTIMIZED_REDUCTION_INPUT_UNEXPECTED")
        return [], None
    nodes = reduction_plan.get("nodes")
    root_node = reduction_plan.get("root_node")
    node_hashes: dict[str, str] = {}
    node_ids_by_artifact: dict[str, str] = {}
    root_node_hash: str | None = None
    if not isinstance(nodes, list) or not isinstance(root_node, dict):
        raise SystemExit("OPTIMIZED_REDUCTION_NODE_PLAN_INVALID")
    if len(nodes) != len(expected_artifacts):
        raise SystemExit("OPTIMIZED_REDUCTION_NODE_PLAN_INVALID")
    for node in nodes:
        if not isinstance(node, dict):
            raise SystemExit("OPTIMIZED_REDUCTION_NODE_PLAN_INVALID")
        identity = {
            key: value
            for key, value in node.items()
            if key != "node_descriptor_sha256"
        }
        artifact = node.get("output_artifact")
        digest = node.get("node_descriptor_sha256")
        group = expected_artifacts.get(str(artifact))
        if (
            not isinstance(artifact, str)
            or artifact in node_hashes
            or group is None
            or node.get("node_id") != f"l00-g{group['group_id']:03d}"
            or node.get("level") != 0
            or node.get("group_id") != group["group_id"]
            or canonical_sha256(identity) != digest
            or node.get("campaign_id") != reduction_plan.get("campaign_id")
            or node.get("authority_id") != reduction_plan.get("authority_id")
            or node.get("science_sha256") != reduction_plan.get("science_sha256")
            or node.get("execution_plan_sha256")
            != reduction_plan.get("execution_plan_sha256")
            or not _safe_reduction_projection(
                node.get("resource_projection_p99")
            )
            or node.get("validation_opened") is not False
            or node.get("locked_opened") is not False
        ):
            raise SystemExit("OPTIMIZED_REDUCTION_NODE_PLAN_INVALID")
        node_hashes[artifact] = str(digest)
        node_ids_by_artifact[artifact] = str(node["node_id"])
    if set(node_hashes) != set(expected_artifacts):
        raise SystemExit("OPTIMIZED_REDUCTION_NODE_PLAN_INVALID")
    root_identity = {
        key: value
        for key, value in root_node.items()
        if key != "node_descriptor_sha256"
    }
    expected_root_children = [
        {
            "child_id": node_ids_by_artifact[artifact],
            "artifact_ids": [artifact],
            "descriptor_sha256": node_hashes[artifact],
        }
        for artifact in expected_artifacts
    ]
    if (
        canonical_sha256(root_identity)
        != root_node.get("node_descriptor_sha256")
        or root_node.get("node_id") != "l01-g000"
        or root_node.get("level") != 1
        or root_node.get("group_id") != 0
        or root_node.get("direct_children") != expected_root_children
        or root_node.get("output_artifact")
        != reduction_plan.get("final_evidence_artifact")
        or root_node.get("campaign_id") != reduction_plan.get("campaign_id")
        or root_node.get("authority_id") != reduction_plan.get("authority_id")
        or root_node.get("science_sha256") != reduction_plan.get("science_sha256")
        or root_node.get("execution_plan_sha256")
        != reduction_plan.get("execution_plan_sha256")
        or not _safe_reduction_projection(
            root_node.get("resource_projection_p99")
        )
        or root_node.get("validation_opened") is not False
        or root_node.get("locked_opened") is not False
    ):
        raise SystemExit("OPTIMIZED_REDUCTION_ROOT_PLAN_INVALID")
    root_node_hash = str(root_node["node_descriptor_sha256"])
    try:
        entries = list(input_root.iterdir())
    except OSError as exc:
        raise SystemExit("OPTIMIZED_REDUCTION_INPUT_MISSING") from exc
    if (
        {entry.name for entry in entries} != set(expected_artifacts)
        or any(not entry.is_dir() or entry.is_symlink() for entry in entries)
    ):
        raise SystemExit("OPTIMIZED_REDUCTION_INPUT_SET_INVALID")

    receipts: list[dict[str, object]] = []
    for artifact, group in expected_artifacts.items():
        root = input_root / artifact
        if any(path.is_symlink() for path in root.rglob("*")):
            raise SystemExit("OPTIMIZED_REDUCTION_INPUT_SET_INVALID")
        try:
            receipt = json.loads((root / "receipt.json").read_text("utf-8"))
            manifest = json.loads(
                (root / "reduction_group_manifest.json").read_text("utf-8")
            )
        except (OSError, ValueError) as exc:
            raise SystemExit("OPTIMIZED_REDUCTION_GROUP_INVALID") from exc
        if not isinstance(receipt, dict) or not isinstance(manifest, dict):
            raise SystemExit("OPTIMIZED_REDUCTION_GROUP_INVALID")
        receipt_identity = {
            key: value for key, value in receipt.items() if key != "receipt_sha256"
        }
        result_path = root / "results.parquet"
        if (
            receipt.get("reduction_group_id") != group["group_id"]
            or receipt.get("reduction_artifact") != artifact
            or receipt.get("worker_ids") != group["worker_ids"]
            or receipt.get("source_worker_receipt_count")
            != len(group["worker_ids"])
            or receipt.get("science_identity_sha256")
            != expected_science_identity_sha256
            or receipt.get("catalog_manifest_sha256")
            != expected_catalog_manifest_sha256
            or receipt.get("work_manifest_sha256")
            != expected_work_manifest_sha256
            or receipt.get("reduction_plan_sha256")
            != reduction_plan["content_sha256"]
            or receipt.get("node_descriptor_sha256")
            != node_hashes.get(artifact)
            or receipt.get("validation_opened") is not False
            or receipt.get("locked_opened") is not False
            or canonical_sha256(receipt_identity) != receipt.get("receipt_sha256")
            or not result_path.is_file()
            or receipt.get("result_sha256") != sha256_file(result_path)
            or manifest.get("group_id") != group["group_id"]
            or manifest.get("worker_ids") != group["worker_ids"]
            or manifest.get("result_sha256") != receipt.get("result_sha256")
            or manifest.get("reduction_plan_sha256")
            != reduction_plan["content_sha256"]
            or manifest.get("node_descriptor_sha256")
            != node_hashes.get(artifact)
            or manifest.get("checkpoint_receipt_manifest_sha256")
            != receipt.get("checkpoint_receipt_manifest_sha256")
            or manifest.get("validation_opened") is not False
            or manifest.get("locked_opened") is not False
        ):
            raise SystemExit("OPTIMIZED_REDUCTION_GROUP_INVALID")
        receipts.append(receipt)
    return receipts, root_node_hash


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
    worker_receipts, root_node_descriptor_sha256 = (
        _verify_group_reduction_inputs(
            args.input_root,
            reduction_plan_path=args.reduction_plan,
            pending_recipe_count=plan.pending_recipe_count,
            expected_science_identity_sha256=science_identity_sha256,
            expected_catalog_manifest_sha256=(
                resolved.science.catalog_manifest_sha256
            ),
            expected_work_manifest_sha256=work_manifest.manifest_sha256,
        )
    )
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
        default=0.0,
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
    _validate_worker_runtime_contract(
        worker_receipts,
        expected_processes_per_worker=plan.processes_per_worker,
        expected_block_size=plan.block_size,
        pending_recipe_count=plan.pending_recipe_count,
    )
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
    receipt_identity = {
        "schema_version": 1,
        "contract_sha256": plan.contract_sha256,
        "strategy_count": len(ordered),
        "selected_strategy_count": len(selected),
        "unique_position_count": unique_positions,
        "behavior_equivalence_hits": len(ordered) - unique_positions,
        "result_bytes": total_bytes,
        "result_bytes_per_recipe": total_bytes / len(ordered),
        "result_sha256": sha256_file(result_path),
        "worker_receipt_count": sum(
            int(receipt.get("source_worker_receipt_count", 1))
            for receipt in worker_receipts
        ),
        "checkpoint_receipt_count": sum(
            int(receipt.get("source_checkpoint_receipt_count", 1))
            for receipt in worker_receipts
        ),
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
        "root_node_descriptor_sha256": root_node_descriptor_sha256,
        "physical_recipe_evaluations": len(current_index.strategy_ids),
        "prior_result_cache_hits": len(resume_index.strategy_ids),
        "resume_source_result_rows": resume_index.physical_result_count,
        "resume_duplicate_result_rows": resume_index.duplicate_result_count,
        "top_10": top,
        "validation_opened": False,
        "locked_opened": False,
    }
    receipt = {
        **receipt_identity,
        "receipt_sha256": canonical_sha256(receipt_identity),
    }
    (args.output_dir / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
