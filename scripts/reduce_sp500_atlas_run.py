"""Verify and join every static Atlas shard without hiding missing results."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable

from aurora.infra.github_performance.contracts import canonical_sha256
from aurora.infra.sp500_megarun.atlas_execution_contract import load_plan
from aurora.infra.sp500_megarun.catalog_atlas_objective import pareto_frontier


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _receipt_paths(root: Path) -> list[Path]:
    return sorted(Path(root).rglob("worker_receipt.json"))


def _find_result_path(receipt_path: Path) -> Path:
    path = receipt_path.parent / "results.jsonl"
    if not path.is_file():
        raise ValueError(f"ATLAS_REDUCER_RESULTS_MISSING:{receipt_path.parent.name}")
    return path


def _verify_row(row: dict[str, object], *, plan_sha256: str, shard_index: int) -> int:
    if row.get("plan_sha256") != plan_sha256:
        raise ValueError("ATLAS_REDUCER_ROW_PLAN_MISMATCH")
    if int(row.get("shard_index", -1)) != shard_index:
        raise ValueError("ATLAS_REDUCER_ROW_SHARD_MISMATCH")
    if row.get("validation_opened") is not False or row.get("locked_opened") is not False:
        raise ValueError("ATLAS_REDUCER_ROW_BOUNDARY_OPEN")
    supplied = row.get("result_sha256")
    identity = {key: value for key, value in row.items() if key != "result_sha256"}
    if supplied != canonical_sha256(identity):
        raise ValueError("ATLAS_REDUCER_ROW_HASH_INVALID")
    return int(row["ordinal"])


def _read_rows(path: Path) -> Iterable[dict[str, object]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"ATLAS_REDUCER_ROW_OBJECT_REQUIRED:{line_number}")
            yield row


def reduce_atlas_run(
    *,
    plan_path: Path,
    partitions_root: Path,
    output_dir: Path,
) -> dict[str, object]:
    plan = load_plan(Path(plan_path))
    receipts = _receipt_paths(Path(partitions_root))
    by_index: dict[int, Path] = {}
    for receipt_path in receipts:
        receipt = json.loads(receipt_path.read_text("utf-8"))
        index = int(receipt.get("shard_index", -1))
        if index in by_index:
            raise ValueError("ATLAS_REDUCER_DUPLICATE_SHARD_RECEIPT")
        by_index[index] = receipt_path
    if set(by_index) != set(range(plan.total_shards)):
        missing = sorted(set(range(plan.total_shards)) - set(by_index))
        extra = sorted(set(by_index) - set(range(plan.total_shards)))
        raise ValueError(f"ATLAS_REDUCER_SHARD_COVERAGE_INVALID:missing={missing[:5]}:extra={extra[:5]}")

    rows: list[dict[str, object]] = []
    seen: set[int] = set()
    for shard in plan.shards:
        receipt_path = by_index[shard.shard_index]
        receipt = json.loads(receipt_path.read_text("utf-8"))
        expected = {
            "plan_sha256": plan.plan_sha256,
            "catalog_manifest_sha256": plan.catalog_manifest_sha256,
            "shard_index": shard.shard_index,
            "start_ordinal": shard.start_ordinal,
            "stop_ordinal": shard.stop_ordinal,
            "expected_recipe_count": shard.expected_recipe_count,
            "actual_recipe_count": shard.expected_recipe_count,
            "validation_opened": False,
            "locked_opened": False,
        }
        for key, value in expected.items():
            if receipt.get(key) != value:
                raise ValueError(f"ATLAS_REDUCER_RECEIPT_MISMATCH:{shard.shard_index}:{key}")
        result_path = _find_result_path(receipt_path)
        if _sha256_file(result_path) != receipt.get("result_sha256"):
            raise ValueError(f"ATLAS_REDUCER_RESULT_FILE_HASH_INVALID:{shard.shard_index}")
        shard_rows: list[dict[str, object]] = []
        for row in _read_rows(result_path):
            ordinal = _verify_row(row, plan_sha256=plan.plan_sha256, shard_index=shard.shard_index)
            if ordinal < shard.start_ordinal or ordinal >= shard.stop_ordinal:
                raise ValueError(f"ATLAS_REDUCER_ORDINAL_OUT_OF_SHARD:{ordinal}")
            if ordinal in seen:
                raise ValueError(f"ATLAS_REDUCER_DUPLICATE_ORDINAL:{ordinal}")
            seen.add(ordinal)
            shard_rows.append(row)
        if len(shard_rows) != shard.expected_recipe_count:
            raise ValueError(f"ATLAS_REDUCER_ROW_COUNT_INVALID:{shard.shard_index}")
        rows.extend(shard_rows)

    if len(rows) != plan.requested_recipe_count or seen != set(range(plan.ordinal_start, plan.ordinal_stop)):
        raise ValueError("ATLAS_REDUCER_GLOBAL_COVERAGE_INVALID")
    rows.sort(key=lambda row: int(row["ordinal"]))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    results_path = output / "results.jsonl"
    with results_path.open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")
    frontier = pareto_frontier(rows)
    frontier_path = output / "pareto_frontier.jsonl"
    frontier_path.write_text(
        "".join(json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n" for row in frontier),
        encoding="utf-8",
    )
    summary = {
        "schema_version": 1,
        "accepted": True,
        "plan_sha256": plan.plan_sha256,
        "catalog_manifest_sha256": plan.catalog_manifest_sha256,
        "requested_recipe_count": plan.requested_recipe_count,
        "verified_recipe_count": len(rows),
        "verified_shard_count": len(by_index),
        "pareto_recipe_count": len(frontier),
        "results_sha256": _sha256_file(results_path),
        "frontier_sha256": _sha256_file(frontier_path),
        "validation_opened": False,
        "locked_opened": False,
    }
    (output / "reduction_receipt.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--partitions-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    # Keep argparse's ``--plan`` spelling separate from the reducer API's
    # explicit ``plan_path`` parameter.  Passing ``vars(args)`` directly would
    # make the final join fail only after every worker had finished.
    print(
        json.dumps(
            reduce_atlas_run(
                plan_path=args.plan,
                partitions_root=args.partitions_root,
                output_dir=args.output_dir,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
