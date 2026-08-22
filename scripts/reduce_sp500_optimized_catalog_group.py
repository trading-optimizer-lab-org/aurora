"""Reduce one sealed, bounded checkpoint group into one verified partial."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

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
_STAGE_NAMES = (
    "component_load",
    "composition",
    "objective",
    "serialization",
    "write",
)
_WALL_STAGE_NAMES = (
    "initialization",
    "evaluation",
    "write",
    "selected_verification",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--resolved-contract", type=Path, required=True)
    parser.add_argument("--resume-work-manifest", type=Path, required=True)
    parser.add_argument("--run-plan", type=Path, required=True)
    parser.add_argument("--admission-token", required=True)
    parser.add_argument("--checkpoint-policy", type=Path, required=True)
    parser.add_argument("--reduction-plan", type=Path, required=True)
    parser.add_argument("--recipe-assignments", type=Path, required=True)
    parser.add_argument("--group-id", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def _read_object(path: Path, error: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(error) from exc
    if not isinstance(value, dict):
        raise SystemExit(error)
    return value


def _verify_plan_document(path: Path, document_type: str) -> dict[str, Any]:
    document = _read_object(path, "REDUCTION_PLAN_DOCUMENT_INVALID")
    identity = {
        key: value for key, value in document.items() if key != "content_sha256"
    }
    if (
        document.get("schema_version") != "1"
        or document.get("document_type") != document_type
        or canonical_sha256(identity) != document.get("content_sha256")
    ):
        raise SystemExit("REDUCTION_PLAN_DOCUMENT_INVALID")
    return document


def _load_assignment_documents(path: Path) -> dict[int, dict[str, Any]]:
    assignments: dict[int, dict[str, Any]] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if (
                not infos
                or len(infos) > 360
                or sum(item.file_size for item in infos) > 16 * 1024 * 1024
            ):
                raise SystemExit("REDUCTION_ASSIGNMENT_BUNDLE_INVALID")
            for info in infos:
                member = Path(info.filename)
                if (
                    member.is_absolute()
                    or ".." in member.parts
                    or len(member.parts) != 2
                    or member.parts[0] != "recipe"
                    or not member.name.startswith("worker-")
                    or member.suffix != ".json"
                    or info.is_dir()
                    or info.file_size > 1024 * 1024
                    or info.compress_type != zipfile.ZIP_STORED
                ):
                    raise SystemExit("REDUCTION_ASSIGNMENT_BUNDLE_INVALID")
                try:
                    document = json.loads(archive.read(info).decode("utf-8"))
                except (KeyError, UnicodeDecodeError, ValueError) as exc:
                    raise SystemExit("REDUCTION_ASSIGNMENT_BUNDLE_INVALID") from exc
                if not isinstance(document, dict):
                    raise SystemExit("REDUCTION_ASSIGNMENT_BUNDLE_INVALID")
                worker_id = document.get("worker_id")
                strategy_ids = document.get("strategy_ids")
                if (
                    document.get("schema_version") != "1"
                    or not isinstance(worker_id, int)
                    or not 0 <= worker_id <= 359
                    or worker_id in assignments
                    or not isinstance(strategy_ids, list)
                    or not strategy_ids
                    or any(not isinstance(item, str) or not item for item in strategy_ids)
                    or len(strategy_ids) != len(set(strategy_ids))
                ):
                    raise SystemExit("REDUCTION_ASSIGNMENT_BUNDLE_INVALID")
                identity = {
                    "schema_version": "1",
                    "worker_id": worker_id,
                    "strategy_ids": strategy_ids,
                }
                if canonical_sha256(identity) != document.get(
                    "expected_strategy_manifest_sha256"
                ):
                    raise SystemExit("REDUCTION_ASSIGNMENT_BUNDLE_INVALID")
                assignments[worker_id] = document
    except (OSError, zipfile.BadZipFile) as exc:
        raise SystemExit("REDUCTION_ASSIGNMENT_BUNDLE_INVALID") from exc
    return assignments


def _group_row(plan: dict[str, Any], group_id: int) -> dict[str, Any]:
    groups = plan.get("groups")
    if not isinstance(groups, list) or not 1 <= len(groups) <= 15:
        raise SystemExit("REDUCTION_GROUP_PLAN_INVALID")
    matches = [
        item
        for item in groups
        if isinstance(item, dict) and item.get("group_id") == group_id
    ]
    if len(matches) != 1:
        raise SystemExit("REDUCTION_GROUP_PLAN_INVALID")
    row = matches[0]
    if set(row) != {
        "group_id",
        "worker_ids",
        "checkpoint_artifacts",
        "checkpoint_artifact_pattern",
        "reduction_artifact",
    }:
        raise SystemExit("REDUCTION_GROUP_PLAN_INVALID")
    worker_ids = row.get("worker_ids")
    artifacts = row.get("checkpoint_artifacts")
    if (
        not isinstance(worker_ids, list)
        or not 1 <= len(worker_ids) <= 24
        or worker_ids != sorted(worker_ids)
        or len(worker_ids) != len(set(worker_ids))
        or not isinstance(artifacts, list)
        or not artifacts
        or any(not isinstance(item, str) or not item for item in artifacts)
        or len(artifacts) != len(set(artifacts))
    ):
        raise SystemExit("REDUCTION_GROUP_PLAN_INVALID")
    return row


def _checkpoint_rows(
    policy: dict[str, Any],
    *,
    worker_ids: list[int],
) -> dict[int, dict[str, Any]]:
    rows = policy.get("workers")
    if not isinstance(rows, list):
        raise SystemExit("REDUCTION_CHECKPOINT_POLICY_INVALID")
    by_worker = {
        item.get("worker_id"): item
        for item in rows
        if isinstance(item, dict) and isinstance(item.get("worker_id"), int)
    }
    if len(by_worker) != len(rows) or not set(worker_ids).issubset(by_worker):
        raise SystemExit("REDUCTION_CHECKPOINT_POLICY_INVALID")
    selected: dict[int, dict[str, Any]] = {}
    for worker_id in worker_ids:
        row = by_worker[worker_id]
        if set(row) != {
            "worker_id",
            "checkpoint_slot_count",
            "checkpoint_slot_artifacts",
            "checkpoint_slot_manifest_sha256",
        }:
            raise SystemExit("REDUCTION_CHECKPOINT_POLICY_INVALID")
        slot_count = row.get("checkpoint_slot_count")
        artifacts = row.get("checkpoint_slot_artifacts")
        if (
            slot_count not in {1, 2, 4, 8}
            or not isinstance(artifacts, list)
            or len(artifacts) != 8
            or len(artifacts) != len(set(artifacts))
            or canonical_sha256(
                {
                    "schema_version": "1",
                    "artifacts": artifacts,
                    "slot_count": slot_count,
                }
            )
            != row.get("checkpoint_slot_manifest_sha256")
        ):
            raise SystemExit("REDUCTION_CHECKPOINT_POLICY_INVALID")
        selected[worker_id] = row
    return selected


def _checkpoint_receipts(
    input_root: Path,
    *,
    worker_ids: list[int],
    checkpoint_rows: dict[int, dict[str, Any]],
    assignments: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    expected_artifacts = {
        artifact
        for worker_id in worker_ids
        for artifact in checkpoint_rows[worker_id]["checkpoint_slot_artifacts"][
            : checkpoint_rows[worker_id]["checkpoint_slot_count"]
        ]
    }
    try:
        entries = list(input_root.iterdir())
    except OSError as exc:
        raise SystemExit("REDUCTION_CHECKPOINT_INPUT_INVALID") from exc
    if (
        {item.name for item in entries} != expected_artifacts
        or any(not item.is_dir() or item.is_symlink() for item in entries)
        or any(path.is_symlink() for path in entries for path in path.rglob("*"))
    ):
        raise SystemExit("REDUCTION_CHECKPOINT_INPUT_INVALID")

    receipts: list[dict[str, Any]] = []
    receipt_manifest: list[dict[str, Any]] = []
    for worker_id in worker_ids:
        policy = checkpoint_rows[worker_id]
        slot_count = int(policy["checkpoint_slot_count"])
        strategy_ids = list(assignments[worker_id]["strategy_ids"])
        previous_receipt_sha256 = "0" * 64
        for slot_index in range(1, slot_count + 1):
            artifact = policy["checkpoint_slot_artifacts"][slot_index - 1]
            root = input_root / artifact
            required = {
                "results.parquet",
                "receipt.json",
                "shard_attempt_manifest.json",
                "checkpoint_chain_manifest.json",
            }
            if not required.issubset(
                {path.name for path in root.iterdir() if path.is_file()}
            ):
                raise SystemExit("REDUCTION_CHECKPOINT_CONTENT_MISSING")
            result_path = root / "results.parquet"
            receipt_path = root / "receipt.json"
            receipt = _read_object(
                receipt_path,
                "REDUCTION_CHECKPOINT_RECEIPT_INVALID",
            )
            attempt = _read_object(
                root / "shard_attempt_manifest.json",
                "REDUCTION_CHECKPOINT_ATTEMPT_INVALID",
            )
            chain = _read_object(
                root / "checkpoint_chain_manifest.json",
                "REDUCTION_CHECKPOINT_CHAIN_INVALID",
            )
            result_sha256 = sha256_file(result_path)
            receipt_sha256 = sha256_file(receipt_path)
            start = (len(strategy_ids) * (slot_index - 1)) // slot_count
            stop = (len(strategy_ids) * slot_index) // slot_count
            expected_strategy_ids = strategy_ids[start:stop]
            table_ids = [
                str(value)
                for value in pq.read_table(
                    result_path,
                    columns=["strategy_id"],
                ).column("strategy_id").to_pylist()
            ]
            if (
                receipt.get("shard_index") != worker_id
                or receipt.get("checkpoint_slot_index") != slot_index
                or receipt.get("checkpoint_slot_count") != slot_count
                or receipt.get("previous_checkpoint_receipt_sha256")
                != previous_receipt_sha256
                or receipt.get("result_sha256") != result_sha256
                or receipt.get("strategy_count") != len(expected_strategy_ids)
                or receipt.get("validation_opened") is not False
                or receipt.get("locked_opened") is not False
                or table_ids != expected_strategy_ids
                or attempt.get("worker_id") != worker_id
                or attempt.get("checkpoint_slot_index") != slot_index
                or attempt.get("checkpoint_slot_count") != slot_count
                or attempt.get("strategy_ids") != expected_strategy_ids
                or attempt.get("result_sha256") != result_sha256
                or attempt.get("receipt_sha256") != receipt_sha256
                or attempt.get("previous_checkpoint_receipt_sha256")
                != previous_receipt_sha256
                or chain.get("worker_id") != worker_id
                or chain.get("slot_index") != slot_index
                or chain.get("slot_count") != slot_count
                or chain.get("previous_receipt_sha256")
                != previous_receipt_sha256
                or chain.get("current_receipt_sha256") != receipt_sha256
                or chain.get("completed_strategy_ids") != expected_strategy_ids
            ):
                raise SystemExit("REDUCTION_CHECKPOINT_CHAIN_INVALID")
            chain_identity = {
                key: value for key, value in chain.items() if key != "chain_sha256"
            }
            if canonical_sha256(chain_identity) != chain.get("chain_sha256"):
                raise SystemExit("REDUCTION_CHECKPOINT_CHAIN_INVALID")
            receipts.append(receipt)
            receipt_manifest.append(
                {
                    "artifact": artifact,
                    "worker_id": worker_id,
                    "slot_index": slot_index,
                    "receipt_sha256": receipt_sha256,
                    "result_sha256": result_sha256,
                }
            )
            previous_receipt_sha256 = receipt_sha256
    return receipts, receipt_manifest


def _sum_stages(
    receipts: list[dict[str, Any]],
    field: str,
    names: tuple[str, ...],
) -> dict[str, float]:
    return {
        name: sum(
            float(
                receipt.get(field, {}).get(name, 0.0)
                if isinstance(receipt.get(field), dict)
                else 0.0
            )
            for receipt in receipts
        )
        for name in names
    }


def main() -> int:
    args = _parser().parse_args()
    run_plan = verify_catalog_plan_token(
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
        resolved.contract_sha256 != run_plan.contract_sha256
        or canonical_sha256(work_identity) != work_manifest.manifest_sha256
        or work_manifest.manifest_sha256 != run_plan.work_manifest_sha256
    ):
        raise SystemExit("REDUCTION_GROUP_BINDING_INVALID")
    reduction_plan = _verify_plan_document(
        args.reduction_plan,
        "reduction_plan",
    )
    checkpoint_policy = _verify_plan_document(
        args.checkpoint_policy,
        "checkpoint_policy",
    )
    binding_fields = (
        "campaign_id",
        "authority_id",
        "science_sha256",
        "execution_plan_sha256",
    )
    if any(
        reduction_plan.get(field) != checkpoint_policy.get(field)
        for field in binding_fields
    ):
        raise SystemExit("REDUCTION_GROUP_BINDING_INVALID")
    if (
        reduction_plan.get("validation_opened") is not False
        or reduction_plan.get("locked_opened") is not False
    ):
        raise SystemExit("REDUCTION_GROUP_BOUNDARY_INVALID")

    group = _group_row(reduction_plan, args.group_id)
    worker_ids = list(group["worker_ids"])
    assignments = _load_assignment_documents(args.recipe_assignments)
    if not set(worker_ids).issubset(assignments):
        raise SystemExit("REDUCTION_ASSIGNMENT_COVERAGE_INVALID")
    checkpoint_rows = _checkpoint_rows(
        checkpoint_policy,
        worker_ids=worker_ids,
    )
    expected_artifacts = [
        artifact
        for worker_id in worker_ids
        for artifact in checkpoint_rows[worker_id]["checkpoint_slot_artifacts"][
            : checkpoint_rows[worker_id]["checkpoint_slot_count"]
        ]
    ]
    if expected_artifacts != group["checkpoint_artifacts"]:
        raise SystemExit("REDUCTION_CHECKPOINT_COVERAGE_INVALID")

    receipts, receipt_manifest = _checkpoint_receipts(
        args.input_root,
        worker_ids=worker_ids,
        checkpoint_rows=checkpoint_rows,
        assignments=assignments,
    )
    science_identity_sha256 = canonical_sha256(resolved.science)
    index = load_resume_index(
        (args.input_root,),
        expected_science_identity_sha256=science_identity_sha256,
        expected_catalog_manifest_sha256=(
            resolved.science.catalog_manifest_sha256
        ),
    )
    expected_strategy_ids = [
        strategy_id
        for worker_id in worker_ids
        for strategy_id in assignments[worker_id]["strategy_ids"]
    ]
    if (
        len(expected_strategy_ids) != len(set(expected_strategy_ids))
        or set(index.strategy_ids) != set(expected_strategy_ids)
        or index.physical_result_count != len(expected_strategy_ids)
        or index.duplicate_result_count != 0
    ):
        raise SystemExit("REDUCTION_GROUP_RESULT_SET_INVALID")

    by_id = {item.strategy_id: item for item in index.results}
    ordered = [
        {
            "strategy_id": strategy_id,
            "result_json": by_id[strategy_id].result_json,
        }
        for strategy_id in sorted(expected_strategy_ids)
    ]
    args.output_dir.mkdir(parents=True, exist_ok=False)
    result_path = args.output_dir / "results.parquet"
    pq.write_table(
        pa.Table.from_pylist(ordered, schema=_RESULT_SCHEMA),
        result_path,
        compression="zstd",
        use_dictionary=True,
        row_group_size=4096,
    )

    selected_by_key: dict[str, dict[str, Any]] = {}
    for path in sorted(args.input_root.rglob("selected_results.jsonl")):
        for line in path.read_text("utf-8").splitlines():
            if not line:
                continue
            row = json.loads(line)
            key = str(row["source_strategy_key"])
            previous = selected_by_key.get(key)
            if previous is not None and scientific_result_sha256(
                dict(previous["result"])
            ) != scientific_result_sha256(dict(row["result"])):
                raise SystemExit("REDUCTION_GROUP_SELECTED_RESULT_CONFLICT")
            selected_by_key[key] = row
    if selected_by_key:
        (args.output_dir / "selected_results.jsonl").write_text(
            "".join(
                json.dumps(
                    selected_by_key[key],
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
                for key in sorted(selected_by_key)
            ),
            "utf-8",
        )

    process_counts = {int(item.get("processes_per_worker", 0)) for item in receipts}
    block_sizes = {int(item.get("block_size", 0)) for item in receipts}
    if len(process_counts) != 1 or len(block_sizes) != 1:
        raise SystemExit("REDUCTION_GROUP_WORKER_TOPOLOGY_INVALID")
    available_memory = [
        int(item.get("available_memory_bytes", 0))
        for item in receipts
        if int(item.get("available_memory_bytes", 0)) > 0
    ]
    group_manifest = {
        "schema_version": "1",
        "group_id": args.group_id,
        "worker_ids": worker_ids,
        "checkpoint_receipts": receipt_manifest,
        "checkpoint_receipt_manifest_sha256": canonical_sha256(
            receipt_manifest
        ),
        "result_sha256": sha256_file(result_path),
        "reduction_plan_sha256": reduction_plan["content_sha256"],
        "validation_opened": False,
        "locked_opened": False,
    }
    (args.output_dir / "reduction_group_manifest.json").write_text(
        json.dumps(group_manifest, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    receipt_identity = {
        "schema_version": "1",
        "reduction_group_id": args.group_id,
        "reduction_artifact": group["reduction_artifact"],
        "worker_ids": worker_ids,
        "source_worker_receipt_count": len(worker_ids),
        "source_checkpoint_receipt_count": len(receipts),
        "strategy_count": len(ordered),
        "selected_strategy_count": len(selected_by_key),
        "result_bytes": result_path.stat().st_size,
        "result_bytes_per_recipe": result_path.stat().st_size / len(ordered),
        "result_sha256": sha256_file(result_path),
        "science_identity_sha256": science_identity_sha256,
        "catalog_manifest_sha256": resolved.science.catalog_manifest_sha256,
        "work_manifest_sha256": work_manifest.manifest_sha256,
        "reduction_plan_sha256": reduction_plan["content_sha256"],
        "checkpoint_receipt_manifest_sha256": group_manifest[
            "checkpoint_receipt_manifest_sha256"
        ],
        "processes_per_worker": next(iter(process_counts)),
        "block_size": next(iter(block_sizes)),
        "scientific_stage_seconds": _sum_stages(
            receipts,
            "scientific_stage_seconds",
            _STAGE_NAMES,
        ),
        "scientific_wall_stage_seconds": _sum_stages(
            receipts,
            "scientific_wall_stage_seconds",
            _WALL_STAGE_NAMES,
        ),
        "scientific_attribution_difference_ratio": max(
            (
                float(
                    item.get("scientific_attribution_difference_ratio", 1.0)
                )
                for item in receipts
            ),
            default=0.0,
        ),
        "cpu_seconds": sum(float(item.get("cpu_seconds", 0.0)) for item in receipts),
        "peak_memory_bytes": max(
            (int(item.get("peak_memory_bytes", 0)) for item in receipts),
            default=0,
        ),
        "available_memory_bytes": min(available_memory, default=0),
        "peak_memory_fraction": max(
            (float(item.get("peak_memory_fraction", 0.0)) for item in receipts),
            default=0.0,
        ),
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
